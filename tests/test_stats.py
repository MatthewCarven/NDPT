import pytest

from ndpt.core.stats import RollingStats


def test_empty_stats_have_no_numbers():
    s = RollingStats()
    assert (s.sent, s.received, s.loss_pct) == (0, 0, 0.0)
    assert s.avg is None and s.stdev is None and s.percentile(50) is None


def test_counts_loss_and_extremes():
    s = RollingStats()
    for rtt in [10.0, None, 30.0, 20.0, None]:
        s.add(rtt)
    assert (s.sent, s.received, s.lost) == (5, 3, 2)
    assert s.loss_pct == pytest.approx(40.0)
    assert (s.best, s.worst, s.last) == (10.0, 30.0, 20.0)
    assert s.avg == pytest.approx(20.0)
    assert s.stdev == pytest.approx(10.0)  # sample standard deviation of 10, 30, 20


def test_jitter_is_rfc3550_smoothed():
    s = RollingStats()
    for rtt in [10.0, 20.0, 10.0]:
        s.add(rtt)
    first = 10 / 16
    assert s.jitter == pytest.approx(first + (10 - first) / 16)


def test_a_lost_probe_does_not_break_the_jitter_chain():
    s = RollingStats()
    for rtt in [10.0, None, 20.0]:
        s.add(rtt)
    assert s.jitter == pytest.approx(10 / 16)


def test_window_keeps_only_recent_samples_but_counters_keep_everything():
    s = RollingStats(window=3)
    for i, rtt in enumerate([1.0, 2.0, None, 4.0]):
        s.add(rtt, sent_at=100.0 + i)
    assert s.recent() == [2.0, None, 4.0]
    assert [t for t, _ in s.history] == [101.0, 102.0, 103.0]
    assert (s.sent, s.best) == (4, 1.0)


def test_percentile_interpolates_over_received_samples():
    s = RollingStats()
    for rtt in [10.0, 20.0, 30.0, 40.0, None]:
        s.add(rtt)
    assert s.percentile(0) == 10.0
    assert s.percentile(50) == pytest.approx(25.0)
    assert s.percentile(100) == 40.0
