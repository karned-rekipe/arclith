from abc import ABC, abstractmethod


class SecretResolver(ABC):
    @abstractmethod
    def get(self, field_path: str, secret_key: str) -> str | None:
        """
        Resolve a secret value.

        :param field_path: dot-notation config field (e.g. "adapters.mongodb.uri")
        :param secret_key: adapter-specific key (e.g. Vault path "rekipe/recipe/mongodb")
        """
        pass  # pragma: no cover

