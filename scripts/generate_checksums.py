#!/usr/bin/env python3
from __future__ import annotations
import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {'.git', '.gradle', 'build', 'DerivedData', '__pycache__', 'source'}
EXCLUDED_FILES = {'SHA256SUMS'}
rows=[]
for path in sorted(ROOT.rglob('*')):
    if not path.is_file():
        continue
    rel=path.relative_to(ROOT)
    if any(part in EXCLUDED_DIRS for part in rel.parts) or rel.name in EXCLUDED_FILES:
        continue
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):
            h.update(chunk)
    rows.append(f"{h.hexdigest()}  {rel.as_posix()}")
(ROOT/'SHA256SUMS').write_text('\n'.join(rows)+'\n',encoding='utf-8')
print(f"Wrote {len(rows)} checksums")
