"""Durable worker failure injection: never acknowledge a failed case as completed."""
import asyncio

import pytest

from agrireach import db
from agrireach.channels import service, sms, whatsapp


@pytest.mark.parametrize("adapter,cfg,channel,sender,item", [
    (sms, sms.Config("sandbox", "unused", "x" * 24), "sms", "+233000000001",
     {"message_id": "s1", "from": "+233000000001", "text": "maize"}),
    (whatsapp, whatsapp.Config("verify", "secret", "unused", "123"), "whatsapp", "233000000001",
     {"message_id": "w1", "from": "233000000001", "type": "text", "text": "maize"}),
])
def test_durable_worker_failure_is_uncertain_and_not_replayed(
    monkeypatch, tmp_path, adapter, cfg, channel, sender, item
):
    monkeypatch.setenv("DATABASE_URL", "sqlite:///" + str(tmp_path / "failure.sqlite"))
    con = db.connect()
    assert db.enqueue_inbound(con, channel, item["message_id"], item, sender_id=sender)
    con.close()

    async def broken(*args, **kwargs):
        raise RuntimeError("simulated crash during processing")

    monkeypatch.setattr(service, "handle_inbound", broken)
    with pytest.raises(RuntimeError, match="simulated crash"):
        asyncio.run(adapter.process_durable(cfg, item))

    con = db.connect()
    row = con.execute(
        "SELECT state,attempt_count,outcome_reason,lease_id FROM channel_inbox WHERE channel=? AND message_id=?",
        (channel, item["message_id"]),
    ).fetchone()
    assert row["state"] == "uncertain"
    assert row["attempt_count"] == 1
    assert row["lease_id"] is None
    assert "interrupted" in row["outcome_reason"]
    assert db.claim_inbound(con, channel, item["message_id"]) is None
    con.close()
