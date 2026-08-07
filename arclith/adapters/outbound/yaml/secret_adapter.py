from __future__ import annotations

from pathlib import Path

import yaml

from arclith.domain.ports.outbound.secret_resolver import SecretResolver


class YamlSecretAdapter(SecretResolver):
    """Reads secrets from a gitignored YAML file (local dev fallback).

    The file mirrors the config.yaml structure — only secret fields need to appear.

    Example secrets.yaml:
        adapters:
          mongodb:
            uri: mongodb://localhost:5971
        lm:
          intent_interpreter:
            api_key: sk-ant-xxxx
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._data: dict | None = None

    def _load(self) -> dict:
        if self._data is None:
            if self._path.exists():
                with self._path.open() as f:
                    self._data = yaml.safe_load(f) or {}
            else:
                self._data = {}
        return self._data

    def get(self, field_path: str, secret_key: str) -> str | None:
        data = self._load()
        current: object = data
        for key in field_path.split("."):
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return str(current) if current is not None else None
