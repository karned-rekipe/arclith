from __future__ import annotations

from arclith_cli.capability_models import (
    AdapterSpec,
    CapabilitySpec,
    FileTemplateSpec,
    ParameterSpec,
)

AUTH_CAPABILITY = CapabilitySpec(
    name="auth",
    layer="inbound",
    description="Authentification JWT Keycloak mutualisée FastAPI et FastMCP.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="keycloak",
            capability="auth",
            layer="inbound",
            description="JWT RS256 via JWKS Keycloak et Swagger UI OAuth2 PKCE.",
            config_path="config/adapters/inbound/keycloak.yaml",
            config_template="""\
url: "{url}"
realm: "{realm}"
audience: {audience}
client_id: {client_id}
""",
            parameters=(
                ParameterSpec(
                    name="url",
                    kind="string",
                    prompt="URL Keycloak",
                    default="http://localhost:8080",
                ),
                ParameterSpec(
                    name="realm",
                    kind="string",
                    prompt="Realm Keycloak",
                    default="rekipe",
                ),
                ParameterSpec(
                    name="audience",
                    kind="string",
                    prompt="Audience JWT attendue",
                    default="null",
                ),
                ParameterSpec(
                    name="client_id",
                    kind="string",
                    prompt="Client public Swagger UI PKCE",
                    default="null",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

TENANT_CAPABILITY = CapabilitySpec(
    name="tenant",
    layer="inbound",
    description="Résolution tenant multitenant depuis un claim JWT.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="vault",
            capability="tenant",
            layer="inbound",
            description="Tenant resolver Vault KV v2 pour coordonnées par adapter.",
            config_path="config/adapters/inbound/tenant.yaml",
            config_template="""\
vault_addr: "{addr}"
vault_mount: "{mount}"
vault_path_prefix: "{path_prefix}"
tenant_claim: "{tenant_claim}"
""",
            merge_config_templates=(
                FileTemplateSpec(
                    path="config/adapters/inbound/cache.yaml",
                    template="""\
tenant_uri_ttl: {tenant_uri_ttl}
""",
                ),
            ),
            parameters=(
                ParameterSpec(
                    name="addr",
                    kind="string",
                    prompt="Adresse Vault",
                    default="http://127.0.0.1:8200",
                ),
                ParameterSpec(
                    name="mount",
                    kind="string",
                    prompt="Mount KV v2",
                    default="kv",
                ),
                ParameterSpec(
                    name="path_prefix",
                    kind="string",
                    prompt="Préfixe Vault des tenants",
                    default="rekipe/tenants",
                ),
                ParameterSpec(
                    name="tenant_claim",
                    kind="string",
                    prompt="Claim JWT tenant",
                    default="sub",
                ),
                ParameterSpec(
                    name="tenant_uri_ttl",
                    kind="string",
                    prompt="TTL cache tenant en secondes",
                    default="300",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)

LICENSE_CAPABILITY = CapabilitySpec(
    name="license",
    layer="inbound",
    description="Validation d'accès par rôle realm Keycloak.",
    activation_config_key=None,
    adapters=(
        AdapterSpec(
            name="role",
            capability="license",
            layer="inbound",
            description="Vérifie un rôle dans realm_access.roles via RoleLicenseValidator.",
            config_path="config/adapters/inbound/license.yaml",
            config_template="""\
role: "{role}"
""",
            parameters=(
                ParameterSpec(
                    name="role",
                    kind="string",
                    prompt="Rôle realm Keycloak requis",
                    default="rekipe:licensed",
                ),
            ),
            entity_scoped=False,
        ),
    ),
)
