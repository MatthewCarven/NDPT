# NDPT — Network Diagnostics & Performance Testing: plan

2026-10-29. Status: **phase 1 (engine + CLI) done 2026-10-29**; phase 2 (TUI) next.
See WORKLOG.md for what was built and checked, and TODO.md for what's left.

## Goal

Ping hosts and trace routes, graphically, from both a desktop GUI and a terminal
TUI. Both front ends share one engine. A plain CLI comes along for free.

## What was checked before planning (2026-10-29)

- **Python 3.14.4** (`C:\Program Files\Python314`). Already installed globally:
  PySide6 6.11.1, pyqtgraph 0.14.0, textual 0.71.0, rich 15.0.0, pytest 9.0.3,
  pytest-asyncio 1.3.0 (also dearpygui, matplotlib, numpy).
- **The Windows ICMP API works from Python through ctypes** (`IcmpSendEcho` in
  `iphlpapi.dll`, the same API `ping.exe` and `tracert.exe` use). Pings to
  127.0.0.1 and 1.1.1.1 got replies. Probes to 1.1.1.1 with TTL 1, 2 and 3 came
  back with status 11013 (TTL expired in transit), each carrying that hop's
  address. That's everything a traceroute needs, with no extra packages.
- **The API reports round-trip time in whole milliseconds.** The first hop read
  0 ms, while `perf_counter_ns` around the call read 0.61 ms. NDPT times each
  probe itself.
- **The test ran in an elevated (Administrator) session**, so the no-admin case
  hasn't been tested. Windows' own `ping` and `tracert` use this API without
  admin, so it should work. Phase 1 checks it from a normal shell. NDPT should
  never require elevation. Admin is only for the optional extras in phase 5.

## Library choices

