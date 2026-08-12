#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
exec postgres -D "$FM_DATA/postgres" -k "$FM_RUN/postgres" -h 127.0.0.1 -p 5432
