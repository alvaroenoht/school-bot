#!/usr/bin/env bash
# Restore production seed data into the running postgres container.
# Usage: ./scripts/restore.sh
# Prerequisites: docker compose up -d postgres
set -e
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
SEED="$SCRIPT_DIR/seed_production.sql"

if [ ! -f "$SEED" ]; then
  echo "ERROR: seed_production.sql not found at $SEED"
  echo "Run: python3 scripts/gen_seed.py  (from the project root)"
  exit 1
fi

echo "Running seed (this may take a moment)..."
docker compose exec -T postgres psql -U schoolbot -d schoolbot < "$SEED"

echo ""
echo "Done. Verify:"
docker compose exec postgres psql -U schoolbot -d schoolbot -c \
  "SELECT 'classrooms' AS t, COUNT(*) FROM classrooms
   UNION ALL SELECT 'parents', COUNT(*) FROM parents
   UNION ALL SELECT 'students', COUNT(*) FROM students
   UNION ALL SELECT 'seduca_groups', COUNT(*) FROM seduca_groups
   UNION ALL SELECT 'classroom_seduca_links', COUNT(*) FROM classroom_seduca_links
   UNION ALL SELECT 'payments', COUNT(*) FROM payments
   UNION ALL SELECT 'form_submissions', COUNT(*) FROM form_submissions
   UNION ALL SELECT 'known_contacts', COUNT(*) FROM known_contacts
   UNION ALL SELECT 'assignments', COUNT(*) FROM assignments;"
