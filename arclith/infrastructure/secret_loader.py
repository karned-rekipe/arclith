from __future__ import annotations

from copy import deepcopy
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arclith.domain.ports.outbound.secret_resolver import SecretResolver


def resolve_dict_secrets(data: dict, resolver: "SecretResolver") -> dict:
    """Inject resolved secrets into a raw config dict.

    Operates on a deepcopy — the original dict is never mutated.
    Works with any dict structure: AppConfig, AgentConfig, or any custom config.

    :param data: raw config dict (from yaml.safe_load)
    :param resolver: SecretResolver instance (Vault, Yaml, Env, Chain…)
    :returns: new dict with secrets injected at their dot-notation paths
    """
    secrets: dict = data.get("secrets") or {}
    mappings: dict[str, str] = secrets.get("mappings") or {}
    if not mappings:
        return data

    result = deepcopy(data)
    missing: list[str] = []

    for field_path, secret_key in mappings.items():
        value = resolver.get(field_path, secret_key)
        if value is not None:
            _set_nested(result, field_path, value)
        else:
            missing.append(field_path)

    if missing:
        raise RuntimeError(
            f"Secrets non résolus pour les champs suivants : {missing}. "
            "Vérifiez votre Vault, secrets.yaml ou variables d'environnement."
        )

    return result


def _set_nested(data: dict, path: str, value: str) -> None:
    keys = path.split(".")
    current = data
    for key in keys[:-1]:
        if not isinstance(current.get(key), dict):
            current[key] = {}
        current = current[key]
    current[keys[-1]] = value

