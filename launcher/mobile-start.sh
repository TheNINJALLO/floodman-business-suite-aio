#!/bin/sh
set -eu

cd /home/container

log() { printf '[Floodman Mobile v4.6.7] %s\n' "$*"; }
die() { printf '[Floodman Mobile v4.6.7] ERROR: %s\n' "$*" >&2; exit 1; }

base='/opt/floodman/aio'
hotfix='/home/container/runtime/floodman-v4.6.7'
run_dir='/home/container/run'

[ -r "$base/start-suite.sh" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/start-suite.sh.'
[ -r "$base/supervisord.conf" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/supervisord.conf.'
[ -r "$base/common.sh" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/common.sh.'
[ -r "$base/start-hub.sh" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/start-hub.sh.'
[ -r "$base/nginx.conf.template" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/nginx.conf.template.'

case "${FLOODMAN_SOURCE_MODE:-builtin}" in
  builtin|'') ;;
  *) log 'Source Mode is not builtin. This emergency launcher uses the verified source already baked into the image.' ;;
esac

mkdir -p "$hotfix" "$run_dir/postgres" /home/container/logs

overlay_zip="/home/container/floodman-operations-runtime-v4.6.7.zip"
overlay_extract="$hotfix/app-overlay"
overlay_root="$overlay_extract/floodman-operations-v4.6.7"
[ -r "$overlay_zip" ] || die 'Keep floodman-operations-runtime-v4.6.7.zip in the Pterodactyl server root before starting.'
rm -rf "$overlay_extract"
mkdir -p "$overlay_extract"
unzip -q "$overlay_zip" -d "$overlay_extract" || die 'Could not extract the Floodman v4.6.7 mobile-API overlay.'
[ "$(cat "$overlay_root/VERSION" 2>/dev/null || true)" = '4.6.7' ] || die 'The uploaded mobile-API overlay is not Floodman v4.6.7.'
( cd "$overlay_root" && sha256sum -c MANIFEST.sha256 >/dev/null ) || die 'The Floodman v4.6.7 mobile-API overlay failed its checksum verification.'
log 'Verified the cumulative Floodman v4.6.7 full-ERP login overlay with authentication-aware routing, injected browser recovery, separate desktop/mobile workspaces, RoomFlow workspaces, guarded PDFs, estimates, invoices, scheduling, and payments.'
# Remove only stale extracted runtime trees. Uploaded rollback ZIPs and all data remain untouched.
rm -rf /home/container/runtime/floodman-v4.6.0 /home/container/runtime/floodman-v4.6.1 /home/container/runtime/floodman-v4.6.2 /home/container/runtime/floodman-v4.6.3 /home/container/runtime/floodman-v4.6.4 /home/container/runtime/floodman-v4.6.5 /home/container/runtime/floodman-v4.6.6
mkdir -p /home/container/config
printf '%s\n' '4.6.7' > /home/container/config/floodman-active-runtime.txt



# ---------------------------------------------------------------------------
# Restart safety: never launch a second Supervisor/PostgreSQL process
# ---------------------------------------------------------------------------
process_cmdline() {
  pid="$1"
  [ -r "/proc/$pid/cmdline" ] || return 1
  tr '\000' ' ' < "/proc/$pid/cmdline" 2>/dev/null || true
}

wait_for_pid_exit() {
  pid="$1"
  limit="${2:-30}"
  waited=0
  while kill -0 "$pid" 2>/dev/null; do
    [ "$waited" -lt "$limit" ] || return 1
    sleep 1
    waited=$((waited + 1))
  done
  return 0
}

cleanup_previous_suite() {
  supervisor_pidfile="$run_dir/supervisord.pid"
  if [ -s "$supervisor_pidfile" ]; then
    supervisor_pid="$(head -n1 "$supervisor_pidfile" 2>/dev/null | tr -cd '0-9')"
    if [ -n "$supervisor_pid" ] && kill -0 "$supervisor_pid" 2>/dev/null; then
      supervisor_cmd="$(process_cmdline "$supervisor_pid")"
      case "$supervisor_cmd" in
        *supervisord*)
          log "Stopping a previous Floodman Supervisor process (PID $supervisor_pid) before restart..."
          kill -TERM "$supervisor_pid" 2>/dev/null || true
          if ! wait_for_pid_exit "$supervisor_pid" 45; then
            log "Previous Supervisor did not exit in time; forcing it to stop."
            kill -KILL "$supervisor_pid" 2>/dev/null || true
            wait_for_pid_exit "$supervisor_pid" 10 || true
          fi
          ;;
        *)
          log 'Removing a stale Supervisor PID file.'
          ;;
      esac
    fi
    rm -f "$supervisor_pidfile"
  fi

  pgdata='/home/container/data/postgres'
  pg_pidfile="$pgdata/postmaster.pid"
  if [ -s "$pg_pidfile" ]; then
    pg_pid="$(head -n1 "$pg_pidfile" 2>/dev/null | tr -cd '0-9')"
    if [ -n "$pg_pid" ] && kill -0 "$pg_pid" 2>/dev/null; then
      pg_cmd="$(process_cmdline "$pg_pid")"
      case "$pg_cmd" in
        *postgres*"$pgdata"*|*postgres*'-D '"$pgdata"*)
          log "Stopping a PostgreSQL process left by the previous Floodman runtime (PID $pg_pid)..."
          if ! pg_ctl -D "$pgdata" -m fast -w -t 60 stop > /home/container/logs/postgres-restart-cleanup.log 2>&1; then
            kill -INT "$pg_pid" 2>/dev/null || true
            if ! wait_for_pid_exit "$pg_pid" 30; then
              log 'PostgreSQL did not stop cleanly; forcing the orphaned process to exit so crash recovery can run.'
              kill -KILL "$pg_pid" 2>/dev/null || true
              wait_for_pid_exit "$pg_pid" 10 || true
            fi
          fi
          ;;
        *)
          log "Removing stale PostgreSQL lock file; PID $pg_pid belongs to another process."
          rm -f "$pg_pidfile"
          ;;
      esac
    else
      log 'Removing a stale PostgreSQL lock file from the previous container.'
      rm -f "$pg_pidfile"
    fi
  fi

  # Remove only transient socket files after the prior server is confirmed gone.
  rm -f \
    "$run_dir/postgres/.s.PGSQL.5432" \
    "$run_dir/postgres/.s.PGSQL.5432.lock"
}

cleanup_previous_suite


# ---------------------------------------------------------------------------
# Private HTTPS through Tailscale Serve
# ---------------------------------------------------------------------------
ts_version="${TAILSCALE_VERSION:-$(cat "$overlay_root/tailscale/STABLE_VERSION" 2>/dev/null || printf '1.102.2')}"
ts_root='/home/container/runtime/tailscale'
ts_bin="$ts_root/bin"
ts_cache="$ts_root/cache"
ts_state='/home/container/data/tailscale'
ts_run='/home/container/run/tailscale'
ts_socket="$ts_run/tailscaled.sock"
ts_logs='/home/container/logs/tailscale'
ts_auth_file='/home/container/config/tailscale-auth-key.txt'
ts_hostname_file='/home/container/config/tailscale-hostname.txt'
ts_urls_file='/home/container/config/tailscale-private-urls.txt'
ts_public_signing_status_file='/home/container/config/public-signing-status.txt'
ts_public_signing_ready_marker='/home/container/run/public-signing-ready'
mkdir -p "$ts_bin" "$ts_cache" "$ts_state" "$ts_run" "$ts_logs" /home/container/config

if [ -s "$ts_hostname_file" ]; then
  ts_hostname="$(tr -d '\r\n' < "$ts_hostname_file")"
else
  ts_hostname="${TAILSCALE_HOSTNAME:-floodman-operations}"
fi
ts_hostname="$(printf '%s' "$ts_hostname" | tr '[:upper:]' '[:lower:]' | sed 's/[^a-z0-9-]/-/g; s/--*/-/g; s/^-//; s/-$//' | cut -c1-63)"
[ -n "$ts_hostname" ] || ts_hostname='floodman-operations'
printf '%s\n' "$ts_hostname" > "$ts_hostname_file"
chmod 0600 "$ts_hostname_file" 2>/dev/null || true

install_tailscale() {
  current=''
  if [ -x "$ts_bin/tailscale" ]; then
    current="$($ts_bin/tailscale version 2>/dev/null | head -n1 | tr -d 'v' || true)"
  fi
  [ "$current" = "$ts_version" ] && [ -x "$ts_bin/tailscaled" ] && return 0

  case "$(uname -m)" in
    x86_64|amd64) ts_arch='amd64' ;;
    aarch64|arm64) ts_arch='arm64' ;;
    *) die "This Tailscale package supports Pterodactyl AMD64 or ARM64 nodes; detected $(uname -m)." ;;
  esac

  archive="tailscale_${ts_version}_${ts_arch}.tgz"
  archive_path="$ts_cache/$archive"
  checksum_path="$archive_path.sha256"
  base_url="https://pkgs.tailscale.com/stable"
  temp_extract="$ts_cache/extract-$ts_version-$ts_arch"

  log "Downloading the official Tailscale stable runtime v$ts_version for $ts_arch..."
  curl -fsSL --retry 3 --connect-timeout 20 --max-time 300 \
    -o "$archive_path.part" "$base_url/$archive" \
    || die 'Could not download Tailscale from the official package server. Confirm the Pterodactyl container has outbound HTTPS access.'
  curl -fsSL --retry 3 --connect-timeout 20 --max-time 60 \
    -o "$checksum_path" "$base_url/$archive.sha256" \
    || die 'Could not download the official Tailscale checksum.'
  mv "$archive_path.part" "$archive_path"

  expected="$(awk 'NF {print $1; exit}' "$checksum_path")"
  actual="$(sha256sum "$archive_path" | awk '{print $1}')"
  [ -n "$expected" ] && [ "$actual" = "$expected" ] \
    || die 'The downloaded Tailscale archive did not match the official SHA-256 checksum.'

  rm -rf "$temp_extract"
  mkdir -p "$temp_extract"
  tar -xzf "$archive_path" -C "$temp_extract" || die 'Could not extract the verified Tailscale archive.'
  extracted="$(find "$temp_extract" -mindepth 1 -maxdepth 1 -type d -name 'tailscale_*' | head -n1)"
  [ -x "$extracted/tailscale" ] && [ -x "$extracted/tailscaled" ] \
    || die 'The verified Tailscale archive did not contain the expected binaries.'
  cp "$extracted/tailscale" "$ts_bin/tailscale"
  cp "$extracted/tailscaled" "$ts_bin/tailscaled"
  chmod 0755 "$ts_bin/tailscale" "$ts_bin/tailscaled"
  rm -rf "$temp_extract"
  log "Installed Tailscale $($ts_bin/tailscale version | head -n1)."
}

start_bootstrap_tailscaled() {
  rm -f "$ts_socket"
  "$ts_bin/tailscaled" \
    --tun=userspace-networking \
    --statedir="$ts_state" \
    --socket="$ts_socket" \
    --port=0 \
    >"$ts_logs/tailscaled-bootstrap.log" 2>&1 &
  ts_boot_pid=$!
  waited=0
  while ! "$ts_bin/tailscale" --socket="$ts_socket" status --json >/dev/null 2>&1; do
    kill -0 "$ts_boot_pid" 2>/dev/null || {
      tail -n 80 "$ts_logs/tailscaled-bootstrap.log" >&2 || true
      die 'The Tailscale daemon stopped during bootstrap.'
    }
    [ "$waited" -lt 90 ] || die 'Tailscale did not create its control socket within 90 seconds.'
    sleep 2
    waited=$((waited + 2))
  done
}

stop_bootstrap_tailscaled() {
  if [ "${ts_boot_pid:-}" ]; then
    kill "$ts_boot_pid" 2>/dev/null || true
    wait "$ts_boot_pid" 2>/dev/null || true
    ts_boot_pid=''
  fi
  rm -f "$ts_socket"
}

