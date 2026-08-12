-- Floodman Business Suite v3.0.0 fresh-install baseline.
-- This file is executed only by the official PostgreSQL image when the new data volume is empty.
-- There is no runtime application migration container in v3.

-- -----------------------------------------------------------------------------
-- Imported baseline section: 001_core.sql
-- -----------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS workflow_jobs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id text NOT NULL,
    roomflow_job_id text NOT NULL,
    roomflow_estimate_id text NOT NULL,
    revision integer NOT NULL CHECK (revision >= 1),
    state text NOT NULL DEFAULT 'QUEUED' CHECK (state IN (
        'DRAFT','QUEUED','ESTIMATE_SYNCED','AUTHORIZATION_SENT','AUTHORIZATION_SIGNED',
        'DEPOSIT_PUBLISHED','DEPOSIT_PAID','IN_PROGRESS','CHANGE_ORDER_PENDING',
        'COMPLETION_SENT','COMPLETION_SIGNED','FINAL_PAYMENT_DUE','PAID','CLOSED',
        'PAYMENT_REVIEW','FAILED'
    )),
    customer jsonb NOT NULL,
    property jsonb NOT NULL,
    estimate jsonb NOT NULL,
    invoice_number integer NOT NULL,
    total_cents bigint NOT NULL CHECK (total_cents > 0),
    deposit_cents bigint NOT NULL CHECK (deposit_cents >= 0 AND deposit_cents <= total_cents),
    currency char(3) NOT NULL DEFAULT 'USD',
    gauzy_contact_id text,
    gauzy_estimate_id text,
    gauzy_invoice_id text,
    square_customer_id text,
    square_order_id text,
    square_invoice_id text,
    square_invoice_version integer,
    square_public_url text,
    portal_token_version integer NOT NULL DEFAULT 1,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, roomflow_job_id)
);

CREATE INDEX IF NOT EXISTS workflow_jobs_state_idx ON workflow_jobs (state, updated_at);
CREATE INDEX IF NOT EXISTS workflow_jobs_square_invoice_idx ON workflow_jobs (square_invoice_id) WHERE square_invoice_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS workflow_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    kind text NOT NULL CHECK (kind IN ('WORK_AUTHORIZATION','CHANGE_ORDER','COMPLETION_OF_SERVICE')),
    revision integer NOT NULL CHECK (revision >= 1),
    status text NOT NULL CHECK (status IN ('QUEUED','DRAFT','PENDING','COMPLETED','REJECTED','CANCELLED','FAILED')),
    source_url text,
    source_pdf_sha256 char(64),
    signed_pdf_sha256 char(64),
    stored_path text,
    documenso_envelope_id text UNIQUE,
    documenso_item_ids jsonb NOT NULL DEFAULT '[]'::jsonb,
    signing_url text,
    recipient_email text NOT NULL,
    recipient_name text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    completed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (job_id, kind, revision)
);

CREATE INDEX IF NOT EXISTS workflow_documents_job_idx ON workflow_documents (job_id, kind, revision DESC);

CREATE TABLE IF NOT EXISTS workflow_payments (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    provider text NOT NULL DEFAULT 'square',
    provider_payment_id text,
    provider_invoice_id text,
    payment_request_uid text,
    amount_cents bigint NOT NULL DEFAULT 0,
    currency char(3) NOT NULL DEFAULT 'USD',
    status text NOT NULL,
    payment_type text NOT NULL DEFAULT 'UNKNOWN',
    ledger_status text NOT NULL DEFAULT 'PENDING' CHECK (ledger_status IN ('PENDING','PROCESSING','SYNCED','FAILED')),
    ledger_locked_at timestamptz,
    gauzy_payment_id text,
    ledger_error text,
    occurred_at timestamptz,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_payment_id)
);

CREATE INDEX IF NOT EXISTS workflow_payments_job_idx ON workflow_payments (job_id, created_at DESC);
ALTER TABLE workflow_payments ADD COLUMN IF NOT EXISTS ledger_status text NOT NULL DEFAULT 'PENDING';
ALTER TABLE workflow_payments ADD COLUMN IF NOT EXISTS ledger_locked_at timestamptz;
ALTER TABLE workflow_payments ADD COLUMN IF NOT EXISTS gauzy_payment_id text;
ALTER TABLE workflow_payments ADD COLUMN IF NOT EXISTS ledger_error text;
ALTER TABLE workflow_payments DROP CONSTRAINT IF EXISTS workflow_payments_ledger_status_check;
ALTER TABLE workflow_payments ADD CONSTRAINT workflow_payments_ledger_status_check
    CHECK (ledger_status IN ('PENDING','PROCESSING','SYNCED','FAILED')) NOT VALID;
