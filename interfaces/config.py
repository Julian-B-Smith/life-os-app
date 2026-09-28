"""Trial configuration, read from the DATA tree (`schedule/interfaces.yaml`).

Why the data tree and not `.env`: the owner (or a session) can retune times by
editing one file and pushing — no SSH to the VPS needed — and the data repo is
private, so the public origin of the hub can live there without landing in this
public repo. Every key has a default; a missing or malformed file degrades to
the defaults rather than taking the bot down.
"""
from __future__ import annotations

from pathlib import Path

import yaml

DEFAULTS = {
    # Box-local wall-clock times (the VPS runs US Eastern — its 06:00 morning
    # timer's commits land at 10:00Z).
    "morning_time": "07:30",
    # Watcher confirmations. The Mac-side watcher reports at 20:30; the sweep
    # follows so the day's findings are in before it fires.
    "sweep_time": "20:45",
    # e.g. "https://example.org" — joined with LIFE_OS_HUB_PREFIX for links.
    "public_origin": None,
}


def load(root: Path) -> dict:
    cfg = dict(DEFAULTS)
    try:
        data = yaml.safe_load((Path(root) / "schedule" / "interfaces.yaml")
                              .read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return cfg
    if isinstance(data, dict):
        for k in DEFAULTS:
            if data.get(k) is not None:
                cfg[k] = data[k]
    return cfg
