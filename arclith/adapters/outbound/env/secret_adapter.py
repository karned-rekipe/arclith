from __future__ import annotations

import os

from arclith.domain.ports.outbound.secret_resolver import SecretResolver


class EnvSecretAdapter(SecretResolver):
    """Reads secrets from environment variables.

    The env var name is derived from field_path:
        "adapters.mongodb.uri"  →  ADAPTERS_MONGODB_URI

    Useful for CI/CD pipelines and Docker deployments where env vars are injected.
    """

    def get(self, field_path: str, secret_key: str) -> str | None:
        for env_key in _env_key_candidates(field_path, secret_key):
            value = os.environ.get(env_key)
            if value:
                return value
        return None


def _env_key_candidates(field_path: str, secret_key: str) -> tuple[str, ...]:
    candidates: list[str] = []
    explicit_key = secret_key.strip()
    if explicit_key:
        candidates.append(explicit_key)
        upper_key = explicit_key.upper()
        if upper_key != explicit_key:
            candidates.append(upper_key)

    derived_key = field_path.replace(".", "_").upper()
    if derived_key not in candidates:
        candidates.append(derived_key)

    return tuple(candidates)
