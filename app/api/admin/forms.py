import secrets
import string
from typing import List, Optional, Dict, Any
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin, require_write_access
from app.whatsapp.client import WahaClient
from app.bot.notifications import notify_form_created
from app.config import get_settings
from pydantic import BaseModel

router = APIRouter(prefix="/forms", tags=["forms"])
wa = WahaClient()


def _generate_form_code(db: Session) -> str:
    """Generate a unique short form code like FORM-XK4M2."""
    alphabet = string.ascii_uppercase + string.digits
    while True:
        suffix = "".join(secrets.choice(alphabet) for _ in range(5))
        code = f"FORM-{suffix}"
        if not db.query(models.Form).filter_by(form_code=code).first():
            return code

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
    description: Optional[str] = None
    audience_classroom_ids: Optional[List[int]] = None

@router.post("")
async def create_form(req: FormCreate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    if not admin["is_super_admin"]:
        my_write_classrooms = [r["classroom_id"] for r in admin["roles"] if r["role"] != "soporte"]
        if any(cid not in my_write_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Not authorized")

    form_code = _generate_form_code(db)
    db_form = models.Form(
        title=req.title, description=req.description, purpose=req.purpose,
        form_code=form_code,
        created_by_jid=admin["phone"] + "@c.us", status="open"
    )
    db.add(db_form)
    db.flush()
    for cid in req.audience_classroom_ids:
        db.add(models.FormAudience(form_id=db_form.id, classroom_id=cid))
    for q in req.questions:
        db.add(models.FormQuestion(form_id=db_form.id, text=q.text, type=q.type, required=q.required, options=q.options, order=q.order))
    db.commit()
    notify_form_created(db_form, db)
    return {"id": db_form.id, "form_code": form_code, "status": "open"}

@router.post("/{form_id}/remind")
async def remind_incomplete(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)

    # 1. Target JIDs — from KnownContactGroup (tracked contacts only)
    target_jids = set()
    for aud in form.audience:
        kcgs = db.query(models.KnownContactGroup).filter_by(classroom_id=aud.classroom_id, active=True).all()
        for kcg in kcgs:
            target_jids.add(kcg.contact_jid)

    # 2. Responded JIDs
    submitted_jids = {s.respondent_jid for s in form.submissions if s.status == 'submitted'}
    unanswered_jids = target_jids - submitted_jids

    # Anti-ban: no unsolicited 1:1 blasts. Post the form code in the group instead.
    if not get_settings().allow_outbound_dms:
        return {
            "sent_count": 0,
            "disabled": True,
            "unanswered_count": len(unanswered_jids),
            "detail": "Los recordatorios 1:1 están desactivados para proteger el número. "
                      "Comparte el código del formulario en el grupo del salón.",
        }

    # 3. Notify
    msg = f"🔔 *Recordatorio: {form.title}*\n\nAún no hemos recibido tu respuesta.\n\nPara completarlo, responde con el código:\n*{form.form_code}*"
    for jid in unanswered_jids:
        wa.send_text(jid, msg)

    return {"sent_count": len(unanswered_jids)}


@router.post("/{form_id}/start-all")
async def start_form_for_all(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    """Directly start the form session for all unanswered audience members."""
    require_write_access(admin)
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)
    if form.status not in ("open", "active"):
        raise HTTPException(status_code=400, detail="Form is not open/active")

    # Anti-ban: this pushes an unsolicited form invite to every pending parent —
    # exactly the mass-DM pattern that gets the number banned. Off by default.
    if not get_settings().allow_outbound_dms:
        raise HTTPException(
            status_code=403,
            detail="El envío directo a todos está desactivado para proteger el número. "
                   "Comparte el código del formulario en el grupo del salón.",
        )

    from app.bot.form_flow import start_from_code

    # Collect unanswered JIDs
    target_jids = set()
    for aud in form.audience:
        kcgs = db.query(models.KnownContactGroup).filter_by(classroom_id=aud.classroom_id, active=True).all()
        for kcg in kcgs:
            target_jids.add(kcg.contact_jid)
    submitted_jids = {s.respondent_jid for s in form.submissions if s.status == 'submitted'}
    # Also exclude anyone with an active form session already
    active_session_jids = {
        s.chat_jid for s in db.query(models.ConversationSession).filter_by(flow="form_respond").all()
        if (s.data or {}).get("form_id") == form.id
    }
    pending_jids = target_jids - submitted_jids - active_session_jids

    started = 0
    skipped = 0
    for jid in pending_jids:
        # Resolve @lid → phone@c.us for sending
        chat_id = jid
        if "@lid" in jid:
            kc = db.query(models.KnownContact).filter_by(jid=jid).first()
            if kc and kc.phone:
                chat_id = kc.phone + "@c.us"
            else:
                skipped += 1
                continue
        await start_from_code(jid, chat_id, form.form_code, db, admin_override=True)
        started += 1

    return {"started": started, "skipped": skipped, "total_audience": len(target_jids), "already_submitted": len(submitted_jids)}

@router.get("")
async def list_forms(
    status: Optional[str] = None,
    include_closed: bool = False,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    if not admin["is_super_admin"]:
        my_ids = [r["classroom_id"] for r in admin["roles"]]
        allowed_form_ids = (
            db.query(models.FormAudience.form_id)
            .filter(models.FormAudience.classroom_id.in_(my_ids))
            .subquery()
        )
        forms = db.query(models.Form).filter(models.Form.id.in_(allowed_form_ids)).all()
    else:
        forms = db.query(models.Form).all()
    if status:
        forms = [f for f in forms if f.status == status]
    elif include_closed:
        forms = [f for f in forms if f.status not in ("archived",)]
    else:
        forms = [f for f in forms if f.status in ("open", "active")]

    result = []
    for f in forms:
        audience_ids = [a.classroom_id for a in db.query(models.FormAudience).filter_by(form_id=f.id).all()]
        if audience_ids:
            kcgs = db.query(models.KnownContactGroup).filter(
                models.KnownContactGroup.classroom_id.in_(audience_ids),
                models.KnownContactGroup.active == True,
            ).all()
            child_names = {(kcg.child_name or "").lower().strip() for kcg in kcgs if kcg.child_name}
            unnamed = sum(1 for kcg in kcgs if not kcg.child_name)
            audience_count = len(child_names) + unnamed
        else:
            audience_count = 0
        submitted = db.query(models.FormSubmission).filter_by(form_id=f.id, status="submitted").count()
        result.append({
            "id": f.id, "title": f.title, "description": f.description, "purpose": f.purpose, "status": f.status,
            "form_code": f.form_code,
            "submitted_count": submitted,
            "audience_count": audience_count,
            "audience_classroom_ids": audience_ids,
            "completion_pct": round(submitted / audience_count * 100) if audience_count else 0,
            "created_at": f.created_at,
        })
    return result

@router.get("/{form_id}/excel")
async def download_excel(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from app.utils.form_report import _build_form_excel
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)
    subs = db.query(models.FormSubmission).filter_by(form_id=form_id, status="submitted").count()
    if not subs:
        raise HTTPException(status_code=400, detail="No submissions to export")
    content = _build_form_excel(form, db)
    filename = f"{form.form_code}_{form.title[:30].replace(' ', '_')}.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/{form_id}/report")
async def get_report(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)
    subs = db.query(models.FormSubmission).filter_by(form_id=form_id).all()
    audience_classroom_ids = [
        a.classroom_id for a in db.query(models.FormAudience).filter_by(form_id=form_id).all()
    ]
    from app.utils.form_report import _get_submission_classroom

    def _resolve_student(s):
        if s.student:
            return s.student.name
        # Fall back to KCG child_name
        if s.respondent_jid:
            kc = db.query(models.KnownContact).filter_by(jid=s.respondent_jid).first()
            if not kc and s.respondent_jid:
                phone = s.respondent_jid.replace("@c.us", "").replace("@lid", "")
                kc = db.query(models.KnownContact).filter_by(phone=phone).first()
            if kc:
                kcg = db.query(models.KnownContactGroup).filter_by(
                    contact_jid=kc.jid, active=True
                ).filter(models.KnownContactGroup.child_name.isnot(None)).first()
                if kcg:
                    return kcg.child_name
        return None

    return {
        "id": form.id, "title": form.title, "status": form.status,
        "multi_classroom": len(audience_classroom_ids) > 1,
        "submissions": [{
            "id": s.id,
            "parent": s.respondent_name,
            "student": _resolve_student(s),
            "classroom": _get_submission_classroom(s, audience_classroom_ids, db),
            "date": s.submitted_at,
            "status": s.status,
        } for s in subs]
    }

@router.get("/{form_id}/submissions/{submission_id}")
async def get_submission(
    form_id: int,
    submission_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    sub = db.query(models.FormSubmission).filter_by(id=submission_id, form_id=form_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    answers = []
    for a in sub.answers:
        q = a.question
        answers.append({
            "question": q.text if q else "?",
            "type": q.type if q else "text",
            "value": a.value,
            "value_json": a.value_json,
        })
    return {
        "id": sub.id,
        "respondent_name": sub.respondent_name,
        "student": sub.student.name if sub.student else None,
        "status": sub.status,
        "submitted_at": sub.submitted_at,
        "answers": answers,
    }


@router.get("/{form_id}/questions")
async def get_questions(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    questions = db.query(models.FormQuestion).filter_by(form_id=form_id).order_by(models.FormQuestion.order).all()
    return [{"id": q.id, "text": q.text, "type": q.type, "required": q.required, "options": q.options, "order": q.order} for q in questions]

@router.delete("/{form_id}/submissions/{submission_id}")
async def delete_submission(
    form_id: int,
    submission_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)
    sub = db.query(models.FormSubmission).filter_by(id=submission_id, form_id=form_id).first()
    if not sub:
        raise HTTPException(status_code=404, detail="Submission not found")
    db.delete(sub)
    db.commit()
    return {"status": "deleted"}


@router.patch("/{form_id}")
async def update_form(form_id: int, req: FormUpdate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)

    if req.status: form.status = req.status
    if req.title: form.title = req.title
    if req.description is not None: form.description = req.description
    if req.audience_classroom_ids is not None:
        db.query(models.FormAudience).filter_by(form_id=form_id).delete()
        for cid in req.audience_classroom_ids:
            db.add(models.FormAudience(form_id=form_id, classroom_id=cid))

    db.commit()
    return {"status": "updated"}

@router.delete("/{form_id}")
async def delete_form(form_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    form = db.query(models.Form).filter_by(id=form_id).first()
    if not form: raise HTTPException(status_code=404)

    # Only delete if no submissions exist
    submission_count = db.query(models.FormSubmission).filter_by(form_id=form_id).count()
    if submission_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete form with existing submissions")

    db.delete(form)
    db.commit()
    return {"status": "deleted"}
