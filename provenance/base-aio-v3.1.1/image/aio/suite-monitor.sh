#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh

fm_log "Waiting for the complete Floodman suite..."
fm_wait_http "http://127.0.0.1:${SERVER_PORT}/health/live" 2700 false || fm_die "Main Hub did not become ready."
fm_wait_http "http://127.0.0.1:3000/api/auth/authenticated" 60 true || fm_die "Gauzy API is unavailable."
fm_wait_http "http://127.0.0.1:${FLOODMAN_API_PORT}/health/ready" 180 false || fm_die "Floodman API is unavailable."
fm_wait_http "http://127.0.0.1:${DOCUMENSO_PORT}/api/health" 600 true || fm_die "Documenso is unavailable."
fm_wait_http "http://127.0.0.1:${MAILPIT_PORT}/api/v1/info" 120 true || fm_die "Mailpit is unavailable."
fm_wait_http "http://127.0.0.1:${ENGINEERING_PORT}/health/live" 120 false || fm_die "Engineering Sandbox is unavailable."

printf '\n============================================================\n'
printf 'FLOODMAN_SUITE_READY\n'
printf 'Main Hub: %s\n' "$MAIN_PUBLIC_URL"
printf 'Documenso: %s\n' "$DOCUMENSO_PUBLIC_URL"
printf 'Mailpit: %s\n' "$MAILPIT_PUBLIC_URL"
printf 'Engineering Sandbox: %s/lab\n' "$ENGINEERING_PUBLIC_URL"
printf 'Floodman API: %s/docs\n' "$API_PUBLIC_URL"
printf 'Owner: %s\n' "$FLOODMAN_OWNER_EMAIL"
printf '============================================================\n\n'

# Keep a supervised readiness process alive so future health loss is visible.
while :; do
  sleep 60
  if ! curl -fsS --max-time 5 "http://127.0.0.1:${SERVER_PORT}/health/live" >/dev/null 2>&1; then
    fm_warn "Main Hub health check failed. Review the Pterodactyl console logs."
  fi
done
