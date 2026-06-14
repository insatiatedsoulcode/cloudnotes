"""
File storage abstraction.

LocalStorage writes to the local filesystem.
Swap to S3Storage later by setting STORAGE_BACKEND=s3 — no router code changes required.
The StorageBackend Protocol is the only interface routers depend on.
"""

from pathlib import Path
from typing import Protocol

from app.config import settings


class StorageBackend(Protocol):
    def save(self, key: str, data: bytes, content_type: str) -> None: ...
    def get_url(self, key: str) -> str: ...
    def delete(self, key: str) -> None: ...


class LocalStorage:
    """Filesystem storage. Production swap: replace with S3Storage."""

    def __init__(self, base_dir: str, base_url: str) -> None:
        self._base = Path(base_dir)
        self._url = base_url.rstrip("/")

    def save(self, key: str, data: bytes, content_type: str) -> None:
        target = self._base / key
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)

    def get_url(self, key: str) -> str:
        return f"{self._url}/{key}"

    def delete(self, key: str) -> None:
        target = self._base / key
        if target.exists():
            target.unlink()
        try:
            target.parent.rmdir()  # remove the per-note dir if now empty
        except OSError:
            pass


def get_storage() -> StorageBackend:
    """FastAPI dependency — returns the configured storage backend.

    S3Storage would be wired here when STORAGE_BACKEND=s3.
    """
    if settings.STORAGE_BACKEND == "s3":
        raise NotImplementedError("S3 storage not yet implemented — see F-10b")
    return LocalStorage(
        base_dir=settings.UPLOADS_DIR,
        base_url=f"{settings.APP_BASE_URL}/uploads",
    )
