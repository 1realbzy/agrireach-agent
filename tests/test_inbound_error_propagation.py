"""Ensure durable workers see exceptions rather than treating them as empty success."""
import asyncio
import pytest
from agrireach.channels import sms, whatsapp, service


@pytest.mark.parametrize("adapter,config,item", [
    (sms, sms.Config("sandbox", "unused", "x" * 24),
     {"message_id": "s1", "from": "+233000000001", "text": "maize"}),
    (whatsapp, whatsapp.Config("verify", "secret", "unused", "123"),
     {"message_id": "w1", "from": "233000000001", "type": "text", "text": "maize"}),
])
def test_processing_exception_reaches_durable_worker(monkeypatch, tmp_path, adapter, config, item):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "inbound.sqlite"))

    async def broken(*args, **kwargs):
        raise RuntimeError("simulated processing failure")

    monkeypatch.setattr(service, "handle_inbound", broken)
    with pytest.raises(RuntimeError, match="simulated processing failure"):
        asyncio.run(adapter.process(config, [item], channel=object()))
