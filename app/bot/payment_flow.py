"""
Parent payment flow — handles both fixed-amount and variable/catalog fundraisers.

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
                lines.append(f"  \u2022 `{f.name}` (ID {f.id})")
            wa.send_text(chat_id, "\n".join(lines))
        else:
            wa.send_text(chat_id, "\u26a0\ufe0f No hay actividades activas en este momento.")
        return

    if fundraiser.status != "active":
        wa.send_text(chat_id, f"\U0001f6d1 La actividad *{fundraiser.name}* est\u00e1 cerrada.")
        return

    # Determine payer info
    payer_name, children = _resolve_payer_info(payer, db)

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
                    _send_payment_instructions(chat_id, fundraiser, existing.data)
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
        db.delete(existing)
        db.flush()

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
            _send_payment_instructions(chat_id, fundraiser, data)


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
                _send_payment_instructions(chat_id, fundraiser, data)
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
            _send_payment_instructions(chat_id, fundraiser, data)
        elif text.lower() in ("no", "cambiar", "editar"):
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
    """Find fundraiser by ID or name (case-insensitive partial match)."""
    if search.isdigit():
        return db.query(models.Fundraiser).get(int(search))
    return (
        db.query(models.Fundraiser)
        .filter(
            models.Fundraiser.name.ilike(f"%{search}%"),
            models.Fundraiser.status == "active",
        )
        .first()
    )


def _resolve_payer_info(payer, db: Session) -> tuple[str, list[str]]:
    """Return (payer_name, list_of_children_names)."""
    if isinstance(payer, models.Parent):
        name = f"{payer.first_name} {payer.last_name}"
        students = db.query(models.Student).filter_by(parent_id=payer.id).all()
        children = [f"{s.name} ({s.grade})" for s in students] if students else [name]
        return name, children
    elif isinstance(payer, models.KnownContact):
        return payer.name, [payer.child_name]
    return "Desconocido", ["Desconocido"]


def _send_payment_instructions(chat_id: str, fundraiser: models.Fundraiser, data: dict):
    """Show amount + account number, ask for receipt."""
    if fundraiser.type == "fixed":
        amount_line = f"\U0001f4b5 Monto: *${fundraiser.fixed_amount}*"
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
        receipt_media_url=data.get("receipt_message_id"),
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

    db.delete(session)
    db.commit()

    status_icon = "\u26a0\ufe0f" if flagged else "\u2705"
    wa.send_text(
        chat_id,
        f"{status_icon} *Pago registrado para {fundraiser.name}*\n\n"
        f"  \u2022 Estudiante: {data.get('child_name', '?')}\n"
        f"  \u2022 Monto: ${data.get('ocr_amount', '?')}\n"
        f"  \u2022 C\u00f3digo: {data.get('confirmation_code', 'N/A')}\n\n"
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


# ── Session helpers ────────────────────────────────────────────────────────────

def _advance(session: models.ConversationSession, step: str, data: dict, db: Session):
    session.step = step
    session.data = dict(data)
    flag_modified(session, "data")
    session.updated_at = datetime.utcnow()
    db.commit()
