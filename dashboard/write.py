"""Write API — append-only recording primitives (write-mcp.md Phase 1).

Authenticated by ``LIFE_OS_WRITE_TOKEN`` — a SEPARATE, higher-privilege secret
than the dashboard read token. Each endpoint is a constrained, validated
primitive that appends to the data tree via the existing writers; there is no
arbitrary-file-write path. Writes land in the tree and the 5-min sync timer
commits + pushes them (git = the audit log).

Hard scope (write-mcp.md): these primitives can only append to daily/logs,
ingest/, daily/reviews, and inbox.md — plus, for the interface trial
(2026-09-28), daily/morning/ (check-in stanzas) and daily/proposals/ (watcher
findings awaiting a human tap). They cannot touch the vault, thresholds,
schema, derived state, skills, or dev/ — there is simply no endpoint for it.

If ``LIFE_OS_WRITE_TOKEN`` is unset the whole write API is disabled (503) — a
write surface must never be open, unlike the read grace mode.

TWO SURFACES, ONE IMPLEMENTATION (SW-0, 2026-08-26)
---------------------------------------------------
The same four primitives are exposed twice, for two callers that authenticate
differently and cannot share a credential:

* ``/api/write/*`` — **Bearer only**. Programmatic clients (the MCP, watchers,
  scripts). A browser must never use this: it would mean a write token in
  client-side JS.
* ``/api/sw/*``    — **session cookie + CSRF guard**. The browser hub, so the
  UI can record without ever holding a token.

Both call the SAME `_do_*` primitives below, so the two surfaces cannot drift in
what they permit — the hard scope exclusions above hold identically for both.
Both pass through the same rate limiter.
"""
import hmac
import os
from datetime import date
from typing import Optional
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from pydantic import BaseModel

from bot_handlers.review import append_review
from dashboard.ratelimit import enforce_pre_auth, enforce_write, record_auth_failure
from scheduler.domains import list_domains
from interfaces import proposals as _proposals
from interfaces.config import load as _load_cfg
from interfaces.morning import VIAS, record_morning, render_day_text, shape_for
from utils import append_inbox, append_log_entry, get_life_os_root, write_ingest_note

router = APIRouter(prefix="/api/write", tags=["write"])

_OUTCOMES = ("done", "partial", "missed", "rescheduled")


def _write_token() -> str:
    return os.getenv("LIFE_OS_WRITE_TOKEN", "").strip()


def _dashboard_token() -> str:
    """The READ/session secret — gates the session-write surface's login."""
    return os.getenv("LIFE_OS_DASHBOARD_TOKEN", "").strip()


def require_write_token(request: Request,
                        authorization: Optional[str] = Header(default=None)) -> None:
    """Bearer-only gate for the write API, rate-limited (Phase 3 hardening).

    Order is deliberate:
      1. rate-limit check on FAILED-auth budget — refuses a brute-force burst
         BEFORE the token compare (cheap, no timing surface, no file work);
      2. token compare (constant-time); a miss burns the caller's fail budget;
      3. successful-write budget — a leaked-but-valid token cannot flood.
    Deliberately NOT session-cookie: this is state-changing, so cookie auth
    would be CSRF-able (see app.require_token for the read-side contrast).
    """
    tok = _write_token()
    if not tok:
        raise HTTPException(status_code=503,
                            detail="write API disabled (LIFE_OS_WRITE_TOKEN unset)")
    key = enforce_pre_auth(request)                       # 429 if fail budget burned
    if not authorization or not hmac.compare_digest(authorization, f"Bearer {tok}"):
        record_auth_failure(key)
        raise HTTPException(status_code=401, detail="missing or invalid write token",
                            headers={"WWW-Authenticate": "Bearer"})
    enforce_write(key)                                    # 429 if write budget burned


def _require_domain(domain: Optional[str]) -> None:
    if domain and domain not in list_domains(get_life_os_root()):
        raise HTTPException(status_code=422, detail=f"unknown domain {domain!r}")


class LogBody(BaseModel):
    domain: str
    outcome: str = "done"
    amount: Optional[float] = None
    unit: Optional[str] = None
    covered: Optional[str] = None
    task: Optional[str] = None
    via: Optional[str] = None      # which interface wrote this (trial measurement)


