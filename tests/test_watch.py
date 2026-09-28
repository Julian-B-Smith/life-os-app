"""Pure parts of the Mac watcher (clients/watch.py)."""
from datetime import date, datetime, time
from pathlib import Path

from clients import watch


def test_estimate_single_event_is_lead_only():
    assert watch.estimate_minutes([1000.0]) == watch.LEAD_MIN
    assert watch.estimate_minutes([]) == 0


def test_estimate_splits_sittings_on_gap():
    t0 = 1_000_000.0
    one = [t0, t0 + 30 * 60]                        # 30-min sitting
    two = [t0 + 4 * 3600, t0 + 4 * 3600 + 10 * 60]  # 10-min sitting, hours later
    assert watch.estimate_minutes(one + two) == (30 + watch.LEAD_MIN) + (10 + watch.LEAD_MIN)


def test_estimate_is_capped():
    stamps = [i * 30 * 60.0 for i in range(40)]     # a save every 30 min for 20h
    assert watch.estimate_minutes(stamps) == watch.CAP_MIN


def test_backup_counts_as_its_parent_project():
    assert watch.als_project(Path("/x/Song Project/Song.als")) == "Song"
    assert watch.als_project(Path("/x/Song Project/Backup/Song [2026].als")) == "Song"
    assert watch.als_project(Path("/x/Loose/idea.als")) == "Loose"


def test_ableton_findings_only_today(tmp_path):
    import os
    proj = tmp_path / "Tune Project"
    (proj / "Backup").mkdir(parents=True)
    today = date(2026, 9, 28)
    noon = datetime.combine(today, time(12)).timestamp()
    for name, t in [("Tune.als", noon), ("Backup/Tune [a].als", noon - 600)]:
        p = proj / name
        p.write_text("x")
        os.utime(p, (t, t))
    old = tmp_path / "Old Project"
    old.mkdir()
    (old / "Old.als").write_text("x")
    os.utime(old / "Old.als", (noon - 3 * 86400,) * 2)
    arch = tmp_path / "OLD SYSTEM" / "Arch Project"
    arch.mkdir(parents=True)
    (arch / "Arch.als").write_text("x")
    os.utime(arch / "Arch.als", (noon,) * 2)

    got = watch.ableton_findings({"roots": [str(tmp_path)], "skip": ["OLD SYSTEM"],
                                  "domain": "production"}, today)
    assert [f["key"] for f in got] == ["als:Tune"]
    assert got[0]["amount"] == 10 + watch.LEAD_MIN and got[0]["unit"] == "minutes"


def test_findings_pass_server_validation():
    """What the watcher emits must be what /propose accepts."""
    from interfaces.proposals import validate
    f = {"key": "git:x", "domain": "coding", "summary": "x: 1 commit(s), ~20 min — y",
         "amount": 20, "unit": "minutes"}
    assert validate(f, ["coding"])["amount"] == 20.0


def test_git_is_one_proposal_with_union_minutes():
    t0 = 1_000_000.0
    f = watch.git_summary({"a": 5, "b": 2, "c": 1, "d": 1}, [t0, t0 + 600, t0 + 1200],
                          "coding", date(2026, 9, 28))
    assert f["key"] == "git:2026-09-28"
    assert f["summary"].startswith("9 commit(s) in a, b, c +1")
    assert f["amount"] == 20 + watch.LEAD_MIN     # parallel repos don't add up
