#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
while [ ! -f "$FM_RUN/gauzy-finalized" ]; do sleep 2; done
fm_wait_http "http://127.0.0.1:8700/health/live" 600 false || fm_die "Floodman Office did not become ready before Hub startup."

runtime_web="$FM_HOME/runtime/gauzy-web"
config_hash="$(printf '%s\n' "$MAIN_PUBLIC_URL|$FLOODMAN_COMPANY_NAME|$HUB_RELEASE" | sha256sum | awk '{print $1}')"
old_hash="$(cat "$runtime_web/.floodman-config-hash" 2>/dev/null || true)"
if [ "$config_hash" != "$old_hash" ] || [ ! -s "$runtime_web/index.html" ]; then
  fm_log "Preparing the branded Floodman ERP browser bundle..."
  rm -rf "$runtime_web"
  mkdir -p "$runtime_web"
  cp -a /opt/gauzy-web-pristine/. "$runtime_web/"
  cd "$runtime_web"
  envsubst < replacements.sed > replacements_values.sed
  # The ERP entrypoint replaces generated Docker placeholders in root JS bundles.
  for file in ./*.js; do
    [ -f "$file" ] || continue
    sed -i -f replacements_values.sed "$file"
  done
  printf '%s' "$config_hash" > .floodman-config-hash
fi

mkdir -p "$FM_HOME/runtime/hub"
envsubst '${HUB_TITLE} ${HUB_RELEASE} ${HUB_OFFICE_URL} ${HUB_VOICE_URL} ${HUB_ROOMFLOW_URL} ${HUB_DOCUMENSO_URL} ${HUB_MAILPIT_URL} ${HUB_ENGINEERING_URL} ${HUB_API_URL} ${HUB_COMPETITOR_URL} ${HUB_SYNC_STATUS_URL} ${HUB_REMOTE_ACCESS_ENABLED} ${HUB_REMOTE_DOCUMENSO_PORT} ${HUB_REMOTE_MAILPIT_PORT} ${HUB_REMOTE_ENGINEERING_PORT} ${HUB_REMOTE_API_PORT} ${HUB_REMOTE_DOCUMENSO_URL} ${HUB_REMOTE_MAILPIT_URL} ${HUB_REMOTE_ENGINEERING_URL} ${HUB_REMOTE_API_URL}' \
  < /opt/floodman/hub/hub-config.js.template \
  > "$FM_HOME/runtime/hub/floodman-hub-config.js"
envsubst '${SERVER_PORT} ${HUB_RELEASE}' \
  < /opt/floodman/aio/nginx.conf.template \
  > "$FM_CONFIG/nginx.conf"

fm_log "Starting Floodman Operations Hub on port $SERVER_PORT..."
exec nginx -e "$FM_LOGS/nginx-bootstrap.log" -c "$FM_CONFIG/nginx.conf" -g 'daemon off;'
