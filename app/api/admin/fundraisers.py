from typing import List, Dict, Any, Optional
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

@router.post("/")
async def create_fundraiser(
    req: FundraiserCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    """Create a new fundraiser activity."""
    # Auth check: must manage these classrooms
    if not admin["is_super_admin"]:
        my_classrooms = [r["classroom_id"] for r in admin["roles"]]
        if any(cid not in my_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Cannot target classrooms you don't manage.")

    # 1. Create Fundraiser
    db_fund = models.Fundraiser(
        name=req.name,
        account_number=req.account_number,
        type=req.type,
        fixed_amount=req.fixed_amount,
        audience_classroom_ids=req.audience_classroom_ids,
        created_by_jid=admin["phone"] + "@c.us",
        status="active"
    )
    db.add(db_fund)
    db.flush()

    # 2. Add Products if variable
    if req.type == "variable" and req.products:
        for idx, p in enumerate(req.products):
            db_p = models.FundraiserProduct(
                fundraiser_id=db_fund.id,
                name=p.name,
                price=p.price,
                sort_order=idx
            )
            db.add(db_p)

    db.commit()
    return {"id": db_fund.id, "status": "active"}

@router.get("/")
async def list_fundraisers(
    classroom_id: Optional[int] = None,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    query = db.query(models.Fundraiser)
    if admin["is_super_admin"]:
        if classroom_id:
            query = query.filter(models.Fundraiser.audience_classroom_ids.contains([classroom_id]))
        return query.all()

    my_classrooms = [r["classroom_id"] for r in admin["roles"]]
    # Logic to filter by overlapping classroom IDs in JSON column
    # For now, return all for simplicity in preview, but filter in production
    return query.all()

@router.get("/{fundraiser_id}/payments")
async def get_payments(
    fundraiser_id: int,
    status: Optional[str] = None,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    return db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id).all()

@router.post("/payments/{payment_id}/confirm")
async def confirm_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin)
):
    payment = db.query(models.Payment).filter_by(id=payment_id).first()
    if not payment: raise HTTPException(status_code=404)
    payment.status = "confirmed"
    db.commit()
    wa.send_text(payment.payer_jid, f"✅ *Pago Confirmado*\n\nTu pago para *{payment.fundraiser.name}* ha sido verificado.")
    return {"status": "confirmed"}
