from typing import List, Dict, Any, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, Query
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
    account_number: str
    type: str # fixed | variable
    fixed_amount: Optional[str] = None
    audience_classroom_ids: List[int]
    products: Optional[List[ProductSchema]] = None

class FundraiserUpdate(BaseModel):
    status: Optional[str] = None # active | closed
    name: Optional[str] = None
    audience_classroom_ids: Optional[List[int]] = None

@router.post("/")
async def create_fundraiser(req: FundraiserCreate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    if not admin["is_super_admin"]:
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        if any(cid not in my_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Not authorized")

    db_fund = models.Fundraiser(
        name=req.name, account_number=req.account_number, type=req.type,
        fixed_amount=req.fixed_amount, audience_classroom_ids=req.audience_classroom_ids,
        created_by_jid=admin["phone"] + "@c.us", status="active"
    )
    db.add(db_fund)
    db.flush()
    if req.type == "variable" and req.products:
        for idx, p in enumerate(req.products):
            db.add(models.FundraiserProduct(fundraiser_id=db_fund.id, name=p.name, price=p.price, sort_order=idx))
    db.commit()
    return {"id": db_fund.id, "status": "active"}

@router.post("/{fundraiser_id}/remind")
async def remind_unpaid(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)
    
    # 1. Get all targeted JIDs
    target_jids = set()
    for cid in (fund.audience_classroom_ids or []):
        parents = db.query(models.Parent).filter_by(classroom_id=cid).all()
        for p in parents: target_jids.add(p.whatsapp_jid)
    
    # 2. Get JIDs who already paid
    paid_jids = {p.payer_jid for p in fund.payments if p.status in ('confirmed', 'pending')}
    unpaid_jids = target_jids - paid_jids
    
    # 3. Send WhatsApp
    msg = f"🔔 *Recordatorio: {fund.name}*\n\nAún no recibimos tu pago. Si ya lo hiciste, envía tu comprobante escribiendo *pagar*."
    for jid in unpaid_jids:
        wa.send_text(jid, msg)
        
    return {"sent_count": len(unpaid_jids)}

@router.get("/")
async def list_fundraisers(db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    return db.query(models.Fundraiser).all()

@router.get("/{fundraiser_id}/report")
async def get_report(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)
    payments = db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id).all()
    return {
        "id": fund.id, "name": fund.name, "status": fund.status, "type": fund.type,
        "payments": [{"id": p.id, "parent": p.payer_name, "child": p.child_name, "amount": p.amount, "status": p.status, "date": p.submitted_at} for p in payments]
    }

@router.patch("/{fundraiser_id}")
async def update_fundraiser(fundraiser_id: int, req: FundraiserUpdate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    if req.status:
        fund.status = req.status
        if req.status == "closed": fund.closed_at = datetime.utcnow()
    if req.name: fund.name = req.name
    if req.audience_classroom_ids is not None: fund.audience_classroom_ids = req.audience_classroom_ids

    db.commit()
    return {"status": "updated"}

@router.delete("/{fundraiser_id}")
async def delete_fundraiser(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    # Only delete if no payments exist
    payment_count = db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id).count()
    if payment_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete fundraiser with existing payments")

    db.delete(fund)
    db.commit()
    return {"status": "deleted"}
