"""`GET /api/domains/{name}` — the per-domain page payload.

Filed by six page specs at once (dev/plans/page-specs/). Env-independent: runs
against the temp fixture tree so the deploy gate stays green.
"""
from fastapi.testclient import TestClient

import dashboard.app as A

TOK = "secret123"
H = {"Authorization": f"Bearer {TOK}"}


def _client(life_os, monkeypatch):
    monkeypatch.setenv("LIFE_OS_ROOT", str(life_os))
    monkeypatch.setenv("LIFE_OS_DASHBOARD_TOKEN", TOK)
    return TestClient(A.app)


def test_gated(life_os, monkeypatch):
    assert _client(life_os, monkeypatch).get("/api/domains/career").status_code == 401


def test_unknown_domain_404s(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    assert c.get("/api/domains/nonesuch", headers=H).status_code == 404


def test_path_traversal_never_reaches_the_domain_handler(life_os, monkeypatch):
    """`name` indexes the canonical domain set — it is never a path fragment.

    Two defenses stack: the router normalizes `..` BEFORE routing (so probes
    land on a different route entirely), and the handler validates `name`
    against `list_domains()`. The property that matters is that no probe ever
    returns domain content.
    """
    c = _client(life_os, monkeypatch)
    for bad in ("..", "../vault", "%2e%2e", "....//vault"):
        r = c.get(f"/api/domains/{bad}", headers=H)
        # A normalized probe can land on a legitimate SIBLING route (`..` becomes
        # `/api/`, which is a real 200 endpoint) — that is not traversal
        # succeeding. The property that must hold is that no probe ever yields a
        # DOMAIN payload for a name outside the canonical set.
        assert "docs" not in r.text, bad
        assert "last_completion" not in r.text, bad


def test_shape(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    d = c.get("/api/domains/career", headers=H).json()
    assert set(d) >= {"domain", "thresholds", "docs", "tasks",
                      "last_completion", "completions_this_week"}
    assert d["domain"] == "career"
    assert set(d["docs"]) == {"readme", "goals", "program"}


def test_docs_are_markdown_text_not_html(life_os, monkeypatch):
    """No unsanitized HTML crosses the boundary; the client renders."""
    (life_os / "domains" / "career" / "README.md").write_text(
        "# Career\n\nprep phase\n", encoding="utf-8")
    c = _client(life_os, monkeypatch)
    readme = c.get("/api/domains/career", headers=H).json()["docs"]["readme"]
    assert readme.startswith("# Career")
    assert "<h1" not in readme


def test_absent_doc_is_null_not_invented(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    # career has no program.md in the fixture
    assert c.get("/api/domains/career", headers=H).json()["docs"]["program"] is None


def test_tasks_carry_the_engine_s_computed_fields(life_os, monkeypatch):
    """urgency / eligible / blocked-reason come from compile(), not the client."""
    from scheduler.compile_queue import compile_to_file
    compile_to_file(life_os)          # a real tree always has a compiled queue
    c = _client(life_os, monkeypatch)
    tasks = c.get("/api/domains/career", headers=H).json()["tasks"]
    assert tasks, "fixture career has task records"
    for t in tasks:
        assert {"id", "title", "type", "domain", "urgency", "eligible"} <= set(t)
        assert t["domain"] == "career"


def test_thresholds_exposed_for_chart_bands(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    th = c.get("/api/domains/career", headers=H).json()["thresholds"]
    assert "cadence" in th


def test_session_cookie_works_too(life_os, monkeypatch):
    c = _client(life_os, monkeypatch)
    c.post("/login", data={"token": TOK}, follow_redirects=False)
    assert c.get("/api/domains/career").status_code == 200


def test_tasks_read_the_ENGINE_S_projection_not_a_fresh_compile(life_os, monkeypatch):
    """Deliberate: the page shows what the scheduler actually planned from.

    `load_queue` reads schedule/queue.yaml (self-healing only when ABSENT). A
    fresh recompile here could diverge from the plan the day was built on, so
    the projection is the more honest source. The fixture ships a stub empty
    queue, which is exactly the "projection says nothing yet" case.
    """
    c = _client(life_os, monkeypatch)   # no compile → stub queue.yaml stands
    assert c.get("/api/domains/career", headers=H).json()["tasks"] == []
