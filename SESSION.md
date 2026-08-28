# SESSION — life-os-app

The hot-state artifact: the only prior-session context the next session should
trust. Written at close, describing the tree as it ends.

**Closed:** 2026-08-26 · **branch** `master` · **verify:** `./verify fast` green,
**280 passed** (run at close, not a stale record) · first recorded close for this
repo.

## Where things stand

The app is **live** and healthy on the VPS. This session took it from "a
read-only hub" to "a hub the browser can write through, with the per-domain page
work fully specced."

Landed, in order:

- **`e3a88fd`** — `GET /api/overview` (BR-1/BR-2): the whole Overview payload in
  one request, incl. umbrella grouping. `build_overview()` is shared by the Jinja
  page and the JSON endpoint so the two surfaces cannot drift.
- **`d4add96` → `dd4d614`** — a security triage filed by the `autonomous` repo
  (mailbox brief `autonomous-lifeos-001`, closed): machine identity and the VPS
  IP removed from this public tree, leak + IP gates added to `./verify` and CI.
  Live box verified against `bootstrap.sh` — **one real finding**: password auth
  was effectively ON because Ubuntu Includes `sshd_config.d/*.conf` *first* and
  OpenSSH is first-value-wins, so a cloud-init drop-in silently overrode the
  script's `sed`. Fixed live and durably (a `00-` drop-in that sorts first, plus
  an `sshd -T` assertion so the script proves the result, not the file).
  Exposure was bounded: the deploy account's password is locked and root login
  is off, so none of the ~67k failed attempts could have succeeded.
- **`5e3c33d`** — MCP SDK 2.0 migration (compat import, works on 1.x and 2.x;
  the CI `mcp<2` pin is gone). A fresh install was broken before this.
- **`1a9933c`** — write-API rate limiting (write-mcp Phase 3): per-client
  sliding windows, failed-auth budget checked *before* the token compare.
- **`6a54cac`** — the React hub (`life-os-web`) deployed as a static bundle at
  the hidden prefix's `/app` subtree, served by Caddy from `/srv/life-os-web`.
- **`01827ce`** — **SW-0**: the `/api/sw/*` session-write surface (CSRF-guarded)
  and `GET /api/domains/{name}`. These were the two shared prerequisites every
  per-domain page spec needed; both verified live.

Also this session, outside this repo: `life-os-web` integrated BR-1/BR-2 (13
requests → 1, temp umbrella mirror deleted), and **11 per-domain page specs +
CONVENTIONS** were written to `Life-OS/dev/plans/page-specs/`.

## First move next session

**Give `life-os-web` a git remote.** It is six commits deep and exists only on
this machine — no origin. Do this before building more on top of it.

## Open threads

- `life-os-web` has **no remote** (the thread above; also in REFLECTIONS).
- `life-os-web` has **no router** — the first structural change any per-domain
  page needs, scoped to the `/app` subtree.
- Page specs' **AUTHOR** stores do not exist yet (recipes, workout plan,
  applications rows, `books.yaml`, `projects.yaml`, `collab-log.yaml`). Pages
  will render honest empty states until they do.
- **BR-3** (latest review capture on the API) deliberately open; if built, it
  returns markdown, not HTML.
- Structured-mutation **SW-n** primitives (tick a list item, upsert an
  application row, update a book position) are specced but not built — only the
  four append primitives exist on `/api/sw/*`.
- The unsanitized-markdown render on the Jinja hub remains a known, accepted
  single-tenant risk, ranked below the rate cap (now shipped).

## Traces

This repo has no `traces/` directory; the commits above are the trace, and the
cross-repo record is `integrations/autonomous/` (brief-1 + response-1). Durable
lessons from this session are **L0002–L0004** in `LIBRARY.md` (indexed in
`INDEX.md`); L0002 was promoted into the `autonomous` fleet LIBRARY as canonical.
