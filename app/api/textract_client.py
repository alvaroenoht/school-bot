"""
AWS Textract receipt OCR — uses AnalyzeExpense for receipt/invoice parsing.
"""
import logging
import re

import boto3

from app.config import get_settings

logger = logging.getLogger(__name__)


def analyze_receipt(image_bytes: bytes) -> dict:
    """
    Run AWS Textract AnalyzeExpense on a receipt image.

    Returns:
        {
            "amount": str or None,
            "confirmation_code": str or None,
            "confidence": float (0-100),
            "raw_response": dict,
        }
    """
    settings = get_settings()

    try:
        client = boto3.client(
            "textract",
            region_name=settings.aws_region,
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )

        response = client.analyze_expense(
            Document={"Bytes": image_bytes}
        )
    except Exception as e:
        logger.error(f"Textract AnalyzeExpense failed: {e}")
        return {
            "amount": None,
            "confirmation_code": None,
            "confidence": 0.0,
            "raw_response": {},
        }

    amount = None
    confirmation_code = None
    best_confidence = 0.0

    for doc in response.get("ExpenseDocuments", []):
        for field in doc.get("SummaryFields", []):
            field_type = (field.get("Type") or {}).get("Text", "")
            value = (field.get("ValueDetection") or {}).get("Text", "")
            conf = (field.get("ValueDetection") or {}).get("Confidence", 0)

            if not value:
                continue

            # Amount fields
            if field_type in ("TOTAL", "AMOUNT_PAID", "AMOUNT_DUE", "SUBTOTAL"):
                if amount is None or field_type in ("TOTAL", "AMOUNT_PAID"):
                    amount = _clean_amount(value)
                    best_confidence = max(best_confidence, conf)

            # Confirmation / transaction ID fields
            if field_type in (
                "INVOICE_RECEIPT_ID", "ORDER_ID", "ACCOUNT_NUMBER",
                "PAYMENT_REFERENCE",
            ):
                confirmation_code = value.strip()
                best_confidence = max(best_confidence, conf)

    return {
        "amount": amount,
        "confirmation_code": confirmation_code,
        "confidence": round(best_confidence, 2),
        "raw_response": response,
    }


def _clean_amount(raw: str) -> str:
    """Extract numeric amount from OCR text like '$25.00', 'B/. 25,00', etc."""
    # Remove currency symbols and whitespace
    cleaned = re.sub(r"[^\d.,]", "", raw)
    # Normalize comma as decimal separator (common in Panama)
    if "," in cleaned and "." not in cleaned:
        cleaned = cleaned.replace(",", ".")
    elif "," in cleaned and "." in cleaned:
        # e.g. "1,234.56" → keep as is
        cleaned = cleaned.replace(",", "")
    return cleaned
