from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

RELEASE = "4.6.7"
ROOMFLOW_COMMIT = "1f97817a52b916875e50cc6380c0d284072b8ce8"
ARCHIVE_URL = f"https://github.com/TheNINJALLO/roomflow/archive/{ROOMFLOW_COMMIT}.tar.gz"
ESSENTIAL = ("index.html", "app.js", "styles.css", "config.js", "supabase-service.js")
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


def download(url: str, destination: Path) -> None:
    request = urllib.request.Request(url, headers={"User-Agent": "Floodman-RoomFlow/4.6.7"})
    with urllib.request.urlopen(request, timeout=180) as response, destination.open("wb") as output:
        shutil.copyfileobj(response, output)


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
    if not all((root / name).is_file() for name in ESSENTIAL):
        raise RuntimeError("RoomFlow archive does not contain the expected web application files")
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
    for required in ESSENTIAL:
        if not (staging / required).is_file():
            raise RuntimeError(f"RoomFlow staging copy is missing {required}")
    backup = target.parent / f".{target.name}.previous"
    shutil.rmtree(backup, ignore_errors=True)
    if target.exists():
        target.rename(backup)
    staging.rename(target)
    shutil.rmtree(backup, ignore_errors=True)


def inject_panel(target: Path, overlay: Path) -> None:
    shutil.copy2(overlay / "floodman-panel.css", target / "floodman-panel.css")
    shutil.copy2(overlay / "floodman-panel.js", target / "floodman-panel.js")

    index = target / "index.html"
    text = index.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"<title>.*?</title>", "<title>Floodman RoomFlow</title>", text, count=1, flags=re.I | re.S)
    if "name=\"viewport\"" not in text and "name='viewport'" not in text:
        text = text.replace("</head>", '<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">\n</head>', 1)
    if "floodman-panel.css" not in text:
        text = text.replace("</head>", f'<link rel="stylesheet" href="floodman-panel.css?v={RELEASE}">\n</head>', 1)
    if "floodman-panel.js" not in text:
        text = text.replace("</body>", f'<script src="floodman-panel.js?v={RELEASE}"></script>\n</body>', 1)
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
    }
    (target / ".floodman-roomflow.json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")


def fallback(target: Path, error: Exception) -> None:
    target.mkdir(parents=True, exist_ok=True)
    message = str(error).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    (target / "index.html").write_text(
        f"""<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Floodman RoomFlow</title><style>body{{margin:0;background:#eef5fb;color:#102443;font-family:Inter,Segoe UI,Arial,sans-serif;display:grid;place-items:center;min-height:100vh;padding:24px;box-sizing:border-box}}main{{max-width:650px;background:#fff;border-radius:22px;padding:28px;box-shadow:0 22px 60px rgba(15,43,70,.17)}}a{{color:#146ca4}}</style></head><body><main><h1>Floodman RoomFlow needs its source download</h1><p>The Floodman suite is running, but the pinned RoomFlow source could not be prepared.</p><pre>{message}</pre><p>Restart after outbound GitHub access is available, or upload a RoomFlow source archive as <code>/home/container/roomflow-source.zip</code>.</p><p><a href='/office' target='_top'>Return to Floodman Operations</a></p></main></body></html>""",
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

        with tempfile.TemporaryDirectory(prefix="floodman-roomflow-") as temp_name:
            temp = Path(temp_name)
            local_candidates = [
                Path(args.archive) if args.archive else None,
                Path("/home/container/roomflow-source.zip"),
                Path("/home/container/roomflow-source.tar.gz"),
            ]
            archive = next((path for path in local_candidates if path and path.is_file()), None)
            if archive is None:
                archive = temp / "roomflow.tar.gz"
                print(f"Downloading pinned RoomFlow source {ROOMFLOW_COMMIT[:12]}...")
                download(ARCHIVE_URL, archive)
            print(f"RoomFlow source archive SHA-256: {archive_sha256(archive)}")
            extracted = extract_archive(archive, temp / "source")
            copy_web_source(extracted, target)
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
