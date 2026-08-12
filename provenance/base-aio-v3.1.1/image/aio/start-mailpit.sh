#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
exec /usr/local/bin/mailpit --listen "0.0.0.0:${MAILPIT_PORT}" --smtp "127.0.0.1:1026" --database "$FM_DATA/mailpit/mailpit.db" --max 1000
