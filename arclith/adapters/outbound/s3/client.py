from collections.abc import Mapping
from typing import Any

from arclith.adapters.outbound.s3.config import ResolvedS3Config
from arclith.adapters.outbound.s3.errors import raise_s3_storage_error
from arclith.domain.ports.outbound.file_storage import (
    FileStorageError,
    FileStorageUnavailable,
)


def safe_create_s3_client(resolved: ResolvedS3Config, *, key: str) -> Any:
    try:
        return create_s3_client(resolved)
    except FileStorageError as e:
        if e.key is None:
            e.key = key
        raise
    except Exception as e:
        raise_s3_storage_error(e, key=key)


def create_s3_client(resolved: ResolvedS3Config) -> Any:
    try:
        import boto3
        from botocore.config import Config
    except ImportError as e:
        raise FileStorageUnavailable(
            "s3 storage requires optional dependency arclith[s3]"
        ) from e

    session_kwargs = _without_none(
        {
            "profile_name": resolved.profile_name,
            "region_name": resolved.region_name,
            "aws_access_key_id": resolved.aws_access_key_id,
            "aws_secret_access_key": resolved.aws_secret_access_key,
            "aws_session_token": resolved.aws_session_token,
        }
    )
    client_kwargs = _without_none({"endpoint_url": resolved.endpoint_url})
    if resolved.force_path_style:
        client_kwargs["config"] = Config(s3={"addressing_style": "path"})

    session = boto3.Session(**session_kwargs)
    return session.client("s3", **client_kwargs)


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
