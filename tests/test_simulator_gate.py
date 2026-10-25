"""The phone simulator's outbox lists every farmer's messages, so it must be off unless explicitly enabled."""
from fastapi.testclient import TestClient

from agrireach.api import app


def test_simulator_routes_are_off_by_default(monkeypatch):
    monkeypatch.delenv("AGRIREACH_SIMULATOR", raising=False)
    c = TestClient(app)
    assert c.get("/channels/simulator/outbox").status_code == 404
    assert c.post("/channels/simulator/inbound", data={"sender": "+233200000001", "text": "hi"}).status_code == 404


def test_simulator_outbox_works_when_enabled(monkeypatch):
    monkeypatch.setenv("AGRIREACH_SIMULATOR", "1")
    assert TestClient(app).get("/channels/simulator/outbox").status_code == 200
