"""Stage B: durable model-usage records for assess, failures, and app-level draft retries.

One record is one application call. The OpenAI client may retry inside that call;
those HTTP tries are not separate records because the client does not report them.
"""
import asyncio
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from agrireach import agent, db, judge, knowledge, llm
from agrireach.api import app

SECRET_QUESTION = "SECRET-QUESTION-WHEN-SHOULD-I-PLANT"
SECRET_TEXT = "SECRET-FARMER-TEXT harvest in the morning when pods are brown"


def officer():
    return {"Authorization": f"Bearer {db.add_officer(db.connect(), 'Ama Mensah')}"}


def response(cost=0.0002, prompt=11, completion=4):
    return SimpleNamespace(
        usage=SimpleNamespace(prompt_tokens=prompt, completion_tokens=completion, cost=cost),
        choices=[SimpleNamespace(message=SimpleNamespace(content="{}"))],
    )


class FakeClient:
    def __init__(self, cost=0.0002):
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=lambda **_kw: response(cost)))


def usage_rows(case_id):
    return [row for row in db.case_log(db.connect(), case_id) if row["tool"] == "model_usage"]


def args_of(row):
    return json.loads(row["args"])


def test_assess_records_the_judge_call_with_reported_usage(monkeypatch):
    client = TestClient(app)
    headers = officer()
    asked = client.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    case_id = asked["case_id"]

    def judge_call(user):
        llm.create("judge", "fake-judge", FakeClient())
        count = user.count(". SENTENCE: ")
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(count)]})

    monkeypatch.setattr(judge, "_call", judge_call)
    result = client.post(f"/officer/cases/{case_id}/assess", headers=headers, json={"farmer_text": SECRET_TEXT})
    assert result.status_code == 200, result.text
    rows = usage_rows(case_id)
    assert len(rows) == 1, rows
    recorded = args_of(rows[0])
    assert recorded["path"] == "assess"
    entry = recorded["entries"][0]
    assert entry == {"role": "judge", "model": "fake-judge", "ok": True, "error": None,
                     "prompt_tokens": 11, "completion_tokens": 4, "cost_usd": 0.0002, "attempt": None}
    assert recorded["cost_usd"] == 0.0002
    blob = rows[0]["args"] + rows[0]["result_summary"]
    assert SECRET_TEXT not in blob and "Tamale" not in blob


def test_assess_timeout_records_the_error_class_and_unknown_usage(monkeypatch):
    client = TestClient(app)
    headers = officer()
    asked = client.post("/ask", json={"question": "When should I harvest soybean in Tamale?"}).json()
    case_id = asked["case_id"]

    class Clock:
        class chat:
            class completions:
                @staticmethod
                def create(**_kw):
                    raise TimeoutError(SECRET_QUESTION)

    def judge_call(_user):
        return llm.create("judge", "fake-judge", Clock).choices[0]

    monkeypatch.setattr(judge, "_call", judge_call)
    result = client.post(
        f"/officer/cases/{case_id}/assess", headers=headers,
        json={"farmer_text": "Harvest the soybean in the morning when most pods are brown or dry."},
    )
    assert result.status_code == 200, result.text
    rows = usage_rows(case_id)
    assert len(rows) == 1 and not rows[0]["ok"], rows
    recorded = args_of(rows[0])
    assert recorded["path"] == "assess"
    assert recorded["failed"] == 1 and recorded["errors"] == ["TimeoutError"]
    assert recorded["cost_usd"] is None
    entry = recorded["entries"][0]
    assert entry["ok"] is False and entry["error"] == "TimeoutError"
    assert entry["prompt_tokens"] is None and entry["completion_tokens"] is None and entry["cost_usd"] is None
    blob = json.dumps(recorded)
    assert SECRET_QUESTION not in blob and "TimeoutError" in blob


def test_citation_retry_records_each_application_attempt(monkeypatch):
    passage = knowledge.reference("APNI-SARI-2023:harvest")
    case_id = db.agent_upsert_case(db.connect(), status="draft", question=SECRET_QUESTION, crop="soybean", region="tamale")
    drafted = {"n": 0}

    def draft(_question, passages, _notes, conflicts=None, feedback=None):
        drafted["n"] += 1
        llm.create("draft", "fake-draft", FakeClient(0.0003))
        if drafted["n"] == 1:
            # Cited, so the judge runs, but the figure is not in the passage, so the app drafts again.
            return f"Soybean should be harvested when 4 out of 10 pods are mature [{passages[0]['id']}].", "llm:fake-draft"
        return f"{passages[0]['text'].split('. ')[0]}. [{passages[0]['id']}]", "llm:fake-draft"

    def judge_call(user):
        llm.create("judge", "fake-judge", FakeClient(0.0005))
        count = user.count(". SENTENCE: ")
        return json.dumps({"verdicts": [{"n": i + 1, "verdict": "supported", "why": "ok"} for i in range(count)]})

    monkeypatch.setattr(llm, "draft", draft)
    monkeypatch.setattr(judge, "_call", judge_call)
    calls = llm.start_usage()
    state = {"notes": [], "errors": [], "urgent_reasons": [], "passages": [passage], "question": SECRET_QUESTION,
             "conflicts": {}, "region": "tamale", "zone_mismatch": False, "officer_facts": [], "language": "en",
             "case_id": case_id}
    asyncio.run(agent.write(state, None))
    llm.log_usage(case_id, calls, actor="agent", path="generation")
    rows = usage_rows(case_id)
    assert len(rows) == 1, rows
    recorded = args_of(rows[0])
    assert [(item["attempt"], item["role"], item["ok"], item["cost_usd"]) for item in recorded["entries"]] == [
        (1, "draft", True, 0.0003), (1, "judge", True, 0.0005),
        (2, "draft", True, 0.0003), (2, "judge", True, 0.0005),
    ]
    assert recorded["cost_usd"] == 0.0016
    assert SECRET_QUESTION not in rows[0]["args"]
    assert drafted["n"] == 2
