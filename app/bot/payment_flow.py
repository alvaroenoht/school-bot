"""
Parent payment flow — handles both fixed-amount and variable/catalog fundraisers.
Issue #2: Struggle detection + AI escalation added.

Entry point: DM with "pay <name>" or "pagar <name>".
Sender must be a Registered Parent or Known Contact.

Fixed flow:
    resolve_fundraiser → awaiting_child → awaiting_receipt → processing_receipt
    → awaiting_confirmation → complete

Variable/catalog flow:
    resolve_fundraiser → awaiting_child → showing_catalog → awaiting_order
    → confirming_order → awaiting_receipt → processing_receipt
    → awaiting_confirmation → complete
"""
import logging
import re
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()


# ── Public entry points ────────────────────────────────────────────────────────

async def start_from_command(
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    payer,   # Parent or KnownContact
):
    """Start a payment flow from a 'pay/pagar <name>' command."""
    # Extract fundraiser name from command
    clean = text.lstrip("/")
    match = re.match(r"(?:pay|pagar)\s+(.+)", clean, re.IGNORECASE)
    if not match:
        wa.send_text(chat_id, "Uso: `/pagar <nombre de la actividad>`")
        return

    search = match.group(1).strip()

    # Resolve fundraiser by name or ID
    fundraiser = _find_fundraiser(search, db)
    if fundraiser is None:
        active = db.query(models.Fundraiser).filter_by(status="active").all()
        if active:
            lines = ["\u2753 No encontr\u00e9 esa actividad. Activas:\n"]
            for f in active:
                lines.append(f"  \u2022 *{f.code}* \u2014 {f.name}")
            wa.send_text(chat_id, "\n".join(lines))
        else:
            wa.send_text(chat_id, "\u26a0\ufe0f No hay actividades activas en este momento.")
        return

    if fundraiser.status != "active":
        wa.send_text(chat_id, f"\U0001f6d1 La actividad *{fundraiser.name}* est\u00e1 cerrada.")
        return

    # Determine payer info — only children in fundraiser's audience
    payer_name, children = _resolve_payer_info(payer, db, fundraiser.audience_classroom_ids)

    # Build session data
    data = {
        "fundraiser_id": fundraiser.id,
        "fundraiser_name": fundraiser.name,
        "fundraiser_type": fundraiser.type,
        "payer_name": payer_name,
        "payer_type": "parent" if isinstance(payer, models.Parent) else "contact",
    }

    # Check for resumable session for the same fundraiser
    existing = db.query(models.ConversationSession).filter_by(chat_jid=raw_jid).first()
    if existing and existing.flow == "payment":
        existing_fid = (existing.data or {}).get("fundraiser_id")
        if existing_fid == fundraiser.id:
            # Resume: re-send the prompt for the current step
            resumable = {"awaiting_receipt", "awaiting_manual_amount", "awaiting_manual_code",
                         "awaiting_confirmation", "awaiting_order", "confirming_order"}
            if existing.step in resumable:
                wa.send_text(
                    chat_id,
                    f"📋 Tienes un pago pendiente para *{fundraiser.name}*.\n"
                    "Continuando donde lo dejaste...",
                )
                if existing.step == "awaiting_receipt":
                    _send_payment_instructions(chat_id, fundraiser, existing.data, db=db, payer_jid=raw_jid)
                elif existing.step in ("awaiting_manual_amount",):
                    wa.send_text(chat_id, "Ingresa el *monto pagado* (ej: `25.00`):")
                elif existing.step == "awaiting_manual_code":
                    wa.send_text(chat_id, "Ingresa el *código de confirmación* del pago:")
                elif existing.step == "awaiting_confirmation":
                    d = existing.data or {}
                    wa.send_text(
                        chat_id,
                        f"📝 Datos del pago:\n"
                        f"  • Código: *{d.get('confirmation_code', '—')}*\n"
                        f"  • Monto: *${d.get('ocr_amount', '?')}*\n\n"
                        "¿Es correcto? Responde *si* o *no*.",
                    )
                elif existing.step in ("awaiting_order", "showing_catalog", "confirming_order"):
                    _send_catalog(chat_id, fundraiser, db)
                return
    # Save the interrupted session's state so it can be resumed later
    interrupted_payment: dict | None = None
    if existing and existing.flow == "payment":
        existing_fid = (existing.data or {}).get("fundraiser_id")
        if existing_fid != fundraiser.id:
            resumable = {
                "awaiting_receipt", "awaiting_manual_amount", "awaiting_manual_code",
                "awaiting_confirmation", "awaiting_order", "confirming_order",
            }
            if existing.step in resumable:
                interrupted_payment = {
                    "step": existing.step,
                    "data": dict(existing.data or {}),
                }

    if existing:
        db.delete(existing)
        db.flush()

    # Carry the interrupted payment into the new session's data
    if interrupted_payment:
        data["_interrupted_payment"] = interrupted_payment
        int_name = (interrupted_payment.get("data") or {}).get("fundraiser_name", "otra actividad")
        wa.send_text(
            chat_id,
            f"⏸️ Pausando el pago de *{int_name}*. "
            f"Lo podrás retomar cuando termines con *{fundraiser.name}*.",
        )

    # Child selection
    if len(children) > 1:
        data["children"] = children
        session = models.ConversationSession(
            chat_jid=raw_jid, flow="payment", step="awaiting_child", data=data,
        )
        db.add(session)
        db.commit()
        lines = [f"\U0001f4b3 *{fundraiser.name}*\n\n\u00bfPara cu\u00e1l estudiante es este pago?\n"]
        for i, c in enumerate(children, 1):
            lines.append(f"  `{i}` \u2014 {c}")
        wa.send_text(chat_id, "\n".join(lines))
    else:
        data["child_name"] = children[0] if children else payer_name
        session = models.ConversationSession(
            chat_jid=raw_jid, flow="payment",
            step="showing_catalog" if fundraiser.type == "variable" else "awaiting_receipt",
            data=data,
        )
        db.add(session)
        db.commit()
        if fundraiser.type == "variable":
            _send_catalog(chat_id, fundraiser, db)
        else:
            _send_payment_instructions(chat_id, fundraiser, data, db=db, payer_jid=raw_jid)


