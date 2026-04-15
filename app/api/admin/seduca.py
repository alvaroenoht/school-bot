"""
Admin endpoints for Seduca portal credential management and group discovery.

Flow:
  1. Admin PUT /me/seduca-creds   → validates creds, encrypts, auto-discovers SeducaGroups
  2. Admin GET /seduca/groups     → lists all discovered groups (shared, any admin can see)
  3. Admin POST /classrooms/{id}/seduca-link → binds 1:1
  4. Bot scheduler reads ClassroomSeducaLink to send hourly summaries
"""
import logging
from datetime import datetime, time
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.admin.auth import get_current_admin
from app.api.seduca_client import SeducaClient
from app.db import models
from app.db.database import get_db
from app.utils.crypto import decrypt, encrypt
from app.utils.jid_utils import find_parent_by_jid
from app.utils.seduca_groups import upsert_seduca_groups
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
router = APIRouter(tags=["seduca"])


# ── Helpers ────────────────────────────────────────────────────────────────────

def _get_parent_for_admin(admin: dict, db: Session) -> models.Parent:
    phone = admin["phone"]
    parent = find_parent_by_jid(
        db, f"{phone}@c.us", WahaClient(), require_active=False
    )
    if not parent:
        raise HTTPException(
            status_code=404,
            detail="No parent record for this admin phone. Register via WhatsApp first.",
        )
    return parent


# ── Seduca credentials ─────────────────────────────────────────────────────────

class SeducaCredsRequest(BaseModel):
    username: str
    password: str


