#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh

umask 077
mkdir -p "$FM_CONFIG" "$FM_DATA" "$FM_RUN" "$FM_LOGS" \
  "$FM_DATA/postgres" "$FM_DATA/documents" "$FM_DATA/office" "$FM_DATA/lab-state" \
  "$FM_DATA/mailpit" "$FM_DATA/gauzy-files" "$FM_DATA/gauzy-import" \
  "$FM_DATA/documenso" "$FM_HOME/runtime" "$FM_HOME/backups" "$FM_HOME/diagnostics" \
  "$FM_HOME/tmp/nginx/client" "$FM_HOME/tmp/nginx/proxy" "$FM_HOME/tmp/nginx/fastcgi" \
  "$FM_HOME/tmp/nginx/uwsgi" "$FM_HOME/tmp/nginx/scgi"

: "${FLOODMAN_COMPANY_NAME:=Floodman}"
: "${FLOODMAN_OWNER_FIRST_NAME:?Set FLOODMAN_OWNER_FIRST_NAME in the Pterodactyl Startup tab}"
: "${FLOODMAN_OWNER_LAST_NAME:?Set FLOODMAN_OWNER_LAST_NAME in the Pterodactyl Startup tab}"
: "${FLOODMAN_OWNER_EMAIL:?Set FLOODMAN_OWNER_EMAIL in the Pterodactyl Startup tab}"
: "${FLOODMAN_OWNER_PASSWORD:?Set FLOODMAN_OWNER_PASSWORD in the Pterodactyl Startup tab}"
: "${TZ:=America/Detroit}"
: "${SERVER_PORT:?Pterodactyl did not supply SERVER_PORT}"
: "${DOCUMENSO_PORT:=9001}"
: "${MAILPIT_PORT:=9002}"
: "${ENGINEERING_PORT:=9003}"
: "${FLOODMAN_API_PORT:=9004}"
: "${FLOODMAN_PUBLIC_SCHEME:=http}"
: "${FLOODMAN_ENFORCE_9000_PORT_SCHEME:=true}"
: "${FLOODMAN_PUBLIC_HOST:=${SERVER_IP:-127.0.0.1}}"
: "${ROOMFLOW_WEB_URL:=/roomflow/}"
: "${GAUZY_NODE_HEAP_MB:=4096}"
: "${ENABLE_ENGINEERING_TOOLS:=true}"
: "${AI_PROVIDER:=deterministic}"
: "${MESSAGING_AI_PROVIDER:=deterministic}"

case "$FLOODMAN_OWNER_EMAIL" in
  *@*.*) ;;
  *) fm_die "FLOODMAN_OWNER_EMAIL must be a valid email address." ;;
esac
[ "${#FLOODMAN_OWNER_PASSWORD}" -ge 12 ] || fm_die "FLOODMAN_OWNER_PASSWORD must be at least 12 characters."

for p in "$SERVER_PORT" "$DOCUMENSO_PORT" "$MAILPIT_PORT" "$ENGINEERING_PORT" "$FLOODMAN_API_PORT"; do
  case "$p" in *[!0-9]*|'') fm_die "Every configured port must be numeric." ;; esac
  [ "$p" -ge 1024 ] && [ "$p" -le 65535 ] || fm_die "Port $p is outside 1024-65535."
done

ports="$SERVER_PORT $DOCUMENSO_PORT $MAILPIT_PORT $ENGINEERING_PORT $FLOODMAN_API_PORT"
[ "$(printf '%s\n' $ports | sort -n | uniq | wc -l | tr -d ' ')" -eq 5 ] || fm_die "Primary, Documenso, Mailpit, Engineering, and API ports must all be different."
if [ "$FLOODMAN_ENFORCE_9000_PORT_SCHEME" = "true" ]; then
  [ "$SERVER_PORT" = "9000" ] || fm_die "The primary Pterodactyl allocation must be 9000 when the 9000-series scheme is enforced."
  [ "$DOCUMENSO_PORT" = "9001" ] || fm_die "Documenso must use allocation 9001 when the 9000-series scheme is enforced."
  [ "$MAILPIT_PORT" = "9002" ] || fm_die "Mailpit must use allocation 9002 when the 9000-series scheme is enforced."
  [ "$ENGINEERING_PORT" = "9003" ] || fm_die "Engineering Sandbox must use allocation 9003 when the 9000-series scheme is enforced."
  [ "$FLOODMAN_API_PORT" = "9004" ] || fm_die "Floodman API must use allocation 9004 when the 9000-series scheme is enforced."
