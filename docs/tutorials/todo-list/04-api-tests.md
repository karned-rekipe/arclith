# 4.4 Tester l'API

Le CLI génère d'abord un test pur du contrat dans
`tests/adapters/fastapi/test_create_todo_contract.py`. Il vérifie les mappings
sans démarrer de serveur ni de base.

Ajouter ensuite un smoke de composition qui verrouille le problème du double
router :

```python
from fastapi.testclient import TestClient

from main import build_api


def test_create_todo_route_is_registered_once() -> None:
    app = build_api()
    routes = [
        route
        for route in app.routes
        if getattr(route, "path", None) == "/v1/todos"
        and "POST" in getattr(route, "methods", set())
    ]

    assert len(routes) == 1
    assert "/v1/v1/todos" not in app.openapi()["paths"]

    with TestClient(app) as client:
        response = client.post("/v1/todos", json={})

    assert response.status_code == 201
    assert response.json()["version"] == 1
```

Le payload vide est volontaire pour la première itération : `Entity` fournit
déjà les champs techniques. Lorsque les champs métier sont ajoutés au
`CreateTodoCommand`, le test doit fournir ces champs et contrôler les invariants
du domaine.

Pour le test manuel :

```bash
curl -fsS -X POST \
  -H 'Content-Type: application/json' \
  -d '{}' \
  http://127.0.0.1:8120/v1/todos
```

Étape suivante : [exposer le même use case via MCP](05-mcp.md).
