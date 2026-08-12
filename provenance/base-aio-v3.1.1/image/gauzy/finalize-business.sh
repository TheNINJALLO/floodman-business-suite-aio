#!/usr/bin/env sh
set -eu

: "${GAUZY_DB_PASSWORD:?GAUZY_DB_PASSWORD is required}"
: "${GAUZY_OWNER_EMAIL:?GAUZY_OWNER_EMAIL is required}"
: "${GAUZY_OWNER_FIRST_NAME:?GAUZY_OWNER_FIRST_NAME is required}"
: "${GAUZY_OWNER_LAST_NAME:?GAUZY_OWNER_LAST_NAME is required}"
: "${GAUZY_COMPANY_NAME:?GAUZY_COMPANY_NAME is required}"
: "${TIMEZONE:?TIMEZONE is required}"
: "${GAUZY_BOOTSTRAP_ADMIN_EMAIL:?GAUZY_BOOTSTRAP_ADMIN_EMAIL is required}"
: "${GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL:?GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL is required}"

export PGPASSWORD="$GAUZY_DB_PASSWORD"
PSQL="psql --host=gauzy-db --username=gauzy --dbname=gauzy --set=ON_ERROR_STOP=1"

printf '%s\n' 'Waiting for the genuine Gauzy minimum non-demo seed...'
tries=0
until $PSQL -Atc "SELECT CASE WHEN to_regclass('public.\"user\"') IS NOT NULL AND to_regclass('public.\"organization\"') IS NOT NULL AND to_regclass('public.\"employee\"') IS NOT NULL THEN 1 ELSE 0 END" 2>/dev/null | grep -q '^1$'; do
  tries=$((tries + 1))
  if [ "$tries" -ge 180 ]; then
    printf '%s\n' 'Gauzy tables did not become available within 30 minutes.' >&2
    exit 1
  fi
  sleep 10
done

$PSQL \
  --set=owner_email="$GAUZY_OWNER_EMAIL" \
  --set=owner_first="$GAUZY_OWNER_FIRST_NAME" \
  --set=owner_last="$GAUZY_OWNER_LAST_NAME" \
  --set=company_name="$GAUZY_COMPANY_NAME" \
  --set=timezone="$TIMEZONE" \
  --set=bootstrap_admin="$GAUZY_BOOTSTRAP_ADMIN_EMAIL" \
  --set=bootstrap_employee="$GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL" <<'SQL'
BEGIN;

UPDATE "tenant"
SET "name" = :'company_name', "updatedAt" = NOW()
WHERE "id" = (SELECT "id" FROM "tenant" ORDER BY "createdAt" ASC LIMIT 1);

UPDATE "organization"
SET "name" = :'company_name',
    "officialName" = :'company_name',
    "currency" = 'USD',
    "timeZone" = :'timezone',
    "brandColor" = '#0B4F6C',
    "totalEmployees" = 1,
    "updatedAt" = NOW()
WHERE "isDefault" = TRUE;

UPDATE "user"
SET "firstName" = :'owner_first',
    "lastName" = :'owner_last',
    "timeZone" = :'timezone',
    "isActive" = TRUE,
    "isArchived" = FALSE,
    "archivedAt" = NULL,
    "emailVerifiedAt" = COALESCE("emailVerifiedAt", NOW()),
    "updatedAt" = NOW()
WHERE lower("email") = lower(:'owner_email');

UPDATE "employee"
SET "isActive" = TRUE,
    "isArchived" = FALSE,
    "archivedAt" = NULL,
    "startedWorkOn" = COALESCE("startedWorkOn", CURRENT_DATE),
    "updatedAt" = NOW()
WHERE "userId" IN (SELECT "id" FROM "user" WHERE lower("email") = lower(:'owner_email'));

UPDATE "user"
SET "isActive" = FALSE,
    "isArchived" = TRUE,
    "archivedAt" = COALESCE("archivedAt", NOW()),
    "updatedAt" = NOW()
WHERE lower("email") IN (lower(:'bootstrap_admin'), lower(:'bootstrap_employee'));

UPDATE "employee"
SET "isActive" = FALSE,
    "isArchived" = TRUE,
    "archivedAt" = COALESCE("archivedAt", NOW()),
    "updatedAt" = NOW()
WHERE "userId" IN (
    SELECT "id" FROM "user"
    WHERE lower("email") IN (lower(:'bootstrap_admin'), lower(:'bootstrap_employee'))
);

CREATE TABLE IF NOT EXISTS floodman_installation_meta (
    singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
    version text NOT NULL,
    company_name text NOT NULL,
    owner_email text NOT NULL,
    finalized_at timestamptz NOT NULL DEFAULT now()
);

INSERT INTO floodman_installation_meta(singleton, version, company_name, owner_email)
VALUES (true, '3.0.0', :'company_name', lower(:'owner_email'))
ON CONFLICT (singleton) DO UPDATE
SET version = EXCLUDED.version,
    company_name = EXCLUDED.company_name,
    owner_email = EXCLUDED.owner_email,
    finalized_at = now();

COMMIT;
SQL

verification="$($PSQL -At \
  --set=owner_email="$GAUZY_OWNER_EMAIL" \
  --set=bootstrap_admin="$GAUZY_BOOTSTRAP_ADMIN_EMAIL" \
  --set=bootstrap_employee="$GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL" \
  --set=company_name="$GAUZY_COMPANY_NAME" <<'SQL'
SELECT concat_ws('|',
  (SELECT COUNT(*) FROM "user" WHERE lower("email") = lower(:'owner_email') AND COALESCE("isActive", TRUE) = TRUE AND COALESCE("isArchived", FALSE) = FALSE),
  (SELECT COUNT(*) FROM "user" WHERE lower("email") IN (lower(:'bootstrap_admin'), lower(:'bootstrap_employee')) AND COALESCE("isActive", TRUE) = TRUE AND COALESCE("isArchived", FALSE) = FALSE),
  (SELECT COUNT(*) FROM "organization" WHERE "name" = :'company_name' AND COALESCE("isArchived", FALSE) = FALSE),
  (SELECT COUNT(*) FROM "organization_contact"),
  (SELECT COUNT(*) FROM "invoice"),
  (SELECT COUNT(*) FROM "payment")
);
SQL
)"

IFS='|' read -r owner_count bootstrap_count company_count contact_count invoice_count payment_count <<EOF
$verification
EOF

[ "$owner_count" = '1' ] || { printf 'Expected exactly one active owner, found %s.\n' "$owner_count" >&2; exit 1; }
[ "$bootstrap_count" = '0' ] || { printf 'Temporary bootstrap accounts are still active: %s.\n' "$bootstrap_count" >&2; exit 1; }
[ "$company_count" -ge 1 ] || { printf '%s\n' 'Floodman company name was not applied.' >&2; exit 1; }
[ "$contact_count" = '0' ] || { printf 'Expected zero contacts in the fresh ERP, found %s.\n' "$contact_count" >&2; exit 1; }
[ "$invoice_count" = '0' ] || { printf 'Expected zero invoices in the fresh ERP, found %s.\n' "$invoice_count" >&2; exit 1; }
[ "$payment_count" = '0' ] || { printf 'Expected zero payments in the fresh ERP, found %s.\n' "$payment_count" >&2; exit 1; }

printf 'Floodman Gauzy finalized: owner=%s contacts=%s invoices=%s payments=%s\n' \
  "$owner_count" "$contact_count" "$invoice_count" "$payment_count"
