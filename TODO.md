# TODO

## For Matthew

- [ ] **Run NDPT from a normal (non-admin) terminal** to confirm it works without
      Administrator rights. Claude's session is elevated and can't drop its rights
      (`runas /trustlevel` fails silently there):
      `.venv\Scripts\python -m ndpt ping -c 3 127.0.0.1 1.1.1.1`, then
      `.venv\Scripts\python -m ndpt trace -c 3 1.1.1.1`.
- [ ] Push `main` (origin is set).

## Phase 2: TUI (Textual)

- [ ] Pin a current Textual in pyproject's `tui` extra and install it into `.venv`
      (the global one is 0.71.0).
- [ ] Ping screen: a row per host with a sparkline, and the stats table.
- [ ] Trace screen: an mtr table with an inline sparkline column; Enter on a hop opens its history.
- [ ] Keys: p ping, t trace, a add target, space pause, e export, q quit.
- [ ] Pilot tests (`App.run_test()`) on the fake prober.

## Phase 3: GUI (PySide6 + pyqtgraph)

- [ ] Run sessions on `core.runner.LoopThread`; listeners post to the Qt thread through signals.
- [ ] Read session state safely from the Qt thread: a `snapshot()` per session, or only
      what arrives through signals.
- [ ] Ping tab, trace tab, route diagram, per-hop chart (see PLAN.md).
- [ ] Offscreen smoke tests (`QT_QPA_PLATFORM=offscreen`).

## Phase 4: Polish

- [ ] CSV/JSON export, saved settings, session save/load.
- [ ] PyInstaller build.

## Phase 5: Performance testing

- [ ] Path MTU discovery: set `IP_FLAG_DF` (0x2) in `IP_OPTION_INFORMATION.Flags`. Status
      11009 ("packet too big") maps to ERROR today; make it an answer with its responder.
- [ ] DNS resolve timing, TCP/HTTP time to first byte, owner/ASN per hop, iperf3 throughput,
      long-running monitoring.

## Smaller, surfaced along the way

- [ ] **Choose the source interface.** The laptop has two links (Wi-Fi and the phone's USB
      tether), and the first hop flips between them. `IcmpSendEcho2Ex` takes a source
      address; offer `--source`/`--interface`.
- [ ] icmplib backend for Linux/macOS (`make_prober` raises NotImplementedError off Windows).
- [ ] IPv6 is only tested on loopback: this network has no global IPv6.
- [ ] Output piped into something that stops reading early (`Select-Object -First N`, `head`)
      ends in an OSError traceback on flush; quieten it.
- [ ] TCP ping to a closed port reports an inflated time on Windows, which retries the SYN
      after the reset. Mark those rows, or leave them out of the averages.
- [ ] The "reached X at hop N" event can name a hop that's too high if round-1 replies land
      out of order. Later rounds correct `dest_ttl` quietly. Rare.
