#!/usr/bin/env python3
from __future__ import annotations

import ast
import csv
import hashlib
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVER = ROOT / "server"
OUT = ROOT / "docs" / "generated"
OUT.mkdir(parents=True, exist_ok=True)

TEXT_SUFFIXES = {
    ".py", ".sh", ".bash", ".js", ".mjs", ".ts", ".tsx", ".kt", ".kts", ".swift",
    ".json", ".yml", ".yaml", ".xml", ".plist", ".html", ".css", ".md", ".txt", ".sql",
    ".template", ".env", ".properties", ".gradle",
}
EXCLUDE_PARTS = {".git", ".gradle", "build", "DerivedData", "__pycache__", "release-artifacts", "source", "generated"}
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "options", "head", "api_route", "websocket"}


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def text_file(path: Path) -> bool:
    return path.suffix.lower() in TEXT_SUFFIXES or path.name in {"Dockerfile", "Makefile", "VERSION", "REPOSITORY", "PINNED_COMMIT"}


def service_for(path: Path) -> str:
    parts = path.relative_to(SERVER).parts
    return parts[0] if parts else "server"


def constant_string(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def scan_router_prefixes(path: Path, tree: ast.AST) -> dict[str, str]:
    constants: dict[str, str] = {}
    prefixes: dict[str, str] = {}
    for node in getattr(tree, "body", []):
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            value = node.value
            string = constant_string(value) if value else None
            if string:
                for target in targets:
                    if isinstance(target, ast.Name):
                        constants[target.id] = string
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Call):
            call = node.value
            func_name = call.func.id if isinstance(call.func, ast.Name) else (call.func.attr if isinstance(call.func, ast.Attribute) else "")
            if func_name != "APIRouter":
                continue
            prefix = ""
            for kw in call.keywords:
                if kw.arg == "prefix":
                    prefix = constant_string(kw.value) or (constants.get(kw.value.id, "") if isinstance(kw.value, ast.Name) else "")
            for target in node.targets:
                if isinstance(target, ast.Name):
                    prefixes[target.id] = prefix
    # Builder functions often create `router = APIRouter(...)` inside a function.
    if path.name == "mobile_api.py":
        prefixes["router"] = constants.get("API_PREFIX", "/mobile-api/v1")
    return prefixes


def route_inventory() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for path in sorted(SERVER.rglob("*.py")):
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="ignore"))
        except SyntaxError:
            continue
        prefixes = scan_router_prefixes(path, tree)
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            for decorator in node.decorator_list:
                if not isinstance(decorator, ast.Call):
                    continue
                func = decorator.func
                if not isinstance(func, ast.Attribute) or func.attr not in HTTP_METHODS:
                    continue
                router_name = func.value.id if isinstance(func.value, ast.Name) else ""
                method = func.attr.upper()
                path_value = constant_string(decorator.args[0]) if decorator.args else ""
                prefix = prefixes.get(router_name, "")
                full_path = f"{prefix.rstrip('/')}/{path_value.lstrip('/')}" if prefix and path_value else (prefix or path_value)
                if full_path and not full_path.startswith("/"):
                    full_path = "/" + full_path
                rows.append({
                    "service": service_for(path),
                    "method": method,
                    "path": path_value,
                    "effective_path": full_path,
                    "handler": node.name,
                    "source_file": path.relative_to(ROOT).as_posix(),
                    "line": node.lineno,
                })
    return sorted(rows, key=lambda row: (str(row["service"]), str(row["effective_path"]), str(row["method"])))


def environment_inventory() -> list[dict[str, object]]:
    references: dict[str, set[str]] = defaultdict(set)
    defaults: dict[str, set[str]] = defaultdict(set)
    patterns = [
        re.compile(r"(?:os\.getenv|os\.environ\.get|environ\.get)\(\s*['\"]([A-Z][A-Z0-9_]+)['\"](?:\s*,\s*([^\)]+))?"),
        re.compile(r"\$\{([A-Z][A-Z0-9_]+)(?::-[^}]*)?\}"),
        re.compile(r"(?<![A-Z0-9_])\$([A-Z][A-Z0-9_]+)"),
    ]
    for path in sorted(SERVER.rglob("*")):
        if not path.is_file() or not text_file(path):
            continue
        rel = path.relative_to(ROOT).as_posix()
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pattern in patterns:
            for match in pattern.finditer(text):
                name = match.group(1)
                references[name].add(rel)
                if len(match.groups()) > 1 and match.group(2):
                    defaults[name].add(match.group(2).strip()[:120])
    return [
        {
            "name": name,
            "default_expressions": " | ".join(sorted(defaults.get(name, set()))),
            "referenced_by": " | ".join(sorted(references[name])),
            "reference_count": len(references[name]),
        }
        for name in sorted(references)
    ]


def source_inventory() -> list[dict[str, object]]:
    rows = []
    for path in sorted(ROOT.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(ROOT)
        if any(part in EXCLUDE_PARTS for part in rel.parts):
            continue
        size = path.stat().st_size
        line_count = ""
        if text_file(path):
            try:
                line_count = len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
            except OSError:
                pass
        rows.append({
            "path": rel.as_posix(),
            "size_bytes": size,
            "lines": line_count,
            "sha256": sha256(path),
            "extension": path.suffix.lower() or path.name,
        })
    return rows


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    target = OUT / name
    if not rows:
        target.write_text("", encoding="utf-8")
        return
    with target.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


routes = route_inventory()
envs = environment_inventory()
sources = source_inventory()
write_csv("API_ROUTE_INVENTORY.csv", routes)
write_csv("ENVIRONMENT_VARIABLES.csv", envs)
write_csv("SOURCE_MANIFEST.csv", sources)

route_counts = Counter(str(row["service"]) for row in routes)
ext_counts = Counter(str(row["extension"]) for row in sources)
source_bytes = sum(int(row["size_bytes"]) for row in sources)
source_lines = sum(int(row["lines"]) for row in sources if row["lines"] != "")
stats = {
    "generated_at_note": "Generated from the checked-in handoff source; no live customer data was inspected.",
    "route_count": len(routes),
    "route_counts_by_service": dict(sorted(route_counts.items())),
    "environment_variable_count": len(envs),
    "source_file_count": len(sources),
    "source_bytes": source_bytes,
    "text_line_count": source_lines,
    "file_counts_by_extension": dict(sorted(ext_counts.items())),
}
(OUT / "SOURCE_STATS.json").write_text(json.dumps(stats, indent=2) + "\n", encoding="utf-8")

lines = [
    "# Generated source inventory", "",
    f"- FastAPI route decorators found: **{len(routes)}**",
    f"- Environment variable names referenced: **{len(envs)}**",
    f"- Files included in the source inventory: **{len(sources)}**",
    f"- Text lines counted: **{source_lines:,}**",
    f"- Inventory bytes: **{source_bytes:,}**", "",
    "## Routes by service", "",
]
for service, count in sorted(route_counts.items()):
    lines.append(f"- `{service}`: {count}")
lines += ["", "The complete machine-readable inventories are adjacent CSV files.", ""]
(OUT / "README.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps(stats, indent=2))
