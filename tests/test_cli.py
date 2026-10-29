import pytest

from ndpt.cli import main
from ndpt.textviz import fmt_ms, sparkline
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


def test_tui_and_gui_say_they_are_not_built_yet(capsys):
    assert main(["tui"]) == 2
    assert main(["gui"]) == 2


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


@pytest.mark.parametrize("value, text", [(None, "-"), (0.6123, "0.61"), (12.34, "12.3"), (123.4, "123")])
def test_fmt_ms(value, text):
    assert fmt_ms(value) == text
