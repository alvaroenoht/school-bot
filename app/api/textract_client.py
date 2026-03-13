"""
Receipt OCR — uses OpenAI GPT-4o vision to extract amount and confirmation code
from mobile payment screenshots (Yappy, Nequi, bank apps, etc.).
"""
import base64
import json
import logging
import re

from app.config import get_settings

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = (
    "You are a payment receipt parser. Extract the transferred amount and "
    "confirmation/transaction code from the receipt image. "
    "Respond ONLY with valid JSON in this exact format: "
    '{"amount": "1.50", "confirmation_code": "860205699"} '
    "Use null for any field you cannot find. "
    "For the amount, return only digits and a decimal point (e.g. '1.50', '25.00'). "
    "For the confirmation code, return only the alphanumeric code without # or labels."
)


def analyze_receipt(image_bytes: bytes) -> dict:
    """
    Use OpenAI GPT-4o vision to parse a payment receipt image.

    Returns:
        {
            "amount": str or None,
            "confirmation_code": str or None,
            "confidence": float (0-100),
        }
    """
    settings = get_settings()

    try:
        from openai import OpenAI
        client = OpenAI(api_key=settings.openai_api_key)

        b64 = base64.b64encode(image_bytes).decode("utf-8")

        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{b64}",
                                "detail": "low",
                            },
                        },
                        {"type": "text", "text": "Extract the amount and confirmation code from this payment receipt."},
                    ],
                },
            ],
            max_tokens=100,
            temperature=0,
        )

        raw = response.choices[0].message.content.strip()
        # Strip markdown code fences if present
        raw = re.sub(r"^```(?:json)?\s*|\s*```$", "", raw, flags=re.MULTILINE).strip()
        parsed = json.loads(raw)

        amount = _clean_amount(str(parsed.get("amount") or "")) or None
        code = str(parsed.get("confirmation_code") or "").strip() or None

        # High confidence if we got both fields, medium if only one
        if amount and code:
            confidence = 95.0
        elif amount or code:
            confidence = 85.0
        else:
            confidence = 0.0

        logger.info(f"Vision OCR: amount={amount} code={code} confidence={confidence}")
        return {"amount": amount, "confirmation_code": code, "confidence": confidence}

    except Exception as e:
        logger.error(f"Vision OCR failed: {e}")
        return {"amount": None, "confirmation_code": None, "confidence": 0.0}


def _clean_amount(raw: str) -> str:
    """Extract numeric amount from text like '$25.00', 'B/. 25,00', etc."""
    cleaned = re.sub(r"[^\d.,]", "", raw)
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(",", "")
    return cleaned
