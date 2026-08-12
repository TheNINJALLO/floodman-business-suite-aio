#!/bin/sh
set -eu
cd /home/container
: "${STARTUP:=/opt/floodman/aio/start-suite.sh}"
# Pterodactyl passes the resolved startup string in STARTUP.
exec /bin/sh -lc "$STARTUP"
