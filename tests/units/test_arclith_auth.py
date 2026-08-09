from pathlib import Path

import pytest
from fastapi import Depends

from arclith import Arclith


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
    keycloak_dir = config_dir / "adapters" / "inbound"
    keycloak_dir.mkdir(parents=True)
    (keycloak_dir / "keycloak.yaml").write_text(
        "url: https://auth.example.test\n"
        "realm: rekipe\n"
        "audience: rekipe-api\n"
        "client_id: swagger-public\n",
        encoding="utf-8",
    )
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
