from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin, require_write_access
from pydantic import BaseModel, field_validator

router = APIRouter(prefix="/events", tags=["events"])

ALLOWED_TYPES = {"holiday", "exam", "general"}  # birthday auto-managed via Student.birth_date


class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    date: datetime
    location: Optional[str] = None
    type: str = "general"
    audience_classroom_ids: List[int] = []  # empty list + super_admin = global

    @field_validator("type")
    @classmethod
    def _valid_type(cls, v: str) -> str:
        if v not in ALLOWED_TYPES:
            raise ValueError(f"type must be one of {sorted(ALLOWED_TYPES)}")
        return v


def _serialize_event(ev: models.Event) -> dict:
    return {
        "id": ev.id,
        "title": ev.title,
        "description": ev.description,
        "date": ev.date,
        "location": ev.location,
        "is_global": ev.is_global,
        "type": ev.type,
        "student_id": ev.student_id,
        "student_name": ev.student.name if ev.student else None,
        "audience_classroom_ids": [a.classroom_id for a in ev.audience],
        "created_at": ev.created_at,
    }


@router.post("")
async def create_event(
    req: EventCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)
    if not admin["is_super_admin"]:
        my_write_classrooms = [r["classroom_id"] for r in admin["roles"] if r["role"] != "soporte"]
        if any(cid not in my_write_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Cannot create event for classrooms you don't manage.")
        if not req.audience_classroom_ids:
            raise HTTPException(status_code=403, detail="Only super admins can create global events.")

    db_event = models.Event(
        title=req.title,
        description=req.description,
        date=req.date,
        location=req.location,
        type=req.type,
        is_global=len(req.audience_classroom_ids) == 0 and admin["is_super_admin"],
    )
    db.add(db_event)
    db.flush()

    for cid in req.audience_classroom_ids:
        db.add(models.EventAudience(event_id=db_event.id, classroom_id=cid))

    db.commit()
    return {"id": db_event.id, "status": "created"}


@router.get("")
async def list_events(
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    if admin["is_super_admin"]:
        events = db.query(models.Event).order_by(models.Event.date).all()
    else:
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        events = (
            db.query(models.Event)
            .outerjoin(models.EventAudience)
            .filter(
                (models.Event.is_global == True)  # noqa: E712
                | (models.EventAudience.classroom_id.in_(my_classrooms))
            )
            .distinct()
            .order_by(models.Event.date)
            .all()
        )
    return [_serialize_event(e) for e in events]


@router.get("/{event_id}")
async def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    event = db.query(models.Event).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404)
    return _serialize_event(event)


@router.patch("/{event_id}")
async def update_event(
    event_id: int,
    req: EventCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)
    event = db.query(models.Event).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404)
    if event.type == "birthday":
        raise HTTPException(status_code=400, detail="Birthday events are auto-managed — edit Student.birth_date instead.")

    event.title = req.title
    event.description = req.description
    event.date = req.date
    event.location = req.location
    event.type = req.type
    event.is_global = len(req.audience_classroom_ids) == 0 and admin["is_super_admin"]

    db.query(models.EventAudience).filter_by(event_id=event_id).delete()
    for cid in req.audience_classroom_ids:
        db.add(models.EventAudience(event_id=event_id, classroom_id=cid))

    db.commit()
    return {"status": "updated"}


@router.delete("/{event_id}")
async def delete_event(
    event_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)
    event = db.query(models.Event).filter_by(id=event_id).first()
    if not event:
        raise HTTPException(status_code=404)

    db.delete(event)
    db.commit()
    return {"status": "deleted"}
