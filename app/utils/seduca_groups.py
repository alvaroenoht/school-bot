"""
Shared SeducaGroup upsert used by every Parent creation path (WhatsApp
registration, admin panel credential save, etc.) so both flows produce the
same discoverable groups.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.orm import Session

from app.db import models


def upsert_seduca_groups(
    students: list[dict],
    parent: models.Parent,
    db: Session,
) -> list[models.SeducaGroup]:
    """Upsert SeducaGroup rows from a list of Seduca students (children).

    Deduped by seduca_group_id — a second admin with the same child hits the
    existing row. Commits at the end.
    """
    now = datetime.utcnow()
    result: list[models.SeducaGroup] = []
    for s in students:
        sid = str(s["id"])
        name = f"{s['name']} - {s.get('grade', '')}".strip(" -")
        existing = db.query(models.SeducaGroup).filter_by(seduca_group_id=sid).first()
        if existing:
            existing.name = name
            existing.last_fetched_at = now
            result.append(existing)
        else:
            sg = models.SeducaGroup(
                seduca_group_id=sid,
                name=name,
                discovered_by_id=parent.id,
                last_fetched_at=now,
            )
            db.add(sg)
            db.flush()
            result.append(sg)
    db.commit()
    return result
