from __future__ import annotations

import os
import tempfile
from pathlib import Path

from .security import sha256_hex


class ImmutableStorage:
    def __init__(self, root: Path):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def store(self, *, job_id: str, kind: str, revision: int, body: bytes, signed: bool) -> tuple[str, str]:
        digest = sha256_hex(body)
        directory = self.root / job_id / kind.lower()
        directory.mkdir(parents=True, exist_ok=True)
        os.chmod(directory, 0o700)
        suffix = "signed" if signed else "source"
        path = directory / f"r{revision}-{suffix}-{digest[:16]}.pdf"
        if path.exists():
            existing = path.read_bytes()
            if sha256_hex(existing) != digest:
                raise RuntimeError("Immutable document path collision")
            return str(path), digest
        fd, temporary_name = tempfile.mkstemp(prefix=path.stem + "-", suffix=".tmp", dir=directory)
        temporary = Path(temporary_name)
        try:
            os.chmod(temporary, 0o600)
            with os.fdopen(fd, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            os.chmod(path, 0o400)
        finally:
            temporary.unlink(missing_ok=True)
        return str(path), digest
