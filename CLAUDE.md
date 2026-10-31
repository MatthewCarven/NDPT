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
- **GUI: PySide6-Essentials 6.12.0 and pyqtgraph 0.14.0 in `.venv`**; the global PySide6 is
  6.11.1. Same rule as Textual: don't run the GUI with the global Python.
- **The Qt thread never touches a live session.** Sessions run on `LoopThread`; the views get
  snapshots (`core/snapshot.py`) through `Runner` signals, and call `add`/`pause`/`stop` on the
  loop through the runner. `Engine.ping/trace` hand back an *unstarted* runner: connect, then
  `start()`. A trace of a name that won't resolve finishes at once, and its signals were lost
  1 run in 10 when the runner started first.
- **Runner signals carry the runner first; don't use `QObject.sender()`.** A queued signal still
  arrives after `disconnect()` (with `sender()` None), and `sender()` is also None in a
  wrapped slot, which silently dropped every snapshot in one timing experiment.
- **`QTableWidgetItem.setIcon` costs ~0.4 ms even for the same icon.** `widgets.set_cell` only
  sets what changed (the icons are cached, so the same icon is the same object). Setting
  everything every refresh made an 11-hop table take 100 ms.
- **A hidden tab keeps its snapshots and draws them when it's shown**, from the tab widget's
  `currentChanged`. Not from `showEvent`: that never fires in a window that was never shown,
  as in the tests.
- **Offscreen Qt here draws no text** (every glyph a box) unless `QT_QPA_FONTDIR=C:\Windows\Fonts`.
  The tests don't need it; screenshots do. A windowed grab is truer still: `widget.grab().save()`
  with `WA_ShowWithoutActivating`, so the window appears on screen without taking focus.
- **Matthew's Windows is in dark mode**, and the GUI follows it (`gui/theme.py`). Offscreen
  runs are always light.
- **A simulated key reaches a `QShortcut` only in the active window**: `w.show()`, then
  `QTest.qWaitForWindowActive(w)` (`activateWindow()` alone isn't enough offscreen). And don't
  test a shortcut by swapping the method it's connected to: PySide finds a bound-method slot by
  name, so the swap gets called, not the original.
- **`build.cmd` (`packaging/build.py`) makes the exes with PyInstaller 6.22.3**, into `dist\`
  (`build\` holds its work files and specs; both are gitignored). Each exe leaves out the
  other front end, which cli.py imports inside a function (`--exclude-module`), and packs
  every submodule of textual and rich (`--collect-submodules`): both import parts of
  themselves only when first used. From PowerShell, run it as `& .\build.cmd`: `cmd /c
  build.cmd` couldn't find it in this folder. It ends with `pause`, which returns at once
  when stdin isn't a console.
- **`Session.set_interval` wakes sleeping beats** (`_wake` is pulsed, `_next_beat` re-reads the
  interval), so speeding up from 60 s doesn't wait out the 60 s. `faster()` stops at
  `base_interval`, what the session was made with.
- **Time a GUI change by its redraws, not by eye**: a 20 ms `QTimer` noting its longest gap shows
  a stalled Qt thread. Check the snapshots really arrived first: an empty window never stalls.
