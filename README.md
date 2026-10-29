# NDPT: Network Diagnostics & Performance Testing

Ping hosts and trace routes, live. One engine, with three front ends planned:
a command line (built), a terminal UI and a desktop GUI (next). See
[PLAN.md](PLAN.md) for the design and the phases.

## Setup

```
py -3.14 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev]"
```

## Use

```
.venv\Scripts\python -m ndpt ping 1.1.1.1 example.com     several hosts side by side
.venv\Scripts\python -m ndpt ping --tcp 443 example.com   TCP handshake time, for hosts that filter ping
.venv\Scripts\python -m ndpt trace 1.1.1.1                mtr-style: every hop, probed every round
.venv\Scripts\python -m ndpt trace --demo example.com     a made-up network, no packets sent
```

Both commands update a table in place until Ctrl+C, then print the final table.

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

### Reading a trace

Routers answer traceroute probes as a low-priority chore, and rate-limit those
answers. A hop showing loss or high latency that the hops after it don't share
is that router being slow to *reply*, not your traffic being dropped or
delayed. The trace view prints a note under the table when it sees this. Only
loss and latency that carry on to the destination are real.

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
that's never routed). Everything else runs on a scripted fake prober.

## Layout

```
ndpt/
  cli.py  textviz.py         command line, text sparklines
  core/   models.py stats.py session.py ping.py trace.py resolve.py runner.py
    backends/  win_icmp.py tcp.py fake.py
tests/
```
