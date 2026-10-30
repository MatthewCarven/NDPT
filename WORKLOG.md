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
