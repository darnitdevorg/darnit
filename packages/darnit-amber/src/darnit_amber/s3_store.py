"""S3-compatible ``AttestationStore`` backend (AWS S3, GCS interop, R2, MinIO).

Registered under ``darnit.stores.attestation`` as ``s3``. Configure in the
``[stores.attestation]`` block: ``backend = "s3"``, ``bucket``, optional
``prefix`` (default ``amber/runs``), ``endpoint_url`` and ``region``.
Credentials come from the usual boto3 chain (env, profile, instance role).
Objects are keyed by bundle id, so a bundle is written once and never changes.
"""

from __future__ import annotations

from typing import Any

from darnit.stores.errors import StoreOperationError

_CONTENT_TYPE_EXT = {
    "application/vnd.in-toto+json": ".intoto.json",
    "application/vnd.dev.sigstore.bundle+json": ".sigstore.json",
    "application/json": ".json",
}


class S3AttestationStore:
    _BACKEND_NAME = "s3"

    def __init__(
        self,
        bucket: str,
        prefix: str = "amber/runs",
        endpoint_url: str | None = None,
        region: str | None = None,
        **_: object,
    ) -> None:
        import boto3  # type: ignore[import-untyped]

        if not bucket:
            raise StoreOperationError(f"{self._BACKEND_NAME}: 'bucket' is required")
        self._bucket = bucket
        self._prefix = prefix.strip("/")
        self._client = boto3.client("s3", endpoint_url=endpoint_url, region_name=region)

    def _key(self, bundle_id: str, content_type: str) -> str:
        safe = "".join(c for c in bundle_id if c.isalnum() or c in "-_.")
        ext = _CONTENT_TYPE_EXT.get(content_type, ".bin")
        return f"{self._prefix}/{safe}{ext}" if self._prefix else f"{safe}{ext}"

    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        key = self._key(bundle_id, content_type)
        try:
            self._client.put_object(Bucket=self._bucket, Key=key, Body=bundle_bytes, ContentType=content_type)
        except Exception as e:  # botocore raises many classes; all are failures here
            raise StoreOperationError(f"{self._BACKEND_NAME}: write of s3://{self._bucket}/{key} failed: {e}") from e

    def read(self, bundle_id: str, content_type: str = "application/vnd.in-toto+json") -> bytes:
        key = self._key(bundle_id, content_type)
        try:
            return self._client.get_object(Bucket=self._bucket, Key=key)["Body"].read()
        except Exception as e:
            raise StoreOperationError(f"{self._BACKEND_NAME}: read of s3://{self._bucket}/{key} failed: {e}") from e

    def write_blob(self, key: str, data: bytes) -> None:
        """An object next to the bundles (experiment outputs); key is relative to the prefix."""
        full = f"{self._prefix}/{key}" if self._prefix else key
        try:
            self._client.put_object(Bucket=self._bucket, Key=full, Body=data)
        except Exception as e:
            raise StoreOperationError(f"{self._BACKEND_NAME}: write of s3://{self._bucket}/{full} failed: {e}") from e

    def read_blob(self, key: str) -> bytes:
        full = f"{self._prefix}/{key}" if self._prefix else key
        try:
            return self._client.get_object(Bucket=self._bucket, Key=full)["Body"].read()
        except Exception as e:
            raise StoreOperationError(f"{self._BACKEND_NAME}: read of s3://{self._bucket}/{full} failed: {e}") from e

    def list_bundles(self) -> list[str]:
        """Bundle ids under the prefix (additive extension; not in the v0 Protocol)."""
        ids: list[str] = []
        try:
            paginator = self._client.get_paginator("list_objects_v2")
            kw: dict[str, Any] = {"Bucket": self._bucket}
            if self._prefix:
                kw["Prefix"] = self._prefix + "/"
            for page in paginator.paginate(**kw):
                for obj in page.get("Contents", []):
                    name = obj["Key"].rsplit("/", 1)[-1]
                    ids.append(name.split(".", 1)[0])
        except Exception as e:
            raise StoreOperationError(f"{self._BACKEND_NAME}: list failed: {e}") from e
        return ids

    def close(self) -> None:
        self._client.close()
