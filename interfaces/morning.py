"""The morning check-in: record the owner's read of the day, then SIZE the plan.

Three dials, all set by the human:
  * energy — foggy | steady | sharp  (a coarse read on executive function; words
             on purpose, because a 1–5 number implies precision the read lacks)
  * pull   — where attention is drawn: an umbrella key, a domain, or nothing
  * focus  — optional free-text "today is about X" goals, in the owner's words

What the dials DO is deliberately presentational. The engine's ranked list
(`split_goals` over the compiled queue) is never re-ranked here. Energy caps how
much of it is shown and which amount is shown (floor vs aspirational, both read
straight from thresholds / task records — no invented numbers). Pull groups the
pulled domains' items FIRST, engine order preserved inside each group. That
keeps the one rule intact: the human sets dials, the engine decides placement,
this module only decides what to show.

Records append to `daily/morning/YYYY-MM-DD.md` (one stanza per check-in, via the
fileio safe-write layer), each tagged with the surface that produced it.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from scheduler.fileio import locked_append_text

ENERGY = ("foggy", "steady", "sharp")

#: How much of the engine's ranked list a morning of each energy gets to see.
#: None = all of it. The ORDER is always the engine's; only the length changes.
CAPS = {"foggy": 3, "steady": 5, "sharp": None}

VIAS = ("telegram", "claude", "paper", "watcher", "hub", "mcp", "cli")

_UNIT = {"minutes": "min", "words": "words", "pages": "pages",
         "sessions": "session", "planning-session": "planning session"}


# --- pure --------------------------------------------------------------------

def resolve_pull(pull: Optional[str], umbrellas: list, domains: list):
    """(label, {domains}) for a pull choice, or None for no pull.

    Accepts an umbrella key ("craft"), an umbrella label ("Craft & Art"), or a
    single domain name. Anything unrecognised is treated as no pull rather than
    an error — a mistyped pull should never block a morning check-in.
    """
    if not pull or str(pull).strip().lower() in ("none", "nowhere", "-"):
        return None
    p = str(pull).strip()
    for u in umbrellas:
        if p.lower() in (str(u.get("key", "")).lower(), str(u.get("label", "")).lower()):
            return u["label"], set(u.get("domains") or [])
    if p in domains:
        return p, {p}
    return None


def _fmt(n) -> str:
    return f"{n:g}" if isinstance(n, (int, float)) else str(n)


def item_amount(task, thresholds: dict, energy: str) -> str:
    """The amount to show for one item, sized by energy. '' when unknown.

    Type-3 records carry their own `min`/`duration`; recurring (Type-4) items
    read the domain's threshold `min|floor` / `aspirational`. Foggy shows the
    floor, sharp the aspiration, steady the honest range between them.
    """
    if getattr(task, "type", None) == 4:
        cfg = thresholds.get(task.domain) or {}
        lo = cfg.get("min", cfg.get("floor"))
        hi = cfg.get("aspirational", cfg.get("target"))
        unit = _UNIT.get(cfg.get("unit"), cfg.get("unit") or "")
    else:
        lo, hi, unit = getattr(task, "min", None), getattr(task, "duration", None), "min"
    if energy == "foggy":
        val = lo if lo is not None else hi
        return f"{_fmt(val)} {unit}".strip() if val is not None else ""
    if energy == "sharp":
        val = hi if hi is not None else lo
        return f"{_fmt(val)} {unit}".strip() if val is not None else ""
    if lo is not None and hi is not None and lo != hi:
        return f"{_fmt(lo)}–{_fmt(hi)} {unit}".strip()
    val = lo if lo is not None else hi
    return f"{_fmt(val)} {unit}".strip() if val is not None else ""


def shape_day(live: list, thresholds: dict, umbrellas: list, domains: list,
              energy: str, pull: Optional[str] = None,
              focus: Optional[list] = None) -> dict:
    """Size the engine's ranked `live` list for one morning. Pure.

    Returns {"energy", "focus", "pull": {"label", "items"} | None, "rest",
    "hidden"}. Items are {"id","domain","title","amount"}.
    """
    if energy not in ENERGY:
        raise ValueError(f"energy must be one of {ENERGY}")
    pulled = resolve_pull(pull, umbrellas, domains)
    pulled_domains = pulled[1] if pulled else set()

    def item(t):
        return {"id": t.id, "domain": t.domain, "title": t.title,
                "amount": item_amount(t, thresholds, energy)}

    first = [t for t in live if t.domain in pulled_domains]
    others = [t for t in live if t.domain not in pulled_domains]
    ordered = first + others                    # engine order kept within each
    cap = CAPS[energy]
    shown = ordered if cap is None else ordered[:cap]
    shown_ids = {t.id for t in shown}
    return {
        "energy": energy,
        "focus": [f for f in (focus or []) if str(f).strip()],
        "pull": ({"label": pulled[0],
                  "items": [item(t) for t in first if t.id in shown_ids]}
                 if pulled else None),
        "rest": [item(t) for t in others if t.id in shown_ids],
        "hidden": len(ordered) - len(shown),
    }


_OPENERS = {"foggy": "A floors-only day.",
            "steady": "A steady day.",
            "sharp": "A full-strength day."}


def render_day_text(shaped: dict, card_url: Optional[str] = None) -> str:
    """Plain text for Telegram / MCP replies — the check-in's immediate payoff."""
    lines = [f"{_OPENERS[shaped['energy']]} Here's today, sized for it:"]
    if shaped["focus"]:
        lines.append("")
        lines.append("Your call for today:")
        lines += [f"  • {f}" for f in shaped["focus"]]
    n = 0

    def block(title, items):
        nonlocal n
        if not items:
            return
        lines.append("")
        lines.append(title)
        for it in items:
            n += 1
            amt = f" — {it['amount']}" if it["amount"] else ""
            lines.append(f"  {n}. {it['title']}{amt}")

    if shaped["pull"]:
        block(f"Where you're pulled ({shaped['pull']['label']}):", shaped["pull"]["items"])
        block("Also on the list:", shaped["rest"])
    else:
        block("On the list:", shaped["rest"])
    if n == 0 and not shaped["focus"]:
        lines.append("")
        lines.append("Nothing eligible in the plan today — a genuinely open day.")
    if shaped["hidden"]:
        lines.append("")
        lines.append(f"({shaped['hidden']} more held back for a {shaped['energy']} morning.)")
    if card_url:
        lines.append("")
        lines.append(f"Paper card: {card_url}")
    return "\n".join(lines)


