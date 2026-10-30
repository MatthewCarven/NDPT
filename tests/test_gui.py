import os
import threading
import time

import pytest

pytest.importorskip("PySide6")
pytest.importorskip("pyqtgraph")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")  # before the QApplication exists

from PySide6.QtCore import QObject  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ndpt.core.backends.fake import DemoResolver, FakeHop, FakeProber, demo_route  # noqa: E402
from ndpt.gui.app import build  # noqa: E402
from ndpt.gui.bridge import Engine, Settings  # noqa: E402

FAST = Settings(interval=0.02, timeout=0.5)
REFRESH = 0.05  # snapshots this often, so the tests don't wait on the GUI's quarter second


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def until(condition, timeout: float = 5.0) -> None:
    """Run the Qt event loop until `condition()` holds."""
    deadline = time.monotonic() + timeout
    while not condition():
        assert time.monotonic() < deadline, "timed out waiting for the GUI"
        QApplication.processEvents()
        time.sleep(0.01)


def spin(seconds: float) -> None:
    """Run the Qt event loop for a while, for checking that something *doesn't* happen."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.01)


@pytest.fixture
def window(qapp):
    """Makes windows on the fake network (answering at once), and closes them after the test."""
    made = []

    def make(hosts=("example.com", "example.net"), prober=None, settings=FAST, **kwargs):
        probers = [prober] if prober else []

        def new_prober(settings, demo):  # a fresh one each time the settings change it
            p = probers.pop() if probers else FakeProber(route_factory=demo_route)
            made_probers.append(p)
            return p

        made_probers = []
        w = build(settings, hosts=hosts, make=new_prober, resolver=DemoResolver(), refresh=REFRESH,
                  **kwargs)
        w.probers = made_probers
        made.append(w)
        return w

    yield make
    for w in made:
        w.close()
    QApplication.processEvents()


def test_snapshots_arrive_on_the_qt_thread(qapp):
    engine = Engine(FakeProber(route_factory=demo_route), DemoResolver(), refresh=REFRESH)
    seen = []

    class Catcher(QObject):
        def take(self, snapshot):
            seen.append((threading.current_thread() is threading.main_thread(), snapshot))

    catcher = Catcher()
    try:
        runner = engine.ping(["example.com"], FAST)
        runner.updated.connect(catcher.take)
        until(lambda: seen and seen[-1][1].targets[0].stats.received >= 3)
        assert all(on_qt_thread for on_qt_thread, _ in seen)
    finally:
        engine.shutdown()
    assert not engine.loop._thread.is_alive()


def test_ping_tab_charts_and_tabulates_every_host(window):
    view = window().ping_view
    until(lambda: view.snapshot and all(t.stats.received >= 5 for t in view.snapshot.targets))
    assert view.table.rowCount() == 2
    assert view.table.item(0, 0).text().startswith("example.com (203.0.113.")
    assert view.table.item(1, 0).text().startswith("example.net (203.0.113.")
    assert int(view.table.item(0, 1).text()) >= 5
    assert view.table.item(0, 2).text().endswith("%")
    assert [view.host_list.item(i).text() for i in range(2)] == \
        [view.table.item(0, 0).text(), view.table.item(1, 0).text()]
    assert set(view.chart.curves) == {"example.com", "example.net"}
    xs, ys = view.chart.curves["example.com"].getData()
    assert len(xs) >= 5 and (ys > 0).all()
    assert view.histogram.curves["example.com"].getData()[1].sum() >= 5  # a count per answer
    assert view.colour("example.com") != view.colour("example.net")
    assert "fake every 0.02s" in view.status.text()


def test_lost_probes_show_as_red_ticks_and_count_as_loss(window):
    prober = FakeProber({"192.0.2.9": [FakeHop("192.0.2.9", rtts=[5.0, None])]})
    view = window(hosts=("192.0.2.9",), prober=prober).ping_view
    until(lambda: view.snapshot and view.snapshot.targets[0].stats.sent >= 6)
    s = view.snapshot.targets[0].stats
    assert s.lost >= 3 and 40 <= s.loss_pct <= 60  # every other probe
    assert len(view.chart.lost.data) == s.lost
    assert set(view.chart.lost.data["y"]) == {0.0}  # along the bottom
    assert view.table.item(0, 2).text() == f"{s.loss_pct:.1f}%"


def test_hosts_can_be_added_and_removed_while_it_runs(window):
    view = window(hosts=("example.com",)).ping_view
    until(lambda: view.host_list.count() == 1)
    view.entry.setText("example.net 192.0.2.7 example.com")  # example.com is already there
    view.add_button.click()
    assert view.names == ["example.com", "example.net", "192.0.2.7"]
    until(lambda: view.host_list.count() == 3 and view.table.rowCount() == 3)
    until(lambda: set(view.chart.curves) == {"example.com", "example.net", "192.0.2.7"})
    net_colour = view.colour("example.net")

    view.host_list.setCurrentRow(1)
    assert view.selected().name == "example.net"
    view.remove_button.click()
    until(lambda: [t.name for t in view.snapshot.targets] == ["example.com", "192.0.2.7"])
    until(lambda: set(view.chart.curves) == {"example.com", "192.0.2.7"})
    assert view.host_list.count() == 2 and view.table.rowCount() == 2
    assert view.add("example.org")
    assert view.colour("example.org") == net_colour  # the freed colour goes to the next host


def test_pause_holds_the_probes_and_resume_takes_them_up(window):
    w = window(hosts=("example.com",))
    view, prober = w.ping_view, w.probers[0]
    until(lambda: view.snapshot and view.snapshot.targets[0].stats.sent >= 3)
    view.pause_button.click()
    until(lambda: view.snapshot.paused)
    assert view.pause_button.text() == "Resume" and "paused" in view.status.text()
    sent = len(prober.probes)
    spin(0.3)
    assert len(prober.probes) == sent
    view.pause_button.click()
    until(lambda: len(prober.probes) >= sent + 5)
    until(lambda: not view.snapshot.paused)


def test_closing_the_window_stops_the_sessions_and_the_loop(window):
    w = window()
    until(lambda: w.ping_view.snapshot is not None)
    w.close()
    assert not w.engine.loop._thread.is_alive()
    QApplication.processEvents()
    assert not w.engine.runners  # each session said it had finished
