#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh

fm_log "Linking the Floodman Owner to the specialized operations modules..."
waited=0
while [ ! -f "$FM_RUN/gauzy-finalized" ]; do
  [ "$waited" -lt 2700 ] || fm_die "Floodman Owner finalization did not complete."
  sleep 3
  waited=$((waited + 3))
done
fm_wait_http "http://127.0.0.1:8700/health/live" 300 false || fm_die "Floodman Office did not become ready for Owner linking."
body="$FM_LOGS/owner-link-response.html"
code="$(curl -sS --max-time 30 -o "$body" -w '%{http_code}' \
  -X POST \
  --data-urlencode "email=$FLOODMAN_OWNER_EMAIL" \
  --data-urlencode "password=$FLOODMAN_OWNER_PASSWORD" \
  --data-urlencode 'next=/office' \
  'http://127.0.0.1:8700/login/gauzy' || true)"
case "$code" in
  302|303)
    touch "$FM_RUN/owner-linked"
    rm -f "$body"
    fm_log "The Floodman Owner is linked to every operations module."
    ;;
  *)
    fm_warn "Owner linking returned HTTP ${code:-000}. Response saved to $body"
    fm_die "The Floodman Owner could not be linked to the operations modules."
    ;;
esac