wait_for_tailscale_running() {
  waited=0
  while :; do
    status_json="$($ts_bin/tailscale --socket="$ts_socket" status --json 2>/dev/null || printf '{}')"
    backend="$(printf '%s' "$status_json" | jq -r '.BackendState // empty')"
    [ "$backend" = 'Running' ] && return 0
    if [ "$backend" = 'NeedsMachineAuth' ]; then
      log 'The Tailscale server is waiting for device approval. Approve floodman-operations in Tailscale Admin → Machines.'
    fi
    [ "$waited" -lt 300 ] || die "Tailscale did not enter Running state (last state: ${backend:-unknown})."
    sleep 3
    waited=$((waited + 3))
  done
}

configure_tailscale_serve() {
  serve_log="$ts_logs/serve-bootstrap.log"
  : > "$serve_log"
  "$ts_bin/tailscale" --socket="$ts_socket" serve reset >>"$serve_log" 2>&1 || true
  for spec in \
    '8443:http://127.0.0.1:9000' \
    '8444:http://127.0.0.1:9001' \
    '8445:http://127.0.0.1:9004' \
    '8446:http://127.0.0.1:9002' \
    '8447:http://127.0.0.1:9003'
  do
    serve_port="${spec%%:*}"
    serve_target="${spec#*:}"
    if ! "$ts_bin/tailscale" --socket="$ts_socket" serve --bg --yes --https="$serve_port" "$serve_target" >>"$serve_log" 2>&1; then
      cat "$serve_log" >&2
      die 'Tailscale Serve could not enable private HTTPS. In Tailscale Admin → DNS, enable MagicDNS and HTTPS Certificates, then restart Floodman.'
    fi
  done
}


configure_public_signing_funnel() {
  funnel_log="$ts_logs/funnel-bootstrap.log"
  : > "$funnel_log"
  rm -f "$ts_public_signing_ready_marker"
  "$ts_bin/tailscale" --socket="$ts_socket" funnel reset >>"$funnel_log" 2>&1 || true

  # A single loopback gateway owns every public path. This prevents the root
  # signing proxy from swallowing /mobile-api requests and returning HTML.
  if "$ts_bin/tailscale" --socket="$ts_socket" funnel --bg --yes --https=443 http://127.0.0.1:9010 >>"$funnel_log" 2>&1; then
    touch "$ts_public_signing_ready_marker"
    cat > "$ts_public_signing_status_file" <<FUNNEL_ACTIVE
status=active
public_url=https://${ts_fqdn}
customer_url=https://${ts_fqdn}/customer
mobile_api_url=https://${ts_fqdn}/mobile-api
customer_payments=active
mobile_api=active
message=The Floodman public gateway routes signing, customer payments, and the device-authenticated Android API through one HTTPS Funnel.
FUNNEL_ACTIVE
    chmod 0640 "$ts_public_signing_status_file" 2>/dev/null || true
    "$ts_bin/tailscale" --socket="$ts_socket" funnel status --json >>"$funnel_log" 2>&1 || true
    return 0
  fi

  reason="$(tail -n 20 "$funnel_log" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g' | cut -c1-900)"
  cat > "$ts_public_signing_status_file" <<FUNNEL_PENDING
status=pending
public_url=https://${ts_fqdn}
message=Tailscale Funnel permission is not active yet. The private staff system will continue running. Add the funnel node attribute in Tailscale Access controls, then restart Floodman or wait for the watchdog retry.
detail=$reason
FUNNEL_PENDING
  chmod 0640 "$ts_public_signing_status_file" 2>/dev/null || true
  return 1
}

install_tailscale
start_bootstrap_tailscaled
trap 'stop_bootstrap_tailscaled' EXIT INT TERM

# Give a persisted node a moment to restore its control-plane state before
# deciding that fresh authentication is required.
settle=0
while :; do
  status_json="$($ts_bin/tailscale --socket="$ts_socket" status --json 2>/dev/null || printf '{}')"
  backend="$(printf '%s' "$status_json" | jq -r '.BackendState // empty')"
  case "$backend" in
    Running|Stopped|NeedsLogin|NeedsMachineAuth) break ;;
  esac
  [ "$settle" -lt 30 ] || break
  sleep 2
  settle=$((settle + 2))
done

case "$backend" in
  Running)
    ;;
  NeedsMachineAuth)
    log 'The saved Tailscale node is waiting for approval; no new auth key is required.'
    ;;
  Stopped)
    log 'Re-enabling the saved Tailscale node...'
    "$ts_bin/tailscale" --socket="$ts_socket" up \
      --hostname="$ts_hostname" \
      --accept-dns=false \
      >"$ts_logs/tailscale-up.log" 2>&1 \
      || { cat "$ts_logs/tailscale-up.log" >&2 || true; die 'Could not re-enable the saved Tailscale node.'; }
    ;;
  *)
    [ -s "$ts_auth_file" ] || die 'Create /home/container/config/tailscale-auth-key.txt with a one-off, non-ephemeral Tailscale auth key, then restart Floodman.'
    chmod 0600 "$ts_auth_file" 2>/dev/null || true
    log "Registering $ts_hostname as a private Tailscale server..."
    if ! "$ts_bin/tailscale" --socket="$ts_socket" up \
        --auth-key="file:$ts_auth_file" \
        --hostname="$ts_hostname" \
        --accept-dns=false \
        >"$ts_logs/tailscale-up.log" 2>&1; then
      cat "$ts_logs/tailscale-up.log" >&2 || true
      die 'Tailscale authentication failed. Create a new auth key and replace config/tailscale-auth-key.txt.'
    fi
    # One-off auth keys are automatically revoked by Tailscale after use. Remove
    # the local copy as soon as the persistent node state has been created.
    rm -f "$ts_auth_file"
    ;;
esac

wait_for_tailscale_running
status_json="$($ts_bin/tailscale --socket="$ts_socket" status --json)"
ts_fqdn="$(printf '%s' "$status_json" | jq -r '.Self.DNSName // empty' | sed 's/\.$//')"
[ -n "$ts_fqdn" ] || die 'Tailscale connected but did not return a MagicDNS HTTPS hostname.'
configure_tailscale_serve
if configure_public_signing_funnel; then
  funnel_bootstrap_state='active'
else
  funnel_bootstrap_state='pending'
  log 'Public customer signing is pending Tailscale Funnel permission. Floodman staff services will continue starting.'
  log 'Tailscale JSON allow-all rules do not grant Funnel by themselves; the separate nodeAttrs funnel attribute is required.'
fi

TAILSCALE_MAIN_URL="https://${ts_fqdn}:8443"
TAILSCALE_PUBLIC_SIGNING_URL="https://${ts_fqdn}"
TAILSCALE_CUSTOMER_URL="https://${ts_fqdn}/customer"
TAILSCALE_MOBILE_API_URL="https://${ts_fqdn}/mobile-api"
TAILSCALE_SIGNING_ADMIN_URL="https://${ts_fqdn}:8444"
TAILSCALE_API_URL="https://${ts_fqdn}:8445"
TAILSCALE_MAILPIT_URL="https://${ts_fqdn}:8446"
TAILSCALE_ENGINEERING_URL="https://${ts_fqdn}:8447"

cat > "$ts_urls_file" <<TS_URLS
Floodman Operations private HTTPS URLs

Main PWA: $TAILSCALE_MAIN_URL
Integrated RoomFlow: $TAILSCALE_MAIN_URL/roomflow/
Install app: $TAILSCALE_MAIN_URL/install-app
Public customer signing: $TAILSCALE_PUBLIC_SIGNING_URL
Public estimates, invoices, receipts, and payments: $TAILSCALE_CUSTOMER_URL
Android app API (no Tailscale app required): $TAILSCALE_MOBILE_API_URL
Public signing status: $funnel_bootstrap_state (see config/public-signing-status.txt)
Private signing administration: $TAILSCALE_SIGNING_ADMIN_URL
Floodman API: $TAILSCALE_API_URL/docs
Test email: $TAILSCALE_MAILPIT_URL
Engineering Sandbox: $TAILSCALE_ENGINEERING_URL/lab

The Main PWA, RoomFlow, API, Mailpit, Engineering, and private signing administration require Tailscale. The public customer-signing URL does not require Tailscale.
TS_URLS
chmod 0600 "$ts_urls_file" 2>/dev/null || true

export FLOODMAN_PUBLIC_SCHEME='https'
export FLOODMAN_PUBLIC_HOST="$ts_fqdn"
export FLOODMAN_PUBLIC_URL="$TAILSCALE_MAIN_URL"
export FLOODMAN_DOCUMENSO_URL="$TAILSCALE_PUBLIC_SIGNING_URL"
export FLOODMAN_CUSTOMER_PUBLIC_URL="$TAILSCALE_CUSTOMER_URL"
export FLOODMAN_MOBILE_API_PUBLIC_URL="$TAILSCALE_MOBILE_API_URL"
export FLOODMAN_DOCUMENSO_PRIVATE_URL="$TAILSCALE_SIGNING_ADMIN_URL"
export FLOODMAN_API_PUBLIC_URL="$TAILSCALE_API_URL"
export FLOODMAN_MAILPIT_URL="$TAILSCALE_MAILPIT_URL"
export FLOODMAN_ENGINEERING_URL="$TAILSCALE_ENGINEERING_URL"
export ROOMFLOW_WEB_URL="${TAILSCALE_MAIN_URL}/roomflow/"
export FLOODMAN_ROOMFLOW_URL="$ROOMFLOW_WEB_URL"
export TAILSCALE_PRIVATE_ENABLED='true'
export TAILSCALE_PRIVATE_FQDN="$ts_fqdn"
printf '%s\n' "$TAILSCALE_PUBLIC_SIGNING_URL" > /home/container/config/public-signing-url.txt
printf '%s\n' "$TAILSCALE_CUSTOMER_URL" > /home/container/config/public-customer-url.txt
printf '%s\n' "$TAILSCALE_MOBILE_API_URL" > /home/container/config/android-mobile-api.txt
chmod 0640 /home/container/config/public-signing-url.txt /home/container/config/public-customer-url.txt /home/container/config/android-mobile-api.txt 2>/dev/null || true
log "Private staff HTTPS is ready at $TAILSCALE_MAIN_URL"
if [ "$funnel_bootstrap_state" = active ]; then
  log "Public customer signing is ready at $TAILSCALE_PUBLIC_SIGNING_URL"
else
  log "Public customer signing is not active yet. Floodman remains online privately; see config/public-signing-status.txt."
fi

# ---------------------------------------------------------------------------
# Floodman Android device/session security
# ---------------------------------------------------------------------------
mobile_env='/home/container/config/floodman-mobile.env'
if [ ! -s "$mobile_env" ]; then
  mobile_secret="$(openssl rand -base64 48 | tr -d '\r\n')"
  cat > "$mobile_env" <<MOBILE_ENV
FLOODMAN_MOBILE_TOKEN_SECRET=$mobile_secret
FLOODMAN_MOBILE_ACCESS_TTL_SECONDS=900
FLOODMAN_MOBILE_REFRESH_TTL_DAYS=30
MOBILE_ENV
  chmod 0600 "$mobile_env" 2>/dev/null || true
  log 'Generated the persistent Floodman Android device/session key.'
fi
set -a
# shellcheck disable=SC1090
. "$mobile_env"
set +a
export FLOODMAN_MOBILE_TOKEN_SECRET FLOODMAN_MOBILE_ACCESS_TTL_SECONDS FLOODMAN_MOBILE_REFRESH_TTL_DAYS FLOODMAN_MOBILE_API_PUBLIC_URL

