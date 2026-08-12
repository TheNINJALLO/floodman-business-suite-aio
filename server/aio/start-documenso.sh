#!/bin/sh
set -eu
. /opt/floodman/aio/common.sh
tries=0
while [ ! -f "$FM_RUN/databases-ready" ]; do
  tries=$((tries + 1)); [ "$tries" -lt 900 ] || fm_die "Database bootstrap did not finish before Documenso startup."
  sleep 2
done
cert="$FM_DATA/documenso/cert.p12"
if [ ! -s "$cert" ]; then
  fm_log "Generating persistent local Documenso signing certificate..."
  tmp="$FM_RUN/documenso-cert"
  rm -rf "$tmp" && mkdir -p "$tmp"
  openssl req -x509 -newkey rsa:2048 -sha256 -nodes -days 3650 \
    -subj "/CN=Floodman Test Signing/O=Floodman/C=US" \
    -keyout "$tmp/key.pem" -out "$tmp/cert.pem" >/dev/null 2>&1
  openssl pkcs12 -export -out "$tmp/cert.p12" -inkey "$tmp/key.pem" -in "$tmp/cert.pem" \
    -passout pass:"$DOCUMENSO_SIGNING_PASSPHRASE" -name "Floodman Test Signing" >/dev/null 2>&1
  openssl pkcs12 -in "$tmp/cert.p12" -passin pass:"$DOCUMENSO_SIGNING_PASSPHRASE" -noout
  mv "$tmp/cert.p12" "$cert"
  chmod 0600 "$cert"
  rm -rf "$tmp"
fi
fm_log "Starting Documenso on port $DOCUMENSO_PORT..."
cd /opt/documenso/apps/remix
export PATH="/opt/documenso-runtime/usr/local/bin:$PATH"
exec sh start.sh
