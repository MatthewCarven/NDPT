import asyncio

import pytest

pytest.importorskip("textual")

from textual.widgets import DataTable, Input  # noqa: E402

from ndpt.cli import main  # noqa: E402
from ndpt.core.backends.fake import DemoResolver, FakeProber, demo_route  # noqa: E402
from ndpt.tui.app import NdptApp, Settings  # noqa: E402
from ndpt.tui.ping_screen import PingScreen, PingStrip  # noqa: E402
from ndpt.tui.trace_screen import TraceScreen  # noqa: E402
from ndpt.tui.widgets import HistoryScreen, HostPrompt, share_width  # noqa: E402

FAST = Settings(interval=0.02, timeout=0.5)
SIZE = (120, 40)


def make_app(hosts=("example.com", "example.net"), **kwargs) -> NdptApp:
    # time_scale=0: every probe is answered as soon as its task runs.
    return NdptApp(FakeProber(route_factory=demo_route), DemoResolver(), FAST, hosts=hosts, **kwargs)


async def until(pilot, condition, timeout: float = 3.0) -> None:
    """Let the app run until `condition()` holds."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not condition():
        assert loop.time() < deadline, "timed out waiting for the app"
        await pilot.pause(0.02)


def column(app: NdptApp, key: str) -> list[str]:
    table = app.screen.query_one(DataTable)
    return [str(value) for value in table.get_column(key)]


def history_head(app: NdptApp) -> str:
    return str(app.screen.query_one("#history-head").render())


async def test_ping_screen_shows_each_host_with_its_numbers():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        assert isinstance(app.screen, PingScreen)
        session = app.ping_screen.session
        await until(pilot, lambda: all(t.stats.received >= 3 for t in session.targets))
        # The table redraws on a timer: wait for it, not for a fixed time (GitHub's machines are slow).
        await until(pilot, lambda: len(sent := column(app, "Sent")) == 2 and all(int(n) >= 3 for n in sent))
        hosts = column(app, "host")
        assert len(hosts) == 2
        assert hosts[0].startswith("example.com (203.0.113.") and hosts[1].startswith("example.net (")
        assert all(int(sent) >= 3 for sent in column(app, "Sent"))
        strip = str(app.screen.query_one(PingStrip).render())
        assert "example.com (203.0.113." in strip and "avg" in strip and "loss" in strip
        assert "fake every 0.02s" in app.screen.sub_title


async def test_a_adds_hosts_and_d_removes_the_highlighted_one():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("a")
        assert isinstance(app.screen, HostPrompt)
        await pilot.press(*"192.0.2.7 example.com", "enter")  # example.com is already there
        session = app.ping_screen.session
        assert [t.name for t in session.targets] == ["example.com", "example.net", "192.0.2.7"]
        await until(pilot, lambda: len(column(app, "host")) == 3)
        await until(pilot, lambda: session.targets[2].stats.received > 0)
        await pilot.press("down", "d")
        assert [t.name for t in session.targets] == ["example.com", "192.0.2.7"]
        await until(pilot, lambda: len(column(app, "host")) == 2)


async def test_plus_and_minus_probe_less_or_more_often_but_not_faster_than_the_start():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        session = app.ping_screen.session
        await pilot.press("plus")
        assert session.interval == 1.0 and "every 1s" in app.screen.sub_title
        await pilot.press("equals_sign")  # + without shift
        assert session.interval == 2.0
        await pilot.press("minus", "minus")
        assert session.interval == 0.02
        await pilot.press("minus")
        assert session.interval == 0.02 and "every 0.02s" in app.screen.sub_title


async def test_escape_leaves_the_host_list_alone():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("a", "x", "escape")
        assert isinstance(app.screen, PingScreen)
        assert len(app.ping_screen.session.targets) == 2


async def test_space_pauses_and_resumes_the_screen_on_show():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        target = app.ping_screen.session.targets[0]
        await until(pilot, lambda: target.stats.sent >= 2)
        await pilot.press("space")
        assert app.ping_screen.session.paused and "[paused]" in app.screen.sub_title
        await pilot.pause(0.1)
        sent = target.stats.sent
        await pilot.pause(0.2)
        assert target.stats.sent == sent
        await pilot.press("space")
        await until(pilot, lambda: target.stats.sent > sent)
        assert "[paused]" not in app.screen.sub_title


async def test_enter_traces_the_highlighted_host():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("down", "enter")
        assert isinstance(app.screen, TraceScreen)
        session = app.trace_screen.session
        assert session.host == "example.net"
        await until(pilot, lambda: session.dest_ttl is not None and session.round >= 3)
        await until(pilot, lambda: len(column(app, "ttl")) == session.dest_ttl)
        assert column(app, "host")[-1].startswith("example.net (203.0.113.")
        assert "to example.net (203.0.113." in app.screen.sub_title
        history = column(app, "history")
        assert history[0] and set(history[0]) <= set("▁▂▃▄▅▆▇█×")


async def test_t_and_p_switch_screens_and_both_keep_running():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("t")
        assert isinstance(app.screen, TraceScreen)
        assert app.trace_screen.session.host == "example.com"  # the highlighted host
        await pilot.press("p")
        assert isinstance(app.screen, PingScreen)
        trace = app.trace_screen.session
        rounds = trace.round
        await until(pilot, lambda: trace.round > rounds)  # still tracing while hidden
        await pilot.press("t")
        assert app.trace_screen.session is trace  # back to the same trace, not a new one


async def test_enter_on_a_hop_opens_its_history():
    app = make_app(start="trace")
    async with app.run_test(size=SIZE) as pilot:
        session = app.trace_screen.session
        await until(pilot, lambda: session.dest_ttl is not None and len(column(app, "ttl")) >= 3)
        await pilot.press("down", "enter")
        assert isinstance(app.screen, HistoryScreen)
        await until(pilot, lambda: "answered by " in history_head(app))
        head = history_head(app)
        assert head.startswith("hop 2: ") and "sent " in head
        await pilot.press("escape")
        assert isinstance(app.screen, TraceScreen)


async def test_h_shows_a_hosts_history():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await until(pilot, lambda: app.ping_screen.session.targets[0].stats.received > 0)
        await pilot.press("h")
        assert isinstance(app.screen, HistoryScreen)
        await until(pilot, lambda: history_head(app).startswith("example.com ("))


async def test_a_on_the_trace_screen_traces_another_host():
    app = make_app(start="trace")
    async with app.run_test(size=SIZE) as pilot:
        first = app.trace_screen.session
        await pilot.press("a")
        prompt = app.screen.query_one(Input)
        assert prompt.value == "example.com"
        prompt.value = "example.org"
        await pilot.press("enter")
        assert app.trace_screen.session.host == "example.org"
        assert first.stopping
        await until(pilot, lambda: app.trace_screen.session.dest_ttl is not None)


async def test_with_no_hosts_it_says_how_to_add_one_and_t_asks_what_to_trace():
    app = make_app(hosts=())
    async with app.run_test(size=SIZE) as pilot:
        assert "press a to add one" in str(app.screen.query_one(PingStrip).render())
        await pilot.press("t")
        assert isinstance(app.screen, HostPrompt)
        await pilot.press(*"example.com", "enter")
        assert isinstance(app.screen, TraceScreen)
        assert app.trace_screen.session.host == "example.com"


async def test_q_stops_the_sessions_and_quits():
    app = make_app()
    async with app.run_test(size=SIZE) as pilot:
        await pilot.press("t")
        await pilot.press("q")
        await pilot.pause()
    assert app.ping_screen.session.stopping and app.trace_screen.session.stopping
    assert app.return_code == 0


def test_tui_command_runs_the_app_with_the_demo_hosts(monkeypatch):
    seen = {}

    async def fake_run(app):
        seen.update(hosts=app.hosts, start=app.start, settings=app.settings,
                    prober=app.prober.name)

    monkeypatch.setattr(NdptApp, "run_async", fake_run)
    assert main(["tui", "--demo", "--trace", "-i", "0.5", "-m", "12"]) == 0
    assert seen["hosts"] == ["example.com", "example.net", "example.org"]
    assert seen["start"] == "trace" and seen["prober"] == "fake"
    assert seen["settings"].interval == 0.5 and seen["settings"].max_hops == 12


def test_tui_trace_needs_a_host(capsys):
    with pytest.raises(SystemExit):
        main(["tui", "--trace"])
    assert "--trace needs a host" in capsys.readouterr().err


@pytest.mark.parametrize("total, longest, expected", [
    (200, 20, (20, 60)),   # room for everything: history stops at 60 samples
    (100, 60, (36, 36)),   # long names stop at 36 and the history takes the rest
    (60, 30, (24, 8)),     # names give way until the history is down to 8
    (40, 30, (12, 0)),     # too narrow for a history: the names get what's left
    (200, 6, (6, 60)),     # short names stay short
])
def test_share_width(total, longest, expected):
    # 20 cells of other columns, 4 columns in all with a cell of padding either side
    assert share_width(total, fixed=20, columns=4, longest_host=longest, max_history=60) == expected


def test_share_width_without_a_history_column():
    assert share_width(200, fixed=20, columns=4, longest_host=60) == (60, 0)
