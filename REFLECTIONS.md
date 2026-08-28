# REFLECTIONS — life-os-app

Dated notes worth holding between sessions. `/wakeup` flags entries that have
gone stale, so the date is load-bearing.

- [2026-08-26] **`life-os-web` has no git remote.** The React hub exists only on
  this machine — six commits, no origin. A disk failure loses it outright, and
  nothing else in the ecosystem can consume it. This is the loose thread most
  likely to be forgotten precisely because the app *works* locally.
- [2026-08-26] Most per-domain pages will render empty until their **AUTHOR**
  data stores exist (recipes, workout plan, applications rows, `books.yaml`,
  `projects.yaml`, `collab-log.yaml`). That is by design — the specs say degrade
  visibly, never fake — but expect the first page builds to look sparse, and do
  not read that as a bug in the page.
- [2026-08-26] `life-os-web` is still a single page with **no router**; the first
  structural change any per-domain page needs is routing scoped to the `/app`
  subtree.
- [2026-08-26] The README had drifted badly enough to be actively misleading —
  it claimed the app ran locally on Windows with VPS deployment "deferred",
  months after the VPS became the only deployment, and omitted the entire web
  hub, all three HTTP surfaces, the MCP server, and the deploy gate. Rewritten
  at this close. Worth a periodic re-read: nobody notices a README rotting.
- [2026-08-26] Two commit messages this session lost text to shell command
  substitution (backticks in a double-quoted `-m`). Now canonical lesson L0004 —
  use a quoted heredoc into `git commit -F -`. Cosmetic damage only, and not
  worth amending on a branch the deploy box pulls.
