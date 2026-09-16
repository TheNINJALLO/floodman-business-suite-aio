-- MANUAL ROLLBACK ONLY. Back up the floodman database and stop the orchestrator first.
-- This removes call-intake receipts and canonical links and is intentionally never run by startup.

BEGIN;
DROP TABLE IF EXISTS call_intake_events;
DROP TABLE IF EXISTS call_intakes;
DELETE FROM floodman_schema_migrations WHERE version='005';
COMMIT;
