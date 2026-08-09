from arclith.adapters.inbound.license.validator import RoleLicenseValidator


def test_role_license_validator_accepts_configured_realm_role() -> None:
    validator = RoleLicenseValidator("rekipe:licensed")

    assert validator.validate({"realm_access": {"roles": ["rekipe:licensed"]}}) is True


def test_role_license_validator_rejects_missing_realm_role() -> None:
    validator = RoleLicenseValidator("rekipe:licensed")

    assert validator.validate({"realm_access": {"roles": ["rekipe:trial"]}}) is False


def test_role_license_validator_rejects_absent_realm_access() -> None:
    validator = RoleLicenseValidator("rekipe:licensed")

    assert validator.validate({"sub": "user-1"}) is False
