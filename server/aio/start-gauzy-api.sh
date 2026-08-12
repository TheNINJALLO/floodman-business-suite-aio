#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
tries=0
while [ ! -f "$FM_RUN/databases-ready" ]; do
  tries=$((tries + 1)); [ "$tries" -lt 900 ] || fm_die "Database bootstrap did not finish before Floodman ERP startup."
  sleep 2
done
fm_log "Starting the Floodman ERP API in non-demo mode..."
cd /srv/gauzy
exec bash -o pipefail -c 'node main.js 2>&1 | python3 -u /opt/floodman/aio/rebrand-console.py'
