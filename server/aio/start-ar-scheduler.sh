#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
while [ ! -f "$FM_RUN/databases-ready" ] || [ ! -f "$FM_RUN/gauzy-finalized" ]; do sleep 2; done
cd /opt/floodman/orchestrator
export PYTHONPATH="/opt/pydeps/orchestrator:/opt/floodman/orchestrator"
exec python3 -m app.ar_scheduler
