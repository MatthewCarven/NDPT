"""Starting the GUI: `python -m ndpt gui`."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from ndpt.core.backends import Prober, make_prober
from ndpt.core.backends.fake import DemoResolver, FakeProber, demo_route
from ndpt.core.resolve import Resolver
from ndpt.gui import theme as themes
from ndpt.gui.bridge import Engine, Settings
from ndpt.gui.main_window import MainWindow

ICON = Path(__file__).with_name("icon.png")  # none until Matthew makes one; build.cmd packs it


def prober_for(settings: Settings, demo: bool) -> Prober:
    """The prober `settings` ask for; on the demo network, always the fake one."""
    if demo:
        return FakeProber(route_factory=demo_route, time_scale=1.0)
    return make_prober(settings.protocol, port=settings.port)


def build(settings: Settings, *, hosts: Sequence[str] = (), trace: str | None = None,
          demo: bool = False, make: Callable[[Settings, bool], Prober] = prober_for,
          resolver: Resolver | None = None, refresh: float | None = None) -> MainWindow:
    """The window, with its engine running. Needs a QApplication first."""
    pg.setConfigOptions(antialias=True)
    theme = themes.current()
    resolver = resolver or (DemoResolver() if demo else Resolver())
    engine = Engine(make(settings, demo), resolver,
                    **({"refresh": refresh} if refresh is not None else {}))
    return MainWindow(engine, settings, theme, hosts=hosts, trace=trace, demo=demo, make=make)


def run(settings: Settings, *, hosts: Sequence[str] = (), trace: str | None = None,
        demo: bool = False) -> int:
    if sys.platform == "win32":
        # Its own taskbar button and icon, rather than grouped under python.exe's.
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("NDPT")
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("NDPT")
    if ICON.exists():
        app.setWindowIcon(QIcon(str(ICON)))
    try:
        window = build(settings, hosts=hosts, trace=trace, demo=demo)
    except (NotImplementedError, OSError) as e:
        # No prober: on Linux, most likely no permission to ping. The caller prints why, but
        # someone who opened the GUI from a file manager has no terminal to see it in.
        cant_probe(e, settings).exec()
        raise
    window.show()
    try:
        return app.exec()
    finally:
        window.shutdown()


def cant_probe(error: Exception, settings: Settings) -> QMessageBox:
    """A box saying why the GUI can't start probing, and what to change; selectable, so the
    command in it can be copied."""
    reason = str(error) or type(error).__name__
    box = QMessageBox(QMessageBox.Icon.Critical, "NDPT", "NDPT can't start probing.")
    more = reason[:1].upper() + reason[1:] + "."
    if settings.protocol == "icmp":
        more += ("\n\nOr ping with TCP handshakes, which needs no permission, by starting "
                 "it with --tcp 443 (TCP can't trace).")
    box.setInformativeText(more)
    box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
    return box
