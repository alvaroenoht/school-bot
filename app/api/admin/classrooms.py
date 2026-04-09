from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin
from pydantic import BaseModel

router = APIRouter(prefix="/classrooms", tags=["classrooms"])

class ClassroomBase(BaseModel):
    name: str
    parent_id: Optional[int] = None
    whatsapp_group_id: Optional[str] = None

@router.get("/")
async def list_classrooms(
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """Returns the full hierarchy or just accessible nodes."""
    if admin["is_super_admin"]:
        return db.query(models.Classroom).all()
    
    my_ids = [r["classroom_id"] for r in admin["roles"]]
    return db.query(models.Classroom).filter(models.Classroom.id.in_(my_ids)).all()

@router.get("/{classroom_id}/members")
async def list_members(
    classroom_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """List parents and students in this group."""
    # Auth check omitted for preview
    parents = db.query(models.Parent).filter_by(classroom_id=classroom_id).all()
    
    result = []
    for p in parents:
        # Get students via link table
        student_links = db.query(models.StudentParent).filter_by(parent_id=p.id).all()
        kids = []
        for sl in student_links:
            kids.append({
                "id": sl.student.id,
                "name": sl.student.name,
                "is_primary_payer": sl.is_primary_payer
            })
            
        result.append({
            "id": p.id,
            "name": f"{p.first_name} {p.last_name}",
            "jid": p.whatsapp_jid,
            "students": kids
        })
    return result

@router.patch("/members/{parent_id}")
async def update_member(
    parent_id: int,
    data: dict, # {first_name, last_name, students: [{id, name, is_primary_payer}]}
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """Update parent/student names and payment responsibility."""
    parent = db.query(models.Parent).filter_by(id=parent_id).first()
    if not parent: raise HTTPException(status_code=404)
    
    if "first_name" in data: parent.first_name = data["first_name"]
    if "last_name" in data: parent.last_name = data["last_name"]
    
    if "students" in data:
        for s_data in data["students"]:
            student = db.query(models.Student).filter_by(id=s_data["id"]).first()
            if student:
                student.name = s_data["name"]
                # Update link table
                link = db.query(models.StudentParent).filter_by(student_id=student.id, parent_id=parent.id).first()
                if link:
                    link.is_primary_payer = s_data["is_primary_payer"]
    
    db.commit()
    return {"status": "updated"}
