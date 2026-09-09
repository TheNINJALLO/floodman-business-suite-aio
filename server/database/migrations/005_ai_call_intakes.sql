-- 005_ai_call_intakes.sql
-- Durable, provider-neutral incoming AI call intake and replay ledger.
-- Idempotent and safe to run repeatedly after the v3.0.0 fixed baseline.

BEGIN;

CREATE TABLE IF NOT EXISTS floodman_schema_migrations (
    version text PRIMARY KEY,
    description text NOT NULL,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS call_intakes (
    id uuid PRIMARY KEY,
    organization_id text NOT NULL,
    workspace_id text NOT NULL,
    provider text NOT NULL,
    provider_call_id text NOT NULL,
    status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','COMPLETED','REVIEW_REQUIRED')),
    review_status text NOT NULL DEFAULT 'PENDING' CHECK (review_status IN ('PENDING','PROJECTED','REVIEW_REQUIRED')),
    last_event_type text NOT NULL CHECK (last_event_type IN (
        'call-started','caller-identified','transcript-updated','call-ended','call-failed'
    )),
    last_sequence bigint NOT NULL CHECK (last_sequence >= 0),
    caller jsonb NOT NULL DEFAULT '{}'::jsonb,
    property jsonb NOT NULL DEFAULT '{}'::jsonb,
    service_reason text NOT NULL DEFAULT '',
    summary text NOT NULL DEFAULT '',
    requested_services jsonb NOT NULL DEFAULT '[]'::jsonb,
    urgency text NOT NULL DEFAULT 'NORMAL' CHECK (urgency IN ('NORMAL','PRIORITY','URGENT','EMERGENCY')),
    appointment jsonb NOT NULL DEFAULT '{}'::jsonb,
    consent jsonb NOT NULL DEFAULT '{}'::jsonb,
    transcript_available boolean NOT NULL DEFAULT false,
    transcript_reference text NOT NULL DEFAULT '',
    failure_reason text NOT NULL DEFAULT '',
    review_reasons jsonb NOT NULL DEFAULT '[]'::jsonb,
    proposed_ids jsonb NOT NULL,
    customer_id text,
    property_id text,
    job_id text,
    roomflow_job_id text,
    estimate_id text,
    note_id text,
    task_id text,
    appointment_id text,
    gauzy_contact_id text,
    gauzy_project_id text,
    gauzy_sync_status text NOT NULL DEFAULT 'PENDING' CHECK (gauzy_sync_status IN ('PENDING','SYNCED','REVIEW_REQUIRED','FAILED')),
    gauzy_sync_error text,
    projection_status text NOT NULL DEFAULT 'PENDING' CHECK (projection_status IN ('PENDING','PROJECTED','REVIEW_REQUIRED','FAILED')),
    projection_error text,
    projection_result jsonb NOT NULL DEFAULT '{}'::jsonb,
    started_at timestamptz,
    ended_at timestamptz,
    last_event_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_call_id)
);

CREATE INDEX IF NOT EXISTS call_intakes_workspace_updated_idx
    ON call_intakes (workspace_id, updated_at DESC);
CREATE INDEX IF NOT EXISTS call_intakes_review_idx
    ON call_intakes (review_status, updated_at DESC)
    WHERE review_status='REVIEW_REQUIRED';
ALTER TABLE call_intakes ADD COLUMN IF NOT EXISTS appointment_id text;
ALTER TABLE call_intakes ADD COLUMN IF NOT EXISTS note_id text;

CREATE TABLE IF NOT EXISTS call_intake_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    intake_id uuid REFERENCES call_intakes(id) ON DELETE RESTRICT,
    provider text NOT NULL,
    provider_call_id text NOT NULL,
    provider_event_id text NOT NULL,
    source_event_id text NOT NULL,
    event_type text NOT NULL CHECK (event_type IN (
        'call-started','caller-identified','transcript-updated','call-ended','call-failed'
    )),
    event_sequence bigint NOT NULL CHECK (event_sequence >= 0),
    organization_id text NOT NULL,
    workspace_id text NOT NULL,
    payload_sha256 char(64) NOT NULL,
    status text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED','PROCESSED','IGNORED','FAILED')),
    error text,
    occurred_at timestamptz NOT NULL,
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    UNIQUE (provider, provider_event_id),
    UNIQUE (provider, provider_call_id, event_type, event_sequence)
);

CREATE INDEX IF NOT EXISTS call_intake_events_call_idx
    ON call_intake_events (provider, provider_call_id, event_sequence);

DROP TRIGGER IF EXISTS call_intakes_set_updated_at ON call_intakes;
CREATE TRIGGER call_intakes_set_updated_at BEFORE UPDATE ON call_intakes
FOR EACH ROW EXECUTE FUNCTION set_updated_at();

INSERT INTO floodman_schema_migrations(version, description)
VALUES ('005', 'Provider-neutral AI call intake, replay ledger, and canonical record links')
ON CONFLICT (version) DO NOTHING;

COMMIT;