async def show_pending(raw_jid: str, chat_id: str, db: Session, payer):
    """Show list of pending fundraisers and forms for this parent/contact."""
    # Determine classroom IDs
    if isinstance(payer, models.Parent):
        student_cls = db.query(models.Student).filter(
            models.Student.id.in_(payer.student_ids or [])
        ).all()
        classroom_ids = list({s.classroom_id for s in student_cls if s.classroom_id})
        # Also include KCG classrooms
        kcgs = db.query(models.KnownContactGroup).filter_by(
            contact_jid=payer.whatsapp_jid, active=True
        ).all()
        classroom_ids = list(set(classroom_ids) | {kcg.classroom_id for kcg in kcgs})
    elif isinstance(payer, models.KnownContact):
        kcgs = db.query(models.KnownContactGroup).filter_by(
            contact_jid=payer.jid, active=True
        ).all()
        classroom_ids = [kcg.classroom_id for kcg in kcgs]
    else:
        classroom_ids = []

    if not classroom_ids:
        wa.send_text(chat_id, "No estás vinculado a ningún grupo escolar.")
        return

    payer_jid = payer.whatsapp_jid if isinstance(payer, models.Parent) else payer.jid

    # Active fundraisers that target any of the parent's classrooms
    all_funds = db.query(models.Fundraiser).filter_by(status="active").all()
    relevant_funds = [
        f for f in all_funds
        if any(cid in (f.audience_classroom_ids or []) for cid in classroom_ids)
    ]

    # Open forms
    from sqlalchemy import distinct
    form_ids = [
        a.form_id for a in
        db.query(models.FormAudience)
        .filter(models.FormAudience.classroom_id.in_(classroom_ids))
        .all()
    ]
    open_forms = db.query(models.Form).filter(
        models.Form.id.in_(form_ids), models.Form.status == "open"
    ).all() if form_ids else []

    # Check which forms already submitted
    submitted_form_ids = {
        s.form_id for s in
        db.query(models.FormSubmission)
        .filter_by(respondent_jid=payer_jid, status="submitted")
        .all()
    }

    lines = ["📋 *Pendientes:*\n"]
    has_items = False

    # Fundraisers
    for f in relevant_funds:
        has_items = True
        _, f_children = _resolve_payer_info(payer, db, f.audience_classroom_ids)
        if f.type == "fixed" and f.fixed_amount:
            fixed = Decimal(f.fixed_amount or "0")
            # Check per child
            status_parts = []
            for child in f_children:
                paid = _get_paid_total(f.id, payer_jid, child, db)
                if paid >= fixed:
                    status_parts.append(f"✅ {child}")
                elif paid > 0:
                    status_parts.append(f"⚠️ {child} ${paid}/${fixed}")
                else:
                    status_parts.append(f"❌ {child}")
            status = " | ".join(status_parts) if len(f_children) > 1 else status_parts[0] if status_parts else "❌ Pendiente"
            lines.append(f"💳 *{f.code}* — {f.name} (${fixed})\n   {status}")
        else:
            # Variable: just check if any payment exists
            has_payment = db.query(models.Payment).filter_by(
                fundraiser_id=f.id, payer_jid=payer_jid,
            ).filter(models.Payment.status.in_(["confirmed", "pending"])).first()
            status = "✅ Pagado" if has_payment else "❌ Pendiente"
            lines.append(f"💳 *{f.code}* — {f.name}\n   {status}")

    # Forms
    for form in open_forms:
        has_items = True
        done = form.id in submitted_form_ids
        status = "✅ Enviado" if done else "❌ Pendiente"
        lines.append(f"📝 *{form.form_code}* — {form.title}\n   {status}")

    if not has_items:
        wa.send_text(chat_id, "✅ No tienes actividades ni formularios pendientes.")
        return

    lines.append("\nEscribe el *código* para iniciar.")
    wa.send_text(chat_id, "\n\n".join(lines))


