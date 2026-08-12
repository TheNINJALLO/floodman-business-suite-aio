#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
export LAB_STATE_DIR="$FM_DATA/lab-state"
cd /opt/floodman/local-lab
export PYTHONPATH="/opt/pydeps/local-lab:/opt/floodman/local-lab"
exec python3 -m uvicorn app.main:app --host 0.0.0.0 --port "$ENGINEERING_PORT" --no-access-log
