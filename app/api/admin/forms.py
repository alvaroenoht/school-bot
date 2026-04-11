from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin
from app.whatsapp.client import WahaClient
from pydantic import BaseModel

router = APIRouter(prefix="/forms", tags=["forms"])
wa = WahaClient()

class QuestionSchema(BaseModel):
    text: str
    type: str 
    required: bool = True
    options: Optional[List[str]] = None
    order: int

class FormCreate(BaseModel):
    title: str
    description: Optional[str] = None
    purpose: str
    audience_classroom_ids: List[int]
    questions: List[QuestionSchema]

class FormUpdate(BaseModel):
    status: Optional[str] = None
    title: Optional[str] = None
    audience_classroom_ids: Optional[List[int]] = None

@router.post("")
async def create_form(req: FormCreate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    if not admin["is_super_admin"]:
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        if any(cid not in my_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Not authorized")

    db_form = models.Form(
        title=req.title, description=req.description, purpose=req.purpose,
        created_by_jid=admin["phone"] + "@c.us", status="open"
    )
    db.add(db_form)
    db.flush()
    for cid in req.audience_classroom_ids:
        db.add(models.FormAudience(form_id=db_form.id, classroom_id=cid))
    for q in req.questions:
        db.add(models.FormQuestion(form_id=db_form.id, text=q.text, type=q.type, required=q.required, options=q.options, order=q.order))
    db.commit()
    return {"id": db_form.id, "status": "open"}

@router.post("/{form_id}/remind")
async def remind_incomplete(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)
    
    # 1. Target JIDs
    target_jids = set()
    for aud in form.audience:
        parents = db.query(models.Parent).filter_by(classroom_id=aud.classroom_id).all()
        for p in parents: target_jids.add(p.whatsapp_jid)
        
    # 2. Responded JIDs
    submitted_jids = {s.respondent_jid for s in form.submissions if s.status == 'submitted'}
    unanswered_jids = target_jids - submitted_jids
    
    # 3. Notify
    msg = f"🔔 *Recordatorio: {form.title}*\n\nAún no hemos recibido tu respuesta. Por favor complétalo respondiendo *formulario* a este chat."
    for jid in unanswered_jids:
        wa.send_text(jid, msg)
        
    return {"sent_count": len(unanswered_jids)}

@router.get("")
async def list_forms(
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    forms = db.query(models.Form).all()
    if status:
        forms = [f for f in forms if f.status == status]
    else:
        forms = [f for f in forms if f.status != "archived"]

    result = []
    for f in forms:
        audience_ids = [a.classroom_id for a in db.query(models.FormAudience).filter_by(form_id=f.id).all()]
        audience_count = (
            db.query(models.Parent)
            .filter(models.Parent.classroom_id.in_(audience_ids), models.Parent.is_active == True)
            .count() if audience_ids else 0
        )
        submitted = db.query(models.FormSubmission).filter_by(form_id=f.id, status="submitted").count()
        result.append({
            "id": f.id, "title": f.title, "purpose": f.purpose, "status": f.status,
            "submitted_count": submitted,
            "audience_count": audience_count,
            "completion_pct": round(submitted / audience_count * 100) if audience_count else 0,
            "created_at": f.created_at,
        })
    return result

@router.get("/{form_id}/report")
async def get_report(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)
    subs = db.query(models.FormSubmission).filter_by(form_id=form_id).all()
    return {
        "id": form.id, "title": form.title, "status": form.status,
        "submissions": [{"id": s.id, "parent": s.respondent_name, "student": s.student.name if s.student else "N/A", "date": s.submitted_at, "status": s.status} for s in subs]
    }

@router.get("/{form_id}/questions")
async def get_questions(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    questions = db.query(models.FormQuestion).filter_by(form_id=form_id).order_by(models.FormQuestion.order).all()
    return [{"id": q.id, "text": q.text, "type": q.type, "required": q.required, "options": q.options, "order": q.order} for q in questions]

@router.patch("/{form_id}")
async def update_form(form_id: int, req: FormUpdate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)

    if req.status: form.status = req.status
    if req.title: form.title = req.title
    if req.audience_classroom_ids is not None:
        db.query(models.FormAudience).filter_by(form_id=form_id).delete()
        for cid in req.audience_classroom_ids:
            db.add(models.FormAudience(form_id=form_id, classroom_id=cid))

    db.commit()
    return {"status": "updated"}

@router.delete("/{form_id}")
async def delete_form(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)

    # Only delete if no submissions exist
    submission_count = db.query(models.FormSubmission).filter_by(form_id=form_id).count()
    if submission_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete form with existing submissions")

    db.delete(form)
    db.commit()
    return {"status": "deleted"}
