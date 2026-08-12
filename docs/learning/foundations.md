# Comprendre Le Modèle

Cette page pose le vocabulaire minimal avant les quickstarts.

## Idée Centrale

Arclith sépare le métier des outils.

Le métier définit les entités, les ports et les use cases. Les adapters
branchent ensuite FastAPI, MCP, LangGraph, les repositories, le cache, les
secrets, le bus ou l'observabilité.

## Chemin Standard

```text
client
  -> adapter inbound
  -> port inbound
  -> use case
  -> port outbound
  -> adapter outbound
```

Le même use case peut donc être appelé depuis une API, un serveur MCP, un worker
ou un agent.

## À Retenir

| Terme | Rôle |
|---|---|
| entité | objet métier |
| port inbound | intention exposée par l'application |
| use case | orchestration métier |
| port outbound | besoin du métier vers l'extérieur |
| adapter inbound | entrée technique comme API ou MCP |
| adapter outbound | sortie technique comme repository ou LLM |
| capability | bloc activable par la CLI |

## Validation

Lire ces deux pages:

- [C'est quoi Arclith ?](../foundations/what-is-arclith.md)
- [Le chemin hexagonal](../foundations/hexagonal-flow.md)

Pouvoir expliquer en une phrase pourquoi un handler FastAPI ne doit pas parler
directement au repository.

## Erreur Fréquente

Éviter de démarrer par le framework HTTP. Commencer par le use case force une
frontière propre et rend l'API remplaçable.

## Média

!!! note "Média à produire"
    Capture attendue : schéma du chemin client vers adapter outbound.
    Vidéo attendue : explication courte du vocabulaire sur un exemple Todo.

## Suite

Lire [Quickstarts essentiels](quickstarts.md).
