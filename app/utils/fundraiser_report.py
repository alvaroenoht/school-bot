"""
Fundraiser payment report PDF generator.

Uses ReportLab to create a tabular report of all payments for a fundraiser.
"""
import logging
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

from app.db import models

logger = logging.getLogger(__name__)


def create_fundraiser_report(
    fundraiser: models.Fundraiser,
    payments: list[models.Payment],
    output_path: str,
    db=None,
):
    """Generate a PDF report for a fundraiser with all payment details."""
    doc = SimpleDocTemplate(
        output_path,
        pagesize=landscape(letter),
        leftMargin=0.5 * inch,
        rightMargin=0.5 * inch,
        topMargin=0.5 * inch,
        bottomMargin=0.5 * inch,
    )
    styles = getSampleStyleSheet()
    elements = []

    # Title
    type_label = f"Monto fijo: ${fundraiser.fixed_amount}" if fundraiser.type == "fixed" else "Catálogo"
    elements.append(Paragraph(
        f"<b>Reporte: {fundraiser.name}</b> — {type_label} — {fundraiser.status}",
        styles["Title"],
    ))
    elements.append(Spacer(1, 12))

    # Summary line
    total_amount = sum(
        float(p.amount) for p in payments if p.amount and p.amount.replace(".", "").isdigit()
    )
    confirmed = sum(1 for p in payments if p.status == "confirmed")
    flagged = sum(1 for p in payments if p.status == "flagged")
    elements.append(Paragraph(
        f"Total recaudado: <b>${total_amount:.2f}</b> — "
        f"Pagos: {len(payments)} (✅ {confirmed} confirmados, ⚠️ {flagged} requieren revisión)",
        styles["Normal"],
    ))
    elements.append(Spacer(1, 12))

    # Table
    if fundraiser.type == "variable" and db:
        headers = ["#", "Padre", "Estudiante", "Pedido", "Código", "Total", "Estado", "Fecha"]
        data_rows = [headers]
        for i, p in enumerate(payments, 1):
            # Get order items
            items = db.query(models.OrderItem).filter_by(payment_id=p.id).all() if db else []
            order_text = ", ".join(
                f"{oi.quantity}x {oi.product.name}" for oi in items
            ) if items else "—"

            status_text = "⚠️" if p.status == "flagged" else "✅"
            date_str = p.submitted_at.strftime("%d/%m %H:%M") if p.submitted_at else "—"
            data_rows.append([
                str(i),
                p.payer_name,
                p.child_name or "—",
                order_text,
                p.confirmation_code or "—",
                f"${p.amount}" if p.amount else "—",
                status_text,
                date_str,
            ])
        col_widths = [0.4 * inch, 1.5 * inch, 1.5 * inch, 2.5 * inch, 1.2 * inch, 0.8 * inch, 0.6 * inch, 1.0 * inch]
    else:
        headers = ["#", "Padre", "Estudiante", "Código", "Monto", "Estado", "Fecha"]
        data_rows = [headers]
        for i, p in enumerate(payments, 1):
            status_text = "⚠️" if p.status == "flagged" else "✅"
            date_str = p.submitted_at.strftime("%d/%m %H:%M") if p.submitted_at else "—"
            data_rows.append([
                str(i),
                p.payer_name,
                p.child_name or "—",
                p.confirmation_code or "—",
                f"${p.amount}" if p.amount else "—",
                status_text,
                date_str,
            ])
        col_widths = [0.4 * inch, 2.0 * inch, 2.0 * inch, 1.5 * inch, 1.0 * inch, 0.6 * inch, 1.0 * inch]

    table = Table(data_rows, colWidths=col_widths)
    table.setStyle(TableStyle([
        # Header row
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#2c3e50")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, 0), 9),
        # Body rows
        ("FONTSIZE", (0, 1), (-1, -1), 8),
        ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
        # Alternating row colors
        *[
            ("BACKGROUND", (0, r), (-1, r), colors.HexColor("#f5f6fa"))
            for r in range(2, len(data_rows), 2)
        ],
        # Flagged row highlighting
        *[
            ("BACKGROUND", (0, i + 1), (-1, i + 1), colors.HexColor("#fff3cd"))
            for i, p in enumerate(payments) if p.status == "flagged"
        ],
        # Grid
        ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (-3, 0), (-1, -1), "CENTER"),
    ]))

    elements.append(table)
    elements.append(Spacer(1, 12))

    # Footer
    now = datetime.now().strftime("%d/%m/%Y %H:%M")
    elements.append(Paragraph(
        f"<i>Generado: {now} — Cuenta: {fundraiser.account_number}</i>",
        styles["Normal"],
    ))

    doc.build(elements)
    logger.info(f"Fundraiser report generated: {output_path}")