ALTER TABLE workflow_payments VALIDATE CONSTRAINT workflow_payments_ledger_status_check;
CREATE INDEX IF NOT EXISTS workflow_payments_ledger_idx ON workflow_payments (ledger_status, created_at);

CREATE TABLE IF NOT EXISTS external_mappings (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    entity_type text NOT NULL,
    internal_id text NOT NULL,
    external_id text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, entity_type, internal_id),
    UNIQUE (provider, entity_type, external_id)
);

CREATE TABLE IF NOT EXISTS webhook_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    provider text NOT NULL,
    provider_event_id text NOT NULL,
    event_type text NOT NULL,
    payload_sha256 char(64) NOT NULL,
    status text NOT NULL DEFAULT 'RECEIVED' CHECK (status IN ('RECEIVED','PROCESSED','IGNORED','FAILED')),
    error text,
    received_at timestamptz NOT NULL DEFAULT now(),
    processed_at timestamptz,
    UNIQUE (provider, provider_event_id)
);

CREATE INDEX IF NOT EXISTS webhook_events_status_idx ON webhook_events (status, received_at);

CREATE TABLE IF NOT EXISTS idempotency_keys (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    scope text NOT NULL,
    idempotency_key text NOT NULL,
    request_sha256 char(64) NOT NULL,
    status text NOT NULL DEFAULT 'PROCESSING' CHECK (status IN ('PROCESSING','COMPLETED','FAILED')),
    response jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    expires_at timestamptz NOT NULL DEFAULT (now() + interval '30 days'),
    UNIQUE (scope, idempotency_key)
);

CREATE TABLE IF NOT EXISTS audit_events (
    id bigserial PRIMARY KEY,
    organization_id text,
    actor_type text NOT NULL,
    actor_id text,
    action text NOT NULL,
    entity_type text NOT NULL,
    entity_id text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS audit_events_entity_idx ON audit_events (entity_type, entity_id, created_at DESC);
CREATE INDEX IF NOT EXISTS audit_events_org_idx ON audit_events (organization_id, created_at DESC);

CREATE TABLE IF NOT EXISTS outbox_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    aggregate_type text NOT NULL,
    aggregate_id uuid NOT NULL,
    event_type text NOT NULL,
    payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'PENDING' CHECK (status IN ('PENDING','PROCESSING','COMPLETED','DEAD')),
    attempts integer NOT NULL DEFAULT 0 CHECK (attempts >= 0),
    available_at timestamptz NOT NULL DEFAULT now(),
    locked_at timestamptz,
    locked_by text,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS outbox_events_claim_idx ON outbox_events (status, available_at, created_at);

CREATE TABLE IF NOT EXISTS competitor_targets (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id text NOT NULL DEFAULT 'floodman',
    name text NOT NULL,
    url text NOT NULL,
    category text,
    additional_paths jsonb NOT NULL DEFAULT '[]'::jsonb,
    enabled boolean NOT NULL DEFAULT true,
    frequency_hours integer NOT NULL DEFAULT 168 CHECK (frequency_hours BETWEEN 6 AND 8760),
    next_run_at timestamptz NOT NULL DEFAULT now(),
    last_run_at timestamptz,
    last_error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, url)
);

CREATE TABLE IF NOT EXISTS competitor_snapshots (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    target_id uuid NOT NULL REFERENCES competitor_targets(id) ON DELETE CASCADE,
    content_sha256 char(64) NOT NULL,
    extracted_data jsonb NOT NULL,
    evidence jsonb NOT NULL,
    source_count integer NOT NULL DEFAULT 0,
    model text,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (target_id, content_sha256)
);

CREATE INDEX IF NOT EXISTS competitor_snapshots_target_idx ON competitor_snapshots (target_id, created_at DESC);

