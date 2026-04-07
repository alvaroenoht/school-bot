"""
Thin wrapper around icalendar + recurring_ical_events.

Fetches an iCal feed and returns events whose reminder day matches today,
based on VALARM triggers (or sensible fallbacks).
"""
import logging
from datetime import date, timedelta, datetime

import requests
import icalendar
import recurring_ical_events

logger = logging.getLogger(__name__)

_FALLBACK_DAYS = {7, 1}


def get_due_reminders(ical_url: str, today: date) -> list[dict]:
    """
    Fetch the iCal feed and return events that should be notified today.

    Each returned dict has:
      summary      – event title
      description  – optional event description
      event_date   – the concrete occurrence date (date object)
      is_birthday  – True if title contains 'cumpleaños'
      days_before  – 0 for birthdays on the day, N for advance reminders
    """
    try:
        resp = requests.get(ical_url, timeout=15)
        resp.raise_for_status()
    except Exception as e:
        logger.error("ICAL fetch failed url=%s: %s", ical_url, e)
        return []

    try:
        cal = icalendar.Calendar.from_ical(resp.content)
    except Exception as e:
        logger.error("ICAL parse failed url=%s: %s", ical_url, e)
        return []

    # Expand recurring events up to 60 days out so we can evaluate VALARMs
    look_ahead = today + timedelta(days=60)
    try:
        occurrences = recurring_ical_events.of(cal).between(today, look_ahead)
    except Exception as e:
        logger.error("ICAL recurrence expansion failed: %s", e)
        return []

    results: list[dict] = []
    seen: set[tuple] = set()  # (summary, event_date, days_before) dedup key

    for component in occurrences:
        if component.name != "VEVENT":
            continue

        summary = str(component.get("SUMMARY", "")).strip()
        description = str(component.get("DESCRIPTION", "")).strip() or None

        # Resolve the event date (DTSTART may be a date or datetime)
        dtstart = component.get("DTSTART")
        if not dtstart:
            continue
        dtstart_val = dtstart.dt
        if isinstance(dtstart_val, datetime):
            event_date = dtstart_val.date()
        else:
            event_date = dtstart_val  # already a date

        is_birthday = "cumpleaños" in summary.lower()

        if is_birthday:
            # Always remind day-of
            if event_date == today:
                key = (summary, event_date, 0)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "summary": summary,
                        "description": description,
                        "event_date": event_date,
                        "is_birthday": True,
                        "days_before": 0,
                    })
            continue

        # Collect VALARM trigger days
        trigger_days: set[int] = set()
        for sub in component.subcomponents:
            if sub.name != "VALARM":
                continue
            trigger = sub.get("TRIGGER")
            if not trigger:
                continue
            td = trigger.dt if hasattr(trigger, "dt") else trigger
            if isinstance(td, timedelta) and td.total_seconds() < 0:
                days = int(abs(td.total_seconds()) / 86400)
                if days > 0:
                    trigger_days.add(days)

        if not trigger_days:
            trigger_days = _FALLBACK_DAYS

        for days in trigger_days:
            reminder_date = event_date - timedelta(days=days)
            if reminder_date == today:
                key = (summary, event_date, days)
                if key not in seen:
                    seen.add(key)
                    results.append({
                        "summary": summary,
                        "description": description,
                        "event_date": event_date,
                        "is_birthday": False,
                        "days_before": days,
                    })

    return results
