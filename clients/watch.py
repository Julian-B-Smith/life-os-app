"""Passive watcher — the Mac-side half of the "you only confirm" interface.

Interface trial, 2026-09-28: the system had logged zero completions in 90 days
because every surface asked the owner to self-report. This script looks at
evidence the day already left behind — Ableton sets saved today, git commits
authored today — and PROPOSES it to Life-OS. It never logs. Proposals land in
daily/proposals/<day>.yaml via POST /api/write/propose; the evening Telegram
sweep asks the owner to confirm or dismiss each one, and only a confirm writes
a log entry (tagged via=watcher).

Deterministic by design (the one rule): no model calls, no ranking — it
reports what the filesystem and git say, plus a transparent minutes estimate.

Runs once each evening from launchd (clients/install-watch.sh), stdlib only,
so it works under any Python >= 3.11 without the app's venv.

Config: ~/.config/life-os/watch.toml (outside the repo — it names local
folders, which must never be committed). Example:

    [ableton]
    domain = "production"
    roots  = ["~/Music/Ableton Projects"]
    skip   = ["OLD SYSTEM"]          # folder names to ignore anywhere below a root

    [git]
    domain = "coding"
    roots  = ["~/Documents/Claude"]
    emails = ["you@example.com"]     # default: your global git user.email

Token: LIFE_OS_WRITE_TOKEN, else ~/.config/life-os/write-token (same as the MCP).

    python3 clients/watch.py --dry-run      # show what would be proposed
    python3 clients/watch.py                # propose today's findings
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tomllib
import urllib.error
import urllib.request
from datetime import date, datetime, time
from pathlib import Path

CONFIG = Path("~/.config/life-os/watch.toml").expanduser()
TOKEN_FILE = Path("~/.config/life-os/write-token").expanduser()
DEFAULT_URL = "https://mindlathe.xyz/lathe/api/write"

# Session estimate: events closer than GAP belong to one sitting; each sitting
# is credited its span plus LEAD (work happens before the first save/commit).
# Capped so a machine left saving all day can't claim 14 hours. The owner sees
# "~N min" and can dismiss a bad guess — the estimate is a hint, not a record.
GAP_MIN, LEAD_MIN, CAP_MIN = 45, 20, 240
# Directories never worth descending into when hunting for repos / sets.
PRUNE = {"node_modules", "venv", ".venv", "__pycache__", "dist", "build", ".git"}


# --- pure helpers (tested) --------------------------------------------------

def estimate_minutes(stamps: list[float]) -> int:
    """Epoch seconds → an estimated minutes-worked figure (see GAP/LEAD/CAP)."""
    if not stamps:
        return 0
    s = sorted(stamps)
    total, start, prev = 0.0, s[0], s[0]
    for t in s[1:]:
        if t - prev > GAP_MIN * 60:
            total += (prev - start) / 60 + LEAD_MIN
            start = t
        prev = t
    total += (prev - start) / 60 + LEAD_MIN
    return int(min(round(total), CAP_MIN))


def als_project(path: Path) -> str:
    """The project a .als belongs to. Ableton writes previous versions into a
    Backup/ folder inside the project, so a backup counts as a save of its
    parent project — useful, because backups carry the day's save times."""
    parent = path.parent
    if parent.name == "Backup":
        parent = parent.parent
    name = parent.name
    return name[: -len(" Project")] if name.endswith(" Project") else name


def day_bounds(day: date) -> tuple[float, float]:
    start = datetime.combine(day, time.min).timestamp()
    return start, start + 86400


# --- evidence gathering -----------------------------------------------------

def _walk(root: Path, skip: set, max_depth: int):
    """os.walk with pruning + a depth limit (the Documents tree is large)."""
    base = len(root.parts)
    for dirpath, dirnames, filenames in os.walk(root):
        depth = len(Path(dirpath).parts) - base
        dirnames[:] = [d for d in dirnames
                       if d not in PRUNE and d not in skip and not d.startswith(".")
                       and depth < max_depth]
        yield Path(dirpath), dirnames, filenames


def ableton_findings(cfg: dict, day: date) -> list[dict]:
    lo, hi = day_bounds(day)
    skip = set(cfg.get("skip", []))
    saves: dict[str, list[float]] = {}
    for r in cfg.get("roots", []):
        root = Path(r).expanduser()
        if not root.is_dir():
            continue
        for d, _, files in _walk(root, skip - {"Backup"}, max_depth=6):
            for f in files:
                if not f.endswith(".als"):
                    continue
                p = d / f
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if lo <= m < hi:
                    saves.setdefault(als_project(p), []).append(m)
    out = []
    for proj, stamps in sorted(saves.items()):
        mins = estimate_minutes(stamps)
        out.append({"key": f"als:{proj}"[:120], "domain": cfg.get("domain", "production"),
                    "summary": f"Ableton — {proj}: {len(stamps)} save(s), ~{mins} min"[:200],
                    "amount": mins, "unit": "minutes"})
    return out


