import re
import unicodedata
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin
from app.whatsapp.client import WahaClient
from pydantic import BaseModel

router = APIRouter(prefix="/fundraisers", tags=["fundraisers"])
wa = WahaClient()

class ProductSchema(BaseModel):
    name: str
    price: str

class FundraiserCreate(BaseModel):
    name: str
    friendly_name: Optional[str] = None
    account_number: str
    type: str  # fixed | variable
    fixed_amount: Optional[str] = None
    audience_classroom_ids: List[int]
    products: Optional[List[ProductSchema]] = None

class FundraiserUpdate(BaseModel):
    status: Optional[str] = None  # active | closed | archived
    name: Optional[str] = None
    friendly_name: Optional[str] = None
    audience_classroom_ids: Optional[List[int]] = None


def _generate_code(name: str, db: Session) -> str:
    """Slugify name → uppercase code, ensure uniqueness."""
    nfkd = unicodedata.normalize("NFKD", name)
    ascii_str = "".join(c for c in nfkd if not unicodedata.combining(c))
    base = re.sub(r"[^A-Z0-9]", "", ascii_str.upper())[:10] or "FUND"
    code = base
    suffix = 2
    while db.query(models.Fundraiser).filter_by(code=code).first():
        code = f"{base[:8]}{suffix}"
        suffix += 1
    return code


def _fund_stats(fund: models.Fundraiser, db: Session) -> dict:
    confirmed = [p for p in fund.payments if p.status == "confirmed"]
    total = sum(float(p.amount or 0) for p in confirmed)
    paid_count = len(confirmed)
    audience_ids = fund.audience_classroom_ids or []
    audience_count = (
        db.query(models.Parent)
        .filter(models.Parent.classroom_id.in_(audience_ids), models.Parent.is_active == True)
        .count()
        if audience_ids else 0
    )
    return {
        "id": fund.id,
        "name": fund.name,
        "friendly_name": fund.friendly_name,
        "code": fund.code,
        "type": fund.type,
        "fixed_amount": fund.fixed_amount,
        "status": fund.status,
        "total_collected": round(total, 2),
        "paid_count": paid_count,
        "audience_count": audience_count,
        "completion_pct": round(paid_count / audience_count * 100) if audience_count else 0,
        "created_at": fund.created_at,
        "closed_at": fund.closed_at,
    }


@router.post("")
async def create_fundraiser(req: FundraiserCreate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    if not admin["is_super_admin"]:
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        if any(cid not in my_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Not authorized")

    code = _generate_code(req.name, db)
    db_fund = models.Fundraiser(
        name=req.name,
        friendly_name=req.friendly_name or req.name,
        code=code,
        account_number=req.account_number,
        type=req.type,
        fixed_amount=req.fixed_amount,
        audience_classroom_ids=req.audience_classroom_ids,
        created_by_jid=admin["phone"] + "@c.us",
        status="active",
    )
    db.add(db_fund)
    db.flush()
    if req.type == "variable" and req.products:
        for idx, p in enumerate(req.products):
            db.add(models.FundraiserProduct(fundraiser_id=db_fund.id, name=p.name, price=p.price, sort_order=idx))
    db.commit()
    return {"id": db_fund.id, "code": code, "status": "active"}


@router.post("/{fundraiser_id}/remind")
async def remind_unpaid(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    target_jids = set()
    for cid in (fund.audience_classroom_ids or []):
        for p in db.query(models.Parent).filter_by(classroom_id=cid).all():
            target_jids.add(p.whatsapp_jid)

    paid_jids = {p.payer_jid for p in fund.payments if p.status in ("confirmed", "pending")}
    unpaid_jids = target_jids - paid_jids

    msg = f"🔔 *Recordatorio: {fund.name}*\n\nAún no recibimos tu pago. Si ya lo hiciste, envía tu comprobante escribiendo *pagar*."
    for jid in unpaid_jids:
        wa.send_text(jid, msg)

    return {"sent_count": len(unpaid_jids)}


@router.get("")
async def list_fundraisers(
    status: Optional[str] = None,  # "active" | "closed" | "archived" | None = all
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    q = db.query(models.Fundraiser)
    if not admin["is_super_admin"]:
        my_ids = [r["classroom_id"] for r in admin["roles"]]
        # Filter by audience overlap (JSON contains check not trivial in SQLite/PG — filter in Python)
        all_funds = q.all()
        funds = [f for f in all_funds if any(cid in (f.audience_classroom_ids or []) for cid in my_ids)]
    else:
        funds = q.all()

    if status:
        funds = [f for f in funds if f.status == status]
    else:
        # Default: exclude archived
        funds = [f for f in funds if f.status != "archived"]

    return [_fund_stats(f, db) for f in funds]


@router.get("/{fundraiser_id}/report")
async def get_report(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)
    payments = db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id).all()
    return {
        "id": fund.id, "name": fund.name, "friendly_name": fund.friendly_name,
        "code": fund.code, "status": fund.status, "type": fund.type,
        "payments": [
            {"id": p.id, "parent": p.payer_name, "child": p.child_name,
             "amount": p.amount, "status": p.status, "date": p.submitted_at}
            for p in payments
        ],
    }


@router.patch("/{fundraiser_id}")
async def update_fundraiser(fundraiser_id: int, req: FundraiserUpdate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    if req.status:
        fund.status = req.status
        if req.status == "closed": fund.closed_at = datetime.utcnow()
    if req.name: fund.name = req.name
    if req.friendly_name: fund.friendly_name = req.friendly_name
    if req.audience_classroom_ids is not None:
        fund.audience_classroom_ids = req.audience_classroom_ids

    db.commit()
    return {"status": "updated"}


@router.delete("/{fundraiser_id}")
async def delete_fundraiser(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    payment_count = db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id).count()
    if payment_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete fundraiser with existing payments")

    db.delete(fund)
    db.commit()
    return {"status": "deleted"}