def stanza(when: datetime, energy: str, pull: Optional[str], focus: Optional[list],
           note: Optional[str], via: str) -> str:
    lines = [f"## {when:%H:%M} · via {via}", "", f"- **energy:** {energy}"]
    if pull:
        lines.append(f"- **pull:** {pull}")
    if focus:
        lines.append(f"- **focus:** {'; '.join(str(f).strip() for f in focus if str(f).strip())}")
    if note and note.strip():
        lines.append(f"- **note:** {note.strip()}")
    return "\n".join(lines) + "\n\n"


_FIELD = re.compile(r"^- \*\*(\w+):\*\* (.*)$")


def parse_last(text: str) -> Optional[dict]:
    """The most recent stanza of a morning file as a dict, or None."""
    blocks = [b for b in re.split(r"(?m)^## ", text) if b.strip()]
    if not blocks:
        return None
    head, *rest = blocks[-1].splitlines()
    out = {"via": head.split("via", 1)[1].strip() if "via" in head else None}
    for line in rest:
        m = _FIELD.match(line.strip())
        if m:
            out[m.group(1)] = m.group(2)
    if "focus" in out:
        out["focus"] = [f.strip() for f in out["focus"].split(";") if f.strip()]
    return out if "energy" in out else None


# --- IO ----------------------------------------------------------------------

def morning_path(root: Path, day: date) -> Path:
    return Path(root) / "daily" / "morning" / f"{day.isoformat()}.md"


def record_morning(root: Path, energy: str, pull: Optional[str] = None,
                   focus: Optional[list] = None, note: Optional[str] = None,
                   via: str = "cli", when: Optional[datetime] = None) -> Path:
    """Append one check-in stanza. Validates the dials; never overwrites."""
    if energy not in ENERGY:
        raise ValueError(f"energy must be one of {ENERGY}")
    if via not in VIAS:
        raise ValueError(f"via must be one of {VIAS}")
    when = when or datetime.now()
    path = morning_path(root, when.date())
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        locked_append_text(path, f"# Morning check-ins — {when.date().isoformat()}\n\n")
    locked_append_text(path, stanza(when, energy, pull, focus, note, via))
    return path


def read_today(root: Path, day: date) -> Optional[dict]:
    try:
        return parse_last(morning_path(root, day).read_text(encoding="utf-8"))
    except OSError:
        return None


def live_tasks(root: Path, day: date) -> list:
    """The engine's ranked live list for `day` — the only list we ever shape."""
    from scheduler.compile_queue import load_queue
    from scheduler.goals import split_goals
    try:
        tasks, _lint, _gen = load_queue(root)
    except OSError:
        return []
    _anchors, live, _waiting, _blocked = split_goals(tasks, day)
    return live


def shape_for(root: Path, day: date, energy: str, pull: Optional[str] = None,
              focus: Optional[list] = None) -> dict:
    """shape_day over the real tree: engine list + thresholds + umbrellas."""
    from dashboard.groups import load_umbrellas
    from scheduler.domains import list_domains, read_thresholds
    umbrellas = [u for u in load_umbrellas(root) if u.get("domains")]
    return shape_day(live_tasks(root, day), read_thresholds(root) or {},
                     umbrellas, list_domains(root), energy, pull, focus)
