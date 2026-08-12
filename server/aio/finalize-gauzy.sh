#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh

fm_log "Waiting for the Floodman ERP API and minimum platform foundation..."
fm_wait_http "http://127.0.0.1:3000/api/auth/authenticated" 2700 true || fm_die "Floodman ERP API did not become ready within 45 minutes."

export PGPASSWORD="$GAUZY_DB_PASSWORD"
PSQL="psql -h $FM_RUN/postgres -p 5432 -U gauzy -d gauzy -v ON_ERROR_STOP=1"

tries=0
until $PSQL -Atc "SELECT CASE WHEN to_regclass('public.\"user\"') IS NOT NULL AND to_regclass('public.\"organization\"') IS NOT NULL AND to_regclass('public.\"employee\"') IS NOT NULL THEN 1 ELSE 0 END" 2>/dev/null | grep -q '^1$'; do
  tries=$((tries + 1)); [ "$tries" -lt 180 ] || fm_die "Floodman ERP tables did not become available."
  sleep 10
done

installed="$($PSQL -Atc "SELECT owner_email FROM floodman_installation_meta WHERE singleton=true" 2>/dev/null || true)"
if [ -z "$installed" ]; then
  fm_log "Applying the Floodman company and Owner profile to the ERP..."
  $PSQL \
    --set=owner_email="$FLOODMAN_OWNER_EMAIL" \
    --set=owner_first="$FLOODMAN_OWNER_FIRST_NAME" \
    --set=owner_last="$FLOODMAN_OWNER_LAST_NAME" \
    --set=company_name="$FLOODMAN_COMPANY_NAME" \
    --set=timezone="$TZ" \
    --set=bootstrap_admin="$GAUZY_BOOTSTRAP_ADMIN_EMAIL" \
    --set=bootstrap_employee="$GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL" <<'SQL'
BEGIN;
UPDATE "tenant" SET "name"=:'company_name', "updatedAt"=NOW()
WHERE "id"=(SELECT "id" FROM "tenant" ORDER BY "createdAt" ASC LIMIT 1);
UPDATE "organization" SET "name"=:'company_name', "officialName"=:'company_name', "currency"='USD',
  "timeZone"=:'timezone', "brandColor"='#0B4F6C', "totalEmployees"=1, "updatedAt"=NOW()
WHERE "isDefault"=TRUE;
UPDATE "user" SET "firstName"=:'owner_first', "lastName"=:'owner_last', "timeZone"=:'timezone',
  "isActive"=TRUE, "isArchived"=FALSE, "archivedAt"=NULL,
  "emailVerifiedAt"=COALESCE("emailVerifiedAt",NOW()), "updatedAt"=NOW()
WHERE lower("email")=lower(:'owner_email');
UPDATE "employee" SET "isActive"=TRUE, "isArchived"=FALSE, "archivedAt"=NULL,
  "startedWorkOn"=COALESCE("startedWorkOn",CURRENT_DATE), "updatedAt"=NOW()
WHERE "userId" IN (SELECT "id" FROM "user" WHERE lower("email")=lower(:'owner_email'));
UPDATE "user" SET "isActive"=FALSE, "isArchived"=TRUE, "archivedAt"=COALESCE("archivedAt",NOW()), "updatedAt"=NOW()
WHERE lower("email") IN (lower(:'bootstrap_admin'),lower(:'bootstrap_employee'));
UPDATE "employee" SET "isActive"=FALSE, "isArchived"=TRUE, "archivedAt"=COALESCE("archivedAt",NOW()), "updatedAt"=NOW()
WHERE "userId" IN (SELECT "id" FROM "user" WHERE lower("email") IN (lower(:'bootstrap_admin'),lower(:'bootstrap_employee')));
CREATE TABLE IF NOT EXISTS floodman_installation_meta (
  singleton boolean PRIMARY KEY DEFAULT true CHECK(singleton),
  version text NOT NULL, company_name text NOT NULL, owner_email text NOT NULL,
  finalized_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO floodman_installation_meta(singleton,version,company_name,owner_email)
VALUES(true,'3.1.1-pterodactyl-aio',:'company_name',lower(:'owner_email'))
ON CONFLICT(singleton) DO UPDATE SET version=EXCLUDED.version,company_name=EXCLUDED.company_name,
  owner_email=EXCLUDED.owner_email,finalized_at=now();
COMMIT;
SQL

  verification="$($PSQL -At \
    --set=owner_email="$FLOODMAN_OWNER_EMAIL" \
    --set=bootstrap_admin="$GAUZY_BOOTSTRAP_ADMIN_EMAIL" \
    --set=bootstrap_employee="$GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL" \
    --set=company_name="$FLOODMAN_COMPANY_NAME" <<'SQL'
SELECT concat_ws('|',
 (SELECT COUNT(*) FROM "user" WHERE lower("email")=lower(:'owner_email') AND COALESCE("isActive",TRUE)=TRUE AND COALESCE("isArchived",FALSE)=FALSE),
 (SELECT COUNT(*) FROM "user" WHERE lower("email") IN (lower(:'bootstrap_admin'),lower(:'bootstrap_employee')) AND COALESCE("isActive",TRUE)=TRUE AND COALESCE("isArchived",FALSE)=FALSE),
 (SELECT COUNT(*) FROM "organization" WHERE "name"=:'company_name' AND COALESCE("isArchived",FALSE)=FALSE),
 (SELECT COUNT(*) FROM "organization_contact"),
 (SELECT COUNT(*) FROM "invoice"),
 (SELECT COUNT(*) FROM "payment")
);
SQL
  )"
  IFS='|' read -r owner_count bootstrap_count company_count contact_count invoice_count payment_count <<VERIFY
$verification
VERIFY
  [ "$owner_count" = 1 ] || fm_die "Expected one active Owner; found $owner_count."
  [ "$bootstrap_count" = 0 ] || fm_die "Temporary bootstrap accounts are still active."
  [ "$company_count" -ge 1 ] || fm_die "Floodman company name was not applied."
  [ "$contact_count" = 0 ] || fm_die "Fresh ERP unexpectedly contains $contact_count contacts."
  [ "$invoice_count" = 0 ] || fm_die "Fresh ERP unexpectedly contains $invoice_count invoices."
  [ "$payment_count" = 0 ] || fm_die "Fresh ERP unexpectedly contains $payment_count payments."
  fm_log "Clean Floodman ERP verified: owner=1 contacts=0 invoices=0 payments=0"
else
  current_owner="$($PSQL -Atc "SELECT COUNT(*) FROM \"user\" WHERE lower(\"email\")=lower('$FLOODMAN_OWNER_EMAIL') AND COALESCE(\"isActive\",TRUE)=TRUE AND COALESCE(\"isArchived\",FALSE)=FALSE")"
  [ "$current_owner" = 1 ] || fm_die "Configured Owner no longer matches the initialized Floodman ERP database. Restore the original Pterodactyl Owner email variable."
  fm_log "Existing Floodman ERP installation verified for $installed."
fi

touch "$FM_RUN/gauzy-finalized"
touch "$FM_CONFIG/gauzy-business-initialized"
chmod 0600 "$FM_CONFIG/gauzy-business-initialized" 2>/dev/null || true
