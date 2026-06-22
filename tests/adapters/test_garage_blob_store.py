"""Garage blob store unit tests."""

from __future__ import annotations

from dataclasses import replace

import pytest

from trading.adapters.object_store.garage import BlobChecksumMismatchError, GarageBlobStore
from trading.adapters.object_store.protocol import BlobRef, maybe_blob_json


class _Body:
    def __init__(self, body: bytes) -> None:
        self._body = body

    def read(self) -> bytes:
        return self._body


class _FakeS3Client:
    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.content_types: dict[tuple[str, str], str] = {}
        self.metadata: dict[tuple[str, str], dict[str, str]] = {}

    def put_object(self, **kwargs: object) -> dict[str, object]:
        bucket = _expect_str(kwargs["Bucket"])
        key = _expect_str(kwargs["Key"])
        body = _expect_bytes(kwargs["Body"])
        content_type = _expect_str(kwargs["ContentType"])
        metadata = _expect_metadata(kwargs["Metadata"])
        object_key = (bucket, key)
        self.objects[object_key] = body
        self.content_types[object_key] = content_type
        self.metadata[object_key] = metadata
        return {"ETag": '"fake-etag"'}

    def get_object(self, **kwargs: object) -> dict[str, object]:
        bucket = _expect_str(kwargs["Bucket"])
        key = _expect_str(kwargs["Key"])
        return {"Body": _Body(self.objects[(bucket, key)])}


def _expect_str(value: object) -> str:
    assert isinstance(value, str)
    return value


def _expect_bytes(value: object) -> bytes:
    assert isinstance(value, bytes)
    return value


def _expect_metadata(value: object) -> dict[str, str]:
    assert isinstance(value, dict)
    return {str(k): str(v) for k, v in value.items()}


def test_put_get_round_trip_verifies_checksum() -> None:
    client = _FakeS3Client()
    store = GarageBlobStore(
        endpoint_url="http://garage.local",
        bucket="tracker-blobs",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        client=client,
    )

    ref = store.put_bytes("payloads/test.json", b'{"ok":true}', "application/json")

    assert isinstance(ref, BlobRef)
    assert ref.bucket == "tracker-blobs"
    assert ref.key == "payloads/test.json"
    assert ref.size_bytes == len(b'{"ok":true}')
    assert client.metadata[("tracker-blobs", "payloads/test.json")]["sha256"] == ref.sha256
    assert store.get_bytes(ref) == b'{"ok":true}'


def test_get_bytes_raises_on_checksum_mismatch() -> None:
    client = _FakeS3Client()
    store = GarageBlobStore(
        endpoint_url="http://garage.local",
        bucket="tracker-blobs",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        client=client,
    )
    ref = store.put_bytes("payloads/test.json", b"original", "application/json")
    client.objects[("tracker-blobs", "payloads/test.json")] = b"tampered"

    with pytest.raises(BlobChecksumMismatchError):
        store.get_bytes(ref)


def test_maybe_blob_json_stores_large_payload() -> None:
    client = _FakeS3Client()
    store = GarageBlobStore(
        endpoint_url="http://garage.local",
        bucket="tracker-blobs",
        aws_access_key_id="key",
        aws_secret_access_key="secret",
        client=client,
    )

    result = maybe_blob_json(
        {"body": "x" * 20}, key="big.json", blob_store=store, threshold_bytes=8
    )

    assert isinstance(result, BlobRef)
    assert result.key == "big.json"
    assert store.get_bytes(result).startswith(b'{"body"')


def test_blob_ref_round_trip_dict() -> None:
    ref = BlobRef(
        bucket="bucket",
        key="key",
        content_type="application/json",
        size_bytes=2,
        sha256="abc",
        etag="etag",
    )

    assert BlobRef.from_dict(ref.to_dict()) == replace(ref)
