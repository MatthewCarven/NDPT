"""The main window: a tab per job, over one engine."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ndpt.core.backends import Prober
from ndpt.gui.bridge import Engine, Settings
from ndpt.gui.ping_view import PingView
from ndpt.gui.settings_view import SettingsView
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
        self.settings_view = SettingsView(settings, theme, demo)
        self.tabs.addTab(self.ping_view, "Ping")
        self.tabs.addTab(self.trace_view, "Trace")
        self.tabs.addTab(self.settings_view, "Settings")
        self.setCentralWidget(self.tabs)
        self.tabs.currentChanged.connect(self._tab_changed)
        self.ping_view.trace_requested.connect(self.trace)
        self.settings_view.applied.connect(self.apply)
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

    def _tab_changed(self, index: int) -> None:
        view = self.tabs.widget(index)
        if view is self.ping_view or view is self.trace_view:
            view.catch_up()  # a hidden tab keeps its snapshots but doesn't draw them

    def apply(self, settings: Settings) -> None:
        """Restart both tabs' probes with new settings, and a new prober if they ask for one."""
        old = self.settings
        prober = None
        if (settings.protocol, settings.port) != (old.protocol, old.port) and not self.demo:
            try:
                prober = self.make(settings, self.demo)
            except (NotImplementedError, OSError, ValueError) as e:
                self.settings_view.refused(f"Can't probe that way: {e}")
                return
        tracing = self.trace_view.runner is not None
        self.ping_view.stop()
        self.trace_view.stop()
        if prober is not None:
            self.engine.swap_prober(prober)  # closes the old one once its sessions have stopped
        self.settings = settings
        self.ping_view.start(settings)
        self.trace_view.restart(settings, again=tracing)
        self.settings_view.accepted(settings)
        self.statusBar().showMessage("settings applied: the probes started again", ROUTE_CHANGE_MS)

    def closeEvent(self, event: QCloseEvent) -> None:
        self.hide()  # at once: shutting down can wait up to a second on reverse-DNS lookups
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Stop the sessions and the loop thread. Safe to call more than once."""
        self.ping_view.runner = None
        self.trace_view.runner = None
        self.engine.shutdown()