CREATE TABLE IF NOT EXISTS competitor_reports (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    target_id uuid NOT NULL REFERENCES competitor_targets(id) ON DELETE CASCADE,
    snapshot_id uuid NOT NULL REFERENCES competitor_snapshots(id) ON DELETE CASCADE,
    previous_snapshot_id uuid REFERENCES competitor_snapshots(id) ON DELETE SET NULL,
    report jsonb NOT NULL,
    change_summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    status text NOT NULL DEFAULT 'COMPLETED',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS competitor_reports_target_idx ON competitor_reports (target_id, created_at DESC);

CREATE TABLE IF NOT EXISTS portal_access_log (
    id bigserial PRIMARY KEY,
    job_id uuid REFERENCES workflow_jobs(id) ON DELETE SET NULL,
    remote_hash char(64),
    user_agent_hash char(64),
    result text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$;

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'workflow_jobs','workflow_documents','workflow_payments','external_mappings',
        'idempotency_keys','outbox_events','competitor_targets'
    ] LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS %I_set_updated_at ON %I', table_name, table_name);
        EXECUTE format(
            'CREATE TRIGGER %I_set_updated_at BEFORE UPDATE ON %I FOR EACH ROW EXECUTE FUNCTION set_updated_at()',
            table_name, table_name
        );
    END LOOP;
END;
$$;


-- -----------------------------------------------------------------------------
-- Imported baseline section: 002_ar_messaging.sql
-- -----------------------------------------------------------------------------
-- Floodman A/R messaging, two-way SMS and final-invoice workflow.
-- All invoices created by this workflow are due upon issuance. Square represents
-- due dates as calendar dates; the application stores the exact issue/due timestamp.

ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS square_invoice_role text NOT NULL DEFAULT 'LEGACY' CHECK (square_invoice_role IN ('LEGACY','DEPOSIT'));
ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS square_final_order_id text;
ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS square_final_invoice_id text;
ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS square_final_invoice_version integer;
ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS square_final_public_url text;
ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS final_invoice_issued_at timestamptz;
ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS final_invoice_due_at timestamptz;

CREATE UNIQUE INDEX IF NOT EXISTS workflow_jobs_square_final_invoice_idx
    ON workflow_jobs (square_final_invoice_id)
    WHERE square_final_invoice_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS communication_consents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id text NOT NULL,
    job_id uuid REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    phone_e164 text NOT NULL,
    channel text NOT NULL DEFAULT 'SMS' CHECK (channel IN ('SMS')),
    status text NOT NULL DEFAULT 'UNKNOWN' CHECK (status IN ('UNKNOWN','OPTED_IN','OPTED_OUT')),
    source text NOT NULL DEFAULT 'UNSPECIFIED',
    disclosure_version text,
    captured_at timestamptz,
    opted_out_at timestamptz,
    opted_in_at timestamptz,
    evidence jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (organization_id, phone_e164, channel)
);

