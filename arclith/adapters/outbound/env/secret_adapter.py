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
        env_key = field_path.replace(".", "_").upper()
        return os.environ.get(env_key) or None

