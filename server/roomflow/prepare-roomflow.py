from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import zipfile
from html.parser import HTMLParser
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit

RELEASE = "4.7.3"
ROOMFLOW_COMMIT = "1f97817a52b916875e50cc6380c0d284072b8ce8"
ARCHIVE_URL = f"https://github.com/TheNINJALLO/roomflow/archive/{ROOMFLOW_COMMIT}.tar.gz"
RELEASE_ASSETS = Path(__file__).resolve().with_name("release-assets")
CORE_RUNTIME = (
    "index.html", "app.js", "ar-estimator.js", "cost-catalog.js", "cost-engine.js",
    "cost-tests.js", "cost-ui.js", "document-workflow.js", "jobs.json", "migration.js",
    "renderer3d.js", "spatial-engine.js", "styles.css", "user-guide.html", "work-order.js",
    "catalog/floodman-products.json",
)
CLOUD_RUNTIME = ("config.js", "roomflow-integrations.js", "supabase-service.js", "townsquare-integration.js")
ESSENTIAL = CORE_RUNTIME + CLOUD_RUNTIME
EXCLUDED_TOP = {
    ".git", ".github", ".gradle", "app", "build", "gradle", "supabase",
    "sync-station", "tests", "node_modules", "dist", "townsquare-bridge-extension",
}


def safe_member(name: str) -> bool:
    value = str(name or "").replace("\\", "/")
    path = PurePosixPath(value)
    return bool(value) and not path.is_absolute() and ".." not in path.parts


def archive_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class LocalReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        attribute = "href" if tag == "link" else "poster" if tag == "video" else "src"
        value = values.get(attribute)
        if value:
            self.references.append(value)


def validate_web_runtime(root: Path) -> None:
    missing = [name for name in ESSENTIAL if not (root / name).is_file()]
    for page_name in ("index.html", "user-guide.html"):
        page = root / page_name
        if not page.is_file():
            continue
        parser = LocalReferenceParser()
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        for reference in parser.references:
            parsed = urlsplit(reference)
            if parsed.scheme or parsed.netloc or reference.startswith(("#", "data:", "mailto:", "javascript:")):
                continue
            local = unquote(parsed.path).lstrip("/")
            if not local or "{" in local:
                continue
            resolved = root / local
            if not resolved.is_file():
                missing.append(f"{page_name} -> {local}")
    if missing:
        raise RuntimeError("RoomFlow web runtime is incomplete: " + ", ".join(sorted(set(missing))))


