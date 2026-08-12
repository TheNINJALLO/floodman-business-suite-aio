#!/usr/bin/env python3
"""Validate that a prepared RoomFlow web bundle is complete and self-consistent."""

from __future__ import annotations

import argparse
import sys
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote, urlsplit

CORE_RUNTIME = (
    "index.html",
    "app.js",
    "ar-estimator.js",
    "cost-catalog.js",
    "cost-engine.js",
    "cost-tests.js",
    "cost-ui.js",
    "document-workflow.js",
    "jobs.json",
    "migration.js",
    "renderer3d.js",
    "spatial-engine.js",
    "styles.css",
    "user-guide.html",
    "work-order.js",
    "catalog/floodman-products.json",
)
CLOUD_RUNTIME = (
    "config.js",
    "roomflow-integrations.js",
    "supabase-service.js",
    "townsquare-integration.js",
)


class ReferenceParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.references: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        values = dict(attrs)
        attribute = "href" if tag == "link" else "poster" if tag == "video" else "src"
        value = values.get(attribute)
        if value:
            self.references.append(value)


def local_path(reference: str) -> str | None:
    parsed = urlsplit(reference)
    if parsed.scheme or parsed.netloc or reference.startswith(("#", "data:", "mailto:", "javascript:")):
        return None
    path = unquote(parsed.path).lstrip("/")
    return path if path and "{" not in path else None


def validate(root: Path, mode: str, extra_required: list[str]) -> list[str]:
    required = list(CORE_RUNTIME)
    if mode in {"source", "server"}:
        required.extend(CLOUD_RUNTIME)
    required.extend(extra_required)
    problems = [f"missing required file: {name}" for name in required if not (root / name).is_file()]

    for page_name in ("index.html", "user-guide.html"):
        page = root / page_name
        if not page.is_file():
            continue
        parser = ReferenceParser()
        parser.feed(page.read_text(encoding="utf-8", errors="replace"))
        for reference in parser.references:
            path = local_path(reference)
            if path and not (root / path).is_file():
                problems.append(f"{page_name} references missing local file: {path}")
    return sorted(set(problems))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--mode", choices=("source", "server", "native"), required=True)
    parser.add_argument("--require", action="append", default=[])
    args = parser.parse_args()

    root = args.root.resolve()
    problems = validate(root, args.mode, args.require)
    if problems:
        for problem in problems:
            print(f"ERROR: {problem}", file=sys.stderr)
        return 1
    print(f"RoomFlow {args.mode} bundle validated at {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
