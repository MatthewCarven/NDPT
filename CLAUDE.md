# NDPT: notes for Claude

Read PLAN.md (design and phases), TODO.md and WORKLOG.md first.

- **Pushing NDPT is fine without asking.** Matthew, 2026-10-31: "feel free to push when you
  like". This overrides the working agreement's "flag pushes" for this repo only. Push
  committed work to `origin/main`; never force-push or rewrite pushed history.

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
- **Linux and macOS probe through `backends/posix_icmp.py`**: ping sockets (SOCK_DGRAM ICMP, no
  root), else raw sockets (root), else a PermissionError saying what to change. A Linux ping
  socket rewrites the ICMP identifier and hears errors only on its error queue (`IP_RECVERR`,
  `recvmsg(MSG_ERRQUEUE)`, the router's address in the cmsg). macOS ping sockets and raw sockets
  get errors as packets quoting the probe, keep our identifier, and (IPv4) include the IP
  header. **Ubuntu 24.04 shuts ping sockets** (`ping_group_range` "1 0"), in WSL and on GitHub.
- **`tests/netns/route.sh` tests the Linux prober in WSL**, from PowerShell:
  `wsl -d Ubuntu-24.04 -u root --cd <repo> -- bash tests/netns/route.sh` (`-u root` asks no
  password). A command after it runs inside the client's namespace instead (`ping -c1 10.9.0.9`).
  Two kernel habits it works around: with `icmp_ratelimit=0` every "time exceeded" zeroes the
  router's tokens for the client, and "no route" (`ip_error`) needs a second's worth, so the
  unreachable probes go first and the runs are 1.5 s apart; and the first IPv6 contact in fresh
  namespaces can wait 1 s for neighbour discovery, so it pings first.
- **`.github/workflows/test.yml` runs the tests on Windows, Linux and macOS on every push**,
  plus localhost pings, the namespaced network (sudo) and a look at a trace of 1.1.1.1.
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
  when stdin isn't a console. Windows won't replace a running exe, so it
  checks first and says which to close (Matthew runs the GUI from `dist\`).
- **build.py builds for the system it runs on**, and only that (PyInstaller can't cross-build).
  macOS's GUI is always an `.app` (onedir: PyInstaller 7 refuses a one-file windowed app).
  `--release` puts the release's files in `dist/release`: Windows' exes as they are, else
  archives (tar.gz, or a `ditto` zip on macOS, which keeps the app's symlinks and signature).
- **`packaging/smoke.py` starts a built program and quits it**: the GUI through
  `NDPT_QUIT_AFTER` (read only by `packaging/ndpt_gui.py`, which queues `closeAllWindows`),
  the TUI on a pseudo-terminal with a `q` (so not on Windows). A windowed exe that crashes
  on Windows leaves an error box open, so a hang counts as a failure.
- **GitHub Actions builds on four machines** (`.github/workflows/build.yml`, Python 3.14):
  windows-latest; ubuntu-22.04 (glibc 2.35); macos-15 (arm64) and macos-15-intel (x86_64).
  Tests without the `network` marker, `build.py --release`, smoke.py on each, and Linux's
  again in a bare `ubuntu:24.04` container. Qt's xcb libraries are apt-installed so
  PyInstaller packs them (it leaves out libxcb, libGL/libEGL and Wayland's). A `v*` tag
  also makes a Release from every build, but only if the tag matches `pyproject.toml` and
  `ndpt.__version__`. A release is public: tag only when Matthew says so.
  `gh workflow run build.yml` builds without releasing.
- **`Session.set_interval` wakes sleeping beats** (`_wake` is pulsed, `_next_beat` re-reads the
  interval), so speeding up from 60 s doesn't wait out the 60 s. `faster()` stops at
  `base_interval`, what the session was made with.
- **Time a GUI change by its redraws, not by eye**: a 20 ms `QTimer` noting its longest gap shows
  a stalled Qt thread. Check the snapshots really arrived first: an empty window never stalls.
