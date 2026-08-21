#!/usr/bin/env python3
from __future__ import annotations

import ast
import hashlib
import json
import os
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ERRORS: list[str] = []
WARNINGS: list[str] = []
EXCLUDED_PARTS = {
    ".git", ".gradle", ".venv", "venv", ".pytest_cache", ".mypy_cache", ".ruff_cache",
    "build", "dist", "out", "node_modules", "DerivedData", "__pycache__",
}


def error(message: str) -> None:
    ERRORS.append(message)
    print(f"ERROR: {message}")


def warning(message: str) -> None:
    WARNINGS.append(message)
    print(f"WARN: {message}")


def run(command: list[str], cwd: Path | None = None, required: bool = True) -> None:
    resolved_command = list(command)
    if os.name == "nt" and not Path(command[0]).is_absolute():
        # Windows CreateProcess searches system directories before PATH. That can
        # select the WSL bash shim even when Git Bash is first on PATH. Resolve
        # explicitly so the command verified by shutil is the command executed.
        executable = None
        if command[0].lower() == "bash":
            git = shutil.which("git")
            candidates = []
            if git:
                candidates.append(Path(git).resolve().parent.parent / "bin" / "bash.exe")
            for variable in ("ProgramW6432", "ProgramFiles", "ProgramFiles(x86)"):
                if os.getenv(variable):
                    candidates.append(Path(str(os.getenv(variable))) / "Git" / "bin" / "bash.exe")
            executable = next((str(path) for path in candidates if path.is_file()), None)
        executable = executable or shutil.which(command[0])
        if executable:
            resolved_command[0] = executable
    try:
        completed = subprocess.run(resolved_command, cwd=cwd or ROOT, text=True, capture_output=True, check=False)
    except FileNotFoundError:
        if required:
            error(f"Required command not found: {command[0]}")
        else:
            warning(f"Optional command not found: {command[0]}")
        return
    if completed.returncode:
        output = (completed.stdout + completed.stderr).strip()
        error(f"Command failed ({completed.returncode}): {' '.join(command)}\n{output[-4000:]}")


# Identity and source boundaries.
expected = {
    ROOT / "server" / "VERSION": "4.7.1",
    ROOT / "apps" / "android" / "VERSION": "0.4.0-alpha01",
    ROOT / "apps" / "ios" / "VERSION": "0.1.0-alpha03",
    ROOT / "vendor" / "roomflow" / "PINNED_COMMIT": "1f97817a52b916875e50cc6380c0d284072b8ce8",
}
for path, value in expected.items():
    if not path.exists() or path.read_text(encoding="utf-8").strip() != value:
        error(f"Version pin mismatch: {path.relative_to(ROOT)}")

# Python parse without creating __pycache__.
for path in sorted((ROOT / "server").rglob("*.py")):
    try:
        ast.parse(path.read_text(encoding="utf-8", errors="strict"), filename=str(path))
    except Exception as exc:
        error(f"Python parse failed: {path.relative_to(ROOT)}: {exc}")

# JSON, XML and plist validation.
for path in sorted(ROOT.rglob("*.json")):
    if any(part in EXCLUDED_PARTS for part in path.parts):
        continue
    try:
        json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        error(f"JSON parse failed: {path.relative_to(ROOT)}: {exc}")
for path in sorted(ROOT.rglob("*.xml")):
    if any(part in EXCLUDED_PARTS for part in path.parts):
        continue
    try:
        ET.parse(path)
    except Exception as exc:
        error(f"XML parse failed: {path.relative_to(ROOT)}: {exc}")
for path in sorted(ROOT.rglob("*.plist")):
    if any(part in EXCLUDED_PARTS for part in path.parts):
        continue
    try:
        with path.open("rb") as handle:
            plistlib.load(handle)
    except Exception as exc:
        error(f"plist parse failed: {path.relative_to(ROOT)}: {exc}")

# Shell and JavaScript syntax.
for path in sorted(ROOT.rglob("*.sh")):
    if any(part in EXCLUDED_PARTS for part in path.parts):
        continue
    run(["bash", "-n", str(path)])
raw_roomflow_export = ROOT / "server" / "roomflow" / "release-assets" / "upstream"
for path in sorted(ROOT.rglob("*.js")) + sorted(ROOT.rglob("*.mjs")):
    if any(part in EXCLUDED_PARTS | {"source"} for part in path.parts):
        continue
    # This is an immutable export of the audited upstream pin. Its known
    # duplicate job renderer is repaired by Floodman's deterministic prepare
    # overlay before execution; verify_roomflow_pin.py checks that exact input
    # and both native preparation gates syntax-check the repaired output.
    if raw_roomflow_export in path.parents:
        continue
    run(["node", "--check", str(path)], required=False)

# YAML parse if PyYAML is available.
try:
    import yaml  # type: ignore
except Exception:
    warning("PyYAML not installed; YAML syntax was not parsed by verify_repo.py")
