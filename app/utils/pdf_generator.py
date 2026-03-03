from reportlab.lib.pagesizes import letter, landscape
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Flowable, Spacer
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase import pdfmetrics
from reportlab.platypus import KeepTogether
import os
from datetime import datetime

# Register the font
font_path = os.path.join(os.path.dirname(__file__), "fonts", "LexendDeca-Regular.ttf")
pdfmetrics.registerFont(TTFont("LexendDeca", font_path))

class Checkbox(Flowable):
    def __init__(self, size=8):
        Flowable.__init__(self)
        self.size = size
        self.width = size
        self.height = size

    def draw(self):
        self.canv.setLineWidth(0.5)
        self.canv.rect(0, 0, self.size, self.size)

def create_weekly_pdf(data_by_day, output_path, week_dates):
    doc = SimpleDocTemplate(output_path, pagesize=landscape(letter), leftMargin=22, rightMargin=22, topMargin=22, bottomMargin=22)
    elements = []
    styles = getSampleStyleSheet()

    # Define styles
    title_style = ParagraphStyle('Title', parent=styles['Heading1'], fontName='LexendDeca', fontSize=20, textColor=colors.black, alignment=1)
    header_style = ParagraphStyle('Header', parent=styles['Heading2'], fontName='LexendDeca', fontSize=14, textColor=colors.white, alignment=1)
    cell_style = ParagraphStyle('Cell', parent=styles['Normal'], fontName='LexendDeca', fontSize=9, textColor=colors.black, leading=9)
    uniform_style = ParagraphStyle('Uniform', parent=styles['Normal'], fontName='LexendDeca', fontSize=9, textColor=colors.black)

    # Create title
    first_day = week_dates[0].strftime("%d/%m")
    last_day = week_dates[-1].strftime("%d/%m")
    title_text = f"Semana del {first_day} al {last_day}"
    elements.append(Paragraph(title_text, title_style))
    elements.append(Spacer(1, 12))  # Add some space after title

    # Define headers
    headers = []
    header_colors = ["#a4243b", "#d8c99b", "#d8973c", "#bd632f", "#273e47"]
    for i, day in enumerate(["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]):
        date_str = week_dates[i].strftime("%d")
        headers.append(f"{day} {date_str}")

    english_to_spanish = {
        "Monday": "Lunes",
        "Tuesday": "Martes",
        "Wednesday": "Miercoles",
        "Thursday": "Jueves",
        "Friday": "Viernes"
    }

    # Prepare table data
    sumativas_row = []
    spacer_row = [Paragraph("<br/>", cell_style) for _ in headers]
    materials_row = []
    uniform_row = []

    UNIFORMS = {
        "Lunes": "Camisa blanca y pantalon gris",
        "Martes": "Polo blanco",
        "Miercoles": "Traje tipico",
        "Jueves": "Polo blanco",
        "Viernes": "Educacion Fisica"
    }

    # Calculate column widths
    usable_width = landscape(letter)[0] - doc.leftMargin - doc.rightMargin
    main_col_width = usable_width / 5
    min_col_width = 50  # Minimum width to prevent negative availWidth

    for idx, day in enumerate(["Lunes", "Martes", "Miercoles", "Jueves", "Viernes"]):
        eng_day = [k for k, v in english_to_spanish.items() if v == day][0]
        entries = data_by_day.get(eng_day, {}).get('sumativas', [])
        text = "<br/>".join([f"<font size='10'><b>{s['subject']}</b>: {s['title']}</font><br/><font size='8' color='#4f5d75'>{s['summary']}</font><br/>" for s in entries]) or "-"
        sumativas_row.append(Paragraph(text, cell_style))

        items = data_by_day.get(eng_day, {}).get('materials', [])
        if items:
            rows = []
            for m in items:
                safe_text = str(m).strip() if m else "-"
                rows.append([Checkbox(), Paragraph(safe_text, cell_style)])

            # Ensure inner table width is sufficient
            text_col_width = max(main_col_width - 20, min_col_width)  # Adjusted to account for padding
            inner_table = Table(
                rows,
                colWidths=[10, text_col_width],  # Checkbox width fixed at 10
                style=TableStyle([
                    ('VALIGN', (0, 0), (-1, -1), 'TOP'),
                    ('LEFTPADDING', (0, 0), (-1, -1), 2),
                    ('RIGHTPADDING', (0, 0), (-1, -1), 2),
                    ('TOPPADDING', (0, 0), (-1, -1), 2),
                    ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
                ])
            )
            materials_row.append(inner_table)
        else:
            materials_row.append(Paragraph("-", cell_style))

        uniform_row.append(Paragraph(UNIFORMS.get(day, "-"), uniform_style))

    # Create main table
    table_data = [headers, sumativas_row, spacer_row, materials_row, uniform_row]
    t = Table(table_data, colWidths=[main_col_width] * 5)
    t.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (0, 0), colors.HexColor(header_colors[0])),
        ('BACKGROUND', (1, 0), (1, 0), colors.HexColor(header_colors[1])),
        ('BACKGROUND', (2, 0), (2, 0), colors.HexColor(header_colors[2])),
        ('BACKGROUND', (3, 0), (3, 0), colors.HexColor(header_colors[3])),
        ('BACKGROUND', (4, 0), (4, 0), colors.HexColor(header_colors[4])),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('FONTNAME', (0, 0), (-1, -1), 'LexendDeca'),
        ('FONTSIZE', (0, 0), (-1, -1), 9),
        ('VALIGN', (0, 0), (-1, -1), 'TOP'),
        ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
        ('LINEBEFORE', (1, 0), (-1, -1), 0.5, colors.darkgrey),
        ('LINEAFTER', (0, 0), (-2, -1), 0.5, colors.darkgrey),
        ('INNERGRID', (0, 0), (-1, -1), 0, colors.white),
        ('BOX', (0, 0), (-1, -1), 0, colors.white),
        ('LEFTPADDING', (0, 0), (-1, -1), 5),
        ('RIGHTPADDING', (0, 0), (-1, -1), 5),
        ('TOPPADDING', (0, 0), (-1, -1), 5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 5),
    ]))

    elements.append(t)
    doc.build(elements)