async def handle(
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    session: models.ConversationSession,
    payload: dict | None = None,
):
    """Drive the payment state machine for an existing session."""
    data: dict = session.data or {}
    step = session.step
    text = (text or "").strip()
    has_media = (payload or {}).get("hasMedia", False)
    _p = payload or {}
    media_type = _p.get("type") or _p.get("_data", {}).get("type") or ""

    # ── Regex guards: reject bot-command-like inputs in name/order steps ──
    _CMD_RE = re.compile(r"^(pagar|pay|/|FORM-[A-Z0-9]+)\b", re.IGNORECASE)
    if step in ("awaiting_child", "awaiting_order", "confirming_order") and _CMD_RE.match(text):
        wa.send_text(chat_id, "Por favor responde con la opción que te pedí, no con un comando.")
        return

    # ── Image with caption in receipt step: extract caption as fallback ──
    if step == "awaiting_receipt" and has_media and media_type == "image":
        caption = _p.get("body") or _p.get("caption") or ""
        if caption:
            data.setdefault("_image_caption", caption)

    # ── Track input history for struggle detection ────────────────────────
    history = data.get("_input_history", [])
    if text:
        history = (history + [text])[-10:]
        data["_input_history"] = history
    data["_last_step"] = step

    # ── Struggle detection → AI escalation ───────────────────────────────
    struggle = _detect_struggle(session, text, data)
    if struggle:
        logger.info("Struggle detected (%s) at step=%s — escalating to agent", struggle, step)
        await _escalate_to_agent(raw_jid, chat_id, text, db, session, data, struggle)
        return

    # ── awaiting_child ────────────────────────────────────────────────────
    if step == "awaiting_child":
        children = data.get("children", [])
        if text.isdigit() and 1 <= int(text) <= len(children):
            data["child_name"] = children[int(text) - 1]
            del data["children"]

            fundraiser = db.query(models.Fundraiser).get(data["fundraiser_id"])
            if fundraiser.type == "variable":
                _advance(session, "showing_catalog", data, db)
                _send_catalog(chat_id, fundraiser, db)
            else:
                _advance(session, "awaiting_receipt", data, db)
                _send_payment_instructions(chat_id, fundraiser, data, db=db, payer_jid=raw_jid)
        else:
            wa.send_text(chat_id, f"Elige un n\u00famero del 1 al {len(children)}:")

    # ── showing_catalog ───────────────────────────────────────────────────
    elif step == "showing_catalog":
        # User sees catalog, next step is ordering
        _advance(session, "awaiting_order", data, db)
        # The catalog message was already sent, but if they type anything
        # we treat it as an order attempt
        await _process_order_input(raw_jid, chat_id, text, db, session, data)

    # ── awaiting_order ────────────────────────────────────────────────────
    elif step == "awaiting_order":
        await _process_order_input(raw_jid, chat_id, text, db, session, data)

    # ── confirming_order ──────────────────────────────────────────────────
    elif step == "confirming_order":
        if text.lower() in ("si", "s\u00ed", "yes", "confirmar"):
            fundraiser = db.query(models.Fundraiser).get(data["fundraiser_id"])
            _advance(session, "awaiting_receipt", data, db)
            _send_payment_instructions(chat_id, fundraiser, data, db=db, payer_jid=raw_jid)
        elif text.lower() in ("no", "cambiar", "editar"):
            data["_no_count"] = data.get("_no_count", 0) + 1
            fundraiser = db.query(models.Fundraiser).get(data["fundraiser_id"])
            data.pop("cart", None)
            data.pop("cart_total", None)
            _advance(session, "awaiting_order", data, db)
            wa.send_text(chat_id, "Env\u00eda tu nuevo pedido \u2014 reemplazar\u00e1 el anterior:")
            _send_catalog(chat_id, fundraiser, db)
        else:
            wa.send_text(chat_id, "Responde *si* para confirmar o *no* para cambiar tu pedido.")

    # ── awaiting_receipt ──────────────────────────────────────────────────
    elif step == "awaiting_receipt":
        if has_media and media_type == "image":
            await _process_receipt_image(raw_jid, chat_id, db, session, data, payload)
        else:
            wa.send_text(
                chat_id,
                "\U0001f4f8 Env\u00eda la *foto del comprobante* de pago.\n"
                "_(debe ser una imagen, no un documento)_",
            )

    # ── awaiting_manual_code ──────────────────────────────────────────────
    elif step == "awaiting_manual_code":
        data["confirmation_code"] = text.strip()
        _advance(session, "awaiting_confirmation", data, db)
        amount_str = data.get("ocr_amount") or data.get("cart_total") or "?"
        wa.send_text(
            chat_id,
            f"\U0001f4dd Datos del pago:\n"
            f"  \u2022 C\u00f3digo: *{data['confirmation_code']}*\n"
            f"  \u2022 Monto: *${amount_str}*\n\n"
            "\u00bfEs correcto? Responde *si* o *no*.",
        )

    # ── awaiting_manual_amount ────────────────────────────────────────────
    elif step == "awaiting_manual_amount":
        try:
            amount = Decimal(text.replace(",", ".").replace("$", "").strip())
            data["ocr_amount"] = str(amount)
        except (InvalidOperation, ValueError):
            wa.send_text(chat_id, "\u274c Monto inv\u00e1lido. Ej: `25.00`")
            return
        _advance(session, "awaiting_manual_code", data, db)
        wa.send_text(chat_id, "Ingresa el *c\u00f3digo de confirmaci\u00f3n* del pago:")

    # ── awaiting_confirmation ─────────────────────────────────────────────
    elif step == "awaiting_confirmation":
        if text.lower() in ("si", "s\u00ed", "yes"):
            await _finalize_payment(raw_jid, chat_id, db, session, data)
        elif text.lower() in ("no",):
            _advance(session, "awaiting_receipt", data, db)
            wa.send_text(
                chat_id,
                "Env\u00eda nuevamente la *foto del comprobante* de pago.",
            )
        else:
            wa.send_text(chat_id, "Responde *si* para confirmar o *no* para reenviar.")


