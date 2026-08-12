# Lancement Local MCP

Objectif: exposer les tools MCP du projet via FastMCP `streamable-http` depuis l'image Docker.

## Configuration

FastMCP doit écouter sur `0.0.0.0` dans le conteneur:

```yaml
# config/adapters/inbound/fastmcp.yaml
host: 0.0.0.0
port: 8001
```

Créer la configuration si elle n'existe pas:

```bash
arclith-cli add-adapter \
  --capability mcp \
  --adapter fastmcp \
  --param host=0.0.0.0 \
  --param port=8001 \
  --yes
```

Reconstruire après modification:

```bash
uv lock
docker build -t my-service:local .
```

## Lancer Le Serveur MCP

```bash
docker run --rm \
  -p 8001:8001 \
  -p 9000:9000 \
  my-service:local mcp_http
```

Le endpoint FastMCP HTTP est exposé sur:

```text
http://127.0.0.1:8001/mcp
```

Les probes restent indépendantes:

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/info
```

## Smoke Client MCP

Depuis le projet local, utiliser le client FastMCP pour vérifier le protocole, pas seulement le port:

```bash
uv run python - <<'PY'
import asyncio

from fastmcp import Client


async def main() -> None:
    async with Client("http://127.0.0.1:8001/mcp") as client:
        tools = await client.list_tools()
        print([tool.name for tool in tools])


asyncio.run(main())
PY
```

Un projet minimal peut renvoyer une liste vide. Un projet métier doit exposer les tools attendus.

## Probes Sur Port Séparé

Si l'API tourne déjà sur le host avec les probes en `9000`, publier les probes MCP sur un autre port
host:

```bash
docker run --rm \
  -p 8001:8001 \
  -p 9001:9000 \
  my-service:local mcp_http

curl -fsS http://127.0.0.1:9001/health
```

Le port conteneur des probes reste `9000`; seul le port host change.

## Checklist SOTA

- FastMCP écoute sur `0.0.0.0` dans Docker.
- La validation utilise un client MCP réel.
- Les tools MCP appellent des ports/use cases, jamais des repositories concrets.
- Les headers d'auth et de tenant sont testés via le transport HTTP si l'auth est activée.
- Les probes restent exposées séparément pour diagnostiquer le runtime MCP.

Page suivante: [lancer l'agent localement](local-agent.md).
