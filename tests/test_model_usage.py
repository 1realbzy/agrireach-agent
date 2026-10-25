"""Every model call sends max_tokens and records its token usage and provider cost (Grok Bot's live run hit 402s)."""
import sys
import types

import pytest

from agrireach import farmer_reply, judge, llm

_JUDGE_CALL = judge._call  # conftest swaps judge._call for an offline judge per test; keep the real one


class _FakeOpenAI:
    calls: list = []

    def __init__(self, **k):
        self.chat = types.SimpleNamespace(completions=types.SimpleNamespace(create=self._create))

    def _create(self, **k):
        _FakeOpenAI.calls.append(k)
        msg = types.SimpleNamespace(content='{"verdicts": []}')
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)],
                                     usage=types.SimpleNamespace(prompt_tokens=120, completion_tokens=30, cost=0.0004))


@pytest.fixture
def fake_openai(monkeypatch):
    _FakeOpenAI.calls = []
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=_FakeOpenAI))
    monkeypatch.setenv("LLM_BASE_URL", "https://openrouter.ai/api/v1")
    monkeypatch.setenv("LLM_MODEL", "test-model")
    monkeypatch.setenv("LLM_API_KEY", "x")
    return _FakeOpenAI.calls


def test_all_three_model_calls_send_max_tokens_and_record_usage(fake_openai):
    calls = llm.start_usage()
    llm.draft("When should I plant soybean in Tamale?", [{"id": "P1", "text": "Plant in June.", "title": "t", "source": "s"}], [])
    farmer_reply._llm_rewrite("Plant in June [P1].", "When should I plant?", conflicts=False)
    _JUDGE_CALL("items")
    assert [c["max_tokens"] for c in fake_openai] == [800, 400, 1500]
    assert all(c["extra_body"] == {"usage": {"include": True}} for c in fake_openai)
    assert [c["role"] for c in calls] == ["draft", "farmer_text", "judge"]
    s = llm.usage_summary(calls)
    assert s["calls"] == 3 and s["by_role"]["judge"] == {"calls": 1, "prompt_tokens": 120, "completion_tokens": 30}
    assert s["cost_usd"] == pytest.approx(0.0012)


def test_max_tokens_can_be_set_per_role(fake_openai, monkeypatch):
    monkeypatch.setenv("AGRIREACH_MAX_TOKENS_JUDGE", "900")
    _JUDGE_CALL("items")
    assert fake_openai[0]["max_tokens"] == 900


def test_cost_is_unknown_when_provider_does_not_report_it_and_no_extra_body_off_openrouter(fake_openai, monkeypatch):
    monkeypatch.setenv("LLM_BASE_URL", "http://localhost:11434/v1")
    calls = llm.start_usage()
    r = types.SimpleNamespace(usage=types.SimpleNamespace(prompt_tokens=5, completion_tokens=1))
    llm.record_usage("draft", "m", r)
    assert llm.usage_summary(calls)["cost_usd"] is None
    _JUDGE_CALL("items")
    assert fake_openai[0]["extra_body"] == {}


def test_a_failed_call_counts_as_attempted_not_succeeded(fake_openai, monkeypatch):
    class Refused(Exception):
        pass

    def boom(self, **k):
        raise Refused("402")

    calls = llm.start_usage()
    _JUDGE_CALL("items")
    monkeypatch.setattr(_FakeOpenAI, "_create", boom)
    with pytest.raises(Refused):
        _JUDGE_CALL("items")
    s = llm.usage_summary(calls)
    assert (s["attempted"], s["calls"], s["failed"], s["errors"]) == (2, 1, 1, ["Refused"])
    assert s["cost_usd"] == pytest.approx(0.0004)  # cost of the call that ran
