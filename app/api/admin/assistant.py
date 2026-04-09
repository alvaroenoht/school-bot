import json
import logging
from typing import Optional
import openai
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin
from app.config import get_settings
from pydantic import BaseModel

router = APIRouter(prefix="/assistant", tags=["assistant"])
logger = logging.getLogger(__name__)

class Question(BaseModel):
    text: str
    classroom_id: Optional[int] = None

@router.post("/ask")
async def ask_assistant(
    req: Question,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """Context-aware AI assistant for admins/delegates."""
    settings = get_settings()
    client = openai.OpenAI(api_key=settings.openai_api_key)

    # 1. Gather Context
    context = {
        "admin_phone": admin["phone"],
        "is_super_admin": admin["is_super_admin"],
        "active_fundraisers": [],
        "active_forms": []
    }

    # Filter by accessible classrooms
    my_classrooms = [r["classroom_id"] for r in admin["roles"]]
    if req.classroom_id:
        if not admin["is_super_admin"] and req.classroom_id not in my_classrooms:
            raise HTTPException(status_code=403, detail="Access denied to this classroom.")
        target_ids = [req.classroom_id]
    else:
        target_ids = my_classrooms if not admin["is_super_admin"] else None

    # Fetch Fundraisers
    fund_query = db.query(models.Fundraiser).filter_by(status="active")
    if target_ids:
        # Simple overlap check for JSON list
        fund_query = fund_query.filter(models.Fundraiser.audience_classroom_ids.contains(target_ids))
    
    for f in fund_query.all():
        confirmed = db.query(models.Payment).filter_by(fundraiser_id=f.id, status="confirmed").count()
        pending = db.query(models.Payment).filter_by(fundraiser_id=f.id, status="pending").count()
        context["active_fundraisers"].append({
            "name": f.name,
            "confirmed_payments": confirmed,
            "pending_payments": pending,
            "target_amount": f.fixed_amount
        })

    # Fetch Forms
    form_query = db.query(models.Form).filter_by(status="open")
    if target_ids:
        form_query = form_query.join(models.FormAudience).filter(models.FormAudience.classroom_id.in_(target_ids))
    
    for f in form_query.all():
        subs = db.query(models.FormSubmission).filter_by(form_id=f.id, status="submitted").count()
        context["active_forms"].append({
            "title": f.title,
            "submissions": subs
        })

    # 2. Call OpenAI
    system_prompt = f"""
    Eres un asistente para Administradores y Delegados de salones escolares.
    Responde preguntas sobre el estado de las actividades basándote en el CONTEXTO proporcionado.
    Sé conciso y profesional.
    Responde en el mismo idioma que la pregunta (Bilingual EN/ES support).
    
    CONTEXTO:
    {json.dumps(context, indent=2)}
    """

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": req.text},
            ],
            temperature=0.5,
            timeout=30,
        )
        return {"answer": response.choices[0].message.content}
    except Exception as e:
        logger.error(f"Assistant error: {e}")
        raise HTTPException(status_code=500, detail="AI Assistant failed to respond.")
