# NDPT: Network Diagnostics & Performance Testing

Ping hosts and trace routes, live. One engine, with three front ends: a
command line, a terminal UI and a desktop GUI. See [PLAN.md](PLAN.md) for the
design and the phases.

## Setup

```
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,tui,gui]"
```

The `tui` extra is Textual (pinned at 8.2.8). The `gui` extra is PySide6-Essentials
6.12.0 (PySide6 without its add-ons, which NDPT doesn't use) and pyqtgraph 0.14.0.
The command line works without either.

## Use

```
.venv\Scripts\python -m ndpt ping 1.1.1.1 example.com     several hosts side by side
.venv\Scripts\python -m ndpt ping --tcp 443 example.com   TCP handshake time, for hosts that filter ping
.venv\Scripts\python -m ndpt trace 1.1.1.1                mtr-style: every hop, probed every round
.venv\Scripts\python -m ndpt trace --demo example.com     a made-up network, no packets sent
```

Both commands update a table in place until Ctrl+C, then print the final table.

### Terminal UI

```
.venv\Scripts\python -m ndpt tui 1.1.1.1 example.com    ping screen: these hosts side by side
.venv\Scripts\python -m ndpt tui --trace 1.1.1.1        start on the trace screen
.venv\Scripts\python -m ndpt tui --demo                 a made-up network, with three made-up hosts
```

Or double-click `starttui.cmd`, or run it with the same arguments
(`starttui --trace 1.1.1.1`). It runs `.venv`'s Python, so there's no venv to
activate first.

The ping screen has a line per host (a sparkline as wide as the window, then
last, average and loss) and a table of every number below it. The trace
screen is an mtr-style table with a sparkline per hop, and notes under it on
reading the trace (see below). Both keep running while the other is on show.

| Key | Ping screen | Trace screen |
|---|---|---|
| `p` / `t` | switch to the ping / trace screen | |
| `a` | add hosts (several, separated by spaces) | trace another host |
| `Enter` | trace the highlighted host | latency history of the highlighted hop |
| `h` | latency history of the highlighted host | |
| `d` / `Delete` | stop pinging the highlighted host | |
| `space` | pause / resume this screen's probes | pause / resume |
| `+` (or `=`) | probe less often: 2, 5, 10, 15, 30, then 60 s apart | the same, between rounds |
| `-` | probe more often again, down to the interval it started with | the same |
| `q` / `Ctrl+C` | quit | quit |

`-i`, `-W`, `-s`, `-4`/`-6`, `-m` and `-n` work as for `ping` and `trace`.

| Option | |
|---|---|
| `-c N` | stop after N probes per host (ping) or N rounds (trace) |
| `-i SECONDS` | time between probes, default 1 (at least 0.1 on a real network) |
| `-W SECONDS` | how long to wait for each answer, default 1 |
| `-s BYTES` | payload size, default 32 (as Windows ping) |
| `-4` / `-6` | IPv4 or IPv6 only |
| `--report` | no live table; print once at the end (automatic when output isn't a terminal) |
| `--demo` | fake network, for trying it out and for tests |
| `-m N`, `-n` | trace only: max hops (default 30); don't look up hop names |

### Desktop GUI

```
.venv\Scripts\python -m ndpt gui 1.1.1.1 example.com    ping tab: these hosts side by side
.venv\Scripts\python -m ndpt gui --trace 1.1.1.1        start on the trace tab
.venv\Scripts\python -m ndpt gui --demo                 a made-up network, with three made-up hosts
```

The same options as `tui` work, plus `--tcp PORT` to ping with TCP handshakes.
Both tabs keep probing while the other is showing.

- **Ping:** the host list (add several at once, separated by spaces; remove;
  pause; trace the selected host), a scrolling latency chart with a colour per
  host and lost probes as red ticks in the gaps of their own line, a table of
  every number, and a latency histogram.
- **Trace:** the mtr table, the engine's notes and path events, a bar per hop
  (average, best to worst, and a line for the latency that carries on), the
  latency over time of the selected hop, and a route diagram: hops left to
  right, nodes coloured by the loss that carries on, edges by the latency added
  on that link. Click a router or a bar to select its hop.
- **Settings:** interval, timeout, payload, max hops, IPv4/IPv6, ICMP or TCP
  with a port. Apply restarts the probes. TCP can't trace: while it's chosen,
  the trace tab says so.

`+` (or `=`) and `-` slow down and speed up the tab on show, as in the TUI, and
so do its Slower and Faster buttons. Faster goes no lower than the interval in
Settings. While you're typing in a host box, `+` and `-` are just text there:
use `Ctrl+=` and `Ctrl+-` instead.

The GUI follows Windows' light or dark mode.

### Reading a trace

Routers answer traceroute probes as a low-priority chore, and rate-limit those
answers. A hop showing loss or high latency that the hops after it don't share
is that router being slow to *reply*, not your traffic being dropped or
delayed. The trace view prints a note under the table when it sees this. Only
loss and latency that carry on to the destination are real.

The GUI colours by this rule. A hop is coloured by the least loss of it and
every hop after it that answers, and an edge by the latency added that carries
on. A hop's own numbers still show, but in grey with a hollow dot where they
don't carry on, so a rate-limiting router stays green while the path is.

## How it probes

On Windows, NDPT calls the Windows ICMP API (`IcmpSendEcho` in `iphlpapi.dll`), the
same one `ping` and `tracert` use. It needs no packet driver, and it shouldn't need
Administrator rights; that hasn't been confirmed from a non-elevated shell yet (see
TODO.md). The API rounds times down to whole milliseconds, so NDPT times each probe
itself as well.

## Tests

```
.venv\Scripts\python -m pytest -q
.venv\Scripts\python -m pytest -q -m "not network"    skip tests that send real probes
```

The network tests only probe localhost and 192.0.2.1 (a documentation address
that's never routed). Everything else runs on a scripted fake prober. The GUI
tests run offscreen (`QT_QPA_PLATFORM=offscreen`); they're skipped without the
`gui` extra.

## Layout

```
ndpt/
  cli.py  textviz.py         command line, text sparklines and cells
  core/   models.py stats.py session.py ping.py trace.py resolve.py runner.py
          snapshot.py        frozen copies of a session, for the GUI's thread
    backends/  win_icmp.py tcp.py fake.py
  tui/    app.py ping_screen.py trace_screen.py widgets.py
  gui/    app.py main_window.py bridge.py ping_view.py trace_view.py
          route_graph.py charts.py settings_view.py theme.py widgets.py
tests/                       test_tui.py drives the TUI headless (Textual's pilot);
                             test_gui.py the GUI offscreen
starttui.cmd                 the TUI without activating the venv
```
