"""Interface prototypes — the surfaces the owner is TRIALLING (2026-09-28).

Four cheap-but-real ways into Life-OS, built to be lived with for a week and
then judged by the system's own numbers, not by taste:

  * telegram — a 3-tap morning card pushed at wake time
  * claude   — a conversational check-in through the MCP server
  * paper    — a printable index card, read back from a photo at night
  * watcher  — Mac-side detection of Ableton saves / git commits, confirmed
               by the owner in one evening tap

Every write any of them makes carries a `via:` tag, so `scripts/trial_report.py`
can count which surface actually got used. That tag is the point of the trial:
the prior 90 days logged zero completions, so a clean baseline exists.

The AI/deterministic boundary is unchanged. The owner sets the dials (energy,
pull, focus); pure functions here shape a PRESENTATION of the engine's own
ordered plan. Nothing in this package re-ranks, re-schedules, or decides.
"""
