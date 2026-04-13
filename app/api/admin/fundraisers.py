import re
import unicodedata
from typing import List, Optional
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from app.db.database import get_db
from app.db import models
from app.api.admin.auth import get_current_admin, require_write_access
from app.whatsapp.client import WahaClient
from app.bot.notifications import notify_fundraiser_created
from pydantic import BaseModel

router = APIRouter(prefix="/fundraisers", tags=["fundraisers"])
wa = WahaClient()

class ProductSchema(BaseModel):
    name: str
    price: str

class FundraiserCreate(BaseModel):
    name: str
    account_number: str
    type: str  # fixed | variable
    fixed_amount: Optional[str] = None
    audience_classroom_ids: List[int]
    products: Optional[List[ProductSchema]] = None

class FundraiserUpdate(BaseModel):
    status: Optional[str] = None  # active | closed | archived
    name: Optional[str] = None
    audience_classroom_ids: Optional[List[int]] = None
    fixed_amount: Optional[str] = None
    account_number: Optional[str] = None
    products: Optional[List[ProductSchema]] = None


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
    audience_ids = fund.audience_classroom_ids or []
    # Count kids (unique child_names) across audience classrooms
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

    # For fixed fundraisers, count unique kids who have fully paid vs partially
    if fund.type == "fixed" and fund.fixed_amount:
        fixed_amount = float(fund.fixed_amount)
        # Group confirmed payments by child_name
        child_totals: dict[str, float] = {}
        for p in confirmed:
            key = (p.child_name or "").lower().strip()
            child_totals[key] = child_totals.get(key, 0) + float(p.amount or 0)
        fully_paid = sum(1 for t in child_totals.values() if t >= fixed_amount)
        partially_paid = sum(1 for t in child_totals.values() if 0 < t < fixed_amount)
        paid_count = fully_paid
        completion_pct = round(fully_paid / audience_count * 100) if audience_count else 0
    else:
        # Variable: count unique kids with any confirmed payment
        paid_kids = {(p.child_name or "").lower().strip() for p in confirmed}
        paid_count = len(paid_kids)
        partially_paid = 0
        completion_pct = round(paid_count / audience_count * 100) if audience_count else 0

    return {
        "id": fund.id,
        "name": fund.name,
        "friendly_name": fund.friendly_name,
        "code": fund.code,
        "type": fund.type,
        "fixed_amount": fund.fixed_amount,
        "account_number": fund.account_number,
        "status": fund.status,
        "total_collected": round(total, 2),
        "paid_count": paid_count,
        "partially_paid": partially_paid,
        "audience_count": audience_count,
        "completion_pct": completion_pct,
        "created_at": fund.created_at,
        "closed_at": fund.closed_at,
        "audience_classroom_ids": fund.audience_classroom_ids or [],
        "products": [{"id": p.id, "name": p.name, "price": str(p.price)} for p in fund.products],
    }


