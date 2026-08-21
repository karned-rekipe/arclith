# Préparer Son Poste

Cette page vérifie que l'environnement local peut suivre les tutoriels Arclith.

## Prérequis

- Python 3.13;
- `uv`;
- `git`;
- Docker Desktop ou un moteur Docker compatible;
- accès au dépôt GitHub Arclith;
- LM Studio si le parcours agent est prévu.

## Installer La CLI

```bash
uv tool install --force arclith-cli
arclith-cli version
```

Pour travailler depuis le dépôt Arclith:

```bash
git clone https://github.com/karned-rekipe/arclith.git
cd arclith
uv sync --all-extras
```

## Vérifier Docker

```bash
docker version
docker compose version
```

Docker est requis pour MongoDB, Redis, Vault, RabbitMQ, OpenTelemetry Collector
et les tutoriels de déploiement.

## Préparer LM Studio

LM Studio est utile pour les quickstarts MCP et agent avec un modèle local.

```bash
curl -fsS http://127.0.0.1:1234/v1/models
```

Si la commande échoue, ouvrir LM Studio, charger un modèle, puis activer le
serveur local OpenAI-compatible.

Pour prouver le chemin complet LM Studio, adapter LLM et LangGraph sans LangSmith, suivre
[Validation IA locale et hors ligne](local-ai-validation.md).

## Validation

```bash
arclith-cli version
uv --version
docker version
```

Chaque commande doit répondre sans erreur.

## Erreur Fréquente

`curl: (7) Failed to connect` sur LM Studio signifie que le serveur local n'est
pas lancé ou n'écoute pas sur `127.0.0.1:1234`.

## Média

!!! note "Média à produire"
    Capture attendue : terminal avec `arclith-cli version`, `uv --version` et `docker version`.
    Vidéo attendue : installation de la CLI puis vérification Docker.

## Suite

Lire [Comprendre le modèle](foundations.md), ou [Validation IA locale et hors ligne](local-ai-validation.md)
si le parcours agent est prévu.
