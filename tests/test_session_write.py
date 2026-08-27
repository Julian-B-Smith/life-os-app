"""Session-write surface `/api/sw/*` (SW-0) — the browser's write path.

The whole point of this surface is to let the hub record WITHOUT a token in
client JS. That makes CSRF the central risk, so most of these tests are about
what must be REFUSED. The single most important assertion is the last one: the
original Bearer-only boundary must still hold — adding this surface must not
have quietly made `/api/write/*` cookie-accessible.
"""
from fastapi.testclient import TestClient

import dashboard.app as A
import dashboard.ratelimit as RL
import pytest

TOK = "secret123"
WTOK = "write-secret-xyz"
CSRF = {"X-Life-OS-Request": "1"}


@pytest.fixture(autouse=True)
def _fresh():
    RL.reset_all()
    yield
    RL.reset_all()


def _client(life_os, monkeypatch, login=True):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.setenv("LIFE_OS_DASHBOARD_TOKEN", TOK)
    monkeypatch.setenv("LIFE_OS_WRITE_TOKEN", WTOK)
    c = TestClient(A.app)
    if login:
        c.post("/login", data={"token": TOK}, follow_redirects=False)
    return c


# --- what must be refused ---------------------------------------------------

def test_requires_a_session(life_os, monkeypatch):
    c = _client(life_os, monkeypatch, login=False)
    r = c.post("/api/sw/inbox", json={"text": "x"}, headers=CSRF)
    assert r.status_code == 401


def test_bearer_token_is_not_accepted_here(life_os, monkeypatch):
    """This surface is session-only; the write token belongs to /api/write/*."""
    c = _client(life_os, monkeypatch, login=False)
    r = c.post("/api/sw/inbox", json={"text": "x"},
               headers={**CSRF, "Authorization": f"Bearer {WTOK}"})
    assert r.status_code == 401


def test_missing_csrf_header_is_refused(life_os, monkeypatch):
    """A logged-in session ALONE must not be enough — that is the CSRF hole."""
    c = _client(life_os, monkeypatch)
    r = c.post("/api/sw/inbox", json={"text": "x"})       # no custom header
    assert r.status_code == 403


def test_cross_origin_is_refused_even_with_the_header(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    r = c.post("/api/sw/inbox", json={"text": "x"},
               headers={**CSRF, "Origin": "https://evil.example"})
    assert r.status_code == 403


def test_same_origin_is_allowed(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    r = c.post("/api/sw/inbox", json={"text": "x"},
               headers={**CSRF, "Origin": "http://testserver"})
    assert r.status_code == 200


# --- the boundary that must NOT have regressed ------------------------------

def test_bearer_write_api_still_rejects_a_session_cookie(life_os, monkeypatch):
    """The original CSRF boundary. Adding /api/sw must not have opened this."""
    c = _client(life_os, monkeypatch)                      # logged in
    assert c.post("/api/write/inbox", json={"text": "x"},
                  headers=CSRF).status_code == 401


# --- it really writes, through the same primitives --------------------------

def test_inbox_write_lands_in_the_tree(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    r = c.post("/api/sw/inbox", json={"text": "from the hub"}, headers=CSRF)
    assert r.status_code == 200 and r.json()["ok"] is True
    assert "from the hub" in (life_os / "inbox.md").read_text(encoding="utf-8")


def test_log_write_validates_domain_exactly_like_the_bearer_surface(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.post("/api/sw/log", json={"domain": "nonesuch"},
                  headers=CSRF).status_code == 422
    assert c.post("/api/sw/log", json={"domain": "career", "outcome": "bogus"},
                  headers=CSRF).status_code == 422
    assert c.post("/api/sw/log", json={"domain": "career", "outcome": "done"},
                  headers=CSRF).status_code == 200


def test_all_four_primitives_are_present(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.post("/api/sw/note", json={"text": "n"}, headers=CSRF).status_code == 200
    assert c.post("/api/sw/review", json={"text": "r", "kind": "daily"},
                  headers=CSRF).status_code == 200


def test_hard_scope_has_no_endpoint_for_excluded_stores(life_os, monkeypatch):
    """Scope is enforced by ABSENCE — there is no route to reach these at all."""
    c = _client(life_os, monkeypatch)
    for path in ("/api/sw/thresholds", "/api/sw/vault", "/api/sw/file"):
        assert c.post(path, json={"x": 1}, headers=CSRF).status_code == 404


def test_rate_limited_like_the_bearer_surface(life_os, monkeypatch):
    monkeypatch.setattr(RL.write_bucket, "limit", 2)
    c = _client(life_os, monkeypatch)
    h = {**CSRF, "X-Forwarded-For": "hub-client"}
    for i in range(2):
        assert c.post("/api/sw/inbox", json={"text": f"i{i}"},
                      headers=h).status_code == 200
    r = c.post("/api/sw/inbox", json={"text": "over"}, headers=h)
    assert r.status_code == 429 and "Retry-After" in r.headers