elif [ "$SERVER_PORT" != "9000" ] || [ "$DOCUMENSO_PORT" != "9001" ] || [ "$MAILPIT_PORT" != "9002" ] || [ "$ENGINEERING_PORT" != "9003" ] || [ "$FLOODMAN_API_PORT" != "9004" ]; then
  fm_log "WARNING: The exact 9000-series scheme is disabled. Current distinct allocation values will be used."
fi
for p in $ports; do
  case "$p" in 1025|1026|3000|4201|5432|8090|8100|8700) fm_die "Port $p is reserved internally by the all-in-one container." ;; esac
done

SECRETS_FILE="$FM_CONFIG/generated-secrets.env"
if [ ! -s "$SECRETS_FILE" ]; then
  fm_log "Generating persistent application and database secrets..."
  internal_hmac="$(openssl rand -base64 48 | tr -d '\n')"
  ai_hmac="$(openssl rand -base64 48 | tr -d '\n')"
  portal_secret="$(openssl rand -base64 48 | tr -d '\n')"
  cat > "$SECRETS_FILE" <<SECRETS
FLOODMAN_DB_PASSWORD=$(openssl rand -hex 32)
AI_DB_PASSWORD=$(openssl rand -hex 32)
GAUZY_DB_PASSWORD=$(openssl rand -hex 32)
DOCUMENSO_DB_PASSWORD=$(openssl rand -hex 32)
POSTGRES_ADMIN_PASSWORD=$(openssl rand -hex 32)
INTERNAL_HMAC_KEYS=v1:${internal_hmac}
AI_HMAC_KEYS=ai-v1:${ai_hmac}
PORTAL_TOKEN_SECRET=${portal_secret}
GAUZY_JWT_SECRET=$(openssl rand -hex 64)
GAUZY_SESSION_SECRET=$(openssl rand -hex 64)
GAUZY_REFRESH_SECRET=$(openssl rand -hex 64)
GAUZY_VERIFICATION_SECRET=$(openssl rand -hex 64)
GAUZY_BOOTSTRAP_ADMIN_PASSWORD=$(openssl rand -hex 24)
GAUZY_BOOTSTRAP_EMPLOYEE_PASSWORD=$(openssl rand -hex 24)
SQUARE_WEBHOOK_SIGNATURE_KEY=$(openssl rand -hex 32)
DOCUMENSO_WEBHOOK_SECRET=$(openssl rand -hex 32)
TWILIO_AUTH_TOKEN=$(openssl rand -hex 32)
DOCUMENSO_NEXTAUTH_SECRET=$(openssl rand -hex 64)
DOCUMENSO_ENCRYPTION_KEY=$(openssl rand -hex 32)
DOCUMENSO_ENCRYPTION_SECONDARY_KEY=$(openssl rand -hex 32)
DOCUMENSO_SIGNING_PASSPHRASE=$(openssl rand -hex 32)
SECRETS
  chmod 0600 "$SECRETS_FILE"
fi

set -a
. "$SECRETS_FILE"
set +a

build_url() {
  scheme="$1"; host="$2"; port="$3"
  case "$scheme:$port" in
    http:80|https:443) printf '%s://%s' "$scheme" "$host" ;;
    *) printf '%s://%s:%s' "$scheme" "$host" "$port" ;;
  esac
}

