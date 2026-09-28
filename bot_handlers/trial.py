"""Telegram surfaces for the interface trial (2026-09-28).

Three surfaces, same layering as review.py — pure helpers up top, thin
telegram factories below, bot.py injecting its auth/root helpers so this module
never imports bot.py:

  1. MORNING CARD — pushed at `morning_time`: energy → pull → "anything
     specific?", three taps, answered half-awake. The reply is the day SIZED by
     those taps. That immediate payoff is the design: the evening review prompt
     asked for effort and gave nothing back, and went unanswered for months.
  2. EVENING SWEEP — at `sweep_time`, only when there is something to say:
     watcher findings to confirm with one tap each, and (if a card was printed
     today) a nudge to photograph it. A sweep with nothing in it is not sent.
  3. PAPER READ-BACK — send a photo of the day's card; a vision call reads the
     ticks, `card.validate_read` keeps only real task IDs, and NOTHING is logged
     until the owner taps Confirm.

Every write carries `via` (telegram | paper | watcher) so the trial can be
judged by counts. Callback prefixes: mc: (morning) · wt: (watcher sweep) ·
pc: (paper confirm) — chosen not to collide with the existing ci/sk/ex/ev/sh/
dn/mv/rm/ad set.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta

from interfaces import card, morning, proposals
from interfaces.config import load as load_cfg

logger = logging.getLogger(__name__)

_ENERGY_LABEL = {"foggy": "🌫 foggy", "steady": "🙂 steady", "sharp": "⚡ sharp"}

# Sweep messages → the proposal keys they offered, by message id. In-memory on
# purpose (same as review.PROMPT_IDS): a sweep is a same-evening interaction,
# and after a restart the /sweep command simply re-sends it.
SWEEP_KEYS: dict = {}


# --- pure --------------------------------------------------------------------

def _at(day: date, hhmm: str) -> datetime:
    h, m = str(hhmm).split(":")
    return datetime.combine(day, datetime.min.time()).replace(hour=int(h), minute=int(m))


def trial_fire_times(cfg: dict, today: date, now: datetime) -> list:
    """[(kind, datetime)] for today's trial pushes, filtered to the future."""
    out = []
    for kind, key in (("morning", "morning_time"), ("sweep", "sweep_time")):
        try:
            when = _at(today, cfg[key])
        except (ValueError, KeyError, AttributeError):
            continue                       # a bad time in the config skips, never crashes
        if when > now:
            out.append((kind, when))
    return out


def pull_options(umbrellas: list) -> list:
    """[(label, callback_value)] — umbrellas that have domains, then 'nowhere'."""
    return [(u["label"], u["key"]) for u in umbrellas if u.get("domains")] + \
           [("nowhere in particular", "-")]


def split_focus(text: str) -> list:
    parts = [p.strip(" •-\t") for chunk in text.split("\n") for p in chunk.split(";")]
    return [p for p in parts if p][:5]


def sweep_text(items: list, card_printed: bool) -> str:
    lines = ["🌙 Evening sweep."]
    if items:
        lines.append("")
        lines.append("Today I noticed — tap what's true:")
        for i, it in enumerate(items, 1):
            lines.append(f"  {i}. {it['summary']}  ({it['domain']})")
    if card_printed:
        lines.append("")
        lines.append("You printed a card today — send me a photo of it and I'll read the ticks.")
    return "\n".join(lines)


# --- telegram factories ------------------------------------------------------

def _kb(rows):
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    return InlineKeyboardMarkup([[InlineKeyboardButton(t, callback_data=d) for t, d in row]
                                 for row in rows])


def _energy_markup():
    return _kb([[(_ENERGY_LABEL[e], f"mc:e:{e}") for e in morning.ENERGY]])


_MORNING_Q = "☀️ Morning. How's the engine today?"


def build_send_morning_card(get_token, get_chat_id):
    async def send_morning_card() -> None:
        from telegram import Bot
        bot = Bot(token=get_token())
        async with bot:
            await bot.send_message(chat_id=get_chat_id(), text=_MORNING_Q,
                                   reply_markup=_energy_markup())
    return send_morning_card


def build_cmd_morning(is_authorized):
    async def cmd_morning(update, context) -> None:
        if not is_authorized(update):
            return
        await update.message.reply_text(_MORNING_Q, reply_markup=_energy_markup())
    return cmd_morning


