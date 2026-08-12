#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
while [ ! -f "$FM_RUN/databases-ready" ] || [ ! -f "$FM_RUN/gauzy-finalized" ]; do sleep 2; done
cd /opt/floodman/office-console
export PYTHONPATH="/opt/pydeps/office-console:/opt/floodman/office-console"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8700 --no-access-log
