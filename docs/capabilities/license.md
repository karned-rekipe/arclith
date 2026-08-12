# Capability License

Autorisation par rôle realm Keycloak.

## Adapter

| Adapter | Usage |
|---|---|
| `role` | vérifie un rôle dans `realm_access.roles` |

## Commande

```bash
arclith-cli add-adapter \
  --capability license \
  --adapter role \
  --param role=rekipe:licensed \
  --yes
```

## Configuration

```yaml
# config/adapters/inbound/license.yaml
role: "rekipe:licensed"
```

## Règle

`401` signifie authentification absente ou invalide. `403` signifie token valide mais rôle manquant.

## Validation

```bash
uv run pytest
```

## Suite

Lire [auth/keycloak](auth.md).
