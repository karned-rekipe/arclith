# Arclith

Python 3.13 framework for building microservices with Hexagonal Architecture and Clean Architecture.

Arclith provides reusable domain models, use cases, repositories, adapters, FastAPI/FastMCP bootstrap, configuration, probes, and service wiring.

## Canonical Service Layout

Arclith applications should use a namespaced `src/<package>/...` layout. This keeps imports explicit, avoids top-level package collisions, and matches how the project is built and tested.

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

The current convention is exposed by the framework:

```python
from arclith import canonical_project_layout

layout = canonical_project_layout("my_service")
print(layout.domain)  # src/my_service/domain
```

## Project Links

- Repository: [karned-rekipe/arclith](https://github.com/karned-rekipe/arclith)
- Functional sample: [karned-rekipe/_sample](https://github.com/karned-rekipe/_sample)
- GitHub Project: [Arclith backlog](https://github.com/orgs/karned-rekipe/projects/5)
- Issues: [Arclith issues](https://github.com/karned-rekipe/arclith/issues)
- PyPI: [arclith](https://pypi.org/project/arclith/)

## Installation

```bash
pip install arclith
```

## Quickstart

Pour creer un projet concret avec la CLI, lancer API/MCP/probes, puis faire evoluer les adapters:

- [Quickstart Arclith](docs/quickstart.md)
- [Capacites standardisees](docs/capabilities.md)
- [CLI](cli/README.md)
- [Sample fonctionnel](https://github.com/karned-rekipe/_sample)

### Optional dependencies

```bash
pip install "arclith[mongodb]"
pip install "arclith[duckdb]"
pip install "arclith[mariadb]"
pip install "arclith[fastapi]"
pip install "arclith[mcp]"
pip install "arclith[langgraph]"
pip install "arclith[all]"
```

`arclith[langgraph]` installe le socle local pour tester un agent via LangGraph Studio et LangSmith.
Le chemin standard est ensuite:

```bash
arclith-cli add-adapter --capability observability --adapter langsmith
uv run langgraph dev --no-browser --allow-blocking --port 2024
```

## Development

```bash
uv sync
uv run pytest
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
