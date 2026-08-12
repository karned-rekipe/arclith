# Capability License

Autorisation par rôle realm Keycloak.

## Objectif

`license` ajoute un contrôle d'accès simple au pipeline d'authentification.
Le cas fourni par Arclith vérifie qu'un rôle realm Keycloak est présent dans le
token avant de laisser l'appel atteindre le cas d'usage.

Cette capability sert à bloquer l'accès global à une fonctionnalité ou à un
produit. Les règles métier fines restent dans les use cases.

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

## Flux

Le contrôle licence se place après le décodage du JWT:

1. l'adapter `auth` valide la signature et les claims de base;
2. `license` lit `realm_access.roles`;
3. le rôle configuré doit être présent;
4. la requête continue vers la route ou le tool MCP.

Le même validateur peut être branché côté API et côté MCP pour garder une règle
identique quel que soit le point d'entrée.

## Règles

`401` signifie authentification absente ou invalide. `403` signifie token valide mais rôle manquant.

Le nom du rôle doit être stable et explicite. Préférer un rôle comme
`rekipe:licensed` ou `todo:agent:enabled` à un rôle vague comme `user`.

Ne pas dupliquer le nom du rôle dans les routes. Le rôle doit venir de
`config/adapters/inbound/license.yaml` pour rester modifiable par environnement.

Ne pas confondre licence et autorisation métier. Une licence peut dire
"ce compte a accès au produit"; un use case doit encore vérifier les règles
comme propriétaire de ressource, quota, statut ou périmètre tenant.

## Erreurs attendues

| Situation | Statut |
|---|---:|
| token absent | `401` |
| token invalide | `401` |
| rôle absent | `403` |
| rôle présent | accès autorisé |

## Validation

```bash
uv run pytest
```

Tester au minimum:

| Cas | Résultat attendu |
|---|---|
| rôle configuré présent | accès autorisé |
| rôle configuré absent | `403` |
| `realm_access` absent | `403` |
| config `license.yaml` absente | contrôle licence désactivé |

## Suite

Lire aussi:

- [Capability Auth](auth.md)
- [API - Auth et sécurité](../production/auth.md)
- [Capability Tenant](tenant.md)
