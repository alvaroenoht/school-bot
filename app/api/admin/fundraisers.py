import logging
import re
import unicodedata
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.api.admin.auth import get_current_admin, require_write_access
from app.bot.notifications import notify_fundraiser_created
from app.db import models
from app.db.database import get_db
from app.utils.s3_upload import upload_bytes_to_s3, generate_presigned_url
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)

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
    mode: Optional[str] = "campaign"  # campaign | fund

class FundraiserUpdate(BaseModel):
    status: Optional[str] = None  # active | closed | archived
    name: Optional[str] = None
    audience_classroom_ids: Optional[List[int]] = None
    fixed_amount: Optional[str] = None
    account_number: Optional[str] = None
    products: Optional[List[ProductSchema]] = None
    mode: Optional[str] = None
    transparency_enabled: Optional[bool] = None


MAX_RECEIPT_SIZE = 10 * 1024 * 1024  # 10 MB
ALLOWED_RECEIPT_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
EXPENSE_EDIT_WINDOW = timedelta(hours=1)


def _fund_or_404(db: Session, fundraiser_id: int) -> models.Fundraiser:
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund:
        raise HTTPException(status_code=404, detail="Fundraiser not found")
    return fund


def _require_fund_mode(fund: models.Fundraiser):
    if fund.mode != "fund":
        raise HTTPException(
            status_code=400,
            detail="Activities and expenses are only available for group-fund fundraisers",
        )


def _parse_date(s: Optional[str]) -> Optional[date]:
    if not s:
        return None
    try:
        return date.fromisoformat(s)
    except ValueError:
        raise HTTPException(status_code=400, detail=f"Invalid date: {s!r} (expected YYYY-MM-DD)")


def _can_mutate_expense(expense: models.FundraiserExpense, admin: dict) -> bool:
    """Delete/heavy-edit is only allowed if transparency is not yet published,
    or the expense is fresh (<1h) and the same admin created it."""
    fund = expense.activity.fundraiser
    if not fund.transparency_enabled:
        return True
    if datetime.utcnow() - expense.created_at <= EXPENSE_EDIT_WINDOW:
        actor = f"{admin['phone']}@c.us"
        return expense.created_by_jid == actor or admin["is_super_admin"]
    return admin["is_super_admin"]


async def _save_receipt(
    upload: UploadFile,
    *,
    fundraiser_id: int,
    activity_id: int,
    expense_id: int,
    actor_jid: str,
    db: Session,
) -> models.ExpenseReceipt:
    if upload.content_type not in ALLOWED_RECEIPT_TYPES:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type: {upload.content_type}",
        )
    data = await upload.read()
    if len(data) == 0:
        raise HTTPException(status_code=400, detail="Empty file")
    if len(data) > MAX_RECEIPT_SIZE:
        raise HTTPException(status_code=400, detail="File exceeds 10 MB limit")

    ext = (upload.filename or "").rsplit(".", 1)[-1].lower() if upload.filename and "." in upload.filename else ""
    safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", (upload.filename or "receipt"))[:80]
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
    s3_key = (
        f"expense_receipts/{fundraiser_id}/{activity_id}/{expense_id}/"
        f"{ts}_{safe_name or 'receipt'}"
    )
    url = upload_bytes_to_s3(data, s3_key, content_type=upload.content_type or "application/octet-stream")
    rec = models.ExpenseReceipt(
        expense_id=expense_id,
        media_url=url,
        s3_key=s3_key,
        filename=upload.filename,
        content_type=upload.content_type,
        size_bytes=len(data),
        uploaded_by_jid=actor_jid,
    )
    db.add(rec)
    db.flush()
    return rec


def _receipt_dict(r: models.ExpenseReceipt) -> dict:
    return {
        "id": r.id,
        "media_url": generate_presigned_url(r.s3_key),
        "filename": r.filename,
        "content_type": r.content_type,
        "size_bytes": r.size_bytes,
        "uploaded_at": r.uploaded_at,
    }


def _expense_dict(e: models.FundraiserExpense) -> dict:
    return {
        "id": e.id,
        "activity_id": e.activity_id,
        "title": e.title,
        "amount": e.amount,
        "spent_on": e.spent_on,
        "note": e.note,
        "created_by_jid": e.created_by_jid,
        "created_at": e.created_at,
        "receipts": [_receipt_dict(r) for r in e.receipts],
    }