def _git(repo: Path, *args: str) -> str:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=30)
    return r.stdout if r.returncode == 0 else ""


def git_findings(cfg: dict, day: date) -> list[dict]:
    emails = [e.lower() for e in cfg.get("emails", [])]
    if not emails:
        g = subprocess.run(["git", "config", "--global", "user.email"],
                           capture_output=True, text=True).stdout.strip()
        emails = [g.lower()] if g else []
    if not emails:
        return []
    lo, hi = day_bounds(day)
    per_repo: dict[str, int] = {}
    stamps: list[float] = []
    seen: set[Path] = set()
    for r in cfg.get("roots", []):
        root = Path(r).expanduser()
        if not root.is_dir():
            continue
        for d, dirnames, _ in _walk(root, set(), max_depth=int(cfg.get("max_depth", 3))):
            if not (d / ".git").exists() or d in seen:
                continue
            seen.add(d)
            # --all: work on unmerged branches counts too. %H dedupes across refs.
            log = _git(d, "log", "--all", f"--since=@{int(lo)}", f"--until=@{int(hi)}",
                       "--format=%H\t%ae\t%at")
            commits = {}
            for line in log.splitlines():
                parts = line.split("\t")
                if len(parts) == 3 and parts[1].lower() in emails:
                    commits[parts[0]] = float(parts[2])
            if commits:
                per_repo[d.name] = per_repo.get(d.name, 0) + len(commits)
                stamps += commits.values()
    return [git_summary(per_repo, stamps, cfg.get("domain", "coding"), day)] if per_repo else []


def git_summary(per_repo: dict[str, int], stamps: list[float], domain: str,
                day: date) -> dict:
    """ONE proposal per day for all repos, not one per repo: agent sessions run
    in parallel across repos, so per-repo minutes would double-count the same
    hour, and seven confirm taps a night is exactly the friction this trial
    exists to remove. Minutes come from the union of commit times."""
    top = sorted(per_repo.items(), key=lambda kv: (-kv[1], kv[0]))
    names = ", ".join(n for n, _ in top[:3]) + (f" +{len(top) - 3}" if len(top) > 3 else "")
    mins = estimate_minutes(stamps)
    return {"key": f"git:{day.isoformat()}", "domain": domain,
            "summary": f"{sum(per_repo.values())} commit(s) in {names}, ~{mins} min"[:200],
            "amount": mins, "unit": "minutes"}


# --- IO ---------------------------------------------------------------------

def _token() -> str:
    t = os.getenv("LIFE_OS_WRITE_TOKEN", "").strip()
    if t:
        return t
    try:
        return TOKEN_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def propose(url: str, findings: list[dict]) -> dict:
    token = _token()
    if not token:
        raise SystemExit(f"no write token: set LIFE_OS_WRITE_TOKEN or create {TOKEN_FILE}")
    req = urllib.request.Request(
        f"{url.rstrip('/')}/propose", method="POST",
        data=json.dumps({"findings": findings, "via": "watcher"}).encode(),
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        raise SystemExit(f"write API {e.code}: {e.read()[:300]!r}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--day", type=date.fromisoformat, default=date.today())
    ap.add_argument("--config", type=Path, default=CONFIG)
    a = ap.parse_args(argv)
    try:
        cfg = tomllib.loads(a.config.read_text(encoding="utf-8"))
    except FileNotFoundError:
        print(f"no config at {a.config} — see this file's docstring", file=sys.stderr)
        return 2
    findings = []
    if "ableton" in cfg:
        findings += ableton_findings(cfg["ableton"], a.day)
    if "git" in cfg:
        findings += git_findings(cfg["git"], a.day)
    stamp = datetime.now().isoformat(timespec="seconds")
    if not findings:
        print(f"{stamp} nothing to propose for {a.day}")
        return 0
    for f in findings:
        print(f"{stamp} {f['key']}: {f['summary']}")
    if a.dry_run:
        return 0
    res = propose(cfg.get("url", DEFAULT_URL), findings[:50])
    print(f"{stamp} proposed {len(findings)}; open now: {res.get('open')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