class MorningBody(BaseModel):
    energy: str                    # foggy | steady | sharp
    pull: Optional[str] = None     # umbrella key/label, a domain, or none
    focus: Optional[list[str]] = None
    note: Optional[str] = None
    via: str = "mcp"


class ProposeBody(BaseModel):
    findings: list[dict]
    via: str = "watcher"


class NoteBody(BaseModel):
    text: str
    domain: Optional[str] = None


class ReviewBody(BaseModel):
    text: str
    kind: str = "daily"


class InboxBody(BaseModel):
    text: str
    due: Optional[str] = None   # e.g. "hard 2026-07-15"


# --- the primitives: validated, bounded, surface-agnostic -------------------
# Each takes a validated body and performs ONE append. Both routers call these,
# so a permission or validation change lands on both surfaces at once.

def _do_log(b: "LogBody") -> dict:
    _require_domain(b.domain)
    if b.outcome not in _OUTCOMES:
        raise HTTPException(status_code=422, detail=f"outcome must be one of {_OUTCOMES}")
    entry = {"date": date.today().isoformat(), "outcome": b.outcome, "domain": b.domain}
    if b.covered:
        entry["covered"] = b.covered
    if b.task:
        entry["task"] = b.task
    if b.amount is not None and b.unit:
        # Canonical `duration:` field carries the unit (DOMAIN-FORMAT §2).
        entry["duration"] = f"{b.amount:g} {b.unit}"
    if b.via:
        if b.via not in VIAS:
            raise HTTPException(status_code=422, detail=f"via must be one of {VIAS}")
        entry["via"] = b.via
    append_log_entry(entry)
    return {"ok": True, "written": "daily/logs", "entry": entry}


def _do_note(b: "NoteBody") -> dict:
    _require_domain(b.domain)
    if not b.text.strip():
        raise HTTPException(status_code=422, detail="empty note text")
    rel = write_ingest_note(b.domain or "", b.text.strip())
    return {"ok": True, "written": rel}


def _do_review(b: "ReviewBody") -> dict:
    if b.kind not in ("daily", "weekly"):
        raise HTTPException(status_code=422, detail="kind must be 'daily' or 'weekly'")
    if not b.text.strip():
        raise HTTPException(status_code=422, detail="empty review text")
    path = append_review(get_life_os_root(), b.text.strip(), kind=b.kind)
    return {"ok": True, "written": path.name, "kind": b.kind}


def _do_inbox(b: "InboxBody") -> dict:
    text = b.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="empty inbox text")
    if b.due:
        text = f"{text} | due: {b.due.strip()}"
    append_inbox(text)
    return {"ok": True, "written": "inbox.md", "line": text}


def _card_url() -> Optional[str]:
    """Absolute link to the printable card, if the public origin is configured.

    The origin lives in the PRIVATE data tree (schedule/interfaces.yaml) and the
    hidden prefix in env — neither is ever written into this public repo.
    """
    origin = _load_cfg(get_life_os_root()).get("public_origin")
    if not origin:
        return None
    return f"{str(origin).rstrip('/')}{os.getenv('LIFE_OS_HUB_PREFIX', '').rstrip('/')}/card"


def _do_morning(b: "MorningBody") -> dict:
    """Record a check-in, then return the day sized by it — the payoff."""
    focus = [f.strip()[:200] for f in (b.focus or []) if f and f.strip()][:5]
    if b.note and len(b.note) > 1000:
        raise HTTPException(status_code=422, detail="note too long (≤1000 chars)")
    root = get_life_os_root()
    try:
        path = record_morning(root, b.energy, b.pull, focus, b.note, via=b.via)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    shaped = shape_for(root, date.today(), b.energy, b.pull, focus)
    return {"ok": True, "written": str(path.relative_to(root)), "day": shaped,
            "text": render_day_text(shaped, _card_url())}


