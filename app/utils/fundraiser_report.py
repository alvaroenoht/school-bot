"""
Fundraiser CSV report generator.

Generates a CSV, uploads to S3, and returns a presigned download URL.

For variable (catalog) fundraisers: one column per product with quantities, totals row at end.
For fixed fundraisers: simple rows with amounts, totals row at end.
"""
import csv
import io
import logging
import os
import tempfile
from datetime import datetime

from sqlalchemy.orm import Session

from app.db import models

logger = logging.getLogger(__name__)


def generate_fundraiser_csv_url(
    fundraiser: models.Fundraiser,
    payments: list[models.Payment],
    db: Session,
) -> str:
    """Build CSV, upload to S3, return presigned URL."""
    from app.utils.s3_upload import upload_file_to_s3, generate_presigned_url
    from app.utils.helpers import shorten_url

    content = _build_csv(fundraiser, payments, db)

    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
        f.write(content)
        tmp_path = f.name

    try:
        timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        s3_key = f"fundraisers/fundraiser_{fundraiser.id}_{timestamp}.csv"
        upload_file_to_s3(tmp_path, s3_key)
        presigned = generate_presigned_url(s3_key)
        return shorten_url(presigned)
    finally:
        os.unlink(tmp_path)


def _build_csv(
    fundraiser: models.Fundraiser,
    payments: list[models.Payment],
    db: Session,
) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)

    if fundraiser.type == "variable":
        _write_variable_csv(writer, fundraiser, payments, db)
    else:
        _write_fixed_csv(writer, payments)

    return output.getvalue().encode("utf-8-sig")  # BOM for Excel


def _write_variable_csv(writer, fundraiser, payments, db):
    """One column per product; quantities per payer; totals row at bottom."""
    products = (
        db.query(models.FundraiserProduct)
        .filter_by(fundraiser_id=fundraiser.id)
        .order_by(models.FundraiserProduct.sort_order)
        .all()
    )

    # Pre-load order items keyed by payment_id → {product_id: quantity}
    all_items = (
        db.query(models.OrderItem)
        .filter(models.OrderItem.payment_id.in_([p.id for p in payments]))
        .all()
    )
    items_by_payment: dict[int, dict[int, int]] = {}
    for item in all_items:
        items_by_payment.setdefault(item.payment_id, {})[item.product_id] = item.quantity

    # Header
    product_names = [p.name for p in products]
    writer.writerow(["Nombre", "Estudiante"] + product_names + ["Total", "Fecha"])

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
        writer.writerow(
            [payment.payer_name, payment.child_name or ""]
            + quantities
            + [f"{amount:.2f}" if amount else "", date_str]
        )

    # Totals row
    totals_row = (
        ["TOTAL", ""]
        + [product_totals[p.id] for p in products]
        + [f"{grand_total:.2f}", ""]
    )
    writer.writerow(totals_row)


def _write_fixed_csv(writer, payments):
    """Simple name/student/amount table for fixed fundraisers."""
    writer.writerow(["Nombre", "Estudiante", "Monto", "Estado", "Fecha"])

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
        writer.writerow([
            payment.payer_name,
            payment.child_name or "",
            f"{amount:.2f}" if amount else "",
            status,
            date_str,
        ])

    # Totals row
    writer.writerow(["TOTAL", "", f"{grand_total:.2f}", "", ""])