# ── Private helpers ────────────────────────────────────────────────────────────

def _find_fundraiser(search: str, db: Session) -> models.Fundraiser | None:
    """Find fundraiser by ID, code, or name (case-insensitive partial match)."""
    if search.isdigit():
        return db.query(models.Fundraiser).get(int(search))
    # Exact code match first
    by_code = (
        db.query(models.Fundraiser)
        .filter(models.Fundraiser.code.ilike(search), models.Fundraiser.status == "active")
        .first()
    )
    if by_code:
        return by_code
    # Partial name match
    return (
        db.query(models.Fundraiser)
        .filter(
            models.Fundraiser.name.ilike(f"%{search}%"),
            models.Fundraiser.status == "active",
        )
        .first()
    )


def _resolve_payer_info(payer, db: Session, audience_classroom_ids: list[int] | None = None) -> tuple[str, list[str]]:
    """Return (payer_name, list_of_children_names).

    If audience_classroom_ids is given, only return children in those classrooms.
    """
    if isinstance(payer, models.Parent):
        name = f"{payer.first_name} {payer.last_name}"
        students = db.query(models.Student).filter_by(parent_id=payer.id).all()
        children = [f"{s.name} ({s.grade})" for s in students] if students else [name]
        return name, children
    elif isinstance(payer, models.KnownContact):
        # child_name lives on KCG (per-classroom); collect only from audience classrooms
        q = db.query(models.KnownContactGroup).filter_by(contact_jid=payer.jid, active=True)
        if audience_classroom_ids:
            q = q.filter(models.KnownContactGroup.classroom_id.in_(audience_classroom_ids))
        kcgs = q.all()
        # If no KCGs found, try resolving via phone (handles @lid vs @c.us mismatch)
        if not kcgs and payer.phone:
            alt_kc = db.query(models.KnownContact).filter(
                models.KnownContact.phone == payer.phone,
                models.KnownContact.jid != payer.jid,
            ).first()
            if alt_kc:
                q2 = db.query(models.KnownContactGroup).filter_by(contact_jid=alt_kc.jid, active=True)
                if audience_classroom_ids:
                    q2 = q2.filter(models.KnownContactGroup.classroom_id.in_(audience_classroom_ids))
                kcgs = q2.all()
        seen = set()
        children = []
        for kcg in kcgs:
            if kcg.child_name and kcg.child_name.lower() not in seen:
                seen.add(kcg.child_name.lower())
                children.append(kcg.child_name)
        if not children and payer.child_name:
            children = [payer.child_name]
        return payer.name, children if children else [payer.name]
    return "Desconocido", ["Desconocido"]


def _get_paid_total(fundraiser_id: int, payer_jid: str, child_name: str | None, db: Session) -> Decimal:
    """Sum confirmed payments for this payer+child+fundraiser."""
    payments = db.query(models.Payment).filter_by(
        fundraiser_id=fundraiser_id, payer_jid=payer_jid, status="confirmed",
    ).all()
    total = Decimal("0")
    for p in payments:
        if child_name and p.child_name and p.child_name.lower() != child_name.lower():
            continue
        try:
            total += Decimal(p.amount or "0")
        except InvalidOperation:
            pass
    return total