# ---------------------------------------------------------------------------
# Floodman online payment configuration
# ---------------------------------------------------------------------------
payments_env='/home/container/config/floodman-payments.env'
payments_example='/home/container/config/floodman-payments.env.example'
cat > "$payments_example" <<'PAYMENT_ENV_EXAMPLE'
# Start with the payment processor Sandbox. Never commit this file to GitHub or share the access token.
SQUARE_ENVIRONMENT=sandbox
SQUARE_APPLICATION_ID=replace-with-sandbox-application-id
SQUARE_ACCESS_TOKEN=replace-with-sandbox-access-token
SQUARE_LOCATION_ID=replace-with-sandbox-location-id
SQUARE_VERSION=2026-07-15
SQUARE_BASE_URL=https://connect.squareupsandbox.com
SQUARE_WEB_SDK_URL=https://sandbox.web.squarecdn.com/v1/square.js
SQUARE_VERIFY_TLS=true
FLOODMAN_PAYMENTS_ENABLED=true
PAYMENT_ENV_EXAMPLE
chmod 0600 "$payments_example" 2>/dev/null || true
if [ -s "$payments_env" ]; then
  set -a
  # shellcheck disable=SC1090
  . "$payments_env"
  set +a
  log 'Loaded Floodman payment configuration from config/floodman-payments.env.'
else
  : "${SQUARE_ENVIRONMENT:=local}"
  : "${FLOODMAN_PAYMENTS_ENABLED:=true}"
  log 'Floodman Payments is in local test mode. Copy config/floodman-payments.env.example to config/floodman-payments.env to connect the payment Sandbox.'
fi
case "${SQUARE_ENVIRONMENT:-local}" in
  sandbox)
    : "${SQUARE_BASE_URL:=https://connect.squareupsandbox.com}"
    : "${SQUARE_WEB_SDK_URL:=https://sandbox.web.squarecdn.com/v1/square.js}"
    ;;
  production)
    : "${SQUARE_BASE_URL:=https://connect.squareup.com}"
    : "${SQUARE_WEB_SDK_URL:=https://web.squarecdn.com/v1/square.js}"
    ;;
  *)
    SQUARE_ENVIRONMENT='local'
    : "${SQUARE_BASE_URL:=http://127.0.0.1:${ENGINEERING_PORT:-9003}/square}"
    : "${SQUARE_WEB_SDK_URL:=}"
    ;;
esac
export SQUARE_ENVIRONMENT SQUARE_BASE_URL SQUARE_WEB_SDK_URL SQUARE_APPLICATION_ID SQUARE_ACCESS_TOKEN SQUARE_LOCATION_ID SQUARE_VERSION SQUARE_VERIFY_TLS FLOODMAN_PAYMENTS_ENABLED FLOODMAN_CUSTOMER_PUBLIC_URL FLOODMAN_MOBILE_API_PUBLIC_URL
export OFFICE_SESSION_COOKIE_SECURE='true'

# Runtime markers and sockets must never survive a Pterodactyl container restart.
rm -f \
  "$run_dir/databases-ready" \
  "$run_dir/gauzy-finalized" \
  "$run_dir/owner-linked" \
  "$run_dir/supervisord.pid" \
  "$run_dir/postgres-password" \
  "$run_dir/postgres/.s.PGSQL.5432" \
  "$run_dir/postgres/.s.PGSQL.5432.lock"
rm -rf "$run_dir/documenso-cert"
log 'Cleared stale database readiness markers and PostgreSQL sockets.'

# Prepare a persistent, pinned copy of RoomFlow inside the Floodman origin.
roomflow_target='/home/container/data/roomflow/current'
roomflow_overlay="$overlay_root/roomflow"
mkdir -p "$(dirname "$roomflow_target")"
python3 "$roomflow_overlay/prepare-roomflow.py" \
  --target "$roomflow_target" \
  --overlay "$roomflow_overlay" \
  || die 'Could not prepare the integrated RoomFlow workspace.'
[ -s "$roomflow_target/index.html" ] || die 'The integrated RoomFlow workspace did not produce index.html.'
log 'Integrated RoomFlow is prepared under /roomflow/ and linked to Floodman customer files.'

cat > "$hotfix/start-competitor-api.sh" <<'COMPETITOR_API'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh

fm_log 'Waiting for the active PostgreSQL instance and Competitor Intelligence grants...'
while :; do
  if [ -f "$FM_RUN/databases-ready" ] && pg_isready -h 127.0.0.1 -p 5432 -U floodman >/dev/null 2>&1; then
    if PGPASSWORD="$AI_DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$AI_DB_USER" -d floodman -Atc 'SELECT 1' 2>/dev/null | grep -q '^1$'; then
      break
    fi
  fi
  sleep 2
done

overlay="$FM_HOME/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/competitor-intel"
[ -r "$overlay/app/main.py" ] || fm_die 'The Floodman Competitor Intelligence v4.6.7 overlay is missing.'
cd "$overlay"
export PYTHONPATH="/opt/pydeps/competitor-intel:$overlay:/opt/floodman/competitor-intel"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8090 --no-access-log
COMPETITOR_API

cat > "$hotfix/start-competitor-scheduler.sh" <<'COMPETITOR_SCHEDULER'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh

wait_for_database() {
  while :; do
    if [ -f "$FM_RUN/databases-ready" ] && pg_isready -h 127.0.0.1 -p 5432 -U floodman >/dev/null 2>&1; then
      if PGPASSWORD="$AI_DB_PASSWORD" psql -h 127.0.0.1 -p 5432 -U "$AI_DB_USER" -d floodman -Atc 'SELECT 1' 2>/dev/null | grep -q '^1$'; then
        return 0
      fi
    fi
    sleep 2
  done
}

overlay="$FM_HOME/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/competitor-intel"
[ -r "$overlay/app/scheduler.py" ] || fm_die 'The Floodman Competitor Intelligence scheduler overlay is missing.'

while :; do
  fm_log 'Waiting for the active PostgreSQL instance and Competitor Intelligence grants...'
  wait_for_database
  cd "$overlay"
  export PYTHONPATH="/opt/pydeps/competitor-intel:$overlay:/opt/floodman/competitor-intel"
  set +e
  python3 -m app.scheduler
  code=$?
  set -e
  fm_warn "Competitor Intelligence scheduler exited with status $code. Waiting before retrying."
  sleep 10
done
COMPETITOR_SCHEDULER

cat > "$hotfix/floodman-boot-guard.js" <<'BOOT_GUARD'
(() => {
  'use strict';
  const release = 'pterodactyl-mobile-v4.6.7';
  const started = Date.now();

  function routeName() {
    return String(window.location.hash || '').replace(/^#\/?/, '').split('?')[0].replace(/^\/+|\/+$/g, '');
  }

  async function probeAuth() {
    try {
      const response = await fetch('/api/auth/authenticated', {
        cache: 'no-store',
        credentials: 'same-origin',
        headers: { accept: 'application/json,text/plain,*/*' }
      });
      const text = await response.text();
      let payload = null;
      try { payload = JSON.parse(text); } catch (_) { payload = text.trim(); }
      const authenticated = payload === true || payload === 'true' || payload?.authenticated === true || Boolean(payload?.user?.id);
      return { ok: response.status < 500, status: response.status, authenticated, payload };
    } catch (error) {
      return { ok: false, status: 0, authenticated: false, error: String(error) };
    }
  }

  async function probe(path) {
    try {
      const response = await fetch(path, { cache: 'no-store', credentials: 'same-origin' });
      return { ok: response.status < 500, status: response.status };
    } catch (error) {
      return { ok: false, status: 0, error: String(error) };
    }
  }

  function appAppearsReady() {
    const selectors = [
      'nb-layout', 'nb-auth', 'nb-card', 'form input[type="password"]',
      'form input[type="email"]', '[class*="dashboard"]', '[class*="login"]',
      '[class*="workspace"]', '[class*="sidebar"]', 'router-outlet + *'
    ];
    return selectors.some((selector) => document.querySelector(selector));
  }

  function go(path) {
    const target = `/index.html?desktop=1&fm=${encodeURIComponent(release)}#/${path}`;
    if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== target) window.location.replace(target);
  }

  function showRecovery(api, hub) {
    if (document.getElementById('floodman-boot-recovery')) return;
    const panel = document.createElement('section');
    panel.id = 'floodman-boot-recovery';
    panel.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;padding:22px;background:#eef5fb;color:#102443;font-family:Inter,Segoe UI,Arial,sans-serif';
    panel.innerHTML = `
      <div style="width:min(560px,100%);background:#fff;border-radius:22px;padding:30px;box-shadow:0 24px 70px rgba(15,35,65,.18)">
        <div style="font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#0ea5e9">Floodman Operations</div>
        <h1 style="margin:10px 0 8px;font-size:25px">Floodman ERP browser did not finish rendering</h1>
        <p style="margin:0 0 18px;line-height:1.55;color:#52657c">The Hub and ERP API answered, but the embedded ERP browser did not draw its login or dashboard within 90 seconds.</p>
        <div style="display:grid;grid-template-columns:1fr 1fr;gap:10px;margin:16px 0">
          <div style="padding:12px;border-radius:12px;background:#f3f7fb"><b>Hub</b><br><span>${hub.ok ? 'responding' : 'unavailable'} (${hub.status || 'no response'})</span></div>
          <div style="padding:12px;border-radius:12px;background:#f3f7fb"><b>Floodman ERP API</b><br><span>${api.ok ? 'responding' : 'unavailable'} (${api.status || 'no response'})</span></div>
        </div>
        <div style="display:flex;flex-wrap:wrap;gap:10px">
          <a href="/full-erp?target=login" style="display:inline-block;padding:12px 16px;border-radius:12px;background:#0f5ea8;color:#fff;text-decoration:none;font-weight:750">Open Floodman login</a>
          <a href="/floodman-status.html?fm=${release}" style="display:inline-block;padding:12px 16px;border-radius:12px;background:#e7eef6;color:#102443;text-decoration:none;font-weight:750">Open status page</a>
          <button type="button" id="floodman-reload" style="padding:12px 16px;border:0;border-radius:12px;background:#e7eef6;color:#102443;font-weight:750">Reload without cache</button>
        </div>
        <p style="margin:16px 0 0;font-size:12px;color:#728197">Release ${release}</p>
      </div>`;
    document.body.appendChild(panel);
    document.getElementById('floodman-reload').addEventListener('click', () => {
      const url = new URL(window.location.href);
      url.searchParams.set('fm', release + '-' + Date.now());
      window.location.replace(url.toString());
    });
  }

  async function check() {
    if (appAppearsReady()) return;
    const route = routeName();
    const [api, hub] = await Promise.all([probeAuth(), probe('/health/live')]);

    // The endpoint intentionally returns HTTP 200 with the JSON value false
    // for an unauthenticated browser. Treat that as a login redirect, not as
    // an ERP loading failure.
    if (api.ok && !api.authenticated) {
      if (!/^auth\/(login|register|forgot-password|reset-password)/.test(route)) {
        go('auth/login');
        return;
      }
      if (Date.now() - started < 120000) {
        window.setTimeout(check, 3000);
        return;
      }
    }

    if (api.ok && api.authenticated && (!route || route === 'pages')) {
      go('pages/dashboard');
      return;
    }

    if (!appAppearsReady() && Date.now() - started > 90000) {
      showRecovery(api, hub);
      return;
    }
    window.setTimeout(check, 3000);
  }

  window.setTimeout(check, 2500);
})();
BOOT_GUARD

