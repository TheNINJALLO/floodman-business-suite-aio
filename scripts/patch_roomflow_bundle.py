#!/usr/bin/env python3
"""Apply release-reviewed compatibility fixes to a prepared pinned RoomFlow bundle."""

from __future__ import annotations

import argparse
from pathlib import Path


def repair_job_list_renderers(app_path: Path) -> bool:
    text = app_path.read_text(encoding="utf-8")
    declaration = "function renderJobsList() {"
    first = text.find(declaration)
    second = text.find(declaration, first + len(declaration)) if first >= 0 else -1
    if first < 0:
        raise RuntimeError("RoomFlow app.js does not contain its jobs renderer")
    if second < 0:
        # Already repaired bundles contain one dashboard renderer and one named
        # legacy renderer.
        if "function renderLegacyJobsList() {" in text and "function refreshJobLists() {" in text:
            return False
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
    prefix = prefix.replace(marker, replacement, 1)
    app_path.write_text(prefix + text[second:], encoding="utf-8")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    app_path = args.root.resolve() / "app.js"
    changed = repair_job_list_renderers(app_path)
    print(f"RoomFlow compatibility overlay {'applied' if changed else 'already present'} at {args.root.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
