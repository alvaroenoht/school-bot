"""Mint a long-lived, read-only dashboard token for the SEDUCA iPad kiosk.

Fallback for when you'd rather not use the admin-panel UI. Needs the DB
reachable (run from the repo root with DATABASE_URL set, or copy into the
schoolbot container). Not baked into the Docker image.

Examples:
    python -m scripts.mint_dashboard_token --label "iPad cocina" --students 2036,7505
    python -m scripts.mint_dashboard_token --label "iPad" --phone 50761234567
    python -m scripts.mint_dashboard_token --students 2036 --days 0   # never expires
"""
import argparse
import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.db import models
from app.db.database import SessionLocal
from app.utils.dashboard_tokens import build_dashboard_path, new_token
from app.utils.jid_utils import find_parent_by_jid


def main() -> int:
    ap = argparse.ArgumentParser(description="Mint a dashboard kiosk token.")
    ap.add_argument("--label", default=None, help='e.g. "iPad cocina"')
    ap.add_argument("--students", default=None, help="comma-separated student ids (scope)")
    ap.add_argument("--phone", default=None, help="scope = this parent's children (no + or spaces)")
    ap.add_argument("--days", type=int, default=365, help="expiry in days (0 = never)")
    args = ap.parse_args()

    db = SessionLocal()
    try:
        student_ids = None
        if args.students:
            student_ids = [int(x) for x in args.students.split(",") if x.strip()]
        elif args.phone:
            parent = find_parent_by_jid(db, args.phone + "@c.us", None, require_active=False)
            student_ids = parent.student_ids if parent else None

        if not student_ids:
            print("ERROR: provide --students, or a --phone whose parent has children.", file=sys.stderr)
            return 2

        expires_at = None if args.days == 0 else datetime.utcnow() + timedelta(days=args.days)
        tok = models.DashboardToken(
            token=new_token(),
            label=args.label,
            student_ids=student_ids,
            created_by_jid="cli",
            expires_at=expires_at,
        )
        db.add(tok)
        db.commit()
        db.refresh(tok)

        print("Token id:        ", tok.id)
        print("Scope students:  ", student_ids)
        print("Expires:         ", tok.expires_at or "never")
        print("Path:            " + build_dashboard_path(tok.token))
        print("Open on iPad:    https://YOUR-DOMAIN" + build_dashboard_path(tok.token))
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    raise SystemExit(main())
