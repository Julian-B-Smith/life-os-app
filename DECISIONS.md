# DECISIONS — life-os-app

Append-only. The next number is **max + 1**, never last + 1, and entries are
never renumbered. A decision recorded here is settled: do not re-litigate it,
amend it with a later numbered entry instead.

Started 2026-08-26 at the repo's first session close; decisions made before that
date live in the data tree's `dev/plans/` docs and in git history.

1. **Two write surfaces, one implementation** (2026-08-26). The append-only
   write primitives are exposed twice: `/api/write/*` gated by **Bearer only**
   (programmatic clients — MCP, watchers, scripts) and `/api/sw/*` gated by
   **session cookie + CSRF guard** (the browser hub). Both routers call the same
   `_do_*` functions, so the two surfaces cannot drift in what they permit.
   *Why:* a browser must never hold a write token, and a state-changing endpoint
   must never accept a bare cookie. Rather than choose, both callers get the
   credential that suits them over one shared, bounded implementation. CSRF is
   defended in three independent layers (SameSite=lax, a required custom header
   that cannot be set cross-origin without a CORS preflight, and an Origin/Host
   match). Scope stays enforced by **absence** — no endpoint reaches the vault,
   thresholds, schema, derived state, skills, or `dev/`.

2. **Page specs are data-contract-first** (2026-08-26). Every per-domain page
   spec (`Life-OS/dev/plans/page-specs/`) tags each display element with one of
   four statuses — **LIVE** (on the API today), **AUTHOR** (new data-tree
   content), **API** (needs a new read endpoint), **SW** (needs a session-write
   primitive) — and pages must degrade visibly rather than fake a missing value.
   *Why:* the hard part of these pages was never visualization, it was that most
   of the data does not exist yet. A spec that hides that split produces an agent
   that either invents data or silently reimplements backend logic in the client.
   New needs are filed (`BR-n` / `SW-n`) and implemented behind the deploy gate,
   never worked around in the browser.

3. **The React hub migrates surface-by-surface at `<prefix>/app`** (2026-08-26).
   `life-os-web` ships as a static bundle mounted on the `/app` subtree of the
   hidden hub prefix; the server-rendered Jinja pages keep the prefix root and
   remain the working fallback until each React surface is proven in daily use.
   *Why:* consume-when-connected / degrade-visibly, applied to our own frontend.
   It also keeps the SPA fallback scoped to a subtree FastAPI does not own, so
   it cannot shadow `/api`, `/login`, or `/health`. The web root lives at
   `/srv/life-os-web`, not under the deploy user's home — a `0750` home is not
   traversable by the Caddy user, and loosening it would be the wrong fix.

4. **The domain root serves mind-lathe's static `dist/` from `/srv/mind-lathe`**
   (2026-10-02, mind-lathe IR-2). The root `respond` placeholder became a plain
   `file_server` — no `try_files`, so unknown paths 404 instead of a SPA
   fallback shadowing reserved paths. Content swaps (Culture holding page now,
   the ratified site later via IR-1) are `deploy/bin/deploy-site.sh` only; the
   Caddy block should not change again. Bare `/health` keeps its old placeholder
   response verbatim in its own `handle`, because IR-2 asked that it be left
   untouched and a file_server would otherwise turn it into a 404. *Why the
   prefix grep lives here:* mind-lathe must never contain the hub prefix, even
   inside a scanner, so only this side can check `dist/` for it; the script
   refuses on an empty prefix, since `grep -F ""` matches everything.