CREATE INDEX IF NOT EXISTS communication_consents_job_idx
    ON communication_consents (job_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS ar_cases (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    job_id uuid NOT NULL UNIQUE REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    organization_id text NOT NULL,
    invoice_number text NOT NULL,
    status text NOT NULL DEFAULT 'OPEN' CHECK (status IN (
        'OPEN','PAST_DUE','PROMISE_TO_PAY','HOLD','DISPUTED','PAID','CLOSED'
    )),
    stage text NOT NULL DEFAULT 'FINAL' CHECK (stage IN ('DEPOSIT','FINAL')),
    issued_at timestamptz NOT NULL,
    due_at timestamptz NOT NULL,
    original_balance_cents bigint NOT NULL CHECK (original_balance_cents >= 0),
    current_balance_cents bigint NOT NULL CHECK (current_balance_cents >= 0),
    currency char(3) NOT NULL DEFAULT 'USD',
    customer_name text NOT NULL,
    recipient_email text NOT NULL,
    recipient_phone_e164 text,
    customer_timezone text NOT NULL DEFAULT 'America/Detroit',
    reminder_index integer NOT NULL DEFAULT 1 CHECK (reminder_index >= 0),
    reminder_count integer NOT NULL DEFAULT 0 CHECK (reminder_count >= 0),
    repeat_count integer NOT NULL DEFAULT 0 CHECK (repeat_count >= 0),
    next_reminder_at timestamptz,
    locked_at timestamptz,
    locked_by text,
    last_reminder_at timestamptz,
    last_reconciled_at timestamptz,
    paused_until timestamptz,
    hold_reason text,
    promise_to_pay_date date,
    assigned_to text,
    last_customer_message_at timestamptz,
    last_staff_alert_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (due_at >= issued_at - interval '1 second')
);

CREATE INDEX IF NOT EXISTS ar_cases_due_idx
    ON ar_cases (status, next_reminder_at)
    WHERE current_balance_cents > 0;
CREATE INDEX IF NOT EXISTS ar_cases_aging_idx
    ON ar_cases (due_at, status)
    WHERE current_balance_cents > 0;

CREATE TABLE IF NOT EXISTS message_threads (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id text NOT NULL,
    job_id uuid REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    ar_case_id uuid REFERENCES ar_cases(id) ON DELETE RESTRICT,
    customer_phone_e164 text,
    customer_email text,
    business_phone_e164 text,
    status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','HUMAN_REQUIRED','CLOSED')),
    assigned_to text,
    last_inbound_at timestamptz,
    last_outbound_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (customer_phone_e164 IS NOT NULL OR customer_email IS NOT NULL),
    UNIQUE (organization_id, customer_phone_e164),
    UNIQUE (organization_id, customer_email)
);

CREATE INDEX IF NOT EXISTS message_threads_job_idx ON message_threads (job_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS message_events (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id uuid NOT NULL REFERENCES message_threads(id) ON DELETE RESTRICT,
    job_id uuid REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    ar_case_id uuid REFERENCES ar_cases(id) ON DELETE RESTRICT,
    direction text NOT NULL CHECK (direction IN ('INBOUND','OUTBOUND','INTERNAL')),
    channel text NOT NULL CHECK (channel IN ('SMS','EMAIL','SYSTEM')),
    provider text NOT NULL,
    provider_message_id text,
    dedupe_key text UNIQUE,
    message_kind text NOT NULL,
    body text NOT NULL DEFAULT '',
    status text NOT NULL DEFAULT 'QUEUED' CHECK (status IN (
        'QUEUED','SENDING','SENT','DELIVERED','UNDELIVERED','FAILED','RECEIVED','SUPPRESSED'
    )),
    error_code text,
    error_message text,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at timestamptz NOT NULL DEFAULT now(),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (provider, provider_message_id)
);

CREATE INDEX IF NOT EXISTS message_events_thread_idx ON message_events (thread_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS message_events_status_idx ON message_events (status, created_at);

CREATE TABLE IF NOT EXISTS payment_promises (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ar_case_id uuid NOT NULL REFERENCES ar_cases(id) ON DELETE RESTRICT,
    job_id uuid NOT NULL REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    promised_date date NOT NULL,
    promised_amount_cents bigint CHECK (promised_amount_cents IS NULL OR promised_amount_cents >= 0),
    status text NOT NULL DEFAULT 'ACTIVE' CHECK (status IN ('ACTIVE','KEPT','MISSED','CANCELLED')),
    source_message_id uuid REFERENCES message_events(id) ON DELETE RESTRICT,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    resolved_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS payment_promises_active_idx
    ON payment_promises (promised_date, status) WHERE status='ACTIVE';

CREATE TABLE IF NOT EXISTS collection_holds (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    ar_case_id uuid NOT NULL REFERENCES ar_cases(id) ON DELETE RESTRICT,
    job_id uuid NOT NULL REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    hold_type text NOT NULL CHECK (hold_type IN ('MANUAL','DISPUTE','CALLBACK','WRONG_NUMBER','LEGAL','PAYMENT_REVIEW')),
    reason text NOT NULL,
    active boolean NOT NULL DEFAULT true,
    created_by text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    released_by text,
    released_at timestamptz,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb
);

CREATE INDEX IF NOT EXISTS collection_holds_active_idx
    ON collection_holds (ar_case_id, active) WHERE active=true;

-- Only one active hold of a given type may exist for an account. Provider
-- webhooks and outbox retries are intentionally at-least-once, so this partial
-- uniqueness rule prevents duplicate holds during replay or reconciliation.
CREATE UNIQUE INDEX IF NOT EXISTS collection_holds_one_active_type_idx
    ON collection_holds (ar_case_id, hold_type) WHERE active=true;

CREATE TABLE IF NOT EXISTS ai_message_decisions (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    thread_id uuid NOT NULL REFERENCES message_threads(id) ON DELETE RESTRICT,
    inbound_message_id uuid NOT NULL REFERENCES message_events(id) ON DELETE RESTRICT,
    provider text NOT NULL,
    model text,
    intent text NOT NULL,
    risk_level text NOT NULL CHECK (risk_level IN ('LOW','MEDIUM','HIGH')),
    confidence numeric(5,4) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    proposed_action text NOT NULL,
    reply_draft text NOT NULL DEFAULT '',
    human_review_required boolean NOT NULL,
    policy_result text NOT NULL,
    structured_output jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (inbound_message_id)
);

CREATE TABLE IF NOT EXISTS staff_alerts (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id text NOT NULL,
    job_id uuid REFERENCES workflow_jobs(id) ON DELETE RESTRICT,
    ar_case_id uuid REFERENCES ar_cases(id) ON DELETE RESTRICT,
    thread_id uuid REFERENCES message_threads(id) ON DELETE RESTRICT,
    alert_type text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('INFO','WARNING','CRITICAL')),
    title text NOT NULL,
    body text NOT NULL,
    status text NOT NULL DEFAULT 'OPEN' CHECK (status IN ('OPEN','ACKNOWLEDGED','RESOLVED')),
    assigned_to text,
    dedupe_key text UNIQUE,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    acknowledged_at timestamptz,
    resolved_at timestamptz
);

ALTER TABLE staff_alerts ADD COLUMN IF NOT EXISTS dedupe_key text;
CREATE UNIQUE INDEX IF NOT EXISTS staff_alerts_dedupe_key_idx
    ON staff_alerts (dedupe_key);

CREATE INDEX IF NOT EXISTS staff_alerts_open_idx
    ON staff_alerts (status, severity, created_at DESC);

CREATE TABLE IF NOT EXISTS ar_digest_runs (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id text NOT NULL,
    local_date date NOT NULL,
    status text NOT NULL DEFAULT 'STARTED' CHECK (status IN ('STARTED','SENT','FAILED')),
    summary jsonb NOT NULL DEFAULT '{}'::jsonb,
    error text,
    created_at timestamptz NOT NULL DEFAULT now(),
    completed_at timestamptz,
    UNIQUE (organization_id, local_date)
);

-- Keep updated_at useful without requiring application code on every provider callback.
CREATE OR REPLACE FUNCTION floodman_touch_updated_at() RETURNS trigger AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS ar_cases_touch_updated_at ON ar_cases;
CREATE TRIGGER ar_cases_touch_updated_at BEFORE UPDATE ON ar_cases
FOR EACH ROW EXECUTE FUNCTION floodman_touch_updated_at();

DROP TRIGGER IF EXISTS message_threads_touch_updated_at ON message_threads;
CREATE TRIGGER message_threads_touch_updated_at BEFORE UPDATE ON message_threads
FOR EACH ROW EXECUTE FUNCTION floodman_touch_updated_at();

DROP TRIGGER IF EXISTS message_events_touch_updated_at ON message_events;
CREATE TRIGGER message_events_touch_updated_at BEFORE UPDATE ON message_events
FOR EACH ROW EXECUTE FUNCTION floodman_touch_updated_at();

DROP TRIGGER IF EXISTS communication_consents_touch_updated_at ON communication_consents;
CREATE TRIGGER communication_consents_touch_updated_at BEFORE UPDATE ON communication_consents
FOR EACH ROW EXECUTE FUNCTION floodman_touch_updated_at();


-- -----------------------------------------------------------------------------
-- Imported baseline section: 003_ar_hardening.sql
-- -----------------------------------------------------------------------------
-- Consolidated A/R scheduling hardening included in the v3 fixed baseline.
-- The first reminder is already represented by next_reminder_at. reminder_index
-- therefore points to the next offset that should be scheduled after it is sent.
ALTER TABLE ar_cases ALTER COLUMN reminder_index SET DEFAULT 1;
UPDATE ar_cases
SET reminder_index=1
WHERE reminder_count=0 AND reminder_index=0;

-- Speed inbound routing when one phone number is associated with multiple open jobs.
CREATE INDEX IF NOT EXISTS ar_cases_phone_open_idx
    ON ar_cases (recipient_phone_e164,due_at,created_at)
    WHERE recipient_phone_e164 IS NOT NULL
      AND current_balance_cents > 0
      AND status NOT IN ('PAID','CLOSED');


-- -----------------------------------------------------------------------------
-- Imported baseline section: 004_gauzy_hub.sql
-- -----------------------------------------------------------------------------
-- Native Floodman ERP project mapping included in the v3 fixed baseline.
-- A RoomFlow job/property may be represented as a native Floodman ERP project so tasks,
-- time entries, expenses, invoice lines, and payments share one operational record.
ALTER TABLE workflow_jobs ADD COLUMN IF NOT EXISTS gauzy_project_id text;
CREATE INDEX IF NOT EXISTS workflow_jobs_gauzy_project_idx
    ON workflow_jobs (gauzy_project_id)
    WHERE gauzy_project_id IS NOT NULL;


CREATE TABLE IF NOT EXISTS floodman_schema_info (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    baseline_version text NOT NULL,
    installed_at timestamptz NOT NULL DEFAULT now(),
    application_name text NOT NULL DEFAULT 'Floodman Business Suite'
);

INSERT INTO floodman_schema_info(singleton, baseline_version, application_name)
VALUES (true, '3.0.0', 'Floodman Business Suite')
ON CONFLICT (singleton) DO UPDATE
SET baseline_version = EXCLUDED.baseline_version,
    application_name = EXCLUDED.application_name;
