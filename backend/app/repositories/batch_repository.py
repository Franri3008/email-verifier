import time
from threading import Lock
from uuid import uuid4

from app.models.schemas.batch import StoredBatch


class BatchRepository:
    """Small in-memory download store with no persistent PII."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._items: dict[str, StoredBatch] = {}
        self._lock = Lock()

    def put(self, filename: str, content: bytes) -> str:
        self._purge_expired()
        batch_id = uuid4().hex
        with self._lock:
            self._items[batch_id] = StoredBatch(
                filename=filename,
                content=content,
                created_at=time.monotonic(),
            )
        return batch_id

    def get(self, batch_id: str) -> StoredBatch | None:
        self._purge_expired()
        with self._lock:
            return self._items.get(batch_id)

    def _purge_expired(self) -> None:
        threshold = time.monotonic() - self._ttl_seconds
        with self._lock:
            expired = [
                key
                for key, value in self._items.items()
                if value.created_at < threshold
            ]
            for key in expired:
                del self._items[key]