def _finish(root, energy, pull, focus, via="telegram"):
    """Record + render. Returns the reply text (the check-in's payoff)."""
    morning.record_morning(root, energy, None if pull == "-" else pull, focus, via=via)
    shaped = morning.shape_for(root, date.today(), energy,
                               None if pull == "-" else pull, focus)
    from dashboard.write import _card_url
    return morning.render_day_text(shaped, _card_url())


def build_morning_callback(get_chat_id, root_fn):
    async def morning_callback(update, context) -> None:
        q = update.callback_query
        if q.message.chat.id != get_chat_id():
            return
        await q.answer()
        parts = q.data.split(":")
        step = parts[1] if len(parts) > 1 else ""
        if step == "e" and parts[2] in morning.ENERGY:
            from dashboard.groups import load_umbrellas
            opts = pull_options(load_umbrellas(root_fn()))
            rows = [[(label, f"mc:p:{parts[2]}:{val}")] for label, val in opts]
            await q.edit_message_text(
                f"{_ENERGY_LABEL[parts[2]]} — got it.\nWhere's your attention pulled?",
                reply_markup=_kb(rows))
        elif step == "p" and len(parts) == 4:
            energy, pull = parts[2], parts[3]
            await q.edit_message_text(
                "Anything specific you want today to be about?",
                reply_markup=_kb([[("no — size my day", f"mc:f:{energy}:{pull}:no")],
                                  [("yes, I'll type it", f"mc:f:{energy}:{pull}:yes")]]))
        elif step == "f" and len(parts) == 5:
            energy, pull, choice = parts[2], parts[3], parts[4]
            if choice == "yes":
                context.user_data["morning_focus"] = {"energy": energy, "pull": pull}
                await q.edit_message_text(
                    "Go ahead — send today's goals in one message (separate with ; or new lines).")
                return
            try:
                await q.edit_message_text(_finish(root_fn(), energy, pull, None))
            except Exception as e:           # a check-in must degrade, never vanish
                logger.exception("morning check-in failed")
                await q.edit_message_text(f"Couldn't record that check-in: {e}")
    return morning_callback


def build_focus_capture(is_authorized, root_fn):
    """The typed 'specific goals' reply after choosing 'yes, I'll type it'."""
    async def focus_capture(update, context) -> None:
        if not is_authorized(update):
            return
        state = context.user_data.get("morning_focus")
        if not state or not update.message or not update.message.text:
            return
        context.user_data.pop("morning_focus", None)
        focus = split_focus(update.message.text)
        await update.message.reply_text(_finish(root_fn(), state["energy"], state["pull"], focus))
    return focus_capture


# --- evening sweep -------------------------------------------------------------

def _sweep_markup(items):
    rows = [[(f"✓ {i}", f"wt:y:{i - 1}"), (f"✗ {i}", f"wt:n:{i - 1}")]
            for i in range(1, len(items) + 1)]
    if len(items) > 1:
        rows.append([("✓ all of them", "wt:all")])
    return _kb(rows)


async def _send_sweep(send, root, force=False):
    today = date.today()
    items = proposals.open_items(root, today)
    printed = card.was_viewed(today)
    if not items and not printed:
        if force:
            await send("🌙 Nothing noticed today, and no card was printed.", None)
        return
    msg = await send(sweep_text(items, printed), _sweep_markup(items) if items else None)
    if items and msg is not None:
        SWEEP_KEYS[msg.message_id] = [i["key"] for i in items]


def build_send_sweep(get_token, get_chat_id, root_fn):
    async def send_sweep() -> None:
        from telegram import Bot
        bot = Bot(token=get_token())
        async with bot:
            async def send(text, markup):
                return await bot.send_message(chat_id=get_chat_id(), text=text,
                                              reply_markup=markup)
            await _send_sweep(send, root_fn())
    return send_sweep


def build_cmd_sweep(is_authorized, root_fn):
    async def cmd_sweep(update, context) -> None:
        if not is_authorized(update):
            return
        async def send(text, markup):
            return await update.message.reply_text(text, reply_markup=markup)
        await _send_sweep(send, root_fn(), force=True)
    return cmd_sweep


def _confirm(root, day, key, append_log_entry):
    item = proposals.set_status(root, day, key, "confirmed")
    if item is None:
        return None
    entry = {"date": day.isoformat(), "domain": item["domain"], "outcome": "done",
             "covered": item["summary"], "via": "watcher"}
    if item.get("amount") and item.get("unit"):
        entry["duration"] = f"{item['amount']:g} {item['unit']}"
    append_log_entry(entry)
    return item


