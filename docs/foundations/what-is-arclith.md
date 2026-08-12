# C'est Quoi Arclith ?

Arclith est un socle pour écrire des microservices Python en architecture hexagonale.

## Idée

Le métier vit dans le domaine et les use cases. Les transports et outils externes restent dans des
adapters.

```text
API / MCP / bus / agent
  -> ports inbound
  -> use cases
  -> ports outbound
  -> repository / cache / LLM / observabilité / secrets
```

## Ce Que Fournit Arclith

- entités de base ;
- ports et use cases standards ;
- configuration validée ;
- adapters FastAPI, FastMCP, repositories, cache, secrets, observabilité ;
- runtime Docker et runners API/MCP/bus/agent.

## Ce Qu'il Ne Fait Pas

Arclith ne contient pas de logique métier.

Les règles produit restent dans le projet consommateur.

## Validation

Dans un projet généré :

```bash
find src -maxdepth 3 -type d
```

Tu dois retrouver `domain`, `application`, `adapters` et `infrastructure`.

## Suite

Lire [Le chemin hexagonal](hexagonal-flow.md).
