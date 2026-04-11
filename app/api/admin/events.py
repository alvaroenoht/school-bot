from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin
from pydantic import BaseModel

router = APIRouter(prefix="/events", tags=["events"])

class EventCreate(BaseModel):
    title: str
    description: Optional[str] = None
    date: datetime
    location: Optional[str] = None
    audience_classroom_ids: List[int] = [] # empty = global if is_global is handled

@router.post("")
async def create_event(
    req: EventCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    if not admin["is_super_admin"]:
        # Delegates can only create events for their classrooms
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        if any(cid not in my_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Cannot create event for classrooms you don't manage.")

    db_event = models.Event(
        title=req.title,
        description=req.description,
        date=req.date,
        location=req.location,
        is_global=len(req.audience_classroom_ids) == 0 and admin["is_super_admin"]
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
    admin: dict = Depends(get_current_admin)
):
    if admin["is_super_admin"]:
        return db.query(models.Event).all()

    my_classrooms = [r["classroom_id"] for r in admin["roles"]]
    return db.query(models.Event).join(models.EventAudience).filter(
        models.EventAudience.classroom_id.in_(my_classrooms)
    ).distinct().all()

@router.get("/{event_id}")
async def get_event(
    event_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    event = db.query(models.Event).filter_by(id=event_id).first()
    if not event: raise HTTPException(status_code=404)
    return event

@router.patch("/{event_id}")
async def update_event(
    event_id: int,
    req: EventCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    event = db.query(models.Event).filter_by(id=event_id).first()
    if not event: raise HTTPException(status_code=404)

    event.title = req.title
    if req.description: event.description = req.description
    event.date = req.date
    if req.location: event.location = req.location
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
    admin: dict = Depends(get_current_admin)
):
    event = db.query(models.Event).filter_by(id=event_id).first()
    if not event: raise HTTPException(status_code=404)

    db.delete(event)
    db.commit()
    return {"status": "deleted"}
