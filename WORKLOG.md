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
