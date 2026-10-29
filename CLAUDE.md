# NDPT: notes for Claude

Read PLAN.md (design and phases), TODO.md and WORKLOG.md first.

- **venv**: `.venv` (Python 3.14.4). Tests: `.venv\Scripts\python -m pytest -q`.
- **Captured CLI output**: set `PYTHONIOENCODING=utf-8` (the tool shell is cp1252) and
  `COLUMNS=130` (rich assumes 80 columns when output isn't a terminal).
- **Live mode needs a real terminal.** Use the Terminal panel (`run_in_terminal`, then
  `read_terminal` partway through a run); the live view clears itself when it ends.
- **Nothing on Matthew's laptop runs un-elevated: UAC is off** (`EnableLUA = 0`), and every
  account is an admin. The tool shell, the Terminal panel and Matthew's own terminals all have
  full admin rights; `runas /trustlevel` does nothing, and a restricted-token launch dies with
  `0xC0000142`. "Works without admin" can only be checked on another machine (TODO.md has the
  steps). Quick test: `socket(AF_INET, SOCK_RAW, IPPROTO_ICMP)` opens only with admin rights.
- **IcmpSendEcho's round trip is whole milliseconds, rounded down.** `combine_rtt` clamps our
  own `perf_counter` timing into that millisecond. Don't "fix" a LAN hop reading 0.4 ms.
- **`Session._sleep` must always yield**, even with a delay of 0 or less. Windows' ~15 ms timer
  puts loops behind schedule easily, and a non-yielding loop never lets its own probes land.
- **`FakeProber(time_scale=0)` never yields**; the trace tests rely on each result landing as
  soon as its task runs.
- **rich crops a table of no-wrap columns instead of shrinking it.** `cli._layout` works out
  host and sparkline widths (3 characters between columns, 1 at each edge). Number columns
  must never be cut short. The TUI's DataTables do the same in `tui.widgets.share_width`
  (1 cell of padding either side of every column).
- **TUI: Textual 8.2.8 in `.venv`**; the global install is 0.71 and its API differs. Don't
  run the TUI with the global Python.
- **Textual sets `is_mounted` only after `on_mount` returns**, so code called from `on_mount`
  can't use it to ask "am I up yet?". `TraceScreen` keeps its own `_ready` flag.
- **DataTable keeps Enter for itself** (`select_cursor`). A screen's Enter binding needs
  `priority=True` to win, which also puts it in the footer.
- **Pilot tests wait on conditions, not fixed sleeps** (`until()` in tests/test_tui.py).
  Sessions run on the test's loop, at `FAST` settings, on `FakeProber(time_scale=0)`.
- **The Terminal panel can't be typed into**, so a live check sees only the screen the app
  starts on: `tui` for ping, `tui --trace HOST` for trace. Keys are tested through the pilot.
