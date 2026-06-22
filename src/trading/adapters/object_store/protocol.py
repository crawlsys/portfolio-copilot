"""Blob store contract and JSON offload helper."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

BLOB_JSON_THRESHOLD_BYTES = 64 * 1024
BLOB_REF_PAYLOAD_KEY = "_blob_ref"


@dataclass(frozen=True, slots=True)
class BlobRef:
    bucket: str
    key: str
    content_type: str
    size_bytes: int
    sha256: str
    etag: str | None = None

    def to_dict(self) -> dict[str, object]:
        return {
            "bucket": self.bucket,
            "key": self.key,
            "content_type": self.content_type,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "etag": self.etag,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> BlobRef:
        size_bytes = data["size_bytes"]
        if not isinstance(size_bytes, int | str):
            raise TypeError(
                f"BlobRef.size_bytes must be int or str, got {type(size_bytes).__name__}"
            )
        return cls(
            bucket=str(data["bucket"]),
            key=str(data["key"]),
            content_type=str(data["content_type"]),
            size_bytes=int(size_bytes),
            sha256=str(data["sha256"]),
            etag=str(data["etag"]) if data.get("etag") is not None else None,
        )


class BlobStore(Protocol):
    def put_bytes(self, key: str, body: bytes, content_type: str) -> BlobRef: ...

    def get_bytes(self, ref: BlobRef) -> bytes: ...


def maybe_blob_json(
    payload: dict[str, Any],
    *,
    key: str,
    blob_store: BlobStore | None,
    threshold_bytes: int = BLOB_JSON_THRESHOLD_BYTES,
) -> dict[str, Any] | BlobRef:
    """Return payload when small; store and return BlobRef when larger than threshold."""
    if blob_store is None:
        return payload

    body = json.dumps(payload, default=str, sort_keys=True, separators=(",", ":")).encode()
    if len(body) <= threshold_bytes:
        return payload
    return blob_store.put_bytes(key, body, "application/json")


def blob_ref_payload(ref: BlobRef) -> dict[str, object]:
    return {BLOB_REF_PAYLOAD_KEY: ref.to_dict()}


__all__ = [
    "BLOB_JSON_THRESHOLD_BYTES",
    "BLOB_REF_PAYLOAD_KEY",
    "BlobRef",
    "BlobStore",
    "blob_ref_payload",
    "maybe_blob_json",
]
