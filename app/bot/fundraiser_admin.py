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


def _check_fund_access(fund: models.Fundraiser, caller_parent: models.Parent | None) -> bool:
    """Super admin (caller_parent=None) has unrestricted access. Others must own the fundraiser."""
    if caller_parent is None:
        return True
    return fund.created_by_jid == caller_parent.whatsapp_jid


async def handle_command(
    caller_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    caller_parent: models.Parent | None = None,
) -> bool:
    """Handle all fundraiser admin commands.  Returns True if handled."""
    parts = text.strip().lstrip("/").split(None, 2)
    # parts[0] = "fundraiser"/"actividad", parts[1] = sub-command, parts[2] = argument (optional)
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

        session_data: dict = {"name": name, "creator_jid": chat_id}
        if caller_parent:
            allowed_ids = [
                s.classroom_id
                for s in db.query(models.Student).filter(
                    models.Student.id.in_(caller_parent.student_ids or [])
                ).all()
                if s.classroom_id
            ]
            if not allowed_ids:
                wa.send_text(chat_id, "❌ No tienes salones vinculados para crear una actividad.")
                return True
            session_data["allowed_classroom_ids"] = allowed_ids

        # Start conversational flow
        existing = db.query(models.ConversationSession).filter_by(chat_jid=chat_id).first()
        if existing:
            db.delete(existing)
            db.flush()
        session = models.ConversationSession(
            chat_jid=chat_id,
            flow="fundraiser_create",
            step="awaiting_account",
            data=session_data,
        )
        db.add(session)
        db.commit()
        wa.send_text(
            chat_id,
            f"📋 Creando actividad: *{name}*\n\n"
            "¿Cuál es el *número de cuenta* para depósitos?",
        )
        return True

    # ── fundraiser list ───────────────────────────────────────────────────
    if sub == "list" or sub == "lista":
        query = db.query(models.Fundraiser).order_by(models.Fundraiser.created_at.desc())
        if caller_parent:
            query = query.filter(models.Fundraiser.created_by_jid == caller_parent.whatsapp_jid)
        fundraisers = query.all()
        if not fundraisers:
            wa.send_text(chat_id, "📋 _No hay actividades registradas._")
            return True
        lines = ["📋 *Actividades:*\n"]
        for f in fundraisers:
            pcount = db.query(models.Payment).filter_by(fundraiser_id=f.id).count()
            status_icon = "✅" if f.status == "active" else "🛑"
            type_label = f"${f.fixed_amount}" if f.type == "fixed" else "catálogo"
            lines.append(
                f"{status_icon} [ID `{f.id}`] *{f.name}* — {f.type} ({type_label}) "
                f"— {pcount} pago(s) — {f.status}"
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
            wa.send_text(chat_id, f"❓ No encontré actividad con ID `{fid}`.")
            return True
        if not _check_fund_access(fund, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar esa actividad.")
            return True
        fund.status = "closed"
        fund.closed_at = datetime.utcnow()
        db.commit()
        wa.send_text(chat_id, f"🛑 Actividad *{fund.name}* cerrada.")
        return True

    # ── fundraiser delete <id> ────────────────────────────────────────────
    if sub == "delete" or sub == "eliminar":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/fundraiser delete <id>`")
            return True
        fund = db.query(models.Fundraiser).get(int(fid))
        if not fund:
            wa.send_text(chat_id, f"❓ No encontré actividad con ID `{fid}`.")
            return True
        if not _check_fund_access(fund, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para gestionar esa actividad.")
            return True
        pcount = db.query(models.Payment).filter_by(fundraiser_id=fund.id).count()
        if pcount > 0:
            wa.send_text(
                chat_id,
                f"❌ No se puede eliminar *{fund.name}*: tiene {pcount} pago(s) registrados.\n"
                f"Usa `/fundraiser close {fid}` para cerrarla en su lugar.",
            )
            return True
        db.delete(fund)
        db.commit()
        wa.send_text(chat_id, f"🗑️ Actividad *{fund.name}* eliminada.")
        return True

    # ── fundraiser report <id> ────────────────────────────────────────────
    if sub == "report" or sub == "reporte":
        fid = parts[2].strip() if len(parts) > 2 else ""
        if not fid.isdigit():
            wa.send_text(chat_id, "Uso: `/fundraiser report <id>`")
            return True
        fund = db.query(models.Fundraiser).get(int(fid))
        if not fund:
            wa.send_text(chat_id, f"❓ No encontré actividad con ID `{fid}`.")
            return True
        if not _check_fund_access(fund, caller_parent):
            wa.send_text(chat_id, "❌ No tienes permiso para ver esa actividad.")
            return True
        payments = db.query(models.Payment).filter_by(fundraiser_id=fund.id).all()
        if not payments:
            wa.send_text(chat_id, f"⚠️ *{fund.name}* no tiene pagos registrados aún.")
            return True

        _send_text_report(chat_id, fund, payments, db)
        return True

    # ── fundraiser subscribe <id> <phone> ─────────────────────────────────
    if sub in ("subscribe", "suscribir", "notify", "notificar"):
        arg = parts[2].strip() if len(parts) > 2 else ""
        arg_parts = arg.split(None, 1)
        if len(arg_parts) < 2 or not arg_parts[0].isdigit():
            wa.send_text(chat_id, "Uso: `/fundraiser subscribe <id> <teléfono>`\nEj: `/fundraiser subscribe 3 50768001234`")
            return True
        fid, phone = int(arg_parts[0]), arg_parts[1].strip().lstrip("+").replace(" ", "")
        fund = db.query(models.Fundraiser).get(fid)
        if not fund:
            wa.send_text(chat_id, f"❓ No encontré actividad con ID `{fid}`.")
            return True
        existing = db.query(models.FundraiserSubscriber).filter_by(fundraiser_id=fid, phone=phone).first()
        if existing:
            wa.send_text(chat_id, f"ℹ️ El número `{phone}` ya está suscrito a *{fund.name}*.")
            return True
        db.add(models.FundraiserSubscriber(fundraiser_id=fid, phone=phone))
        db.commit()
        wa.send_text(chat_id, f"✅ `{phone}` recibirá notificaciones de pagos para *{fund.name}*.")
        return True

    if sub in ("unsubscribe", "desuscribir"):
        arg = parts[2].strip() if len(parts) > 2 else ""
        arg_parts = arg.split(None, 1)
        if len(arg_parts) < 2 or not arg_parts[0].isdigit():
            wa.send_text(chat_id, "Uso: `/fundraiser unsubscribe <id> <teléfono>`")
            return True
        fid, phone = int(arg_parts[0]), arg_parts[1].strip().lstrip("+").replace(" ", "")
        sub_row = db.query(models.FundraiserSubscriber).filter_by(fundraiser_id=fid, phone=phone).first()
        if not sub_row:
            wa.send_text(chat_id, f"❓ `{phone}` no está suscrito a esa actividad.")
            return True
        db.delete(sub_row)
        db.commit()
        wa.send_text(chat_id, f"✅ `{phone}` eliminado de las notificaciones.")
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
            "¿Qué tipo de actividad es?\n\n"
            "  `1` — Monto fijo (todos pagan lo mismo)\n"
            "  `2` — Catálogo de productos (cada quien elige)\n\n"
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
            wa.send_text(chat_id, "❌ Monto inválido. Ingresa un número, ej: `25.00`")
            return
        _advance(session, "awaiting_audience", data, db)
        _prompt_audience(chat_id, data, db)

    # ── awaiting_product (variable) ───────────────────────────────────────
    elif step == "awaiting_product":
        if text.lower() in ("listo", "done", "fin"):
            if not data.get("products"):
                wa.send_text(chat_id, "❌ Debes agregar al menos un producto.")
                return
            _advance(session, "awaiting_audience", data, db)
            _prompt_audience(chat_id, data, db)
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

    # ── awaiting_audience ─────────────────────────────────────────────────
    elif step == "awaiting_audience":
        allowed = data.get("allowed_classroom_ids")
        if text.lower() in ("todos", "all", "todas"):
            if allowed:
                audience_ids = allowed
            else:
                classrooms = db.query(models.Classroom).filter_by(is_active=True).all()
                audience_ids = [c.id for c in classrooms]
        elif text.lower() in ("ninguno", "none", "skip", "omitir"):
            audience_ids = None  # no restriction
        else:
            raw_ids = [x.strip() for x in text.replace(",", " ").split()]
            audience_ids = []
            invalid = []
            for rid in raw_ids:
                if rid.isdigit():
                    cid = int(rid)
                    if allowed and cid not in allowed:
                        invalid.append(f"{rid} (no permitido)")
                        continue
                    cls = db.query(models.Classroom).get(cid)
                    if cls:
                        audience_ids.append(cid)
                    else:
                        invalid.append(rid)
                else:
                    invalid.append(rid)
            if invalid:
                wa.send_text(
                    chat_id,
                    f"⚠️ IDs inválidos o no permitidos: {', '.join(invalid)}\n"
                    "Intenta de nuevo:",
                )
                return
            if not audience_ids:
                wa.send_text(chat_id, "Debes incluir al menos un salón o escribe `todos`.")
                return

        data["audience"] = audience_ids
        _advance(session, "awaiting_confirmation", data, db)
        _send_summary(chat_id, data, db)

    # ── awaiting_confirmation ─────────────────────────────────────────────
    elif step == "awaiting_confirmation":
        if text.lower() in ("si", "sí", "yes", "confirmar"):
            fund = models.Fundraiser(
                name=data["name"],
                account_number=data["account_number"],
                type=data["type"],
                fixed_amount=data.get("fixed_amount"),
                status="active",
                created_by_jid=data.get("creator_jid"),
                audience_classroom_ids=data.get("audience"),
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
                f"✅ Actividad *{fund.name}* creada (ID `{fund.id}`).\n\n"
                f"{_format_pay_link(fund)}",
            )
        elif text.lower() in ("no", "cancelar", "cancel"):
            db.delete(session)
            db.commit()
            wa.send_text(chat_id, "❌ Creación cancelada.")
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


def _format_pay_link(fund: models.Fundraiser) -> str:
    """Return a copyable block with the wa.me deep link for this fundraiser."""
    from app.config import get_settings
    import urllib.parse
    bot_phone = get_settings().waha_bot_phone
    encoded = urllib.parse.quote(f"pagar {fund.name}")
    wa_link = f"https://wa.me/{bot_phone}?text={encoded}"
    type_label = f"Monto fijo: ${fund.fixed_amount}" if fund.type == "fixed" else "Catálogo de productos"

    return (
        f"💳 *Cómo compartir esta actividad:*\n\n"
        f"Actividad: *{fund.name}*\n"
        f"ID: `{fund.id}` | {type_label}\n\n"
        f"📲 *Enlace directo* (toca para abrir en WhatsApp):\n"
        f"{wa_link}\n\n"
        f"💬 *Mensaje para copiar y pegar:*\n"
        f"─────────────────────\n"
        f"💳 Actividad de pago disponible:\n"
        f"*{fund.name}*\n\n"
        f"Toca el enlace para pagar:\n"
        f"{wa_link}\n"
        f"─────────────────────"
    )


def _advance(session: models.ConversationSession, step: str, data: dict, db: Session):
    session.step = step
    session.data = dict(data)
    flag_modified(session, "data")
    session.updated_at = datetime.utcnow()
    db.commit()


def _prompt_audience(chat_id: str, data: dict, db: Session):
    """Ask which classrooms this fundraiser targets."""
    allowed = data.get("allowed_classroom_ids")
    if allowed:
        classrooms = db.query(models.Classroom).filter(
            models.Classroom.id.in_(allowed), models.Classroom.is_active == True
        ).all()
    else:
        classrooms = db.query(models.Classroom).filter_by(is_active=True).all()

    cls_list = "\n".join(f"  `{c.id}` — {c.name}" for c in classrooms)
    wa.send_text(
        chat_id,
        f"¿A qué *salones* va dirigida esta actividad?\n\n"
        f"Salones disponibles:\n{cls_list}\n\n"
        "Envía los IDs separados por comas (ej: `1, 3`) o `todos` para incluir todos.",
    )


def _send_summary(chat_id: str, data: dict, db: Session):
    """Send a confirmation summary before creating the fundraiser."""
    audience = data.get("audience")
    if audience:
        cls_names = []
        for cid in audience:
            cls = db.query(models.Classroom).get(cid)
            cls_names.append(cls.name if cls else str(cid))
        audience_str = ", ".join(cls_names)
    else:
        audience_str = "Todos"

    lines = [
        "📋 *Resumen de la actividad:*\n",
        f"  • Nombre: *{data['name']}*",
        f"  • Cuenta: `{data['account_number']}`",
        f"  • Tipo: *{data['type']}*",
        f"  • Salones: {audience_str}",
    ]
    if data["type"] == "fixed":
        lines.append(f"  • Monto: *${data['fixed_amount']}*")
    else:
        lines.append("  • Productos:")
        for p in data.get("products", []):
            lines.append(f"    └ {p['name']} — ${p['price']}")

    lines.append("\n¿Confirmar? Responde *si* o *no*.")
    wa.send_text(chat_id, "\n".join(lines))