def _send_payment_instructions(chat_id: str, fundraiser: models.Fundraiser, data: dict,
                                db: Session | None = None, payer_jid: str | None = None):
    """Show amount + account number + partial payment info, ask for receipt."""
    if fundraiser.type == "fixed":
        fixed = Decimal(fundraiser.fixed_amount or "0")
        amount_line = f"\U0001f4b5 Monto total: *${fixed}*"

        # Show partial payment progress if applicable
        if db and payer_jid:
            paid = _get_paid_total(fundraiser.id, payer_jid, data.get("child_name"), db)
            if paid > 0:
                remaining = max(fixed - paid, Decimal("0"))
                amount_line = (
                    f"\U0001f4b5 Monto total: *${fixed}*\n"
                    f"✅ Ya pagaste: *${paid}*\n"
                    f"💳 Pendiente: *${remaining}*\n\n"
                    "Puedes pagar el total pendiente o un abono parcial."
                )
    else:
        amount_line = f"\U0001f4b5 Total del pedido: *${data.get('cart_total', '?')}*"

    wa.send_text(
        chat_id,
        f"\U0001f4b3 *Pago: {fundraiser.name}*\n"
        f"\U0001f464 Estudiante: *{data.get('child_name', '?')}*\n\n"
        f"{amount_line}\n"
        f"\U0001f3e6 Cuenta: `{fundraiser.account_number}`\n\n"
        "Realiza el dep\u00f3sito y env\u00eda la *foto del comprobante* aqu\u00ed.",
    )


def _send_catalog(chat_id: str, fundraiser: models.Fundraiser, db: Session):
    """Display the product catalog."""
    products = (
        db.query(models.FundraiserProduct)
        .filter_by(fundraiser_id=fundraiser.id)
        .order_by(models.FundraiserProduct.sort_order)
        .all()
    )
    lines = [f"\U0001f6d2 *{fundraiser.name}*\n"]
    for i, p in enumerate(products, 1):
        lines.append(f"  *{i}* — {p.name}  ${p.price}")
    lines.append(
        "\n\U0001f4dd Responde con los *n\u00fameros* de lo que quieres:\n"
        "  `1 4` \u2014 uno del 1 y uno del 4\n"
        "  `1 1 4` \u2014 dos del 1 y uno del 4\n"
        "  `1x2 4` \u2014 lo mismo con cantidad expl\u00edcita"
    )
    wa.send_text(chat_id, "\n".join(lines))


async def _process_order_input(
    raw_jid: str, chat_id: str, text: str,
    db: Session, session: models.ConversationSession, data: dict,
):
    """Parse order input and show cart summary."""
    fundraiser = db.query(models.Fundraiser).get(data["fundraiser_id"])
    products = (
        db.query(models.FundraiserProduct)
        .filter_by(fundraiser_id=fundraiser.id)
        .order_by(models.FundraiserProduct.sort_order)
        .all()
    )

    qty_map: dict[int, int] = {}  # product index (1-based) → quantity

    # Format 1: "1x2 3x1" or "1:2 3:1" — explicit quantity
    explicit = re.findall(r"(\d+)\s*[x:]\s*(\d+)", text)
    if explicit:
        for idx_str, qty_str in explicit:
            idx, qty = int(idx_str), int(qty_str)
            if 1 <= idx <= len(products) and qty > 0:
                qty_map[idx] = qty_map.get(idx, 0) + qty
    else:
        # Format 2: space/comma-separated numbers — each occurrence = +1 qty
        # Handles "1 4", "1,4", "1 1 4" (two of #1), "1. 4" (dot ignored)
        tokens = re.findall(r"\d+", text)
        for token in tokens:
            idx = int(token)
            if 1 <= idx <= len(products):
                qty_map[idx] = qty_map.get(idx, 0) + 1

    cart = []
    for idx in sorted(qty_map):
        p = products[idx - 1]
        qty = qty_map[idx]
        cart.append({"product_id": p.id, "name": p.name, "price": p.price, "qty": qty})

    if not cart:
        data["_no_entendi_count"] = data.get("_no_entendi_count", 0) + 1
        _advance(session, session.step, data, db)
        nums = " ".join(str(i) for i in range(1, min(len(products) + 1, 4)))
        wa.send_text(
            chat_id,
            f"\u274c No entend\u00ed tu pedido.\n\n"
            f"Responde con los n\u00fameros del cat\u00e1logo:\n"
            f"  `{nums}` \u2014 uno de cada uno\n"
            f"  `1x2 4` \u2014 dos del 1 y uno del 4",
        )
        return

    # Calculate totals
    total = Decimal("0")
    lines = ["\U0001f6d2 *Tu pedido:*\n"]
    for c in cart:
        subtotal = Decimal(c["price"]) * c["qty"]
        total += subtotal
        lines.append(f"  \u2022 {c['qty']}x {c['name']} \u2014 ${subtotal}")
        c["subtotal"] = str(subtotal)

    lines.append(f"\n\U0001f4b5 *Total: ${total}*")
    lines.append("\n\u00bfConfirmar pedido? Responde *si* o *no*.")

    data["cart"] = cart
    data["cart_total"] = str(total)
    _advance(session, "confirming_order", data, db)
    wa.send_text(chat_id, "\n".join(lines))


