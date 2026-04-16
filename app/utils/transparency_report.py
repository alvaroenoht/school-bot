"""
Transparency PDF generator for group-fund fundraisers.

Aggregate view only — individual contributors are never listed.
Grouped by activity; each expense shows its receipt thumbnails inline.

Generated PDF is uploaded to S3 and also saved to a temp file so callers
can attach it via WhatsApp send_document.
"""
from __future__ import annotations

import io
import logging
import os
import tempfile
from datetime import datetime
from typing import Optional

import requests
from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Image, PageBreak, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)
from sqlalchemy.orm import Session

from app.db import models
from app.utils.s3_upload import generate_presigned_url, upload_file_to_s3

logger = logging.getLogger(__name__)

THUMB_MAX_CM = 5.0  # max edge length for inline receipt images


def _styles():
    base = getSampleStyleSheet()
    return {
        "title":    ParagraphStyle("title",    parent=base["Title"], fontSize=18, leading=22, alignment=TA_CENTER, textColor=colors.HexColor("#1F2937")),
        "subtitle": ParagraphStyle("subtitle", parent=base["Normal"], fontSize=10, alignment=TA_CENTER, textColor=colors.HexColor("#6B7280"), spaceAfter=14),
        "h2":       ParagraphStyle("h2",       parent=base["Heading2"], fontSize=13, leading=16, textColor=colors.HexColor("#4338CA"), spaceBefore=10, spaceAfter=6),
        "h3":       ParagraphStyle("h3",       parent=base["Heading3"], fontSize=11, leading=14, textColor=colors.HexColor("#111827"), spaceBefore=6, spaceAfter=4),
        "body":     ParagraphStyle("body",     parent=base["Normal"],   fontSize=9,  leading=12, textColor=colors.HexColor("#1F2937")),
        "mono":     ParagraphStyle("mono",     parent=base["Normal"],   fontSize=9,  leading=12, textColor=colors.HexColor("#374151"), fontName="Helvetica-Oblique"),
        "footer":   ParagraphStyle("footer",   parent=base["Normal"],   fontSize=8,  leading=11, alignment=TA_CENTER, textColor=colors.HexColor("#9CA3AF")),
        "right":    ParagraphStyle("right",    parent=base["Normal"],   fontSize=9,  leading=12, alignment=TA_RIGHT),
    }


def _fetch_image_bytes(url: str) -> Optional[bytes]:
    try:
        r = requests.get(url, timeout=20)
        if r.status_code == 200 and r.content:
            return r.content
    except requests.RequestException as e:
        logger.warning("transparency: failed to fetch receipt image %s: %s", url, e)
    return None


def _fund_totals(fund: models.Fundraiser) -> tuple[float, float, int, float, int]:
    """Return (total, payment_count, contributors, manual_total, manual_count).
    Voided payments are always excluded from totals.
    """
    confirmed = [
        p for p in fund.payments
        if p.status == "confirmed" and p.voided_at is None
    ]
    total = sum(float(p.amount or 0) for p in confirmed)
    contributors = len({p.payer_jid for p in confirmed if p.payer_jid})
    manual = [p for p in confirmed if p.entry_method == "manual"]
    manual_total = sum(float(p.amount or 0) for p in manual)
    return round(total, 2), len(confirmed), contributors, round(manual_total, 2), len(manual)


def _activity_total(activity: models.FundraiserActivity) -> float:
    return sum(float(e.amount or 0) for e in activity.expenses)


