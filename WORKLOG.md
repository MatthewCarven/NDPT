# Worklog

## 2026-10-29: plan, then phase 1 (engine + CLI)

**Plan.** Matthew asked for a Python network diagnostics tool with a GUI and a
TUI that traces routes and pings hosts graphically, with the library choice
left to Claude. PLAN.md has the design: one asyncio engine; a CLI, then a
Textual TUI, then a PySide6 + pyqtgraph GUI; five phases.

**Feasibility, before planning.** Python's ctypes can drive Windows' ICMP API
(`IcmpSendEcho`, iphlpapi.dll). Pings work, and TTL-limited probes come back
"TTL expired in transit" (11013) carrying the hop's address, so traceroute needs
no extra packages. The API's round trip is whole milliseconds, rounded down.

**Phase 1, built:**
- `core/models.py`, `core/stats.py`: probe results, ping targets, hops; running
  stats (loss, best/avg/worst, stdev, RFC 3550 jitter, percentiles, a window of
  recent samples).
- `core/backends/win_icmp.py`: IPv4 (`IcmpSendEcho`) and IPv6 (`Icmp6SendEcho2`)
  on a thread pool, one ICMP handle per probe. `tcp.py`: handshake timing.
  `fake.py`: scripted routes for the tests, plus the `--demo` network.
- `core/ping.py`: many hosts on a steady beat (probes overlap rather than queue).
  `core/trace.py`: mtr-style. Round 1 sends TTL 1, 2, 3, ... 25 ms apart and
  stops at the destination; later rounds probe every hop. It handles load
  balancing, unreachable dead ends and paths that get longer, and adds plain
  notes for loss or delay that doesn't carry on.
- `core/resolve.py`: forward and reverse DNS off the loop, cached.
  `core/runner.py`: a loop thread for the GUI.
- `cli.py`: `python -m ndpt ping|trace` with live rich tables; `--report`, `--demo`.

**Checked:**
- 63 tests pass, three runs in a row (fake prober; real probes only to
  localhost and 192.0.2.1).
- `ndpt trace 1.1.1.1` against `tracert -d 1.1.1.1`: every hop tracert got an
  answer from matches (1, 6, 8, 9, and the destination at 10). NDPT also got
  answers at hops 2–4 and 7, where tracert timed out; those are the same
  routers the morning's probe saw.
- 16 parallel probes give the same spread of times as sequential ones, and the
  same spread as Windows `ping`.
- IPv6 works on loopback; this network has no global IPv6.
- The live display works in a real terminal (Terminal panel): the table
  updates in place, then the final table prints.
- **Not checked:** running without admin. This session is elevated and
  `runas /trustlevel:0x20000` fails silently here. It's on Matthew's list in TODO.md.

**Bug found by the tests:** a session that fell behind schedule computed a wait
of ≤0 and didn't yield, so the next round started before the last round's
results had landed. With no round limit, it would have kept creating probe
tasks that never ran. `Session._sleep` now always yields.

**Seen in passing:** the first hop changes with the link Windows picks. On
10.0.0.138 (Wi-Fi) around 20:20, the first hop varied from 3 to 157 ms, and
Windows `ping` agreed. On 10.243.197.219 (the phone tether) it's sub-millisecond.
That led to the TODO item for a `--source` option.

## 2026-10-30: the no-admin check is parked

Matthew can't run the check: every account on his laptop is an admin, and he
can't create a standard one. The registry shows why nothing un-elevated exists
there: **UAC is off** (`EnableLUA = 0`), so every process gets the full admin
token. That explains why `runas /trustlevel` did nothing.

I tried once to fake a non-elevated process: a restricted copy of the
session's token (Administrators deny-only, no privileges, Medium integrity),
launched with `CreateProcessAsUserW`. The launch succeeds, but the child dies
with `0xC0000142` (DLL init failed) before running any code, both as `cmd.exe`
and as a detached `python.exe`. I stopped there rather than dig into the
token's permissions. The control did work: this session can open a raw ICMP
socket, which an un-elevated process can't. TODO.md now lists the check under
"Waiting on another machine", with that socket test to prove the terminal
there really is un-elevated.

