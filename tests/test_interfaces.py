"""Interface-trial spine: morning sizing, the stores, and the card reader.

Everything here is the deterministic half. The one model call (the card photo)
is not exercised — `validate_read` is, because it is the gate between what a
model claims to see and what may be logged.
"""
from datetime import date, datetime

import pytest

from interfaces import card, morning, proposals
from scheduler.models import Task

UMB = [{"key": "health", "label": "Health & Body", "domains": ["fitness", "meals"]},
       {"key": "craft", "label": "Craft & Art", "domains": ["music-practice", "writing"]}]
DOMS = ["fitness", "meals", "music-practice", "writing", "career"]
TH = {"writing": {"min": 200, "aspirational": 600, "unit": "words"},
      "fitness": {"floor": 1, "aspirational": 3, "unit": "sessions"}}


def T(tid, domain, type_=3, mn=None, dur=None):
    return Task(id=tid, title=tid.replace("-", " "), type=type_, source="tasks",
                domain=domain, min=mn, duration=dur)


# engine order — the only order that exists
LIVE = [T("career-001", "career", mn=30, dur=45), T("writing-recurring", "writing", 4),
        T("fitness-recurring", "fitness", 4), T("career-002", "career", mn=60, dur=120),
        T("meals-001", "meals", mn=30, dur=45), T("writing-003", "writing", mn=20, dur=40)]


# --- sizing ------------------------------------------------------------------

def test_energy_caps_the_list_but_never_reorders_it():
    ids = lambda s: [i["id"] for i in s["rest"]]
    foggy = morning.shape_day(LIVE, TH, UMB, DOMS, "foggy")
    sharp = morning.shape_day(LIVE, TH, UMB, DOMS, "sharp")
    assert ids(foggy) == [t.id for t in LIVE[:3]]
    assert ids(sharp) == [t.id for t in LIVE]
    assert foggy["hidden"] == 3 and sharp["hidden"] == 0


def test_pull_groups_first_and_keeps_engine_order_inside_each_group():
    s = morning.shape_day(LIVE, TH, UMB, DOMS, "sharp", pull="craft")
    assert s["pull"]["label"] == "Craft & Art"
    assert [i["id"] for i in s["pull"]["items"]] == ["writing-recurring", "writing-003"]
    assert [i["id"] for i in s["rest"]] == ["career-001", "fitness-recurring",
                                            "career-002", "meals-001"]


def test_cap_applies_across_pull_and_rest():
    s = morning.shape_day(LIVE, TH, UMB, DOMS, "foggy", pull="craft")
    shown = [i["id"] for i in s["pull"]["items"] + s["rest"]]
    assert shown == ["writing-recurring", "writing-003", "career-001"]


@pytest.mark.parametrize("pull,label", [("health", "Health & Body"),
                                        ("Craft & Art", "Craft & Art"),
                                        ("career", "career")])
def test_pull_resolves_key_label_or_domain(pull, label):
    assert morning.resolve_pull(pull, UMB, DOMS)[0] == label


@pytest.mark.parametrize("pull", [None, "", "none", "nowhere", "typo-umbrella"])
def test_no_or_unknown_pull_is_simply_no_pull(pull):
    assert morning.resolve_pull(pull, UMB, DOMS) is None


def test_amounts_come_only_from_records_and_thresholds():
    w = T("writing-recurring", "writing", 4)
    assert morning.item_amount(w, TH, "foggy") == "200 words"
    assert morning.item_amount(w, TH, "sharp") == "600 words"
    assert morning.item_amount(w, TH, "steady") == "200–600 words"
    f = T("fitness-recurring", "fitness", 4)           # floor, no min
    assert morning.item_amount(f, TH, "foggy") == "1 session"
    c = T("career-001", "career", mn=30, dur=45)
    assert morning.item_amount(c, TH, "foggy") == "30 min"
    assert morning.item_amount(T("x", "career"), TH, "steady") == ""   # unknown → blank


def test_render_is_honest_about_what_was_held_back():
    txt = morning.render_day_text(morning.shape_day(LIVE, TH, UMB, DOMS, "foggy",
                                                    focus=["send Cody a pass"]))
    assert "floors-only" in txt and "send Cody a pass" in txt and "3 more held back" in txt


def test_empty_plan_says_so_instead_of_rendering_nothing():
    txt = morning.render_day_text(morning.shape_day([], TH, UMB, DOMS, "steady"))
    assert "open day" in txt


# --- the morning record ---------------------------------------------------------

