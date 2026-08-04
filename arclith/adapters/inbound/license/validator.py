from arclith.domain.ports.outbound.license_validator import LicenseValidator


class RoleLicenseValidator(LicenseValidator):
    """Valide la licence en vérifiant la présence d'un Keycloak realm role dans les claims JWT."""

    def __init__(self, role: str) -> None:
        self._role = role

    def validate(self, claims: dict) -> bool:
        roles: list = claims.get("realm_access", {}).get("roles", [])
        return self._role in roles

