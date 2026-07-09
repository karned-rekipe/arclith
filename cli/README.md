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

Le projet généré utilise un dossier `config/` structuré par adapter (voir section [Configuration](#configuration)).

---

### `add-adapter` — Ajouter un adapter output

Wizard interactif à lancer **depuis la racine du projet cible**. Scaffold le code Python et le fichier de configuration pour un nouvel adapter de persistance.

```bash
cd my-recipe-service
arclith-cli add-adapter
```

**Étapes du wizard :**

1. **Type d'adapter** — `memory` · `mongodb` · `duckdb`
2. **Entité(s) cible(s)** — détectées automatiquement depuis `domain/models/` via AST ; sélection individuelle ou « toutes »
3. **Paramètres** — questions spécifiques à l'adapter :
   - `mongodb` → `db_name`, `multitenant`
   - `duckdb` → `path`
   - `memory` → aucun paramètre
4. **Activation** — met à jour `config/adapters/adapters.yaml` (`repository: <adapter>`)
5. **Récapitulatif** — liste des fichiers créés ou remplacés avant confirmation

**Fichiers générés par entité :**

```
config/adapters/output/<adapter>.yaml          # config scopée (mongodb/duckdb uniquement)
adapters/output/<adapter>/__init__.py
adapters/output/<adapter>/repository.py        # re-export
adapters/output/<adapter>/repositories/<entity>_repository.py  # sous-classe à compléter
infrastructure/containers/<entity>_container.py  # AdapterRegistry régénéré
```

> ⚠️ `infrastructure/containers/<entity>_container.py` est **régénéré intégralement** si le fichier existe déjà — un avertissement est affiché dans le récapitulatif.

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
    output/
      mongodb.yaml                # adapters.mongodb: { db_name, multitenant }
      duckdb.yaml                 # adapters.duckdb: { path, multitenant }
    input/
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
repository: duckdb   # memory | mongodb | duckdb
```
