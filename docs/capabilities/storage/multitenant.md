# Multitenant Storage

`multitenant: true` permet a un adapter storage de completer sa configuration
depuis le `TenantContext` courant.

## Principe

La config versionnee contient les defaults non sensibles. Le resolver tenant
fournit les coordonnees propres au tenant: bucket, container, prefixe ou
credentials cloud.

```text
auth -> tenant id -> TenantResolver -> TenantContext
                                      -> adapter storage
                                      -> cible tenant
```

Chaque adapter lit uniquement sa tranche de contexte: `s3`, `azure-blob` ou
`gcs`.

## Exemple De Contexte

```python
from arclith.adapters.context import set_tenant_context
from arclith.domain.models.tenant import AdapterTenantCoords, TenantContext

token = set_tenant_context(
    TenantContext(
        adapters={
            "s3": AdapterTenantCoords(
                params={
                    "bucket_name": "tenant-a-files",
                    "prefix": "uploads",
                    "region_name": "eu-west-3",
                }
            )
        }
    )
)
try:
    ...
finally:
    token.var.reset(token)
```

En production, le contexte est normalement pose par le pipeline d'auth ou par un
resolver tenant, pas directement dans le use case.

## Coordonnees Attendues

| Adapter | Coordonnees tenant |
|---|---|
| `s3` | `bucket_name`, `prefix`, `region_name`, `endpoint_url`, `force_path_style`, `profile_name`, `aws_access_key_id`, `aws_secret_access_key`, `aws_session_token` |
| `azure-blob` | `account_url`, `blob_service_url`, `container_name`, `container`, `prefix`, `connection_string`, `conn_str`, `account_key`, `storage_account_key`, `sas_token`, `use_default_credential`, `default_credential`, `managed_identity` |
| `gcs` | `bucket_name`, `prefix`, `project_id`, `project`, `credentials_path`, `service_account_file`, `credentials_json`, `service_account_json`, `credentials_json_b64`, `service_account_json_b64` |

Les alias existent pour faciliter l'integration avec un Vault deja structure.

## Strategies D'isolation

| Strategie | Quand l'utiliser |
|---|---|
| bucket/container par tenant | forte isolation IAM/RBAC, lifecycle et quotas par tenant |
| prefixe par tenant | mutualisation simple, a condition de policies tres bornees |
| credentials par tenant | comptes ou roles differents selon client |
| volume ou deploiement filesystem par tenant | dev ou on-prem avec isolation par runtime |

La strategie doit etre coherente avec les contraintes de suppression, audit,
facturation et restauration.

## Points D'attention

- Ne pas melanger les fichiers de plusieurs tenants dans un prefixe partage sans
  policy explicite.
- Ne pas construire la cible tenant depuis une donnee utilisateur non verifiee.
- Stocker les credentials tenant dans Vault ou un secret manager, jamais dans
  Git.
- Tester chaque tenant avec une cle de smoke isolee, par exemple
  `smoke/<tenant-id>/health.txt`.

## Suite

Lire [Securite](security.md), puis la page du provider utilise:
[S3](s3.md), [Azure Blob](azure-blob.md) ou [GCS](gcs.md).