def _build_pdf(fund: models.Fundraiser, db: Session, out_path: str) -> None:
    styles = _styles()
    doc = SimpleDocTemplate(
        out_path, pagesize=letter,
        leftMargin=1.8 * cm, rightMargin=1.8 * cm,
        topMargin=1.8 * cm, bottomMargin=1.8 * cm,
        title=f"Reporte de transparencia — {fund.name}",
    )
    story: list = []

    # Header
    story.append(Paragraph(f"Reporte de transparencia", styles["title"]))
    story.append(Paragraph(f"{fund.name}", styles["subtitle"]))

    # Summary totals
    total_collected, payment_count, contributors, manual_total, manual_count = _fund_totals(fund)
    activities = sorted(
        fund.activities,
        key=lambda a: (a.occurred_on or a.created_at.date()),
        reverse=True,
    )
    total_spent = round(sum(_activity_total(a) for a in activities), 2)
    balance = round(total_collected - total_spent, 2)

    summary_data = [
        ["Recaudado", f"${total_collected:,.2f}"],
        ["Gastado",   f"${total_spent:,.2f}"],
        ["Saldo",     f"${balance:,.2f}"],
        ["Contribuyentes",  str(contributors)],
        ["Pagos registrados", str(payment_count)],
    ]
    if manual_count:
        summary_data.append([
            "Ingresos manuales",
            f"${manual_total:,.2f} ({manual_count})",
        ])
    summary_data += [
        ["Actividades",       str(len(activities))],
        ["Fecha del reporte", datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")],
    ]
    summary_tbl = Table(summary_data, colWidths=[5.5 * cm, 5.5 * cm], hAlign="CENTER")
    summary_tbl.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#F3F4F6")),
        ("TEXTCOLOR",  (0, 0), (0, -1), colors.HexColor("#4B5563")),
        ("FONTNAME",   (0, 0), (0, -1), "Helvetica-Bold"),
        ("FONTNAME",   (1, 0), (1, -1), "Helvetica-Bold"),
        ("FONTSIZE",   (0, 0), (-1, -1), 10),
        ("ALIGN",      (1, 0), (1, -1), "RIGHT"),
        ("VALIGN",     (0, 0), (-1, -1), "MIDDLE"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING",    (0, 0), (-1, -1), 6),
        ("LINEBELOW",  (0, 0), (-1, -2), 0.3, colors.HexColor("#E5E7EB")),
    ]))
    story.append(summary_tbl)
    story.append(Spacer(1, 0.5 * cm))

    # Privacy note
    story.append(Paragraph(
        "Por privacidad, los aportes individuales de cada padre no se publican. "
        "Los totales mostrados son agregados de todos los pagos confirmados.",
        styles["mono"],
    ))
    story.append(Spacer(1, 0.6 * cm))

    # Activities section
    if not activities:
        story.append(Paragraph("Sin actividades registradas.", styles["body"]))
    else:
        story.append(Paragraph("Detalle por actividad", styles["h2"]))

    for activity in activities:
        expenses = list(activity.expenses)
        activity_total = _activity_total(activity)
        date_label = activity.occurred_on.strftime("%Y-%m-%d") if activity.occurred_on else activity.created_at.strftime("%Y-%m-%d")
        story.append(Paragraph(
            f"{activity.name} — <font color='#6B7280'>{date_label}</font> — "
            f"<font color='#B45309'>${activity_total:,.2f}</font>",
            styles["h3"],
        ))
        if activity.description:
            story.append(Paragraph(activity.description, styles["body"]))
            story.append(Spacer(1, 0.15 * cm))

        if not expenses:
            story.append(Paragraph("Sin gastos registrados en esta actividad.", styles["mono"]))
            story.append(Spacer(1, 0.3 * cm))
            continue

        for expense in expenses:
            try:
                amount_val = float(expense.amount or 0)
            except (TypeError, ValueError):
                amount_val = 0.0

            header_line = (
                f"<b>{expense.title}</b> &nbsp;·&nbsp; "
                f"<font color='#B45309'><b>${amount_val:,.2f}</b></font>"
            )
            if expense.spent_on:
                header_line += f" &nbsp;·&nbsp; <font color='#6B7280'>{expense.spent_on.isoformat()}</font>"
            story.append(Paragraph(header_line, styles["body"]))
            if expense.note:
                story.append(Paragraph(f"<i>{expense.note}</i>", styles["mono"]))

            # Receipt thumbnails
            image_cells: list = []
            for receipt in expense.receipts:
                if (receipt.content_type or "").lower().startswith("image/"):
                    url = generate_presigned_url(receipt.s3_key)
                    data = _fetch_image_bytes(url)
                    if not data:
                        continue
                    try:
                        img = Image(io.BytesIO(data))
                        # Scale to fit THUMB_MAX_CM on longest edge
                        iw, ih = img.imageWidth, img.imageHeight
                        if iw and ih:
                            scale = min(
                                (THUMB_MAX_CM * cm) / iw,
                                (THUMB_MAX_CM * cm) / ih,
                            )
                            img.drawWidth = iw * scale
                            img.drawHeight = ih * scale
                        image_cells.append(img)
                    except Exception as e:
                        logger.warning("transparency: failed to embed receipt image: %s", e)
                else:
                    label = receipt.filename or "comprobante.pdf"
                    image_cells.append(Paragraph(f"📄 {label}", styles["mono"]))

            if image_cells:
                cols = 3
                rows: list[list] = []
                for i in range(0, len(image_cells), cols):
                    row = image_cells[i : i + cols]
                    while len(row) < cols:
                        row.append("")
                    rows.append(row)
                tbl = Table(rows, colWidths=[(THUMB_MAX_CM + 0.5) * cm] * cols, hAlign="LEFT")
                tbl.setStyle(TableStyle([
                    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
                    ("ALIGN",  (0, 0), (-1, -1), "LEFT"),
                    ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
                    ("TOPPADDING",    (0, 0), (-1, -1), 4),
                ]))
                story.append(Spacer(1, 0.15 * cm))
                story.append(tbl)

            story.append(Spacer(1, 0.35 * cm))

    # Footer
    story.append(Spacer(1, 0.8 * cm))
    story.append(Paragraph(
        "Para auditar los comprobantes originales contacta al delegado del grupo. "
        "Este reporte se genera automáticamente a partir de los pagos confirmados y los gastos registrados en la plataforma.",
        styles["footer"],
    ))

    doc.build(story)


def build_transparency_pdf(fund: models.Fundraiser, db: Session) -> str:
    """Build PDF, upload to S3, return (local_temp_path, s3_presigned_url).
    The caller is responsible for deleting the returned temp file.
    """
    ts = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    tmp = tempfile.NamedTemporaryFile(suffix=".pdf", delete=False)
    tmp_path = tmp.name
    tmp.close()

    try:
        _build_pdf(fund, db, tmp_path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise

    s3_key = f"transparency_reports/{fund.id}/{ts}.pdf"
    try:
        upload_file_to_s3(tmp_path, s3_key)
    except Exception as e:
        logger.warning("transparency: failed to upload PDF to S3: %s", e)

    return tmp_path
