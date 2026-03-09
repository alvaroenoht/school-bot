"""
Fundraiser admin commands and creation flow.

Simple commands (non-conversational):
    fundraiser list
    fundraiser close <id>
    fundraiser delete <id>
    fundraiser report <id>

Conversational:
    fundraiser create <name>   →  multi-step creation via ConversationSession
"""
import logging
import secrets
import string
from datetime import datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()


async def handle_command(admin_phone: str, chat_id: str, text: str, db: Session) -> bool:
    """Handle all fundraiser admin commands.  Returns True if handled."""
    parts = text.strip().lstrip("/").split(None, 2)
    # parts[0] = "fundraiser", parts[1] = sub-command, parts[2] = argument (optional)
    if len(parts) < 2:
        wa.send_text(chat_id, _HELP)
        return True

    sub = parts[1].lower()

    # ── fundraiser create <name> ──────────────────────────────────────────
    if sub == "create" or sub == "crear":
        name = parts[2].strip() if len(parts) > 2 else None
        if not name:
            wa.send_text(chat_id, "Uso: `/fundraiser create <nombre>`")
            return True

        # Enforce unique fundraiser names (case-insensitive)
        dup = db.query(models.Fundraiser).filter(
            models.Fundraiser.name.ilike(name)
        ).first()
        if dup:
            wa.send_text(
                chat_id,
                f"❌ Ya existe una actividad con ese nombre:\n"
                f"  • *{dup.name}* (ID `{dup.id}`) — {dup.status}\n\n"
                "Usa un nombre diferente.",
            )
            return True

        # Start conversational flow
        existing = db.query(models.ConversationSession).filter_by(chat_jid=chat_id).first()
        if existing:
            db.delete(existing)
            db.flush()
        session = models.ConversationSession(
            chat_jid=chat_id,
            flow="fundraiser_create",
            step="awaiting_account",
            data={"name": name},
        )
        db.add(session)
        db.commit()
        wa.send_text(
            chat_id,
            f"\U0001f4cb Creando actividad: *{name}*\n\n"
            "\u00bfCu\u00e1l es el *n\u00famero de cuenta* para dep\u00f3sitos?",
        )
        return True

    # ── fundraiser list ───────────────────────────────────────────────────
    if sub == "list" or sub == "lista":
        fundraisers = db.query(models.Fundraiser).all()
        if not fundraisers:
            wa.send_text(chat_id, "\U0001f4cb _No hay actividades registradas._")
            return True
        lines = ["\U0001f4cb *Actividades:*\n"]
        for f in fundraisers:
            pcount = db.query(models.Payment).filter_by(fundraiser_id=f.id).count()
            status_icon = "\u2705" if f.status == "active" else "\U0001f6d1"
            type_label = f"${f.fixed_amount}" if f.type == "fixed" else "cat\u00e1logo"
            lines.append(
                f"{status_icon} [ID `{f.id}`] *{f.name}* \u2014 {f.type} ({type_label}) "
                f"\u2014 {pcount} pago(s) \u2014 {f.status}"
            )
        wa.send_text(chat_id, "\n".join(lines))
        return True

    # ── fundraiser close <id> ─────────────────────────────────────────────
    if sub == "close" or sub == "cerrar":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/fundraiser close <id>`")
            return True
        fund = db.query(models.Fundraiser).get(int(fid))
        if not fund:
            wa.send_text(chat_id, f"\u2753 No encontr\u00e9 actividad con ID `{fid}`.")
            return True
        fund.status = "closed"
        fund.closed_at = datetime.utcnow()
        db.commit()
        wa.send_text(chat_id, f"\U0001f6d1 Actividad *{fund.name}* cerrada.")
        return True

    # ── fundraiser delete <id> ────────────────────────────────────────────
    if sub == "delete" or sub == "eliminar":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/fundraiser delete <id>`")
            return True
        fund = db.query(models.Fundraiser).get(int(fid))
        if not fund:
            wa.send_text(chat_id, f"\u2753 No encontr\u00e9 actividad con ID `{fid}`.")
            return True
        pcount = db.query(models.Payment).filter_by(fundraiser_id=fund.id).count()
        if pcount > 0:
            wa.send_text(
                chat_id,
                f"\u274c No se puede eliminar *{fund.name}*: tiene {pcount} pago(s) registrados.\n"
                "Usa `fundraiser close {fid}` para cerrarla en su lugar.",
            )
            return True
        db.delete(fund)
        db.commit()
        wa.send_text(chat_id, f"\U0001f5d1\ufe0f Actividad *{fund.name}* eliminada.")
        return True

    # ── fundraiser report <id> ────────────────────────────────────────────
    if sub == "report" or sub == "reporte":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/fundraiser report <id>`")
            return True
        fund = db.query(models.Fundraiser).get(int(fid))
        if not fund:
            wa.send_text(chat_id, f"\u2753 No encontr\u00e9 actividad con ID `{fid}`.")
            return True
        payments = db.query(models.Payment).filter_by(fundraiser_id=fund.id).all()
        if not payments:
            wa.send_text(chat_id, f"\u26a0\ufe0f *{fund.name}* no tiene pagos registrados a\u00fan.")
            return True

        # Send as text report (WAHA CORE doesn't support sendFile)
        _send_text_report(chat_id, fund, payments, db)
        return True

    # ── Unknown sub-command ───────────────────────────────────────────────
    wa.send_text(chat_id, _HELP)
    return True


async def handle_conversation(
    raw_jid: str, chat_id: str, text: str, db: Session,
    session: models.ConversationSession,
):
    """Drive the fundraiser creation state machine."""
    data: dict = session.data or {}
    step = session.step
    text = text.strip()

    # ── awaiting_account ──────────────────────────────────────────────────
    if step == "awaiting_account":
        data["account_number"] = text
        _advance(session, "awaiting_type", data, db)
        wa.send_text(
            chat_id,
            "\u00bfQu\u00e9 tipo de actividad es?\n\n"
            "  `1` \u2014 Monto fijo (todos pagan lo mismo)\n"
            "  `2` \u2014 Cat\u00e1logo de productos (cada quien elige)\n\n"
            "Responde *1* o *2*:",
        )

    # ── awaiting_type ─────────────────────────────────────────────────────
    elif step == "awaiting_type":
        if text == "1":
            data["type"] = "fixed"
            _advance(session, "awaiting_amount", data, db)
            wa.send_text(chat_id, "\u00bfCu\u00e1l es el *monto fijo* a pagar? (ej: `25.00`)")
        elif text == "2":
            data["type"] = "variable"
            data["products"] = []
            _advance(session, "awaiting_product", data, db)
            wa.send_text(
                chat_id,
                "\U0001f6d2 Vamos a agregar productos al cat\u00e1logo.\n\n"
                "Env\u00eda el *nombre* y *precio* separados por espacio:\n"
                "Ej: `Galletas 5.00`\n\n"
                "Cuando termines, env\u00eda `listo`.",
            )
        else:
            wa.send_text(chat_id, "Responde *1* (monto fijo) o *2* (cat\u00e1logo):")

    # ── awaiting_amount (fixed) ───────────────────────────────────────────
    elif step == "awaiting_amount":
        try:
            amount = Decimal(text.replace(",", ".").replace("$", "").strip())
            data["fixed_amount"] = str(amount)
        except (InvalidOperation, ValueError):
            wa.send_text(chat_id, "\u274c Monto inv\u00e1lido. Ingresa un n\u00famero, ej: `25.00`")
            return
        _advance(session, "awaiting_confirmation", data, db)
        _send_summary(chat_id, data)

    # ── awaiting_product (variable) ───────────────────────────────────────
    elif step == "awaiting_product":
        if text.lower() in ("listo", "done", "fin"):
            if not data.get("products"):
                wa.send_text(chat_id, "\u274c Debes agregar al menos un producto.")
                return
            _advance(session, "awaiting_confirmation", data, db)
            _send_summary(chat_id, data)
            return

        # Parse "Name Price"
        parts = text.rsplit(None, 1)
        if len(parts) < 2:
            wa.send_text(chat_id, "Formato: `Nombre Precio`, ej: `Galletas 5.00`")
            return
        name, price_str = parts
        try:
            price = Decimal(price_str.replace(",", ".").replace("$", ""))
            data["products"].append({"name": name.strip(), "price": str(price)})
            flag_modified(session, "data")
            _advance(session, "awaiting_product", data, db)
            wa.send_text(
                chat_id,
                f"\u2705 *{name.strip()}* \u2014 ${price}\n\n"
                "Env\u00eda otro producto o `listo` para terminar.",
            )
        except (InvalidOperation, ValueError):
            wa.send_text(chat_id, f"\u274c Precio inv\u00e1lido: `{price_str}`. Ej: `Galletas 5.00`")

    # ── awaiting_confirmation ─────────────────────────────────────────────
    elif step == "awaiting_confirmation":
        if text.lower() in ("si", "s\u00ed", "yes", "confirmar"):
            fund = models.Fundraiser(
                name=data["name"],
                account_number=data["account_number"],
                type=data["type"],
                fixed_amount=data.get("fixed_amount"),
                status="active",
            )
            db.add(fund)
            db.flush()

            # Add products for variable type
            for i, p in enumerate(data.get("products", [])):
                db.add(models.FundraiserProduct(
                    fundraiser_id=fund.id,
                    name=p["name"],
                    price=p["price"],
                    sort_order=i,
                ))

            db.delete(session)
            db.commit()

            wa.send_text(
                chat_id,
                f"\u2705 Actividad *{fund.name}* creada (ID `{fund.id}`).\n\n"
                f"Los padres pueden pagar con: `/pagar {fund.name}`",
            )
        elif text.lower() in ("no", "cancelar", "cancel"):
            db.delete(session)
            db.commit()
            wa.send_text(chat_id, "\u274c Creaci\u00f3n cancelada.")
        else:
            wa.send_text(chat_id, "Responde *si* para confirmar o *no* para cancelar.")


# ── Helpers ────────────────────────────────────────────────────────────────────

def _send_text_report(chat_id: str, fund, payments, db):
    """Send fundraiser report as formatted WhatsApp text messages."""
    total_amount = sum(
        float(p.amount) for p in payments
        if p.amount and p.amount.replace(".", "").replace(",", "").isdigit()
    )
    confirmed = sum(1 for p in payments if p.status == "confirmed")
    flagged = sum(1 for p in payments if p.status == "flagged")

    type_label = f"Monto fijo: ${fund.fixed_amount}" if fund.type == "fixed" else "Catálogo"
    header = (
        f"\U0001f4ca *Reporte: {fund.name}*\n"
        f"{type_label} — {fund.status}\n\n"
        f"Total recaudado: *${total_amount:.2f}*\n"
        f"Pagos: {len(payments)} "
        f"(\u2705 {confirmed} confirmados, \u26a0\ufe0f {flagged} por revisar)\n"
        f"Cuenta: `{fund.account_number}`"
    )
    wa.send_text(chat_id, header)

    # Send payments in chunks to avoid message length limits
    chunk_lines = []
    for i, p in enumerate(payments, 1):
        status = "\u26a0\ufe0f" if p.status == "flagged" else "\u2705"
        date_str = p.submitted_at.strftime("%d/%m %H:%M") if p.submitted_at else "—"
        amount_str = f"${p.amount}" if p.amount else "—"

        line = (
            f"*{i}.* {status} {p.payer_name}\n"
            f"    Estudiante: {p.child_name or '—'}\n"
            f"    Monto: {amount_str} | Código: {p.confirmation_code or '—'}\n"
            f"    Fecha: {date_str}"
        )

        # For variable fundraisers, include order items
        if fund.type == "variable":
            items = db.query(models.OrderItem).filter_by(payment_id=p.id).all()
            if items:
                order_text = ", ".join(f"{oi.quantity}x {oi.product.name}" for oi in items)
                line += f"\n    Pedido: {order_text}"

        chunk_lines.append(line)

        # Send every 10 payments to avoid huge messages
        if len(chunk_lines) == 10:
            wa.send_text(chat_id, "\n\n".join(chunk_lines))
            chunk_lines = []

    if chunk_lines:
        wa.send_text(chat_id, "\n\n".join(chunk_lines))


_HELP = (
    "\U0001f4cb *Comandos de actividades:*\n\n"
    "  `/fundraiser create <nombre>` \u2014 crear nueva\n"
    "  `/fundraiser list` \u2014 listar todas\n"
    "  `/fundraiser close <id>` \u2014 cerrar\n"
    "  `/fundraiser delete <id>` \u2014 eliminar (sin pagos)\n"
    "  `/fundraiser report <id>` \u2014 reporte"
)


def _advance(session: models.ConversationSession, step: str, data: dict, db: Session):
    session.step = step
    session.data = dict(data)
    flag_modified(session, "data")
    session.updated_at = datetime.utcnow()
    db.commit()


def _send_summary(chat_id: str, data: dict):
    """Send a confirmation summary before creating the fundraiser."""
    lines = [
        "\U0001f4cb *Resumen de la actividad:*\n",
        f"  \u2022 Nombre: *{data['name']}*",
        f"  \u2022 Cuenta: `{data['account_number']}`",
        f"  \u2022 Tipo: *{data['type']}*",
    ]
    if data["type"] == "fixed":
        lines.append(f"  \u2022 Monto: *${data['fixed_amount']}*")
    else:
        lines.append("  \u2022 Productos:")
        for p in data.get("products", []):
            lines.append(f"    \u2514 {p['name']} \u2014 ${p['price']}")

    lines.append("\n\u00bfConfirmar? Responde *si* o *no*.")
    wa.send_text(chat_id, "\n".join(lines))
