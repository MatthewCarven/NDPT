import pytest

from ndpt.cli import main
from ndpt.textviz import bar_chart, fmt_ms, sparkline
from tests.helpers import windows_only


def run(capsys, *args: str) -> tuple[int, str]:
    code = main(list(args))
    return code, capsys.readouterr().out


def test_demo_trace_prints_a_hop_table(capsys):
    code, out = run(capsys, "trace", "--demo", "--report", "-c", "5", "-i", "0.01", "example.com")
    assert code == 0
    assert "trace to example.com (203.0.113." in out
    assert "reached 203.0.113." in out


def test_demo_ping_prints_a_row_per_host(capsys, monkeypatch):
    monkeypatch.setenv("COLUMNS", "120")  # room for "name (address)" in full
    code, out = run(capsys, "ping", "--demo", "--report", "-c", "4", "-i", "0.01",
                    "a.example", "b.example")
    assert code == 0
    assert "a.example (203.0.113." in out and "b.example (203.0.113." in out


def test_refuses_fast_intervals_on_a_real_network(capsys):
    with pytest.raises(SystemExit) as exit_:
        main(["ping", "-i", "0.01", "127.0.0.1"])
    assert exit_.value.code == 2
    assert "only allowed with --demo" in capsys.readouterr().err


def test_gui_passes_its_options_to_the_window(monkeypatch):
    pytest.importorskip("PySide6")
    pytest.importorskip("pyqtgraph")
    import ndpt.gui.app

    calls = []
    monkeypatch.setattr(ndpt.gui.app, "run", lambda settings, **kw: calls.append((settings, kw)) or 0)
    assert main(["gui", "--demo", "--trace"]) == 0
    settings, kw = calls[-1]
    assert kw == {"hosts": ["example.com", "example.net", "example.org"], "trace": "example.com",
                  "demo": True}
    assert main(["gui", "--tcp", "80", "-i", "2", "-m", "12", "-n", "1.1.1.1"]) == 0
    settings, kw = calls[-1]
    assert (settings.protocol, settings.port, settings.interval) == ("tcp", 80, 2.0)
    assert (settings.max_hops, settings.lookup_names) == (12, False)
    assert kw == {"hosts": ["1.1.1.1"], "trace": None, "demo": False}


def test_gui_trace_needs_a_host(capsys):
    with pytest.raises(SystemExit) as exit_:
        main(["gui", "--trace"])
    assert exit_.value.code == 2
    assert "--trace needs a host" in capsys.readouterr().err


@windows_only
@pytest.mark.network
def test_real_ping_to_loopback(capsys):
    code, out = run(capsys, "ping", "--report", "-c", "2", "-i", "0.1", "127.0.0.1")
    assert code == 0
    assert "127.0.0.1" in out


def test_sparkline_scales_from_zero_and_marks_losses():
    assert sparkline([0.0, 5.0, 10.0, None]) == "▁▅█×"
    assert sparkline([0.0, 5.0, 10.0, None], ascii_only=True) == "_=#x"
    assert sparkline([]) == ""


def test_bar_chart_rises_from_zero_in_eighths_and_marks_losses():
    assert bar_chart([8.0, 4.0, 1.0, None, 0.0], height=2) == [
        "█    ",
        "██▂×▁",  # 1 ms is a quarter row; a zero still gets a sliver
    ]
    assert bar_chart([2.0], height=1, top=4.0) == ["▄"]
    assert bar_chart([], height=3) == ["", "", ""]


@pytest.mark.parametrize("value, text", [(None, "-"), (0.6123, "0.61"), (12.34, "12.3"), (123.4, "123")])
def test_fmt_ms(value, text):
    assert fmt_ms(value) == text
