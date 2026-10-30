"""Starting the GUI: `python -m ndpt gui`."""

from __future__ import annotations

import sys
from collections.abc import Callable, Sequence

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

from ndpt.core.backends import Prober, make_prober
from ndpt.core.backends.fake import DemoResolver, FakeProber, demo_route
from ndpt.core.resolve import Resolver
from ndpt.gui import theme as themes
from ndpt.gui.bridge import Engine, Settings
from ndpt.gui.main_window import MainWindow


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
    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("NDPT")
    window = build(settings, hosts=hosts, trace=trace, demo=demo)
    window.show()
    try:
        return app.exec()
    finally:
        window.shutdown()
