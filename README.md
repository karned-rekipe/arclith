# Arclith

Arclith est un framework Python 3.13 pour construire des microservices en architecture
hexagonale. Il fournit un socle applicatif orienté domaine: entités, ports, use cases,
configuration, adapters, probes, FastAPI, FastMCP, LangGraph, observabilité et runtime Docker.

Le dépôt contient aussi `arclith-cli`, la CLI qui génère les fichiers projet sans court-circuiter le
cœur métier. L'objectif est de garder une trajectoire unique: domaine et use cases d'abord, puis
API, MCP, agent, bus, persistance et runtime.

## Liens Essentiels

- Documentation publiée: [GitHub Pages](https://karned-rekipe.github.io/arclith/)
- Tutoriel de formation: [Todo List walkthrough](https://karned-rekipe.github.io/arclith/tutorials/todo-list/)
- Quickstart framework: [docs/quickstart.md](docs/quickstart.md)
- Quickstart agent: [docs/agent-quickstart.md](docs/agent-quickstart.md)
- Référence des capacités CLI: [docs/capabilities.md](docs/capabilities.md)
- Runtime Docker: [docs/runtime-docker.md](docs/runtime-docker.md)
- Repository: [karned-rekipe/arclith](https://github.com/karned-rekipe/arclith)
- Sample fonctionnel: [karned-rekipe/_sample](https://github.com/karned-rekipe/_sample)
- Backlog: [GitHub Project](https://github.com/orgs/karned-rekipe/projects/5)
- Issues: [GitHub Issues](https://github.com/karned-rekipe/arclith/issues)
- Releases: [GitHub Releases](https://github.com/karned-rekipe/arclith/releases)
- Packages: [arclith](https://pypi.org/project/arclith/) et
  [arclith-cli](https://pypi.org/project/arclith-cli/) sur PyPI

## Quickstart Minimal API Et MCP

Créer un projet minimal avec la CLI publiée:

```bash
uvx --from arclith-cli arclith-cli init pantry-service --dir .
cd pantry-service
uv sync
uv run pytest
```

Lancer l'API FastAPI et les probes dans un premier terminal:

```bash
MODE=api uv run python main.py
```

Vérifier les probes depuis un second terminal:

```bash
curl -fsS http://127.0.0.1:9000/health
```

Arrêter l'API avec `Ctrl+C`, puis lancer le serveur MCP HTTP:

```bash
MODE=mcp_http uv run python main.py
```

Poser ensuite le cœur métier minimal:

```bash
uvx --from arclith-cli arclith-cli add-entity ShoppingItem
uvx --from arclith-cli arclith-cli add-usecase PlanShoppingList
uvx --from arclith-cli arclith-cli add-intent-interpreter ShoppingIntent
```

Ce quickstart vérifie le socle. Pour construire une vraie fonctionnalité API + MCP + agent pas à
pas, suivre le [parcours Todo](https://karned-rekipe.github.io/arclith/tutorials/todo-list/).

## Parcours De Formation

Le parcours recommandé pour un nouveau venu est:

1. Lire la [vue d'ensemble Pages](https://karned-rekipe.github.io/arclith/).
2. Exécuter le [Quickstart Arclith](https://karned-rekipe.github.io/arclith/quickstart/).
3. Suivre le [Tutoriel Todo](https://karned-rekipe.github.io/arclith/tutorials/todo-list/) dans
   l'ordre: entité, ports/use cases, API, MCP, agent, services locaux.
4. Lire la [référence des capacités](https://karned-rekipe.github.io/arclith/capabilities/) pour
   ajouter les adapters nécessaires via `arclith-cli`.
5. Lire les références spécialisées quand le besoin apparaît: [auth](docs/auth.md),
   [HTTP](docs/http-conventions.md), [command bus](docs/command-bus.md),
   [runtime Docker](docs/runtime-docker.md), [cache](docs/caching.md) et
   [décisions d'architecture](docs/decisions.md).

## Layout Canonique

Les applications Arclith utilisent un layout `src/<package>/...`:

```text
src/my_service/
  domain/
  application/
  adapters/
  infrastructure/
config/
tests/
main.py
```

La convention est exposée par le framework:

```python
from arclith import canonical_project_layout

layout = canonical_project_layout("my_service")
print(layout.domain)  # src/my_service/domain
```

## Dépendances Optionnelles

```bash
uv add "arclith[mongodb]"
uv add "arclith[duckdb]"
uv add "arclith[mariadb]"
uv add "arclith[rabbitmq]"
uv add "arclith[langgraph]"
uv add "arclith[opentelemetry]"
uv add "arclith[all]"
```

Chaque adapter doit être ajouté via `arclith-cli add-adapter`; voir la
[référence des capacités](docs/capabilities.md).

## Documentation, Pages Et Wiki

La documentation canonique est versionnée dans `docs/` et publiée sur
[GitHub Pages](https://karned-rekipe.github.io/arclith/). C'est la bonne source pour une référence
durable et pour le parcours de formation.

Le Wiki GitHub peut rester utile pour des notes temporaires ou des brouillons non versionnés, mais
il ne doit pas devenir la référence principale: il n'est pas relu par les mêmes PR, checks MkDocs et
validations que `docs/`.

## Développement

```bash
uv sync
make precommit
make coverage
make docs
```

## Licence

Apache 2.0 — voir [LICENSE](LICENSE).