else:
    for path in sorted(list(ROOT.rglob("*.yml")) + list(ROOT.rglob("*.yaml"))):
        if any(part in EXCLUDED_PARTS for part in path.parts):
            continue
        try:
            yaml.safe_load(path.read_text(encoding="utf-8"))
        except Exception as exc:
            error(f"YAML parse failed: {path.relative_to(ROOT)}: {exc}")

# Ensure live data and high-risk secret formats were not included.
for forbidden in ["Clients.csv", "clients.csv", "office-state.json", "tailscale-auth-key.txt"]:
    matches = [p for p in ROOT.rglob(forbidden) if "reference" not in p.parts]
    if matches:
        error(f"Live/sensitive file included: {matches[0].relative_to(ROOT)}")

secret_patterns = {
    "OpenAI key": re.compile(r"sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "Tailscale auth key": re.compile(r"tskey-[A-Za-z0-9_-]{10,}"),
    "Square production token": re.compile(r"(?<![A-Za-z0-9+/])EAAA[A-Za-z0-9_-]{20,}(?![A-Za-z0-9+/=])"),
    "private key block": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}
scan_suffixes = {".py", ".sh", ".js", ".mjs", ".kt", ".kts", ".swift", ".json", ".yml", ".yaml", ".md", ".txt", ".env", ".example", ".properties"}
for path in sorted(ROOT.rglob("*")):
    if not path.is_file() or path.suffix.lower() not in scan_suffixes:
        continue
    if any(part in EXCLUDED_PARTS for part in path.parts):
        continue
    if "release-artifacts" in path.parts or "provenance" in path.parts or "tests" in path.parts:
        continue
    text = path.read_text(encoding="utf-8", errors="ignore")
    for label, pattern in secret_patterns.items():
        if pattern.search(text):
            error(f"Possible {label} found in {path.relative_to(ROOT)}")

# Verify checked-in source manifests where possible.
def verify_manifest(base: Path, manifest: Path) -> None:
    if not manifest.exists():
        error(f"Missing manifest: {manifest.relative_to(ROOT)}")
        return
    for line_number, line in enumerate(manifest.read_text(encoding="utf-8").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(maxsplit=1)
        if len(parts) != 2:
            error(f"Malformed manifest line {manifest.relative_to(ROOT)}:{line_number}")
            continue
        expected_hash, name = parts
        name = name.lstrip("* ")
        target = base / name
        if not target.is_file():
            error(f"Manifest target missing: {target.relative_to(ROOT)}")
            continue
        actual = hashlib.sha256(target.read_bytes()).hexdigest()
        if actual != expected_hash:
            error(f"Manifest mismatch: {target.relative_to(ROOT)}")

verify_manifest(ROOT / "server", ROOT / "server" / "MANIFEST.sha256")
verify_manifest(ROOT / "apps" / "android", ROOT / "apps" / "android" / "SOURCE-MANIFEST.sha256")
verify_manifest(ROOT / "apps" / "ios", ROOT / "apps" / "ios" / "SOURCE-MANIFEST.sha256")
run([sys.executable, str(ROOT / "scripts" / "verify_roomflow_pin.py")])
run([sys.executable, str(ROOT / "scripts" / "verify_ios_readiness.py")])
run([sys.executable, str(ROOT / "scripts" / "verify_container_inputs.py")])
run([sys.executable, str(ROOT / "scripts" / "verify_pterodactyl_release.py")])

# Static contract checks.
overlay = json.loads((ROOT / "server" / "overlay.json").read_text(encoding="utf-8"))
if overlay.get("version") != "4.7.1":
    error("server/overlay.json is not v4.7.1")
mobile_api = (ROOT / "server" / "office-console" / "app" / "mobile_api.py").read_text(encoding="utf-8")
for token in ["API_VERSION = \"0.3.0-alpha11\"", "MIN_IOS_VERSION = \"0.1.0-alpha02\"", "roomflow.workspaces.v1", "roomflow.capture.v2", "roomflow.capture.offline.v1", "/mobile-api/v1", 'workspace_id: str = ""', 'raise HTTPException(422, "Select a valid RoomFlow workspace.")']:
    if token not in mobile_api:
        error(f"Mobile API contract is missing {token}")

android_api = (ROOT / "apps" / "android" / "app" / "src" / "main" / "java" / "com" / "floodman" / "operations" / "data" / "FloodmanApi.kt").read_text(encoding="utf-8")
android_roomflow = (ROOT / "apps" / "android" / "app" / "src" / "main" / "java" / "com" / "floodman" / "operations" / "roomflow" / "RoomFlowActivity.kt").read_text(encoding="utf-8")
for token in ["workspace_id=${query(workspaceId)}", "activeWorkspaceId", "repository.customers(query, 1, activeWorkspaceId)", "repository.properties(contactId, query, 1, activeWorkspaceId)"]:
    if token not in android_api + android_roomflow:
        error(f"Android RoomFlow workspace contract is missing {token}")

if ERRORS:
    print(f"\nVerification failed with {len(ERRORS)} error(s) and {len(WARNINGS)} warning(s).")
    sys.exit(1)
print(f"\nVerification passed with {len(WARNINGS)} warning(s).")