MAIN_PUBLIC_URL="${FLOODMAN_PUBLIC_URL:-$(build_url "$FLOODMAN_PUBLIC_SCHEME" "$FLOODMAN_PUBLIC_HOST" "$SERVER_PORT")}"
DOCUMENSO_PUBLIC_URL="${FLOODMAN_DOCUMENSO_URL:-$(build_url "$FLOODMAN_PUBLIC_SCHEME" "$FLOODMAN_PUBLIC_HOST" "$DOCUMENSO_PORT")}"
MAILPIT_PUBLIC_URL="${FLOODMAN_MAILPIT_URL:-$(build_url "$FLOODMAN_PUBLIC_SCHEME" "$FLOODMAN_PUBLIC_HOST" "$MAILPIT_PORT")}"
ENGINEERING_PUBLIC_URL="${FLOODMAN_ENGINEERING_URL:-$(build_url "$FLOODMAN_PUBLIC_SCHEME" "$FLOODMAN_PUBLIC_HOST" "$ENGINEERING_PORT")}"
API_PUBLIC_URL="${FLOODMAN_API_PUBLIC_URL:-$(build_url "$FLOODMAN_PUBLIC_SCHEME" "$FLOODMAN_PUBLIC_HOST" "$FLOODMAN_API_PORT")}"
ROOMFLOW_WEB_URL="${ROOMFLOW_WEB_URL:-${MAIN_PUBLIC_URL}/roomflow/}"
export MAIN_PUBLIC_URL DOCUMENSO_PUBLIC_URL MAILPIT_PUBLIC_URL ENGINEERING_PUBLIC_URL API_PUBLIC_URL ROOMFLOW_WEB_URL

BOOTSTRAP_SUFFIX="$(printf '%s' "${P_SERVER_UUID:-pterodactyl}" | tr -cd 'a-zA-Z0-9' | cut -c1-24)"
GAUZY_BOOTSTRAP_ADMIN_EMAIL="bootstrap-admin-${BOOTSTRAP_SUFFIX}@example.com"
GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL="bootstrap-employee-${BOOTSTRAP_SUFFIX}@example.com"

# Core suite environment.
export FLOODMAN_RELEASE="pterodactyl-mobile-v4.6.8"
export FLOODMAN_ENV="staging" LOG_LEVEL="INFO" TIMEZONE="$TZ"
export LEGAL_TEMPLATES_APPROVED="false" SMS_COMPLIANCE_APPROVED="false" TWILIO_A2P_APPROVED="false" AI_CUSTOMER_MESSAGING_APPROVED="false"
export POSTGRES_DB="floodman" POSTGRES_USER="floodman" POSTGRES_PASSWORD="$FLOODMAN_DB_PASSWORD"
export DATABASE_URL="postgresql+psycopg://floodman:${FLOODMAN_DB_PASSWORD}@127.0.0.1:5432/floodman"
export AI_DB_USER="floodman_intel" AI_DATABASE_URL="postgresql+psycopg://floodman_intel:${AI_DB_PASSWORD}@127.0.0.1:5432/floodman"
export PUBLIC_BASE_URL="$API_PUBLIC_URL" PORTAL_BASE_URL="${API_PUBLIC_URL}/p"
export DOCUMENTS_PATH="$FM_DATA/documents" MAX_DOCUMENT_BYTES="26214400"
export INTERNAL_HMAC_MAX_AGE_SECONDS="300" PORTAL_TOKEN_TTL_SECONDS="2592000"
export ROOMFLOW_DOCUMENT_HOSTS="127.0.0.1,localhost"
export ROOMFLOW_ALLOWED_ORIGINS="${MAIN_PUBLIC_URL},${API_PUBLIC_URL}"
export ALLOW_PRIVATE_DOCUMENT_HOSTS="true" DOCUMENT_REQUIRE_HTTPS="false"