def _activity_dict(a: models.FundraiserActivity) -> dict:
    expenses = list(a.expenses)
    total = round(sum(float(e.amount or 0) for e in expenses), 2)
    return {
        "id": a.id,
        "fundraiser_id": a.fundraiser_id,
        "name": a.name,
        "description": a.description,
        "occurred_on": a.occurred_on,
        "created_by_jid": a.created_by_jid,
        "created_at": a.created_at,
        "expenses": [_expense_dict(e) for e in expenses],
        "total_spent": total,
        "expense_count": len(expenses),
    }


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
    confirmed = [p for p in fund.payments if p.status == "confirmed" and p.voided_at is None]
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
        "mode": fund.mode,
        "transparency_enabled": fund.transparency_enabled,
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

    if not req.account_number or not req.account_number.strip():
        raise HTTPException(status_code=400, detail="account_number is required")
    code = _generate_code(req.name, db)
    mode = req.mode or "campaign"
    if mode not in ("campaign", "fund"):
        raise HTTPException(status_code=400, detail="mode must be 'campaign' or 'fund'")
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
        mode=mode,
    )
    db.add(db_fund)
    db.flush()
    if req.type == "variable" and req.products:
        for idx, p in enumerate(req.products):
            db.add(models.FundraiserProduct(fundraiser_id=db_fund.id, name=p.name, price=p.price, sort_order=idx))
    db.commit()
    return {"id": db_fund.id, "code": code, "status": "active"}


