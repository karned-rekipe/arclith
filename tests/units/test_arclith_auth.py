from pathlib import Path

import pytest
from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials

from arclith import Arclith
from arclith.adapters.inbound.jwt.decoder import JWTDecoder


def _write_keycloak_config(config_dir: Path) -> None:
    keycloak_dir = config_dir / "adapters" / "inbound"
    keycloak_dir.mkdir(parents=True, exist_ok=True)
    (keycloak_dir / "keycloak.yaml").write_text(
        "url: https://auth.example.test\n"
        "realm: rekipe\n"
        "audience: rekipe-api\n"
        "client_id: swagger-public\n",
        encoding="utf-8",
    )


def _write_license_config(config_dir: Path, *, role: str = "rekipe:licensed") -> None:
    license_dir = config_dir / "adapters" / "inbound"
    license_dir.mkdir(parents=True, exist_ok=True)
    (license_dir / "license.yaml").write_text(f"role: {role}\n", encoding="utf-8")


def _bearer_credentials() -> HTTPAuthorizationCredentials:
    return HTTPAuthorizationCredentials(scheme="Bearer", credentials="token")


def test_auth_dependency_requires_keycloak_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    arclith = Arclith(config_dir)

    with pytest.raises(RuntimeError) as exc_info:
        arclith.auth_dependency()

    message = str(exc_info.value)
    assert "config.keycloak est requis" in message
    assert "Ajouter la section keycloak" in message


def test_fastapi_keycloak_openapi_uses_oauth2_pkce_without_http_bearer(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    _write_keycloak_config(config_dir)
    arclith = Arclith(config_dir)
    require_auth = arclith.auth_dependency()
    app = arclith.fastapi()

    @app.get("/private", dependencies=[Depends(require_auth)])
    async def private_endpoint() -> dict[str, str]:
        return {"status": "ok"}

    schema = app.openapi()
    security_schemes = schema["components"]["securitySchemes"]
    keycloak = security_schemes["keycloak"]

    assert "HTTPBearer" not in security_schemes
    assert keycloak["type"] == "oauth2"
    assert keycloak["flows"]["authorizationCode"]["authorizationUrl"] == (
        "https://auth.example.test/realms/rekipe/protocol/openid-connect/auth"
    )
    assert keycloak["flows"]["authorizationCode"]["tokenUrl"] == (
        "https://auth.example.test/realms/rekipe/protocol/openid-connect/token"
    )
    assert schema["paths"]["/private"]["get"]["security"] == [
        {"keycloak": ["openid", "profile"]}
    ]
    assert app.swagger_ui_init_oauth["clientId"] == "swagger-public"
    assert app.swagger_ui_init_oauth["usePkceWithAuthorizationCodeGrant"] is True


@pytest.mark.asyncio
async def test_auth_dependency_accepts_configured_license_role(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _write_keycloak_config(config_dir)
    _write_license_config(config_dir)
    claims = {"realm_access": {"roles": ["rekipe:licensed"]}}

    async def decode(self: JWTDecoder, token: str) -> dict:
        return claims

    monkeypatch.setattr(JWTDecoder, "decode", decode)
    require_auth = Arclith(config_dir).auth_dependency()

    assert await require_auth(_bearer_credentials()) == claims


@pytest.mark.asyncio
async def test_auth_dependency_rejects_missing_license_role_with_403(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _write_keycloak_config(config_dir)
    _write_license_config(config_dir)

    async def decode(self: JWTDecoder, token: str) -> dict:
        return {"realm_access": {"roles": ["rekipe:trial"]}}

    monkeypatch.setattr(JWTDecoder, "decode", decode)
    require_auth = Arclith(config_dir).auth_dependency()

    with pytest.raises(HTTPException) as exc_info:
        await require_auth(_bearer_credentials())

    assert exc_info.value.status_code == 403


@pytest.mark.asyncio
async def test_auth_dependency_skips_license_check_when_license_config_is_absent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config_dir = tmp_path / "config"
    _write_keycloak_config(config_dir)
    claims = {"realm_access": {"roles": []}}

    async def decode(self: JWTDecoder, token: str) -> dict:
        return claims

    monkeypatch.setattr(JWTDecoder, "decode", decode)
    require_auth = Arclith(config_dir).auth_dependency()

    assert await require_auth(_bearer_credentials()) == claims


@pytest.mark.asyncio
async def test_auth_dependency_keeps_401_for_missing_credentials(
    tmp_path: Path,
) -> None:
    config_dir = tmp_path / "config"
    _write_keycloak_config(config_dir)
    _write_license_config(config_dir)
    require_auth = Arclith(config_dir).auth_dependency()

    with pytest.raises(HTTPException) as exc_info:
        await require_auth(None)

    assert exc_info.value.status_code == 401
