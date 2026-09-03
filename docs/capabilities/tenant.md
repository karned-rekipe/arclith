# Capability Tenant

Résolution multitenant depuis un claim JWT et Vault.

## Objectif

`tenant` permet de convertir une identité authentifiée en coordonnées techniques
par adaptateur. Le cas standard est un token JWT qui contient un identifiant
tenant, puis une lecture Vault KV v2 qui retourne les paramètres nécessaires aux
repositories multitenant.

Cette capability ne choisit pas le tenant depuis une route ou un header libre.
Elle part d'un claim signé pour éviter qu'un appelant puisse changer de tenant
en modifiant une entrée HTTP non vérifiée.

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

Paramètres utiles:

| Paramètre | Rôle |
|---|---|
| `addr` | URL du serveur Vault |
| `mount` | mount KV v2 |
| `path_prefix` | préfixe où sont stockées les entrées tenant |
| `tenant_claim` | claim JWT utilisé comme identifiant tenant |
| `tenant_uri_ttl` | durée de cache locale de la résolution |

## Configuration

```yaml
# config/adapters/inbound/tenant.yaml
vault_addr: "http://vault:8200"
vault_mount: "kv"
vault_path_prefix: "rekipe/tenants"
tenant_claim: "tenant_id"
```

La commande complète aussi le cache applicatif:

```yaml
# config/adapters/inbound/cache.yaml
tenant_uri_ttl: 300
```

## Stockage Vault

Le resolver lit le chemin `{path_prefix}/{tenant_id}` dans le mount configuré.
Chaque entrée doit exposer les champs attendus par l'adapter concerné. Exemple
pour MongoDB:

```bash
vault kv put kv/rekipe/tenants/tenant-a \
  uri="mongodb://mongo-tenant-a:27017" \
  db_name="todo_tenant_a"
```

Exemple pour un adapter S3:

```bash
vault kv put kv/rekipe/tenants/tenant-a \
  endpoint_url="https://s3.example.test" \
  bucket_name="tenant-a-assets" \
  region="eu-west-1"
```

## Pipeline HTTP

En API FastAPI, le pipeline attendu est:

1. décoder le JWT;
2. valider la licence si `license` est configurée;
3. lire le claim `tenant_claim`;
4. résoudre tous les `TenantResolver` configurés;
5. poser le `TenantContext` dans le contexte de requête.

Les repositories multitenant lisent ensuite leurs coordonnées via le contexte
Arclith. Le coeur métier ne reçoit pas directement d'URI, de mot de passe ou de
nom de base tenant.

## Règles

Activer cette capability quand un repository fonctionne en `multitenant: true`.

Le claim tenant doit être stable, non ambigu, et émis par l'Identity Provider.
Éviter les claims descriptifs comme `email` si le tenant doit survivre aux
changements de compte ou de domaine.

Ne jamais écrire les coordonnées tenant dans les logs. Les messages d'erreur
peuvent mentionner le tenant logique, mais pas les URI ou secrets récupérés dans
Vault.

Le TTL de cache doit rester court en environnement sensible. Il réduit la charge
Vault, mais retarde la prise en compte d'une rotation de coordonnées.

## Validation

```bash
uv run pytest
```

Tester au minimum:

| Cas | Résultat attendu |
|---|---|
| repository single-tenant | aucun resolver requis |
| repository multitenant sans JWT decoder | erreur de configuration |
| token sans claim tenant | `401` |
| tenant inconnu dans Vault | erreur d'accès au tenant |
| tenant valide | repository initialisé avec les coordonnées du tenant |

Le [POC Vault du tutoriel Todo](../tutorials/todo-list/07-local-services.md#ajouter-vault-localement)
fournit un seed local reproductible et vérifie séparément `VaultSecretAdapter` et
`VaultTenantResolver`.

Le [POC Keycloak de la même annexe](../tutorials/todo-list/07-local-services.md#ajouter-keycloak-localement)
émet le claim signé `tenant_id=client-a`, aligné sur l'entrée Vault créée par ce seed.

## Suite

Lire aussi:

- [Multitenant](../multitenant.md)
- [Capability Auth](auth.md)
- [Capability Secrets](secrets.md)
- [Capability Repository](repository.md)
