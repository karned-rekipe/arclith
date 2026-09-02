# Deep Dive Configuration

Cette page explique comment organiser la configuration Arclith.

## Position

La configuration décrit les adapters actifs et leurs paramètres. Elle ne doit
pas contenir de vraie valeur secrète.

```text
config/
  app.yaml
  adapters/
    inbound/
    outbound/
  command_bus.yaml
```

`Arclith("config")` charge ces fichiers, applique les mappings de secrets, puis
construit `AppConfig`.

## Fichiers Par Capability

Chaque capability possède son propre fichier quand c'est pertinent:

| Capability | Exemple |
|---|---|
| API | `config/adapters/inbound/fastapi.yaml` |
| MCP | `config/adapters/inbound/fastmcp.yaml` |
| Agent | `config/adapters/inbound/langgraph.yaml` |
| Repository | `config/adapters/outbound/mongodb.yaml` |
| Storage | `config/adapters/outbound/storage.yaml` |
| Vector store | `config/adapters/outbound/vector_store.yaml` |
| LLM | `config/adapters/outbound/lm.yaml` |
| Command Bus | `config/command_bus.yaml` |

Ce découpage garde les changements lisibles en revue de code.

## Secrets

Un fichier versionné peut déclarer qu'une valeur est fournie par l'environnement
ou par Vault, mais ne doit pas contenir la vraie valeur.

```yaml
# config/secrets.yaml
resolver: env
```

Les mappings de secret permettent de remplir des champs comme
`adapters.lm.api_key` depuis `OPENAI_API_KEY` ou `ANTHROPIC_API_KEY`.

## Environnements

Garder la même structure entre local, staging et production. Les différences
doivent porter sur les valeurs, pas sur l'architecture.

| Environnement | Exemple |
|---|---|
| local | memory, LM Studio, Redis local |
| staging | services managés ou namespace dédié |
| production | Vault, Redis HA, observabilité complète |

## Overrides

Utiliser les overrides pour adapter le runtime sans modifier le coeur du projet:

- port API;
- URL d'un service externe;
- provider de secrets;
- endpoint LLM;
- flags d'observabilité.

Les overrides ne doivent pas servir à contourner une capability manquante.

## Validation

```bash
uv run python - <<'PY'
from arclith import Arclith

app = Arclith("config")
print(app.config.app.name)
print(app.config.adapters)
PY
```

La validation doit échouer tôt si un secret requis manque ou si un adapter est
mal configuré. Toutes les sections refusent aussi les clés inconnues : une faute
de frappe comme `database_name` à la place de `db_name` provoque une erreur
Pydantic explicite au démarrage, au lieu d'être ignorée.

## Erreurs Fréquentes

| Erreur | Correction |
|---|---|
| vraie clé API dans YAML | utiliser `secrets.yaml` et `.env` |
| config différente par environnement | garder la même structure |
| fichier géant | découper par capability |
| clé YAML inconnue | corriger le nom indiqué dans l'erreur Pydantic |
| valeur par défaut dangereuse | expliciter la valeur de production |
| doc oubliée après ajout capability | documenter la capability dans la même PR |

## Pages Liées

- [Capability Secrets](../capabilities/secrets.md)
- [Capability Tenant](../capabilities/tenant.md)
- [Capability Storage](../capabilities/storage.md)
- [Capability LLM](../capabilities/llm.md)
- [Baseline production](../production/baseline.md)

## Média

!!! note "Média à produire"
    Capture : arbre `config/`.
    Vidéo : passage de `env` à `chain`.
