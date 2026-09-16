#!/bin/sh
set -eu

cd /home/container

log() { printf '[Floodman Mobile v4.7.1] %s\n' "$*"; }
die() { printf '[Floodman Mobile v4.7.1] ERROR: %s\n' "$*" >&2; exit 1; }

base='/opt/floodman/aio'
hotfix='/home/container/runtime/floodman-v4.7.1'
run_dir='/home/container/run'

[ -r "$base/start-suite.sh" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/start-suite.sh.'
[ -r "$base/supervisord.conf" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/supervisord.conf.'
[ -r "$base/common.sh" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/common.sh.'
[ -r "$base/start-hub.sh" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/start-hub.sh.'
[ -r "$base/nginx.conf.template" ] || die 'The Floodman runtime image is missing /opt/floodman/aio/nginx.conf.template.'

: "${FLOODMAN_OWNER_FIRST_NAME:?Set Owner First Name in the Pterodactyl Startup tab.}"
: "${FLOODMAN_OWNER_LAST_NAME:?Set Owner Last Name in the Pterodactyl Startup tab.}"
: "${FLOODMAN_OWNER_EMAIL:?Set Owner Email in the Pterodactyl Startup tab.}"
: "${FLOODMAN_OWNER_PASSWORD:?Set Owner Password in the Pterodactyl Startup tab.}"
case "$FLOODMAN_OWNER_EMAIL" in
  *@*.*) ;;
  *) die 'Owner Email must be a valid email address.' ;;
esac
[ "${#FLOODMAN_OWNER_PASSWORD}" -ge 12 ] || die 'Owner Password must contain at least 12 characters.'
case "$FLOODMAN_OWNER_PASSWORD" in
  ChangeMe12345\!|REPLACE_ME*|replace-me*|owner-password*)
    die 'Replace the example Owner Password in the Pterodactyl Startup tab before starting Floodman.'
    ;;
esac

case "${FLOODMAN_SOURCE_MODE:-builtin}" in
  builtin|'') ;;
  *) log 'Source Mode is not builtin. This emergency launcher uses the verified source already baked into the image.' ;;
esac

mkdir -p "$hotfix" "$run_dir/postgres" /home/container/logs

overlay_zip="/home/container/floodman-operations-runtime-v4.7.1.zip"
overlay_extract="$hotfix/app-overlay"
overlay_root="$overlay_extract/floodman-operations-v4.7.1"
[ -r "$overlay_zip" ] || die 'Keep floodman-operations-runtime-v4.7.1.zip in the Pterodactyl server root before starting.'
rm -rf "$overlay_extract"
mkdir -p "$overlay_extract"
unzip -q "$overlay_zip" -d "$overlay_extract" || die 'Could not extract the Floodman v4.7.1 mobile-API overlay.'
[ "$(cat "$overlay_root/VERSION" 2>/dev/null || true)" = '4.7.1' ] || die 'The uploaded mobile-API overlay is not Floodman v4.7.1.'
( cd "$overlay_root" && sha256sum -c MANIFEST.sha256 >/dev/null ) || die 'The Floodman v4.7.1 mobile-API overlay failed its checksum verification.'
log 'Verified the cumulative Floodman v4.7.1 full-ERP login overlay with authentication-aware routing, injected browser recovery, separate desktop/mobile workspaces, RoomFlow workspaces, guarded PDFs, estimates, invoices, scheduling, and payments.'
# Remove only stale extracted runtime trees. Uploaded rollback ZIPs and all data remain untouched.
rm -rf /home/container/runtime/floodman-v4.6.0 /home/container/runtime/floodman-v4.6.1 /home/container/runtime/floodman-v4.6.2 /home/container/runtime/floodman-v4.6.3 /home/container/runtime/floodman-v4.6.4 /home/container/runtime/floodman-v4.6.5 /home/container/runtime/floodman-v4.6.6
mkdir -p /home/container/config
printf '%s\n' '4.7.1' > /home/container/config/floodman-active-runtime.txt



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
# External HTTPS reverse-proxy topology
# ---------------------------------------------------------------------------
# TLS terminates in the user's HTTPS proxy. Floodman validates and publishes
# canonical HTTPS URLs, while the proxy owns certificates and access policy.
normalize_https_url() {
  label="$1"
  value="${2%/}"
  if ! printf '%s' "$value" | grep -Eq '^https://[A-Za-z0-9]([A-Za-z0-9.-]*[A-Za-z0-9])?(:[0-9]{1,5})?(/[^[:space:]?#]*)?$'; then
    die "$label must be a complete https:// URL without credentials, query parameters, or fragments."
  fi
  printf '%s' "$value"
}

url_host() {
  value="${1#https://}"
  value="${value%%/*}"
  printf '%s' "${value%%:*}"
}

