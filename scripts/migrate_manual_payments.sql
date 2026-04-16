-- Manual payments + audit trail (Phase 2)
-- Idempotent: safe to run multiple times.
-- Run: docker compose exec -T postgres psql -U $POSTGRES_USER $POSTGRES_DB < scripts/migrate_manual_payments.sql

BEGIN;

-- Payment trust/void metadata
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS entry_method        VARCHAR NOT NULL DEFAULT 'receipt';
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS recorded_by_jid     VARCHAR;
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS method_note         TEXT;
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS manual_proof_url    VARCHAR;
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS manual_proof_s3_key VARCHAR;
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS voided_at           TIMESTAMP;
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS voided_by_jid       VARCHAR;
ALTER TABLE payments
  ADD COLUMN IF NOT EXISTS void_reason         TEXT;

-- Append-only audit table
CREATE TABLE IF NOT EXISTS payment_audit (
    id          SERIAL PRIMARY KEY,
    payment_id  INTEGER NOT NULL REFERENCES payments(id) ON DELETE CASCADE,
    action      VARCHAR NOT NULL,
    actor_jid   VARCHAR NOT NULL,
    snapshot    JSONB NOT NULL,
    at          TIMESTAMP NOT NULL DEFAULT (NOW() AT TIME ZONE 'utc')
);
CREATE INDEX IF NOT EXISTS ix_payment_audit_payment_id ON payment_audit(payment_id);

COMMIT;