@router.post("/{fundraiser_id}/announce")
async def announce_fundraiser(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund:
        raise HTTPException(status_code=404)
    if not admin["is_super_admin"]:
        my_write_classrooms = [r["classroom_id"] for r in admin["roles"] if r["role"] != "soporte"]
        if any(cid not in my_write_classrooms for cid in (fund.audience_classroom_ids or [])):
            raise HTTPException(status_code=403, detail="Not authorized")
    notify_fundraiser_created(fund, db)
    return {"ok": True}


@router.post("/{fundraiser_id}/remind")
async def remind_unpaid(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    require_write_access(admin)
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)

    target_jids = set()
    for cid in (fund.audience_classroom_ids or []):
        kcgs = db.query(models.KnownContactGroup).filter_by(classroom_id=cid, active=True).all()
        for kcg in kcgs:
            target_jids.add(kcg.contact_jid)

    paid_jids = {p.payer_jid for p in fund.payments if p.status in ("confirmed", "pending")}
    unpaid_jids = target_jids - paid_jids

    msg = f"🔔 *Recordatorio: {fund.name}*\n\nAún no recibimos tu pago.\n\nPara pagar, responde con el código:\n*{fund.code}*"
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


@router.get("/{fundraiser_id}/excel")
async def download_excel(fundraiser_id: int, db: Session = Depends(get_db), admin: dict = Depends(get_current_admin)):
    from io import BytesIO
    from fastapi.responses import StreamingResponse
    from app.utils.fundraiser_report import _build_excel
    fund = db.query(models.Fundraiser).filter_by(id=fundraiser_id).first()
    if not fund: raise HTTPException(status_code=404)
    payments = db.query(models.Payment).filter_by(fundraiser_id=fundraiser_id, status="confirmed").all()
    if not payments:
        raise HTTPException(status_code=400, detail="No confirmed payments to export")
    content = _build_excel(fund, payments, db)
    filename = f"{fund.code}_{fund.name[:30].replace(' ', '_')}.xlsx"
    return StreamingResponse(
        BytesIO(content),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


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
                "entry_method": p.entry_method,
                "recorded_by_jid": p.recorded_by_jid,
                "method_note": p.method_note,
                "manual_proof_url": p.manual_proof_url,
                "voided_at": p.voided_at,
                "voided_by_jid": p.voided_by_jid,
                "void_reason": p.void_reason,
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
    if req.mode is not None:
        if req.mode not in ("campaign", "fund"):
            raise HTTPException(status_code=400, detail="mode must be 'campaign' or 'fund'")
        fund.mode = req.mode
    if req.transparency_enabled is not None:
        fund.transparency_enabled = req.transparency_enabled

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


# ── Group-fund activities / expenses / receipts ────────────────────────────────

@router.get("/{fundraiser_id}/activities")
async def list_activities(
    fundraiser_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    fund = _fund_or_404(db, fundraiser_id)
    _fundraiser_read_access(admin, fund)
    activities = (
        db.query(models.FundraiserActivity)
        .filter_by(fundraiser_id=fund.id)
        .order_by(models.FundraiserActivity.occurred_on.desc().nulls_last(),
                  models.FundraiserActivity.created_at.desc())
        .all()
    )
    total_collected = round(
        sum(
            float(p.amount or 0)
            for p in fund.payments
            if p.status == "confirmed" and p.voided_at is None
        ),
        2,
    )
    total_spent = round(
        sum(float(e.amount or 0) for a in activities for e in a.expenses),
        2,
    )
    return {
        "fundraiser_id": fund.id,
        "mode": fund.mode,
        "transparency_enabled": fund.transparency_enabled,
        "total_collected": total_collected,
        "total_spent": total_spent,
        "balance": round(total_collected - total_spent, 2),
        "activities": [_activity_dict(a) for a in activities],
    }


class ActivityCreate(BaseModel):
    name: str
    description: Optional[str] = None
    occurred_on: Optional[str] = None  # YYYY-MM-DD


class ActivityUpdate(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    occurred_on: Optional[str] = None


@router.post("/{fundraiser_id}/activities")
async def create_activity(
    fundraiser_id: int,
    req: ActivityCreate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    fund = _fund_or_404(db, fundraiser_id)
    _fundraiser_write_access(admin, fund, db)
    _require_fund_mode(fund)
    activity = models.FundraiserActivity(
        fundraiser_id=fund.id,
        name=req.name.strip(),
        description=req.description,
        occurred_on=_parse_date(req.occurred_on),
        created_by_jid=f"{admin['phone']}@c.us",
    )
    db.add(activity)
    db.commit()
    return _activity_dict(activity)


@router.patch("/activities/{activity_id}")
async def update_activity(
    activity_id: int,
    req: ActivityUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    activity = db.query(models.FundraiserActivity).filter_by(id=activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    _fundraiser_write_access(admin, activity.fundraiser, db)
    if req.name is not None:
        activity.name = req.name.strip()
    if req.description is not None:
        activity.description = req.description
    if req.occurred_on is not None:
        activity.occurred_on = _parse_date(req.occurred_on)
    db.commit()
    return _activity_dict(activity)


@router.delete("/activities/{activity_id}")
async def delete_activity(
    activity_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    activity = db.query(models.FundraiserActivity).filter_by(id=activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    _fundraiser_write_access(admin, activity.fundraiser, db)
    if activity.expenses:
        raise HTTPException(
            status_code=409,
            detail="Activity has expenses. Delete them first.",
        )
    db.delete(activity)
    db.commit()
    return {"status": "deleted"}


@router.post("/activities/{activity_id}/expenses")
async def create_expense(
    activity_id: int,
    title: str = Form(...),
    amount: str = Form(...),
    spent_on: Optional[str] = Form(None),
    note: Optional[str] = Form(None),
    receipts: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Create an expense with ≥1 receipt. Multipart request.
    Rejects with 400 if no receipt files are attached.
    """
    files = [f for f in (receipts or []) if f and f.filename]
    if not files:
        raise HTTPException(status_code=400, detail="At least one receipt is required")

    activity = db.query(models.FundraiserActivity).filter_by(id=activity_id).first()
    if not activity:
        raise HTTPException(status_code=404, detail="Activity not found")
    fund = activity.fundraiser
    _fundraiser_write_access(admin, fund, db)
    _require_fund_mode(fund)

    try:
        float(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be numeric")

    actor_jid = f"{admin['phone']}@c.us"
    expense = models.FundraiserExpense(
        activity_id=activity.id,
        title=title.strip(),
        amount=str(amount).strip(),
        spent_on=_parse_date(spent_on),
        note=note,
        created_by_jid=actor_jid,
    )
    db.add(expense)
    db.flush()  # assign ID for S3 keys

    try:
        for upload in files:
            await _save_receipt(
                upload,
                fundraiser_id=fund.id,
                activity_id=activity.id,
                expense_id=expense.id,
                actor_jid=actor_jid,
                db=db,
            )
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Failed to save expense receipts")
        raise HTTPException(status_code=500, detail="Failed to upload one or more receipts")

    db.refresh(expense)
    return _expense_dict(expense)


class ExpenseUpdate(BaseModel):
    title: Optional[str] = None
    amount: Optional[str] = None
    spent_on: Optional[str] = None
    note: Optional[str] = None


@router.patch("/expenses/{expense_id}")
async def update_expense(
    expense_id: int,
    req: ExpenseUpdate,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    expense = db.query(models.FundraiserExpense).filter_by(id=expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    _fundraiser_write_access(admin, expense.activity.fundraiser, db)
    if not _can_mutate_expense(expense, admin):
        raise HTTPException(
            status_code=409,
            detail="Expense is locked — transparency is published. Contact a super-admin to correct it.",
        )
    if req.title is not None:
        expense.title = req.title.strip()
    if req.amount is not None:
        try:
            float(req.amount)
        except (TypeError, ValueError):
            raise HTTPException(status_code=400, detail="amount must be numeric")
        expense.amount = str(req.amount).strip()
    if req.spent_on is not None:
        expense.spent_on = _parse_date(req.spent_on)
    if req.note is not None:
        expense.note = req.note
    db.commit()
    return _expense_dict(expense)


@router.delete("/expenses/{expense_id}")
async def delete_expense(
    expense_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    expense = db.query(models.FundraiserExpense).filter_by(id=expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    _fundraiser_write_access(admin, expense.activity.fundraiser, db)
    if not _can_mutate_expense(expense, admin):
        raise HTTPException(
            status_code=409,
            detail="Expense is locked — transparency is published. Contact a super-admin to correct it.",
        )
    db.delete(expense)
    db.commit()
    return {"status": "deleted"}


@router.post("/expenses/{expense_id}/receipts")
async def add_receipts(
    expense_id: int,
    receipts: List[UploadFile] = File(...),
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Attach additional receipts to an existing expense."""
    expense = db.query(models.FundraiserExpense).filter_by(id=expense_id).first()
    if not expense:
        raise HTTPException(status_code=404, detail="Expense not found")
    fund = expense.activity.fundraiser
    _fundraiser_write_access(admin, fund, db)

    files = [f for f in (receipts or []) if f and f.filename]
    if not files:
        raise HTTPException(status_code=400, detail="At least one file is required")

    actor_jid = f"{admin['phone']}@c.us"
    created = []
    try:
        for upload in files:
            rec = await _save_receipt(
                upload,
                fundraiser_id=fund.id,
                activity_id=expense.activity_id,
                expense_id=expense.id,
                actor_jid=actor_jid,
                db=db,
            )
            created.append(rec)
        db.commit()
    except HTTPException:
        db.rollback()
        raise
    except Exception:
        db.rollback()
        logger.exception("Failed to attach receipts to expense %s", expense_id)
        raise HTTPException(status_code=500, detail="Failed to upload one or more receipts")

    return [_receipt_dict(r) for r in created]


@router.delete("/receipts/{receipt_id}")
async def delete_receipt(
    receipt_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    rec = db.query(models.ExpenseReceipt).filter_by(id=receipt_id).first()
    if not rec:
        raise HTTPException(status_code=404, detail="Receipt not found")
    expense = rec.expense
    _fundraiser_write_access(admin, expense.activity.fundraiser, db)
    if not _can_mutate_expense(expense, admin):
        raise HTTPException(
            status_code=409,
            detail="Receipt is locked — transparency is published. Contact a super-admin to correct it.",
        )
    # Guard: expense must keep at least one receipt
    remaining = [r for r in expense.receipts if r.id != rec.id]
    if not remaining:
        raise HTTPException(
            status_code=409,
            detail="Cannot delete the only receipt. Delete the expense instead or upload a replacement first.",
        )
    db.delete(rec)
    db.commit()
    return {"status": "deleted"}


# ── Manual payments + audit trail ──────────────────────────────────────────────

MANUAL_PAYMENTS_DAILY_CAP = 20
MANUAL_METHODS = ("cash", "bank", "other")
MANUAL_PROOF_TYPES = {"image/jpeg", "image/png", "image/webp", "application/pdf"}
MANUAL_PROOF_MAX = 10 * 1024 * 1024  # 10 MB


def _fundraiser_read_access(admin: dict, fund: models.Fundraiser) -> None:
    """Any role (including soporte) in at least one target classroom, or
    super-admin. Read endpoints that expose fundraiser-scoped data
    (receipts, contacts, audit logs) must gate on this."""
    if admin["is_super_admin"]:
        return
    audience = set(fund.audience_classroom_ids or [])
    if not audience:
        # Fundraiser with no audience set — only super-admin can read.
        raise HTTPException(status_code=403, detail="Not authorized for this fundraiser")
    my_ids = {r["classroom_id"] for r in admin["roles"]}
    if not (audience & my_ids):
        raise HTTPException(status_code=403, detail="Not authorized for this fundraiser")


def _fundraiser_write_access(admin: dict, fund: models.Fundraiser, db: Session) -> None:
    """Delegate or admin role (non-soporte) in at least one target classroom,
    or super-admin. Raises 403 otherwise."""
    require_write_access(admin)
    if admin["is_super_admin"]:
        return
    audience = set(fund.audience_classroom_ids or [])
    write_ids = {
        r["classroom_id"] for r in admin["roles"] if r["role"] != "soporte"
    }
    if audience and not (audience & write_ids):
        raise HTTPException(
            status_code=403,
            detail="Not authorized for any classroom on this fundraiser",
        )


def _payment_snapshot(p: models.Payment) -> dict:
    return {
        "id": p.id,
        "fundraiser_id": p.fundraiser_id,
        "payer_jid": p.payer_jid,
        "payer_name": p.payer_name,
        "child_name": p.child_name,
        "amount": p.amount,
        "status": p.status,
        "entry_method": p.entry_method,
        "recorded_by_jid": p.recorded_by_jid,
        "method_note": p.method_note,
        "manual_proof_url": p.manual_proof_url,
        "voided_at": p.voided_at.isoformat() if p.voided_at else None,
        "voided_by_jid": p.voided_by_jid,
        "void_reason": p.void_reason,
        "submitted_at": p.submitted_at.isoformat() if p.submitted_at else None,
    }


def _resolve_payer(phone: str, db: Session) -> tuple[str, str | None, str | None]:
    """Resolve a phone to (payer_jid, payer_name, child_name).
    Prefers registered Parent, then KnownContact with same phone.
    """
    phone = (phone or "").strip().lstrip("+")
    if not phone:
        raise HTTPException(status_code=400, detail="payer_phone is required")

    parent = db.query(models.Parent).filter_by(whatsapp_jid=f"{phone}@c.us").first()
    if not parent:
        kc = db.query(models.KnownContact).filter_by(phone=phone).first()
        if kc:
            parent = db.query(models.Parent).filter_by(whatsapp_jid=kc.jid).first()
    if parent:
        return (
            parent.whatsapp_jid,
            f"{parent.first_name} {parent.last_name}".strip(),
            None,
        )

    kc = db.query(models.KnownContact).filter_by(phone=phone).first()
    if kc:
        return (kc.jid, kc.name or phone, kc.child_name)

    # No record — fall back to bare c.us JID (admin is vouching for them)
    return (f"{phone}@c.us", phone, None)


def _daily_manual_count(admin_jid: str, db: Session) -> int:
    from datetime import timedelta
    since = datetime.utcnow() - timedelta(hours=24)
    return (
        db.query(models.PaymentAudit)
        .filter(
            models.PaymentAudit.actor_jid == admin_jid,
            models.PaymentAudit.action == "created_manual",
            models.PaymentAudit.at >= since,
        )
        .count()
    )


@router.get("/{fundraiser_id}/contacts")
async def list_fundraiser_contacts(
    fundraiser_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Flat, deduped list of known contacts across the fundraiser's audience
    classrooms — used to populate the manual-payment payer picker."""
    fund = _fund_or_404(db, fundraiser_id)
    _fundraiser_read_access(admin, fund)
    audience = fund.audience_classroom_ids or []
    if not audience:
        return []

    kcgs = (
        db.query(models.KnownContactGroup)
        .filter(
            models.KnownContactGroup.classroom_id.in_(audience),
            models.KnownContactGroup.active == True,
        )
        .all()
    )

    classroom_names: dict[int, str] = {}
    for cid in audience:
        cls = db.query(models.Classroom).get(cid)
        if cls:
            classroom_names[cid] = cls.display_name or cls.name

    by_phone: dict[str, dict] = {}
    for kcg in kcgs:
        kc = db.query(models.KnownContact).filter_by(jid=kcg.contact_jid).first()
        phone = (kc.phone if kc else None) or kcg.contact_jid.replace("@c.us", "").replace("@lid", "")
        if not phone:
            continue
        entry = by_phone.setdefault(phone, {
            "phone": phone,
            "name": (kc.name if kc else None) or phone,
            "children": [],
            "classrooms": [],
            "jid": kcg.contact_jid,
        })
        if kcg.child_name and kcg.child_name not in entry["children"]:
            entry["children"].append(kcg.child_name)
        cls_label = classroom_names.get(kcg.classroom_id)
        if cls_label and cls_label not in entry["classrooms"]:
            entry["classrooms"].append(cls_label)

    return sorted(by_phone.values(), key=lambda e: e["name"].lower())


@router.post("/{fundraiser_id}/payments/manual")
async def record_manual_payment(
    fundraiser_id: int,
    payer_phone: str = Form(...),
    amount: str = Form(...),
    method: str = Form(...),
    child_name: Optional[str] = Form(None),
    method_note: Optional[str] = Form(None),
    confirmation_code: Optional[str] = Form(None),
    proof: Optional[UploadFile] = File(None),
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Record a payment the parent made outside the WhatsApp flow (cash, bank transfer, etc.).
    Immutable once created — only reversible via /void.
    """
    fund = _fund_or_404(db, fundraiser_id)
    _fundraiser_write_access(admin, fund, db)

    # Variable/catalog fundraisers depend on OrderItem rows for reporting,
    # but manual payments have no product/quantity capture. Allowing them
    # would create sales with money but no product lines — effectively
    # unrecoverable for variable-fundraiser export. Block until (if ever)
    # the modal learns to capture per-product quantities.
    if fund.type == "variable":
        raise HTTPException(
            status_code=400,
            detail="Manual payments are not supported for catalog/variable fundraisers. "
                   "Use a fixed-amount or group-fund fundraiser instead.",
        )

    if method not in MANUAL_METHODS:
        raise HTTPException(status_code=400, detail=f"method must be one of {MANUAL_METHODS}")
    try:
        amount_val = float(amount)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="amount must be numeric")
    if amount_val <= 0:
        raise HTTPException(status_code=400, detail="amount must be > 0")

    actor_jid = f"{admin['phone']}@c.us"
    if not admin["is_super_admin"] and _daily_manual_count(actor_jid, db) >= MANUAL_PAYMENTS_DAILY_CAP:
        raise HTTPException(
            status_code=429,
            detail=f"Daily manual-payment cap reached ({MANUAL_PAYMENTS_DAILY_CAP})",
        )

    payer_jid, payer_name, kc_child_name = _resolve_payer(payer_phone, db)
    child = (child_name or kc_child_name or "").strip() or None

    # Optional proof upload
    proof_url: Optional[str] = None
    proof_key: Optional[str] = None
    if proof is not None and proof.filename:
        if proof.content_type not in MANUAL_PROOF_TYPES:
            raise HTTPException(status_code=400, detail=f"Unsupported proof type: {proof.content_type}")
        data = await proof.read()
        if len(data) == 0:
            raise HTTPException(status_code=400, detail="Empty proof file")
        if len(data) > MANUAL_PROOF_MAX:
            raise HTTPException(status_code=400, detail="Proof exceeds 10 MB limit")
        safe_name = re.sub(r"[^A-Za-z0-9_.-]", "_", proof.filename)[:80]
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S_%f")
        proof_key = f"manual_payments/{fund.id}/{ts}_{safe_name}"
        try:
            proof_url = upload_bytes_to_s3(
                data, proof_key,
                content_type=proof.content_type or "application/octet-stream",
            )
        except Exception:
            logger.exception("Failed to upload manual-payment proof")
            raise HTTPException(status_code=500, detail="Failed to upload proof file")

    payment = models.Payment(
        fundraiser_id=fund.id,
        payer_jid=payer_jid,
        payer_name=payer_name,
        child_name=child,
        amount=str(round(amount_val, 2)),
        confirmation_code=confirmation_code,
        status="confirmed",
        entry_method="manual",
        recorded_by_jid=actor_jid,
        method_note=(method_note.strip() if method_note else None) or f"method={method}",
        manual_proof_url=proof_url,
        manual_proof_s3_key=proof_key,
    )
    db.add(payment)
    db.flush()

    db.add(models.PaymentAudit(
        payment_id=payment.id,
        action="created_manual",
        actor_jid=actor_jid,
        snapshot=_payment_snapshot(payment),
    ))
    db.commit()
    db.refresh(payment)

    # Parent notification (best-effort — don't fail the request if WA is down)
    try:
        from app.whatsapp.client import WahaClient
        wa = WahaClient()
        delegate_name = admin.get("phone", "el delegado")
        body = (
            f"📝 *Pago registrado a tu nombre*\n\n"
            f"Fondo: *{fund.name}*\n"
            f"Monto: *${amount_val:,.2f}*\n"
            f"Método: {method}"
        )
        if child:
            body += f"\nEstudiante: {child}"
        if payment.method_note:
            body += f"\nNota: {payment.method_note}"
        body += (
            f"\n\nRegistrado por: {delegate_name}\n\n"
            "Si esto es un error o no lo reconoces, responde a este mensaje "
            "o contacta al delegado del grupo."
        )
        wa.send_text(payer_jid, body)
    except Exception:
        logger.warning("Could not notify payer %s about manual payment %s", payer_jid, payment.id)

    return {
        "id": payment.id,
        "payer_jid": payment.payer_jid,
        "payer_name": payment.payer_name,
        "child_name": payment.child_name,
        "amount": payment.amount,
        "status": payment.status,
        "entry_method": payment.entry_method,
        "recorded_by_jid": payment.recorded_by_jid,
        "method_note": payment.method_note,
        "manual_proof_url": payment.manual_proof_url,
        "submitted_at": payment.submitted_at,
    }


class PaymentVoidRequest(BaseModel):
    reason: str


@router.post("/payments/{payment_id}/void")
async def void_payment(
    payment_id: int,
    req: PaymentVoidRequest,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Soft-void a payment. Manual payments can be voided by any delegate with
    write access on the fundraiser; other payment types require super-admin."""
    payment = db.query(models.Payment).filter_by(id=payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.voided_at is not None:
        raise HTTPException(status_code=409, detail="Payment is already voided")
    reason = (req.reason or "").strip()
    if not reason:
        raise HTTPException(status_code=400, detail="A reason is required")

    fund = payment.fundraiser
    if payment.entry_method == "manual":
        _fundraiser_write_access(admin, fund, db)
    else:
        if not admin["is_super_admin"]:
            raise HTTPException(
                status_code=403,
                detail="Only a super-admin can void receipt-based payments",
            )

    actor_jid = f"{admin['phone']}@c.us"
    payment.voided_at = datetime.utcnow()
    payment.voided_by_jid = actor_jid
    payment.void_reason = reason

    db.add(models.PaymentAudit(
        payment_id=payment.id,
        action="voided",
        actor_jid=actor_jid,
        snapshot={"reason": reason, **_payment_snapshot(payment)},
    ))
    db.commit()
    return {"status": "voided", "voided_at": payment.voided_at}


@router.post("/payments/{payment_id}/restore")
async def restore_payment(
    payment_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    """Super-admin only — undo a prior void."""
    if not admin["is_super_admin"]:
        raise HTTPException(status_code=403, detail="Super-admin only")
    payment = db.query(models.Payment).filter_by(id=payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    if payment.voided_at is None:
        raise HTTPException(status_code=409, detail="Payment is not voided")

    actor_jid = f"{admin['phone']}@c.us"
    payment.voided_at = None
    payment.voided_by_jid = None
    payment.void_reason = None
    db.add(models.PaymentAudit(
        payment_id=payment.id,
        action="restored",
        actor_jid=actor_jid,
        snapshot=_payment_snapshot(payment),
    ))
    db.commit()
    return {"status": "restored"}


@router.get("/payments/{payment_id}/audit")
async def list_payment_audit(
    payment_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin),
):
    payment = db.query(models.Payment).filter_by(id=payment_id).first()
    if not payment:
        raise HTTPException(status_code=404, detail="Payment not found")
    _fundraiser_read_access(admin, payment.fundraiser)
    rows = (
        db.query(models.PaymentAudit)
        .filter_by(payment_id=payment_id)
        .order_by(models.PaymentAudit.at.desc())
        .all()
    )
    return [
        {
            "id": r.id,
            "action": r.action,
            "actor_jid": r.actor_jid,
            "at": r.at,
            "snapshot": r.snapshot,
        }
        for r in rows
    ]
