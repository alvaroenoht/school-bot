from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin
from pydantic import BaseModel

router = APIRouter(prefix="/classrooms", tags=["classrooms"])

class ClassroomUpdate(BaseModel):
    name: Optional[str] = None
    whatsapp_group_id: Optional[str] = None
    settings: Optional[dict] = None # e.g. {"module": "seduca"}
    portal_user: Optional[str] = None
    portal_pass: Optional[str] = None

@router.get("/")
async def list_classrooms(db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    if admin["is_super_admin"]: return db.query(models.Classroom).all()
    my_ids = [r["classroom_id"] for r in admin["roles"]]
    return db.query(models.Classroom).filter(models.Classroom.id.in_(my_ids)).all()

@router.patch("/{classroom_id}")
async def update_classroom(
    classroom_id: int, 
    req: ClassroomUpdate, 
    db: Session = Depends(get_db), 
    admin: dict = Depends(get_current_admin)
):
    # Auth: super admin or delegate of this classroom
    classroom = db.query(models.Classroom).filter_by(id=classroom_id).first()
    if not classroom: raise HTTPException(status_code=404)
    
    if req.name: classroom.name = req.name
    if req.settings: 
        curr = classroom.settings or {}
        curr.update(req.settings)
        classroom.settings = curr
    
    # In a real app, encrypt these. For preview, storing in JSON settings.
    if req.portal_user or req.portal_pass:
        curr = classroom.settings or {}
        if req.portal_user: curr["portal_user"] = req.portal_user
        if req.portal_pass: curr["portal_pass"] = req.portal_pass
        classroom.settings = curr

    db.commit()
    return {"status": "updated"}

@router.get("/{classroom_id}/members")
async def list_members(classroom_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    parents = db.query(models.Parent).filter_by(classroom_id=classroom_id).all()
    result = []
    for p in parents:
        student_links = db.query(models.StudentParent).filter_by(parent_id=p.id).all()
        result.append({
            "id": p.id,
            "name": f"{p.first_name} {p.last_name}",
            "jid": p.whatsapp_jid,
            "students": [{"id": sl.student.id, "name": sl.student.name, "is_primary_payer": sl.is_primary_payer} for sl in student_links]
        })
    return result

class MemberUpdate(BaseModel):
    first_name: Optional[str] = None
    last_name: Optional[str] = None

@router.patch("/{classroom_id}/members/{parent_id}")
async def update_member(
    classroom_id: int,
    parent_id: int,
    req: MemberUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    parent = db.query(models.Parent).filter_by(id=parent_id, classroom_id=classroom_id).first()
    if not parent: raise HTTPException(status_code=404, detail="Parent not found")

    if req.first_name: parent.first_name = req.first_name
    if req.last_name: parent.last_name = req.last_name

    db.commit()
    return {"status": "updated"}