def build_sweep_callback(get_chat_id, root_fn, append_log_entry):
    async def sweep_callback(update, context) -> None:
        q = update.callback_query
        if q.message.chat.id != get_chat_id():
            return
        await q.answer()
        keys = SWEEP_KEYS.get(q.message.message_id)
        if not keys:
            await q.edit_message_text("That sweep has expired — send /sweep for a fresh one.")
            return
        root, today = root_fn(), date.today()
        parts = q.data.split(":")
        if parts[1] == "all":
            done = [k for k in keys if _confirm(root, today, k, append_log_entry)]
            await q.edit_message_text(f"✅ Logged all {len(done)} — thanks.")
            SWEEP_KEYS.pop(q.message.message_id, None)
            return
        idx = int(parts[2])
        if not 0 <= idx < len(keys):
            return
        if parts[1] == "y":
            item = _confirm(root, today, keys[idx], append_log_entry)
            note = f"✅ logged: {item['summary']}" if item else "already handled"
        else:
            proposals.set_status(root, today, keys[idx], "dismissed")
            note = "✗ dismissed"
        remaining = proposals.open_items(root, today)
        if remaining:
            SWEEP_KEYS[q.message.message_id] = [i["key"] for i in remaining]
            await q.edit_message_text(f"{note}\n\n{sweep_text(remaining, False)}",
                                      reply_markup=_sweep_markup(remaining))
        else:
            SWEEP_KEYS.pop(q.message.message_id, None)
            await q.edit_message_text(f"{note}\n\nAll caught up for today.")
    return sweep_callback


# --- paper read-back ---------------------------------------------------------

def _known_ids(root) -> dict:
    """{task_id: Task} for everything in the compiled queue."""
    from scheduler.compile_queue import load_queue
    try:
        tasks, _l, _g = load_queue(root)
    except OSError:
        tasks = []
    return {t.id: t for t in tasks}


def build_photo_handler(is_authorized, root_fn):
    async def photo_handler(update, context) -> None:
        if not is_authorized(update) or not update.message or not update.message.photo:
            return
        await update.message.reply_text("📸 Reading your card…")
        f = await update.message.photo[-1].get_file()           # largest size
        data = bytes(await f.download_as_bytearray())
        try:
            raw = await asyncio.to_thread(card.read_card, data, "image/jpeg")
        except Exception as e:
            logger.exception("card read failed")
            await update.message.reply_text(f"Couldn't read that photo: {e}")
            return
        known = _known_ids(root_fn())
        read = card.validate_read(raw, set(known))
        if not read["done"] and not read["unknown"]:
            await update.message.reply_text(
                "I didn't find any ticked rows on a card in that photo. "
                "Try again with the whole card in frame and decent light.")
            return
        lines = ["Here's what I read — nothing is logged until you confirm:"]
        for d in read["done"]:
            mins = f" · {d['minutes']:g} min" if d["minutes"] else ""
            lines.append(f"  ✓ {known[d['id']].title}{mins}")
        if read["unknown"]:
            lines.append("")
            lines.append("Couldn't match (ignored): " + ", ".join(read["unknown"]))
        if read["energy"]:
            lines.append(f"\nCircled energy: {read['energy']}")
        if read["note"]:
            lines.append(f"Note: {read['note']}")
        context.user_data["card_read"] = read
        markup = _kb([[("✅ confirm", "pc:ok"), ("✗ cancel", "pc:no")]]) if read["done"] else None
        await update.message.reply_text("\n".join(lines), reply_markup=markup)
    return photo_handler


def build_paper_callback(get_chat_id, root_fn, append_log_entry, write_ingest_note):
    async def paper_callback(update, context) -> None:
        q = update.callback_query
        if q.message.chat.id != get_chat_id():
            return
        await q.answer()
        read = context.user_data.pop("card_read", None)
        if q.data == "pc:no" or not read:
            await q.edit_message_text("Discarded — nothing logged.")
            return
        root, today = root_fn(), date.today()
        known = _known_ids(root)
        for d in read["done"]:
            t = known.get(d["id"])
            if t is None:
                continue
            entry = {"date": today.isoformat(), "task": t.id, "outcome": "done",
                     "covered": t.title, "via": "paper"}
            if t.domain:
                entry["domain"] = t.domain
            if d["minutes"]:
                entry["duration"] = f"{d['minutes']:g} min"
            append_log_entry(entry)
        if read["energy"] and morning.read_today(root, today) is None:
            morning.record_morning(root, read["energy"], via="paper")
        if read["note"]:
            write_ingest_note("", f"[paper card {today.isoformat()}] {read['note']}")
        await q.edit_message_text(f"✅ Logged {len(read['done'])} from your card.")
    return paper_callback