def test_record_roundtrip_and_append_only(tmp_path):
    d = datetime(2026, 9, 28, 7, 31)
    morning.record_morning(tmp_path, "foggy", pull="craft", via="telegram", when=d)
    morning.record_morning(tmp_path, "steady", focus=["a", "b"], note="late start",
                           via="claude", when=d.replace(hour=9))
    text = morning.morning_path(tmp_path, d.date()).read_text()
    assert text.count("## ") == 2                         # nothing overwritten
    last = morning.read_today(tmp_path, d.date())
    assert last == {"via": "claude", "energy": "steady", "focus": ["a", "b"],
                    "note": "late start"}


@pytest.mark.parametrize("kw", [{"energy": "great"}, {"energy": "foggy", "via": "email"}])
def test_record_rejects_unknown_dials(tmp_path, kw):
    with pytest.raises(ValueError):
        morning.record_morning(tmp_path, **kw)


# --- watcher proposals -------------------------------------------------------

def _f(key, **kw):
    return proposals.validate({"key": key, "domain": "coding",
                               "summary": "4 commits", **kw}, ["coding", "production"])


def test_reporting_twice_keeps_a_confirmed_status(tmp_path):
    d = date(2026, 9, 28)
    proposals.report(tmp_path, d, [_f("git:life-os-web")])
    proposals.set_status(tmp_path, d, "git:life-os-web", "confirmed")
    proposals.report(tmp_path, d, [_f("git:life-os-web", summary="6 commits")])
    items = proposals._load(proposals.proposals_path(tmp_path, d))
    assert len(items) == 1 and items[0]["status"] == "confirmed"
    assert items[0]["summary"] == "6 commits"
    assert proposals.open_items(tmp_path, d) == []


@pytest.mark.parametrize("bad", [{"domain": "nope"}, {"unit": "hours"},
                                 {"amount": -5}, {"key": ""}])
def test_validate_refuses_bad_findings(bad):
    with pytest.raises(ValueError):
        proposals.validate({"key": "k", "domain": "coding", "summary": "s", **bad},
                           ["coding"])


def test_unknown_key_status_change_is_none(tmp_path):
    assert proposals.set_status(tmp_path, date(2026, 9, 28), "ghost", "confirmed") is None


# --- the card reader's gate --------------------------------------------------

def test_only_ticked_known_ids_survive_and_misreads_are_surfaced():
    raw = {"is_card": True, "energy": "foggy", "note": " walked ",
           "items": [{"id": "career-001", "checked": True, "minutes": 25},
                     {"id": "meals-001", "checked": False},
                     {"id": "carer-001", "checked": True},            # misread
                     {"id": "writing-003", "checked": True, "minutes": 9999}]}
    out = card.validate_read(raw, {"career-001", "meals-001", "writing-003"})
    assert out["done"] == [{"id": "career-001", "minutes": 25.0},
                           {"id": "writing-003", "minutes": None}]
    assert out["unknown"] == ["carer-001"]
    assert out["energy"] == "foggy" and out["note"] == " walked "


def test_not_a_card_yields_nothing():
    assert card.validate_read({"is_card": False, "items": [{"id": "x", "checked": True}]},
                              {"x"})["done"] == []


def test_card_rows_number_pull_group_first():
    s = morning.shape_day(LIVE, TH, UMB, DOMS, "foggy", pull="craft")
    assert [r["n"] for r in card.card_items(s)] == [1, 2, 3]
    assert card.card_items(s)[0]["id"] == "writing-recurring"


def test_trial_report_counts_by_via(tmp_path):
    from datetime import date as _d
    from interfaces.report import render, tally
    d = _d(2026, 9, 28)
    (tmp_path / "daily" / "morning").mkdir(parents=True)
    (tmp_path / "daily" / "logs").mkdir(parents=True)
    (tmp_path / "daily" / "proposals").mkdir(parents=True)
    (tmp_path / "daily/morning/2026-09-28.md").write_text(
        "## 07:31 · via telegram\n\n- **energy:** foggy\n\n")
    (tmp_path / "daily/logs/2026-09-28.md").write_text(
        "## 2026-09-28\n\n- **outcome:** done\n- **via:** paper\n\n"
        "## 2026-09-28\n\n- **outcome:** missed\n- **via:** paper\n\n"
        "## 2026-09-28\n\n- **outcome:** done\n\n")
    (tmp_path / "daily/proposals/2026-09-28.yaml").write_text(
        "- {key: a, status: confirmed}\n- {key: b, status: open}\n")
    t = tally(tmp_path, d, d)
    assert t["checkins"] == {"telegram": 1}
    assert t["completions"] == {"paper": 1, "untagged": 1}   # missed doesn't count
    assert t["proposals"] == {"confirmed": 1, "open": 1}
    assert "1/1 days" in render(t)
