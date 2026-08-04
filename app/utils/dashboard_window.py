"""Pure date-window logic for the SEDUCA iPad kiosk dashboard.

Kept free of DB / settings imports so it stays trivially unit-testable with an
injected `now`. Consumed by app/api/admin/dashboard.py.

Rule (America/Panama, 7 AM school-start cutoff):
  * Mon-Thu before 07:00 -> today + the next school day      (2-day view)
  * Mon-Thu at/after 07:00 -> tomorrow + the school day after (2-day view)
  * Fri before 07:00      -> Friday + next Monday             (2-day view)
  * Fri at/after 07:00    -> full next week (Mon-Fri)
  * Sat/Sun               -> full next week (Mon-Fri)

The day view always spans two *school* days, so weekends are skipped: on
Thursday afternoon the kiosk shows Friday and next Monday, never Saturday.
"""
from datetime import date, datetime, timedelta

from app.utils.summary_formatter import days_es, months_es

SCHOOL_START_HOUR = 7   # kids start at 7:00; "today" is only relevant before then


def _next_monday(today: date) -> date:
    days = (0 - today.weekday()) % 7
    return today + timedelta(days=days or 7)


def _next_school_day(d: date) -> date:
    """First Mon-Fri strictly after `d` (skips Sat/Sun)."""
    nxt = d + timedelta(days=1)
    while nxt.weekday() >= 5:
        nxt += timedelta(days=1)
    return nxt


def relative_label(today: date, d: date) -> str | None:
    """"today" / "tomorrow" / None — used to head each day column on the kiosk."""
    if d == today:
        return "today"
    if d == today + timedelta(days=1):
        return "tomorrow"
    return None


def _week_window(today: date) -> dict:
    start = _next_monday(today)
    end = start + timedelta(days=4)
    dates = [start + timedelta(days=i) for i in range(5)]
    month = months_es[end.strftime("%B")]
    label = f"Semana del {start.strftime('%d')} al {end.strftime('%d')} de {month}"
    return {"mode": "week", "dates": dates, "start": start, "end": end,
            "relative": None, "range_label": label, "badge": "Próxima semana"}


def _day_range_label(a: date, b: date) -> str:
    """e.g. "22 y 23 de julio" — or "31 de julio y 3 de agosto" across months."""
    ma, mb = months_es[a.strftime("%B")], months_es[b.strftime("%B")]
    if ma == mb:
        return f"{a.day} y {b.day} de {mb}"
    return f"{a.day} de {ma} y {b.day} de {mb}"


def _day_badge(today: date, a: date, b: date) -> str:
    """e.g. "Hoy y mañana", "Hoy y lunes", "Viernes y lunes"."""
    def name(d: date) -> str:
        rel = relative_label(today, d)
        if rel == "today":
            return "Hoy"
        if rel == "tomorrow":
            return "Mañana"
        return days_es[d.strftime("%A")]
    return f"{name(a)} y {name(b).lower()}"


def _day_window(today: date, first: date) -> dict:
    second = _next_school_day(first)
    return {"mode": "day", "dates": [first, second], "start": first, "end": second,
            "relative": relative_label(today, first),
            "range_label": _day_range_label(first, second),
            "badge": _day_badge(today, first, second)}


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
    return _day_window(today, today if before_cutoff else _next_school_day(today))