# Floodman ERP integration and branding.
export GAUZY_BASE_URL="http://127.0.0.1:3000/api" GAUZY_PUBLIC_URL="$MAIN_PUBLIC_URL" GAUZY_WEB_URL="$MAIN_PUBLIC_URL" GAUZY_HUB_URL="$MAIN_PUBLIC_URL"
export GAUZY_LOGIN_PATH="/auth/login" GAUZY_CONTACT_PATH="/organization-contact" GAUZY_INVOICE_PATH="/invoices" GAUZY_PAYMENT_PATH="/payments" GAUZY_PROJECT_PATH="/organization-projects"
export GAUZY_AUTO_DISCOVER_CONTEXT="true" GAUZY_CREATE_PROPERTY_PROJECTS="true" GAUZY_VERIFY_TLS="false"
export GAUZY_EMAIL="$FLOODMAN_OWNER_EMAIL" GAUZY_PASSWORD="$FLOODMAN_OWNER_PASSWORD"
export GAUZY_TENANT_ID="AUTO" GAUZY_ORGANIZATION_ID="AUTO" GAUZY_FROM_ORGANIZATION_ID="AUTO"
export GAUZY_FULL_SYNC_ENABLED="true" GAUZY_FULL_TENANT_ID="AUTO" GAUZY_FULL_ORGANIZATION_ID="AUTO" GAUZY_FULL_FROM_ORGANIZATION_ID="AUTO"
export GAUZY_COMPANY_NAME="$FLOODMAN_COMPANY_NAME" GAUZY_OWNER_FIRST_NAME="$FLOODMAN_OWNER_FIRST_NAME" GAUZY_OWNER_LAST_NAME="$FLOODMAN_OWNER_LAST_NAME" GAUZY_OWNER_EMAIL="$FLOODMAN_OWNER_EMAIL" GAUZY_OWNER_PASSWORD="$FLOODMAN_OWNER_PASSWORD"
export GAUZY_ADMIN_EMAIL="$FLOODMAN_OWNER_EMAIL" GAUZY_ADMIN_PASSWORD="$FLOODMAN_OWNER_PASSWORD"
export GAUZY_BOOTSTRAP_ADMIN_EMAIL GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL
export GAUZY_NODE_HEAP_MB

# Local provider sandbox. No live card, SMS, or email traffic leaves this test container.
export SQUARE_BASE_URL="http://127.0.0.1:${ENGINEERING_PORT}/square" SQUARE_VERSION="2026-07-15" SQUARE_ACCESS_TOKEN="local-square-token" SQUARE_LOCATION_ID="local-square-location"
export SQUARE_WEBHOOK_NOTIFICATION_URL="${API_PUBLIC_URL}/webhooks/square" SQUARE_DELIVERY_METHOD="SHARE_MANUALLY" SQUARE_ACCEPT_CARD="true" SQUARE_ACCEPT_ACH="false" SQUARE_ACCEPT_CASH_APP="false" SQUARE_VERIFY_TLS="false" SQUARE_SPLIT_FINAL_INVOICE="true"
export DOCUMENSO_BASE_URL="http://127.0.0.1:${ENGINEERING_PORT}/documenso" DOCUMENSO_API_TOKEN="local-documenso-token" DOCUMENSO_VERIFY_TLS="false"
export DOCUMENSO_DEFAULT_SUBJECT="Floodman document ready for signature" DOCUMENSO_DEFAULT_MESSAGE="Controlled Pterodactyl test workflow." DOCUMENSO_REDIRECT_URL="${API_PUBLIC_URL}/p/complete"
export DOCUMENSO_WEB_URL="$DOCUMENSO_PUBLIC_URL" DOCUMENSO_PUBLIC_URL
export TWILIO_ENABLED="true" TWILIO_BASE_URL="http://127.0.0.1:${ENGINEERING_PORT}/twilio/2010-04-01" TWILIO_ACCOUNT_SID="ACLOCALFLOODMAN" TWILIO_MESSAGING_SERVICE_SID="MGLOCALFLOODMAN" TWILIO_FROM_NUMBER="+13135550100"
export TWILIO_INBOUND_WEBHOOK_URL="${API_PUBLIC_URL}/webhooks/twilio/inbound" TWILIO_STATUS_WEBHOOK_URL="${API_PUBLIC_URL}/webhooks/twilio/status" TWILIO_VERIFY_TLS="false"
export SMTP_ENABLED="true" SMTP_HOST="127.0.0.1" SMTP_PORT="1025" SMTP_USERNAME="" SMTP_PASSWORD="" SMTP_FROM_EMAIL="$FLOODMAN_OWNER_EMAIL" SMTP_REPLY_TO="$FLOODMAN_OWNER_EMAIL" SMTP_USE_SSL="false" SMTP_STARTTLS="false"
export MAILPIT_URL="$MAILPIT_PUBLIC_URL" LAB_PUBLIC_URL="$ENGINEERING_PUBLIC_URL"