async def _process_receipt_image(
    raw_jid: str, chat_id: str,
    db: Session, session: models.ConversationSession, data: dict,
    payload: dict,
):
    """Download receipt image, run Textract OCR, and ask for confirmation."""
    message_id = payload.get("id", "")
    wa.send_text(chat_id, "\U0001f50d Analizando comprobante...")

    # Download image — prefer media.url from WAHA payload (direct file URL),
    # fall back to message-ID-based download if not available.
    media_url = (payload.get("media") or {}).get("url", "")
    if media_url:
        image_bytes = wa.download_media_url(media_url)
    else:
        image_bytes = wa.download_media(message_id)
    if not image_bytes:
        _advance(session, "awaiting_manual_amount", data, db)
        wa.send_text(
            chat_id,
            "\u26a0\ufe0f No pude descargar la imagen.\n\n"
            "Ingresa el *monto pagado* manualmente (ej: `25.00`):",
        )
        return

    # Upload receipt image to S3 for later admin viewing
    try:
        from app.utils.s3_upload import upload_bytes_to_s3
        fundraiser_id = data.get("fundraiser_id", "unknown")
        jid_safe = raw_jid.replace("@", "_").replace(".", "_")
        ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        s3_key = f"receipts/{fundraiser_id}/{jid_safe}/{ts}.jpg"
        receipt_url = upload_bytes_to_s3(image_bytes, s3_key)
        data["receipt_url"] = receipt_url
    except Exception as e:
        logger.warning(f"S3 upload failed for {raw_jid}: {e}")
        data["receipt_url"] = None

    # Run Textract
    try:
        from app.api.textract_client import analyze_receipt
        result = analyze_receipt(image_bytes)
    except Exception as e:
        logger.error(f"Textract failed for {raw_jid}: {e}")
        result = {"amount": None, "confirmation_code": None, "confidence": 0.0}

    ocr_amount = result.get("amount")
    ocr_code = result.get("confirmation_code")
    confidence = result.get("confidence", 0.0)

    data["ocr_amount"] = ocr_amount
    data["ocr_code"] = ocr_code
    data["ocr_confidence"] = confidence
    data["receipt_message_id"] = message_id

    # If OCR extracted both with good confidence
    if ocr_amount and ocr_code and confidence >= 80.0:
        data["confirmation_code"] = ocr_code
        _advance(session, "awaiting_confirmation", data, db)
        wa.send_text(
            chat_id,
            f"\U0001f4dd *Datos extra\u00eddos del comprobante:*\n\n"
            f"  \u2022 Monto: *${ocr_amount}*\n"
            f"  \u2022 C\u00f3digo: *{ocr_code}*\n\n"
            "\u00bfEs correcto? Responde *si* o *no*.",
        )
    elif ocr_amount and confidence >= 80.0:
        # Got amount but no code
        _advance(session, "awaiting_manual_code", data, db)
        wa.send_text(
            chat_id,
            f"\U0001f4dd Detect\u00e9 un monto de *${ocr_amount}*.\n\n"
            "No pude leer el c\u00f3digo de confirmaci\u00f3n.\n"
            "Ingr\u00e9salo manualmente:",
        )
    else:
        # OCR failed or low confidence
        data["ocr_failed"] = True
        _advance(session, "awaiting_manual_amount", data, db)
        wa.send_text(
            chat_id,
            "\u26a0\ufe0f No pude leer el comprobante con suficiente certeza.\n\n"
            "Ingresa el *monto pagado* manualmente (ej: `25.00`):",
        )


