"""What ndpt-gui runs: the same as `python -m ndpt gui`, with the program's arguments.

A windowed exe has no console, so sys.stdout and sys.stderr are None and the
first print (argparse's usage message, say) would crash it. They go nowhere
instead.

NDPT_QUIT_AFTER=SECONDS closes the window that long after starting, as if it had
been closed by hand: packaging/smoke.py uses it to check a build starts and quits.
If it's still running 30 s after that, it prints where every thread is and exits.
"""

import faulthandler
import os
import sys
import threading
import time

if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(os.devnull, "w")


def quit_after(seconds: float) -> None:
    faulthandler.dump_traceback_later(seconds + 30, exit=True)

    def close() -> None:
        time.sleep(seconds)
        from PySide6.QtCore import QMetaObject, Qt
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is not None:  # if it isn't up by now, smoke.py waits a while, then says so
            # Queued: this thread isn't Qt's, so the GUI's own thread does the closing.
            QMetaObject.invokeMethod(app, "closeAllWindows", Qt.ConnectionType.QueuedConnection)
    threading.Thread(target=close, daemon=True).start()


if seconds := os.environ.get("NDPT_QUIT_AFTER"):
    quit_after(float(seconds))

from ndpt.cli import main  # noqa: E402

sys.exit(main(["gui", *sys.argv[1:]]))
