# arclith — Copilot Instructions

Lib PyPI `arclith` v0.2.1 : framework hexagonal réutilisable (domain/ports/adapters/infra). Lire `AGENTS.md` local.

## Règles spécifiques à ce repo

- Ce repo est une **lib publiée sur PyPI** — tout import applicatif (recette, ingrédient…) est interdit dans `arclith/`.
- `domain/` doit rester pur : zéro import externe hormis `pydantic` et `uuid6`.
- Tout ajout d'adaptateur doit être référencé dans `build_repository()` (`infrastructure/repository_factory.py`).
- Couverture de tests : **≥ 90 %** — vérifier avec `make coverage`.
- Optional-deps groupés : `mongodb`, `duckdb`, `mariadb`, `fastapi`, `mcp`, `all` — ne pas ajouter de dépendances au groupe de base.
- **HTTP Status Codes** : toujours déclarer explicitement `status_code` et `responses` dans FastAPI. Voir `docs/http-conventions.md`.
