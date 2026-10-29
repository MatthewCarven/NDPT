# NDPT: notes for Claude

Read PLAN.md (design and phases), TODO.md and WORKLOG.md first.

- **venv**: `.venv` (Python 3.14.4). Tests: `.venv\Scripts\python -m pytest -q`.
- **Captured CLI output**: set `PYTHONIOENCODING=utf-8` (the tool shell is cp1252) and
  `COLUMNS=130` (rich assumes 80 columns when output isn't a terminal).
- **Live mode needs a real terminal.** Use the Terminal panel (`run_in_terminal`, then
  `read_terminal` partway through a run); the live view clears itself when it ends.
- **This session runs elevated, and `runas /trustlevel` fails silently from the tool shell.**
  Anything about running without admin has to be checked by Matthew from a normal terminal.
- **IcmpSendEcho's round trip is whole milliseconds, rounded down.** `combine_rtt` clamps our
  own `perf_counter` timing into that millisecond. Don't "fix" a LAN hop reading 0.4 ms.
- **`Session._sleep` must always yield**, even with a delay of 0 or less. Windows' ~15 ms timer
  puts loops behind schedule easily, and a non-yielding loop never lets its own probes land.
- **`FakeProber(time_scale=0)` never yields**; the trace tests rely on each result landing as
  soon as its task runs.
- **rich crops a table of no-wrap columns instead of shrinking it.** `cli._layout` works out
  host and sparkline widths (3 characters between columns, 1 at each edge). Number columns
  must never be cut short.
