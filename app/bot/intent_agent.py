"""
LLM Intent Interpreter — understands free-form parent messages and
dispatches to the correct tool/handler.

Called by the webhook ONLY when no deterministic route matched:
  - Registered parent sends a non-command message
  - Known contact sends a non-command message
  - Group @mention that isn't a vincular command

Uses OpenAI function-calling to determine intent and call tool wrappers.
Multi-turn: info tools return data → LLM formulates a natural response.
Falls back to qa_handler on any LLM error.
"""
import json
import logging

import openai
from sqlalchemy.orm import Session

from app.bot import intent_tools, qa_handler
from app.config import get_settings
from app.db import models
from app.whatsapp.client import WahaClient

logger = logging.getLogger(__name__)
wa = WahaClient()

# ── OpenAI function-calling tool schemas ───────────────────────────────────────

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "query_assignments_day",
            "description": (
                "Consulta las actividades/tareas escolares para un día específico. "
                "Usa offset_days=0 para hoy, 1 para mañana, 2 para pasado mañana, etc. "
                "Para un día de la semana usa weekday: 0=lunes, 1=martes, 2=miércoles, "
                "3=jueves, 4=viernes."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "offset_days": {
                        "type": "integer",
                        "description": "Días desde hoy (0=hoy, 1=mañana)",
                    },
                    "weekday": {
                        "type": "integer",
                        "description": "Día de la semana: 0=lunes..4=viernes",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_assignments_week",
            "description": "Muestra el resumen semanal completo de actividades y materiales para todos los estudiantes.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "explain_assignment",
            "description": (
                "Busca una tarea o actividad específica por palabra clave "
                "(materia, tema, título). Devuelve la descripción completa, "
                "resumen y materiales necesarios. "
                "NO generes respuestas a las tareas — solo explica qué hay que hacer."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "search_term": {
                        "type": "string",
                        "description": "Palabra clave: materia (ciencias, español, inglés) o tema (nouns, lectura, etc.)",
                    },
                },
                "required": ["search_term"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_payment",
            "description": (
                "Inicia el flujo de pago para una actividad escolar. "
                "Usa cuando el usuario quiere pagar, dice 'ya pagué', 'quiero pagar', "
                "menciona comprobante, pregunta cuánto cuesta, o habla de dinero/cuenta/transferencia "
                "en relación a una actividad."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fundraiser_name": {
                        "type": "string",
                        "description": "Nombre o parte del nombre de la actividad a pagar",
                    },
                },
                "required": ["fundraiser_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "start_receipt_flow",
            "description": (
                "Recibe o procesa un comprobante de pago. Usa cuando el usuario "
                "envía una imagen que parece un recibo, dice que ya pagó y quiere "
                "enviar comprobante, o envía una imagen sin contexto (probablemente recibo)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "fundraiser_name": {
                        "type": "string",
                        "description": "Nombre de la actividad si se puede determinar del contexto",
                    },
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_active_fundraisers",
            "description": (
                "Lista las actividades escolares activas que están aceptando pagos. "
                "Usa cuando el usuario pregunta qué puede pagar, qué actividades hay, "
                "o quiere ver las opciones disponibles."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
]

# ── System prompt ──────────────────────────────────────────────────────────────

_SYSTEM_TEMPLATE = """\
Eres el asistente escolar de WhatsApp del colegio La Salle. \
Hablas español panameño informal y amigable — como un chat real. \
Usa emojis con moderación (1-2 por mensaje).

Tu rol:
- Ayudar a padres con consultas sobre tareas y actividades escolares
- Guiar pagos de actividades escolares
- Responder preguntas sobre el calendario escolar

Reglas estrictas:
- Respuestas CORTAS (2-4 líneas máximo, estilo WhatsApp)
- Usa las herramientas para consultar datos reales — NUNCA inventes fechas, tareas o montos
- Si no hay herramienta apropiada, responde con un mensaje amable y sugiere opciones
- NUNCA des respuestas a tareas escolares ni ayudes a hacer trampa
- Si te piden ayuda con una tarea, explica los pasos o conceptos pero no des la respuesta final
- Al sugerir acciones, ofrece opciones claras: "hoy, mañana, semana, pagar"
- Cuando presentes datos de actividades, usa formato WhatsApp con emojis y negritas

{sender_context}

{fundraiser_context}\
"""


def _build_system_prompt(sender, is_admin: bool, db: Session) -> str:
    """Build system prompt with sender context and active fundraisers."""
    sender_ctx = _build_sender_context(sender, is_admin, db)
    fundraiser_ctx = _build_fundraiser_context(db)
    return _SYSTEM_TEMPLATE.format(
        sender_context=sender_ctx,
        fundraiser_context=fundraiser_ctx,
    )


def _build_sender_context(sender, is_admin: bool, db: Session) -> str:
    """Build the sender context section of the system prompt."""
    if isinstance(sender, models.Parent):
        students = (
            db.query(models.Student)
            .filter(models.Student.id.in_(sender.student_ids or []))
            .all()
        )
        student_info = ", ".join(f"{s.name} ({s.grade})" for s in students)
        return (
            f"Usuario: {sender.first_name} {sender.last_name} (padre registrado)\n"
            f"Estudiantes: {student_info}\n"
            f"Admin: {'sí' if is_admin else 'no'}"
        )
    elif isinstance(sender, models.KnownContact):
        return (
            f"Usuario: {sender.name} (contacto conocido, no registrado)\n"
            f"Hijo/a: {sender.child_name}\n"
            "Puede: pagar actividades. No puede: consultar tareas (no tiene credenciales del portal)."
        )
    return "Usuario: desconocido"


def _build_fundraiser_context(db: Session) -> str:
    """Build a brief list of active fundraisers for the system prompt."""
    active = db.query(models.Fundraiser).filter_by(status="active").all()
    if not active:
        return "Actividades activas: ninguna."
    lines = ["Actividades activas:"]
    for f in active:
        if f.type == "fixed":
            lines.append(f"- {f.name} (monto fijo ${f.fixed_amount})")
        else:
            lines.append(f"- {f.name} (catálogo de productos)")
    return "\n".join(lines)


# ── Main handler ───────────────────────────────────────────────────────────────

async def handle(
    raw_jid: str,
    chat_id: str,
    text: str,
    db: Session,
    sender: models.Parent | models.KnownContact,
    is_admin: bool = False,
    has_media: bool = False,
    media_type: str = "",
    message_id: str = "",
    payload: dict | None = None,
) -> None:
    """
    LLM Intent Interpreter entry point.

    1. Build context + system prompt
    2. Call OpenAI with function-calling tools
    3. If tool returns data → feed back to LLM for natural response (multi-turn)
    4. If tool returns None → it already sent a WA message (payment flows)
    5. On error, fall back to qa_handler (parents) or brief help (contacts)
    """
    settings = get_settings()

    # Build user message content
    if has_media and "image" in (media_type or ""):
        if text:
            user_content = f"[El usuario envió una imagen con el mensaje: {text}]"
        else:
            user_content = "[El usuario envió una imagen sin texto — probablemente un comprobante de pago]"
    elif text:
        user_content = text
    else:
        # No text and no image — nothing to process
        return

    system_prompt = _build_system_prompt(sender, is_admin, db)

    try:
        client = openai.OpenAI(api_key=settings.openai_api_key)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ]

        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=messages,
            tools=TOOLS,
            tool_choice="auto",
            temperature=0.3,
            max_tokens=300,
        )

        message = response.choices[0].message

        # ── Tool calls ────────────────────────────────────────────────────
        if message.tool_calls:
            tool_call = message.tool_calls[0]  # handle first tool call
            fn_name = tool_call.function.name
            fn_args = json.loads(tool_call.function.arguments)

            logger.info(
                "INTENT route=llm jid=%s intent=%s args=%s",
                raw_jid, fn_name, fn_args,
            )

            # Permission check
            if intent_tools.is_admin_only(fn_name) and not is_admin:
                wa.send_text(chat_id, "Ese comando es solo para administradores. 🔒")
                return

            result = await intent_tools.dispatch(
                fn_name,
                fn_args,
                raw_jid=raw_jid,
                chat_id=chat_id,
                text=text,
                db=db,
                sender=sender,
                is_admin=is_admin,
                message_id=message_id,
                payload=payload,
            )

            # If tool returned data, feed it back to the LLM for a natural response
            if result is not None:
                logger.info("INTENT route=llm_multiturn jid=%s tool=%s", raw_jid, fn_name)

                messages.append(message.model_dump())
                messages.append({
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": result,
                })

                followup = client.chat.completions.create(
                    model=settings.openai_model,
                    messages=messages,
                    temperature=0.3,
                    max_tokens=500,
                )

                reply = followup.choices[0].message.content
                if reply:
                    wa.send_text(chat_id, reply)
                else:
                    # LLM returned empty — send the raw data as fallback
                    wa.send_text(chat_id, result)
            # else: tool already sent WA message (payment flows, etc.)
            return

        # ── Plain text response ───────────────────────────────────────────
        if message.content:
            logger.info("INTENT route=llm_text jid=%s", raw_jid)
            wa.send_text(chat_id, message.content)
            return

        # ── Empty response — should not happen, but handle gracefully ─────
        logger.warning("INTENT route=llm_empty jid=%s", raw_jid)
        _fallback(raw_jid, chat_id, text, db, sender)

    except Exception as e:
        logger.error("INTENT route=llm_error jid=%s error=%s", raw_jid, e)
        _fallback(raw_jid, chat_id, text, db, sender)


def _fallback(raw_jid, chat_id, text, db, sender):
    """Fall back to keyword-based qa_handler or brief help message."""
    if isinstance(sender, models.Parent):
        # Use the synchronous qa_handler — it doesn't actually await anything
        import asyncio
        asyncio.ensure_future(
            qa_handler.handle(raw_jid, chat_id, text, db, sender)
        )
    else:
        wa.send_text(
            chat_id,
            f"Hola *{sender.name}*! 👋 Puedes usar:\n"
            "  • `/pagar <nombre>` — pagar una actividad escolar\n"
            "  • Pregúntame qué actividades hay disponibles",
        )
