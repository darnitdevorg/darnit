"""S3 attestation store backend (#677): tested against moto's in-process fake."""

import os

import pytest

pytest.importorskip("moto")
from darnit_amber.s3_store import S3AttestationStore  # noqa: E402
from moto import mock_aws  # noqa: E402

from darnit.stores.errors import StoreOperationError  # noqa: E402
from darnit.stores.protocols import AttestationStore  # noqa: E402

BUCKET = "amber-test"


@pytest.fixture(autouse=True)
def _aws_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for k, v in {
        "AWS_ACCESS_KEY_ID": "test",
        "AWS_SECRET_ACCESS_KEY": "test",
        "AWS_DEFAULT_REGION": "us-east-1",
    }.items():
        monkeypatch.setenv(k, v)
    for k in ("AWS_PROFILE", "AWS_ENDPOINT_URL"):
        monkeypatch.delenv(k, raising=False)
    assert os.environ["AWS_DEFAULT_REGION"] == "us-east-1"


@pytest.fixture
def store() -> S3AttestationStore:
    with mock_aws():
        import boto3

        boto3.client("s3").create_bucket(Bucket=BUCKET)
        yield S3AttestationStore(bucket=BUCKET, prefix="amber/runs")


def test_satisfies_protocol(store: S3AttestationStore) -> None:
    assert isinstance(store, AttestationStore)


def test_write_then_read_and_list(store: S3AttestationStore) -> None:
    store.write("abc123", b'{"id":"abc123"}', "application/vnd.in-toto+json")
    assert store.read("abc123") == b'{"id":"abc123"}'
    assert store.list_bundles() == ["abc123"]


def test_prefix_and_extension_in_key(store: S3AttestationStore) -> None:
    assert store._key("x", "application/vnd.in-toto+json") == "amber/runs/x.intoto.json"
    assert store._key("../y", "application/json") == "amber/runs/..y.json"


def test_missing_bundle_raises_store_error(store: S3AttestationStore) -> None:
    with pytest.raises(StoreOperationError):
        store.read("nope")


def test_write_to_missing_bucket_raises_store_error() -> None:
    with mock_aws():
        s = S3AttestationStore(bucket="does-not-exist")
        with pytest.raises(StoreOperationError):
            s.write("a", b"{}", "application/json")


def test_bucket_required() -> None:
    with pytest.raises(StoreOperationError):
        S3AttestationStore(bucket="")
