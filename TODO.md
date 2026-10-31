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

## Phase 2: TUI (Textual), done 2026-10-30

- [x] Pin a current Textual in pyproject's `tui` extra and install it into `.venv`
      (8.2.8; the global one is 0.71.0 and was left alone).
- [x] Ping screen: a row per host with a sparkline, and the stats table.
- [x] Trace screen: an mtr table with an inline sparkline column; Enter on a hop opens its history.
- [x] Keys: p ping, t trace, a add target, space pause, q quit (plus Enter, h, d). `e` export
      moved to phase 4, with the export formats.
- [x] Pilot tests (`App.run_test()`) on the fake prober.

## Phase 3: GUI (PySide6 + pyqtgraph), done 2026-10-30

- [x] Run sessions on `core.runner.LoopThread`; listeners post to the Qt thread through signals.
- [x] Read session state safely from the Qt thread: `PingSession/TraceSession.snapshot()`,
      built on the loop and carried by the signals (`core/snapshot.py`).
- [x] Ping tab, trace tab, route diagram, per-hop chart (see PLAN.md), with the honest-graphs
      rule (`carried_on()`).
- [x] Settings tab: interval, timeout, payload, max hops, IPv4/IPv6, ICMP or TCP with a port.
- [x] `python -m ndpt gui [hosts] [--trace] [--demo]`.
- [x] Offscreen smoke tests (`QT_QPA_PLATFORM=offscreen`).

### For Matthew: the GUI by hand

Everything below was only checked offscreen or in grabs of a window nobody touched.

- [ ] **Mouse:** click a router in the route diagram and a bar in the per-hop chart; each
      should select that hop in the table and show its latency over time. Hover a router
      for its tooltip (responders, numbers, and why grey numbers stop at that hop).
- [ ] **Resizing:** drag the window bigger and smaller, and drag the splitters. The route
      diagram should spread its hops out when there's room and scroll sideways when there
      isn't; no table column should be cut short.
- [ ] **The ping tab:** add hosts (several at once, separated by spaces), remove one, Pause and
      Resume, and the Trace button on a selected host.
- [ ] **Settings:** switch to TCP (port 443) and Apply: Ping keeps going, Trace says why it
      can't. Back to ICMP, Apply, Start on the Trace tab.
- [ ] **Closing** the window mid-trace: it should vanish at once (the process can take a few
      more seconds to end if router-name lookups are still running).
- [ ] **Light mode**, if you ever use it: the GUI follows Windows' setting, and every grab so
      far was dark.

### For Matthew: the 2026-10-31 additions

- [ ] **`+` and `-` in a real window.** Both front ends were driven by simulated keys only. In
      the GUI also try `Ctrl+=` / `Ctrl+-` with the cursor in a host box (plain `+` and `-`
      type there), and the Slower/Faster buttons; Faster greys out at the starting interval.
- [ ] **The icon.** Save a square PNG (256x256 or bigger) as `ndpt\gui\icon.png`, then run
      `build.cmd`. Both exes get it, and so does the GUI's window and taskbar button
      (also when run with `python -m ndpt gui`).
- [ ] **The exes on a PC without Python**, when one turns up (the same trip as the no-admin
      check above: a fresh PC tests both).

## Phase 4: Polish

- [ ] CSV/JSON export, saved settings, session save/load. The snapshots (`core/snapshot.py`)
      are frozen copies of everything the front ends show: a good thing to export from.
- [ ] `e` in the TUI exports what's on screen, once the formats exist.
- [x] PyInstaller build: `build.cmd` makes `dist\ndpt-tui.exe` and `dist\ndpt-gui.exe`
      (`packaging/build.py`). Done 2026-10-31.
- [ ] Version info in the exes (File > Properties > Details shows nothing yet): PyInstaller's
      `--version-file`.

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
- [ ] TUI: colour the trace screen's loss with `core.snapshot.carried_on()`, as the GUI does,
      so a hop whose loss stops there isn't red. The TUI only has the notes today.
- [ ] GUI: a `startgui.cmd` (with `pythonw`, so no console window), like `starttui.cmd`.
- [ ] GUI: the trace tab's redraw measured 30-47 ms in a real window, against ~9 ms offscreen.
      Not understood; a guess is GIL contention with the probe threads. The window stays
      responsive (worst Qt stall 59-76 ms with real probes), and a hidden tab doesn't redraw.
- [ ] GUI: one windowed run with real probes had a single 2.1 s stall of the Qt thread (that run
      didn't time NDPT's redraws). Three timed runs after it didn't repeat it, and nothing in
      them ran over 50 ms. Watch for it.
- [ ] GUI: the route diagram scrolls sideways past ~8 hops at 1280 px. Fit to width, or wrap
      long routes onto a second row?
- [ ] GUI: no hover readout on the charts (a crosshair with the time and value); the tables
      carry the numbers for now.
- [ ] GUI: closing while router-name lookups run leaves the process alive for a few seconds:
      Python joins the default executor's threads at exit, and Windows' reverse lookup for an
      address with no name takes seconds.
- [ ] `+`/`-` aren't in the CLI's live mode, which reads no keys. A new trace on the TUI's
      trace screen starts again at the starting interval, not the pace the last one had.

## Ideas (2026-10-31, for Matthew to pick from)

Not planned yet. What people reach for in a tool like this, beyond what PLAN.md has:

- [ ] **"Is it me, my router, my ISP, or them?"** One button: ping the gateway, the ISP's first
      hop, a DNS server, 1.1.1.1 and the target together, then say in plain words where the
      trouble starts.
- [ ] **Latency under load (bufferbloat).** Ping while a download fills the link, and grade how
      far latency climbs. Matthew saw 300–900 ms during a download on 2026-10-30.
- [ ] **An outage log.** Timestamped "1.1.1.1 stopped answering 14:02:10, back 14:02:45 (35 s)"
      and route changes, kept and exportable: evidence for an ISP support call.
- [ ] **Alerts.** A Windows notification when loss or latency crosses a line for N probes, or a
      host goes down or comes back. With a tray icon whose colour is the current state, for
      leaving it running.
- [ ] **The link itself.** Local addresses, gateway, DNS servers, public IP, and Wi-Fi SSID,
      signal and channel (`netsh wlan show interfaces`), with signal drawn beside latency to
      see whether a bad patch was the Wi-Fi.
- [ ] **Call/game quality score.** MOS (the ITU E-model) from latency, jitter and loss: one
      number people understand.
- [ ] **A shareable report.** One HTML page or PNG of a trace and its numbers, for a forum
      post or a support ticket.
- [ ] **LAN sweep.** Ping every address on the local subnet and list who answers, with names
      and the network-card maker from the ARP table.
- [ ] **Compare the two links side by side** (Wi-Fi and the tether), once `--source` exists.