## 2026-10-30: phase 2 (TUI)

A side session, started from the planning session, built the Textual TUI.

**Built:**
- Textual 8.2.8 pinned in the `tui` extra and installed into `.venv` (the global
  0.71.0 is untouched).
- `tui/app.py`: one app, two screens as Textual modes, sharing the prober and
  the name cache. Sessions run as workers on Textual's own loop; screens redraw
  from session state every 0.25 s while they're on show. Both sessions keep
  probing while hidden. Keys: `p`, `t`, `q`/`Ctrl+C`; `space` pauses the screen
  on show.
- `tui/ping_screen.py`: a line per host (name, a window-wide sparkline that ends
  at the same column for every host, last/avg/loss) over a stats table (sent,
  loss, last, avg, best, worst, stdev, jitter, p95). `a` adds hosts, `d` drops the
  highlighted one, `Enter` traces it, `h` opens its history.
- `tui/trace_screen.py`: the mtr table with a sparkline column; the notes and the
  last three path events under it; route changes after round 1 also pop up.
  `a` traces another host, `Enter` opens a hop's history (a bar chart scaled from
  0, its responders, and any note about that hop).
- `python -m ndpt tui [hosts] [--trace] [--demo]`, with the usual probe options.
  `--demo` with no hosts pings example.com/.net/.org on the fake network.
- Shared cell helpers (`host_label`, `hop_label`, `loss_cell`, `last_cell`) moved
  from `cli.py` to `textviz.py`, which also gained `bar_chart`.

**The TUI found two gaps in the engine API**, as phase 2 was meant to:
- *Adding a host to a running ping.* `PingSession` took a fixed list and its
  `run()` ended when that list was done. It now has `add()`/`remove()`, and
  `until_stopped=True` keeps `run()` going with no hosts at all.
- *Pausing.* `Session.pause()`/`resume()`. A resumed session takes its beat up
  from that moment; without that it sent two probes back to back on resume (the
  "fell behind, carry on" rule saw the paused time as lateness).
- Also: cancelling `run()` (as Textual does to workers on exit) now cancels the
  probes in flight. Before, they kept running and landed in a session nobody was
  watching.

**Checked:**
- 91 tests pass (63 before), seven full runs without a failure: 19 TUI tests drive the app
  headless with Textual's pilot on the fake prober, plus engine tests for
  add/remove, pause/resume and cancelling. The pause and cancel tests fail with
  their fix taken out.
- Live in the Terminal panel: `tui --demo` and `tui --demo --trace`, then real
  probes: `tui 1.1.1.1 example.com 192.0.2.1` (two answer, 192.0.2.1 times out)
  and `tui --trace 1.1.1.1` (10 hops to one.one.one.one, hop 5 silent, hop 1 the
  phone tether). 25 rounds took 24.5–24.8 s by the clock: the beat holds.
  Ctrl+C quits cleanly, with no traceback.
- **Not checked:** keys in a real terminal. The Terminal panel can't be typed
  into from here, so keys were only tested through the pilot. On Matthew's list
  in TODO.md.

**Gotchas** (in CLAUDE.md too): Textual sets `is_mounted` only after `on_mount`
returns; DataTable keeps Enter for itself unless a screen binding has
`priority=True`.

## 2026-10-30: `starttui.cmd`

Matthew asked for a launcher so nobody has to know about the venv.
`starttui.cmd` runs `.venv\Scripts\python -m ndpt tui` with any arguments given
to it, from any folder (ndpt is installed editable). If `.venv` is missing it
says so; if the TUI exits with an error, it pauses so a double-clicked window
stays open to show it, and it keeps the exit code. Checked: `--demo` live in the
Terminal panel (ping, then trace), Ctrl+C back to the prompt with no pause; by
full path from another folder (the `=` in the path is fine); a bad argument
(pause, exit 2); and a copy with no `.venv` beside it (message, exit 1).

