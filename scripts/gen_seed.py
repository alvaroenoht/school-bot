#!/usr/bin/env python3
"""
Generate scripts/seed_production.sql from the pg_dump backup.
Run: python3 scripts/gen_seed.py
Writes: scripts/seed_production.sql (utf-8)
"""
import re
import sys
import io

BACKUP_PATH = "schoolbot_20260410_154833.sql"
OUTPUT_PATH = "scripts/seed_production.sql"

# Column types for proper SQL quoting.
# Unspecified columns default to 'str' (single-quoted).
COL_TYPES: dict[str, dict[str, str]] = {
    "classrooms":          {"id": "int", "is_active": "bool"},
    "parents":             {"id": "int", "classroom_id": "int", "is_active": "bool", "student_ids": "json"},
    "students":            {"id": "int", "classroom_id": "int", "parent_id": "int"},
    "subjects":            {"id": "int", "materia_id": "int", "classroom_id": "int"},
    "invite_codes":        {"id": "int", "parent_id": "int"},
    "known_contacts":      {"id": "int"},
    "known_contact_groups": {"id": "int", "classroom_id": "int", "active": "bool"},
    "fundraisers":         {"id": "int"},
    "fundraiser_products": {"id": "int", "fundraiser_id": "int", "sort_order": "int"},
    "fundraiser_subscribers": {"id": "int", "fundraiser_id": "int"},
    "payments":            {"id": "int", "fundraiser_id": "int", "confidence_score": "float"},
    "order_items":         {"id": "int", "payment_id": "int", "product_id": "int", "quantity": "int"},
    "forms":               {"id": "int", "send_group_reminders": "bool", "reminder_interval_days": "int"},
    "form_questions":      {"id": "int", "form_id": "int", "order": "int", "required": "bool", "options": "json"},
    "form_audience":       {"id": "int", "form_id": "int", "classroom_id": "int"},
    "form_submissions":    {"id": "int", "form_id": "int", "student_id": "int"},
    "form_answers":        {"id": "int", "submission_id": "int", "question_id": "int", "value_json": "json"},
    "form_readers":        {"id": "int"},
    "bot_status":          {"id": "int"},
    "assignments":         {"id": "int", "student_id": "int", "subject_id": "int"},
}

# Tables to restore in dependency order (tables not listed are skipped)
RESTORE_ORDER = [
    "classrooms",
    "parents",
    "students",
    "subjects",
    "invite_codes",
    "known_contacts",
    "known_contact_groups",
    "fundraisers",
    "fundraiser_products",
    "fundraiser_subscribers",
    "payments",
    "order_items",
    "forms",
    "form_questions",
    "form_audience",
    "form_submissions",
    "form_answers",
    "form_readers",
    "bot_status",
    "assignments",
]

# Sequence names for tables that need reset
SEQUENCES = {
    "classrooms": "classrooms_id_seq",
    "parents": "parents_id_seq",
    "students": "students_id_seq",
    "seduca_groups": "seduca_groups_id_seq",
    "classroom_seduca_links": "classroom_seduca_links_id_seq",
    "subjects": "subjects_id_seq",
    "invite_codes": "invite_codes_id_seq",
    "known_contacts": "known_contacts_id_seq",
    "known_contact_groups": "known_contact_groups_id_seq",
    "fundraisers": "fundraisers_id_seq",
    "fundraiser_products": "fundraiser_products_id_seq",
    "fundraiser_subscribers": "fundraiser_subscribers_id_seq",
    "payments": "payments_id_seq",
    "order_items": "order_items_id_seq",
    "forms": "forms_id_seq",
    "form_questions": "form_questions_id_seq",
    "form_audience": "form_audience_id_seq",
    "form_submissions": "form_submissions_id_seq",
    "form_answers": "form_answers_id_seq",
    "form_readers": "form_readers_id_seq",
    "bot_status": "bot_status_id_seq",
    "assignments": "assignments_id_seq",
}


def pg_val(raw: str, ctype: str) -> str:
    """Convert a raw backup tab-separated value to a SQL literal."""
    if raw == r"\N":
        return "NULL"
    if ctype == "int":
        return raw
    if ctype == "float":
        return raw
    if ctype == "bool":
        return "TRUE" if raw == "t" else "FALSE"
    if ctype == "json":
        # JSON values are stored verbatim in the dump — just single-quote them.
        # Use dollar-quoting to avoid escaping issues with embedded quotes.
        # We use $J$ as tag (unlikely to appear in JSON content).
        return f"$J${raw}$J$"
    # Default: text — single-quote with escaping
    escaped = raw.replace("'", "''")
    return f"'{escaped}'"


