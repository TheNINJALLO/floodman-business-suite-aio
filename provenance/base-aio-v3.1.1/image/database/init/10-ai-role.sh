#!/usr/bin/env sh
set -eu

: "${POSTGRES_DB:?POSTGRES_DB is required}"
: "${POSTGRES_USER:?POSTGRES_USER is required}"
: "${AI_DB_USER:?AI_DB_USER is required}"
: "${AI_DB_PASSWORD:?AI_DB_PASSWORD is required}"

psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=ON_ERROR_STOP=1 --set=ai_user="$AI_DB_USER" --set=ai_pass="$AI_DB_PASSWORD" <<'SQL'
SELECT format('CREATE ROLE %I LOGIN PASSWORD %L', :'ai_user', :'ai_pass')
WHERE NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = :'ai_user') \gexec
SELECT format('ALTER ROLE %I LOGIN PASSWORD %L', :'ai_user', :'ai_pass') \gexec
SELECT format('GRANT CONNECT ON DATABASE %I TO %I', current_database(), :'ai_user') \gexec
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SELECT format('GRANT USAGE ON SCHEMA public TO %I', :'ai_user') \gexec
SELECT format(
  'GRANT SELECT,INSERT,UPDATE ON TABLE competitor_targets,competitor_snapshots,competitor_reports TO %I',
  :'ai_user'
) \gexec
SELECT format(
  'REVOKE ALL ON TABLE workflow_jobs,workflow_documents,workflow_payments,external_mappings,webhook_events,idempotency_keys,audit_events,outbox_events,portal_access_log,ar_cases,message_threads,message_events,payment_promises,collection_holds,ai_message_decisions,staff_alerts,ar_digest_runs,communication_consents FROM %I',
  :'ai_user'
) \gexec
SQL