| Part | Choice | Why | Passed over |
|---|---|---|---|
| Probing, Windows | Own ctypes wrapper over `IcmpSendEcho2` / `Icmp6SendEcho2` | No admin, no driver, IPv4 + IPv6, per-probe TTL. Proven above. | scapy (needs Npcap + admin); raw sockets / icmplib on Windows (raw sockets need admin); parsing `ping.exe`/`tracert.exe` output (output depends on locale, and it's slow) |
| Probing, Linux/macOS (later) | icmplib, unprivileged mode | Small, maintained, no root needed there | — |
| TCP "ping" | stdlib `asyncio.open_connection` | Measures handshake time and works where ICMP is blocked | — |
| GUI | **PySide6 + pyqtgraph** | Both installed already. pyqtgraph redraws live charts quickly, where matplotlib struggles. Qt provides tables, tabs, docks, and `QGraphicsView` for the route diagram | dearpygui (fast, but awkward for tables and forms); matplotlib (slow for live data); Tkinter (no good live charting) |
| TUI | **Textual** | Built on asyncio, so the engine plugs straight in. `DataTable` and `Sparkline` are built in. Add `textual-plotext` later for a full latency chart | curses (too low-level); plain rich `Live` (no input or screens) |
| GUI ↔ engine bridge | Engine's asyncio loop on a background thread, results delivered by Qt signals | No extra dependency | qasync |
| Tests | pytest + pytest-asyncio; Textual's `run_test()` pilot; Qt offscreen platform | Everything runs headless and without network access (see fake prober) | — |

The global Textual 0.71.0 is old. NDPT gets its own `.venv` with current, pinned
releases, so other projects using the global packages are unaffected.

## Architecture

```
 GUI (PySide6) ─┐      ndpt.core  (asyncio)
 TUI (Textual) ─┼──►   PingSession · TraceSession · RollingStats · Resolver
 CLI           ─┘      Prober backends:  WinICMP | icmplib | TCP | Fake
```

**Prober protocol.** `async probe(dest, ttl, timeout, size) -> ProbeResult`.
A result is one of `reply | ttl_expired | timeout | unreachable | error`, with
the responder's address, RTT (our own `perf_counter_ns` timing) and send time.
Blocking `IcmpSendEcho` calls run through `asyncio.to_thread` behind a
semaphore that caps concurrency.

**PingSession.** Takes many targets, an interval, a timeout and a packet size.
It streams `ProbeResult`s. Each target has `RollingStats`: sent, received,
loss %, last/min/avg/max, standard deviation, jitter (RFC 3550 smoothed), and
p50/p95 over a sliding window.

**TraceSession.** Runs like mtr. The discovery round sends TTL 1..max_hops in
parallel and stops at the hop where the destination itself answers. After that
it re-probes every hop each interval and emits `HopUpdate(ttl, responders,
stats)`. A hop can list several IPs when load balancing spreads the probes. A
change of responder at a TTL is raised as a route-change event.

**Resolver.** Reverse DNS in a thread pool with a cache. Lookups never hold up
probes: hostnames fill in when they arrive.

**Fake prober.** Scripted latency, loss and topology, so the core, TUI and GUI
tests all run without a network.

## Screens

**GUI**
- *Ping tab*: target list (add/remove, one coloured series each), a live
  scrolling latency chart with lost probes marked as red ticks, a stats table,
  and a latency histogram.
- *Traceroute tab*: target bar with Start/Stop, and an MTR table (hop, host,
  IP, loss %, sent, last, avg, best, worst, jitter). A route diagram draws the
  hops as nodes left to right, with edges coloured by latency and nodes by loss.
  A per-hop bar chart shows the average with min–max whiskers. Selecting a hop
  shows its latency over time.
- *Settings*: interval, timeout, packet size, max hops, IPv4/IPv6, ICMP/TCP
  (with port).

**TUI**
- *Ping screen*: one row per target with name, sparkline, last/avg/loss, plus
  a stats table.
- *Trace screen*: MTR-style table with an inline sparkline column per hop.
  Enter on a hop opens its latency history.
- Keys: `p` ping, `t` trace, `a` add target, `space` pause, `e` export, `q` quit.

**CLI**: `python -m ndpt ping 1.1.1.1 example.com`, `python -m ndpt trace 1.1.1.1`,
`python -m ndpt gui`, `python -m ndpt tui`. The text output doubles as a test
harness.

## Reading the graphs honestly

Routers send ICMP "TTL exceeded" replies as a low-priority job and rate-limit
them. So an intermediate hop can show loss or latency that the hops after it
don't have. The probe above saw this: hop 2 took 38 ms, hop 3 took 19 ms. Only
loss or latency that carries through to the later hops and the destination is
real. The trace view should say so, with a hint and with colouring that weights
the destination's numbers over intermediate ones. Otherwise the tool tells
people their ISP is broken when it isn't.

## Layout

```
NDPT/
  pyproject.toml          deps + `ndpt` entry point
  README.md  PLAN.md  TODO.md  WORKLOG.md  CLAUDE.md
  ndpt/
    __main__.py  cli.py
    core/      models.py  stats.py  resolve.py  ping.py  trace.py  runner.py
      backends/  base.py  win_icmp.py  icmplib_backend.py  tcp.py  fake.py
    gui/       app.py  main_window.py  ping_view.py  trace_view.py  route_graph.py
    tui/       app.py  ping_screen.py  trace_screen.py  widgets.py
  tests/
```

## Phases (one session each)

1. **Scaffold, engine, CLI.** venv and pyproject; models and stats; Windows
   ICMP backend (IPv4, then IPv6); TCP backend; fake prober; PingSession;
   TraceSession; CLI. Tests run on the fake prober, plus a smoke test against
   127.0.0.1 and a no-admin check from a normal shell. *Done when*
   `python -m ndpt trace 1.1.1.1` prints a live MTR table whose hops match `tracert`.
2. **TUI.** Ping and trace screens on the engine. *Done when* both screens run
   live and the pilot tests pass.
3. **GUI.** Ping and trace tabs, the route diagram, and the background-loop
   bridge. *Done when* both tabs graph live without freezing the window, and
   offscreen smoke tests pass.
4. **Polish.** Saved settings, CSV/JSON export, session save/load, and a
   PyInstaller build (as Network Notepad has).
5. **Performance testing proper** (pick from): DNS resolve timing, TCP/HTTP
   time to first byte, path MTU discovery (Don't Fragment flag), owner/ASN
   lookup per hop, throughput via iperf3, long-running monitoring with alerts.
   With admin: TCP/UDP traceroute using a raw ICMP socket to catch the replies,
   which gets past firewalls that drop ICMP echo. Feasibility to be checked.

The TUI comes before the GUI because Textual runs on asyncio directly. It
exercises the engine API without a threading bridge, so API mistakes show up
cheaply before the GUI is built on top.

## Open questions

- IPv6 in v1, or IPv4 first? *(Plan: v4 first, v6 at the end of phase 1.)*
- Windows only, or Linux/macOS too? *(Plan: Windows first, with an icmplib slot kept open.)*
- The folder isn't a git repo yet. `git init` before phase 1.
