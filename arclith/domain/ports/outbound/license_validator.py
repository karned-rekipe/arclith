from abc import ABC, abstractmethod


class LicenseValidator(ABC):
    @abstractmethod
    def validate(self, claims: dict) -> bool: ...

