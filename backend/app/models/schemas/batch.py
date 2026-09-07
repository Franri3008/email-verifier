from dataclasses import dataclass


@dataclass(slots=True)
class StoredBatch:
    filename: str
    content: bytes
    created_at: float
