"""Pure date-window logic for the SEDUCA iPad kiosk dashboard.

Kept free of DB / settings imports so it stays trivially unit-testable with an
injected `now`. Consumed by app/api/admin/dashboard.py.

Rule (America/Panama, 7 AM school-start cutoff):
  * Mon-Thu before 07:00 -> today;  at/after 07:00 -> tomorrow  (single day)
  * Fri before 07:00      -> Friday; at/after 07:00 -> full next week (Mon-Fri)
  * Sat/Sun               -> full next week (Mon-Fri)
"""
from datetime import date, datetime, timedelta

from app.utils.summary_formatter import months_es, translate_date

SCHOOL_START_HOUR = 7   # kids start at 7:00; "today" is only relevant before then


def _next_monday(today: date) -> date:
    days = (0 - today.weekday()) % 7
    return today + timedelta(days=days or 7)


def _week_window(today: date) -> dict:
    start = _next_monday(today)
    end = start + timedelta(days=4)
    dates = [start + timedelta(days=i) for i in range(5)]
    month = months_es[end.strftime("%B")]
    label = f"Semana del {start.strftime('%d')} al {end.strftime('%d')} de {month}"
    return {"mode": "week", "dates": dates, "start": start, "end": end,
            "relative": None, "range_label": label}


def _day_window(today: date, target: date) -> dict:
    if target == today:
        rel = "today"
    elif target == today + timedelta(days=1):
        rel = "tomorrow"
    else:
        rel = None
    return {"mode": "day", "dates": [target], "start": target, "end": target,
            "relative": rel, "range_label": translate_date(target)}


def compute_window(now: datetime) -> dict:
    """Given a Panama-local `now`, return which dates the kiosk should display."""
    today = now.date()
    wd = today.weekday()                 # 0=Mon .. 6=Sun
    before_cutoff = now.hour < SCHOOL_START_HOUR

    if wd >= 5:                          # Sat / Sun
        return _week_window(today)
    if wd == 4:                          # Friday
        return _day_window(today, today) if before_cutoff else _week_window(today)
    # Mon-Thu
    return _day_window(today, today) if before_cutoff else _day_window(today, today + timedelta(days=1))