def parse_backup(path: str) -> dict[str, dict]:
    """Line-by-line COPY block parser — handles empty tables and special chars."""
    tables: dict[str, dict] = {}
    current_table: str | None = None
    current_cols: list[str] = []
    current_rows: list[list[str]] = []

    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.rstrip("\r\n")
            if line.startswith("COPY public."):
                m = re.match(r"COPY public\.(\w+) \(([^)]+)\) FROM stdin;", line)
                if m:
                    current_table = m.group(1)
                    current_cols = [c.strip().strip('"') for c in m.group(2).split(",")]
                    current_rows = []
            elif line == "\\." and current_table is not None:
                tables[current_table] = {"cols": current_cols, "rows": current_rows}
                current_table = None
            elif current_table is not None:
                current_rows.append(line.split("\t"))

    print(f"Parsed {len(tables)} tables: {', '.join(sorted(tables))}", file=sys.stderr)
    return tables


def rows_to_insert(table: str, cols: list[str], rows: list[list[str]], extra_cols: dict | None = None) -> str:
    """Generate an INSERT statement for the given rows.
    extra_cols: {col_name: sql_expr} — extra columns to append to the INSERT.
    """
    if not rows:
        return f"-- {table}: no rows\n"
    type_map = COL_TYPES.get(table, {})
    all_cols = list(cols)
    if extra_cols:
        all_cols += list(extra_cols.keys())
    col_list = ", ".join(all_cols)

    chunks = []
    batch_size = 200
    for i in range(0, len(rows), batch_size):
        batch = rows[i : i + batch_size]
        val_lines = []
        for row in batch:
            vals = [pg_val(v, type_map.get(c, "str")) for c, v in zip(cols, row)]
            if extra_cols:
                vals += list(extra_cols.values())
            val_lines.append("  (" + ", ".join(vals) + ")")
        chunks.append(
            f"INSERT INTO {table} ({col_list})\nVALUES\n"
            + ",\n".join(val_lines)
            + ";\n"
        )
    return "\n".join(chunks)


def gen_classrooms(table_data: dict) -> str:
    """Classrooms: add display_name=name, parent_id=NULL, settings='{}'."""
    cols = table_data["cols"]  # id, name, school_url, whatsapp_group_id, is_active, created_at
    rows = table_data["rows"]
    type_map = COL_TYPES.get("classrooms", {})

    new_cols = cols + ["display_name", "parent_id", "settings"]
    col_list = ", ".join(new_cols)

    chunks = []
    val_lines = []
    for row in rows:
        vals = [pg_val(v, type_map.get(c, "str")) for c, v in zip(cols, row)]
        # name is cols[1], index 1
        name_val = pg_val(row[1], "str")
        vals += [name_val, "NULL", "'{}'"]
        val_lines.append("  (" + ", ".join(vals) + ")")

    chunks.append(
        f"INSERT INTO classrooms ({col_list})\nVALUES\n"
        + ",\n".join(val_lines)
        + ";\n"
    )
    return "\n".join(chunks)


def gen_fundraisers(table_data: dict) -> str:
    """Fundraisers: add friendly_name=name, code=derived."""
    cols = table_data["cols"]
    rows = table_data["rows"]
    type_map = COL_TYPES.get("fundraisers", {})

    new_cols = cols + ["friendly_name", "code"]
    col_list = ", ".join(new_cols)

    val_lines = []
    for row in rows:
        vals = [pg_val(v, type_map.get(c, "str")) for c, v in zip(cols, row)]
        name_raw = row[1]  # name is index 1
        # Generate a code: uppercase first 10 alphanum chars
        slug = re.sub(r"[^A-Z0-9]", "", name_raw.upper())[:10] or "FUND"
        name_val = pg_val(name_raw, "str")
        code_val = f"'{slug}'"
        vals += [name_val, code_val]
        val_lines.append("  (" + ", ".join(vals) + ")")

    return (
        f"INSERT INTO fundraisers ({col_list})\nVALUES\n"
        + ",\n".join(val_lines)
        + ";\n"
    )


def gen_seduca_groups(students: dict) -> str:
    """Derive seduca_groups from students table."""
    cols = students["cols"]  # id, name, grade, classroom_id, parent_id
    rows = students["rows"]

    # seduca_groups cols: id, seduca_group_id, name, discovered_by_id, last_fetched_at, cached_data
    val_lines = []
    for i, row in enumerate(rows, start=1):
        sid = row[0]          # student.id → seduca_group_id (string)
        sname = row[1]        # student.name
        sgrade = row[2]       # student.grade
        parent_id = row[4]    # student.parent_id → discovered_by_id

        sg_name = f"{sname} - {sgrade}".strip(" -")
        sg_name_val = pg_val(sg_name, "str")
        sid_val = pg_val(sid, "str")
        parent_val = pg_val(parent_id, "int") if parent_id != r"\N" else "NULL"

        val_lines.append(
            f"  ({i}, {sid_val}, {sg_name_val}, {parent_val}, NULL, NULL)"
        )

    return (
        "INSERT INTO seduca_groups (id, seduca_group_id, name, discovered_by_id, last_fetched_at, cached_data)\nVALUES\n"
        + ",\n".join(val_lines)
        + ";\n"
    )