def verify_release_assets(root: Path) -> str:
    manifest = root / "SHA256SUMS"
    if not manifest.is_file():
        raise RuntimeError("checksummed RoomFlow release assets are missing")
    declared: dict[str, str] = {}
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        parts = line.split("  ", 1)
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-f]{64}", parts[0]) or not safe_member(parts[1]):
            raise RuntimeError(f"invalid RoomFlow release asset manifest row {line_number}")
        if parts[1] in declared:
            raise RuntimeError(f"duplicate RoomFlow release asset path: {parts[1]}")
        declared[parts[1]] = parts[0]
    actual = {
        path.relative_to(root).as_posix(): archive_sha256(path)
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    if set(actual) != set(declared):
        raise RuntimeError("RoomFlow release asset manifest and packaged files differ")
    changed = [name for name, expected in declared.items() if actual[name] != expected]
    if changed:
        raise RuntimeError("RoomFlow release asset checksum differs: " + ", ".join(changed))
    if (root / "PINNED_COMMIT").read_text(encoding="utf-8").strip() != ROOMFLOW_COMMIT:
        raise RuntimeError("RoomFlow release asset pin differs from the server contract")
    validate_web_runtime(root / "upstream")
    return archive_sha256(manifest)


def extract_archive(archive: Path, destination: Path) -> Path:
    destination.mkdir(parents=True, exist_ok=True)
    if zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as bundle:
            for info in bundle.infolist():
                if not safe_member(info.filename):
                    raise RuntimeError(f"Unsafe RoomFlow ZIP path: {info.filename}")
            bundle.extractall(destination)
    else:
        with tarfile.open(archive, "r:*") as bundle:
            for member in bundle.getmembers():
                if not safe_member(member.name) or member.issym() or member.islnk():
                    raise RuntimeError(f"Unsafe RoomFlow archive entry: {member.name}")
            bundle.extractall(destination)
    candidates = [path for path in destination.iterdir() if path.is_dir()]
    root = candidates[0] if len(candidates) == 1 else destination
    validate_web_runtime(root)
    return root


def copy_web_source(source: Path, target: Path) -> None:
    staging = target.parent / f".{target.name}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    for entry in source.iterdir():
        if entry.name in EXCLUDED_TOP or entry.name.startswith("."):
            continue
        destination = staging / entry.name
        if entry.is_dir():
            shutil.copytree(
                entry,
                destination,
                ignore=shutil.ignore_patterns("*.apk", "*.aab", "*.keystore", "*.jks", "*.class", "*.jar", "*.lock"),
            )
        elif entry.is_file():
            shutil.copy2(entry, destination)
    validate_web_runtime(staging)
    backup = target.parent / f".{target.name}.previous"
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.rename(backup)
    staging.rename(target)
    shutil.rmtree(backup, ignore_errors=True)


def repair_job_list_renderers(target: Path) -> None:
    """Separate two same-name upstream renderers at the reviewed RoomFlow pin."""
    app = target / "app.js"
    text = app.read_text(encoding="utf-8")
    declaration = "function renderJobsList() {"
    first = text.find(declaration)
    second = text.find(declaration, first + len(declaration)) if first >= 0 else -1
    if first < 0:
        raise RuntimeError("RoomFlow app.js does not contain its jobs renderer")
    if second < 0:
        if "function renderLegacyJobsList() {" in text and "function refreshJobLists() {" in text:
            return
        raise RuntimeError("RoomFlow app.js jobs renderer layout differs from the reviewed pin")
    prefix = text[:second].replace("renderJobsList", "refreshJobLists")
    marker = "// Render jobs list helper\nfunction refreshJobLists() {"
    replacement = (
        "// Keep the toolbar job database and the newer dashboard in sync.\n"
        "function refreshJobLists() {\n"
        "    renderLegacyJobsList();\n"
        "    renderJobsList();\n"
        "}\n\n"
        "// Render jobs list helper\n"
        "function renderLegacyJobsList() {"
    )
    if marker not in prefix:
        raise RuntimeError("RoomFlow legacy jobs renderer marker differs from the reviewed pin")
    app.write_text(prefix.replace(marker, replacement, 1) + text[second:], encoding="utf-8")


def inject_panel(target: Path, overlay: Path) -> None:
    repair_job_list_renderers(target)
    (target / "vendor").mkdir(parents=True, exist_ok=True)
    for name in ("lucide.min.js", "three.min.js", "OrbitControls.js"):
        shutil.copy2(RELEASE_ASSETS / "vendor" / name, target / "vendor" / name)
    shutil.copy2(overlay / "floodman-panel.css", target / "floodman-panel.css")
    shutil.copy2(overlay / "floodman-panel.js", target / "floodman-panel.js")
    shutil.copy2(overlay / "capture" / "roomflow-capture.css", target / "roomflow-capture.css")
    shutil.copy2(overlay / "capture" / "roomflow-capture-geometry.js", target / "roomflow-capture-geometry.js")
    shutil.copy2(overlay / "capture" / "roomflow-capture.js", target / "roomflow-capture.js")

    index = target / "index.html"
    text = index.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<title>.*?</title>", "<title>Floodman RoomFlow</title>", text, count=1, flags=re.I | re.S)
    text = re.sub(r'\s*<link rel="preconnect" href="https://fonts[^>]+>', "", text)
    text = re.sub(r'\s*<link href="https://fonts\.googleapis\.com[^>]+>', "", text)
    text = text.replace('<script src="https://unpkg.com/lucide@latest"></script>', '<script src="vendor/lucide.min.js"></script>')
    text = text.replace('<script src="https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2"></script>', "")
    text = text.replace('<script src="https://cdnjs.cloudflare.com/ajax/libs/three.js/r128/three.min.js"></script>', '<script src="vendor/three.min.js"></script>')
    text = text.replace('<script src="https://cdn.jsdelivr.net/npm/three@0.128.0/examples/js/controls/OrbitControls.js"></script>', '<script src="vendor/OrbitControls.js"></script>')
    if "name=\"viewport\"" not in text and "name='viewport'" not in text:
        text = text.replace("</head>", '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n</head>', 1)
    if "floodman-panel.css" not in text:
        text = text.replace("</head>", f'<link rel="stylesheet" href="floodman-panel.css?v={RELEASE}">\n</head>', 1)
    if "roomflow-capture.css" not in text:
        text = text.replace("</head>", f'<link rel="stylesheet" href="roomflow-capture.css?v={RELEASE}">\n</head>', 1)
    if "floodman-panel.js" not in text:
        text = text.replace("</body>", f'<script src="floodman-panel.js?v={RELEASE}"></script>\n</body>', 1)
    if "roomflow-capture-geometry.js" not in text:
        text = text.replace("</body>", f'<script src="roomflow-capture-geometry.js?v={RELEASE}"></script>\n</body>', 1)
    if "roomflow-capture.js" not in text:
        text = text.replace("</body>", f'<script src="roomflow-capture.js?v={RELEASE}"></script>\n</body>', 1)
    index.write_text(text, encoding="utf-8")

    config = target / "config.js"
    config_text = config.read_text(encoding="utf-8", errors="replace")
    config_text = re.sub(
        r"\n?\(function\s+loadTownsquareIntegration\s*\(\)\s*\{.*?\}\)\(\);?",
        "\n// Legacy Townsquare browser bridge disabled in Floodman Operations.\n",
        config_text,
        flags=re.S,
    )
    marker = "window.FLOODMAN_ROOMFLOW_EMBEDDED"
    if marker not in config_text:
        config_text += f"""
window.FLOODMAN_ROOMFLOW_EMBEDDED = true;
window.FLOODMAN_ROOMFLOW_RELEASE = '{RELEASE}';
window.FLOODMAN_ROOMFLOW_DISABLE_LEGACY_CLOUD = true;
// Floodman Operations is the only durable source of truth in embedded mode.
// The upstream Supabase organization/login system remains disabled so staff
// use their existing Floodman session and permissions.
if (window.RoomFlowConfig) {{
  window.RoomFlowConfig.supabaseUrl = '';
  window.RoomFlowConfig.supabaseAnonKey = '';
}}
"""
    config.write_text(config_text, encoding="utf-8")

    metadata = {
        "release": RELEASE,
        "base_commit": ROOMFLOW_COMMIT,
        "prepared_by": "Floodman Operations",
        "created_by": "Josh Aldrich",
        "timezone": "America/Detroit",
        "capture_schema_version": 2,
        "asset_manifest_sha256": verify_release_assets(RELEASE_ASSETS),
    }
    (target / ".floodman-roomflow.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    validate_web_runtime(target)


def fallback(target: Path, error: Exception) -> None:
    target.mkdir(parents=True, exist_ok=True)
    message = str(error).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    (target / "index.html").write_text(
        f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Floodman RoomFlow</title><style>body{{margin:0;background:#eef5fb;color:#102443;font-family:"Segoe UI",Arial,sans-serif;display:grid;place-items:center;min-height:100vh;padding:24px;box-sizing:border-box}}main{{max-width:650px;background:#fff;border-radius:22px;padding:28px;box-shadow:0 22px 60px rgba(15,43,70,.17)}}a{{color:#146ca4}}</style></head><body><main><h1>Floodman RoomFlow package needs attention</h1><p>The Floodman suite is running, but its checksummed RoomFlow release assets could not be prepared.</p><pre>{message}</pre><p>Reinstall the matching Floodman runtime package. Do not substitute an unreviewed RoomFlow download.</p><p><a href='/office' target='_top'>Return to Floodman Operations</a></p></main></body></html>""",
        encoding="utf-8",
    )
    (target / ".floodman-roomflow-error.txt").write_text(str(error), encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--target", default="/home/container/data/roomflow/current")
    parser.add_argument("--overlay", required=True)
    parser.add_argument("--archive", default="")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    target = Path(args.target)
    overlay = Path(args.overlay)
    metadata_path = target / ".floodman-roomflow.json"

    try:
        if metadata_path.exists() and not args.force:
            current = json.loads(metadata_path.read_text(encoding="utf-8"))
            if current.get("base_commit") == ROOMFLOW_COMMIT and all((target / name).is_file() for name in ESSENTIAL):
                inject_panel(target, overlay)
                if current.get("release") == RELEASE:
                    print(f"Floodman RoomFlow {RELEASE} already prepared at {target}")
                else:
                    print(f"Floodman RoomFlow upgraded in place to {RELEASE} at {target}")
                return 0

        if args.archive:
            archive = Path(args.archive)
            if not archive.is_file():
                raise RuntimeError(f"RoomFlow source archive does not exist: {archive}")
            with tempfile.TemporaryDirectory(prefix="floodman-roomflow-") as temp_name:
                print(f"RoomFlow source archive SHA-256: {archive_sha256(archive)}")
                extracted = extract_archive(archive, Path(temp_name) / "source")
                copy_web_source(extracted, target)
        else:
            manifest_hash = verify_release_assets(RELEASE_ASSETS)
            print(f"Using checksummed RoomFlow release assets: {manifest_hash}")
            copy_web_source(RELEASE_ASSETS / "upstream", target)
        inject_panel(target, overlay)
        print(f"Floodman RoomFlow {RELEASE} prepared at {target}")
        return 0
    except Exception as exc:
        if target.is_dir() and (target / "index.html").is_file():
            try:
                inject_panel(target, overlay)
                (target / ".floodman-roomflow-error.txt").write_text(str(exc), encoding="utf-8")
                print(f"WARNING: RoomFlow refresh failed; retained existing copy: {exc}")
                return 0
            except Exception:
                pass
        fallback(target, exc)
        print(f"WARNING: RoomFlow source could not be prepared: {exc}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
