import base64
import json
import os
from collections.abc import Mapping
from typing import Any

from arclith.adapters.outbound.gcs.config import ResolvedGCSConfig
from arclith.adapters.outbound.gcs.errors import raise_gcs_storage_error
from arclith.domain.ports.outbound.file_storage import (
    FileStorageError,
    FileStorageUnavailable,
)

_CREDENTIALS_PATH_ENV = "ARCLITH_GCS_CREDENTIALS_PATH"
_CREDENTIALS_JSON_ENV = "ARCLITH_GCS_CREDENTIALS_JSON"
_CREDENTIALS_JSON_B64_ENV = "ARCLITH_GCS_CREDENTIALS_JSON_B64"


def safe_create_gcs_client(resolved: ResolvedGCSConfig, *, key: str) -> Any:
    try:
        return create_gcs_client(resolved)
    except FileStorageError as e:
        if e.key is None:
            e.key = key
        raise
    except Exception as e:
        raise_gcs_storage_error(e, key=key)


def create_gcs_client(resolved: ResolvedGCSConfig) -> Any:
    try:
        from google.cloud import storage
        from google.oauth2 import service_account
    except ImportError as e:
        raise FileStorageUnavailable(
            "gcs storage requires optional dependency arclith[gcs]"
        ) from e

    credentials = _credentials_from_sources(resolved, service_account)
    client_kwargs = _without_none(
        {
            "project": resolved.project_id,
            "credentials": credentials,
        }
    )
    return storage.Client(**client_kwargs)


def _credentials_from_sources(
    resolved: ResolvedGCSConfig,
    service_account: Any,
) -> Any | None:
    if resolved.credentials_json is not None:
        return _credentials_from_json(resolved.credentials_json, service_account)
    if resolved.credentials_json_b64 is not None:
        return _credentials_from_json_b64(
            resolved.credentials_json_b64, service_account
        )
    if resolved.credentials_path is not None:
        return _credentials_from_file(resolved.credentials_path, service_account)

    env_json = _optional_env(_CREDENTIALS_JSON_ENV)
    if env_json is not None:
        return _credentials_from_json(env_json, service_account)

    env_json_b64 = _optional_env(_CREDENTIALS_JSON_B64_ENV)
    if env_json_b64 is not None:
        return _credentials_from_json_b64(env_json_b64, service_account)

    env_path = _optional_env(_CREDENTIALS_PATH_ENV)
    if env_path is not None:
        return _credentials_from_file(env_path, service_account)

    return None


def _credentials_from_json(value: str, service_account: Any) -> Any:
    try:
        info = json.loads(value)
        if not isinstance(info, Mapping):
            raise ValueError("GCS credentials JSON must be an object")
        return service_account.Credentials.from_service_account_info(dict(info))
    except Exception as e:
        raise FileStorageUnavailable("gcs storage credentials are invalid") from e


def _credentials_from_json_b64(value: str, service_account: Any) -> Any:
    try:
        decoded = base64.b64decode(value, validate=True).decode()
    except Exception as e:
        raise FileStorageUnavailable("gcs storage credentials are invalid") from e
    return _credentials_from_json(decoded, service_account)


def _credentials_from_file(path: str, service_account: Any) -> Any:
    try:
        return service_account.Credentials.from_service_account_file(path)
    except Exception as e:
        raise FileStorageUnavailable("gcs storage credentials are invalid") from e


def _optional_env(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _without_none(values: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in values.items() if value is not None}
