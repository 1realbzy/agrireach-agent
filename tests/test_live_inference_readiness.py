"""Regressions for the live-inference readiness defects.

These tests describe the required behavior. On commit ba15bcb they fail:
a pesticide referral passes a soybean harvest question, an evidence-gap
sentence is blocked as S2, provider clients retry without counting each HTTP
attempt, and a rejected case is described as still waiting for review.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from agrireach import approval, farmer_reply, judge, knowledge, llm, safety_gate

PESTICIDE = "Consult your local AEA before choosing or applying a pesticide."
HERBICIDE = "Consult your local agricultural extension officer before applying any herbicide."
FAW = "Consult your local AEA for advice on the recommended fall army worm control pesticide in your area."
HARVEST_Q = "When should I harvest soybean in Tamale?"
EVIDENCE_GAP = "An extension officer needs to answer this case."
REJECTION = "An extension officer reviewed this question and did not approve any advice. Nothing was sent to you."
REAL_JUDGE_CALL = judge._call

_OK = {
    "id": "chatcmpl-test",
    "object": "chat.completion",
    "created": 0,
    "model": "test-model",
    "choices": [{
        "index": 0,
        "finish_reason": "stop",
        "message": {"role": "assistant", "content": "Harvest when most pods are brown."},
    }],
    "usage": {"prompt_tokens": 3, "completion_tokens": 4, "total_tokens": 7},
}


def _harvest():
    return knowledge.reference("APNI-SARI-2023:harvest")


def _ctx(question: str, source: dict | None = None) -> dict:
    return {
        "case": {
            "question": question, "region": "tamale", "farmer_draft": None, "crop": "soybean",
        },
        "sources": [source or _harvest()],
        "contact": None,
    }


class _Provider(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _read(self) -> None:
        length = int(self.headers.get("Content-Length", "0") or 0)
        if length:
            self.rfile.read(length)

    def _count(self) -> None:
        self.server.hits += 1
        self.server.paths.append(f"{self.command} {self.path}")

    def do_POST(self) -> None:
        self._read()
        self._count()
        mode = self.server.mode
        if mode == "timeout":
            time.sleep(self.server.pause)
            return
        if mode == "redirect":
            port = self.server.server_address[1]
            self.send_response(302)
            self.send_header("Location", f"http://127.0.0.1:{port}/v1/chat/completions/followed")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if mode == "rate":
            self._json(429, {"error": {"message": "slow down", "type": "rate_limit_error"}})
            return
        if mode == "down":
            self._json(500, {"error": {"message": "unavailable", "type": "server_error"}})
            return
        if mode == "auth":
            self._json(401, {"error": {"message": "bad key", "type": "authentication_error"}})
            return
        self._json(200, _OK)

    def do_GET(self) -> None:
        self._count()
        self._json(200, _OK)

    def _json(self, status: int, payload: dict) -> None:
        body = json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt: str, *args) -> None:
        return


class _Server(ThreadingHTTPServer):
    allow_reuse_address = True
    hits: int
    paths: list
    mode: str
    pause: float


@pytest.fixture
def provider(monkeypatch):
    """Local OpenAI-compatible endpoint. No request leaves the machine."""
    import openai._base_client as base_client

    monkeypatch.setattr(base_client.time, "sleep", lambda *_args, **_kwargs: None)
    server = _Server(("127.0.0.1", 0), _Provider)
    server.hits = 0
    server.paths = []
    server.mode = "ok"
    server.pause = 5
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    port = server.server_address[1]
    monkeypatch.setenv("LLM_BASE_URL", f"http://127.0.0.1:{port}/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "local-test-key")
    monkeypatch.setenv("LLM_TIMEOUT", "0.4")
    monkeypatch.setenv("AGRIREACH_JUDGE_MODEL", "test-judge")
    monkeypatch.delenv("AGRIREACH_JUDGE_BASE_URL", raising=False)
    monkeypatch.delenv("AGRIREACH_JUDGE_API_KEY", raising=False)
    try:
        yield server
    finally:
        server.shutdown()
        thread.join(timeout=2)
        server.server_close()


def test_pesticide_referral_is_not_a_pass_for_soybean_harvest():
    result = safety_gate.assess(PESTICIDE, [_harvest()], question=HARVEST_Q)
    assert result.outcome == "review_required"
    assert any(f.rule_id == "RELEVANCE" for f in result.findings)
    assert result.to_dict().get("relevance", {}).get("status") == "unrelated"
    assessed = approval.assess_candidate(PESTICIDE, _ctx(HARVEST_Q))
    assert assessed["outcome"] == "review_required"
    assert any(f["rule_id"] == "RELEVANCE" for f in assessed["findings"])
    assert assessed.get("judge_status") != "supported"


def test_shared_words_do_not_make_a_pesticide_referral_relevant():
    question = "When should I harvest soybean? Please consult the season calendar."
    result = safety_gate.assess(PESTICIDE, [_harvest()], question=question)
    assert result.to_dict().get("relevance", {}).get("status") == "unrelated"
    assert result.outcome == "review_required"


def test_matching_pest_referral_stays_a_safety_pass():
    question = "Fall armyworm is eating my maize. What should I do?"
    source = knowledge.reference("APNI-SARI-2023-MAIZE:p20-faw-control")
    result = safety_gate.assess(FAW, [source], question=question)
    assert result.outcome == "pass"
    assert not any(f.rule_id == "RELEVANCE" for f in result.findings)
    assert result.to_dict().get("relevance", {}).get("status") == "aligned"


def test_unclassifiable_question_is_not_called_relevant():
    result = safety_gate.assess(HERBICIDE, [_harvest()], question="Can you help my farm?")
    relevance = result.to_dict().get("relevance", {})
    assert relevance.get("status") == "uncertain"
    assert relevance.get("status") != "aligned"
    assert result.outcome == "pass"


def test_harvest_advice_is_not_flagged_as_an_unrelated_referral():
    text = "Harvest soybean when most pods are brown and dry."
    result = safety_gate.assess(text, [_harvest()], question=HARVEST_Q)
    assert result.outcome == "pass"
    assert not any(f.rule_id == "RELEVANCE" for f in result.findings)


def test_evidence_gap_sentence_is_not_an_s2_block():
    result = safety_gate.assess(EVIDENCE_GAP, [], question=HARVEST_Q)
    assert not any(finding.rule_id == "S2" for finding in result.findings)
    assert result.outcome == "pass"
    assert result.judge_status == "required"
    stub = (
        "I could not find guidance on this in the curated sources, so I cannot give a grounded answer. "
        + EVIDENCE_GAP
    )
    combined = safety_gate.assess(stub, [], question=HARVEST_Q)
    assert not any(finding.rule_id == "S2" for finding in combined.findings)
    assert combined.outcome == "pass"


@pytest.mark.parametrize("text", [
    "An extension officer needs to answer this case. Apply glyphosate at 2 litres per hectare.",
    "An extension officer needs to answer this case, but spray glyphosate on the soybean.",
    "An extension officer needs to answer this case before you use glyphosate.",
    "You do not need an extension officer to answer this case.",
    "Skip the extension officer and spray the crop yourself.",
])
def test_treatment_hidden_in_referral_language_stays_blocked(text):
    result = safety_gate.assess(text, [], question=HARVEST_Q)
    assert result.outcome == "safety_blocked"
    assert any(finding.rule_id in {"S2", "S3"} for finding in result.findings)


def test_named_product_beside_the_evidence_gap_cannot_pass():
    text = "Apply mancozeb at 2 litres per hectare. An extension officer needs to answer this case."
    result = safety_gate.assess(text, [], question=HARVEST_Q)
    assert result.outcome != "pass"
    assert any(finding.rule_id == "S3" and "mancozeb" in finding.sentence.casefold() for finding in result.findings)
    assert not any(
        finding.rule_id == "S2" and "needs to answer this case" in finding.sentence.casefold()
        for finding in result.findings)


def test_clients_disable_hidden_retries_and_redirects(provider, monkeypatch):
    import openai

    assert openai.__version__ == "3.29.0"
    assert openai._constants.DEFAULT_MAX_RETRIES == 2
    built = []
    real = openai.OpenAI

    def spy(**kwargs):
        client = real(**kwargs)
        built.append(client)
        return client

    monkeypatch.setattr(llm, "OpenAI", spy)
    llm.draft(HARVEST_Q, [{"id": "P1", "text": "Harvest when pods are brown.", "title": "t", "source": "s"}], [])
    farmer_reply._llm_rewrite("Harvest when pods are brown.", HARVEST_Q)
    REAL_JUDGE_CALL("1. SENTENCE: Harvest when pods are brown.\n   PASSAGES: [P1] Harvest when pods are brown.")
    assert len(built) == 3
    assert all(client.max_retries == 0 for client in built)
    assert all(client._client.follow_redirects is False for client in built)
    assert provider.hits == 3


@pytest.mark.parametrize("mode", ["timeout", "rate", "down", "auth", "redirect"])
def test_provider_errors_make_one_http_attempt(provider, mode):
    provider.mode = mode
    provider.hits = 0
    with pytest.raises(Exception):
        llm.draft(HARVEST_Q, [{"id": "P1", "text": "Harvest when pods are brown.", "title": "t", "source": "s"}], [])
    assert provider.hits == 1


def test_failed_attempt_is_counted_and_exhaustion_sends_nothing_further(provider, monkeypatch):
    monkeypatch.setenv("AGRIREACH_REQUEST_BUDGET", "1")
    calls = llm.start_usage()
    provider.mode = "down"
    with pytest.raises(Exception):
        llm.draft(HARVEST_Q, [{"id": "P1", "text": "Harvest when pods are brown.", "title": "t", "source": "s"}], [])
    assert provider.hits == 1
    assert len(calls) == 1 and calls[0]["ok"] is False
    provider.mode = "ok"
    before = provider.hits
    with pytest.raises(llm.ProviderBudgetExceeded):
        farmer_reply._llm_rewrite("Harvest when pods are brown.", HARVEST_Q)
    with pytest.raises(llm.ProviderBudgetExceeded):
        REAL_JUDGE_CALL("1. SENTENCE: Harvest when pods are brown.\n   PASSAGES: [P1] brown.")
    assert provider.hits == before
    summary = llm.usage_summary(calls)
    assert summary["attempted"] == 1
    assert summary["failed"] == 1


def test_budget_is_shared_by_draft_regeneration_judge_and_rewrite(provider, monkeypatch):
    monkeypatch.setenv("AGRIREACH_REQUEST_BUDGET", "3")
    passage = [{"id": "P1", "text": "Harvest when pods are brown.", "title": "t", "source": "s"}]
    llm.draft(HARVEST_Q, passage, [])
    llm.draft(HARVEST_Q, passage, [], feedback=["sentence is not cited"])
    REAL_JUDGE_CALL("1. SENTENCE: Harvest when pods are brown.\n   PASSAGES: [P1] Harvest when pods are brown.")
    assert provider.hits == 3
    with pytest.raises(llm.ProviderBudgetExceeded):
        farmer_reply._llm_rewrite("Harvest when pods are brown.", HARVEST_Q)
    assert provider.hits == 3


def test_concurrent_callers_cannot_exceed_the_shared_budget(provider, monkeypatch):
    monkeypatch.setenv("AGRIREACH_REQUEST_BUDGET", "5")
    errors = []
    passage = [{"id": "P1", "text": "Harvest when pods are brown.", "title": "t", "source": "s"}]

    def once():
        try:
            llm.draft(HARVEST_Q, passage, [])
        except llm.ProviderBudgetExceeded:
            errors.append("exhausted")
        except Exception as exc:  # pragma: no cover - unexpected provider failure
            errors.append(type(exc).__name__)

    threads = [threading.Thread(target=once) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert provider.hits == 5
    assert errors.count("exhausted") == 3
    assert set(errors) == {"exhausted"}


def test_rejected_case_is_not_described_as_waiting_for_review():
    from fastapi.testclient import TestClient

    from agrireach import db
    from agrireach.api import app

    con = db.connect()
    case_id = db.agent_upsert_case(
        con, status="pending_review", question=HARVEST_Q, crop="soybean", region="tamale", draft="draft")
    secret = "private north-field detail"
    db.officer_decide(
        con, case_id, officer="Ama", decision="reject", note=secret,
        expected_revision=db.get_case(con, case_id)["revision"])
    token = db.issue_farmer_case_token(con, case_id)
    client = TestClient(app)
    assert client.get(f"/farmer/cases/{case_id}").status_code == 404
    wrong = client.get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": "not-the-token"})
    assert wrong.status_code == 404
    assert secret not in wrong.text
    body = client.get(f"/farmer/cases/{case_id}", headers={"X-Case-Access-Token": token}).json()
    assert body["status"] == "rejected"
    assert body["answer"] is None
    assert body["message"] == REJECTION
    assert "waiting" not in body["message"].lower()
    assert secret not in json.dumps(body)
    pending = db.agent_upsert_case(
        con, status="pending_review", question=HARVEST_Q, crop="soybean", region="tamale", draft="draft")
    pending_token = db.issue_farmer_case_token(con, pending)
    waiting = client.get(f"/farmer/cases/{pending}", headers={"X-Case-Access-Token": pending_token}).json()
    assert waiting["status"] == "pending_review"
    assert "waiting" in waiting["message"].lower()


def test_farmer_portal_shows_the_rejection_message(monkeypatch):
    import httpx
    from fastapi.testclient import TestClient
    from streamlit import env_util
    from streamlit.testing.v1 import AppTest

    from agrireach import db
    from agrireach.api import app

    monkeypatch.setattr(env_util, "is_repl", lambda: False)
    con = db.connect()
    case_id = db.agent_upsert_case(
        con, status="pending_review", question=HARVEST_Q, crop="soybean", region="tamale", draft="draft")
    secret = "private north-field detail"
    db.officer_decide(
        con, case_id, officer="Ama", decision="reject", note=secret,
        expected_revision=db.get_case(con, case_id)["revision"])
    token = db.issue_farmer_case_token(con, case_id)
    api = TestClient(app)

    def backend(method, url, **kwargs):
        path = url[url.find("/"):] if "://" in url else url
        response = api.request(method, path, headers=kwargs.get("headers"))
        return httpx.Response(response.status_code, content=response.content)

    monkeypatch.setattr(httpx, "request", backend)
    screen = AppTest.from_string("from agrireach.ui import farmer_screen\nfarmer_screen()", default_timeout=20).run()
    screen.number_input(key="farmer_lookup_id").set_value(case_id)
    screen.text_input(key="farmer_lookup_token").set_value(token)
    screen.button(key="farmer_check").click().run()
    visible = " ".join(item.value for item in list(screen.info) + list(screen.warning) + list(screen.success) + list(screen.error))
    assert REJECTION in visible
    assert "waiting for an extension officer to review" not in visible.lower()
    assert secret not in visible
    assert not screen.success