def _do_propose(b: "ProposeBody") -> dict:
    """Watcher findings → the confirm queue. Nothing is logged here."""
    if len(b.findings) > 50:
        raise HTTPException(status_code=422, detail="at most 50 findings per report")
    if b.via not in VIAS:
        raise HTTPException(status_code=422, detail=f"via must be one of {VIAS}")
    root = get_life_os_root()
    domains = list_domains(root)
    try:
        clean = [_proposals.validate(f, domains) for f in b.findings]
    except (ValueError, TypeError) as e:
        raise HTTPException(status_code=422, detail=str(e))
    items = _proposals.report(root, date.today(), clean, via=b.via)
    return {"ok": True, "written": "daily/proposals",
            "open": sum(1 for i in items if i.get("status") == "open")}


# --- surface 1: Bearer token (programmatic clients) -------------------------

@router.post("/log", dependencies=[Depends(require_write_token)])
def w_log(b: LogBody) -> dict:
    return _do_log(b)


@router.post("/note", dependencies=[Depends(require_write_token)])
def w_note(b: NoteBody) -> dict:
    return _do_note(b)


@router.post("/review", dependencies=[Depends(require_write_token)])
def w_review(b: ReviewBody) -> dict:
    return _do_review(b)


@router.post("/inbox", dependencies=[Depends(require_write_token)])
def w_inbox(b: InboxBody) -> dict:
    return _do_inbox(b)


@router.post("/morning", dependencies=[Depends(require_write_token)])
def w_morning(b: MorningBody) -> dict:
    return _do_morning(b)


@router.post("/propose", dependencies=[Depends(require_write_token)])
def w_propose(b: ProposeBody) -> dict:
    return _do_propose(b)


# --- surface 2: session cookie + CSRF (the browser hub) ---------------------

session_router = APIRouter(prefix="/api/sw", tags=["session-write"])

#: Browsers refuse to send a custom header cross-origin without a successful
#: CORS preflight, and this app configures no CORS middleware — so requiring
#: this header is itself a CSRF defense, not decoration.
CSRF_HEADER = "x-life-os-request"


def _origin_is_same(request: Request) -> bool:
    """True when no Origin is present, or it matches the request's own Host.

    A missing Origin is NOT treated as hostile: non-browser clients omit it, and
    browsers omit it on same-origin GETs. The cross-site POST case we care about
    always carries one.
    """
    origin = request.headers.get("origin")
    if not origin:
        return True
    return urlsplit(origin).netloc == request.headers.get("host", "")


def require_session_write(request: Request) -> None:
    """Session + CSRF gate for the browser write surface.

    THREE independent layers, because this is the one place a browser can
    mutate the tree:
      1. `SameSite=lax` on the session cookie — the browser will not attach it
         to a cross-site POST at all (the primary defense, set in app.py);
      2. a required custom header — unsettable cross-origin without a CORS
         preflight, and no CORS is configured;
      3. an Origin/Host match when Origin is present.
    Then the same rate limiter as the Bearer surface, and the same primitives.

    Note the deliberate asymmetry with `require_write_token`: there is no
    LIFE_OS_WRITE_TOKEN check here — this surface never sees that secret. It is
    gated by *being logged in*, which is the dashboard token's session.
    """
    if not _dashboard_token():
        # Token unset = auth disabled entirely (local dev grace). Mirroring the
        # read side keeps local development usable; on the VPS it is always set.
        return
    key = enforce_pre_auth(request)
    if not request.session.get("auth"):
        record_auth_failure(key)
        raise HTTPException(status_code=401,
                            detail="not logged in (session required)")
    if request.headers.get(CSRF_HEADER) is None or not _origin_is_same(request):
        record_auth_failure(key)
        raise HTTPException(status_code=403, detail="CSRF check failed")
    enforce_write(key)


@session_router.post("/log", dependencies=[Depends(require_session_write)])
def sw_log(b: LogBody) -> dict:
    return _do_log(b)


@session_router.post("/note", dependencies=[Depends(require_session_write)])
def sw_note(b: NoteBody) -> dict:
    return _do_note(b)


@session_router.post("/review", dependencies=[Depends(require_session_write)])
def sw_review(b: ReviewBody) -> dict:
    return _do_review(b)


@session_router.post("/inbox", dependencies=[Depends(require_session_write)])
def sw_inbox(b: InboxBody) -> dict:
    return _do_inbox(b)


@session_router.post("/morning", dependencies=[Depends(require_session_write)])
def sw_morning(b: MorningBody) -> dict:
    return _do_morning(b)
