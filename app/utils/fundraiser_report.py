"""
Fundraiser Excel report generator.

Generates an .xlsx file, uploads to S3, and returns a presigned download URL.

For variable (catalog) fundraisers: one column per product with quantities, totals row at end.
For fixed fundraisers: simple rows with amounts, totals row at end.
"""
import io
import logging
import os
import tempfile
from datetime import datetime

from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment
from openpyxl.utils import get_column_letter
from sqlalchemy.orm import Session

from app.db import models

logger = logging.getLogger(__name__)

_HEADER_FILL = PatternFill("solid", fgColor="1F4E79")
_HEADER_FONT = Font(color="FFFFFF", bold=True)
_TOTAL_FILL = PatternFill("solid", fgColor="D6E4F0")
_TOTAL_FONT = Font(bold=True)


def generate_fundraiser_excel_url(
    fundraiser: models.Fundraiser,
    payments: list[models.Payment],
    db: Session,
) -> str:
    """Build Excel workbook, upload to S3, return presigned URL."""
    from app.utils.s3_upload import upload_file_to_s3, generate_presigned_url
    from app.utils.helpers import shorten_url

    content = _build_excel(fundraiser, payments, db)

    with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
        f.write(content)
        tmp_path = f.name

    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        s3_key = f"fundraisers/fundraiser_{fundraiser.id}_{timestamp}.xlsx"
        upload_file_to_s3(tmp_path, s3_key)
        presigned = generate_presigned_url(s3_key)
        return shorten_url(presigned)
    finally:
        os.unlink(tmp_path)


def _build_excel(
    fundraiser: models.Fundraiser,
    payments: list[models.Payment],
    db: Session,
) -> bytes:
    wb = Workbook()
    ws = wb.active
    ws.title = "Reporte"

    if fundraiser.type == "variable":
        _write_variable(ws, fundraiser, payments, db)
    else:
        _write_fixed(ws, payments)

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _apply_header(ws, headers: list[str]):
    ws.append(headers)
    for col_idx, _ in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_idx)
        cell.font = _HEADER_FONT
        cell.fill = _HEADER_FILL
        cell.alignment = Alignment(horizontal="center")


def _autofit(ws):
    for col in ws.columns:
        max_len = max((len(str(cell.value or "")) for cell in col), default=8)
        ws.column_dimensions[get_column_letter(col[0].column)].width = min(max_len + 4, 40)


def _write_variable(ws, fundraiser, payments, db):
    """One column per product; quantities per payer; totals row at bottom."""
    products = (
        db.query(models.FundraiserProduct)
        .filter_by(fundraiser_id=fundraiser.id)
        .order_by(models.FundraiserProduct.sort_order)
        .all()
    )

    all_items = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.payment_id.in_([p.id for p in payments]))
        .all()
    )
    items_by_payment: dict[int, dict[int, int]] = {}
    for item in all_items:
        items_by_payment.setdefault(item.payment_id, {})[item.product_id] = item.quantity

    headers = ["Nombre", "Estudiante"] + [p.name for p in products] + ["Total ($)", "Fecha"]
    _apply_header(ws, headers)

    product_totals = {p.id: 0 for p in products}
    grand_total = 0.0

    for payment in payments:
        order = items_by_payment.get(payment.id, {})
        quantities = []
        for p in products:
            qty = order.get(p.id, 0)
            product_totals[p.id] += qty
            quantities.append(qty if qty else "")

        try:
            amount = float(payment.amount) if payment.amount else 0.0
        except (ValueError, TypeError):
            amount = 0.0
        grand_total += amount

        date_str = payment.submitted_at.strftime("%Y-%m-%d %H:%M") if payment.submitted_at else ""
        ws.append(
            [payment.payer_name, payment.child_name or ""]
            + quantities
            + [round(amount, 2) if amount else "", date_str]
        )

    # Totals row
    totals_row = (
        ["TOTAL", ""]
        + [product_totals[p.id] for p in products]
        + [round(grand_total, 2), ""]
    )
    ws.append(totals_row)
    total_row_idx = ws.max_row
    for col_idx in range(1, len(totals_row) + 1):
        cell = ws.cell(row=total_row_idx, column=col_idx)
        cell.font = _TOTAL_FONT
        cell.fill = _TOTAL_FILL

    _autofit(ws)


def _write_fixed(ws, payments):
    """Simple name/student/amount table for fixed fundraisers."""
    _apply_header(ws, ["Nombre", "Estudiante", "Monto ($)", "Estado", "Fecha"])

    grand_total = 0.0

    for payment in payments:
        try:
            amount = float(payment.amount) if payment.amount else 0.0
        except (ValueError, TypeError):
            amount = 0.0
        grand_total += amount

        status = "Confirmado" if payment.status == "confirmed" else (
            "Por revisar" if payment.status == "flagged" else payment.status
        )
        date_str = payment.submitted_at.strftime("%Y-%m-%d %H:%M") if payment.submitted_at else ""
        ws.append([
            payment.payer_name,
            payment.child_name or "",
            round(amount, 2) if amount else "",
            status,
            date_str,
        ])

    # Totals row
    ws.append(["TOTAL", "", round(grand_total, 2), "", ""])
    total_row_idx = ws.max_row
    for col_idx in range(1, 6):
        cell = ws.cell(row=total_row_idx, column=col_idx)
        cell.font = _TOTAL_FONT
        cell.fill = _TOTAL_FILL

    _autofit(ws)