# Receivables and AI test settings.
export AR_ENABLED="true" AR_TIMEZONE="$TZ" AR_SCAN_SECONDS="10" AR_REMINDER_OFFSETS_HOURS="1,2,3,4,5,6" AR_REPEAT_INTERVAL_HOURS="24" AR_MAX_AUTOMATED_AGE_DAYS="0"
export AR_SEND_START_LOCAL="00:00" AR_SEND_END_LOCAL="23:59" AR_DIGEST_LOCAL_TIME="08:00" AR_MAX_SMS_PER_SEVEN_DAYS="20" AR_REQUIRE_SMS_CONSENT="true" AR_PROMISE_MAX_DAYS="14"
export AR_STAFF_EMAILS="$FLOODMAN_OWNER_EMAIL" AR_STAFF_SMS_ENABLED="false" AR_STAFF_SMS_NUMBERS=""
export OUTBOX_POLL_SECONDS="1" OUTBOX_MAX_ATTEMPTS="20" OUTBOX_LOCK_SECONDS="300" WEBHOOK_MAX_BODY_BYTES="1048576"
export MESSAGING_AI_ENABLED="true" MESSAGING_AI_PROVIDER AI_CUSTOMER_MESSAGING_APPROVED="false" MESSAGING_AI_MIN_CONFIDENCE="0.90" MESSAGING_AI_AUTO_REPLY_LOW_RISK="true" MESSAGING_AI_AUTO_REPLY_MEDIUM_RISK="false"
export MESSAGING_AI_MAX_MESSAGE_CHARS="3000" MESSAGING_AI_MAX_HISTORY_MESSAGES="12" OPENAI_MESSAGING_API_KEY="${OPENAI_MESSAGING_API_KEY:-}" OPENAI_MESSAGING_MODEL="${OPENAI_MESSAGING_MODEL:-gpt-5-mini}" OPENAI_MESSAGING_TIMEOUT_SECONDS="45" OPENAI_VERIFY_TLS="true"
export AI_PROVIDER OPENAI_API_KEY="${OPENAI_API_KEY:-}" OPENAI_MODEL="${OPENAI_MODEL:-gpt-5-mini}" OPENAI_BASE_URL="${OPENAI_BASE_URL:-https://api.openai.com/v1}"
export AI_SCHEDULE_SECONDS="604800" AI_MAX_RUNS_PER_DAY="30" AI_MAX_PAGES_PER_TARGET="5" AI_MAX_RESPONSE_BYTES="2097152" AI_MAX_ANALYSIS_CHARS="60000" AI_USER_AGENT="FloodmanBusinessSuite-Pterodactyl-Mobile/4.6.8" AI_ALLOW_HTTP="true"

# Internal topology.
export AI_SERVICE_URL="http://127.0.0.1:8090" AI_CALLBACK_URL="http://127.0.0.1:${FLOODMAN_API_PORT}/internal/v1/ai/reports" MESSAGING_AI_SERVICE_URL="http://127.0.0.1:8100"
export ORCHESTRATOR_URL="http://127.0.0.1:${FLOODMAN_API_PORT}" LOCAL_LAB_URL="http://127.0.0.1:${ENGINEERING_PORT}" COMPETITOR_URL="http://127.0.0.1:8090" MESSAGING_AI_URL="http://127.0.0.1:8100"
export OFFICE_CONSOLE_PUBLIC_URL="$MAIN_PUBLIC_URL" OFFICE_CONSOLE_DATA_DIR="$FM_DATA/office" OFFICE_INTERNAL_URL="http://127.0.0.1:8700" OFFICE_AUTH_ENABLED="true"
case "$FLOODMAN_PUBLIC_SCHEME" in https) export OFFICE_SESSION_COOKIE_SECURE="true" ;; *) export OFFICE_SESSION_COOKIE_SECURE="false" ;; esac
export OFFICE_MAX_UPLOAD_BYTES="26214400" ROOMFLOW_SYNC_ENDPOINT="${API_PUBLIC_URL}/internal/v1/jobs/sync-estimate" ROOMFLOW_WEB_URL
export GAUZY_FULL_API_URL="http://127.0.0.1:3000/api" GAUZY_HEALTH_URL="http://127.0.0.1:${SERVER_PORT}/health/live"
export DOCUMENSO_FULL_API_URL="http://127.0.0.1:${DOCUMENSO_PORT}/api/v2" DOCUMENSO_HEALTH_URL="http://127.0.0.1:${DOCUMENSO_PORT}" MAILPIT_HEALTH_URL="http://127.0.0.1:${MAILPIT_PORT}"

