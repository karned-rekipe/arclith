# Catalogue Des Capabilities

Une capability est une brique activable par `arclith-cli add-adapter`.

## Règle

Chaque capability du catalogue CLI doit avoir sa page dédiée dans cette section.

```bash
arclith-cli capabilities
arclith-cli capabilities --json
```

## Inbound

- [api](capabilities/api.md)
- [mcp](capabilities/mcp.md)
- [auth](capabilities/auth.md)
- [tenant](capabilities/tenant.md)
- [license](capabilities/license.md)
- [probe](capabilities/probe.md)
- [http](capabilities/http.md)
- [agent](capabilities/agent.md)

## Outbound

- [repository](capabilities/repository.md)
- [cache](capabilities/cache.md)
- [logger](capabilities/logger.md)
- [secrets](capabilities/secrets.md)
- [llm](capabilities/llm.md)
- [observability](capabilities/observability.md)

## Bidirectionnel Et Runtime

- [command-bus](capabilities/command-bus.md)
- [runtime](capabilities/runtime.md)

## Ajouter Une Capability

Une PR qui ajoute ou modifie une capability doit mettre à jour :

1. le catalogue CLI ;
2. la page dédiée ;
3. cet index ;
4. le quickstart si le flux est fréquent ;
5. la baseline production si la capability appartient au socle de production.
