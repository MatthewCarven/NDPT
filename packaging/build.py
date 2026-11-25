"""Builds NDPT's programs with PyInstaller, for the system it runs on.

    build.cmd               both (python packaging/build.py on Linux and macOS)
    build.cmd gui           just one (tui or gui)
    build.cmd --onedir      a folder per program instead of one file
    build.cmd --release     and put what a release carries in dist/release

Windows: dist/ndpt-tui.exe and dist/ndpt-gui.exe. Linux: dist/ndpt-tui and dist/ndpt-gui.
macOS: dist/ndpt-tui, and the GUI as an app, dist/ndpt-gui.app.

Each program runs on a computer with no Python, on the same system and processor as the
one that built it: PyInstaller can't build for another. If ndpt/gui/icon.png exists,
both programs get it as their icon (not on Linux, whose programs carry none), and the
GUI uses it for its window.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import time
from pathlib import Path

import PyInstaller.__main__

ROOT = Path(__file__).resolve().parent.parent
ICON = ROOT / "ndpt" / "gui" / "icon.png"
DIST = ROOT / "dist"
RELEASE = DIST / "release"
WORK = ROOT / "build"

SYSTEM = {"win32": "windows", "darwin": "macos"}.get(sys.platform, "linux")
ARCH = {"amd64": "x86_64", "aarch64": "arm64"}.get(platform.machine().lower(),
                                                   platform.machine().lower())
BUNDLE_ID = "io.github.matthewcarven.ndpt"  # macOS: the app's identity, for its settings

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


def is_app(target: str) -> bool:
    """Whether `target` builds as a macOS app. A one-file app is on its way out of PyInstaller
    (version 7 refuses it), and an app is a folder anyway, so it's always built as one."""
    return SYSTEM == "macos" and TARGETS[target]["windowed"]


def build(target: str, onedir: bool) -> Path:
    t = TARGETS[target]
    work = WORK / target
    args = [str(ROOT / "packaging" / t["script"]), "--name", t["name"],
            "--onedir" if onedir or is_app(target) else "--onefile",
            "--windowed" if t["windowed"] else "--console",
            "--paths", str(ROOT),  # ndpt itself, without relying on the editable install
            "--distpath", str(DIST), "--workpath", str(work), "--specpath", str(work),
            "--noconfirm", "--clean", "--log-level", "WARN"]
    for package in t["collect"]:
        args += ["--collect-submodules", package]
    for module in t["exclude"] + NEVER:
        args += ["--exclude-module", module]
    if is_app(target):
        args += ["--osx-bundle-identifier", BUNDLE_ID]
    if ICON.exists():
        # Pillow turns the PNG into the .ico Windows wants, or the .icns macOS wants.
        args += ["--icon", str(ICON)]
        if target == "gui":
            args += ["--add-data", f"{ICON}{os.pathsep}ndpt/gui"]
    PyInstaller.__main__.run(args)
    return exe_path(target, onedir)


def exe_path(target: str, onedir: bool) -> Path:
    """What the build makes: the program, or on macOS the GUI's app."""
    name = TARGETS[target]["name"]
    if is_app(target):
        return DIST / f"{name}.app"
    program = name + (".exe" if SYSTEM == "windows" else "")
    return DIST / name / program if onedir else DIST / program


def package(target: str, onedir: bool) -> Path:
    """Puts what a release carries for `target` in dist/release, and returns it.

    On Windows, the .exe itself (or a zip of its folder). Elsewhere an archive, because a
    program downloaded on its own loses its permission to run: a .tar.gz on Linux, and on
    macOS a zip made by `ditto`, which keeps an app's links and signature as Finder would.
    """
    built = exe_path(target, onedir)
    name = TARGETS[target]["name"]
    what = built.parent if onedir and not is_app(target) else built  # the folder, or the file
    RELEASE.mkdir(parents=True, exist_ok=True)
    if SYSTEM == "windows":
        if what.is_file():
            return Path(shutil.copy2(what, RELEASE / what.name))
        return Path(shutil.make_archive(str(RELEASE / f"{name}-windows-{ARCH}"), "zip",
                                        what.parent, what.name))
    if SYSTEM == "macos":
        out = RELEASE / f"{name}-macos-{ARCH}.zip"
        out.unlink(missing_ok=True)
        subprocess.run(["ditto", "-c", "-k", "--sequesterRsrc", "--keepParent", what, out],
                       check=True)
        return out
    out = RELEASE / f"{name}-linux-{ARCH}.tar.gz"
    with tarfile.open(out, "w:gz") as tar:
        tar.add(what, arcname=what.name)
    return out


def in_use(exe: Path) -> bool:
    """Whether Windows won't let the build replace `exe`: it's running, almost always.
    Linux and macOS let a running program's file be replaced."""
    if SYSTEM != "windows":
        return False
    try:
        with open(exe, "r+b"):
            return False
    except FileNotFoundError:
        return False
    except PermissionError:
        return True


def size(path: Path) -> str:
    files = [path] if path.is_file() else [p for p in path.rglob("*")
                                           if p.is_file() and not p.is_symlink()]
    return f"{sum(p.stat().st_size for p in files) / 1e6:.0f} MB"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="build", description=__doc__.splitlines()[0])
    parser.add_argument("targets", nargs="*", metavar="tui|gui", help="what to build (default: both)")
    parser.add_argument("--onedir", action="store_true",
                        help="a folder per program instead of one file: starts faster, but it's a "
                             "folder to carry around rather than one program")
    parser.add_argument("--release", action="store_true",
                        help="also put what a release carries in dist/release: archives on "
                             "Linux and macOS, which keep a program's permission to run")
    args = parser.parse_args(argv)
    unknown = [t for t in args.targets if t not in TARGETS]
    if unknown:
        parser.error(f"don't know how to build {', '.join(unknown)}: choose from tui, gui")
    targets = args.targets or list(TARGETS)
    # Check first: PyInstaller would only find out at the very end, with a traceback.
    busy = [exe for exe in (exe_path(t, args.onedir) for t in targets) if in_use(exe)]
    for exe in busy:
        print(f"{exe.relative_to(ROOT)} is running, so it can't be replaced. "
              f"Close it, then build again.", file=sys.stderr)
    if busy:
        return 1
    built = []
    for target in targets:
        print(f"building {TARGETS[target]['name']} for {SYSTEM} ({ARCH})...", flush=True)
        start = time.monotonic()
        exe = build(target, args.onedir)
        built.append((target, exe, time.monotonic() - start))
    print()
    for target, exe, seconds in built:
        where = exe.parent if args.onedir and not is_app(target) else exe
        print(f"  {exe.relative_to(ROOT)}  ({size(where)}, built in {seconds:.0f} s)")
    if args.release:
        print()
        for target, _, _ in built:
            out = package(target, args.onedir)
            print(f"  {out.relative_to(ROOT)}  ({size(out)})")
    if not ICON.exists():
        print(f"\nNo icon yet: save a square PNG (256x256 or bigger) as "
              f"{ICON.relative_to(ROOT)} and build again.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
