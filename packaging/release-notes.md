NDPT pings hosts and traces routes live, mtr-style: loss, latency and jitter for every host
and every hop along the way, as it happens. For Windows, Linux and macOS.

There are two programs for each: **ndpt-gui** is the desktop app, **ndpt-tui** the terminal UI.
Neither needs Python. Both take the same options as `ndpt gui` and `ndpt tui`: try `--demo` for
a made-up network that sends nothing, or `--trace 1.1.1.1` to start on a trace.

| | Desktop app | Terminal UI |
|---|---|---|
| Windows 10 or 11 | `ndpt-gui.exe` | `ndpt-tui.exe` |
| Linux (x86_64) | `ndpt-gui-linux-x86_64.tar.gz` | `ndpt-tui-linux-x86_64.tar.gz` |
| Mac with Apple silicon (M1 or later) | `ndpt-gui-macos-arm64.zip` | `ndpt-tui-macos-arm64.zip` |
| Mac with an Intel processor | `ndpt-gui-macos-x86_64.zip` | `ndpt-tui-macos-x86_64.zip` |

None of them is code-signed, so each system warns the first time. Here's how past that.

### Windows

Windows will probably say "Windows protected your PC". Click **More info**, then **Run anyway**.
Run the TUI in Windows Terminal.

### macOS (14 Sonoma or newer)

Not sure which Mac you have? Apple menu > **About This Mac**: "Chip: Apple M…" is Apple
silicon; "Processor: Intel…" is Intel.

Unzip it (double-click), then open it. macOS will say it can't check the app for malicious
software. To open it anyway:

- **macOS 15 or newer:** click **Done**, then open **System Settings > Privacy & Security**,
  scroll down to the message about NDPT, and click **Open Anyway**.
- **macOS 14:** Control-click the app, choose **Open**, then **Open** again.

Or once, in Terminal, from the folder it's in:

```
xattr -dr com.apple.quarantine ndpt-gui.app     (or ndpt-tui)
```

Run the TUI from Terminal: `./ndpt-tui`. Pings need nothing more on a Mac.

### Linux (glibc 2.35 or newer)

Built on Ubuntu 22.04, so it runs there and on anything newer: Ubuntu 22.04, Debian 12,
Fedora 36 and later (`ldd --version` says which glibc you have). Unpack it and run it from a
terminal:

```
tar -xzf ndpt-gui-linux-x86_64.tar.gz
./ndpt-gui
```

The GUI needs a desktop (X11 or Wayland), and uses the system's OpenGL, which every desktop has.

**Pings need permission.** Many distributions let everyone send them; Ubuntu doesn't. If NDPT
says it can't, either open ping sockets to everyone:

```
sudo sysctl -w net.ipv4.ping_group_range="0 2147483647"                                until the next boot
echo 'net.ipv4.ping_group_range = 0 2147483647' | sudo tee /etc/sysctl.d/60-ping.conf   and from then on
```

or run the TUI as root: `sudo ./ndpt-tui`. (`setcap` won't do: a program given a capability
refuses to start, because of how it unpacks itself.)
