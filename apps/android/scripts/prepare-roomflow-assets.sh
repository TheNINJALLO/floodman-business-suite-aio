#!/usr/bin/env bash
set -euo pipefail
REF="${ROOMFLOW_REF:-1f97817a52b916875e50cc6380c0d284072b8ce8}"
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT
curl -fsSL --retry 4 --retry-delay 2 -o "$TMP/roomflow.zip" "https://codeload.github.com/TheNINJALLO/roomflow/zip/$REF"
unzip -q "$TMP/roomflow.zip" -d "$TMP/src"
SRC="$(find "$TMP/src" -mindepth 1 -maxdepth 1 -type d | head -n1)"
DEST="app/src/main/assets/roomflow"
mkdir -p "$DEST/vendor"
for file in index.html app.js ar-estimator.js cost-catalog.js cost-engine.js cost-ui.js document-workflow.js migration.js renderer3d.js spatial-engine.js styles.css user-guide.html work-order.js jobs.json; do
  [ -f "$SRC/$file" ] && cp "$SRC/$file" "$DEST/$file"
done
[ -d "$SRC/catalog" ] && rm -rf "$DEST/catalog" && cp -a "$SRC/catalog" "$DEST/catalog"
curl -fsSL --retry 4 -o "$DEST/vendor/lucide.min.js" "https://unpkg.com/lucide@0.468.0/dist/umd/lucide.min.js"
curl -fsSL --retry 4 -o "$DEST/vendor/three.min.js" "https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"
curl -fsSL --retry 4 -o "$DEST/vendor/OrbitControls.js" "https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"
python3 - <<'PYROOMFLOW'
from pathlib import Path
import re
p=Path('app/src/main/assets/roomflow/index.html')
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
    s=s.replace('</body>','<script src="floodman-native-bridge.js?v=11"></script>\n</body>')
p.write_text(s,encoding='utf-8')
PYROOMFLOW
node --check "$DEST/floodman-native-bridge.js"
test -s "$DEST/index.html" && test -s "$DEST/app.js" && test -s "$DEST/vendor/three.min.js"
echo "Prepared pinned Floodman RoomFlow engine at $DEST"