@router.put("/me/seduca-creds")
async def save_seduca_creds(
    req: SeducaCredsRequest,
    admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Validate Seduca credentials, encrypt and store them, then auto-discover groups."""
    parent = _get_parent_for_admin(admin, db)

    # Validate before storing
    client = SeducaClient(req.username, req.password)
    if not client.login():
        raise HTTPException(status_code=400, detail="Seduca rechazó las credenciales")

    parent.encrypted_username = encrypt(req.username)
    parent.encrypted_password = encrypt(req.password)
    db.commit()

    # Auto-discover — reuse the already-logged-in session
    students = client.fetch_students()
    groups = upsert_seduca_groups(students, parent, db)

    return {
        "status": "saved",
        "groups": [
            {"id": g.id, "name": g.name, "seduca_group_id": g.seduca_group_id}
            for g in groups
        ],
    }


@router.get("/me/seduca-creds")
async def get_seduca_creds(
    admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    """Return whether admin has Seduca creds set and their username (password never echoed)."""
    parent = _get_parent_for_admin(admin, db)
    has_creds = bool(parent.encrypted_username and parent.encrypted_password)
    username = None
    if has_creds:
        try:
            username = decrypt(parent.encrypted_username)
        except Exception:
            username = None
    return {"has_creds": has_creds, "username": username}


@router.delete("/me/seduca-creds")
async def delete_seduca_creds(
    admin: dict = Depends(get_current_admin),
    db: Session = Depends(get_db),
):
    parent = _get_parent_for_admin(admin, db)
    parent.encrypted_username = None
    parent.encrypted_password = None
    db.commit()
    return {"status": "deleted"}


# ── Seduca groups (shared) ─────────────────────────────────────────────────────

@router.get("/seduca/groups")
async def list_seduca_groups(
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Return all discovered SeducaGroups. Any admin can view and bind any group."""
    groups = db.query(models.SeducaGroup).all()
    result = []
    for g in groups:
        link = db.query(models.ClassroomSeducaLink).filter_by(seduca_group_id=g.id).first()
        bound_cls = (
            db.query(models.Classroom).get(link.classroom_id)
            if link
            else None
        )
        # Derive classroom name from the linked student record
        student_cls = None
        try:
            student = db.query(models.Student).filter_by(id=int(g.seduca_group_id)).first()
            if student and student.classroom_id:
                student_cls = db.query(models.Classroom).get(student.classroom_id)
        except (ValueError, TypeError):
            pass
        classroom_label = (
            (bound_cls.display_name or bound_cls.name) if bound_cls
            else (student_cls.display_name or student_cls.name) if student_cls
            else g.name
        )
        result.append({
            "id": g.id,
            "name": g.name,
            "classroom_name": classroom_label,
            "seduca_group_id": g.seduca_group_id,
            "last_fetched_at": g.last_fetched_at,
            "bound_classroom_id": link.classroom_id if link else None,
            "bound_classroom_name": (bound_cls.display_name or bound_cls.name) if bound_cls else None,
        })
    return result


# ── Classroom ↔ Seduca link ────────────────────────────────────────────────────

class SeducaLinkRequest(BaseModel):
    seduca_group_id: int
    summary_time: str  # "HH:MM"
    summary_day: int = 0  # 0=Monday, 6=Sunday
    answer_dms: bool = True


class SeducaLinkUpdate(BaseModel):
    summary_time: Optional[str] = None
    summary_day: Optional[int] = None
    answer_dms: Optional[bool] = None


def _parse_time(t: str) -> time:
    try:
        h, m = t.split(":")
        return time(int(h), int(m))
    except Exception:
        raise HTTPException(status_code=400, detail="summary_time must be HH:MM")


def _require_classroom_role(admin: dict, classroom_id: int, db: Session):
    if admin["is_super_admin"]:
        return
    role = db.query(models.ClassroomRole).filter_by(
        user_jid=f"{admin['phone']}@c.us", classroom_id=classroom_id
    ).first()
    if not role:
        raise HTTPException(status_code=403, detail="Not authorized for this classroom")


@router.get("/classrooms/{classroom_id}/seduca-link")
async def get_seduca_link(
    classroom_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    link = db.query(models.ClassroomSeducaLink).filter_by(classroom_id=classroom_id).first()
    if not link:
        return {"linked": False}
    return {
        "linked": True,
        "seduca_group": {
            "id": link.seduca_group.id,
            "name": link.seduca_group.name,
            "last_fetched_at": link.seduca_group.last_fetched_at,
        },
        "summary_time": link.summary_time.strftime("%H:%M") if link.summary_time else None,
        "summary_day": link.summary_day if link.summary_day is not None else 0,
        "answer_dms": link.answer_dms,
    }


@router.post("/classrooms/{classroom_id}/seduca-link")
async def create_seduca_link(
    classroom_id: int,
    req: SeducaLinkRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Bind a SeducaGroup to a classroom (1:1). Classroom delegate or super admin only."""
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom:
        raise HTTPException(status_code=404, detail="Classroom not found")

    _require_classroom_role(admin, classroom_id, db)

    # 1:1 check — classroom side
    if db.query(models.ClassroomSeducaLink).filter_by(classroom_id=classroom_id).first():
        raise HTTPException(
            status_code=409,
            detail="Classroom already has a Seduca group linked. Unlink first.",
        )

    # 1:1 check — seduca group side
    seduca_group = db.query(models.SeducaGroup).filter_by(id=req.seduca_group_id).first()
    if not seduca_group:
        raise HTTPException(status_code=404, detail="Seduca group not found")

    sg_link = db.query(models.ClassroomSeducaLink).filter_by(seduca_group_id=req.seduca_group_id).first()
    if sg_link:
        cls = db.query(models.Classroom).get(sg_link.classroom_id)
        raise HTTPException(
            status_code=409,
            detail=f"Seduca group already linked to classroom '{(cls.display_name or cls.name) if cls else sg_link.classroom_id}'",
        )

    try:
        parent = _get_parent_for_admin(admin, db)
        creator_id = parent.id
    except HTTPException:
        creator_id = None

    link = models.ClassroomSeducaLink(
        classroom_id=classroom_id,
        seduca_group_id=req.seduca_group_id,
        summary_time=_parse_time(req.summary_time),
        summary_day=req.summary_day,
        answer_dms=req.answer_dms,
        created_by_id=creator_id,
    )
    db.add(link)
    db.commit()
    return {"status": "linked", "classroom_id": classroom_id, "seduca_group_id": req.seduca_group_id}


@router.patch("/classrooms/{classroom_id}/seduca-link")
async def update_seduca_link(
    classroom_id: int,
    req: SeducaLinkUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    link = db.query(models.ClassroomSeducaLink).filter_by(classroom_id=classroom_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="No Seduca link for this classroom")

    _require_classroom_role(admin, classroom_id, db)

    if req.summary_time is not None:
        link.summary_time = _parse_time(req.summary_time)
    if req.summary_day is not None:
        link.summary_day = req.summary_day
    if req.answer_dms is not None:
        link.answer_dms = req.answer_dms

    db.commit()
    return {"status": "updated"}


@router.delete("/classrooms/{classroom_id}/seduca-link")
async def delete_seduca_link(
    classroom_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    link = db.query(models.ClassroomSeducaLink).filter_by(classroom_id=classroom_id).first()
    if not link:
        raise HTTPException(status_code=404, detail="No Seduca link for this classroom")

    _require_classroom_role(admin, classroom_id, db)

    db.delete(link)
    db.commit()
    return {"status": "unlinked"}
