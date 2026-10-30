"""The main window: a tab per job, over one engine."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ndpt.core.backends import Prober
from ndpt.gui.bridge import Engine, Settings
from ndpt.gui.ping_view import PingView
from ndpt.gui.theme import Theme
from ndpt.gui.trace_view import TraceView

ROUTE_CHANGE_MS = 8000  # how long a route change stays in the status bar


class MainWindow(QMainWindow):
    """Ping and trace tabs, both running at once. Closing the window stops everything.

    `make(settings, demo)` makes a prober, for when the settings change it.
    """

    def __init__(self, engine: Engine, settings: Settings, theme: Theme, *,
                 hosts: Sequence[str] = (), trace: str | None = None, demo: bool = False,
                 make: Callable[[Settings, bool], Prober] | None = None) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.demo = demo
        self.make = make
        self.setWindowTitle("NDPT" + (" (demo network: nothing is sent)" if demo else ""))
        self.tabs = QTabWidget()
        self.ping_view = PingView(engine, settings, theme, hosts)
        self.trace_view = TraceView(engine, settings, theme)
        self.tabs.addTab(self.ping_view, "Ping")
        self.tabs.addTab(self.trace_view, "Trace")
        self.setCentralWidget(self.tabs)
        self.ping_view.trace_requested.connect(self.trace)
        self.trace_view.route_changed.connect(
            lambda text: self.statusBar().showMessage(f"route change: {text}", ROUTE_CHANGE_MS))
        self.resize(1280, 820)
        self.ping_view.start()
        if trace:
            self.trace(trace)

    def trace(self, host: str) -> None:
        """Show the trace tab, tracing `host` (from scratch, unless it's already the one)."""
        self.tabs.setCurrentWidget(self.trace_view)
        if host != self.trace_view.host or self.trace_view.runner is None:
            self.trace_view.trace(host)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Stop the sessions and the loop thread. Safe to call more than once."""
        self.ping_view.runner = None
        self.trace_view.runner = None
        self.engine.shutdown()
