"""Refresh only Office/orchestrator Python source inside the immutable bundled ZIP."""
from __future__ import annotations
import hashlib
import zipfile
from pathlib import Path


def refresh(archive: Path, source: Path) -> None:
    prefix = 'floodman-operations-v4.7.3/'
    with zipfile.ZipFile(archive) as current:
        entries = {item.filename: (item, current.read(item)) for item in current.infolist()}
    manifest_name = prefix + 'MANIFEST.sha256'
    for line in entries[manifest_name][1].decode().splitlines():
        digest, name = line.split('  ', 1)
        content = entries[prefix + name.removeprefix('./')][1]
        if hashlib.sha256(content).hexdigest() != digest:
            raise RuntimeError('Original runtime checksum failed: ' + name)
    for service in ('office-console', 'orchestrator'):
        for path in sorted((source / service / 'app').rglob('*.py')):
            relative = path.relative_to(source).as_posix()
            name = prefix + relative
            info = entries.get(name, (zipfile.ZipInfo(name, (2026,9,11,0,0,0)), b''))[0]
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            entries[name] = (info, path.read_bytes())
    rows = [hashlib.sha256(content).hexdigest() + '  ./' + name.removeprefix(prefix)
            for name, (_, content) in sorted(entries.items()) if name != manifest_name and not name.endswith('/')]
    entries[manifest_name] = (entries[manifest_name][0], ('\n'.join(rows)+'\n').encode())
    temporary = archive.with_suffix('.portal-next.zip')
    with zipfile.ZipFile(temporary, 'x', compression=zipfile.ZIP_DEFLATED) as updated:
        for name, (info, content) in sorted(entries.items()): updated.writestr(info, content)
    with zipfile.ZipFile(temporary) as checked:
        for line in rows:
            digest, name = line.split('  ', 1)
            assert hashlib.sha256(checked.read(prefix + name.removeprefix('./'))).hexdigest() == digest
    temporary.replace(archive)


if __name__ == '__main__':
    refresh(Path('/opt/floodman/unified/assets/floodman-operations-runtime-v4.7.3.zip'), Path('/opt/floodman'))
