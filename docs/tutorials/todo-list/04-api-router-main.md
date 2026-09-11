# 4.3 Router et composition

Les routers ne sont pas créés à la main. `add-adapter` installe le router de
version et `expose-usecase` ajoute le router de feature et son opération.

Les responsabilités sont séparées ainsi :

| Fichier | Responsabilité |
|---|---|
| `main.py` | construire le processus et sélectionner `MODE=api` |
| `infrastructure/use_cases_generated.py` | construire les use cases et leurs ports outbound |
| `fastapi/register.py` | inclure une fois le router FastAPI racine |
| `routers/v1/router.py` | posséder le préfixe `/v1` |
| `routers/v1/todos/router.py` | agréger les opérations de la feature |
| `bindings_generated.py` | injecter les ports dans chaque feature |

Le chemin public `/v1/todos` est donc composé une seule fois. Le manifeste
`.arclith/bindings/fastapi.json` conserve le chemin public complet, tandis que
le fichier d'opération reçoit le chemin local `/todos` sous le router `/v1`.

Lancer l'API :

```bash
uv sync
MODE=api uv run python main.py
```

Si FastAPI n'a pas été ajouté, `MODE=api` échoue avec la liste des modes
effectivement installés au lieu d'importer une dépendance absente.

Étape suivante : [tester l'API](04-api-tests.md).
