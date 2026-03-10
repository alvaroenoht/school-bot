# -*- coding: utf-8 -*-
"""
GPT-based assignment analyzer.
Extracts materials list and summary from assignment HTML descriptions.
"""
import json
import logging

import openai

from app.config import get_settings

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = "Eres un asistente escolar útil."

USER_PROMPT = """
Eres un asistente escolar que ayuda a los padres a preparar materiales que sus hijos deben traer de casa para su asignación.

Lee el título y la descripción y responde en JSON con este formato:
{{
  "needs_materials": true|false,
  "materials": ["lista", "de", "materiales que deben traer de casa"],
  "summary": "Breve resumen de la actividad"
}}

Indica solo materiales que explícitamente se mencionan en la descripción como necesarios para traer de casa.

**Título**: {title}
**Descripción**: {description}
"""


CHANGE_SYSTEM_PROMPT = "Eres un asistente escolar que ayuda a los padres de familia."

CHANGE_USER_PROMPT = """
Una actividad escolar fue actualizada. Determina si el cambio es relevante para notificar a los padres y redacta un mensaje claro si lo es.

Materia: {subject_name}

ANTES:
- Título: {old_title}
- Fecha: {old_date}
- Resumen: {old_summary}
- Materiales: {old_materials}

AHORA:
- Título: {new_title}
- Fecha: {new_date}
- Resumen: {new_summary}
- Materiales: {new_materials}

Responde SOLO en JSON con este formato:
{{
  "worth_notifying": true|false,
  "message": "Mensaje breve en español para los padres describiendo qué cambió. Solo completa este campo si worth_notifying es true, de lo contrario deja vacío."
}}

Vale la pena notificar si hay cambios sustanciales: nueva fecha de entrega, nuevos materiales requeridos, cambio importante en la descripción o título. No notifiques por correcciones menores de texto o cambios triviales.
"""


def analyze_change(change: dict) -> dict:
    """
    For a 'new' assignment: always worth notifying, returns a standard message.
    For an 'updated' assignment: calls GPT to decide if it's worth notifying and
    returns a human-readable diff message.

    Returns dict with: worth_notifying (bool), message (str).
    """
    if change["type"] == "new":
        summary = change.get("summary", "")
        materials = change.get("materials", "")
        msg = f"*{change['subject_name']}*: {change['title']}"
        if summary:
            msg += f"\n_{summary}_"
        if materials:
            msg += f"\n📦 Materiales: {materials}"
        return {"worth_notifying": True, "message": msg}

    # type == "updated"
    old = change.get("old") or {}
    settings = get_settings()
    client = openai.OpenAI(api_key=settings.openai_api_key)

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": CHANGE_SYSTEM_PROMPT},
                {"role": "user", "content": CHANGE_USER_PROMPT.format(
                    subject_name=change.get("subject_name", ""),
                    old_title=old.get("title", ""),
                    old_date=old.get("date", ""),
                    old_summary=old.get("summary", ""),
                    old_materials=old.get("materials", ""),
                    new_title=change.get("title", ""),
                    new_date=change.get("date", ""),
                    new_summary=change.get("summary", ""),
                    new_materials=change.get("materials", ""),
                )},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        result = json.loads(response.choices[0].message.content)
        return {
            "worth_notifying": bool(result.get("worth_notifying", False)),
            "message": result.get("message", ""),
        }
    except Exception as e:
        logger.error(f"GPT change analysis failed for '{change.get('title')}': {e}")
        # Fallback: always notify with basic info
        return {
            "worth_notifying": True,
            "message": f"*{change['subject_name']}*: {change['title']} _(actualizado)_",
        }


def analyze_materials(title: str, description: str) -> dict:
    """
    Analyze an assignment and return materials + summary.
    API key is read from settings (env var), not passed as argument.
    """
    settings = get_settings()
    client = openai.OpenAI(api_key=settings.openai_api_key)

    try:
        response = client.chat.completions.create(
            model=settings.openai_model,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": USER_PROMPT.format(
                    title=title, description=description
                )},
            ],
            temperature=0.2,
            response_format={"type": "json_object"},
        )
        result_text = response.choices[0].message.content
        return json.loads(result_text)

    except Exception as e:
        logger.error(f"GPT analysis failed for '{title}': {e}")
        return {"needs_materials": False, "materials": [], "summary": ""}
