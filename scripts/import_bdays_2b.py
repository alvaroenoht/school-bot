"""
One-off: import birthdays for classroom 2B from the legacy Google Calendar iCal feed.

Steps:
1. Fetch iCal URL
2. Extract "Cumpleaños de <name>" events with their start dates
3. For each name, fuzzy-match against KnownContactGroup.child_name where classroom_id=2
4. Upsert a Student row (name from KCG, classroom_id=2, birth_date=start.date())

Safe to re-run (idempotent update).
"""
import sys
import unicodedata
from datetime import date
from difflib import SequenceMatcher

import requests
from icalendar import Calendar
import recurring_ical_events

from app.db.database import SessionLocal
from app.db import models

ICAL_URL = (
    "https://calendar.google.com/calendar/ical/"
    "6c3f9dc978690a2c16bf5562f332acf021edd846c575bc3911941843c6f6ab12"
    "%40group.calendar.google.com/private-8a2d4ea1c850bd99ef7fae075d65edf0/basic.ics"
)
CLASSROOM_ID = 2


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFD", s or "")
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return s.lower().strip()


def _score(a: str, b: str) -> float:
    return SequenceMatcher(None, _norm(a), _norm(b)).ratio()


def _tokens(s: str) -> set[str]:
    return {t for t in _norm(s).split() if len(t) >= 3}


def _best_match(name: str, candidates: list[str]) -> tuple[str | None, float]:
    ical_toks = _tokens(name)
    # 1) Prefer candidate whose tokens are a subset of ical tokens (KCG short → iCal full)
    best_subset, best_overlap = None, 0
    for c in candidates:
        ctoks = _tokens(c)
        if ctoks and ctoks.issubset(ical_toks) and len(ctoks) > best_overlap:
            best_subset, best_overlap = c, len(ctoks)
    if best_subset and best_overlap >= 2:
        return best_subset, 0.99
    # 2) Fallback: highest overlap ratio
    best, best_score = None, 0.0
    for c in candidates:
        ctoks = _tokens(c)
        if not ctoks:
            continue
        overlap = len(ctoks & ical_toks)
        ratio = overlap / max(len(ctoks), len(ical_toks))
        blended = max(ratio, _score(name, c))
        if blended > best_score:
            best, best_score = c, blended
    return best, best_score


def main():
    resp = requests.get(ICAL_URL, timeout=30)
    resp.raise_for_status()
    cal = Calendar.from_ical(resp.text)

    # Expand the calendar over the whole year + next year window
    start = date(date.today().year, 1, 1)
    end = date(date.today().year + 1, 12, 31)
    events = recurring_ical_events.of(cal).between(start, end)

    bdays: dict[str, date] = {}
    for ev in events:
        summary = str(ev.get("SUMMARY") or "")
        if "Cumpleaños" not in summary and "cumpleaños" not in summary:
            continue
        # Extract name after "Cumpleaños de "
        name = summary
        for prefix in ("Cumpleaños de ", "cumpleaños de "):
            if prefix in summary:
                name = summary.split(prefix, 1)[1].strip()
                break
        dtstart = ev.get("DTSTART").dt
        if hasattr(dtstart, "date"):
            dtstart = dtstart.date()
        # Only keep the earliest occurrence (birth date has no year info in practice)
        if name not in bdays or dtstart < bdays[name]:
            bdays[name] = dtstart

    print(f"Parsed {len(bdays)} birthdays from iCal.")

    db = SessionLocal()
    try:
        kcg_rows = (
            db.query(models.KnownContactGroup)
            .filter_by(classroom_id=CLASSROOM_ID, active=True)
            .all()
        )
        kcg_names = sorted({(r.child_name or "").strip() for r in kcg_rows if r.child_name})
        print(f"{len(kcg_names)} KCG child names in classroom {CLASSROOM_ID}.")

        matched = 0
        skipped = []
        for ical_name, bdate in bdays.items():
            best, score = _best_match(ical_name, kcg_names)
            if score < 0.75:
                skipped.append((ical_name, best, score))
                continue

            # Use the KCG-canonical name (preserves accents + the school's spelling)
            student = (
                db.query(models.Student)
                .filter(
                    models.Student.classroom_id == CLASSROOM_ID,
                    models.Student.name == best,
                )
                .first()
            )
            if student:
                if student.birth_date == bdate:
                    print(f"[=] {best} already {bdate}")
                    continue
                student.birth_date = bdate
                action = "updated"
            else:
                student = models.Student(
                    name=best,
                    grade="2B",
                    classroom_id=CLASSROOM_ID,
                    birth_date=bdate,
                )
                db.add(student)
                action = "created"
            matched += 1
            print(f"[{action}] {best} -> {bdate}  (ical: {ical_name!r}, score={score:.2f})")

        db.commit()
        print(f"\n✔ Matched & written: {matched}")
        if skipped:
            print(f"\n✖ Skipped {len(skipped)} (score<0.75):")
            for ical_name, best, score in skipped:
                print(f"   - iCal={ical_name!r}  closest={best!r}  score={score:.2f}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
