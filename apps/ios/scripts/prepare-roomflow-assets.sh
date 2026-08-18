#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$APP_ROOT/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
NODE_BIN="${NODE_BIN:-node}"
node_check() {
  local target="$1"
  case "$NODE_BIN" in *.exe) target="$(wslpath -w "$target")" ;; esac
  "$NODE_BIN" --check "$target"
}
REF="${ROOMFLOW_REF:-$(tr -d '\r\n' < "$REPO_ROOT/vendor/roomflow/PINNED_COMMIT")}"
BUNDLE="$REPO_ROOT/server/roomflow/release-assets"
if [ -n "${ROOMFLOW_SOURCE_DIR:-}" ]; then
  SRC="$(cd "$ROOMFLOW_SOURCE_DIR" && pwd)"
else
  "$PYTHON_BIN" "$REPO_ROOT/scripts/verify_roomflow_release_assets.py"
  SRC="$BUNDLE/upstream"
fi
DEST="${ROOMFLOW_DEST:-$APP_ROOT/FloodmanOperations/Resources/RoomFlow}"
mkdir -p "$DEST"
find "$DEST" -depth -mindepth 1 \
  ! -path "$DEST/floodman-ios-bridge.js" \
  -delete
mkdir -p "$DEST/vendor"
for f in index.html app.js ar-estimator.js cost-catalog.js cost-engine.js cost-tests.js cost-ui.js document-workflow.js migration.js renderer3d.js spatial-engine.js styles.css user-guide.html work-order.js jobs.json;do test -f "$SRC/$f";cp "$SRC/$f" "$DEST/$f";done
test -f "$SRC/catalog/floodman-products.json"
rm -rf "$DEST/catalog"&&cp -a "$SRC/catalog" "$DEST/catalog"
"$PYTHON_BIN" "$REPO_ROOT/scripts/patch_roomflow_bundle.py" --root "$DEST"
cp "$BUNDLE/vendor/lucide.min.js" "$DEST/vendor/lucide.min.js"
cp "$BUNDLE/vendor/three.min.js" "$DEST/vendor/three.min.js"
cp "$BUNDLE/vendor/OrbitControls.js" "$DEST/vendor/OrbitControls.js"
cp "$REPO_ROOT/server/roomflow/capture/roomflow-capture-schema-v2.json" "$DEST/roomflow-capture-schema-v2.json"
cp "$REPO_ROOT/server/roomflow/capture/roomflow-capture-geometry.js" "$DEST/roomflow-capture-geometry.js"
cp "$REPO_ROOT/server/roomflow/capture/roomflow-capture.css" "$DEST/roomflow-capture.css"
cp "$REPO_ROOT/server/roomflow/capture/roomflow-capture.js" "$DEST/roomflow-capture.js"
ROOMFLOW_DEST_PATH="$DEST" ROOMFLOW_REF_VALUE="$REF" ROOMFLOW_ASSET_MANIFEST="$(sha256sum "$BUNDLE/SHA256SUMS" | awk '{print $1}')" "$PYTHON_BIN" - <<'PYROOMFLOW'
from pathlib import Path
import json
import os
import re
p=Path(os.environ['ROOMFLOW_DEST_PATH']) / 'index.html';s=p.read_text(encoding='utf-8')
s=s.replace('<title>RoomFlow - Interactive 2D/3D Room Layout & Estimation</title>','<title>Floodman RoomFlow</title>').replace('<h1>RoomFlow<span>Sketcher</span></h1>','<h1>Floodman<span>RoomFlow</span></h1>')
s=re.sub(r'\s*<link rel="preconnect" href="https://fonts[^>]+>','',s);s=re.sub(r'\s*<link href="https://fonts\.googleapis\.com[^>]+>','',s)
s=s.replace('<script src="https://unpkg.com/lucide@latest"></script>','<script src="vendor/lucide.min.js"></script>').replace('<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>','')
s=re.sub(r'\s*<script src="config\.js[^>]*></script>','',s).replace('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>','<script src="vendor/three.min.js"></script>').replace('<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>','<script src="vendor/OrbitControls.js"></script>')
for name in ('supabase-service.js','roomflow-integrations.js','townsquare-integration.js'):s=re.sub(rf'\s*<script src="{name}[^>]*></script>','',s)
s=s.replace('onclick="RoomFlowAuth.signOut()"','onclick="FloodmanRoomFlow.close()"')
if 'roomflow-capture.css' not in s:s=s.replace('</head>','<link rel="stylesheet" href="roomflow-capture.css?v=2">\n</head>')
scripts='\n'.join(('<script src="floodman-ios-bridge.js?v=3"></script>','<script src="roomflow-capture-geometry.js?v=2"></script>','<script src="roomflow-capture.js?v=2"></script>'))
if 'roomflow-capture.js' not in s:s=s.replace('</body>',scripts+'\n</body>')
p.write_text(s, encoding='utf-8')
(p.parent / 'floodman-roomflow.json').write_text(json.dumps({
    'release': '4.7.0',
    'base_commit': os.environ['ROOMFLOW_REF_VALUE'],
    'asset_manifest_sha256': os.environ['ROOMFLOW_ASSET_MANIFEST'],
    'prepared_by': 'Floodman Operations iOS',
    'created_by': 'Josh Aldrich',
    'timezone': 'America/Detroit',
    'capture_schema_version': 2,
}, indent=2), encoding='utf-8')
PYROOMFLOW
node_check "$DEST/floodman-ios-bridge.js"
node_check "$DEST/roomflow-capture-geometry.js"
node_check "$DEST/roomflow-capture.js"
"$PYTHON_BIN" "$REPO_ROOT/scripts/validate_roomflow_web.py" --root "$DEST" --mode native --require floodman-ios-bridge.js --require floodman-roomflow.json --require roomflow-capture-schema-v2.json --require roomflow-capture-geometry.js --require roomflow-capture.css --require roomflow-capture.js
echo "Prepared pinned Floodman RoomFlow engine at $DEST"
