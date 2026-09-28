"""Interface-trial scoreboard: which surfaces the owner actually used.

    venv/bin/python -m interfaces.report                 # trial start → today
    venv/bin/python -m interfaces.report 2026-09-28 2026-10-05

Counts, per `via`, over an inclusive date range:
  * check-ins   — stanzas in daily/morning/<day>.md
  * completions — log entries with outcome done|partial (untagged = pre-trial
                  or a writer that doesn't tag yet; shown, never guessed at)
  * proposals   — watcher findings by status (confirmed / dismissed / open)
Read-only and deterministic — this measures, it doesn't judge. The baseline it
is measured against: zero completions in the 90 days before 2026-09-28.
"""
from __future__ import annotations

import re
import sys
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

import yaml

TRIAL_START = date(2026, 9, 28)
_FIELD = re.compile(r"^- \*\*(\w+):\*\* (.*)$", re.M)


def _days(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _read(p: Path) -> str:
    try:
        return p.read_text(encoding="utf-8")
    except OSError:
        return ""


def tally(root: Path, start: date, end: date) -> dict:
    checkins, done, props = Counter(), Counter(), Counter()
    days_active = set()
    for d in _days(start, end):
        for block in re.split(r"(?m)^## ", _read(root / "daily" / "morning" / f"{d}.md")):
            head = block.splitlines()[0] if block.strip() else ""
            if "via" in head:
                checkins[head.split("via", 1)[1].strip()] += 1
                days_active.add(d)
        # A log file can hold stanzas for other dates; the file's own day is
        # the day it was written, which is what "did I use it today" means.
        for block in re.split(r"(?m)^## ", _read(root / "daily" / "logs" / f"{d}.md")):
            f = dict(_FIELD.findall(block))
            if f.get("outcome") in ("done", "partial"):
                done[f.get("via", "untagged")] += 1
                days_active.add(d)
        try:
            items = yaml.safe_load(_read(root / "daily" / "proposals" / f"{d}.yaml")) or []
        except yaml.YAMLError:
            items = []
        for i in items if isinstance(items, list) else []:
            props[i.get("status", "open")] += 1
    return {"start": start, "end": end, "checkins": dict(checkins),
            "completions": dict(done), "proposals": dict(props),
            "days_active": len(days_active), "days": (end - start).days + 1}


def render(t: dict) -> str:
    vias = sorted(set(t["checkins"]) | set(t["completions"]))
    rows = [f"Interface trial {t['start']} → {t['end']}  "
            f"({t['days_active']}/{t['days']} days with any use)", "",
            f"{'via':<10}{'check-ins':>10}{'completions':>13}"]
    for v in vias:
        rows.append(f"{v:<10}{t['checkins'].get(v, 0):>10}{t['completions'].get(v, 0):>13}")
    if not vias:
        rows.append("(nothing yet)")
    p = t["proposals"]
    rows += ["", f"watcher proposals: {p.get('confirmed', 0)} confirmed · "
                 f"{p.get('dismissed', 0)} dismissed · {p.get('open', 0)} unanswered"]
    return "\n".join(rows)


if __name__ == "__main__":
    from utils import get_life_os_root
    a = [date.fromisoformat(x) for x in sys.argv[1:3]]
    start = a[0] if a else TRIAL_START
    end = a[1] if len(a) > 1 else date.today()
    print(render(tally(get_life_os_root(), start, end)))
