# life-os-app

Automation layer for a personal life operating system. The data layer is a
markdown/YAML file tree (the `Life-OS` sibling repo); this app reads it, builds a
deterministic daily plan, and exposes it through a Telegram bot, a web hub, a
JSON API, and an MCP server.

**Governing principle:** AI may interpret language. AI may **not** make
scheduling decisions. The scheduling path is fully deterministic and testable;
model calls are confined to language tasks (`/ai` notes, `/evening`).

**Status:** live on a small Ubuntu VPS. Push to `master` → the box auto-deploys
in about a minute, **gated by pytest** (a red suite refuses the restart and
fires a Telegram alert). Developed on macOS; the VPS is the only deployment.

_Last verified: 2026-08-26 — `./verify fast` green, 280 tests._

## Layout

- `bot.py` + `bot_handlers/` — the Telegram bot (long-polling on the VPS).
- `scheduler/` — the deterministic core, no model calls anywhere in it:
  - `compile_queue.py` — four task sources + logs → `schedule/queue.yaml`
    (urgency, eligibility, dependencies, lint).
  - `schedule.py` — placement (fixed anchors → mandatory floors → priority fill
    → carry). `day.py`, `goals.py` — the two plan modes.
  - `restday.py` — the screen-free-day primitive (closes screen-bound slots on
    configured weekdays via the same off-day path as `days.py`).
  - `fileio.py` — **the safe write layer**; every data-tree write goes through
    it (atomic + advisory lock).
  - `tasks_parser.py`, `logs.py`, `urgency.py`, `days.py`, `mode.py`,
    `day_template.py`, `models.py`, `constants.py`, `domains.py`.
- `dashboard/` — the FastAPI web hub:
  - `app.py` — server-rendered pages (Today, Domains, Logs, System, Overview),
    the JSON read API, and `/health`.
  - `overview_data.py` — `build_overview()`, shared by the HTML page and
    `GET /api/overview` so the two surfaces cannot drift.
  - `groups.py` — domain umbrella grouping (presentation overlay; the scheduler
    stays flat).
  - `write.py` — the append-only write primitives, exposed on two surfaces
    (see below). `ratelimit.py` — per-client sliding windows.
- `metrics/aggregate.py` — progress aggregation (series, streaks, adherence).
- `mcp_server.py` — MCP server: read tools plus write tools that POST to the
  write API. Works on MCP SDK **1.x and 2.x** (compat import; do not pin `mcp<2`).
- `deploy/` — systemd units, `Caddyfile(.hidden)`, `bin/` scripts,
  `install-services.sh`, `bootstrap.sh`.
- `verify` — the QC entry point (`./verify fast`): leak gate, IP gate, tests.

## The three HTTP surfaces

| Surface | Auth | For |
|---|---|---|
| `GET /api/*` | Bearer **or** session cookie | reads; the browser hub uses the cookie so no token lives in client JS |
| `POST /api/write/*` | **Bearer only** | programmatic writers (MCP, watchers, scripts) |
| `POST /api/sw/*` | session cookie **+ CSRF guard** | the browser hub's writes |

Both write surfaces call the same primitives, so they cannot drift in what they
permit. Scope is enforced by **absence**: the primitives only append to
`daily/logs/`, `daily/reviews/`, `ingest/` and `inbox.md` — there is no endpoint
that can reach the vault, thresholds, schema, derived state, skills, or `dev/`.
Both are rate-limited per client (failed-auth budget checked *before* the token
compare; a separate successful-write budget). `GET /health` is unauthenticated —
the auto-deploy poller reads its `rev`; do not change its shape.

The hub is served behind a **secret path prefix** (`LIFE_OS_HUB_PREFIX`) so the
domain root is free for a separate public site. Caddy strips the prefix before
proxying, so the app runs as a normal root app — **do not set FastAPI
`root_path`** (it makes `StaticFiles` expect a prefix Caddy already removed).
A React hub (`life-os-web`) is served as a static bundle under that prefix's
`/app` subtree; the server-rendered pages remain the fallback while surfaces
migrate one at a time.

