"""Telegram trial surfaces — the deterministic half (no network)."""
from datetime import date, datetime

from bot_handlers import trial
from interfaces import proposals

D = date(2026, 9, 28)


def test_fire_times_are_future_only_and_survive_a_bad_config():
    cfg = {"morning_time": "07:30", "sweep_time": "20:45"}
    assert [k for k, _ in trial.trial_fire_times(cfg, D, datetime(2026, 9, 28, 6))] == \
        ["morning", "sweep"]
    assert [k for k, _ in trial.trial_fire_times(cfg, D, datetime(2026, 9, 28, 12))] == \
        ["sweep"]
    assert trial.trial_fire_times({"morning_time": "soon", "sweep_time": None}, D,
                                  datetime(2026, 9, 28, 6)) == []


def test_pull_options_skip_empty_umbrellas_and_offer_nowhere():
    umb = [{"key": "health", "label": "Health & Body", "domains": ["fitness"]},
           {"key": "all", "label": "All domains", "domains": []}]
    assert trial.pull_options(umb) == [("Health & Body", "health"),
                                       ("nowhere in particular", "-")]


def test_focus_splits_on_semicolons_and_lines_and_caps_at_five():
    assert trial.split_focus("send Cody a pass; 20 min synth\n• call mum") == \
        ["send Cody a pass", "20 min synth", "call mum"]
    assert len(trial.split_focus(";".join(str(i) for i in range(9)))) == 5


def test_sweep_text_mentions_the_card_only_when_one_was_printed():
    items = [{"summary": "4 commits to life-os-web", "domain": "coding"}]
    assert "photo" not in trial.sweep_text(items, False)
    assert "photo" in trial.sweep_text(items, True)


def test_confirm_logs_with_via_watcher_and_marks_the_proposal(tmp_path):
    f = proposals.validate({"key": "als:Tensegrity", "domain": "production",
                            "summary": "Tensegrity saved 3×", "amount": 45,
                            "unit": "minutes"}, ["production"])
    proposals.report(tmp_path, D, [f])
    logged = []
    item = trial._confirm(tmp_path, D, "als:Tensegrity", logged.append)
    assert item["status"] == "confirmed"
    assert logged == [{"date": "2026-09-28", "domain": "production", "outcome": "done",
                       "covered": "Tensegrity saved 3×", "via": "watcher",
                       "duration": "45 minutes"}]
    assert trial._confirm(tmp_path, D, "ghost", logged.append) is None
