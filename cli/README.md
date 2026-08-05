# arclith-cli

`arclith-cli` génère instantanément un projet Python en architecture hexagonale prêt à démarrer, en téléchargeant le template officiel `_sample` depuis GitHub et en remplaçant l'entité de démo `Ingredient` par le nom de votre choix. Tout type de projet peut être scaffoldé — service REST, agent IA, API MCP — avec les ports, le nom de projet et le backend de persistance configurés d'emblée.

## Installation

```bash
uv tool install "git+https://github.com/karned-rekipe/arclith.git#subdirectory=cli"
```

## Commandes

### `new` — Créer un projet

Scaffold un nouveau projet arclith depuis le template officiel `_sample`.

```bash
# Mode interactif — l'outil pose les questions
arclith-cli new

# Mode direct
arclith-cli new Recipe my-recipe-service
arclith-cli new RecipeStep meal-planner --port 8400
arclith-cli new MealPlan meal-plan-service --dir ~/projects --port 8500
```

| Option | Défaut | Description |
|--------|--------|-------------|
| `--port` / `-p` | `8000` | Port REST (MCP = port+1) |
| `--dir` / `-d` | `.` | Répertoire parent |
| `--ref` | `main` | Branche/tag du template |

Le projet généré utilise un layout `src/<package>/...` pour le code applicatif et un dossier `config/` structuré par adapter (voir section [Configuration](#configuration)).

---

### `add-adapter` — Ajouter un adapter output

Wizard interactif à lancer **depuis la racine du projet cible**. Scaffold le code Python et/ou les fichiers de configuration pour un nouvel adapter. Par défaut, la capacité cible est `repository`.

```bash
cd my-recipe-service
arclith-cli add-adapter
```

Mode direct, utile pour CI, scripts de migration ou commandes reproductibles :

```bash
arclith-cli add-adapter --adapter mongodb --entity Recipe --db-name my_recipe_service --yes
arclith-cli add-adapter --adapter duckdb --all-entities --path data/ --no-activate --yes
arclith-cli add-adapter --adapter mariadb --entity Recipe --param database=my_recipe_service --param user=app --yes
arclith-cli add-adapter --capability observability --adapter langsmith
arclith-cli add-adapter --capability repository --adapter memory --entity Recipe --yes
```

**Étapes du wizard :**

1. **Type d'adapter** — selon la capacité : `memory` · `mongodb` · `duckdb` · `mariadb` · `langsmith`
2. **Entité(s) cible(s)** — détectées automatiquement pour les adapters entity-scoped ; ignorées pour `observability/langsmith`
3. **Paramètres** — questions spécifiques à l'adapter :
   - `mongodb` → `db_name`, `multitenant`
   - `duckdb` → `path`
   - `mariadb` → `host`, `port`, `database`, `user`, `driver`, `table_prefix`
   - `langsmith` → `tracing`, `project`, `endpoint`, `LANGSMITH_API_KEY`
   - `memory` → aucun paramètre
4. **Activation** — met à jour `config/adapters/adapters.yaml` (`repository: <adapter>` ou `observability: langsmith`)
5. **Récapitulatif** — liste des fichiers créés ou remplacés avant confirmation

| Option | Défaut | Description |
|--------|--------|-------------|
| `--capability` | `repository` | Capacité cible du catalogue standardisé (`repository`, `observability`) |
| `--adapter` / `-a` | interactif | Adapter du catalogue : `memory`, `mongodb`, `duckdb`, `mariadb`, `langsmith` |
| `--entity` / `-e` | auto si une seule entité | Entité cible, liste séparée par virgule acceptée |
| `--all-entities` | `false` | Génère l'adapter pour toutes les entités détectées |
| `--activate/--no-activate` | `--activate` | Met à jour ou non `repository: <adapter>` |
| `--db-name` | nom du projet | Nom de base pour MongoDB |
| `--multitenant/--single-tenant` | `--single-tenant` | Mode MongoDB multitenant |
| `--path` | `data/` | Chemin DuckDB |
| `--param` | - | Paramètre adapter `key=value`, répétable pour les adapters du catalogue |
| `--yes` / `-y` | `false` | Skip la confirmation et utilise les valeurs fournies ou par défaut |

**Fichiers générés par entité :**

```
config/adapters/outbound/<adapter>.yaml          # config scopée si l'adapter en a besoin
src/<package>/adapters/outbound/<adapter>/__init__.py
src/<package>/adapters/outbound/<adapter>/repository.py        # re-export
src/<package>/adapters/outbound/<adapter>/repositories/<entity>_repository.py  # sous-classe à compléter
src/<package>/infrastructure/containers/<entity>_container.py  # RepositoryRegistry régénéré
```

> ⚠️ `src/<package>/infrastructure/containers/<entity>_container.py` est **régénéré intégralement** si le fichier existe déjà — un avertissement est affiché dans le récapitulatif.

**LangSmith / tests agent :**

```bash
arclith-cli add-adapter --capability observability --adapter langsmith
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

La CLI génère `config/adapters/outbound/langsmith.yaml`, met à jour `.env` et ajoute `.env` au
`.gitignore` si besoin. LangSmith Studio devient l'endroit standard pour tester les agents. Le
serveur LangGraph doit lire `.env` via `langgraph.json`. Une `LANGSMITH_API_KEY` déjà présente est
conservée si aucune nouvelle valeur n'est fournie.

---

### `capabilities` — Lister le catalogue standardisé

Affiche les capacités et adapters connus par la CLI.

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

Le catalogue est la source de vérité pour les adapters supportés, leurs paramètres, leur chemin de configuration et la clé d'activation.

---

### `export-config` — Générer `config.yaml` pour K8s

Fusionne le dossier `config/` en un fichier YAML unique, à lancer **depuis la racine du projet**.

```bash
arclith-cli export-config                        # → ./config.yaml
arclith-cli export-config --output dist/app.yaml # chemin personnalisé
```

Le fichier généré peut être monté directement comme **ConfigMap** Kubernetes.
Arclith le lit au même titre que le dossier `config/` :

```python
# dev
arclith = Arclith("config/")

# K8s (ConfigMap monté sur /app/config.yaml)
arclith = Arclith("config.yaml")
```

> ⚠️ `config.yaml` est un **artefact généré** — l'ajouter à `.gitignore`.
> La source de vérité reste `config/`.

---

### `update` — Mettre à jour le CLI

```bash
arclith-cli update
```

### `version` — Afficher la version

```bash
arclith-cli version
```

---

## Configuration

Les projets arclith utilisent un dossier `config/` à la place d'un `config.yaml` monolithique. Chaque fichier est **scopé** : son chemin détermine la section `AppConfig` dans laquelle son contenu est injecté.

```
config/
  app.yaml                        # app: { name, version, description }
  soft_delete.yaml                # soft_delete: { retention_days }
  secrets.yaml                    # secrets: { resolver, mappings, vault, yaml }
  adapters/
    adapters.yaml                 # adapters: { logger, repository }   ← adapter actif
    outbound/
      mongodb.yaml                # adapters.mongodb: { db_name, multitenant }
      duckdb.yaml                 # adapters.duckdb: { path, multitenant }
      mariadb.yaml                # adapters.mariadb: { host, port, database, user, ... }
      langsmith.yaml              # adapters.langsmith: { tracing, project, endpoint, ... }
    inbound/
      fastapi.yaml                # api: { host, port, reload }
      fastmcp.yaml                # mcp: { host, port }
      probe.yaml                  # probe: { host, port, enabled }
      keycloak.yaml               # keycloak: { url, realm }
      tenant.yaml                 # tenant: { vault_addr, … }
      license.yaml                # license: { role }
      cache.yaml                  # cache: { backend, redis_url, … }
```

Pour changer l'adapter actif sans passer par le wizard :

```yaml
# config/adapters/adapters.yaml
repository: duckdb   # memory | mongodb | duckdb | mariadb
observability: langsmith
```

Pour MariaDB, ne committez pas le mot de passe. Mappez `adapters.mariadb.password` ou `adapters.mariadb.url` via `config/secrets.yaml`, un resolver `env` ou Vault.