# Floodman ERP API runtime.
export NODE_ENV="production" IS_DOCKER="true" API_HOST="0.0.0.0" API_PORT="3000" WEB_HOST="127.0.0.1" WEB_PORT="4201"
export API_BASE_URL="$MAIN_PUBLIC_URL" CLIENT_BASE_URL="$MAIN_PUBLIC_URL" ALLOWED_ORIGINS="${MAIN_PUBLIC_URL},${API_PUBLIC_URL},${DOCUMENSO_PUBLIC_URL}"
export DB_ORM="typeorm" DB_TYPE="postgres" DB_SYNCHRONIZE="false" DB_HOST="127.0.0.1" DB_PORT="5432" DB_NAME="gauzy" DB_USER="gauzy" DB_PASS="$GAUZY_DB_PASSWORD"
export DB_LOGGING="none" DB_POOL_SIZE="20" DB_POOL_SIZE_KNEX="5" DB_CONNECTION_TIMEOUT="15000" DB_IDLE_TIMEOUT="10000" DB_SSL_MODE="false"
export WORKER_QUEUE_ENABLED="false" WORKER_SCHEDULER_ENABLED="false" REDIS_ENABLED="false"
export JWT_SECRET="$GAUZY_JWT_SECRET" EXPRESS_SESSION_SECRET="$GAUZY_SESSION_SECRET" JWT_REFRESH_TOKEN_SECRET="$GAUZY_REFRESH_SECRET" JWT_VERIFICATION_TOKEN_SECRET="$GAUZY_VERIFICATION_SECRET"
export DEMO="false" ALLOW_SUPER_ADMIN_ROLE="true" DEMO_SUPER_ADMIN_EMAIL="$FLOODMAN_OWNER_EMAIL" DEMO_SUPER_ADMIN_PASSWORD="$FLOODMAN_OWNER_PASSWORD"
if [ -f "$FM_CONFIG/gauzy-business-initialized" ]; then
  export FORCE_SEED_PASSWORD="false"
else
  # On the first clean bootstrap, guarantee that the configured Owner password
  # is the password the Floodman ERP hashes for the seeded Owner.
  export FORCE_SEED_PASSWORD="true"
fi
export DEMO_ADMIN_EMAIL="$GAUZY_BOOTSTRAP_ADMIN_EMAIL" DEMO_ADMIN_PASSWORD="$GAUZY_BOOTSTRAP_ADMIN_PASSWORD" DEMO_EMPLOYEE_EMAIL="$GAUZY_BOOTSTRAP_EMPLOYEE_EMAIL" DEMO_EMPLOYEE_PASSWORD="$GAUZY_BOOTSTRAP_EMPLOYEE_PASSWORD"
export MAIL_HOST="127.0.0.1" MAIL_PORT="1026" MAIL_USERNAME="" MAIL_PASSWORD="" MAIL_FROM_ADDRESS="$FLOODMAN_OWNER_EMAIL"
export FLOODMAN_CREATOR_NAME="Josh Aldrich"
export APP_NAME="Floodman Operations" APP_SIGNATURE="Floodman Operations · Created by Josh Aldrich" APP_LINK="$MAIN_PUBLIC_URL" APP_EMAIL_CONFIRMATION_URL="${MAIN_PUBLIC_URL}/index.html?desktop=1#/auth/confirm-email" APP_MAGIC_SIGN_URL="${MAIN_PUBLIC_URL}/index.html?desktop=1#/auth/magic-sign-in"
export APP_LOGO="${MAIN_PUBLIC_URL}/floodman-brand/floodman-wordmark.svg" NO_INTERNET_LOGO="$APP_LOGO" PLATFORM_LOGO="$APP_LOGO" GAUZY_DESKTOP_LOGO_512X512="${MAIN_PUBLIC_URL}/floodman-brand/floodman-mark.svg"
export COMPANY_NAME="$FLOODMAN_COMPANY_NAME" COMPANY_LINK="https://floodman.com" COMPANY_SITE_NAME="Floodman Operations" COMPANY_SITE_LINK="https://floodman.com"
export PLATFORM_WEBSITE_URL="https://floodman.com" PLATFORM_WEBSITE_DOWNLOAD_URL="https://floodman.com" PLATFORM_PRIVACY_URL="https://floodman.com" PLATFORM_TOS_URL="https://floodman.com"
export DEFAULT_CURRENCY="USD" DEFAULT_COUNTRY="US" DEFAULT_LATITUDE="42.3314" DEFAULT_LONGITUDE="-83.0458" GOOGLE_PLACE_AUTOCOMPLETE="false"
export FILE_PROVIDER="LOCAL" POSTHOG_ENABLED="false" OTEL_ENABLED="false" SENTRY_HTTP_TRACING_ENABLED="false" SENTRY_POSTGRES_TRACKING_ENABLED="false" SENTRY_PROFILING_ENABLED="false"
export NODE_OPTIONS="--max-old-space-size=${GAUZY_NODE_HEAP_MB}"