**Keys checked in Windows Terminal** (Matthew, same day): "works flawlessly". His
screenshots show a real trace to www.google.com.au (10 hops; hops 5 and 6
silent), a hop's history opened with Enter, and space pausing at round 56. That
closes the one thing phase 2 couldn't check from here.

## 2026-10-30: phase 3 (GUI)

A side session, started from the planning session, built the PySide6 + pyqtgraph GUI
in three commits (709c8c9, 04a5d39, 34d9991, and the docs after).

**Built:**
- PySide6-Essentials 6.12.0 and pyqtgraph 0.14.0 pinned in the `gui` extra and installed
  into `.venv` (with numpy 2.5.4). Essentials is PySide6 without its add-ons (WebEngine and
  the rest), which NDPT doesn't use. The global PySide6 6.11.1 and pyqtgraph are untouched.
- `core/snapshot.py`: frozen copies of a session's state, built by the new
  `PingSession.snapshot()` / `TraceSession.snapshot()` on the session's own loop.
  `carried_on()` works out how much of each hop's loss and latency carries on to the hops
  after it, and flags a hop whose loss stops there or that's slow only to reply (the same
  test as `notes()`).
- `gui/bridge.py`: `Engine` runs sessions on `core.runner.LoopThread`. Each `Runner` posts a
  snapshot to the Qt thread through a signal, at most every 0.25 s and only when there's
  news; `add`/`remove`/`pause`/`stop` run on the loop. The Qt thread never reads a live
  session. Closing hides the window, stops the sessions, closes the prober and stops the loop.
- Ping tab: a host list (add several at once, remove, pause, trace the selected host), a
  scrolling latency chart on a clock axis (a colour per host; a lost probe is a gap in its
  line with a red tick in the gap), a table of every number, and a latency histogram.
- Trace tab: Start/Stop and Pause, the mtr table, the engine's notes and path events (route
  changes after round 1 also go to the status bar), a per-hop bar chart (average, best to
  worst, and a line for what carries on), the selected hop's latency over time (the
  destination until another is chosen), and the route diagram (`QGraphicsView`): hops left to
  right, nodes coloured by the loss that carries on, edges by the latency added on that link
  (a blue ramp), each router of a load-balanced hop drawn, a silent hop dashed. Clicking a
  router or a bar selects its hop.
- Honest graphs: a hop's own loss and average still show, but where they don't carry on they
  are grey, with a hollow dot and a faint bar, and the node is coloured as the path is. Only
  the destination's numbers are taken as they come.
- Settings tab: interval, timeout, payload, max hops, IPv4/IPv6, ICMP or TCP with a port,
  name lookups. Apply restarts both tabs; a protocol change swaps the prober (the old one
  closes after its sessions stop). While TCP is chosen, the trace tab says why it can't
  trace. On the demo network the protocol is greyed out.
- `python -m ndpt gui [hosts] [--trace] [--demo]` with the `tui` options plus `--tcp PORT`.
- The GUI follows Windows' light or dark mode. Matthew's is dark.

**Checked:**
- 119 tests pass (91 before), five full runs in a row after the last fix: 22 GUI tests run
  offscreen on the fake prober, waiting on conditions, including a real mouse click on the
  route diagram (`QTest`); plus snapshot, `carried_on` and CLI tests.
- Live, windowed, grabbed with `widget.grab()` and sent to Matthew: `--demo` (ping three
  hosts, trace example.org), and real probes (ping 1.1.1.1, example.com and 192.0.2.1, trace
  1.1.1.1, every 0.5 s). The link was congested: 100-900 ms, and ~25-45% loss from hop 2 on,
  which the diagram paints red from there, while hop 1's extra loss is grey. Matthew sent a
  grab of his own from the same run: "Looks great".
- The window doesn't freeze: a 20 ms `QTimer` noting its longest gap read 59-76 ms at worst
  in windowed real-probe runs, median 20 ms. `ndpt gui` through the real CLI entry point
  closes in 3 ms on the demo, ~1 s with real probes (it waits up to 1 s on reverse-DNS
  lookups), exit code 0.