FLOODMAN_PUBLIC_URL="$(normalize_https_url 'Main Floodman URL' "${FLOODMAN_PUBLIC_URL:-https://floodman.oninetwork.com}")"
FLOODMAN_DOCUMENSO_URL="$(normalize_https_url 'Floodman Signing URL' "${FLOODMAN_DOCUMENSO_URL:-https://sign.oninetwork.com}")"
FLOODMAN_CUSTOMER_PUBLIC_URL="$(normalize_https_url 'Customer portal URL' "${FLOODMAN_CUSTOMER_PUBLIC_URL:-https://floodman.oninetwork.com/customer}")"
FLOODMAN_MOBILE_API_PUBLIC_URL="$(normalize_https_url 'Mobile API URL' "${FLOODMAN_MOBILE_API_PUBLIC_URL:-https://api.oninetwork.com/mobile-api}")"
FLOODMAN_API_PUBLIC_URL="$(normalize_https_url 'Workflow API URL' "${FLOODMAN_API_PUBLIC_URL:-https://api.oninetwork.com}")"
FLOODMAN_ENGINEERING_URL="$(normalize_https_url 'Engineering URL' "${FLOODMAN_ENGINEERING_URL:-https://lab.oninetwork.com}")"
FLOODMAN_DOCUMENSO_PRIVATE_URL="$FLOODMAN_DOCUMENSO_URL"
FLOODMAN_MAILPIT_URL="http://127.0.0.1:${MAILPIT_PORT}"
ROOMFLOW_WEB_URL="${FLOODMAN_PUBLIC_URL}/roomflow/"
FLOODMAN_ROOMFLOW_URL="$ROOMFLOW_WEB_URL"
FLOODMAN_PUBLIC_SCHEME='https'
FLOODMAN_PUBLIC_HOST="$(url_host "$FLOODMAN_PUBLIC_URL")"

export FLOODMAN_PUBLIC_SCHEME FLOODMAN_PUBLIC_HOST FLOODMAN_PUBLIC_URL
export FLOODMAN_DOCUMENSO_URL FLOODMAN_CUSTOMER_PUBLIC_URL FLOODMAN_MOBILE_API_PUBLIC_URL
export FLOODMAN_DOCUMENSO_PRIVATE_URL FLOODMAN_API_PUBLIC_URL FLOODMAN_MAILPIT_URL FLOODMAN_ENGINEERING_URL
export ROOMFLOW_WEB_URL FLOODMAN_ROOMFLOW_URL

mkdir -p /home/container/config
cat > /home/container/config/external-https-urls.txt <<EXTERNAL_URLS
Floodman Operations external HTTPS URLs

Main PWA and ERP: $FLOODMAN_PUBLIC_URL
Integrated RoomFlow: $ROOMFLOW_WEB_URL
Customer portal and payments: $FLOODMAN_CUSTOMER_PUBLIC_URL
Floodman Signing: $FLOODMAN_DOCUMENSO_URL
Android and Apple Mobile API: $FLOODMAN_MOBILE_API_PUBLIC_URL
Workflow API: $FLOODMAN_API_PUBLIC_URL
Engineering Sandbox: $FLOODMAN_ENGINEERING_URL/lab

The HTTPS reverse proxy must protect staff, signing administration, API documentation, and Engineering routes. Mailpit remains loopback-only and has no public hostname.
EXTERNAL_URLS
cat > /home/container/config/public-signing-status.txt <<PUBLIC_HTTPS_CONFIGURED
status=configured
public_url=$FLOODMAN_DOCUMENSO_URL
customer_url=$FLOODMAN_CUSTOMER_PUBLIC_URL
mobile_api_url=$FLOODMAN_MOBILE_API_PUBLIC_URL
message=External HTTPS URLs are configured. Confirm proxy certificates, forwarding, and access policy before production use.
PUBLIC_HTTPS_CONFIGURED
printf '%s\n' "$FLOODMAN_DOCUMENSO_URL" > /home/container/config/public-signing-url.txt
printf '%s\n' "$FLOODMAN_CUSTOMER_PUBLIC_URL" > /home/container/config/public-customer-url.txt
printf '%s\n' "$FLOODMAN_MOBILE_API_PUBLIC_URL" > /home/container/config/android-mobile-api.txt
chmod 0640 \
  /home/container/config/external-https-urls.txt \
  /home/container/config/public-signing-status.txt \
  /home/container/config/public-signing-url.txt \
  /home/container/config/public-customer-url.txt \
  /home/container/config/android-mobile-api.txt \
  2>/dev/null || true
log "External HTTPS topology configured for $FLOODMAN_PUBLIC_HOST; no bundled overlay-network runtime is installed or started."

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

overlay="$FM_HOME/runtime/floodman-v4.7.1/app-overlay/floodman-operations-v4.7.1/competitor-intel"
[ -r "$overlay/app/main.py" ] || fm_die 'The Floodman Competitor Intelligence v4.7.1 overlay is missing.'
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

overlay="$FM_HOME/runtime/floodman-v4.7.1/app-overlay/floodman-operations-v4.7.1/competitor-intel"
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
  const release = 'pterodactyl-mobile-v4.7.1';
  const started = Date.now();
  const pendingLoginKey = 'floodmanLoginNext';

  function pendingLoginTarget() {
    try {
      const value = String(sessionStorage.getItem(pendingLoginKey) || '');
      return value.startsWith('/') && !value.startsWith('//') && !value.includes('\\') ? value : '';
    } catch (_) {
      return '';
    }
  }

  async function completePendingLogin() {
    const target = pendingLoginTarget();
    if (!target) return false;
    try {
      const response = await fetch('/login/status', {
        cache: 'no-store', credentials: 'same-origin', headers: { accept: 'application/json' }
      });
      const payload = response.ok ? await response.json() : {};
      if (payload?.authenticated === true) {
        try { sessionStorage.removeItem(pendingLoginKey); } catch (_) {}
        window.location.replace(target);
        return true;
      }
    } catch (_) {}
    return false;
  }

  async function watchPendingLogin() {
    if (await completePendingLogin()) return;
    if (pendingLoginTarget()) window.setTimeout(watchPendingLogin, 1000);
  }

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
    panel.style.cssText = 'position:fixed;inset:0;z-index:2147483647;display:grid;place-items:center;overflow:auto;padding:22px;background:#eef5fb;color:#102443;font-family:Inter,Segoe UI,Arial,sans-serif';
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-modal', 'true');
    panel.setAttribute('aria-labelledby', 'floodman-recovery-title');
    panel.innerHTML = `
      <div style="position:relative;width:min(560px,100%);max-height:calc(100dvh - 44px);overflow:auto;background:#fff;border-radius:22px;padding:30px;box-shadow:0 24px 70px rgba(15,35,65,.18)">
        <button type="button" id="floodman-dismiss-recovery" aria-label="Dismiss recovery notice" style="position:absolute;top:12px;right:12px;display:grid;place-items:center;width:44px;min-height:44px;border:0;border-radius:12px;background:#e7eef6;color:#102443;font-size:24px;font-weight:800;cursor:pointer">×</button>
        <div style="font-size:12px;font-weight:800;letter-spacing:.12em;text-transform:uppercase;color:#0ea5e9">Floodman Operations</div>
        <h1 id="floodman-recovery-title" style="margin:10px 48px 8px 0;font-size:25px">Floodman ERP browser did not finish rendering</h1>
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
        <p style="margin:16px 0 0;font-size:12px;color:#728197">Created by Josh Aldrich · Release ${release}</p>
      </div>`;
    document.body.appendChild(panel);
    const dismiss = () => { document.removeEventListener('keydown', dismissOnEscape); panel.remove(); };
    const dismissOnEscape = (event) => { if (event.key === 'Escape') dismiss(); };
    document.getElementById('floodman-dismiss-recovery').addEventListener('click', dismiss);
    document.addEventListener('keydown', dismissOnEscape);
    document.getElementById('floodman-dismiss-recovery').focus();
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
  window.setTimeout(watchPendingLogin, 400);
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
  <p class="muted">This page checks the Floodman Operations Hub, ERP API, native Mobile API, signing, and Engineering Sandbox from the same browser you are using.</p>
  <div id="checks" class="grid"><div class="row"><b>Checks</b><span>running…</span></div></div>
  <div class="actions"><a class="primary" href="/full-erp?target=login">Open Floodman login</a><button class="secondary" id="again">Run again</button></div>
  <p class="muted" style="font-size:12px;margin-top:18px">Release pterodactyl-mobile-v4.7.1</p>
</main>
<script>
(() => {
  const checks = [
    ['Main Hub', `${location.origin}/health/live`],
    ['Floodman ERP API', `${location.origin}/api/auth/authenticated`, true],
    ['Native Mobile API', 'https://api.oninetwork.com/mobile-api/v1/health'],
    ['Floodman Signing', 'https://sign.oninetwork.com/api/health', true],
    ['Engineering Sandbox', 'https://lab.oninetwork.com/health/live']
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
overlay="$FM_HOME/runtime/floodman-v4.7.1/app-overlay/floodman-operations-v4.7.1/office-console"
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
config_hash="$(printf '%s\n' "$SERVER_PORT|$FLOODMAN_COMPANY_NAME|pterodactyl-mobile-v4.7.1" | sha256sum | awk '{print $1}')"
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
  < "$FM_HOME/runtime/floodman-v4.7.1/app-overlay/floodman-operations-v4.7.1/hub/hub-config.js.template" \
  > "$FM_HOME/runtime/hub/floodman-hub-config.js"
envsubst '${SERVER_PORT} ${FLOODMAN_API_PORT} ${HUB_RELEASE}' \
  < "$FM_HOME/runtime/floodman-v4.7.1/nginx.conf.template" \
  > "$FM_CONFIG/nginx.conf"

fm_log "Starting Floodman Operations Hub on port $SERVER_PORT with same-origin browser routing..."
exec nginx -e "$FM_LOGS/nginx-bootstrap.log" -c "$FM_CONFIG/nginx.conf" -g 'daemon off;'
START_HUB

# Use the verified v4.7.1 Nginx template, which serves the manifest, service worker, install page, icons, and safe offline shell.
cp "$overlay_root/aio/nginx.conf.template" "$hotfix/nginx.conf.template"


# Add a dedicated API gateway on the allocated API port. The external HTTPS
# proxy maps api.oninetwork.com to this listener. Mobile API traffic is sent to
# Office; the existing workflow API remains behind the same authenticated API
# origin so current callbacks and integrations keep working.
python3 - "$hotfix/nginx.conf.template" <<'PY_PUBLIC_GATEWAY'
from pathlib import Path
import sys

path = Path(sys.argv[1])
text = path.read_text(encoding="utf-8")
if "listen 0.0.0.0:${FLOODMAN_API_PORT};" not in text:
    gateway = '\n\n    # External HTTPS API gateway. The upstream proxy terminates TLS and must\n    # restrict public access to the Mobile API, required webhooks, and customer\n    # token routes. Workflow administration and API docs require staff access.\n    server {\n        listen 0.0.0.0:${FLOODMAN_API_PORT};\n        server_name _;\n\n        access_log off;\n        client_max_body_size 50m;\n        add_header X-Content-Type-Options "nosniff" always;\n        add_header Referrer-Policy "same-origin" always;\n\n        location = /__floodman_public_gateway_health {\n            default_type application/json;\n            add_header Cache-Control "no-store" always;\n            return 200 \'{"status":"ok","service":"floodman-external-api-gateway","release":"v4.7.1"}\';\n        }\n\n        location = /mobile-api {\n            return 308 /mobile-api/;\n        }\n\n        location ^~ /mobile-api/ {\n            proxy_pass http://127.0.0.1:8700;\n            proxy_http_version 1.1;\n            proxy_set_header Host $http_host;\n            proxy_set_header X-Real-IP $remote_addr;\n            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n            proxy_set_header X-Forwarded-Proto $fm_public_scheme;\n            proxy_set_header X-Forwarded-Host $http_host;\n            proxy_set_header Upgrade $http_upgrade;\n            proxy_set_header Connection $connection_upgrade;\n            proxy_read_timeout 180s;\n            proxy_send_timeout 180s;\n            proxy_buffering off;\n            add_header Cache-Control "no-store" always;\n        }\n\n        location / {\n            proxy_pass http://127.0.0.1:8701;\n            proxy_http_version 1.1;\n            proxy_set_header Host $http_host;\n            proxy_set_header X-Real-IP $remote_addr;\n            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;\n            proxy_set_header X-Forwarded-Proto $fm_public_scheme;\n            proxy_set_header X-Forwarded-Host $http_host;\n            proxy_set_header Upgrade $http_upgrade;\n            proxy_set_header Connection $connection_upgrade;\n            proxy_read_timeout 300s;\n            proxy_send_timeout 300s;\n            proxy_buffering off;\n        }\n    }\n'
    index = text.rfind("\n}")
    if index < 0:
        raise SystemExit("Could not locate the Nginx http block terminator")
    text = text[:index] + gateway + text[index:]
    path.write_text(text, encoding="utf-8")
PY_PUBLIC_GATEWAY



cat > "$hotfix/start-documenso-external.sh" <<'START_DOCUMENSO_EXTERNAL'
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
fm_log "Starting Floodman Signing on the allocated proxy target port $DOCUMENSO_PORT..."
cd /opt/documenso/apps/remix
export PATH="/opt/documenso-runtime/usr/local/bin:$PATH"
npx prisma migrate deploy --schema ../../packages/prisma/schema.prisma
export HOSTNAME=0.0.0.0
exec node build/server/main.js
START_DOCUMENSO_EXTERNAL

cat > "$hotfix/start-mailpit-private.sh" <<'START_MAILPIT_PRIVATE'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
exec /usr/local/bin/mailpit --listen "127.0.0.1:${MAILPIT_PORT}" --smtp "127.0.0.1:1026" --database "$FM_DATA/mailpit/mailpit.db" --max 1000
START_MAILPIT_PRIVATE

cat > "$hotfix/start-engineering-external.sh" <<'START_ENGINEERING_EXTERNAL'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
export LAB_STATE_DIR="$FM_DATA/lab-state"
overlay="$FM_HOME/runtime/floodman-v4.7.1/app-overlay/floodman-operations-v4.7.1/local-lab"
[ -r "$overlay/app/main.py" ] || fm_die 'The Floodman Engineering Sandbox v4.7.1 overlay is missing.'
cd "$overlay"
export PYTHONPATH="/opt/pydeps/local-lab:$overlay:/opt/floodman/local-lab"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$ENGINEERING_PORT" --proxy-headers --forwarded-allow-ips '*' --no-access-log
START_ENGINEERING_EXTERNAL

cat > "$hotfix/start-orchestrator-internal.sh" <<'START_ORCHESTRATOR_INTERNAL'
#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
while [ ! -f "$FM_RUN/databases-ready" ] || [ ! -f "$FM_RUN/gauzy-finalized" ]; do sleep 2; done
overlay="$FM_HOME/runtime/floodman-v4.7.1/app-overlay/floodman-operations-v4.7.1/orchestrator"
[ -r "$overlay/app/main.py" ] || fm_die 'The Floodman API v4.7.1 overlay is missing.'
cd "$overlay"
export PYTHONPATH="/opt/pydeps/orchestrator:$overlay:/opt/floodman/orchestrator"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8701 --proxy-headers --forwarded-allow-ips '*' --no-access-log
START_ORCHESTRATOR_INTERNAL

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
fm_wait_http 'http://127.0.0.1:8701/health/ready' 180 false || fm_die 'Floodman workflow API is unavailable.'
fm_wait_http "http://127.0.0.1:${DOCUMENSO_PORT}/api/health" 600 true || fm_die 'Floodman Signing is unavailable.'
fm_wait_http "http://127.0.0.1:${FLOODMAN_API_PORT}/__floodman_public_gateway_health" 600 false || fm_die 'Floodman external API gateway is unavailable.'
fm_wait_http "http://127.0.0.1:${FLOODMAN_API_PORT}/mobile-api/v1/health" 600 false || fm_die 'Floodman native Mobile API gateway is unavailable.'
fm_wait_http "http://127.0.0.1:${MAILPIT_PORT}/api/v1/info" 120 true || fm_die 'Test Email Inbox is unavailable.'
fm_wait_http "http://127.0.0.1:${ENGINEERING_PORT}/health/live" 120 false || fm_die 'Engineering Sandbox is unavailable.'
fm_wait_http 'http://127.0.0.1:8100/health/live' 180 false || fm_die 'Messaging AI is unavailable.'
fm_wait_http 'http://127.0.0.1:8090/health/ready' 600 false || fm_die 'Competitor Intelligence is unavailable.'
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
printf 'Floodman Signing: %s\n' "$DOCUMENSO_PUBLIC_URL"
printf 'Customer documents and payments: %s\n' "$FLOODMAN_CUSTOMER_PUBLIC_URL"
printf 'Android and Apple Mobile API: %s\n' "$FLOODMAN_MOBILE_API_PUBLIC_URL"
printf 'Test Email Inbox: loopback only on port %s\n' "$MAILPIT_PORT"
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

  if curl -fsS --max-time 5 'http://127.0.0.1:8701/health/ready' >/dev/null 2>&1; then
    report_state api ok 'Floodman API'
  else
    report_state api failed 'Floodman API'
  fi

  if curl -fsS --max-time 5 "http://127.0.0.1:${FLOODMAN_API_PORT}/mobile-api/v1/health" >/dev/null 2>&1; then
    report_state mobile_api ok 'Android Mobile API gateway'
  else
    report_state mobile_api failed 'Android Mobile API gateway'
  fi

  if curl -fsS --max-time 5 'http://127.0.0.1:8090/health/ready' >/dev/null 2>&1; then
    report_state competitor ok 'Competitor Intelligence'
  else
    report_state competitor failed 'Competitor Intelligence'
  fi

done
SUITE_MONITOR

chmod 0755 \
  "$hotfix/start-documenso-external.sh" \
  "$hotfix/start-mailpit-private.sh" \
  "$hotfix/start-engineering-external.sh" \
  "$hotfix/start-orchestrator-internal.sh" \
  "$hotfix/start-competitor-api.sh" \
  "$hotfix/start-competitor-scheduler.sh" \
  "$hotfix/start-office-console.sh" \
  "$hotfix/start-hub.sh" \
  "$hotfix/suite-monitor.sh"

# Reuse the application Supervisor layout, replacing only patched processes.
sed \
  -e "s#^command=/opt/floodman/aio/start-documenso.sh\$#command=$hotfix/start-documenso-external.sh#" \
  -e "s#^command=/opt/floodman/aio/start-mailpit.sh\$#command=$hotfix/start-mailpit-private.sh#" \
  -e "s#^command=/opt/floodman/aio/start-local-lab.sh\$#command=$hotfix/start-engineering-external.sh#" \
  -e "s#^command=/opt/floodman/aio/start-orchestrator-api.sh\$#command=$hotfix/start-orchestrator-internal.sh#" \
  -e "s#^command=/opt/floodman/aio/start-competitor-api.sh\$#command=$hotfix/start-competitor-api.sh#" \
  -e "s#^command=/opt/floodman/aio/start-competitor-scheduler.sh\$#command=$hotfix/start-competitor-scheduler.sh#" \
  -e "s#^command=/opt/floodman/aio/start-office-console.sh\$#command=$hotfix/start-office-console.sh#" \
  -e "s#^command=/opt/floodman/aio/start-hub.sh\$#command=$hotfix/start-hub.sh#" \
  -e "s#^command=/opt/floodman/aio/suite-monitor.sh\$#command=$hotfix/suite-monitor.sh#" \
  "$base/supervisord.conf" > "$hotfix/supervisord.conf"

# Keep all original secret generation and service configuration. Replace only
# the runtime release and final Supervisor file.
sed \
  -e 's/pterodactyl-mobile-v[0-9][0-9.]*/pterodactyl-mobile-v4.7.1/g' \
  -e "s#exec supervisord -n -c /opt/floodman/aio/supervisord.conf#exec supervisord -n -c $hotfix/supervisord.conf#" \
  "$base/start-suite.sh" > "$hotfix/start-suite.sh"
chmod 0755 "$hotfix/start-suite.sh"
# External signing is reachable through the HTTPS proxy. Disable public account creation.
sed -i 's/NEXT_PUBLIC_DISABLE_SIGNUP="false"/NEXT_PUBLIC_DISABLE_SIGNUP="true"/' "$hotfix/start-suite.sh"
# Replace the retired overlay-network fallback ports retained by the pinned base
# image with the actual Pterodactyl allocations. Remote browser links normally
# use the explicit HTTPS URLs above; these values are only compatibility input.
sed -i \
  -e 's/HUB_REMOTE_DOCUMENSO_PORT="[0-9][0-9]*"/HUB_REMOTE_DOCUMENSO_PORT="$DOCUMENSO_PORT"/' \
  -e 's/HUB_REMOTE_MAILPIT_PORT="[0-9][0-9]*"/HUB_REMOTE_MAILPIT_PORT="$MAILPIT_PORT"/' \
  -e 's/HUB_REMOTE_ENGINEERING_PORT="[0-9][0-9]*"/HUB_REMOTE_ENGINEERING_PORT="$ENGINEERING_PORT"/' \
  -e 's/HUB_REMOTE_API_PORT="[0-9][0-9]*"/HUB_REMOTE_API_PORT="$FLOODMAN_API_PORT"/' \
  "$hotfix/start-suite.sh"
# Normalize the integrated RoomFlow URL and export the public topology so every
# Supervisor child receives the same values.
sed -i 's#^: "${ROOMFLOW_WEB_URL:=.*}"#: "${ROOMFLOW_WEB_URL:=/roomflow/}"#' "$hotfix/start-suite.sh"
if ! grep -Fq 'export MAIN_PUBLIC_URL DOCUMENSO_PUBLIC_URL' "$hotfix/start-suite.sh"; then
  sed -i '/^API_PUBLIC_URL=/a\
ROOMFLOW_WEB_URL="${ROOMFLOW_WEB_URL:-${MAIN_PUBLIC_URL}/roomflow/}"\
export MAIN_PUBLIC_URL DOCUMENSO_PUBLIC_URL MAILPIT_PUBLIC_URL ENGINEERING_PUBLIC_URL API_PUBLIC_URL ROOMFLOW_WEB_URL' "$hotfix/start-suite.sh"
fi

# Fail clearly if the upstream image layout changes.
grep -Fq "command=$hotfix/start-documenso-external.sh" "$hotfix/supervisord.conf" || die 'Could not configure the Floodman Signing proxy target.'
grep -Fq "command=$hotfix/start-mailpit-private.sh" "$hotfix/supervisord.conf" || die 'Could not privatize the test email inbox.'
grep -Fq "command=$hotfix/start-engineering-external.sh" "$hotfix/supervisord.conf" || die 'Could not configure the Engineering proxy target.'
grep -Fq "command=$hotfix/start-orchestrator-internal.sh" "$hotfix/supervisord.conf" || die 'Could not configure the internal workflow API.'
grep -Fq 'listen 0.0.0.0:${SERVER_PORT}' "$hotfix/nginx.conf.template" || die 'Could not expose the Floodman Hub to the external HTTPS proxy.'
grep -Fq 'listen 0.0.0.0:${FLOODMAN_API_PORT}' "$hotfix/nginx.conf.template" || die 'Could not expose the native API gateway to the external HTTPS proxy.'
grep -Fq 'NEXT_PUBLIC_DISABLE_SIGNUP="true"' "$hotfix/start-suite.sh" || die 'Could not disable public signing-service account creation.'
grep -Fq 'HUB_REMOTE_DOCUMENSO_PORT="$DOCUMENSO_PORT"' "$hotfix/start-suite.sh" || die 'Could not align the signing Hub fallback with its allocation.'
grep -Fq 'HUB_REMOTE_MAILPIT_PORT="$MAILPIT_PORT"' "$hotfix/start-suite.sh" || die 'Could not align the private inbox Hub fallback with its allocation.'
grep -Fq 'HUB_REMOTE_ENGINEERING_PORT="$ENGINEERING_PORT"' "$hotfix/start-suite.sh" || die 'Could not align the Engineering Hub fallback with its allocation.'
grep -Fq 'HUB_REMOTE_API_PORT="$FLOODMAN_API_PORT"' "$hotfix/start-suite.sh" || die 'Could not align the API Hub fallback with its allocation.'
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
grep -Fq 'absolute_redirect off;' "$hotfix/nginx.conf.template" || die 'Workspace redirects would lose the external HTTPS origin.'
grep -Fq 'location = /full-erp' "$hotfix/nginx.conf.template" || die 'Could not isolate the optional upstream ERP behind /full-erp.'
grep -Fq 'location = /floodman-workspace.css' "$hotfix/nginx.conf.template" || die 'Could not serve the explicit workspace layout stylesheet.'
grep -Fq 'location = /floodman-boot-guard.js' "$hotfix/nginx.conf.template" || die 'Could not serve the full ERP authentication guard.'
grep -Fq 'location = /floodman-status.html' "$hotfix/nginx.conf.template" || die 'Could not serve the full ERP runtime status page.'
grep -Fq '/floodman-boot-guard.js?release=${HUB_RELEASE}' "$hotfix/nginx.conf.template" || die 'Could not inject the authentication guard into the full ERP browser.'
grep -Fq 'map $http_x_forwarded_proto $fm_public_scheme' "$hotfix/nginx.conf.template" || die 'Could not preserve the external HTTPS scheme for the full ERP browser.'
grep -Fq 'location = /erp-login' "$hotfix/nginx.conf.template" || die 'Could not install the direct ERP login shortcut.'
grep -Fq 'location = /erp-home' "$hotfix/nginx.conf.template" || die 'Could not install the direct ERP dashboard shortcut.'
grep -Fq 'http://0.0.0.0:${SERVER_PORT}' "$hotfix/nginx.conf.template" || die 'Could not install the final same-origin ERP browser URL rewrite.'
grep -Fq '/api/auth/authenticated' "$overlay_root/pwa/erp.html" || die 'Could not install the authentication-aware full ERP launcher.'
grep -Fq 'window.location.replace(target(isAuthenticated))' "$overlay_root/pwa/erp.html" || die 'The full ERP launcher does not select login or dashboard from the real authentication response.'
grep -Fq 'location = /api/auth/login' "$hotfix/nginx.conf.template" || die 'The main ERP login is not routed through the unified Floodman session bridge.'
grep -Fq 'proxy_pass http://127.0.0.1:8700/office/api/erp/login' "$hotfix/nginx.conf.template" || die 'The unified Floodman login does not reach the Office session bridge.'
grep -Fq "const pendingLoginKey = 'floodmanLoginNext'" "$hotfix/floodman-boot-guard.js" || die 'The ERP browser cannot return to a requested Floodman module after login.'
grep -Fq "window.location.replace(target)" "$hotfix/floodman-boot-guard.js" || die 'The unified login return target is not activated after ERP authentication.'
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
grep -Fq '/home/container/runtime/floodman-v4.7.1/app-overlay/floodman-operations-v4.7.1/' "$hotfix/nginx.conf.template" || die 'The Hub is not serving the current v4.7.1 frontend assets.'
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
  || die 'Could not validate the Floodman v4.7.1 runtime patches.'
if grep -RIn --include='*.py' -E '(^|[[:space:]])(from[[:space:]]+PIL|import[[:space:]]+PIL)' \
  "$overlay_root/office-console" "$overlay_root/tests" >/home/container/logs/floodman-pillow-import-scan.log 2>&1; then
  cat /home/container/logs/floodman-pillow-import-scan.log >&2 || true
  die 'A Pillow/PIL import remains in the uploaded Floodman v4.7.1 runtime.'
fi
PYTHONPATH="/opt/pydeps/office-console:$overlay_root/office-console:/opt/floodman/office-console" \
  python3 -c 'from app import pdf_documents, roomflow_assets; assert not hasattr(pdf_documents, "_PILImage"); print(pdf_documents.__file__); print(roomflow_assets.__file__)' \
  > /home/container/logs/floodman-office-overlay-preflight.log 2>&1 \
  || { cat /home/container/logs/floodman-office-overlay-preflight.log >&2 || true; die 'The exact v4.7.1 Office overlay could not be imported during startup preflight.'; }
PYTHONPATH="/opt/pydeps/office-console:$overlay_root/office-console:/opt/floodman/office-console" \
  python3 "$overlay_root/tests/pdf_runtime_smoke.py" >/home/container/logs/floodman-pdf-runtime-smoke.log 2>&1 \
  || { cat /home/container/logs/floodman-pdf-runtime-smoke.log >&2 || true; die 'Could not validate direct RoomFlow JPEG embedding for estimate PDFs.'; }
printf '%s\n' '4.7.1' > /home/container/config/floodman-active-runtime.txt
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
grep -Fq 'id="fm-rf-estimate-scope"' "$overlay_root/roomflow/floodman-panel.js" || die 'Could not install the integrated RoomFlow section editor.'
grep -Fq '@app.post("/office/api/roomflow/workspaces")' "$overlay_root/office-console/app/main.py" || die 'Could not install ERP-session RoomFlow company creation.'
grep -Fq '@app.post("/office/api/roomflow/workspaces/{workspace_id}/select")' "$overlay_root/office-console/app/main.py" || die 'Could not install ERP-session RoomFlow company selection.'
grep -Fq "authOverlay.style.display = 'none'" "$overlay_root/roomflow/floodman-panel.js" || die 'Could not neutralize the legacy RoomFlow account overlay.'
grep -Fq 'No separate RoomFlow account is required' "$overlay_root/roomflow/floodman-panel.js" || die 'Could not install the unified Floodman RoomFlow workspace controls.'
grep -Fq "ROOMFLOW_BUNDLED_CATALOG" "$overlay_root/office-console/app/main.py" || die 'Could not install RoomFlow catalog source mapping.'
node --check "$overlay_root/roomflow/floodman-panel.js" >/dev/null || die 'Could not validate the integrated RoomFlow browser panel.'


grep -Fq '/customer/pay/{token}' "$overlay_root/office-console/app/main.py" || die 'Could not install public Floodman online payments.'
grep -Fq 'CARD_BY_PHONE' "$overlay_root/office-console/app/main.py" || die 'Could not install staff card-by-phone payments.'
grep -Fq 'deposit_percent' "$overlay_root/office-console/app/main.py" || die 'Could not install configurable estimate deposits.'
grep -Fq 'build_estimate_pdf' "$overlay_root/office-console/app/pdf_documents.py" || die 'Could not install the Floodman estimate PDF template.'
grep -Fq 'build_invoice_pdf' "$overlay_root/office-console/app/pdf_documents.py" || die 'Could not install the Floodman invoice PDF template.'
grep -Fq 'Square.payments' "$overlay_root/office-console/app/customer_portal.py" || die 'Could not install the secure payment field.'
grep -Fq 'proxy_pass http://127.0.0.1:8700;' "$hotfix/nginx.conf.template" || die 'Could not route the native Mobile API through the allocated API gateway.'
grep -Fq 'proxy_pass http://127.0.0.1:8701;' "$hotfix/nginx.conf.template" || die 'Could not route workflow API traffic to its internal process.'

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
grep -Fq '$FM_HOME/runtime/floodman-v4.7.1/nginx.conf.template' "$hotfix/start-hub.sh" || die 'The Floodman Hub is not loading the gateway-enabled Nginx template.'
if grep -Fq 'app-overlay/floodman-operations-v4.7.1/aio/nginx.conf.template' "$hotfix/start-hub.sh"; then
  die 'The Floodman Hub still points at the pre-gateway Nginx template.'
fi
grep -Fq 'listen 0.0.0.0:${FLOODMAN_API_PORT};' "$hotfix/nginx.conf.template" || die 'Could not install the external Floodman API gateway.'
grep -Fq 'location ^~ /mobile-api/' "$hotfix/nginx.conf.template" || die 'Could not route the Android API through the Floodman public gateway.'
grep -Fq 'location ^~ /customer/' "$hotfix/nginx.conf.template" || die 'Could not route customer payment pages through the Floodman public gateway.'
grep -Fq 'floodman-mobile.env' "$hotfix/start-office-console.sh" || die 'Could not load the persistent Android device/session key.'

# Validate the full v4.7.1 native-app parity, RoomFlow migration, and scheduling additions.
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

# Remove only the generated ERP browser copy so v4.7.1 is guaranteed to
# rebuild it with same-origin URLs. Databases and configuration are untouched.
rm -rf /home/container/runtime/gauzy-web

export TZ=America/Detroit
log "Floodman v4.7.1 validated the external HTTPS topology, stable root selector, true desktop shell, service-aware online detection, separate mobile shell, authentication-aware /full-erp launcher and injected ERP boot guard, matched native alpha11 runtime, RoomFlow workspaces, guarded PDFs, estimates, invoices, payments, calendar, and API at $FLOODMAN_PUBLIC_URL..."
exec sh "$hotfix/start-suite.sh"