# Floodman ERP feature flags.
set -a
. /opt/floodman/aio/gauzy-features.env
set +a

# Documenso runtime.
export PORT="$DOCUMENSO_PORT" NEXTAUTH_SECRET="$DOCUMENSO_NEXTAUTH_SECRET" NEXT_PRIVATE_ENCRYPTION_KEY="$DOCUMENSO_ENCRYPTION_KEY" NEXT_PRIVATE_ENCRYPTION_SECONDARY_KEY="$DOCUMENSO_ENCRYPTION_SECONDARY_KEY"
export NEXT_PUBLIC_WEBAPP_URL="$DOCUMENSO_PUBLIC_URL" NEXT_PRIVATE_INTERNAL_WEBAPP_URL="http://127.0.0.1:${DOCUMENSO_PORT}"
export NEXT_PRIVATE_DATABASE_URL="postgresql://documenso:${DOCUMENSO_DB_PASSWORD}@127.0.0.1:5432/documenso"
export NEXT_PRIVATE_DIRECT_DATABASE_URL="$NEXT_PRIVATE_DATABASE_URL"
export NEXT_PRIVATE_SIGNING_TRANSPORT="local" NEXT_PRIVATE_SIGNING_PASSPHRASE="$DOCUMENSO_SIGNING_PASSPHRASE" NEXT_PRIVATE_SIGNING_LOCAL_FILE_PATH="$FM_DATA/documenso/cert.p12"
export NEXT_PUBLIC_UPLOAD_TRANSPORT="database" NEXT_PRIVATE_SMTP_TRANSPORT="smtp-auth" NEXT_PRIVATE_SMTP_HOST="127.0.0.1" NEXT_PRIVATE_SMTP_PORT="1026" NEXT_PRIVATE_SMTP_UNSAFE_IGNORE_TLS="true"
export NEXT_PRIVATE_SMTP_FROM_NAME="Floodman Signing" NEXT_PRIVATE_SMTP_FROM_ADDRESS="$FLOODMAN_OWNER_EMAIL" NEXT_PUBLIC_DOCUMENT_SIZE_UPLOAD_LIMIT="25" NEXT_PUBLIC_DISABLE_SIGNUP="true" DOCUMENSO_DISABLE_TELEMETRY="true"

# Hub launcher values.
export HUB_TITLE="Floodman Operations Hub" HUB_RELEASE="pterodactyl-mobile-v4.6.8" HUB_OFFICE_URL="$MAIN_PUBLIC_URL" HUB_ROOMFLOW_URL="$ROOMFLOW_WEB_URL"
export HUB_DOCUMENSO_URL="$DOCUMENSO_PUBLIC_URL" HUB_MAILPIT_URL="$MAILPIT_PUBLIC_URL" HUB_ENGINEERING_URL="${ENGINEERING_PUBLIC_URL}/lab" HUB_API_URL="${API_PUBLIC_URL}/docs"
export HUB_COMPETITOR_URL="${MAIN_PUBLIC_URL}/office/intelligence" HUB_SYNC_STATUS_URL="${MAIN_PUBLIC_URL}/office/gauzy" HUB_REMOTE_ACCESS_ENABLED="false"
export HUB_REMOTE_DOCUMENSO_PORT="8443" HUB_REMOTE_MAILPIT_PORT="8444" HUB_REMOTE_ENGINEERING_PORT="8445" HUB_REMOTE_API_PORT="8446" HUB_REMOTE_DOCUMENSO_URL="" HUB_REMOTE_MAILPIT_URL="" HUB_REMOTE_ENGINEERING_URL="" HUB_REMOTE_API_URL=""