- **Not checked:** mouse interaction and window resizing by hand, and light mode on screen.
  On Matthew's list in TODO.md ("For Matthew: the GUI by hand").

**Found along the way:**
- *A race in the bridge.* `Engine.trace()` started the runner before the view connected to
  it, so a trace that failed at once (a name that won't resolve) could finish before anyone
  was listening, leaving the tab at "tracing...". One test caught it 1 run in 10. Runners now
  start only when told, after connecting; a test covers it.
- *Refresh cost.* `QTableWidgetItem.setIcon` costs ~0.4 ms even for the same icon, so an
  11-hop table took 100 ms a refresh. `set_cell` now sets only what changed: under 1 ms. A
  hidden tab doesn't redraw either, until it's shown.
- *`sender()` is fragile.* The views first told a current runner's snapshots from a stopped
  one's with `QObject.sender()`, but a queued signal still arrives after `disconnect()`
  (`sender()` None), and `sender()` is None in a wrapped slot too. My timing wrappers dropped
  every snapshot that way, so three "no stall" windowed runs had measured an empty window.
  The signals now carry their runner.
- *One 2.1 s stall* of the Qt thread in the first windowed real-probe run, which had no timing
  of NDPT's own redraws in it. The three valid runs after it, timed, didn't repeat it, and no
  redraw or Qt event in them ran over 50 ms. And the trace redraw measured
  30-47 ms in a real window against ~9 ms offscreen; not understood. Both in TODO.md.
- *Lost-probe ticks* all along the bottom made a solid red comb for a host that never answers
  (192.0.2.1), hiding everyone else's losses. Each tick now sits in the gap of its own line.

## 2026-10-31: + and - for the interval; build.cmd for the exes

Matthew asked for keys to lengthen the time between pings and shorten it back
to where it started, and for a build script for the TUI and GUI.

**Built:**
- `Session.slower()` / `faster()` step through 1, 2, 5, 10, 15, 30 and 60 s; `faster()`
  stops at `base_interval`, what the session was made with. `set_interval()` pulses a wake
  event, and the beat (`_next_beat`, now shared by ping and trace) re-reads the interval,
  so going from 60 s back to 1 s happens at once instead of after the minute.
- TUI: `+` (or `=`, + without shift) and `-` on both screens, in the footer; a toast when
  there's no further to go.
- GUI: the same keys act on the tab on show, plus `Ctrl+=` / `Ctrl+-` for when a host box
  has focus (a text box keeps plain + and - for itself). Slower and Faster buttons beside
  Pause; Faster greys out at the floor (snapshots now carry `base_interval`). The ping
  chart's time span follows the interval.
- `build.cmd` -> `packaging/build.py`: PyInstaller 6.22.3, one-file exes in `dist\`
  (`--onedir` for folders). Each exe leaves out the other front end and packs every
  submodule of textual and rich, which import parts of themselves lazily. If
  `ndpt\gui\icon.png` exists, both exes take it as their icon and the GUI uses it for its
  window; the GUI also sets an AppUserModelID so it gets its own taskbar button.

**Checked:**
- 124 tests pass (119 before), including a real simulated `+` reaching the GUI's shortcut
  once the window is active, and `-` typing into a host box rather than speeding up.
- TUI headless: the footer reads `space Pause  + Slower  - Faster ...`; `-` at the floor
  says so. GUI grabbed offscreen (with `QT_QPA_FONTDIR`): Slower/Faster sit beside Pause
  on both tabs, the status says "every 2s".
- `ndpt-tui.exe` (23 MB, ~20 s to build) in the Terminal panel: `--demo`, then real
  probes to 1.1.1.1 (~25 ms) and 127.0.0.1. `ndpt-gui.exe` (70 MB, ~90 s): window up 3.2 s
  after launch, titled right, and both its processes gone after closing it.
- **Not checked:** the keys by hand in a real window, and the exes on a PC without Python.
  On Matthew's list in TODO.md, with the icon.

**Ideas:** Matthew asked what else people would want in a tool like this; the list is in
TODO.md under "Ideas".