async def _finalize_payment(
    raw_jid: str, chat_id: str,
    db: Session, session: models.ConversationSession, data: dict,
):
    """Save Payment record, create OrderItems if catalog, notify admin."""
    fundraiser = db.query(models.Fundraiser).get(data["fundraiser_id"])

    # Duplicate guard
    code = data.get("confirmation_code", "")
    if code:
        existing = (
            db.query(models.Payment)
            .filter_by(fundraiser_id=fundraiser.id, confirmation_code=code)
            .first()
        )
        if existing:
            wa.send_text(
                chat_id,
                f"\u26a0\ufe0f Ya existe un pago con el c\u00f3digo *{code}* "
                f"para esta actividad. Registrando con advertencia.",
            )

    # Determine flag status
    flagged = bool(data.get("ocr_failed"))
    flag_reason = "ocr_failed" if data.get("ocr_failed") else None

    payment = models.Payment(
        fundraiser_id=fundraiser.id,
        payer_jid=raw_jid,
        payer_name=data.get("payer_name", "?"),
        child_name=data.get("child_name"),
        amount=data.get("ocr_amount"),
        confirmation_code=data.get("confirmation_code"),
        receipt_media_url=data.get("receipt_url"),
        confidence_score=data.get("ocr_confidence"),
        status="flagged" if flagged else "confirmed",
        flag_reason=flag_reason,
    )
    db.add(payment)
    db.flush()

    # Create order items for variable fundraisers
    for item in data.get("cart", []):
        db.add(models.OrderItem(
            payment_id=payment.id,
            product_id=item["product_id"],
            quantity=item["qty"],
            subtotal=item.get("subtotal", "0"),
        ))

    # Restore interrupted payment session (if any) before committing
    interrupted = data.pop("_interrupted_payment", None)
    db.delete(session)
    if interrupted:
        restored = models.ConversationSession(
            chat_jid=raw_jid,
            flow="payment",
            step=interrupted["step"],
            data=interrupted["data"],
        )
        db.add(restored)
    db.commit()

    status_icon = "\u26a0\ufe0f" if flagged else "\u2705"
    # Build cumulative progress for fixed fundraisers
    progress_line = ""
    if fundraiser.type == "fixed" and fundraiser.fixed_amount:
        fixed = Decimal(fundraiser.fixed_amount or "0")
        paid_total = _get_paid_total(fundraiser.id, raw_jid, data.get("child_name"), db)
        remaining = max(fixed - paid_total, Decimal("0"))
        if remaining > 0:
            progress_line = f"\n  \u2022 Total pagado: ${paid_total} / ${fixed} \u2014 Pendiente: ${remaining}"
        else:
            progress_line = f"\n  \u2022 Total pagado: ${paid_total} / ${fixed} \u2014 \u2705 Completo"

    wa.send_text(
        chat_id,
        f"{status_icon} *Pago registrado para {fundraiser.name}*\n\n"
        f"  \u2022 Estudiante: {data.get('child_name', '?')}\n"
        f"  \u2022 Monto: ${data.get('ocr_amount', '?')}\n"
        f"  \u2022 C\u00f3digo: {data.get('confirmation_code', 'N/A')}"
        f"{progress_line}\n\n"
        "\u00a1Gracias por tu pago!",
    )

    # Notify admin silently
    try:
        from app.config import get_settings
        settings = get_settings()
        admin_jid = settings.admin_phone  # We'll resolve this to a chat_id
        flag_note = " \u26a0\ufe0f *REQUIERE REVISI\u00d3N*" if flagged else ""
        wa.send_text(
            f"{settings.admin_phone}@c.us",
            f"\U0001f4b3 Nuevo pago recibido{flag_note}\n\n"
            f"  \u2022 Actividad: *{fundraiser.name}*\n"
            f"  \u2022 Padre: {data.get('payer_name', '?')}\n"
            f"  \u2022 Estudiante: {data.get('child_name', '?')}\n"
            f"  \u2022 Monto: ${data.get('ocr_amount', '?')}\n"
            f"  \u2022 C\u00f3digo: {data.get('confirmation_code', 'N/A')}",
        )
    except Exception as e:
        logger.warning(f"Could not notify admin of payment: {e}")

    # Notify additional subscribers
    try:
        subscribers = db.query(models.FundraiserSubscriber).filter_by(fundraiser_id=fundraiser.id).all()
        for s in subscribers:
            flag_note = " ⚠️ *REQUIERE REVISIÓN*" if flagged else ""
            wa.send_text(
                f"{s.phone}@c.us",
                f"💳 Nuevo pago recibido{flag_note}\n\n"
                f"  • Actividad: *{fundraiser.name}*\n"
                f"  • Padre: {data.get('payer_name', '?')}\n"
                f"  • Estudiante: {data.get('child_name', '?')}\n"
                f"  • Monto: ${data.get('ocr_amount', '?')}\n"
                f"  • Código: {data.get('confirmation_code', 'N/A')}",
            )
    except Exception as e:
        logger.warning(f"Could not notify subscribers of payment: {e}")

    if interrupted:
        int_name = (interrupted.get("data") or {}).get("fundraiser_name", "otra actividad")
        wa.send_text(
            chat_id,
            f"▶️ Tienes un pago pendiente para *{int_name}*.\n"
            "Escribe `pagar` para ver tus pendientes.",
        )


# ── Session helpers ────────────────────────────────────────────────────────────

def _advance(session: models.ConversationSession, step: str, data: dict, db: Session):
    session.step = step
    session.data = dict(data)
    flag_modified(session, "data")
    session.updated_at = datetime.utcnow()
    db.commit()


