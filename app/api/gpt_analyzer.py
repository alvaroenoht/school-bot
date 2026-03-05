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
