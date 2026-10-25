"""Run 5 (first attempt): two SMS arrived together; one run failed with ExceptionGroup, its case reached the officer
queue, but no contact was saved and no acknowledgement was sent, so that farmer could never get the reply.

Root cause (reproduced here): model calls are synchronous (OpenAI client) and ran on the event loop inside the async
graph nodes. While one farmer's draft/judge/SMS call blocked the loop, another farmer's MCP tool call
(agent.Tools.call, asyncio.wait_for with MCP_TIMEOUT) timed out although the MCP server had already saved the case;
the TimeoutError came out of stdio_client's anyio TaskGroup as an ExceptionGroup, and service._file never reached
save_contact or the acknowledgement. Stubbed (instant) model calls never block the loop, which is why QA's 12-farmer
run on ccc609a didn't reproduce it.

Fix: model calls run in worker threads (asyncio.to_thread); a channel case is filed as 'draft' and the service saves
the contact and moves it to pending_review in one transaction, so a failed run never leaves a queued case without
its contact; the farmer is asked to resend, every sub-exception is logged with its traceback, and the error is
re-raised (not swallowed). Here: MCP_TIMEOUT=1 s and model calls that block for longer and fail at random."""
import asyncio
import json
import random
import time

import pytest

from agrireach import agent, db, farmer_reply as fr, judge, llm
from agrireach.channels import service, simulator
from agrireach.channels.base import InboundMessage

QS = ["Fall armyworm is eating my maize in Tamale. What should I do?",
      "When should I plant maize in Tamale?",
      "Weevils in my stored maize in Tamale. How should I store it?",
      "When should I harvest soybean in Tamale?"]
DRAFT = "Scout the maize field at least once a week [APNI-SARI-2023-MAIZE:p18-scouting]."


@pytest.fixture
def slow_flaky_models(monkeypatch):
    monkeypatch.setenv("MCP_TIMEOUT", "1")
    monkeypatch.setattr(llm, "mode", lambda: "llm")
    rnd = random.Random(7)

    def draft(*a, **k):
        time.sleep(1.5)  # a live model call: synchronous and longer than MCP_TIMEOUT
        if rnd.random() < 0.4:
            raise RuntimeError("502 from the model provider")
        return DRAFT, "llm:fake"

    def rewrite(*a, **k):
        time.sleep(1.2)
        if rnd.random() < 0.5:
            raise TimeoutError("model timed out")
        return "Walk through your maize field at least once a week.", "llm:fake"

    def judge_call(user):
        time.sleep(0.4)
        if rnd.random() < 0.3:
            return '{"verdicts": [{"verdict": "supported"}]}'  # malformed: no "n"
        n = user.count(". SENTENCE: ")
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(n)]})
    monkeypatch.setattr(llm, "draft", draft)
    monkeypatch.setattr(fr, "_llm_rewrite", rewrite)
    monkeypatch.setattr(judge, "_call", judge_call)


def run_together(n):
    ch = simulator.SimulatorChannel()

    async def go():
        msgs = [InboundMessage("simulator", f"sim:farmer-{i}", text=QS[i % len(QS)]) for i in range(n)]
        return await asyncio.gather(*[service.handle_inbound(m, channel=ch) for m in msgs], return_exceptions=True)
    return asyncio.run(go()), ch


def assert_no_half_saved_case():
    con = db.connect()
    for row in con.execute("SELECT id, status FROM cases"):
        if row["status"] in ("pending_review", "not_delivered"):
            assert db.get_contact(con, row["id"]) is not None, f"case {row['id']} queued without its contact"


def test_concurrent_farmers_with_slow_flaky_models_all_get_contact_and_ack(slow_flaky_models):
    res, ch = run_together(4)
    errors = [r for r in res if isinstance(r, BaseException)]
    assert not errors, errors
    con = db.connect()
    for i, r in enumerate(res):
        assert r["status"] == "pending_review" and r["sent"]["ok"], r
        contact = db.get_contact(con, r["case_id"])
        assert contact is not None and contact["sender_id"] == f"sim:farmer-{i}"
        assert db.get_case(con, r["case_id"])["status"] == "pending_review"
        assert [m["text"] for m in ch.messages(f"sim:farmer-{i}")] == [service.ACK]
    assert_no_half_saved_case()


def test_a_run_that_fails_after_the_case_is_saved_never_queues_it(monkeypatch):
    real = agent.Tools.call

    async def fails_after_saving(self, name, args):
        out = await real(self, name, args)
        if name == "create_or_update_case" and args.get("farmer_draft"):
            raise TimeoutError("MCP call timed out after the server saved the case")  # the run 5 failure
        return out
    monkeypatch.setattr(agent.Tools, "call", fails_after_saving)
    res, ch = run_together(2)
    assert all(isinstance(r, BaseException) for r in res), res  # not swallowed
    con = db.connect()
    assert con.execute("SELECT COUNT(*) FROM cases WHERE status='pending_review'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM channel_contacts").fetchone()[0] == 0
    for i in range(2):
        assert [m["text"] for m in ch.messages(f"sim:farmer-{i}")] == [service.RESEND]
    errs = [dict(r) for r in con.execute("SELECT * FROM tool_log WHERE tool='inbound_error'")]
    assert len(errs) == 2 and all("TimeoutError" in e["result_summary"] and "Traceback" in e["result_summary"]
                                  and "fails_after_saving" in e["result_summary"] for e in errs), errs
    assert_no_half_saved_case()


def test_every_sub_exception_of_a_group_is_logged_with_its_traceback():
    def raises(e):
        try:
            raise e
        except BaseException as x:
            return x
    group = ExceptionGroup("unhandled errors in a TaskGroup", [
        raises(TimeoutError("first")), ExceptionGroup("inner", [raises(KeyError("second"))])])
    con = db.connect()
    service.log_failure(con, InboundMessage("sms", "+233200000001", text="q"), group)
    rows = [dict(r) for r in con.execute("SELECT * FROM tool_log WHERE tool='inbound_error' ORDER BY id")]
    assert [json.loads(r["args"])["exception"] for r in rows] == ["TimeoutError", "KeyError"]
    assert all("Traceback" in r["result_summary"] and "raises" in r["result_summary"] for r in rows)
    assert "+233200000001" not in json.dumps(rows)  # the number stays masked
