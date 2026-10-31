"""Builds NDPT's Windows programs with PyInstaller: dist/ndpt-tui.exe and dist/ndpt-gui.exe.

    build.cmd               both
    build.cmd gui           just one (tui or gui)
    build.cmd --onedir      a folder per program instead of one file

Each program runs on a Windows PC that has no Python. If ndpt/gui/icon.png
exists, both programs get it as their icon, and the GUI uses it for its window.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "ndpt" / "gui" / "icon.png"
DIST = ROOT / "dist"
WORK = ROOT / "build"

# cli.py imports each front end inside a function, and PyInstaller's import scan
# would pack the other one too: `exclude` leaves it out. `collect` packs every
# submodule of packages that import parts of themselves only when first used
# (textual.widgets, rich's unicode tables), which the scan can't see.
TARGETS = {
    "tui": dict(name="ndpt-tui", script="ndpt_tui.py", windowed=False, collect=["textual", "rich"],
                exclude=["ndpt.gui", "PySide6", "shiboken6", "pyqtgraph", "numpy"]),
    "gui": dict(name="ndpt-gui", script="ndpt_gui.py", windowed=True, collect=["rich"],
                exclude=["ndpt.tui", "textual"]),
}
# The GUI build warns that it failed to collect pyqtgraph.opengl: that's pyqtgraph's 3D, which
# needs PyOpenGL and which NDPT doesn't use. Its PyInstaller hook tries it whatever's excluded.
NEVER = ["tkinter", "pytest", "matplotlib"]  # installed globally here, and not wanted in either


def build(target: str, onedir: bool) -> Path:
    t = TARGETS[target]
    work = WORK / target
    args = [str(ROOT / "packaging" / t["script"]), "--name", t["name"],
            "--onedir" if onedir else "--onefile",
            "--windowed" if t["windowed"] else "--console",
            "--paths", str(ROOT),  # ndpt itself, without relying on the editable install
            "--distpath", str(DIST), "--workpath", str(work), "--specpath", str(work),
            "--noconfirm", "--clean", "--log-level", "WARN"]
    for package in t["collect"]:
        args += ["--collect-submodules", package]
    for module in t["exclude"] + NEVER:
        args += ["--exclude-module", module]
    if ICON.exists():
        args += ["--icon", str(ICON)]  # Pillow turns the PNG into the .ico Windows wants
        if target == "gui":
            args += ["--add-data", f"{ICON}{os.pathsep}ndpt/gui"]
    PyInstaller.__main__.run(args)
    return DIST / t["name"] / f"{t['name']}.exe" if onedir else DIST / f"{t['name']}.exe"


def size(path: Path) -> str:
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    return f"{sum(p.stat().st_size for p in files) / 1e6:.0f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build", description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="*", metavar="tui|gui", help="what to build (default: both)")
    parser.add_argument("--onedir", action="store_true",
                        help="a folder per program instead of one file: starts faster, but it's a "
                             "folder to carry around rather than one .exe")
    args = parser.parse_args(argv)
    unknown = [t for t in args.targets if t not in TARGETS]
    if unknown:
        parser.error(f"don't know how to build {', '.join(unknown)}: choose from tui, gui")
    built = []
    for target in args.targets or list(TARGETS):
        print(f"building {TARGETS[target]['name']}...", flush=True)
        start = time.monotonic()
        exe = build(target, args.onedir)
        built.append((exe, time.monotonic() - start))
    print()
    for exe, seconds in built:
        where = exe.parent if args.onedir else exe
        print(f"  {exe.relative_to(ROOT)}  ({size(where)}, built in {seconds:.0f} s)")
    if not ICON.exists():
        print(f"\nNo icon yet: save a square PNG (256x256 or bigger) as "
              f"{ICON.relative_to(ROOT)} and build again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
