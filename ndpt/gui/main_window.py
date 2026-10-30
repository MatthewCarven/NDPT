"""The main window: a tab per job, over one engine."""

from __future__ import annotations

from collections.abc import Callable, Sequence

from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import QMainWindow, QTabWidget

from ndpt.core.backends import Prober
from ndpt.gui.bridge import Engine, Settings
from ndpt.gui.ping_view import PingView
from ndpt.gui.theme import Theme


class MainWindow(QMainWindow):
    """Ping and trace tabs, both running at once. Closing the window stops everything.

    `make(settings, demo)` makes a prober, for when the settings change it.
    """

    def __init__(self, engine: Engine, settings: Settings, theme: Theme, *,
                 hosts: Sequence[str] = (), demo: bool = False,
                 make: Callable[[Settings, bool], Prober] | None = None) -> None:
        super().__init__()
        self.engine = engine
        self.settings = settings
        self.demo = demo
        self.make = make
        self.setWindowTitle("NDPT" + (" (demo network: nothing is sent)" if demo else ""))
        self.tabs = QTabWidget()
        self.ping_view = PingView(engine, settings, theme, hosts)
        self.tabs.addTab(self.ping_view, "Ping")
        self.setCentralWidget(self.tabs)
        self.resize(1280, 820)
        self.ping_view.start()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        """Stop the sessions and the loop thread. Safe to call more than once."""
        self.ping_view.runner = None
        self.engine.shutdown()
