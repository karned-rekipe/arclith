import pytest

from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.s3.config import (
    S3StorageConfig,
    normalize_optional_prefix,
    resolve_s3_config,
)
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext
from arclith.domain.ports.outbound.file_storage import FileStorageUnavailable


def test_resolve_s3_config_uses_base_config_without_tenant_context() -> None:
    resolved = resolve_s3_config(
        S3StorageConfig(
            bucket_name="arclith-files",
            prefix="unused",
            region_name=" eu-west-3 ",
            endpoint_url=" http://minio:9000 ",
            force_path_style=True,
        ),
        base_prefix=normalize_optional_prefix("uploads"),
        key="docs/readme.txt",
    )

    assert resolved.bucket_name == "arclith-files"
    assert resolved.prefix == "uploads"
    assert resolved.region_name == "eu-west-3"
    assert resolved.endpoint_url == "http://minio:9000"
    assert resolved.force_path_style is True
    assert resolved.profile_name is None


def test_resolve_s3_config_uses_tenant_defaults_when_fields_are_absent() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "s3": AdapterTenantCoords(params={"bucket_name": "tenant-bucket"})
            }
        )
    )
    try:
        resolved = resolve_s3_config(
            S3StorageConfig(
                bucket_name="fallback-bucket",
                region_name=" ",
                force_path_style=False,
                multitenant=True,
            ),
            base_prefix=normalize_optional_prefix("fallback-prefix"),
            key="docs/readme.txt",
        )
    finally:
        token.var.reset(token)

    assert resolved.bucket_name == "tenant-bucket"
    assert resolved.prefix == "fallback-prefix"
    assert resolved.region_name is None
    assert resolved.force_path_style is False


def test_resolve_s3_config_rejects_invalid_tenant_boolean() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "s3": AdapterTenantCoords(
                    params={
                        "bucket_name": "tenant-bucket",
                        "force_path_style": "maybe",
                    }
                )
            }
        )
    )
    try:
        with pytest.raises(
            FileStorageUnavailable, match="force_path_style"
        ) as exc_info:
            resolve_s3_config(
                S3StorageConfig(bucket_name="fallback", multitenant=True),
                base_prefix="",
                key="docs/readme.txt",
            )
    finally:
        token.var.reset(token)

    assert exc_info.value.key == "docs/readme.txt"
