# Capability Tenant

Résolution multitenant depuis un claim JWT et Vault.

## Adapter

| Adapter | Usage |
|---|---|
| `vault` | coordonnées tenant dans HashiCorp Vault KV v2 |

## Commande

```bash
arclith-cli add-adapter \
  --capability tenant \
  --adapter vault \
  --param addr=http://vault:8200 \
  --param mount=kv \
  --param path_prefix=rekipe/tenants \
  --param tenant_claim=tenant_id \
  --yes
```

## Configuration

```yaml
# config/adapters/inbound/tenant.yaml
vault_addr: "http://vault:8200"
vault_mount: "kv"
vault_path_prefix: "rekipe/tenants"
tenant_claim: "tenant_id"
```

## Règle

Activer cette capability quand un repository fonctionne en `multitenant: true`.

## Validation

```bash
uv run pytest
```

## Suite

Lire [Multitenant](../multitenant.md).
