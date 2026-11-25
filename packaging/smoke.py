"""Checks a built program starts, runs a few seconds and quits cleanly, as CI does after a build.

    python packaging/smoke.py dist/ndpt-gui --demo        (or dist/ndpt-gui.app on macOS)
    python packaging/smoke.py dist/ndpt-tui --demo        Linux and macOS only

The GUI is told to close its window after a few seconds (NDPT_QUIT_AFTER, which only
the built programs read). The TUI runs on a pseudo-terminal and is sent a `q`. Either
way it must exit with 0 and print no traceback: that catches a module, library or Qt
plugin the build left out, which the tests, run from source, never would.

Linux needs a display for the GUI: `xvfb-run -a python packaging/smoke.py ...`.
"""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

RUN_FOR = 8   # seconds: a one-file GUI spends ~3 of them unpacking itself
LIMIT = 120   # by when it must have quit


def program(path: Path) -> Path:
    """The program inside a macOS app, or the program itself."""
    return path / "Contents" / "MacOS" / path.stem if path.suffix == ".app" else path


def run_gui(exe: Path, args: list[str]) -> tuple[int, str]:
    env = os.environ | {"NDPT_QUIT_AFTER": str(RUN_FOR)}
    done = subprocess.run([exe, *args], env=env, capture_output=True, timeout=LIMIT)
    return done.returncode, (done.stdout + done.stderr).decode(errors="replace")


def run_tui(exe: Path, args: list[str]) -> tuple[int, str]:
    import fcntl
    import pty
    import select
    import struct
    import termios

    main, sub = pty.openpty()
    fcntl.ioctl(sub, termios.TIOCSWINSZ, struct.pack("HHHH", 40, 120, 0, 0))  # rows, columns
    env = os.environ | {"TERM": "xterm-256color"}
    proc = subprocess.Popen([exe, *args], stdin=sub, stdout=sub, stderr=sub, env=env,
                            start_new_session=True)
    os.close(sub)
    output = bytearray()
    start = time.monotonic()
    sent_q = False
    # Keep reading: a full pseudo-terminal would stop the TUI drawing.
    while time.monotonic() - start < LIMIT:
        if not sent_q and time.monotonic() - start >= RUN_FOR:
            os.write(main, b"q")
            sent_q = True
        ready, _, _ = select.select([main], [], [], 0.2)
        if ready:
            try:
                chunk = os.read(main, 65536)
            except OSError:  # Linux: the TUI has gone and closed its end
                chunk = b""
            if not chunk:
                break
            output += chunk
        elif proc.poll() is not None:
            break
    os.close(main)
    try:
        code = proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        raise subprocess.TimeoutExpired(exe, LIMIT) from None
    return code, output.decode(errors="replace")


def main(argv: list[str]) -> int:
    if not argv:
        print(__doc__, file=sys.stderr)
        return 2
    path, args = Path(argv[0]), argv[1:]
    exe = program(path).resolve()
    tui = "tui" in path.name
    if tui and sys.platform == "win32":
        print("smoke: the TUI needs a pseudo-terminal, which this does only on Linux and macOS",
              file=sys.stderr)
        return 2
    start = time.monotonic()
    try:
        code, output = (run_tui if tui else run_gui)(exe, args)
    except subprocess.TimeoutExpired:
        print(f"smoke: {path} was still running after {LIMIT} s: it didn't quit when told to. "
              f"(On Windows, a windowed program that crashes leaves an error box open.)")
        return 1
    seconds = time.monotonic() - start
    crashed = code != 0 or "Traceback" in output
    if crashed or os.environ.get("SMOKE_SHOW"):
        print(output[-6000:])
    print(f"smoke: {path} {' '.join(args)}: exit code {code} after {seconds:.0f} s"
          + (", and a traceback" if "Traceback" in output else "")
          + ("" if crashed else ": ok"))
    return 1 if crashed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
