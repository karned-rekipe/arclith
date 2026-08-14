from arclith.adapters.context import set_tenant_context
from arclith.adapters.outbound.gcs.config import (
    GCSStorageConfig,
    normalize_optional_prefix,
    resolve_gcs_config,
)
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext


def test_resolve_gcs_config_uses_base_config_without_tenant_context() -> None:
    resolved = resolve_gcs_config(
        GCSStorageConfig(
            bucket_name="arclith-files",
            prefix="unused",
            project_id=" project-a ",
            credentials_path=" /run/secrets/gcs.json ",
            credentials_json_b64=" encoded ",
        ),
        base_prefix=normalize_optional_prefix("uploads"),
    )

    assert resolved.bucket_name == "arclith-files"
    assert resolved.prefix == "uploads"
    assert resolved.project_id == "project-a"
    assert resolved.credentials_path == "/run/secrets/gcs.json"
    assert resolved.credentials_json is None
    assert resolved.credentials_json_b64 == "encoded"


def test_resolve_gcs_config_uses_tenant_defaults_when_fields_are_absent() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "gcs": AdapterTenantCoords(
                    params={
                        "bucket_name": "tenant-bucket",
                        "project": "tenant-project",
                        "service_account_file": "/run/secrets/gcs.json",
                        "service_account_json_b64": "eyJ0eXBlIjoic2VydmljZV9hY2NvdW50In0=",
                    }
                )
            }
        )
    )
    try:
        resolved = resolve_gcs_config(
            GCSStorageConfig(
                bucket_name="fallback-bucket",
                project_id="fallback-project",
                multitenant=True,
            ),
            base_prefix=normalize_optional_prefix("fallback-prefix"),
        )
    finally:
        token.var.reset(token)

    assert resolved.bucket_name == "tenant-bucket"
    assert resolved.prefix == "fallback-prefix"
    assert resolved.project_id == "tenant-project"
    assert resolved.credentials_path == "/run/secrets/gcs.json"
    assert resolved.credentials_json is None
    assert resolved.credentials_json_b64 == "eyJ0eXBlIjoic2VydmljZV9hY2NvdW50In0="


def test_resolve_gcs_config_uses_tenant_prefix_and_credentials_json() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "gcs": AdapterTenantCoords(
                    params={
                        "prefix": "tenant-a",
                        "credentials_json": '{"type":"service_account"}',
                    }
                )
            }
        )
    )
    try:
        resolved = resolve_gcs_config(
            GCSStorageConfig(bucket_name="fallback-bucket", multitenant=True),
            base_prefix=normalize_optional_prefix("fallback-prefix"),
        )
    finally:
        token.var.reset(token)

    assert resolved.bucket_name == "fallback-bucket"
    assert resolved.prefix == "tenant-a"
    assert resolved.credentials_json == '{"type":"service_account"}'


def test_resolve_gcs_config_keeps_base_credentials_without_tenant_override() -> None:
    token = set_tenant_context(
        TenantContext(
            adapters={
                "gcs": AdapterTenantCoords(
                    params={
                        "bucket_name": "tenant-bucket",
                    }
                )
            }
        )
    )
    try:
        resolved = resolve_gcs_config(
            GCSStorageConfig(
                bucket_name="fallback-bucket",
                credentials_json_b64="fallback-encoded",
                multitenant=True,
            ),
            base_prefix="",
        )
    finally:
        token.var.reset(token)

    assert resolved.bucket_name == "tenant-bucket"
    assert resolved.credentials_json_b64 == "fallback-encoded"
