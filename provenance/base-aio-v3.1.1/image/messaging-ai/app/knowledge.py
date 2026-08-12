from __future__ import annotations

from pathlib import Path


def load_approved_knowledge() -> str:
    root = Path(__file__).resolve().parent.parent / "knowledge"
    chunks: list[str] = []
    for path in sorted(root.glob("*.md")):
        chunks.append(f"# SOURCE: {path.name}\n{path.read_text(encoding='utf-8')[:12000]}")
    return "\n\n".join(chunks)[:40000]
