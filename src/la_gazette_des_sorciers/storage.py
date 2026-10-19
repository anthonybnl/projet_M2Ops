"""Stockage des données. Backend local pour l'instant, à remplacer par du S3."""

import os
from pathlib import Path


class LocalStorage:
    """Même interface qu'un bucket S3 : des clés `a/b/c.json` sous une racine."""

    def __init__(self, root: str | Path | None = None):
        self.root = Path(root or os.environ.get("DATA_DIR", "data"))

    def put(self, key: str, data: bytes) -> Path:
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def get(self, key: str) -> bytes:
        return (self.root / key).read_bytes()

    def list(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(p.relative_to(self.root).as_posix() for p in base.rglob("*") if p.is_file())
