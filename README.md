# Arclith

Framework Python 3.13 pour construire des microservices hexagonaux avec domaine, ports, use cases,
adapters, FastAPI, FastMCP, bus, canaux conversationnels, agents, configuration, observabilité et
runtime Docker.

Pour construire puis piloter un projet sans quitter le terminal, lancez
`uvx --from arclith-cli arclith-cli` sans argument : le cockpit plein écran
guide la création, inspecte le projet et démarre ses runtimes avec leurs logs.
Les commandes directes restent disponibles pour les scripts et la CI.

```bash
uvx --from arclith-cli arclith-cli init my-service --dir .
cd my-service
uv sync
uvx --from arclith-cli arclith-cli run api
curl -fsS http://127.0.0.1:9000/health
```

Documentation : [karned-rekipe.github.io/arclith](https://karned-rekipe.github.io/arclith/)

Liens utiles :
[issues](https://github.com/karned-rekipe/arclith/issues),
[releases](https://github.com/karned-rekipe/arclith/releases),
[arclith PyPI](https://pypi.org/project/arclith/),
[arclith-cli PyPI](https://pypi.org/project/arclith-cli/).

Licence Apache 2.0.
