-- Group-fund fundraiser mode + activities/expenses/receipts (Phase 1)
-- Idempotent: safe to run multiple times.
-- Run on prod: docker compose exec -T postgres psql -U $POSTGRES_USER $POSTGRES_DB < scripts/migrate_group_fund.sql

BEGIN;

-- Fundraiser: mode + transparency toggle
ALTER TABLE fundraisers
  ADD COLUMN IF NOT EXISTS mode VARCHAR NOT NULL DEFAULT 'campaign';
ALTER TABLE fundraisers
  ADD COLUMN IF NOT EXISTS transparency_enabled BOOLEAN NOT NULL DEFAULT FALSE;

-- Activities under a fundraiser (group-fund mode)
CREATE TABLE IF NOT EXISTS fundraiser_activities (
    id              SERIAL PRIMARY KEY,
    fundraiser_id   INTEGER NOT NULL REFERENCES fundraisers(id) ON DELETE CASCADE,
    name            VARCHAR NOT NULL,
    description     TEXT,
    occurred_on     DATE,
    created_by_jid  VARCHAR NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS ix_fundraiser_activities_fundraiser_id
    ON fundraiser_activities(fundraiser_id);

-- Expense line items within an activity
CREATE TABLE IF NOT EXISTS fundraiser_expenses (
    id              SERIAL PRIMARY KEY,
    activity_id     INTEGER NOT NULL REFERENCES fundraiser_activities(id) ON DELETE CASCADE,
    title           VARCHAR NOT NULL,
    amount          VARCHAR NOT NULL,
    spent_on        DATE,
    note            TEXT,
    created_by_jid  VARCHAR NOT NULL,
    created_at      TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS ix_fundraiser_expenses_activity_id
    ON fundraiser_expenses(activity_id);

-- Receipts (proof files) attached to an expense
CREATE TABLE IF NOT EXISTS expense_receipts (
    id              SERIAL PRIMARY KEY,
    expense_id      INTEGER NOT NULL REFERENCES fundraiser_expenses(id) ON DELETE CASCADE,
    media_url       VARCHAR NOT NULL,
    s3_key          VARCHAR NOT NULL,
    filename        VARCHAR,
    content_type    VARCHAR,
    size_bytes      INTEGER,
    uploaded_by_jid VARCHAR NOT NULL,
    uploaded_at     TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS ix_expense_receipts_expense_id
    ON expense_receipts(expense_id);

COMMIT;
