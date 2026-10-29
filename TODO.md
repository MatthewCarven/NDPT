# TODO

## Waiting on another machine

- [ ] **Confirm NDPT works without Administrator rights.** It can't be tested on Matthew's
      laptop: UAC is off there (`EnableLUA = 0`), so every process runs elevated, and every
      account there is an admin. A restricted-token launch from Claude's session dies at
      start-up (`0xC0000142`), so that route is out too. Needs one of: another PC, someone
      else's PC, a VM (VirtualBox; Windows Home has no Hyper-V or Windows Sandbox), or UAC
      turned on. On that machine, from a normal (not "Run as administrator") terminal:
      `.venv\Scripts\python -m ndpt ping -c 3 127.0.0.1 1.1.1.1`, then
      `.venv\Scripts\python -m ndpt trace -c 3 1.1.1.1`, then
      `.venv\Scripts\python -m ndpt tui 1.1.1.1`.
      To prove the terminal really is un-elevated, this should fail with WinError 10013:
      `python -c "import socket; socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_ICMP)"`.
      Windows' own `ping` and `tracert` use the same API without admin, so a failure would be a surprise.

## For Matthew

- [ ] **Try the TUI's keys in Windows Terminal.** Claude saw both screens run live in the
      Terminal panel, but can't type into it: every key was tested headlessly (Textual's pilot)
      only. `.venv\Scripts\python -m ndpt tui --demo`, then `a`, `Enter`, `t`, `p`, `h`, `d`,
      space, `q`.

## Phase 2: TUI (Textual), done 2026-10-30

- [x] Pin a current Textual in pyproject's `tui` extra and install it into `.venv`
      (8.2.8; the global one is 0.71.0 and was left alone).
- [x] Ping screen: a row per host with a sparkline, and the stats table.
- [x] Trace screen: an mtr table with an inline sparkline column; Enter on a hop opens its history.
- [x] Keys: p ping, t trace, a add target, space pause, q quit (plus Enter, h, d). `e` export
      moved to phase 4, with the export formats.
- [x] Pilot tests (`App.run_test()`) on the fake prober.

## Phase 3: GUI (PySide6 + pyqtgraph)

- [ ] Run sessions on `core.runner.LoopThread`; listeners post to the Qt thread through signals.
- [ ] Read session state safely from the Qt thread: a `snapshot()` per session, or only
      what arrives through signals.
- [ ] Ping tab, trace tab, route diagram, per-hop chart (see PLAN.md). The engine already has
      what the TUI needed: `PingSession.add/remove` (with `until_stopped=True`) and
      `Session.pause/resume`. Both must be called on the loop thread.
- [ ] Offscreen smoke tests (`QT_QPA_PLATFORM=offscreen`).

## Phase 4: Polish

- [ ] CSV/JSON export, saved settings, session save/load.
- [ ] `e` in the TUI exports what's on screen, once the formats exist.
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
- [ ] TUI: the ping screen's sparkline lines stop at half the screen's height; more hosts
      than that are cut off there (they're all still in the table below). Scroll, or shrink
      to the table alone past some count.
- [ ] TUI: `--tcp` isn't offered (a TCP prober can't trace). The ping screen could take it,
      with the trace screen saying why it can't.