def gen_classroom_seduca_links(students: dict) -> str:
    """One link per classroom (first student = lowest id per classroom_id).
    Classroom 5 (2C) has students 310 and 2108 — link 310, leave 2108 unlinked.
    """
    cols = students["cols"]
    rows = students["rows"]

    # Build: classroom_id → [(student_id_int, seduca_group_row_index)]
    # seduca_group id = row index in students (1-based)
    student_index = {int(row[0]): i + 1 for i, row in enumerate(rows)}  # student_id → sg_id

    # Group by classroom_id, pick lowest student_id
    classroom_to_student: dict[int, int] = {}
    for row in rows:
        sid = int(row[0])
        cid_raw = row[3]
        if cid_raw == r"\N":
            continue
        cid = int(cid_raw)
        if cid not in classroom_to_student or sid < classroom_to_student[cid]:
            classroom_to_student[cid] = sid

    val_lines = []
    for i, (cid, sid) in enumerate(sorted(classroom_to_student.items()), start=1):
        sg_id = student_index[sid]
        val_lines.append(f"  ({i}, {cid}, {sg_id}, '07:00', TRUE, NULL)")

    return (
        "INSERT INTO classroom_seduca_links (id, classroom_id, seduca_group_id, summary_time, answer_dms, created_by_id)\nVALUES\n"
        + ",\n".join(val_lines)
        + ";\n"
    )


def sequence_resets(tables_with_data: list[str]) -> str:
    lines = []
    for t in tables_with_data:
        seq = SEQUENCES.get(t)
        if seq:
            lines.append(f"SELECT setval('{seq}', COALESCE((SELECT MAX(id) FROM {t}), 1));")
    return "\n".join(lines)


def main():
    tables = parse_backup(BACKUP_PATH)

    out = open(OUTPUT_PATH, "w", encoding="utf-8")

    out.write("-- ============================================================\n")
    out.write("-- Production seed — generated from schoolbot_20260410_154833.sql\n")
    out.write("-- Run via: ./scripts/restore.sh\n")
    out.write("-- ============================================================\n\n")

    out.write("SET session_replication_role = replica;\n\n")

    # Truncate in reverse dependency order (include derived tables)
    truncate_order = ["classroom_seduca_links", "seduca_groups"] + list(reversed(RESTORE_ORDER))
    out.write("-- Truncate all tables (reverse dep order)\n")
    for t in truncate_order:
        out.write(f"TRUNCATE {t} CASCADE;\n")
    out.write("\n")

    # Classrooms (schema adapt)
    out.write("-- classrooms\n")
    out.write(gen_classrooms(tables["classrooms"]))
    out.write("\n")

    # Parents
    out.write("-- parents\n")
    pd = tables["parents"]
    out.write(rows_to_insert("parents", pd["cols"], pd["rows"]))
    out.write("\n")

    # Students
    out.write("-- students\n")
    sd = tables["students"]
    out.write(rows_to_insert("students", sd["cols"], sd["rows"]))
    out.write("\n")

    # SeducaGroups (derived)
    out.write("-- seduca_groups (derived from students)\n")
    out.write(gen_seduca_groups(tables["students"]))
    out.write("\n")

    # ClassroomSeducaLinks (derived)
    out.write("-- classroom_seduca_links (one per classroom, first student)\n")
    out.write(gen_classroom_seduca_links(tables["students"]))
    out.write("\n")

    # Remaining tables in order
    remaining = [t for t in RESTORE_ORDER if t not in ("classrooms", "parents", "students")]
    for tname in remaining:
        td = tables.get(tname)
        if td is None:
            out.write(f"-- {tname}: not found in backup, skipping\n\n")
            continue
        out.write(f"-- {tname}\n")
        if tname == "fundraisers":
            out.write(gen_fundraisers(td))
        else:
            out.write(rows_to_insert(tname, td["cols"], td["rows"]))
        out.write("\n")

    # Sequence resets
    out.write("-- Reset sequences\n")
    all_tables = RESTORE_ORDER + ["seduca_groups", "classroom_seduca_links"]
    out.write(sequence_resets(all_tables))
    out.write("\n\n")

    out.write("SET session_replication_role = DEFAULT;\n")
    out.write("\n-- Done.\n")
    out.close()
    print(f"Written to {OUTPUT_PATH}", file=sys.stderr)


if __name__ == "__main__":
    main()
