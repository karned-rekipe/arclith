# Arclith

Python 3.13 framework for building microservices with Hexagonal Architecture and Clean Architecture.

Arclith provides reusable domain models, use cases, repositories, adapters, FastAPI/FastMCP bootstrap, configuration, probes, and service wiring.

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

### Optional dependencies

```bash
pip install "arclith[mongodb]"
pip install "arclith[duckdb]"
pip install "arclith[fastapi]"
pip install "arclith[mcp]"
pip install "arclith[all]"
```

## Development

```bash
uv sync
uv run pytest
```

## License

Apache 2.0 — see [LICENSE](LICENSE).
