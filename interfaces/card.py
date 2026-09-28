"""The paper index card: what to print in the morning, how to read it back.

Printing is presentation of `morning.shape_for` — the same sized list the
Telegram and Claude surfaces show, so the three stay comparable. Each row
carries its task ID in small print; that is what makes the photo readable
back into records without guessing which line was which.

Reading the photo back is the one place a model touches this trial, and it is
confined to INTERPRETATION: a vision call extracts which printed IDs are ticked
and any minutes written beside them. `validate_read` then keeps only IDs that
exist in today's plan, and nothing is logged until the owner taps Confirm. A
misread costs a correction, never a silent bad record.
"""
from __future__ import annotations

import base64
import json
import os
from datetime import date
from pathlib import Path
from typing import Optional

#: Pinned explicitly (doctrine: never inherit a tier). Reading ticks and
#: handwritten numbers off a printed card is extraction — Haiku-class work.
VISION_MODEL = "claude-haiku-4-5-20251001"

_CACHE = Path(os.path.expanduser("~")) / ".cache" / "life-os"


def card_items(shaped: dict) -> list:
    """Flatten a shaped day into numbered card rows, pull group first."""
    rows = (shaped["pull"]["items"] if shaped.get("pull") else []) + shaped["rest"]
    return [dict(r, n=i + 1) for i, r in enumerate(rows)]


# --- "was a card printed today?" — a marker OUTSIDE the data tree -----------
# The evening sweep uses it to decide whether to ask for a photo. Kept out of
# git on purpose: it is a UI hint, not a record, and must never churn the tree.

def mark_viewed(day: date) -> None:
    try:
        _CACHE.mkdir(parents=True, exist_ok=True)
        (_CACHE / f"card-{day.isoformat()}").touch()
    except OSError:
        pass


def was_viewed(day: date) -> bool:
    return (_CACHE / f"card-{day.isoformat()}").exists()


# --- reading the photo back ---------------------------------------------------

_PROMPT = """This is a photo of a printed daily index card. Each task row has a
checkbox, a title, and a small printed ID like `career-recurring` or `fitness-001`.
The owner ticks boxes by hand and may write minutes beside a row.

Return ONLY a JSON object, no prose:
{"is_card": true|false,
 "items": [{"id": "<printed id, copied exactly>", "checked": true|false,
            "minutes": <number or null>}],
 "energy": "<the circled word among foggy/steady/sharp, or null>",
 "note": "<any handwritten note, or null>"}
Include every row you can see. If this is not such a card, return
{"is_card": false, "items": []}."""


def read_card(image_bytes: bytes, media_type: str = "image/jpeg") -> dict:
    """One vision call → the raw JSON the model saw. Raises on API failure."""
    import anthropic
    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))
    msg = client.messages.create(
        model=VISION_MODEL, max_tokens=800,
        messages=[{"role": "user", "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type,
                                         "data": base64.b64encode(image_bytes).decode()}},
            {"type": "text", "text": _PROMPT},
        ]}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < 0:
        return {"is_card": False, "items": []}
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return {"is_card": False, "items": []}


def validate_read(raw: dict, known_ids: set) -> dict:
    """Keep only ticked rows whose ID is really in today's plan. Pure.

    Returns {"done": [{"id", "minutes"}], "unknown": [ids], "energy", "note"}.
    Unknown IDs are surfaced (never logged) so a misread is visible.
    """
    done, unknown = [], []
    if not isinstance(raw, dict) or not raw.get("is_card"):
        return {"done": [], "unknown": [], "energy": None, "note": None}
    for it in raw.get("items") or []:
        if not isinstance(it, dict) or not it.get("checked"):
            continue
        tid = str(it.get("id") or "").strip()
        mins = it.get("minutes")
        mins = float(mins) if isinstance(mins, (int, float)) and 0 < mins <= 24 * 60 else None
        (done if tid in known_ids else unknown).append({"id": tid, "minutes": mins})
    energy = raw.get("energy") if raw.get("energy") in ("foggy", "steady", "sharp") else None
    note = raw.get("note") if isinstance(raw.get("note"), str) and raw["note"].strip() else None
    return {"done": done, "unknown": [u["id"] for u in unknown], "energy": energy, "note": note}
