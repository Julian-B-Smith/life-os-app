"""Watcher proposals — things a Mac-side watcher NOTICED, awaiting one tap.

A watcher is a deterministic observer (file mtimes, git history); it never
logs anything itself. It proposes, and the owner confirms in Telegram. That
confirm step is the whole design: inferred activity is not trusted as a record
until a human says yes, so a noisy watcher can cost a tap but never corrupt the
log.

Store: `daily/proposals/YYYY-MM-DD.yaml`, rewritten atomically under a lock.
Re-reporting the same day is idempotent — findings are keyed, and a key's
status (open / confirmed / dismissed) survives re-runs, so a watcher that fires
twice can't resurrect something already confirmed or dismissed.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Optional

import yaml

from scheduler.fileio import atomic_write_text, file_lock

STATUSES = ("open", "confirmed", "dismissed")
_UNITS = (None, "minutes", "sessions", "words", "pages")


def proposals_path(root: Path, day: date) -> Path:
    return Path(root) / "daily" / "proposals" / f"{day.isoformat()}.yaml"


def _load(path: Path) -> list:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return []
    items = data.get("items") if isinstance(data, dict) else None
    return items if isinstance(items, list) else []


def validate(finding: dict, domains: list) -> dict:
    """One finding → a clean item, or ValueError naming what is wrong."""
    key = str(finding.get("key") or "").strip()
    summary = str(finding.get("summary") or "").strip()
    domain = finding.get("domain")
    if not key or len(key) > 120:
        raise ValueError("key required (≤120 chars)")
    if not summary or len(summary) > 200:
        raise ValueError("summary required (≤200 chars)")
    if domain not in domains:
        raise ValueError(f"unknown domain {domain!r}")
    unit = finding.get("unit")
    if unit not in _UNITS:
        raise ValueError(f"unit must be one of {_UNITS[1:]}")
    amount = finding.get("amount")
    if amount is not None:
        amount = float(amount)
        if amount < 0 or amount > 24 * 60:
            raise ValueError("amount out of range")
    return {"key": key, "domain": domain, "summary": summary,
            "amount": amount, "unit": unit}


def report(root: Path, day: date, findings: list, via: str = "watcher") -> list:
    """Upsert a day's findings. Existing keys keep their status."""
    path = proposals_path(root, day)
    path.parent.mkdir(parents=True, exist_ok=True)
    with file_lock(path):
        items = _load(path)
        by_key = {i.get("key"): i for i in items}
        for f in findings:
            prior = by_key.get(f["key"])
            if prior:
                prior.update({k: f[k] for k in ("domain", "summary", "amount", "unit")})
            else:
                new = dict(f, status="open", via=via)
                items.append(new)
                by_key[f["key"]] = new
        atomic_write_text(path, yaml.safe_dump({"date": day.isoformat(), "items": items},
                                               sort_keys=False, allow_unicode=True))
    return items


def open_items(root: Path, day: date) -> list:
    return [i for i in _load(proposals_path(root, day)) if i.get("status") == "open"]


def set_status(root: Path, day: date, key: str, status: str) -> Optional[dict]:
    """Mark one proposal; returns the item, or None if the key is unknown."""
    if status not in STATUSES:
        raise ValueError(f"status must be one of {STATUSES}")
    path = proposals_path(root, day)
    with file_lock(path):
        items = _load(path)
        hit = next((i for i in items if i.get("key") == key), None)
        if hit is None:
            return None
        hit["status"] = status
        atomic_write_text(path, yaml.safe_dump({"date": day.isoformat(), "items": items},
                                               sort_keys=False, allow_unicode=True))
    return hit