@router.post("")
async def create_fundraiser(req: FundraiserCreate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    if not admin["is_super_admin"]:
        my_write_classrooms = [r["classroom_id"] for r in admin["roles"] if r["role"] != "soporte"]
        if any(cid not in my_write_classrooms for cid in req.audience_classroom_ids):
            raise HTTPException(status_code=403, detail="Not authorized")

    code = _generate_code(req.name, db)
    db_fund = models.Fundraiser(
        name=req.name,
        friendly_name=req.name,
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
    notify_fundraiser_created(db_fund, db)
    return {"id": db_fund.id, "code": code, "status": "active"}


@router.post("/{fundraiser_id}/remind")
async def remind_unpaid(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
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
    status: Optional[str] = None,
    include_closed: bool = False,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    q = db.query(models.Fundraiser)
    if not admin["is_super_admin"]:
        my_ids = [r["classroom_id"] for r in admin["roles"]]
        all_funds = q.all()
        funds = [f for f in all_funds if any(cid in (f.audience_classroom_ids or []) for cid in my_ids)]
    else:
        funds = q.all()

    if status:
        funds = [f for f in funds if f.status == status]
    elif include_closed:
        funds = [f for f in funds if f.status != "archived"]
    else:
        funds = [f for f in funds if f.status == "active"]

    return [_fund_stats(f, db) for f in funds]


@router.get("/{fundraiser_id}/report")
async def get_report(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)
    payments = db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id).all()

    # Build unpaid/partially-paid kids list
    confirmed_payments = [p for p in payments if p.status in ("confirmed", "pending")]
    # Track total paid per child name AND per payer JID
    child_paid_totals: dict[str, float] = {}
    jid_paid_totals: dict[str, float] = {}
    for p in confirmed_payments:
        if p.child_name:
            key = p.child_name.lower().strip()
            child_paid_totals[key] = child_paid_totals.get(key, 0) + float(p.amount or 0)
        if p.payer_jid:
            jid_paid_totals[p.payer_jid] = jid_paid_totals.get(p.payer_jid, 0) + float(p.amount or 0)

    # Map payer phone → paid total (since KCG uses @lid but payments use @c.us)
    phone_paid_totals: dict[str, float] = {}
    for jid, total in jid_paid_totals.items():
        phone = jid.replace("@c.us", "").replace("@lid", "")
        # For @lid JIDs, resolve phone via KnownContact
        if "@lid" in jid:
            kc = db.query(models.KnownContact).filter_by(jid=jid).first()
            if kc and kc.phone:
                phone = kc.phone
        phone_paid_totals[phone] = phone_paid_totals.get(phone, 0) + total

    fixed_amount = float(fund.fixed_amount or 0) if fund.type == "fixed" else 0

    unpaid = []
    for cid in (fund.audience_classroom_ids or []):
        cls = db.query(models.Classroom).get(cid)
        cls_name = (cls.display_name or cls.name) if cls else str(cid)
        kcgs = db.query(models.KnownContactGroup).filter_by(classroom_id=cid, active=True).all()
        for kcg in kcgs:
            child = (kcg.child_name or "").strip()
            if not child:
                continue
            child_key = child.lower()
            # Check paid by child_name match OR by payer JID/phone
            paid_total = child_paid_totals.get(child_key, 0)
            if paid_total == 0:
                kc = db.query(models.KnownContact).filter_by(jid=kcg.contact_jid).first()
                contact_phone = (kc.phone if kc else None) or kcg.contact_jid.replace("@c.us", "").replace("@lid", "")
                paid_total = phone_paid_totals.get(contact_phone, 0)
            else:
                kc = db.query(models.KnownContact).filter_by(jid=kcg.contact_jid).first()
            # Fully paid → skip
            if fixed_amount and paid_total >= fixed_amount:
                continue
            # No payment at all for variable → show as unpaid
            if not fixed_amount and paid_total > 0:
                continue
            entry = {
                "child_name": child,
                "parent_name": kc.name if kc else None,
                "classroom": cls_name,
            }
            if fixed_amount and paid_total > 0:
                entry["paid"] = round(paid_total, 2)
                entry["remaining"] = round(fixed_amount - paid_total, 2)
            unpaid.append(entry)
    # Deduplicate by child_name (case-insensitive)
    seen = set()
    unique_unpaid = []
    for u in unpaid:
        key = u["child_name"].lower()
        if key not in seen:
            seen.add(key)
            unique_unpaid.append(u)
    unique_unpaid.sort(key=lambda u: (u["classroom"], u["child_name"]))

    return {
        "id": fund.id, "name": fund.name, "friendly_name": fund.friendly_name,
        "code": fund.code, "status": fund.status, "type": fund.type,
        "payments": [
            {
                "id": p.id,
                "payer_jid": p.payer_jid,
                "parent": p.payer_name,
                "child": p.child_name,
                "amount": p.amount,
                "status": p.status,
                "date": p.submitted_at,
                "confirmation_code": p.confirmation_code,
                "receipt_media_url": p.receipt_media_url,
                "order_items": [
                    {"product": oi.product.name if oi.product else "?", "quantity": oi.quantity, "subtotal": oi.subtotal}
                    for oi in p.order_items
                ] if p.order_items else [],
            }
            for p in payments
        ],
        "unpaid": unique_unpaid,
    }


class PaymentStatusUpdate(BaseModel):
    status: str  # rejected | confirmed | pending | flagged


@router.patch("/payments/{payment_id}")
async def update_payment_status(
    payment_id: int,
    req: PaymentStatusUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    require_write_access(admin)
    if req.status not in ("rejected", "confirmed", "pending", "flagged"):
        raise HTTPException(status_code=400, detail="Invalid status")
    payment = db.query(models.Payment).filter_by(id=payment_id).first()
    if not payment:
        raise HTTPException(status_code=404)
    payment.status = req.status
    if req.status == "rejected":
        payment.flag_reason = "admin_rejected"
    elif payment.flag_reason == "admin_rejected":
        payment.flag_reason = None
    db.commit()
    return {"status": "updated"}


@router.patch("/{fundraiser_id}")
async def update_fundraiser(fundraiser_id: int, req: FundraiserUpdate, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    if req.status:
        fund.status = req.status
        if req.status == "closed": fund.closed_at = datetime.utcnow()
    if req.name:
        fund.name = req.name
        fund.friendly_name = req.name
    if req.account_number:
        fund.account_number = req.account_number
    if req.audience_classroom_ids is not None:
        fund.audience_classroom_ids = req.audience_classroom_ids
    if req.fixed_amount is not None:
        fund.fixed_amount = req.fixed_amount
    if req.products is not None:
        db.query(models.FundraiserProduct).filter_by(fundraiser_id=fund.id).delete()
        for idx, p in enumerate(req.products):
            db.add(models.FundraiserProduct(fundraiser_id=fund.id, name=p.name, price=p.price, sort_order=idx))

    db.commit()
    return {"status": "updated"}


@router.delete("/{fundraiser_id}")
async def delete_fundraiser(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    payment_count = db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id).count()
    if payment_count > 0:
        raise HTTPException(status_code=400, detail="Cannot delete fundraiser with existing payments")

    db.delete(fund)
    db.commit()
    return {"status": "deleted"}
