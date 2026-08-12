# Capability MCP

Transport MCP exposé via FastMCP.

## Adapter

| Adapter | Usage |
|---|---|
| `fastmcp` | serveur MCP créé par `Arclith.fastmcp()` |

## Commande

```bash
arclith-cli add-adapter --capability mcp --adapter fastmcp --yes
```

## Configuration

```yaml
# config/adapters/inbound/fastmcp.yaml
host: 127.0.0.1
port: 8001
```

## Règle

Les tools MCP appellent les mêmes ports ou use cases que l'API.

## Validation

```bash
MODE=mcp_http uv run python main.py
curl -fsS http://127.0.0.1:9000/info
```

`active_transports` doit contenir `mcp_http`.

## Suite

Lire [Deep Dive MCP](../deep-dives/mcp.md).
