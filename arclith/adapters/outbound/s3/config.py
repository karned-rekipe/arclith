from dataclasses import dataclass

from arclith.adapters.context import get_adapter_tenant_context
from arclith.adapters.outbound.storage.config import (
    optional_text,
    tenant_bool,
    tenant_first_text,
    tenant_optional_text,
    tenant_prefix,
)


@dataclass(frozen=True)
class S3StorageConfig:
    bucket_name: str | None = None
    prefix: str = ""
    region_name: str | None = None
    endpoint_url: str | None = None
    force_path_style: bool = False
    multitenant: bool = False


@dataclass(frozen=True)
class ResolvedS3Config:
    bucket_name: str | None
    prefix: str
    region_name: str | None
    endpoint_url: str | None
    force_path_style: bool
    profile_name: str | None = None
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_session_token: str | None = None


def resolve_s3_config(
    config: S3StorageConfig,
    *,
    base_prefix: str,
    key: str,
) -> ResolvedS3Config:
    base = ResolvedS3Config(
        bucket_name=optional_text(config.bucket_name),
        prefix=base_prefix,
        region_name=optional_text(config.region_name),
        endpoint_url=optional_text(config.endpoint_url),
        force_path_style=config.force_path_style,
    )
    if not config.multitenant:
        return base

    coords = get_adapter_tenant_context("s3")
    if coords is None:
        return base

    return ResolvedS3Config(
        bucket_name=tenant_optional_text(coords, "bucket_name", base.bucket_name),
        prefix=tenant_prefix(coords, base.prefix),
        region_name=tenant_first_text(
            coords, ("region_name", "region"), base.region_name
        ),
        endpoint_url=tenant_optional_text(coords, "endpoint_url", base.endpoint_url),
        force_path_style=tenant_bool(
            coords,
            "force_path_style",
            base.force_path_style,
            key,
            adapter_label="s3",
        ),
        profile_name=tenant_optional_text(coords, "profile_name", None),
        aws_access_key_id=tenant_first_text(
            coords, ("aws_access_key_id", "access_key_id"), None
        ),
        aws_secret_access_key=tenant_first_text(
            coords,
            ("aws_secret_access_key", "secret_access_key"),
            None,
        ),
        aws_session_token=tenant_first_text(
            coords, ("aws_session_token", "session_token"), None
        ),
    )
