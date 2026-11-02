NDPT pings hosts and traces routes live, mtr-style: loss, latency and jitter for every host
and every hop along the way, as it happens. Windows only, for now.

**ndpt-gui.exe** is the desktop app; **ndpt-tui.exe** is the terminal UI (run it in Windows Terminal).
Neither needs Python: download one and run it. Both take the same options as `ndpt gui` and
`ndpt tui` (try `ndpt-gui.exe --demo` for a made-up network that sends nothing).

The first time, Windows will probably say "Windows protected your PC", because the programs
aren't code-signed. Click **More info**, then **Run anyway**.
