"""What ndpt-tui.exe runs: the same as `python -m ndpt tui`, with the exe's arguments."""

import sys

from ndpt.cli import main

sys.exit(main(["tui", *sys.argv[1:]]))
