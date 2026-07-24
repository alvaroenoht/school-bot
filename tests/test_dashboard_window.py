"""Window-logic tests for the SEDUCA kiosk dashboard.

Runnable two ways (no pytest dependency required in this repo):
    python tests/test_dashboard_window.py      # standalone, prints PASS/FAIL
    pytest tests/test_dashboard_window.py       # if pytest is installed

Reference week (2026-07): Mon 20, Tue 21, Wed 22, Thu 23, Fri 24, Sat 25, Sun 26.
Next Monday from that week = 2026-07-27 .. Fri 2026-07-31.
"""
import os
import sys
from datetime import date, datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.utils.dashboard_window import compute_window


def _w(y, mo, d, h):
    return compute_window(datetime(y, mo, d, h, 0))


def test_monday_before_cutoff_shows_today():
    w = _w(2026, 7, 20, 6)
    assert w["mode"] == "day"
    assert w["relative"] == "today"
    assert w["dates"] == [date(2026, 7, 20)]


def test_monday_after_cutoff_shows_tomorrow():
    w = _w(2026, 7, 20, 8)
    assert w["mode"] == "day"
    assert w["relative"] == "tomorrow"
    assert w["dates"] == [date(2026, 7, 21)]


def test_cutoff_is_inclusive_at_seven():
    # 07:00 = school already started -> roll to tomorrow.
    w = _w(2026, 7, 20, 7)
    assert w["relative"] == "tomorrow"
    assert w["dates"] == [date(2026, 7, 21)]


def test_thursday_after_cutoff_shows_friday():
    w = _w(2026, 7, 23, 8)
    assert w["mode"] == "day"
    assert w["dates"] == [date(2026, 7, 24)]


def test_friday_before_cutoff_shows_friday():
    w = _w(2026, 7, 24, 6)
    assert w["mode"] == "day"
    assert w["relative"] == "today"
    assert w["dates"] == [date(2026, 7, 24)]


def test_friday_after_cutoff_shows_next_week():
    w = _w(2026, 7, 24, 8)
    assert w["mode"] == "week"
    assert w["relative"] is None
    assert w["dates"] == [date(2026, 7, 27), date(2026, 7, 28), date(2026, 7, 29),
                          date(2026, 7, 30), date(2026, 7, 31)]


def test_saturday_shows_next_week():
    w = _w(2026, 7, 25, 10)
    assert w["mode"] == "week"
    assert w["start"] == date(2026, 7, 27)
    assert w["end"] == date(2026, 7, 31)


def test_sunday_shows_next_week():
    w = _w(2026, 7, 26, 23)
    assert w["mode"] == "week"
    assert w["dates"][0] == date(2026, 7, 27)


if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in tests:
        try:
            fn()
            print("PASS  " + fn.__name__)
        except AssertionError as e:
            failures += 1
            print("FAIL  " + fn.__name__ + " -> " + repr(e))
    print("\n" + ("ALL PASS (%d)" % len(tests) if failures == 0 else "%d FAILED" % failures))
    sys.exit(1 if failures else 0)
