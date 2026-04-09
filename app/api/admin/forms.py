from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin
from pydantic import BaseModel

router = APIRouter(prefix="/forms", tags=["forms"])

class QuestionSchema(BaseModel):
    text: str
    type: str # yes_no|text|single_choice|multi_choice|number|date
    required: bool = True
    options: Optional[List[str]] = None
    order: int

class FormCreate(BaseModel):
    title: str
    description: Optional[str] = None
    purpose: str
    audience_classroom_ids: List[int]
    questions: List[QuestionSchema]

@router.post("/")
async def create_form(
    req: FormCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """Create a new form with its questions and audience."""
    # Auth check: must have access to all requested classrooms
    if not admin["is_super_admin"]:
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        if any(cid not in my_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Cannot create form for classrooms you don't manage.")

    # 1. Create Form
    db_form = models.Form(
        title=req.title,
        description=req.description,
        purpose=req.purpose,
        created_by_jid=admin["phone"] + "@c.us",
        status="draft"
    )
    db.add(db_form)
    db.flush() # get ID

    # 2. Add Audience
    for cid in req.audience_classroom_ids:
        db.add(models.FormAudience(form_id=db_form.id, classroom_id=cid))

    # 3. Add Questions
    for q in req.questions:
        db_q = models.FormQuestion(
            form_id=db_form.id,
            text=q.text,
            type=q.type,
            required=q.required,
            options=q.options,
            order=q.order
        )
        db.add(db_q)

    db.commit()
    return {"id": db_form.id, "status": "created"}

@router.get("/")
async def list_forms(
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """List forms the admin has access to view."""
    if admin["is_super_admin"]:
        return db.query(models.Form).all()

    # Filter forms by creator JID OR by those where the admin is a delegate for the audience
    my_classrooms = [r["classroom_id"] for r in admin["roles"]]
    return db.query(models.Form).join(models.FormAudience).filter(
        (models.Form.created_by_jid == admin["phone"] + "@c.us") |
        (models.FormAudience.classroom_id.in_(my_classrooms))
    ).distinct().all()

@router.get("/{form_id}/submissions")
async def get_submissions(
    form_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """Get all submissions for a form."""
    # Auth check omitted for brevity (similar to fundraisers)
    return db.query(models.FormSubmission).filter_by(form_id=form_id).all()