cat > "$hotfix/floodman-status.html" <<'STATUS_PAGE'
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1">
  <meta http-equiv="cache-control" content="no-store">
  <title>Floodman Operations status</title>
  <style>
    html,body{min-height:100%;margin:0;font-family:Inter,Segoe UI,Arial,sans-serif;background:#eef5fb;color:#102443}
    body{display:grid;place-items:center;padding:22px;box-sizing:border-box}
    main{width:min(620px,100%);background:#fff;border-radius:24px;padding:30px;box-shadow:0 24px 70px rgba(15,35,65,.16)}
    h1{margin:8px 0 6px}.muted{color:#52657c;line-height:1.5}.grid{display:grid;gap:10px;margin:20px 0}.row{display:flex;justify-content:space-between;gap:18px;padding:13px;border-radius:12px;background:#f3f7fb}.ok{color:#0b7a50}.bad{color:#b42318}.actions{display:flex;flex-wrap:wrap;gap:10px}.actions a,.actions button{border:0;border-radius:12px;padding:12px 15px;font-weight:750;text-decoration:none;cursor:pointer}.primary{background:#0f5ea8;color:#fff}.secondary{background:#e7eef6;color:#102443}
  </style>
</head>
<body><main>
  <div style="font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#0ea5e9">Floodman Operations</div>
  <h1>Runtime status</h1>
  <p class="muted">This page checks the Floodman Operations Hub, Floodman ERP API, Floodman workflow API, signing, test email, and Engineering Sandbox from the same browser you are using.</p>
  <div id="checks" class="grid"><div class="row"><b>Checks</b><span>running…</span></div></div>
  <div class="actions"><a class="primary" href="/full-erp?target=login">Open Floodman login</a><button class="secondary" id="again">Run again</button></div>
  <p class="muted" style="font-size:12px;margin-top:18px">Release pterodactyl-mobile-v4.6.7</p>
</main>
<script>
(() => {
  const base = `${location.protocol}//${location.hostname}`;
  const checks = [
    ['Main Hub', `${location.origin}/health/live`],
    ['Floodman ERP API', `${location.origin}/api/auth/authenticated`, true],
    ['Floodman API', `${base}:8445/health/ready`],
    ['Documenso', `${base}:8444/api/health`, true],
    ['Mailpit', `${base}:8446/api/v1/info`, true],
    ['Engineering Sandbox', `${base}:8447/health/live`]
  ];
  const root = document.getElementById('checks');
  async function probe(label, url, allow4xx) {
    try {
      const r = await fetch(url, {cache:'no-store', mode:'cors'});
      const ok = r.ok || (allow4xx && r.status >= 400 && r.status < 500);
      return [label, ok, r.status, url];
    } catch (e) { return [label, false, 0, url]; }
  }
  async function run() {
    root.innerHTML = '<div class="row"><b>Checks</b><span>running…</span></div>';
    const results = await Promise.all(checks.map(c => probe(...c)));
    root.innerHTML = '';
    for (const [label, ok, status, url] of results) {
      const row = document.createElement('div'); row.className='row';
      row.innerHTML = `<b>${label}</b><span class="${ok?'ok':'bad'}">${ok?'ready':'not ready'}${status?' · HTTP '+status:''}</span>`;
      row.title=url; root.appendChild(row);
    }
  }
  document.getElementById('again').onclick=run; run();
})();
</script></body></html>
STATUS_PAGE

cat > "$hotfix/start-office-console.sh" <<'START_OFFICE'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
if [ -r /home/container/config/floodman-mobile.env ]; then set -a; . /home/container/config/floodman-mobile.env; set +a; fi
while [ ! -f "$FM_RUN/databases-ready" ] || [ ! -f "$FM_RUN/gauzy-finalized" ]; do sleep 2; done
overlay="$FM_HOME/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/office-console"
[ -r "$overlay/app/main.py" ] || fm_die 'The Floodman mobile Office overlay is missing.'
cd "$overlay"
export PYTHONPATH="/opt/pydeps/office-console:$overlay:/opt/floodman/office-console"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8700 --no-access-log
START_OFFICE

cat > "$hotfix/start-hub.sh" <<'START_HUB'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
while [ ! -f "$FM_RUN/gauzy-finalized" ]; do sleep 2; done
fm_wait_http "http://127.0.0.1:8700/health/live" 600 false || fm_die "Floodman Office did not become ready before Hub startup."

runtime_web="$FM_HOME/runtime/gauzy-web"
config_hash="$(printf '%s\n' "$SERVER_PORT|$FLOODMAN_COMPANY_NAME|pterodactyl-mobile-v4.6.7" | sha256sum | awk '{print $1}')"
old_hash="$(cat "$runtime_web/.floodman-config-hash" 2>/dev/null || true)"
if [ "$config_hash" != "$old_hash" ] || [ ! -s "$runtime_web/index.html" ]; then
  fm_log "Preparing the branded Floodman ERP browser with same-origin API routing..."
  rm -rf "$runtime_web"
  mkdir -p "$runtime_web"
  cp -a /opt/gauzy-web-pristine/. "$runtime_web/"
  cd "$runtime_web"

  # Use a deterministic localhost placeholder in the browser bundle. The public
  # Nginx layer rewrites it to the actual host and scheme of every request. This
  # prevents a blank or incorrect Public Host variable from trapping Floodman ERP on its loader.
  browser_origin="http://localhost:${SERVER_PORT}"
  API_BASE_URL="$browser_origin" \
  CLIENT_BASE_URL="$browser_origin" \
  APP_LINK="$browser_origin" \
  APP_LOGO="${browser_origin}/floodman-brand/floodman-wordmark.svg" \
  PLATFORM_LOGO="${browser_origin}/floodman-brand/floodman-wordmark.svg" \
  NO_INTERNET_LOGO="${browser_origin}/floodman-brand/floodman-wordmark.svg" \
    envsubst < replacements.sed > replacements_values.sed

  for file in ./*.js; do
    [ -f "$file" ] || continue
    sed -i -f replacements_values.sed "$file"
  done

  if grep -l 'DOCKER_API_BASE_URL\|DOCKER_CLIENT_BASE_URL' ./*.js >/dev/null 2>&1; then
    fm_die 'The Floodman ERP browser still contains unresolved API placeholders.'
  fi
  if grep -l '/api/api/' ./*.js >/dev/null 2>&1; then
    fm_die 'The Floodman ERP browser contains an invalid duplicate /api/api path.'
  fi
  printf '%s' "$config_hash" > .floodman-config-hash
fi

mkdir -p "$FM_HOME/runtime/hub"
envsubst '${HUB_TITLE} ${HUB_RELEASE} ${HUB_OFFICE_URL} ${HUB_ROOMFLOW_URL} ${HUB_DOCUMENSO_URL} ${HUB_MAILPIT_URL} ${HUB_ENGINEERING_URL} ${HUB_API_URL} ${HUB_COMPETITOR_URL} ${HUB_SYNC_STATUS_URL} ${HUB_REMOTE_ACCESS_ENABLED} ${HUB_REMOTE_DOCUMENSO_PORT} ${HUB_REMOTE_MAILPIT_PORT} ${HUB_REMOTE_ENGINEERING_PORT} ${HUB_REMOTE_API_PORT} ${HUB_REMOTE_DOCUMENSO_URL} ${HUB_REMOTE_MAILPIT_URL} ${HUB_REMOTE_ENGINEERING_URL} ${HUB_REMOTE_API_URL}' \
  < "$FM_HOME/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/hub/hub-config.js.template" \
  > "$FM_HOME/runtime/hub/floodman-hub-config.js"
envsubst '${SERVER_PORT} ${HUB_RELEASE}' \
  < "$FM_HOME/runtime/floodman-v4.6.7/nginx.conf.template" \
  > "$FM_CONFIG/nginx.conf"

fm_log "Starting Floodman Operations Hub on port $SERVER_PORT with same-origin browser routing..."
exec nginx -e "$FM_LOGS/nginx-bootstrap.log" -c "$FM_CONFIG/nginx.conf" -g 'daemon off;'
START_HUB

# Use the verified v4.6.7 Nginx template, which serves the manifest, service worker, install page, icons, and safe offline shell.
cp "$overlay_root/aio/nginx.conf.template" "$hotfix/nginx.conf.template"


# Add a dedicated loopback-only public gateway. Tailscale Funnel points only to
# this listener, so /mobile-api can never fall through to Floodman Signing.
python3 - "$hotfix/nginx.conf.template" <<'PY_PUBLIC_GATEWAY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "listen 127.0.0.1:9010;" not in text:
    gateway = '\n\n    # Public customer gateway. Only signing, customer portal/payment pages, and\n    # the Android Mobile API are exposed. Floodman Office stays private.\n    server {\n        listen 127.0.0.1:9010;\n        server_name floodman-public-gateway;\n\n        access_log off;\n        client_max_body_size 50m;\n        add_header X-Content-Type-Options "nosniff" always;\n        add_header Referrer-Policy "same-origin" always;\n\n        location = /__floodman_public_gateway_health {\n            default_type application/json;\n            add_header Cache-Control "no-store" always;\n            return 200 \'{"status":"ok","service":"floodman-public-gateway","release":"v4.6.7"}\';\n        }\n\n        location = /mobile-api {\n            return 308 /mobile-api/;\n        }\n\n        location ^~ /mobile-api/ {\n            proxy_pass http://127.0.0.1:8700;\n            proxy_http_version 1.1;\n            proxy_set_header Host $http_host;\n            proxy_set_header X-Real-IP $remote_addr;\n            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n            proxy_set_header X-Forwarded-Proto https;\n            proxy_set_header X-Forwarded-Host $http_host;\n            proxy_set_header Upgrade $http_upgrade;\n            proxy_set_header Connection $connection_upgrade;\n            proxy_read_timeout 180s;\n            proxy_send_timeout 180s;\n            proxy_buffering off;\n            add_header Cache-Control "no-store" always;\n        }\n\n        location = /customer {\n            return 308 /customer/;\n        }\n\n        location ^~ /customer/ {\n            proxy_pass http://127.0.0.1:8700;\n            proxy_http_version 1.1;\n            proxy_set_header Host $http_host;\n            proxy_set_header X-Real-IP $remote_addr;\n            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n            proxy_set_header X-Forwarded-Proto https;\n            proxy_set_header X-Forwarded-Host $http_host;\n            proxy_read_timeout 180s;\n            proxy_send_timeout 180s;\n            proxy_buffering off;\n        }\n\n        # Every other path belongs to Floodman Signing. Office, ERP, Mailpit,\n        # Engineering, and private API documentation are not reachable here.\n        location / {\n            proxy_pass http://127.0.0.1:9001;\n            proxy_http_version 1.1;\n            proxy_set_header Host $http_host;\n            proxy_set_header X-Real-IP $remote_addr;\n            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n            proxy_set_header X-Forwarded-Proto https;\n            proxy_set_header X-Forwarded-Host $http_host;\n            proxy_set_header Upgrade $http_upgrade;\n            proxy_set_header Connection $connection_upgrade;\n            proxy_read_timeout 300s;\n            proxy_send_timeout 300s;\n            proxy_buffering off;\n        }\n    }\n'
    index = text.rfind("\n}")
    if index < 0:
        raise SystemExit("Could not locate the Nginx http block terminator")
    text = text[:index] + gateway + text[index:]
    path.write_text(text, encoding="utf-8")
PY_PUBLIC_GATEWAY



cat > "$hotfix/start-documenso-private.sh" <<'START_DOCUMENSO_PRIVATE'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
tries=0
while [ ! -f "$FM_RUN/databases-ready" ]; do
  tries=$((tries + 1)); [ "$tries" -lt 900 ] || fm_die "Database bootstrap did not finish before Floodman Signing startup."
  sleep 2
done
cert="$FM_DATA/documenso/cert.p12"
if [ ! -s "$cert" ]; then
  fm_log "Generating persistent Floodman Signing certificate..."
  tmp="$FM_RUN/documenso-cert"
  rm -rf "$tmp" && mkdir -p "$tmp"
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3650 \
    -subj "/CN=Floodman Test Signing/O=Floodman/C=US" \
    -keyout "$tmp/key.pem" -out "$tmp/cert.pem" >/dev/null 2>&1
  openssl pkcs12 -export -out "$tmp/cert.p12" -inkey "$tmp/key.pem" -in "$tmp/cert.pem" \
    -passout pass:"$DOCUMENSO_SIGNING_PASSPHRASE" -name "Floodman Test Signing" >/dev/null 2>&1
  openssl pkcs12 -in "$tmp/cert.p12" -passin pass:"$DOCUMENSO_SIGNING_PASSPHRASE" -noout
  mv "$tmp/cert.p12" "$cert"
  chmod 0600 "$cert"
  rm -rf "$tmp"
fi
fm_log "Starting Floodman Signing privately on 127.0.0.1:$DOCUMENSO_PORT..."
cd /opt/documenso/apps/remix
export PATH="/opt/documenso-runtime/usr/local/bin:$PATH"
npx prisma migrate deploy --schema ../../packages/prisma/schema.prisma
export HOSTNAME=127.0.0.1
exec node build/server/main.js
START_DOCUMENSO_PRIVATE

cat > "$hotfix/start-mailpit-private.sh" <<'START_MAILPIT_PRIVATE'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
exec /usr/local/bin/mailpit --listen "127.0.0.1:${MAILPIT_PORT}" --smtp "127.0.0.1:1026" --database "$FM_DATA/mailpit/mailpit.db" --max 1000
START_MAILPIT_PRIVATE

cat > "$hotfix/start-engineering-private.sh" <<'START_ENGINEERING_PRIVATE'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
export LAB_STATE_DIR="$FM_DATA/lab-state"
overlay="$FM_HOME/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/local-lab"
[ -r "$overlay/app/main.py" ] || fm_die 'The Floodman Engineering Sandbox v4.6.7 overlay is missing.'
cd "$overlay"
export PYTHONPATH="/opt/pydeps/local-lab:$overlay:/opt/floodman/local-lab"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$ENGINEERING_PORT" --no-access-log
START_ENGINEERING_PRIVATE

cat > "$hotfix/start-orchestrator-private.sh" <<'START_ORCHESTRATOR_PRIVATE'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
while [ ! -f "$FM_RUN/databases-ready" ] || [ ! -f "$FM_RUN/gauzy-finalized" ]; do sleep 2; done
overlay="$FM_HOME/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/orchestrator"
[ -r "$overlay/app/main.py" ] || fm_die 'The Floodman API v4.6.7 overlay is missing.'
cd "$overlay"
export PYTHONPATH="/opt/pydeps/orchestrator:$overlay:/opt/floodman/orchestrator"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port "$FLOODMAN_API_PORT" --proxy-headers --forwarded-allow-ips '*' --no-access-log
START_ORCHESTRATOR_PRIVATE

cat > "$hotfix/start-tailscaled.sh" <<'START_TAILSCALED'
#!/bin/sh
set -eu
ts_bin='/home/container/runtime/tailscale/bin'
ts_state='/home/container/data/tailscale'
ts_run='/home/container/run/tailscale'
ts_socket="$ts_run/tailscaled.sock"
mkdir -p "$ts_state" "$ts_run" /home/container/logs/tailscale
rm -f "$ts_socket"
exec "$ts_bin/tailscaled" \
  --tun=userspace-networking \
  --statedir="$ts_state" \
  --socket="$ts_socket" \
  --port=0
START_TAILSCALED

cat > "$hotfix/start-tailscale-serve.sh" <<'START_TAILSCALE_SERVE'
#!/bin/sh
set -eu
ts='/home/container/runtime/tailscale/bin/tailscale'
socket='/home/container/run/tailscale/tailscaled.sock'
log='/home/container/logs/tailscale/serve-watchdog.log'
mkdir -p /home/container/logs/tailscale

wait_running() {
  while :; do
    state="$($ts --socket="$socket" status --json 2>/dev/null | jq -r '.BackendState // empty' || true)"
    [ "$state" = 'Running' ] && return 0
    if [ "$state" = 'NeedsLogin' ]; then
      printf '[Floodman][Tailscale] Re-authentication is required. Create config/tailscale-auth-key.txt and restart the server.\n' >&2
    fi
    sleep 3
  done
}

apply_routes() {
  : > "$log"
  for spec in \
    '8443:http://127.0.0.1:9000' \
    '8444:http://127.0.0.1:9001' \
    '8445:http://127.0.0.1:9004' \
    '8446:http://127.0.0.1:9002' \
    '8447:http://127.0.0.1:9003'
  do
    port="${spec%%:*}"
    target="${spec#*:}"
    "$ts" --socket="$socket" serve --bg --yes --https="$port" "$target" >>"$log" 2>&1 || return 1
  done
}

while :; do
  wait_running
  if apply_routes; then
    printf '[Floodman][Tailscale] Private HTTPS Serve routes are active.\n'
    while sleep 60; do
      state="$($ts --socket="$socket" status --json 2>/dev/null | jq -r '.BackendState // empty' || true)"
      [ "$state" = 'Running' ] || break
      "$ts" --socket="$socket" serve status --json >/dev/null 2>&1 || break
    done
  else
    printf '[Floodman][Tailscale] Could not apply Serve routes; retrying in 30 seconds.\n' >&2
    tail -n 40 "$log" >&2 2>/dev/null || true
    sleep 30
  fi
done
START_TAILSCALE_SERVE

cat > "$hotfix/start-tailscale-funnel.sh" <<'START_TAILSCALE_FUNNEL'
#!/bin/sh
set -eu
ts='/home/container/runtime/tailscale/bin/tailscale'
socket='/home/container/run/tailscale/tailscaled.sock'
log='/home/container/logs/tailscale/funnel-watchdog.log'
status_file='/home/container/config/public-signing-status.txt'
ready_marker='/home/container/run/public-signing-ready'
mkdir -p /home/container/logs/tailscale /home/container/config /home/container/run
last_state=''

wait_running() {
  while :; do
    state="$($ts --socket="$socket" status --json 2>/dev/null | jq -r '.BackendState // empty' || true)"
    [ "$state" = 'Running' ] && return 0
    sleep 3
  done
}

record_pending() {
  reason="$(tail -n 20 "$log" 2>/dev/null | tr '\n' ' ' | sed 's/[[:space:]][[:space:]]*/ /g' | cut -c1-900)"
  cat > "$status_file" <<FUNNEL_PENDING
status=pending
message=Tailscale Funnel permission is not active yet. Private Floodman remains available through Tailscale Serve. Add nodeAttrs attr funnel in Tailscale Access controls.
detail=$reason
FUNNEL_PENDING
  chmod 0640 "$status_file" 2>/dev/null || true
  rm -f "$ready_marker"
}

record_active() {
  fqdn="$($ts --socket="$socket" status --json 2>/dev/null | jq -r '.Self.DNSName // empty' | sed 's/\.$//' || true)"
  cat > "$status_file" <<FUNNEL_ACTIVE
status=active
public_url=https://${fqdn}
customer_url=https://${fqdn}/customer
mobile_api_url=https://${fqdn}/mobile-api
customer_payments=active
mobile_api=active
message=The Floodman public gateway routes signing, customer payments, and the device-authenticated Android API through one HTTPS Funnel.
FUNNEL_ACTIVE
  chmod 0640 "$status_file" 2>/dev/null || true
  touch "$ready_marker"
}

while :; do
  wait_running
  : > "$log"
  if "$ts" --socket="$socket" funnel --bg --yes --https=443 http://127.0.0.1:9010 >>"$log" 2>&1; then
    record_active
    if [ "$last_state" != 'active' ]; then
      printf '[Floodman][Tailscale] Public Floodman gateway is active on HTTPS port 443.\n'
    fi
    last_state='active'
    while sleep 60; do
      state="$($ts --socket="$socket" status --json 2>/dev/null | jq -r '.BackendState // empty' || true)"
      [ "$state" = 'Running' ] || break
      "$ts" --socket="$socket" funnel status --json >/dev/null 2>&1 || break
    done
  else
    record_pending
    if [ "$last_state" != 'pending' ]; then
      printf '[Floodman][Tailscale] Public gateway is pending Funnel permission. The private staff system remains online. See config/public-signing-status.txt.\n' >&2
    fi
    last_state='pending'
    sleep 300
  fi
done
START_TAILSCALE_FUNNEL

cat > "$hotfix/suite-monitor.sh" <<'SUITE_MONITOR'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh

# Public URL variables are created by start-suite.sh. Source them instead of
# assuming non-exported shell locals survived into this Supervisor process.
[ -r "$FM_CONFIG/public-urls.env" ] && . "$FM_CONFIG/public-urls.env"
: "${MAIN_PUBLIC_URL:=${FLOODMAN_PUBLIC_URL:-http://127.0.0.1:${SERVER_PORT}}}"
: "${DOCUMENSO_PUBLIC_URL:=${FLOODMAN_DOCUMENSO_URL:-http://127.0.0.1:${DOCUMENSO_PORT}}}"
: "${MAILPIT_PUBLIC_URL:=${FLOODMAN_MAILPIT_URL:-http://127.0.0.1:${MAILPIT_PORT}}}"
: "${ENGINEERING_PUBLIC_URL:=${FLOODMAN_ENGINEERING_URL:-http://127.0.0.1:${ENGINEERING_PORT}}}"
: "${API_PUBLIC_URL:=${FLOODMAN_API_PUBLIC_URL:-http://127.0.0.1:${FLOODMAN_API_PORT}}}"
: "${ROOMFLOW_WEB_URL:=${MAIN_PUBLIC_URL}/roomflow/}"
export MAIN_PUBLIC_URL DOCUMENSO_PUBLIC_URL MAILPIT_PUBLIC_URL ENGINEERING_PUBLIC_URL API_PUBLIC_URL ROOMFLOW_WEB_URL

fm_log 'Running Floodman startup readiness checks...'
fm_wait_http "http://127.0.0.1:${SERVER_PORT}/health/live" 2700 false || fm_die 'Main Hub did not become ready.'
fm_wait_http "http://127.0.0.1:${SERVER_PORT}/full-erp" 120 false || fm_die 'The authentication-aware full ERP launcher is unavailable.'
fm_wait_http "http://127.0.0.1:${SERVER_PORT}/floodman-boot-guard.js" 120 false || fm_die 'The full ERP browser guard is unavailable.'
fm_wait_http "http://127.0.0.1:${SERVER_PORT}/api/auth/authenticated" 120 true || fm_die 'The Hub cannot reach the Floodman ERP authentication endpoint.'
fm_wait_http "http://127.0.0.1:${SERVER_PORT}/roomflow/" 300 false || fm_die 'Integrated RoomFlow did not become ready.'
fm_wait_tcp 127.0.0.1 3000 600 || fm_die 'Floodman ERP API did not open port 3000.'
fm_wait_http "http://127.0.0.1:${FLOODMAN_API_PORT}/health/ready" 180 false || fm_die 'Floodman API is unavailable.'
fm_wait_http "http://127.0.0.1:${DOCUMENSO_PORT}/api/health" 600 true || fm_die 'Floodman Signing is unavailable.'
fm_wait_http 'http://127.0.0.1:9010/__floodman_public_gateway_health' 600 false || fm_die 'Floodman public gateway is unavailable.'
fm_wait_http 'http://127.0.0.1:9010/mobile-api/v1/health' 600 false || fm_die 'Floodman Android Mobile API gateway is unavailable.'
fm_wait_http "http://127.0.0.1:${MAILPIT_PORT}/api/v1/info" 120 true || fm_die 'Test Email Inbox is unavailable.'
fm_wait_http "http://127.0.0.1:${ENGINEERING_PORT}/health/live" 120 false || fm_die 'Engineering Sandbox is unavailable.'
fm_wait_http 'http://127.0.0.1:8100/health/live' 180 false || fm_die 'Messaging AI is unavailable.'
fm_wait_http 'http://127.0.0.1:8090/health/ready' 600 false || fm_die 'Competitor Intelligence is unavailable.'
/home/container/runtime/tailscale/bin/tailscale --socket=/home/container/run/tailscale/tailscaled.sock serve status --json >/dev/null 2>&1 || fm_die 'Tailscale private HTTPS is unavailable.'

waited=0
while [ ! -f "$FM_RUN/owner-linked" ]; do
  [ "$waited" -lt 300 ] || fm_die 'Floodman Owner was not linked to the operations modules.'
  sleep 2
  waited=$((waited + 2))
done

printf '\n============================================================\n'
printf 'FLOODMAN_SUITE_READY\n'
printf 'Main Hub: %s\n' "$MAIN_PUBLIC_URL"
printf 'Direct login: %s/floodman-login\n' "$MAIN_PUBLIC_URL"
printf 'Full Floodman ERP: %s/full-erp\n' "$MAIN_PUBLIC_URL"
printf 'Integrated RoomFlow: %s\n' "$ROOMFLOW_WEB_URL"
printf 'Browser status: %s/floodman-status.html\n' "$MAIN_PUBLIC_URL"
if [ -f "$FM_RUN/public-signing-ready" ]; then
  printf 'Public customer signing: %s\n' "$DOCUMENSO_PUBLIC_URL"
  printf 'Public customer documents and payments: %s\n' "${FLOODMAN_CUSTOMER_PUBLIC_URL:-${DOCUMENSO_PUBLIC_URL}/customer}"
  printf 'Android app API: %s\n' "${FLOODMAN_MOBILE_API_PUBLIC_URL:-${DOCUMENSO_PUBLIC_URL}/mobile-api}"
else
  printf 'Public customer signing: pending Tailscale Funnel permission; staff services are ready.\n'
  printf 'Private signing administration: %s\n' "${FLOODMAN_DOCUMENSO_PRIVATE_URL:-https://${TAILSCALE_PRIVATE_FQDN:-localhost}:8444}"
fi
printf 'Test Email Inbox: %s\n' "$MAILPIT_PUBLIC_URL"
printf 'Engineering Sandbox: %s/lab\n' "$ENGINEERING_PUBLIC_URL"
printf 'Floodman API: %s/docs\n' "$API_PUBLIC_URL"
printf 'Owner: %s\n' "$FLOODMAN_OWNER_EMAIL"
printf 'Console mode: quiet; detailed logs are under Files -> logs/\n'
printf '============================================================\n\n'

# Record and announce only state changes. Healthy polling is silent so the
# Pterodactyl console remains useful for updates and real errors.
state_dir="$FM_RUN/health-state"
mkdir -p "$state_dir"

report_state() {
  name="$1"; next="$2"; message="$3"
  file="$state_dir/$name"
  previous="$(cat "$file" 2>/dev/null || printf unknown)"
  [ "$previous" = "$next" ] && return 0
  printf '%s\n' "$next" > "$file"
  if [ "$next" = 'ok' ]; then
    [ "$previous" = 'failed' ] && fm_log "$message recovered."
  else
    fm_warn "$message health check failed. Detailed logs are under /home/container/logs."
  fi
}

while :; do
  sleep 300

  if curl -fsS --max-time 5 "http://127.0.0.1:${SERVER_PORT}/health/live" >/dev/null 2>&1; then
    report_state hub ok 'Main Hub'
  else
    report_state hub failed 'Main Hub'
  fi

  if curl -fsS --max-time 5 "http://127.0.0.1:${SERVER_PORT}/roomflow/" >/dev/null 2>&1; then
    report_state roomflow ok 'Integrated RoomFlow'
  else
    report_state roomflow failed 'Integrated RoomFlow'
  fi

  if curl -fsS --max-time 5 "http://127.0.0.1:${SERVER_PORT}/api/auth/authenticated" >/dev/null 2>&1; then
    report_state erp ok 'Floodman ERP browser/API route'
  else
    report_state erp failed 'Floodman ERP browser/API route'
  fi

  if curl -fsS --max-time 5 "http://127.0.0.1:${FLOODMAN_API_PORT}/health/ready" >/dev/null 2>&1; then
    report_state api ok 'Floodman API'
  else
    report_state api failed 'Floodman API'
  fi

  if curl -fsS --max-time 5 'http://127.0.0.1:9010/mobile-api/v1/health' >/dev/null 2>&1; then
    report_state mobile_api ok 'Android Mobile API gateway'
  else
    report_state mobile_api failed 'Android Mobile API gateway'
  fi

  if curl -fsS --max-time 5 'http://127.0.0.1:8090/health/ready' >/dev/null 2>&1; then
    report_state competitor ok 'Competitor Intelligence'
  else
    report_state competitor failed 'Competitor Intelligence'
  fi

  if /home/container/runtime/tailscale/bin/tailscale --socket=/home/container/run/tailscale/tailscaled.sock serve status --json >/dev/null 2>&1; then
    report_state tailscale ok 'Tailscale private HTTPS'
  else
    report_state tailscale failed 'Tailscale private HTTPS'
  fi
done
SUITE_MONITOR

chmod 0755 \
  "$hotfix/start-documenso-private.sh" \
  "$hotfix/start-mailpit-private.sh" \
  "$hotfix/start-engineering-private.sh" \
  "$hotfix/start-orchestrator-private.sh" \
  "$hotfix/start-tailscaled.sh" \
  "$hotfix/start-tailscale-serve.sh" \
  "$hotfix/start-tailscale-funnel.sh" \
  "$hotfix/start-competitor-api.sh" \
  "$hotfix/start-competitor-scheduler.sh" \
  "$hotfix/start-office-console.sh" \
  "$hotfix/start-hub.sh" \
  "$hotfix/suite-monitor.sh"

# Reuse the application Supervisor layout, replacing only patched processes.
sed \
  -e "s#^command=/opt/floodman/aio/start-documenso.sh\$#command=$hotfix/start-documenso-private.sh#" \
  -e "s#^command=/opt/floodman/aio/start-mailpit.sh\$#command=$hotfix/start-mailpit-private.sh#" \
  -e "s#^command=/opt/floodman/aio/start-local-lab.sh\$#command=$hotfix/start-engineering-private.sh#" \
  -e "s#^command=/opt/floodman/aio/start-orchestrator-api.sh\$#command=$hotfix/start-orchestrator-private.sh#" \
  -e "s#^command=/opt/floodman/aio/start-competitor-api.sh\$#command=$hotfix/start-competitor-api.sh#" \
  -e "s#^command=/opt/floodman/aio/start-competitor-scheduler.sh\$#command=$hotfix/start-competitor-scheduler.sh#" \
  -e "s#^command=/opt/floodman/aio/start-office-console.sh\$#command=$hotfix/start-office-console.sh#" \
  -e "s#^command=/opt/floodman/aio/start-hub.sh\$#command=$hotfix/start-hub.sh#" \
  -e "s#^command=/opt/floodman/aio/suite-monitor.sh\$#command=$hotfix/suite-monitor.sh#" \
  "$base/supervisord.conf" > "$hotfix/supervisord.conf"


cat >> "$hotfix/supervisord.conf" <<SUPERVISOR_TAILSCALE

[program:tailscaled]
command=$hotfix/start-tailscaled.sh
priority=1
autostart=true
autorestart=true
startsecs=5
startretries=30
stopasgroup=true
killasgroup=true
stdout_logfile=/home/container/logs/tailscaled.log
stdout_logfile_maxbytes=10485760
stdout_logfile_backups=3
stderr_logfile=/home/container/logs/tailscaled-error.log
stderr_logfile_maxbytes=10485760
stderr_logfile_backups=3

[program:tailscale-serve]
command=$hotfix/start-tailscale-serve.sh
priority=6
autostart=true
autorestart=true
startsecs=5
startretries=30
stopasgroup=true
killasgroup=true
stdout_logfile=/home/container/logs/tailscale-serve.log
stdout_logfile_maxbytes=5242880
stdout_logfile_backups=3
stderr_logfile=/home/container/logs/tailscale-serve-error.log
stderr_logfile_maxbytes=5242880
stderr_logfile_backups=3

[program:tailscale-funnel]
command=$hotfix/start-tailscale-funnel.sh
priority=7
autostart=true
autorestart=true
startsecs=5
startretries=30
stopasgroup=true
killasgroup=true
stdout_logfile=/home/container/logs/tailscale-funnel.log
stdout_logfile_maxbytes=5242880
stdout_logfile_backups=3
stderr_logfile=/home/container/logs/tailscale-funnel-error.log
stderr_logfile_maxbytes=5242880
stderr_logfile_backups=3
SUPERVISOR_TAILSCALE

# Keep all original secret generation and service configuration. Replace only
# the runtime release and final Supervisor file.
sed \
  -e 's/pterodactyl-mobile-v[0-9][0-9.]*/pterodactyl-mobile-v4.6.7/g' \
  -e "s#exec supervisord -n -c /opt/floodman/aio/supervisord.conf#exec supervisord -n -c $hotfix/supervisord.conf#" \
  "$base/start-suite.sh" > "$hotfix/start-suite.sh"
chmod 0755 "$hotfix/start-suite.sh"
# Public customer signing is exposed through Funnel. Disable public account creation.
sed -i 's/NEXT_PUBLIC_DISABLE_SIGNUP="false"/NEXT_PUBLIC_DISABLE_SIGNUP="true"/' "$hotfix/start-suite.sh"
# Normalize the integrated RoomFlow URL and export the public topology so every
# Supervisor child receives the same values.
sed -i 's#^: "${ROOMFLOW_WEB_URL:=.*}"#: "${ROOMFLOW_WEB_URL:=/roomflow/}"#' "$hotfix/start-suite.sh"
if ! grep -Fq 'export MAIN_PUBLIC_URL DOCUMENSO_PUBLIC_URL' "$hotfix/start-suite.sh"; then
  sed -i '/^API_PUBLIC_URL=/a\
ROOMFLOW_WEB_URL="${ROOMFLOW_WEB_URL:-${MAIN_PUBLIC_URL}/roomflow/}"\
export MAIN_PUBLIC_URL DOCUMENSO_PUBLIC_URL MAILPIT_PUBLIC_URL ENGINEERING_PUBLIC_URL API_PUBLIC_URL ROOMFLOW_WEB_URL' "$hotfix/start-suite.sh"
fi

# Fail clearly if the upstream image layout changes.
grep -Fq "command=$hotfix/start-documenso-private.sh" "$hotfix/supervisord.conf" || die 'Could not privatize Floodman Signing.'
grep -Fq "command=$hotfix/start-mailpit-private.sh" "$hotfix/supervisord.conf" || die 'Could not privatize the test email inbox.'
grep -Fq "command=$hotfix/start-engineering-private.sh" "$hotfix/supervisord.conf" || die 'Could not privatize the Engineering Sandbox.'
grep -Fq "command=$hotfix/start-orchestrator-private.sh" "$hotfix/supervisord.conf" || die 'Could not privatize the Floodman API.'
grep -Fq 'listen 127.0.0.1:${SERVER_PORT}' "$hotfix/nginx.conf.template" || die 'Could not restrict the Floodman Hub to private loopback access.'
grep -Fq "command=$hotfix/start-tailscaled.sh" "$hotfix/supervisord.conf" || die 'Could not install the Tailscale daemon.'
grep -Fq "command=$hotfix/start-tailscale-serve.sh" "$hotfix/supervisord.conf" || die 'Could not install Tailscale Serve.'
grep -Fq "command=$hotfix/start-tailscale-funnel.sh" "$hotfix/supervisord.conf" || die 'Could not install the public signing Funnel watchdog.'
grep -Fqi 'private staff system remains online' "$hotfix/start-tailscale-funnel.sh" || die 'Could not install non-blocking Funnel fallback behavior.'
grep -Fq 'NEXT_PUBLIC_DISABLE_SIGNUP="true"' "$hotfix/start-suite.sh" || die 'Could not disable public signing-service account creation.'
grep -Fq "command=$hotfix/start-office-console.sh" "$hotfix/supervisord.conf" || die 'Could not patch the responsive Floodman Office command.'
grep -Fq "command=$hotfix/start-hub.sh" "$hotfix/supervisord.conf" || die 'Could not patch the Floodman Operations Hub command.'
grep -Fq "command=$hotfix/start-competitor-api.sh" "$hotfix/supervisord.conf" || die 'Could not patch the Competitor Intelligence API command.'
grep -Fq "command=$hotfix/start-competitor-scheduler.sh" "$hotfix/supervisord.conf" || die 'Could not patch the Competitor Intelligence scheduler command.'
grep -Fq "command=$hotfix/suite-monitor.sh" "$hotfix/supervisord.conf" || die 'Could not patch the suite monitor command.'
grep -Fq "exec supervisord -n -c $hotfix/supervisord.conf" "$hotfix/start-suite.sh" || die 'Could not patch the Supervisor configuration path.'
grep -Fq '/manifest.webmanifest' "$hotfix/nginx.conf.template" || die 'Could not add the Floodman PWA manifest route.'
grep -Fq 'location = /workspace' "$hotfix/nginx.conf.template" || die 'Could not install the adaptive desktop/mobile workspace launcher.'
grep -Fq 'location = / {' "$hotfix/nginx.conf.template" || die 'Could not detach the private root from the upstream ERP readiness page.'
grep -Fq 'return 302 /workspace?source=root&workspace=auto;' "$hotfix/nginx.conf.template" || die 'The private root does not open the adaptive Floodman workspace.'
grep -Fq 'absolute_redirect off;' "$hotfix/nginx.conf.template" || die 'Workspace redirects would lose the Tailscale HTTPS origin.'
grep -Fq 'location = /full-erp' "$hotfix/nginx.conf.template" || die 'Could not isolate the optional upstream ERP behind /full-erp.'
grep -Fq 'location = /floodman-workspace.css' "$hotfix/nginx.conf.template" || die 'Could not serve the explicit workspace layout stylesheet.'
grep -Fq 'location = /floodman-boot-guard.js' "$hotfix/nginx.conf.template" || die 'Could not serve the full ERP authentication guard.'
grep -Fq 'location = /floodman-status.html' "$hotfix/nginx.conf.template" || die 'Could not serve the full ERP runtime status page.'
grep -Fq '/floodman-boot-guard.js?release=${HUB_RELEASE}' "$hotfix/nginx.conf.template" || die 'Could not inject the authentication guard into the full ERP browser.'
grep -Fq 'map $http_host $fm_tls_port' "$hotfix/nginx.conf.template" || die 'Could not preserve the Tailscale HTTPS scheme for the full ERP browser.'
grep -Fq 'location = /erp-login' "$hotfix/nginx.conf.template" || die 'Could not install the direct ERP login shortcut.'
grep -Fq 'location = /erp-home' "$hotfix/nginx.conf.template" || die 'Could not install the direct ERP dashboard shortcut.'
grep -Fq 'http://0.0.0.0:${SERVER_PORT}' "$hotfix/nginx.conf.template" || die 'Could not install the final same-origin ERP browser URL rewrite.'
grep -Fq '/api/auth/authenticated' "$overlay_root/pwa/erp.html" || die 'Could not install the authentication-aware full ERP launcher.'
grep -Fq 'window.location.replace(target(isAuthenticated))' "$overlay_root/pwa/erp.html" || die 'The full ERP launcher does not select login or dashboard from the real authentication response.'
grep -Fq 'location = /office-health/live' "$hotfix/nginx.conf.template" || die 'Could not install the same-origin Floodman Office health probe.'
grep -Fq 'proxy_pass http://127.0.0.1:8700/health/live' "$hotfix/nginx.conf.template" || die 'The Office health probe does not reach the Floodman Office process.'
grep -Fq '/office-health/live' "$overlay_root/pwa/floodman-pwa.js" || die 'The PWA does not verify the actual Floodman Office connection.'
if grep -Fq 'navigator.onLine' "$overlay_root/pwa/floodman-pwa.js"; then
  die 'The PWA still trusts the browser internet flag instead of Floodman Office health.'
fi
grep -Fq 'dynamicOfficeRoute ? 30000 : 15000' "$overlay_root/pwa/floodman-sw.js" || die 'The service worker still uses the short false-offline navigation deadline.'
grep -Fq '/floodman-starting.html' "$overlay_root/pwa/floodman-sw.js" || die 'The service worker cannot distinguish Office startup from a true offline state.'
grep -Fq 'async def _dashboard_state' "$overlay_root/office-console/app/main.py" || die 'The desktop dashboard does not bound optional provider startup time.'
grep -Fq 'asyncio.wait_for(providers.lab_state()' "$overlay_root/office-console/app/main.py" || die 'The desktop dashboard provider snapshot can still block navigation.'
grep -Fq '/office/desktop?desktop=1' "$overlay_root/pwa/workspace.html" || die 'Could not install the dedicated desktop workspace target.'
grep -Fq '/office/mobile?mobile=1' "$overlay_root/pwa/workspace.html" || die 'Could not install the dedicated mobile workspace target.'
grep -Fq 'serviceWorker.register' "$overlay_root/pwa/workspace.html" || die 'The workspace chooser cannot refresh an older service worker before desktop navigation.'
grep -Fq 'html[data-workspace="desktop"] .shell' "$overlay_root/pwa/workspace-mode.css" || die 'Could not force the desktop shell independently of viewport width.'
grep -Fq 'html[data-workspace="mobile"] .mobile-bottom-nav' "$overlay_root/pwa/workspace-mode.css" || die 'Could not force the phone/tablet shell independently of viewport width.'
grep -Fq 'document.documentElement.dataset.workspace=mode' "$overlay_root/office-console/app/ui.py" || die 'Could not set the workspace before the Office page is painted.'
grep -Fq '<style>{BASE_CSS}</style>{WORKSPACE_CSS}' "$overlay_root/office-console/app/ui.py" || die 'The explicit workspace stylesheet does not override the legacy responsive rules.'
grep -Fq '"start_url": "/workspace?source=pwa' "$overlay_root/pwa/manifest.webmanifest" || die 'The Floodman PWA still opens the mobile workspace unconditionally.'
grep -Fq 'Desktop Operations' "$overlay_root/hub/hub.js" || die 'Could not add the desktop workspace to the Hub.'
grep -Fq 'Mobile Operations' "$overlay_root/hub/hub.js" || die 'Could not add the mobile workspace to the Hub.'
if grep -Fq '${hubOrigin}/#/pages/' "$overlay_root/hub/hub.js"; then
  die 'An ERP hash link still uses the workspace-owned root path.'
fi
grep -Fq '${hubOrigin}/index.html?desktop=1#/pages/' "$overlay_root/hub/hub.js" || die 'Could not preserve full ERP hash routes behind /index.html.'
if grep -Fq "pointer: coarse" "$overlay_root/hub/hub.js"; then
  die 'The Hub still classifies every touch-enabled desktop as a mobile device.'
fi
if grep -Fq '/home/container/runtime/floodman-v4.1.0/' "$hotfix/nginx.conf.template"; then
  die 'The Hub is still serving stale v4.1.0 frontend assets.'
fi
grep -Fq '/home/container/runtime/floodman-v4.6.7/app-overlay/floodman-operations-v4.6.7/' "$hotfix/nginx.conf.template" || die 'The Hub is not serving the current v4.6.7 frontend assets.'
node --check "$overlay_root/hub/hub.js" >/dev/null || die 'Could not validate the dual-workspace Hub script.'
node --check "$overlay_root/pwa/floodman-sw.js" >/dev/null || die 'Could not validate the updated Floodman service worker.'
python3 "$overlay_root/tests/full_erp_routing_smoke.py" >/home/container/logs/floodman-full-erp-routing-smoke.log 2>&1 \
  || { cat /home/container/logs/floodman-full-erp-routing-smoke.log >&2 || true; die 'Could not validate authentication-aware full ERP routing.'; }
PYTHONPATH="/opt/pydeps/office-console:$overlay_root/office-console:/opt/floodman/office-console" \
  python3 "$overlay_root/tests/dual_workspace_smoke.py" >/home/container/logs/floodman-dual-workspace-smoke.log 2>&1 \
  || { cat /home/container/logs/floodman-dual-workspace-smoke.log >&2 || true; die 'Could not validate the distinct desktop and mobile workspace shells.'; }
grep -Fq '/floodman-sw.js' "$hotfix/nginx.conf.template" || die 'Could not add the Floodman service-worker route.'
grep -Fq 'same-origin API routing' "$hotfix/start-hub.sh" || die 'Could not install same-origin Floodman ERP browser routing.'
grep -Fq 'Service-Worker-Allowed' "$hotfix/nginx.conf.template" || die 'Could not grant the Floodman service worker root scope.'
grep -Fq 'location = /api/user/me' "$hotfix/nginx.conf.template" || die 'Could not install the Floodman ERP user/me relation compatibility route.'
grep -Fq 'alias /home/container/data/roomflow/current/' "$hotfix/nginx.conf.template" || die 'Could not mount the integrated RoomFlow workspace.'
grep -Fq 'exec nginx -e' "$hotfix/start-hub.sh" || die 'Could not redirect the non-root Nginx bootstrap log.'
grep -Fq 'public-urls.env' "$hotfix/suite-monitor.sh" || die 'Could not install persistent public URL loading for the suite monitor.'
grep -Fq 'Integrated RoomFlow' "$hotfix/suite-monitor.sh" || die 'Could not add RoomFlow readiness monitoring.'
grep -Fq 'role,tenant' "$overlay_root/office-console/app/providers.py" || die 'Could not install the Floodman ERP employee relation query fix.'
grep -Fq "Install Floodman App" "$overlay_root/hub/hub.js" || die 'Could not add the Floodman PWA installer to the Hub.'
python3 -m py_compile \
  "$overlay_root/competitor-intel/app/main.py" \
  "$overlay_root/competitor-intel/app/scheduler.py" \
  "$overlay_root/office-console/app/main.py" \
  "$overlay_root/office-console/app/mobile_api.py" \
  "$overlay_root/office-console/app/mobile_operations.py" \
  "$overlay_root/office-console/app/project_plans.py" \
  "$overlay_root/office-console/app/roomflow_assets.py" \
  "$overlay_root/office-console/app/roomflow_supabase.py" \
  "$overlay_root/office-console/app/customer_portal.py" \
  "$overlay_root/office-console/app/pdf_documents.py" \
  "$overlay_root/office-console/app/estimate_catalog.py" \
  "$overlay_root/office-console/app/security.py" \
  "$overlay_root/office-console/app/store.py" \
  "$overlay_root/office-console/app/ui.py" \
  "$overlay_root/office-console/app/providers.py" \
  "$overlay_root/local-lab/app/main.py" \
  "$overlay_root/orchestrator/app/main.py" \
  "$overlay_root/orchestrator/app/adapters/square.py" \
  "$overlay_root/orchestrator/app/adapters/gauzy.py" \
  "$overlay_root/roomflow/prepare-roomflow.py" \
  || die 'Could not validate the Floodman v4.6.7 runtime patches.'
if grep -RIn --include='*.py' -E '(^|[[:space:]])(from[[:space:]]+PIL|import[[:space:]]+PIL)' \
  "$overlay_root/office-console" "$overlay_root/tests" >/home/container/logs/floodman-pillow-import-scan.log 2>&1; then
  cat /home/container/logs/floodman-pillow-import-scan.log >&2 || true
  die 'A Pillow/PIL import remains in the uploaded Floodman v4.6.7 runtime.'
fi
PYTHONPATH="/opt/pydeps/office-console:$overlay_root/office-console:/opt/floodman/office-console" \
  python3 -c 'from app import pdf_documents, roomflow_assets; assert not hasattr(pdf_documents, "_PILImage"); print(pdf_documents.__file__); print(roomflow_assets.__file__)' \
  > /home/container/logs/floodman-office-overlay-preflight.log 2>&1 \
  || { cat /home/container/logs/floodman-office-overlay-preflight.log >&2 || true; die 'The exact v4.6.7 Office overlay could not be imported during startup preflight.'; }
PYTHONPATH="/opt/pydeps/office-console:$overlay_root/office-console:/opt/floodman/office-console" \
  python3 "$overlay_root/tests/pdf_runtime_smoke.py" >/home/container/logs/floodman-pdf-runtime-smoke.log 2>&1 \
  || { cat /home/container/logs/floodman-pdf-runtime-smoke.log >&2 || true; die 'Could not validate direct RoomFlow JPEG embedding for estimate PDFs.'; }
printf '%s\n' '4.6.7' > /home/container/config/floodman-active-runtime.txt
printf '%s\n' "$overlay_root/office-console" > /home/container/config/floodman-active-office-path.txt
log "Office overlay preflight passed without Pillow/PIL: $overlay_root/office-console"
grep -Fq "payload === true" "$hotfix/floodman-boot-guard.js" || die 'Could not install the Floodman authentication redirect fix.'
grep -Fq "office/api/search/contacts" "$overlay_root/office-console/app/main.py" || die 'Could not install searchable customer selection.'
# Validate the actual PCI-safe boundary implemented by the cumulative overlay.
# Floodman stores Square card tokens and masked display data only; the older
# raw_card_number_stored sentinel was never part of the runtime source.
grep -Fq "Floodman never stores the full card number or card security code" "$overlay_root/office-console/app/main.py" || die 'Could not verify the PCI-safe Square payment-method boundary.'
grep -Fq "default_square_card_id" "$overlay_root/office-console/app/main.py" || die 'Could not verify tokenized Square card selection.'
grep -Fq "store_payment_method_enabled" "$overlay_root/office-console/app/providers.py" || die 'Could not install Square card-on-file enrollment.'
grep -Fq "catalog_items" "$overlay_root/office-console/app/store.py" || die 'Could not install the persistent line-item catalog.'
grep -Fq "estimate_payload" "$overlay_root/office-console/app/main.py" || die 'Could not install grouped estimate and invoice payloads.'
grep -Fq '@app.get("/office/estimates/new")' "$overlay_root/office-console/app/main.py" || die 'Could not install the explicit new-Android mobile API runtime.'
grep -Fq 'Searching never saves an estimate' "$overlay_root/office-console/app/main.py" || die 'Could not separate estimate search from draft creation.'
grep -Fq 'data-estimate-workflow' "$overlay_root/office-console/app/main.py" || die 'Could not install the staged estimate workflow.'
grep -Fq 'new_contact_first_name' "$overlay_root/office-console/app/main.py" || die 'Could not install inline customer creation for estimates.'
grep -Fq 'new_property_service_street' "$overlay_root/office-console/app/main.py" || die 'Could not install inline service-property creation for estimates.'
grep -Fq 'project_summary' "$overlay_root/office-console/app/main.py" || die 'Could not install full estimate project details.'
grep -Fq 'data-estimate-submit' "$overlay_root/office-console/app/ui.py" || die 'Could not install explicit estimate-save controls.'
grep -Fq "event.key === 'Enter'" "$overlay_root/office-console/app/ui.py" || die 'Could not install the accidental Enter-key save guard.'
grep -Fq "import/bundled-roomflow" "$overlay_root/office-console/app/main.py" || die 'Could not install the bundled RoomFlow catalog importer.'
grep -Fq "data-add-estimate-section" "$overlay_root/office-console/app/ui.py" || die 'Could not install multiple estimate headers.'
grep -Fq "Add & save to catalog" "$overlay_root/office-console/app/ui.py" || die 'Could not install custom line-item auto-save.'
grep -Fq "Estimate headers & line items" "$overlay_root/roomflow/floodman-panel.js" || die 'Could not install the integrated RoomFlow section editor.'
grep -Fq "ROOMFLOW_BUNDLED_CATALOG" "$overlay_root/office-console/app/main.py" || die 'Could not install RoomFlow catalog source mapping.'
node --check "$overlay_root/roomflow/floodman-panel.js" >/dev/null || die 'Could not validate the integrated RoomFlow browser panel.'


grep -Fq '/customer/pay/{token}' "$overlay_root/office-console/app/main.py" || die 'Could not install public Floodman online payments.'
grep -Fq 'CARD_BY_PHONE' "$overlay_root/office-console/app/main.py" || die 'Could not install staff card-by-phone payments.'
grep -Fq 'deposit_percent' "$overlay_root/office-console/app/main.py" || die 'Could not install configurable estimate deposits.'
grep -Fq 'build_estimate_pdf' "$overlay_root/office-console/app/pdf_documents.py" || die 'Could not install the Floodman estimate PDF template.'
grep -Fq 'build_invoice_pdf' "$overlay_root/office-console/app/pdf_documents.py" || die 'Could not install the Floodman invoice PDF template.'
grep -Fq 'Square.payments' "$overlay_root/office-console/app/customer_portal.py" || die 'Could not install the secure payment field.'
grep -Fq 'http://127.0.0.1:9010' "$hotfix/start-tailscale-funnel.sh" || die 'Could not publish the Floodman public gateway through Tailscale Funnel.'

grep -Fq 'API_PREFIX = "/mobile-api/v1"' "$overlay_root/office-console/app/mobile_api.py" \
  || die 'Could not install the Android Mobile API prefix.'
grep -Fq '@router.post("/auth/login")' "$overlay_root/office-console/app/mobile_api.py" \
  || die 'Could not install Android login.'
grep -Fq 'store.create_record("mobile_devices"' "$overlay_root/office-console/app/mobile_api.py" \
  || die 'Could not install Android device enrollment.'
grep -Fq 'app.include_router(build_mobile_router(store, providers, settings))' "$overlay_root/office-console/app/main.py" \
  || die 'Could not attach the Android Mobile API router.'
grep -Fq 'mobile_refresh_tokens' "$overlay_root/office-console/app/store.py" || die 'Could not install rotating Android refresh sessions.'
grep -Fq 'FLOODMAN_MOBILE_TOKEN_SECRET' "$overlay_root/office-console/app/config.py" || die 'Could not install mobile API security configuration.'
grep -Fq '$FM_HOME/runtime/floodman-v4.6.7/nginx.conf.template' "$hotfix/start-hub.sh" || die 'The Floodman Hub is not loading the gateway-enabled Nginx template.'
if grep -Fq 'app-overlay/floodman-operations-v4.6.7/aio/nginx.conf.template' "$hotfix/start-hub.sh"; then
  die 'The Floodman Hub still points at the pre-gateway Nginx template.'
fi
grep -Fq 'listen 127.0.0.1:9010;' "$hotfix/nginx.conf.template" || die 'Could not install the loopback-only Floodman public gateway.'
grep -Fq 'location ^~ /mobile-api/' "$hotfix/nginx.conf.template" || die 'Could not route the Android API through the Floodman public gateway.'
grep -Fq 'location ^~ /customer/' "$hotfix/nginx.conf.template" || die 'Could not route customer payment pages through the Floodman public gateway.'
grep -Fq 'floodman-mobile.env' "$hotfix/start-office-console.sh" || die 'Could not load the persistent Android device/session key.'

# Validate the full v4.6.7 native-app parity, RoomFlow migration, and scheduling additions.
grep -Fq 'from .mobile_operations import build_operations_router' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not attach full native mobile operations.'
grep -Fq '@router.patch("/estimates/{estimate_id}")' "$overlay_root/office-console/app/mobile_operations.py" || die 'Could not install native estimate editing.'
grep -Fq 'send_work_authorization' "$overlay_root/office-console/app/mobile_operations.py" || die 'Could not install native Work Authorization actions.'
grep -Fq 'convert_to_invoice' "$overlay_root/office-console/app/mobile_operations.py" || die 'Could not install estimate-to-invoice conversion.'
grep -Fq '@router.patch("/invoices/{invoice_id}")' "$overlay_root/office-console/app/mobile_operations.py" || die 'Could not install native invoice editing.'
grep -Fq '@router.post("/appointments")' "$overlay_root/office-console/app/mobile_operations.py" || die 'Could not install job and inspection scheduling.'
grep -Fq 'appointment_conflicts' "$overlay_root/office-console/app/mobile_operations.py" || die 'Could not install employee scheduling conflict detection.'
grep -Fq '@router.post("/calendar/subscription")' "$overlay_root/office-console/app/mobile_operations.py" || die 'Could not install private calendar subscriptions.'
grep -Fq 'project_plan_options' "$overlay_root/office-console/app/project_plans.py" || die 'Could not install category-based recommended project plans.'
grep -Fq 'enrich_estimate_with_roomflow' "$overlay_root/office-console/app/roomflow_assets.py" || die 'Could not install RoomFlow PDF layout mapping.'
grep -Fq 'roomflow_layout_data_url' "$overlay_root/roomflow/floodman-panel.js" || die 'Could not capture real RoomFlow layout images.'
grep -Fq 'NO SAVED ROOMFLOW LAYOUT ATTACHED' "$overlay_root/office-console/app/pdf_documents.py" || die 'Could not enforce honest RoomFlow layout PDF behavior.'
grep -Fq 'upcoming_appointments' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not add upcoming schedules to the mobile dashboard.'

# Validate the complete native RoomFlow bridge and app synchronization API.
grep -Fq 'class RoomFlowSaveRequest' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install the native RoomFlow save contract.'
grep -Fq '@router.post("/roomflow/jobs")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install native RoomFlow job creation.'
grep -Fq '@router.put("/roomflow/jobs/{job_id}")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install native RoomFlow job updates.'
grep -Fq '@router.get("/roomflow/jobs/{job_id}/layout")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install actual RoomFlow layout retrieval.'
grep -Fq 'FLOODMAN_ROOMFLOW_NATIVE' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install RoomFlow custom catalog persistence.'
grep -Fq 'API_VERSION = "0.3.0-alpha11"' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install the matched Floodman Android alpha11 API contract.'
grep -Fq '@router.get("/roomflow/bootstrap")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install the complete RoomFlow bootstrap endpoint.'
grep -Fq '@router.post("/roomflow/import/supabase")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install the original RoomFlow Supabase import endpoint.'
grep -Fq 'roomflow.supabase-import.v1' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not publish the RoomFlow import capability contract.'
grep -Fq 'DEFAULT_ROOMFLOW_SUPABASE_URL' "$overlay_root/office-console/app/roomflow_supabase.py" || die 'Could not install the protected original RoomFlow Supabase migration client.'
grep -Fq 'job_project_snapshots' "$overlay_root/office-console/app/roomflow_supabase.py" || die 'Could not install complete RoomFlow snapshot restoration.'
grep -Fq 'estimate_catalog_items' "$overlay_root/office-console/app/roomflow_supabase.py" || die 'Could not install original RoomFlow catalog migration.'
grep -Fq 'roomflow_imports' "$overlay_root/office-console/app/store.py" || die 'Could not install RoomFlow import history storage.'
grep -Fq 'roomflow_workspaces' "$overlay_root/office-console/app/store.py" || die 'Could not install persistent RoomFlow workspace storage.'
grep -Fq '@router.get("/roomflow/workspaces")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install the RoomFlow workspace list endpoint.'
grep -Fq '@router.post("/roomflow/workspaces")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install encrypted RoomFlow workspace creation.'
grep -Fq '@router.post("/roomflow/workspaces/{workspace_id}/select")' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not install RoomFlow workspace selection.'
grep -Fq 'roomflow.workspaces.v1' "$overlay_root/office-console/app/mobile_api.py" || die 'Could not publish the RoomFlow workspace capability contract.'
grep -Fq 'ensure_roomflow_workspaces' "$overlay_root/office-console/app/roomflow_supabase.py" || die 'Could not install v4.6.2 RoomFlow organization recovery.'
PYTHONPATH="/opt/pydeps/office-console:$overlay_root/office-console:/opt/floodman/office-console" \
  python3 "$overlay_root/tests/roomflow_workspace_smoke.py" >/home/container/logs/floodman-roomflow-workspace-smoke.log 2>&1 \
  || { cat /home/container/logs/floodman-roomflow-workspace-smoke.log >&2 || true; die 'Could not validate RoomFlow workspace recovery, creation, selection, and job isolation.'; }

# Remove only the generated ERP browser copy so v4.6.7 is guaranteed to
# rebuild it with same-origin URLs. Databases and configuration are untouched.
rm -rf /home/container/runtime/gauzy-web

stop_bootstrap_tailscaled
trap - EXIT INT TERM

export TZ=America/Detroit
log "Floodman v4.6.7 validated the stable root selector, true desktop shell, service-aware online detection, separate mobile shell, authentication-aware /full-erp launcher and injected ERP boot guard, matched Android alpha11 runtime, RoomFlow workspaces, guarded PDFs, estimates, invoices, payments, calendar, and public API at $TAILSCALE_MAIN_URL..."
exec sh "$hotfix/start-suite.sh"
