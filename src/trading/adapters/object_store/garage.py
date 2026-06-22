"""Garage-backed blob store.

Garage exposes an S3-compatible API, so this adapter uses boto3 with the
configured endpoint URL supplied by the composition root.
"""

from __future__ import annotations

import hashlib
from typing import Any, Protocol, cast

import boto3

from trading.adapters.object_store.protocol import BlobRef


class BlobChecksumMismatchError(RuntimeError):
    """Raised when a fetched blob does not match its recorded checksum."""


class _ReadableBody(Protocol):
    def read(self) -> bytes: ...


class GarageBlobStore:
    """S3-compatible blob store for Garage."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        bucket: str,
        aws_access_key_id: str,
        aws_secret_access_key: str,
        region_name: str = "us-east-1",
        client: Any | None = None,
    ) -> None:
        self._bucket = bucket
        self._client = client or boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=aws_access_key_id,
            aws_secret_access_key=aws_secret_access_key,
            region_name=region_name,
        )

    def put_bytes(self, key: str, body: bytes, content_type: str) -> BlobRef:
        checksum = hashlib.sha256(body).hexdigest()
        response = cast(
            dict[str, object],
            self._client.put_object(
                Bucket=self._bucket,
                Key=key,
                Body=body,
                ContentType=content_type,
                Metadata={"sha256": checksum},
            ),
        )
        etag = response.get("ETag")
        return BlobRef(
            bucket=self._bucket,
            key=key,
            content_type=content_type,
            size_bytes=len(body),
            sha256=checksum,
            etag=str(etag) if etag is not None else None,
        )

    def get_bytes(self, ref: BlobRef) -> bytes:
        response = cast(
            dict[str, object],
            self._client.get_object(Bucket=ref.bucket, Key=ref.key),
        )
        body = cast(_ReadableBody, response["Body"]).read()
        checksum = hashlib.sha256(body).hexdigest()
        if checksum != ref.sha256:
            raise BlobChecksumMismatchError(
                f"Checksum mismatch for {ref.bucket}/{ref.key}: expected {ref.sha256}, got {checksum}"
            )
        return body


__all__ = ["BlobChecksumMismatchError", "GarageBlobStore"]
