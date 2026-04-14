-- Calendar Events Module migration
-- Idempotent: safe to run multiple times.
-- Run on prod: docker compose exec -T db psql -U $POSTGRES_USER $POSTGRES_DB < scripts/migrate_events_module.sql

BEGIN;

-- Event enrichment
ALTER TABLE events ADD COLUMN IF NOT EXISTS type VARCHAR NOT NULL DEFAULT 'general';
ALTER TABLE events ADD COLUMN IF NOT EXISTS student_id INTEGER REFERENCES students(id);
ALTER TABLE events ADD COLUMN IF NOT EXISTS notified_day_before BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE events ADD COLUMN IF NOT EXISTS notified_day_of BOOLEAN NOT NULL DEFAULT FALSE;

-- Student birthdate
ALTER TABLE students ADD COLUMN IF NOT EXISTS birth_date DATE;

-- Drop orphaned CalendarSubscription table (model deleted in commit d21116c)
DROP TABLE IF EXISTS calendar_subscriptions;

COMMIT;
