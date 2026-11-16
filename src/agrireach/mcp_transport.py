"""Keep MCP 1.30's stdout consumer alive until its transport finishes closing."""
from contextlib import asynccontextmanager

import anyio
from mcp.client.stdio import stdio_client as _sdk_stdio_client


async def _drain_shutdown(read):
    try:
        async for _ in read:
            pass
    except anyio.ClosedResourceError:
        # The SDK closes its receive endpoint when transport cleanup finishes.
        pass


@asynccontextmanager
async def stdio_client(server):
    """Use the SDK transport, with a separate receive handle for ClientSession.

    ClientSession closes its handle before the SDK closes subprocess stdin. A
    late response would otherwise hit a closed receiver in the SDK stdout task.
    Drain only after the session exits; never retry a request or hide its error.
    The SDK retains responsibility for bounded process termination and cleanup.
    """
    async with anyio.create_task_group() as drains:
        async with _sdk_stdio_client(server) as (read, write):
            try:
                async with read.clone() as session_read:
                    yield session_read, write
            finally:
                drains.start_soon(_drain_shutdown, read)