## Setup

```bash
python3 -m venv venv
venv/bin/pip install -r requirements.txt
# create .env — never committed
```

`.env` keys: `LIFE_OS_ROOT` (path to the data tree), `TELEGRAM_BOT_TOKEN`,
`TELEGRAM_CHAT_ID`, `ANTHROPIC_API_KEY`, `RESEND_API_KEY`, `EMAIL_FROM`,
`EMAIL_TO`, `LIFE_OS_DASHBOARD_TOKEN` (read + session login),
`LIFE_OS_WRITE_TOKEN` (write API; separate, higher-privilege),
`LIFE_OS_HUB_PREFIX`.

## Running

```bash
venv/bin/python morning.py                 # compile, plan, write daily/README.md, email
venv/bin/python bot.py                     # the bot (long-polling)
venv/bin/uvicorn dashboard.app:app --port 8000   # the hub, locally
venv/bin/python -m pytest -q               # tests
./verify fast                              # tests + leak/IP gates (what CI runs)
```

## Bot commands

| Command | What it does |
|---------|--------------|
| `/plan` | Recompute today and show it (blocks mode: the schedule; goals mode: the ranked list). |
| `/behind` | Drop a scheduled task for today; the day reshuffles. |
| `/add` | Pin a carried task into the day. |
| `/skip` | Skip a block for today; resets overnight. |
| `/move <block> <HH:MM-HH:MM>` | Retime a block for today, with a conflict menu. |
| `/extend [N]` | Extend the in-progress block (default 30 min). |
| `/clearday` | Clear today's block edits. |
| `/log [domain] <text>` | Record a completed entry in today's log. |
| `/note [domain] <text>` · `/ai <text>` | Save an ingest note (`/ai` tags + cleans it). |
| `/review` | Capture a messy daily/weekly review. |
| `/edit inbox <text>` | Append to `inbox.md`. |
| `/edit threshold <domain>.<field> <value>` | Update a numeric threshold. |
| `/domain list` | List the known domains. |
| `/mode <goals\|blocks>` | Switch plan mode. |
| `/evening <brief>` | Summarize the evening into the day's log. |
| `/commands`, `/start` | Help; connectivity check. |

Check-ins offer **Done / Partial / Reschedule** and write a log entry carrying
the block's `task:` id, so cadence-debt and dependencies resolve.

## The scheduling model (brief)

`compile()` reads four task sources plus the logs:

- `thresholds.yaml` — recurring per-domain tasks (Type 4).
- `domains/<d>/tasks.md` — authored task records (Type 3).
- `inbox.md` — quick tasks (Type 1; Type 2 when a line carries a `due:` date).
- `daily/logs/` — completion history → urgency and dependency clearing.

Urgency = deadline proximity + cadence-debt, and can promote a `normal` task
above a `high` one. In **blocks** mode the scheduler places at most one task per
block from the day template; in **goals** mode (current) it emits a ranked list.
Domain-level `days:` constrains eligible weekdays. See `SYSTEM.md` and
`DOMAIN-FORMAT.md` in the data tree for the authoring contract.

## Notes

- **Script-owned files** (the only files this app writes): `daily/README.md`,
  `daily/logs/`, `daily/reviews/`, `schedule/queue.yaml`,
  `schedule/today-state.yaml`, plus bot/API-writable targets (`ingest/`,
  `inbox.md` appends, threshold value updates). Everything else in the data tree
  belongs to authoring sessions (the domain-walkthrough skill).
- **Derived state** (`schedule/queue.yaml`, `today-state.yaml`) is untracked and
  self-heals by recompiling. Edit the sources, never the queue.
- **Secrets** live only in `.env` (git-ignored). `httpx` request logging is
  raised to WARNING so tokens stay out of logs.
- **This repo is public.** No machine-absolute paths, usernames, or IP literals
  in tracked files — `./verify` has a leak gate and an IP gate that enforce it.
