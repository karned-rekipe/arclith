from arclith.domain.models.tenant import AdapterTenantCoords
from arclith.domain.ports.outbound.file_storage import (
    FileStorageUnavailable,
    normalize_storage_key,
)

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})


def normalize_optional_prefix(prefix: str) -> str:
    if not prefix:
        return ""
    return normalize_storage_key(prefix)


def optional_text(value: str | None) -> str | None:
    if value is None:
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def tenant_prefix(coords: AdapterTenantCoords, fallback: str) -> str:
    if "prefix" not in coords.params:
        return fallback
    return normalize_optional_prefix(coords.params["prefix"])


def tenant_optional_text(
    coords: AdapterTenantCoords,
    key: str,
    fallback: str | None,
) -> str | None:
    if key not in coords.params:
        return fallback
    return optional_text(coords.params[key])


def tenant_first_text(
    coords: AdapterTenantCoords,
    keys: tuple[str, ...],
    fallback: str | None,
) -> str | None:
    for key in keys:
        if key in coords.params:
            return optional_text(coords.params[key])
    return fallback


def tenant_bool(
    coords: AdapterTenantCoords,
    field: str,
    fallback: bool,
    key: str,
    *,
    adapter_label: str,
    aliases: tuple[str, ...] = (),
) -> bool:
    value = tenant_first_text(coords, (field, *aliases), None)
    if value is None:
        return fallback
    normalized = value.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise FileStorageUnavailable(
        f"{adapter_label} storage tenant field {field} must be boolean",
        key=key,
    )
