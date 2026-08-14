#!/usr/bin/env bash
set -euo pipefail
APP_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
REPO_ROOT="$(cd "$APP_ROOT/../.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3}"
REF="${ROOMFLOW_REF:-$(tr -d '\r\n' < "$REPO_ROOT/vendor/roomflow/PINNED_COMMIT")}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
if [ -n "${ROOMFLOW_SOURCE_DIR:-}" ]; then
  SRC="$(cd "$ROOMFLOW_SOURCE_DIR" && pwd)"
else
  curl -fsSL --retry 4 --retry-delay 2 -o "$TMP/roomflow.zip" "https://codeload.github.com/TheNINJALLO/roomflow/zip/$REF"
  unzip -q "$TMP/roomflow.zip" -d "$TMP/src"
  SRC="$(find "$TMP/src" -mindepth 1 -maxdepth 1 -type d | head -n1)"
fi
DEST="${ROOMFLOW_DEST:-$APP_ROOT/app/src/main/assets/roomflow}"
mkdir -p "$DEST"
find "$DEST" -depth -mindepth 1 \
  ! -path "$DEST/ASSETS_FETCHED_BY_GITHUB_ACTIONS.txt" \
  ! -path "$DEST/floodman-native-bridge.js" \
  -delete
mkdir -p "$DEST/vendor"
for file in index.html app.js ar-estimator.js cost-catalog.js cost-engine.js cost-tests.js cost-ui.js document-workflow.js migration.js renderer3d.js spatial-engine.js styles.css user-guide.html work-order.js jobs.json; do
  test -f "$SRC/$file"
  cp "$SRC/$file" "$DEST/$file"
done
test -f "$SRC/catalog/floodman-products.json"
rm -rf "$DEST/catalog" && cp -a "$SRC/catalog" "$DEST/catalog"
"$PYTHON_BIN" "$REPO_ROOT/scripts/patch_roomflow_bundle.py" --root "$DEST"
curl -fsSL --retry 4 -o "$DEST/vendor/lucide.min.js" "https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js"
curl -fsSL --retry 4 -o "$DEST/vendor/three.min.js" "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
curl -fsSL --retry 4 -o "$DEST/vendor/OrbitControls.js" "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"
ROOMFLOW_DEST_PATH="$DEST" ROOMFLOW_REF_VALUE="$REF" "$PYTHON_BIN" - <<'PYROOMFLOW'
from pathlib import Path
import json
import os
import re
p=Path(os.environ['ROOMFLOW_DEST_PATH']) / 'index.html'
s=p.read_text(encoding='utf-8')
s=s.replace('<title>RoomFlow - Interactive 2D/3D Room Layout & Estimation</title>','<title>Floodman RoomFlow</title>')
s=s.replace('<h1>RoomFlow<span>Sketcher</span></h1>','<h1>Floodman<span>RoomFlow</span></h1>')
s=re.sub(r'\s*<link rel="preconnect" href="https://fonts[^>]+>','',s)
s=re.sub(r'\s*<link href="https://fonts\.googleapis\.com[^>]+>','',s)
s=s.replace('<script src="https://unpkg.com/lucide@latest"></script>','<script src="vendor/lucide.min.js"></script>')
s=s.replace('<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>','')
s=re.sub(r'\s*<script src="config\.js[^>]*></script>','',s)
s=s.replace('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>','<script src="vendor/three.min.js"></script>')
s=s.replace('<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>','<script src="vendor/OrbitControls.js"></script>')
for name in ('supabase-service.js','roomflow-integrations.js','townsquare-integration.js'):
    s=re.sub(rf'\s*<script src="{re.escape(name)}[^>]*></script>','',s)
s=s.replace('onclick="RoomFlowAuth.signOut()"','onclick="FloodmanNative.close()"')
if 'floodman-native-bridge.js' not in s:
    s=s.replace('</body>','<script src="floodman-native-bridge.js?v=12"></script>\n</body>')
p.write_text(s,encoding='utf-8')
(p.parent / 'floodman-roomflow.json').write_text(json.dumps({
    'release': '4.6.9',
    'base_commit': os.environ['ROOMFLOW_REF_VALUE'],
    'prepared_by': 'Floodman Operations Android',
    'created_by': 'Josh Aldrich',
    'timezone': 'America/Detroit',
}, indent=2), encoding='utf-8')
PYROOMFLOW
node --check "$DEST/floodman-native-bridge.js"
"$PYTHON_BIN" "$REPO_ROOT/scripts/validate_roomflow_web.py" --root "$DEST" --mode native --require floodman-native-bridge.js --require floodman-roomflow.json
echo "Prepared pinned Floodman RoomFlow engine at $DEST"
