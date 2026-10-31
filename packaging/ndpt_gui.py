"""What ndpt-gui.exe runs: the same as `python -m ndpt gui`, with the exe's arguments.

A windowed exe has no console, so sys.stdout and sys.stderr are None and the
first print (argparse's usage message, say) would crash it. They go nowhere
instead.
"""

import os
import sys

if sys.stdout is None or sys.stderr is None:
    sys.stdout = sys.stderr = open(os.devnull, "w")

from ndpt.cli import main  # noqa: E402

sys.exit(main(["gui", *sys.argv[1:]]))
