from typing import Any

import pytest

from arclith.adapters.outbound.s3 import client as s3_client
from arclith.adapters.outbound.s3.config import ResolvedS3Config
from arclith.domain.ports.outbound.file_storage import (
    FileStoragePermissionDenied,
    FileStorageUnavailable,
)
from tests.units.adapters.outbound.s3.fakes import S3ProviderError


def test_safe_create_s3_client_attaches_key_to_storage_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    expected = FileStorageUnavailable("explicit setup error")

    def create_client(_resolved: ResolvedS3Config) -> object:
        raise expected

    monkeypatch.setattr(s3_client, "create_s3_client", create_client)

    with pytest.raises(FileStorageUnavailable) as exc_info:
        s3_client.safe_create_s3_client(_resolved_config(), key="docs/readme.txt")

    assert exc_info.value is expected
    assert exc_info.value.key == "docs/readme.txt"


def test_safe_create_s3_client_maps_setup_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def create_client(_resolved: ResolvedS3Config) -> object:
        raise S3ProviderError("AccessDenied")

    monkeypatch.setattr(s3_client, "create_s3_client", create_client)

    with pytest.raises(FileStoragePermissionDenied) as exc_info:
        s3_client.safe_create_s3_client(_resolved_config(), key="docs/readme.txt")

    assert exc_info.value.key == "docs/readme.txt"


def test_create_s3_client_uses_sdk_session_and_path_style(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import boto3

    captured: dict[str, Any] = {}
    expected_client = object()

    class FakeSession:
        def __init__(self, **kwargs: Any) -> None:
            captured["session"] = kwargs

        def client(self, service_name: str, **kwargs: Any) -> object:
            captured["service_name"] = service_name
            captured["client"] = kwargs
            return expected_client

    monkeypatch.setattr(boto3, "Session", FakeSession)

    client = s3_client.create_s3_client(
        _resolved_config(
            prefix="uploads",
            region_name="eu-west-3",
            endpoint_url="http://minio:9000",
            force_path_style=True,
            profile_name="tenant-profile",
            aws_access_key_id="tenant-key",
            aws_secret_access_key="tenant-secret",
            aws_session_token="tenant-session",
        )
    )

    assert client is expected_client
    assert captured["session"] == {
        "profile_name": "tenant-profile",
        "region_name": "eu-west-3",
        "aws_access_key_id": "tenant-key",
        "aws_secret_access_key": "tenant-secret",
        "aws_session_token": "tenant-session",
    }
    assert captured["service_name"] == "s3"
    assert captured["client"]["endpoint_url"] == "http://minio:9000"
    assert captured["client"]["config"].s3 == {"addressing_style": "path"}

    captured.clear()
    s3_client.create_s3_client(_resolved_config(bucket_name="arclith-files"))

    assert captured["session"] == {}
    assert captured["service_name"] == "s3"
    assert captured["client"] == {}


def _resolved_config(**overrides: Any) -> ResolvedS3Config:
    values: dict[str, Any] = {
        "bucket_name": "arclith-files",
        "prefix": "",
        "region_name": None,
        "endpoint_url": None,
        "force_path_style": False,
        "profile_name": None,
        "aws_access_key_id": None,
        "aws_secret_access_key": None,
        "aws_session_token": None,
    }
    values.update(overrides)
    return ResolvedS3Config(**values)
