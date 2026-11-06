"""Reproduce MCP 1.30's late-response teardown race without timing sleeps."""
import asyncio
import json

import anyio
from anyio.streams.memory import MemoryObjectSendStream
import mcp.client.stdio as sdk
from mcp import ClientSession, StdioServerParameters
import pytest

from agrireach.mcp_transport import stdio_client


def _leaves(exc):
    if isinstance(exc, BaseExceptionGroup):
        return [leaf for child in exc.exceptions for leaf in _leaves(child)]
    return [exc]


def _process(monkeypatch, *, fail_active=False):
    stdin_closed, delivered, active = anyio.Event(), anyio.Event(), anyio.Event()
    sends = []
    original_send = MemoryObjectSendStream.send

    async def observe(self, item):
        if getattr(getattr(item, "message", None), "root", None) is not None:
            sends.append(type(item.message.root).__name__)
            try:
                return await original_send(self, item)
            finally:
                delivered.set()
        return await original_send(self, item)

    monkeypatch.setattr(MemoryObjectSendStream, "send", observe)

    class Stdout:
        done = False

        async def receive(self, max_bytes=65536):
            if fail_active:
                await active.wait()
                raise OSError("synthetic active transport failure")
            await stdin_closed.wait()
            if self.done:
                raise anyio.EndOfStream
            self.done = True
            return (json.dumps({"jsonrpc": "2.0", "id": 1, "result": {}}) + "\n").encode()

    class Stdin:
        async def aclose(self):
            stdin_closed.set()

    class Process:
        stdin, stdout = Stdin(), Stdout()
        closed = False

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            self.closed = True
            return False

        async def wait(self):
            if not fail_active:
                # Force the SDK reader to attempt delivery before cleanup ends.
                await delivered.wait()
            return 0

    process = Process()

    async def spawn(**kwargs):
        return process

    monkeypatch.setattr(sdk, "_create_platform_compatible_process", spawn)
    return process, sends, active


@pytest.mark.parametrize("failure", [None, TimeoutError("request failed"), asyncio.CancelledError()])
def test_late_response_does_not_break_shutdown_or_hide_request_failure(monkeypatch, failure):
    async def scenario():
        process, sends, _ = _process(monkeypatch)
        caught = None
        try:
            with anyio.fail_after(5):  # deadlock watchdog, not application waiting
                async with stdio_client(StdioServerParameters(command="synthetic")) as (read, write):
                    async with ClientSession(read, write):
                        await anyio.lowlevel.checkpoint()
                        if failure is not None:
                            raise failure
        except BaseException as exc:
            caught = exc
        assert process.closed
        assert sends == ["JSONRPCResponse"]
        if failure is None:
            assert caught is None, caught
        else:
            assert _leaves(caught) == [failure], caught

    asyncio.run(scenario())


def test_active_transport_error_still_propagates(monkeypatch):
    async def scenario():
        process, _, active = _process(monkeypatch, fail_active=True)
        with pytest.raises(ExceptionGroup) as caught:
            with anyio.fail_after(5):
                async with stdio_client(StdioServerParameters(command="synthetic")) as (read, write):
                    async with ClientSession(read, write):
                        active.set()
                        await anyio.sleep_forever()
        assert process.closed
        errors = _leaves(caught.value)
        assert len(errors) == 1
        assert isinstance(errors[0], OSError)
        assert str(errors[0]) == "synthetic active transport failure"

    asyncio.run(scenario())