# Persist non-secret public topology for troubleshooting and links.
PUBLIC_ENV="$FM_CONFIG/public-urls.env"
: > "$PUBLIC_ENV"
fm_env_set "$PUBLIC_ENV" MAIN_PUBLIC_URL "$MAIN_PUBLIC_URL"
fm_env_set "$PUBLIC_ENV" DOCUMENSO_PUBLIC_URL "$DOCUMENSO_PUBLIC_URL"
fm_env_set "$PUBLIC_ENV" MAILPIT_PUBLIC_URL "$MAILPIT_PUBLIC_URL"
fm_env_set "$PUBLIC_ENV" ENGINEERING_PUBLIC_URL "$ENGINEERING_PUBLIC_URL"
fm_env_set "$PUBLIC_ENV" API_PUBLIC_URL "$API_PUBLIC_URL"
fm_env_set "$PUBLIC_ENV" ROOMFLOW_WEB_URL "$ROOMFLOW_WEB_URL"
chmod 0640 "$PUBLIC_ENV"

# Export the one scoped secret needed by the server-side RoomFlow bridge.
ROOMFLOW_BRIDGE_FILE="$FM_CONFIG/roomflow-bridge.env"
: > "$ROOMFLOW_BRIDGE_FILE"
fm_env_set "$ROOMFLOW_BRIDGE_FILE" FLOODMAN_ORCHESTRATOR_URL "$API_PUBLIC_URL"
fm_env_set "$ROOMFLOW_BRIDGE_FILE" FLOODMAN_ORCHESTRATOR_KEY_ID "v1"
fm_env_set "$ROOMFLOW_BRIDGE_FILE" FLOODMAN_ORCHESTRATOR_HMAC_SECRET "${INTERNAL_HMAC_KEYS#v1:}"
chmod 0600 "$ROOMFLOW_BRIDGE_FILE"

# Initialize the persistent PostgreSQL cluster without running a second container.
PGDATA="$FM_DATA/postgres"
PGSOCKET="$FM_RUN/postgres"
export PGDATA PGSOCKET
mkdir -p "$PGSOCKET"
if [ ! -s "$PGDATA/PG_VERSION" ]; then
  fm_log "Initializing the embedded PostgreSQL cluster..."
  pwfile="$FM_RUN/postgres-password"
  printf '%s' "$POSTGRES_ADMIN_PASSWORD" > "$pwfile"
  initdb -D "$PGDATA" -U postgres --pwfile="$pwfile" --auth-local=trust --auth-host=scram-sha-256 >/dev/null
  rm -f "$pwfile"
  cat >> "$PGDATA/postgresql.conf" <<PGCONF
listen_addresses = '127.0.0.1'
port = 5432
unix_socket_directories = '$PGSOCKET'
max_connections = 150
shared_buffers = '256MB'
log_destination = 'stderr'
logging_collector = off
PGCONF
fi

# Ensure writable persistent storage for the upstream applications.
if [ ! -e "$FM_DATA/gauzy-files/.seeded" ]; then
  cp -a /opt/floodman/gauzy-public-seed/. "$FM_DATA/gauzy-files/" 2>/dev/null || true
  touch "$FM_DATA/gauzy-files/.seeded"
fi
mkdir -p "$FM_DATA/gauzy-import"

fm_log "Starting the all-in-one test suite under Supervisor..."
fm_log "Main Floodman Operations Hub: $MAIN_PUBLIC_URL"
fm_log "Documenso: $DOCUMENSO_PUBLIC_URL"
fm_log "Mailpit: $MAILPIT_PUBLIC_URL"
fm_log "Engineering Sandbox: $ENGINEERING_PUBLIC_URL/lab"
fm_log "Floodman API: $API_PUBLIC_URL/docs"

exec supervisord -n -c /opt/floodman/aio/supervisord.conf
