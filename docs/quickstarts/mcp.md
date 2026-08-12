# Quickstart MCP

Créer un service et vérifier le serveur MCP HTTP.

## Prérequis

- Python 3.13
- `uv`

## Étapes

```bash
uvx --from arclith-cli arclith-cli init todo-mcp --dir .
cd todo-mcp
uv sync
MODE=mcp_http uv run python main.py
```

Dans un second terminal :

```bash
curl -fsS http://127.0.0.1:9000/health
curl -fsS http://127.0.0.1:9000/info
```

## Résultat

`/health` retourne `{"status":"ok"}`.

`/info` indique `mcp_http` dans `active_transports`.

Le terminal serveur affiche aussi l'URL FastMCP, par défaut `http://127.0.0.1:8001/mcp`.

## Erreur Fréquente

Si le client MCP ne se connecte pas, vérifier d'abord que le port `8001` n'est pas déjà utilisé.
Le test protocolaire complet est traité dans le [Deep Dive MCP](../deep-dives/mcp.md).

## Média

!!! note "Média à produire"
    Capture : terminal avec l'URL FastMCP et `/info`.
    Vidéo : lancement MCP puis vérification des probes.

## Suite

Lire [mcp/fastmcp](../capabilities/mcp.md).
