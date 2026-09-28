"""The trial's write primitives over HTTP: /morning and /propose, plus `via`."""
from datetime import date

import pytest
from fastapi.testclient import TestClient

import dashboard.app as A
import dashboard.ratelimit as RL

WTOK, DTOK = "write-secret-xyz", "secret123"
W = {"Authorization": f"Bearer {WTOK}"}


@pytest.fixture(autouse=True)
def _fresh():
    RL.reset_all()
    yield
    RL.reset_all()


def _c(life_os, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.setenv("LIFE_OS_WRITE_TOKEN", WTOK)
    monkeypatch.setenv("LIFE_OS_DASHBOARD_TOKEN", DTOK)
    return TestClient(A.app)


def test_morning_records_and_returns_the_sized_day(life_os, monkeypatch):
    c = _c(life_os, monkeypatch)
    r = c.post("/api/write/morning", headers=W,
               json={"energy": "foggy", "pull": "career", "focus": ["one thing"],
                     "via": "claude"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["day"]["energy"] == "foggy" and "floors-only" in body["text"]
    text = (life_os / body["written"]).read_text()
    assert "- **energy:** foggy" in text and "via claude" in text


def test_morning_rejects_unknown_energy_and_via(life_os, monkeypatch):
    c = _c(life_os, monkeypatch)
    assert c.post("/api/write/morning", headers=W, json={"energy": "wired"}).status_code == 422
    assert c.post("/api/write/morning", headers=W,
                  json={"energy": "sharp", "via": "fax"}).status_code == 422


def test_morning_on_the_browser_surface_needs_session_and_csrf(life_os, monkeypatch):
    c = _c(life_os, monkeypatch)
    c.post("/login", data={"token": DTOK}, follow_redirects=False)
    assert c.post("/api/sw/morning", json={"energy": "steady"}).status_code == 403
    assert c.post("/api/sw/morning", json={"energy": "steady", "via": "hub"},
                  headers={"X-Life-OS-Request": "1"}).status_code == 200


def test_log_via_survives_to_disk(life_os, monkeypatch):
    """Regression: append_log_entry's field WHITELIST used to drop unknown keys
    silently — a `via` tag would have measured zero with no error anywhere."""
    c = _c(life_os, monkeypatch)
    r = c.post("/api/write/log", headers=W,
               json={"domain": "career", "outcome": "done", "via": "paper"})
    assert r.status_code == 200
    log = life_os / "daily" / "logs" / f"{date.today().isoformat()}.md"
    assert "- **via:** paper" in log.read_text()


def test_log_rejects_an_unknown_via(life_os, monkeypatch):
    c = _c(life_os, monkeypatch)
    assert c.post("/api/write/log", headers=W,
                  json={"domain": "career", "via": "carrier-pigeon"}).status_code == 422


def test_propose_queues_findings_without_logging_anything(life_os, monkeypatch):
    c = _c(life_os, monkeypatch)
    r = c.post("/api/write/propose", headers=W, json={"findings": [
        {"key": "git:x", "domain": "career", "summary": "3 commits", "amount": 40,
         "unit": "minutes"}]})
    assert r.status_code == 200 and r.json()["open"] == 1
    log = life_os / "daily" / "logs" / f"{date.today().isoformat()}.md"
    assert not log.exists() or "3 commits" not in log.read_text()


def test_propose_validates_and_bounds(life_os, monkeypatch):
    c = _c(life_os, monkeypatch)
    bad = {"key": "k", "domain": "nope", "summary": "s"}
    assert c.post("/api/write/propose", headers=W, json={"findings": [bad]}).status_code == 422
    many = [{"key": f"k{i}", "domain": "career", "summary": "s"} for i in range(51)]
    assert c.post("/api/write/propose", headers=W, json={"findings": many}).status_code == 422


def test_the_browser_cannot_propose(life_os, monkeypatch):
    """Proposals come from machine observers only; there is no /api/sw route."""
    c = _c(life_os, monkeypatch)
    c.post("/login", data={"token": DTOK}, follow_redirects=False)
    r = c.post("/api/sw/propose", json={"findings": []}, headers={"X-Life-OS-Request": "1"})
    assert r.status_code in (404, 405)


def test_card_page_is_gated_renders_and_marks_itself_printed(life_os, monkeypatch, tmp_path):
    import interfaces.card as card
    monkeypatch.setattr(card, "_CACHE", tmp_path)      # keep the marker out of ~
    c = _c(life_os, monkeypatch)
    assert c.get("/card", follow_redirects=False).status_code in (303, 307)
    c.post("/login", data={"token": DTOK}, follow_redirects=False)
    c.post("/api/write/morning", headers=W, json={"energy": "foggy", "via": "telegram"})
    r = c.get("/card")
    assert r.status_code == 200
    assert 'class="picked">foggy' in r.text           # the morning's energy, pre-circled
    assert "LIFE-OS · CARD" in r.text
    assert card.was_viewed(date.today())
