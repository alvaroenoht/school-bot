from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.admin.auth import get_current_admin, require_write_access
from app.db import models
from app.db.database import get_db

router = APIRouter(prefix="/students", tags=["students"])


class StudentUpdate(BaseModel):
    name: Optional[str] = None
    grade: Optional[str] = None
    classroom_id: Optional[int] = None
    birth_date: Optional[date] = None


def _serialize(s: models.Student) -> dict:
    return {
        "id": s.id,
        "name": s.name,
        "grade": s.grade,
        "classroom_id": s.classroom_id,
        "birth_date": s.birth_date.isoformat() if s.birth_date else None,
    }


@router.get("")
async def list_students(
    classroom_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    q = db.query(models.Student)
    if not admin["is_super_admin"]:
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        q = q.filter(models.Student.classroom_id.in_(my_classrooms))
    if classroom_id is not None:
        q = q.filter(models.Student.classroom_id == classroom_id)
    return [_serialize(s) for s in q.order_by(models.Student.name).all()]


@router.patch("/{student_id}")
async def update_student(
    student_id: int,
    req: StudentUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)
    s = db.query(models.Student).filter_by(id=student_id).first()
    if not s:
        raise HTTPException(status_code=404)

    # Authorization: non-super-admin must have write access to current AND target classroom
    if not admin["is_super_admin"]:
        my_write = {r["classroom_id"] for r in admin["roles"] if r["role"] != "soporte"}
        if s.classroom_id not in my_write:
            raise HTTPException(status_code=403, detail="Not authorized for this student")
        if req.classroom_id is not None and req.classroom_id not in my_write:
            raise HTTPException(status_code=403, detail="Cannot move student to that classroom")

    if req.name is not None:
        s.name = req.name
    if req.grade is not None:
        s.grade = req.grade
    if req.classroom_id is not None:
        s.classroom_id = req.classroom_id
    if req.birth_date is not None:
        s.birth_date = req.birth_date

    db.commit()
    return _serialize(s)
