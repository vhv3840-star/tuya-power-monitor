import pytest
from backend.domain import SessionTracker, in_window


def test_session_debounce_and_energy():
    tracker = SessionTracker(start_w=5, end_w=2, hold_s=10)
    assert tracker.feed(0, 60) == 'started'
    tracker.feed(10, 60)
    assert tracker.energy_kwh == pytest.approx(60 * 10 / 3600000)
    assert tracker.feed(11, 1) is None
    assert tracker.feed(19, 1) is None
    assert tracker.feed(20, 10) is None  # recovery resets hold
    assert tracker.feed(21, 1) is None
    assert tracker.feed(31, 1) == 'completed'
    assert tracker.peak_w == 60


def test_missing_reading_does_not_integrate_or_complete():
    tracker = SessionTracker(start_w=5, end_w=2, hold_s=10)
    tracker.feed(0, 100)
    tracker.feed(1, 1)
    tracker.feed(5, None)
    tracker.feed(100, 1)
    assert tracker.active
    assert tracker.energy_kwh < .0001
    assert tracker.feed(110, 1) == 'completed'


def test_large_poll_gap_is_not_energy():
    tracker = SessionTracker(start_w=5, end_w=2, hold_s=10, max_gap_s=30)
    tracker.feed(0, 1000)
    tracker.feed(3600, 1000)
    assert tracker.energy_kwh == 0


def test_night_window():
    assert in_window('23:15', '23:00', '07:00')
    assert in_window('06:59', '23:00', '07:00')
    assert not in_window('07:00', '23:00', '07:00')
    assert in_window('12:00', '09:00', '17:00')


def test_short_power_spike_does_not_start_charge():
    tracker=SessionTracker(start_w=5,end_w=2,hold_s=10,start_hold_s=5)
    assert tracker.feed(0,60) is None
    assert tracker.feed(2,0) is None
    assert tracker.feed(3,60) is None
    assert tracker.feed(8,60)=='started'
    assert tracker.started_at==3
    assert tracker.energy_kwh==pytest.approx(60*5/3600000)


def test_missing_reading_resets_start_confirmation():
    tracker=SessionTracker(start_w=5,end_w=2,hold_s=10,start_hold_s=5)
    tracker.feed(0,60)
    tracker.feed(3,None)
    assert tracker.feed(7,60) is None
    assert tracker.feed(12,60)=='started'
    assert tracker.started_at==7
