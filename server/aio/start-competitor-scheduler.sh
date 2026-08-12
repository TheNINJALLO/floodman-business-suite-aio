#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
while [ ! -f "$FM_RUN/databases-ready" ]; do sleep 2; done
cd /opt/floodman/competitor-intel
export PYTHONPATH="/opt/pydeps/competitor-intel:/opt/floodman/competitor-intel"
exec python3 -m app.scheduler
