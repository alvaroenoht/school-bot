# summary_formatter.py

import datetime
from collections import defaultdict

emoji_day_prefix = {
    'Monday': '🟦', 'Tuesday': '🟩', 'Wednesday': '🟨',
    'Thursday': '🟧', 'Friday': '🟥', 'Saturday': '⭐', 'Sunday': '🌞'
}

days_es = {
    'Monday': 'Lunes', 'Tuesday': 'Martes', 'Wednesday': 'Miércoles',
    'Thursday': 'Jueves', 'Friday': 'Viernes', 'Saturday': 'Sábado', 'Sunday': 'Domingo'
}
months_es = {
    'January': 'enero', 'February': 'febrero', 'March': 'marzo', 'April': 'abril',
    'May': 'mayo', 'June': 'junio', 'July': 'julio', 'August': 'agosto',
    'September': 'septiembre', 'October': 'octubre', 'November': 'noviembre', 'December': 'diciembre'
}

def translate_date(date_obj):
    day_emoji = emoji_day_prefix[date_obj.strftime('%A')]
    day_name = days_es[date_obj.strftime('%A')]
    month_name = months_es[date_obj.strftime('%B')]
    #return f"{day_name} {date_obj.strftime('%d')}"
    return f"{day_name} {date_obj.strftime('%d')} de {month_name}"

def generate_weekly_summary(conn, student_id, start, end):
    cursor = conn.cursor()
    # Get student's name
    cursor.execute("SELECT grade FROM students WHERE id = ?", (student_id,))
    row = cursor.fetchone()
    student_name = row[0] if row else "Grado"

    # Format week range
    month_span = months_es[end.strftime('%B')]
    week_range = f"📆  {start.strftime('%d')} al {end.strftime('%d')} de {month_span} {end.strftime('%Y')}"

    # Fetch all subjects and emojis
    cursor.execute("SELECT materia_id, name, icon FROM subjects")
    subject_map = {row[0]: (row[2], row[1]) for row in cursor.fetchall()}

    # Fetch all assignments for the student in the range
    #print(start.isoformat())
    #print(end.isoformat())

    cursor.execute('''
        SELECT title, subject_id, type, date, created_at, materials, summary, short_url
        FROM assignments
        WHERE student_id = ? AND date BETWEEN ? AND ?
        ORDER BY date
    ''', (student_id, start.isoformat(), end.isoformat()))

    sumativas_by_day = defaultdict(list)
    materiales_by_day = defaultdict(list)

    for row in cursor.fetchall():
        title, subject_id, type_, date_str, created_at, materials, summary, short_url = row
        #date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        #day_str = f"{date_obj.strftime('%A').capitalize()} {date_obj.strftime('%d %B')}"
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        day_str = translate_date(date_obj)
        emoji, subject_name = subject_map.get(subject_id, ("📘", subject_id))
        title = title.strip()
        link_text = f"{short_url}" if short_url else ""

        if "Sumativa" in type_:
            bag = "🎒" if materials else ""
            sumativas_by_day[day_str].append(f"► {emoji} {subject_name}\n> {title}: {summary} {bag} {link_text}")
        if materials:
            materiales_by_day[day_str].append(f"{materials}. _- {subject_name}_ {link_text}")

    lines = [f"{week_range}\n"]

    if sumativas_by_day:
        lines.append("💯 *S U M A T I V A S* 💯")
        for day, items in sumativas_by_day.items():
            lines.append(f"*{day}*")
            for item in items:
                lines.append(f"{item}")
        lines.append("\n")

    if materiales_by_day:
        lines.append("🎒 *M A T E R I A L E S* 🎒")
        for day, items in materiales_by_day.items():
            lines.append(f"*{day}*")
            for item in items:
                lines.append(f"- {item}")
        lines.append("")

    return "\n".join(lines) if sumativas_by_day or materiales_by_day else None

def generate_weekly_data(conn, student_id, start, end):
    cursor = conn.cursor()

    # Fetch all subjects and emojis
    cursor.execute("SELECT materia_id, name FROM subjects")
    subject_map = {row[0]: row[1] for row in cursor.fetchall()}

    # Fetch all assignments for the student in the range
    cursor.execute('''
        SELECT title, subject_id, type, date, materials, summary
        FROM assignments
        WHERE student_id = ? AND date BETWEEN ? AND ?
        ORDER BY date
    ''', (student_id, start.isoformat(), end.isoformat()))

    data_by_day = {
        'Monday': {'sumativas': [], 'materials': []},
        'Tuesday': {'sumativas': [], 'materials': []},
        'Wednesday': {'sumativas': [], 'materials': []},
        'Thursday': {'sumativas': [], 'materials': []},
        'Friday': {'sumativas': [], 'materials': []}
    }

    for row in cursor.fetchall():
        title, subject_id, type_, date_str, materials, summary = row
        date_obj = datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
        day_name = date_obj.strftime('%A')

        subject_name = subject_map.get(subject_id, str(subject_id))

        if "Sumativa" in type_:
            data_by_day[day_name]['sumativas'].append({
                'subject': subject_name,
                'title': title,
                'summary': summary
            })

        if materials:
            materials_list = [m.strip() for m in materials.split(",") if m.strip()]
            data_by_day[day_name]['materials'].extend(materials_list)

    return data_by_day