def _detect_struggle(session: models.ConversationSession, text: str, data: dict) -> str | None:
    """Detect parent struggling with the payment flow. Returns struggle reason or None."""
    history = data.get("_input_history", [])
    step = session.step
    txt = text.lower().strip()

    # ── Skip struggle detection for valid inputs at the current step ──
    if step == "confirming_order" and txt in ("si", "sí", "yes", "confirmar", "no", "cambiar", "editar"):
        return None
    if step == "awaiting_receipt":
        return None  # any input here (image or text) should reach the handler
    if step == "awaiting_confirmation" and txt in ("si", "sí", "yes", "confirmar", "no"):
        return None

    # 1. Repeated "No entendí" — bot sent this when order parse failed
    no_entendi_count = data.get("_no_entendi_count", 0)
    if no_entendi_count >= 2:
        return "repeated_parse_failures"

    # 2. Same input twice in a row
    if len(history) >= 2 and history[-1].lower() == history[-2].lower():
        return "repeated_input"

    # 3. Long natural language when expecting si/no or numeric
    expects_short = step in ("awaiting_confirmation", "confirming_order")
    if expects_short and len(text.split()) > 8:
        return "verbose_when_short_expected"

    # 4. Session stuck > 5 min on same step
    if session.updated_at:
        elapsed = (datetime.utcnow() - session.updated_at).total_seconds()
        same_step = data.get("_last_step") == step
        if elapsed > 300 and same_step:
            return "stuck_timeout"

    # 5. User says No twice after order confirmation
    no_count = data.get("_no_count", 0)
    if step == "confirming_order" and no_count >= 2:
        return "repeated_rejection"

    return None


async def _escalate_to_agent(
    raw_jid: str, chat_id: str, text: str,
    db: Session, session: models.ConversationSession, data: dict, reason: str,
):
    """Hand off a struggling parent to the AI agent, apply its action, then resume."""
    from app.bot.intent_agent import handle_payment_assist

    fundraiser = db.query(models.Fundraiser).get(data.get("fundraiser_id"))
    products = []
    if fundraiser and fundraiser.type == "variable":
        products = [
            {"id": p.id, "name": p.name, "price": p.price}
            for p in db.query(models.FundraiserProduct)
            .filter_by(fundraiser_id=fundraiser.id)
            .order_by(models.FundraiserProduct.sort_order)
            .all()
        ]

    context = {
        "step": session.step,
        "reason": reason,
        "fundraiser_name": data.get("fundraiser_name"),
        "fundraiser_type": getattr(fundraiser, "type", None),
        "fixed_amount": getattr(fundraiser, "fixed_amount", None),
        "cart": data.get("cart"),
        "cart_total": data.get("cart_total"),
        "child_name": data.get("child_name"),
        "payer_name": data.get("payer_name"),
        "recent_inputs": data.get("_input_history", [])[-5:],
        "products": products,
    }

    action = await handle_payment_assist(chat_id, text, context)

    # Clear history after escalation so next input isn't flagged as repeated
    data["_input_history"] = []

    if action is None:
        # Fallback: just nudge gently
        _advance(session, session.step, data, db)  # persist cleared history
        wa.send_text(chat_id, "¿Necesitas ayuda? Escribe *cancelar* para salir o *pagar* para reintentar.")
        return

    action_type = action.get("type")

    if action_type == "set_order" and action.get("cart"):
        # Agent parsed the order — apply it and advance
        cart = action["cart"]
        total = sum(float(c["price"]) * c["qty"] for c in cart)
        data["cart"] = cart
        data["cart_total"] = str(round(total, 2))
        data["_no_entendi_count"] = 0
        lines = ["🛒 *Tu pedido:*\n"]
        for c in cart:
            lines.append(f"  • {c['qty']}x {c['name']} — ${float(c['price']) * c['qty']:.2f}")
        lines.append(f"\n💵 *Total: ${total:.2f}*\n\n¿Confirmar pedido? Responde *si* o *no*.")
        _advance(session, "confirming_order", data, db)
        wa.send_text(chat_id, "\n".join(lines))

    elif action_type == "restart":
        # Reset to beginning for this fundraiser
        data.pop("cart", None); data.pop("cart_total", None)
        data["_no_entendi_count"] = 0; data["_no_count"] = 0
        _advance(session, "awaiting_receipt" if getattr(fundraiser, "type", "fixed") == "fixed" else "showing_catalog", data, db)
        if fundraiser:
            if fundraiser.type == "variable":
                wa.send_text(chat_id, "Vamos a intentar de nuevo. Aquí está el catálogo:")
                _send_catalog(chat_id, fundraiser, db)
            else:
                _send_payment_instructions(chat_id, fundraiser, data, db=db, payer_jid=raw_jid)

    elif action_type == "natural_reply" and action.get("text"):
        wa.send_text(chat_id, action["text"])

    else:
        # Unknown action — gentle nudge
        wa.send_text(chat_id, "¿Necesitas ayuda? Escribe *cancelar* para salir o *pagar* para reintentar.")
