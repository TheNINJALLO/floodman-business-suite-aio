#!/bin/sh
set -eu
cd /opt/floodman/messaging-ai
export PYTHONPATH="/opt/pydeps/messaging-ai:/opt/floodman/messaging-ai"
exec python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8100 --no-access-log
