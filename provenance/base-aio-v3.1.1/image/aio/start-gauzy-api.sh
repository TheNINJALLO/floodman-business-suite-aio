#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
tries=0
while [ ! -f "$FM_RUN/databases-ready" ]; do
  tries=$((tries + 1)); [ "$tries" -lt 900 ] || fm_die "Database bootstrap did not finish before Gauzy startup."
  sleep 2
done
fm_log "Starting genuine Gauzy API in non-demo mode..."
cd /srv/gauzy
exec node main.js
