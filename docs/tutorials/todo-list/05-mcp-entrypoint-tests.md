# 5.2 Brancher le MCP et tester en mémoire

Intention: attacher les tools à l'instance FastMCP et garder des tests rapides sans dépendre de
MongoDB.

## Registration

Créer `src/todo_list_service/adapters/inbound/fastmcp/register.py`:

```python
from __future__ import annotations

import fastmcp
from arclith import Arclith

from todo_list_service.adapters.inbound.fastmcp.tools import TodoMCP
from todo_list_service.infrastructure.containers.todo_container import (
    build_create_todo_use_case,
    build_list_todos_use_case,
)


def register_tools(mcp: fastmcp.FastMCP, arclith: Arclith) -> None:
    create_todo = build_create_todo_use_case(arclith)
    list_todos = build_list_todos_use_case(arclith)
    TodoMCP(create_todo, list_todos, mcp)
```

## Entrypoint API + MCP

Modifier `main.py`:

```python
"""Application entrypoint for todo-list-service."""
from __future__ import annotations

import os
import sys
from pathlib import Path

import fastmcp
from arclith import Arclith

from todo_list_service.adapters.inbound.fastapi.register import register_routers
from todo_list_service.adapters.inbound.fastmcp.register import register_tools

_DEFAULT_CONFIG = Path(__file__).parent / "config"
_CONFIG = Path(os.getenv("TODO_LIST_CONFIG_DIR", str(_DEFAULT_CONFIG)))
_VALID_MODES = {"api", "mcp_http", "all"}

MODE = os.getenv("MODE", "api")
if MODE not in _VALID_MODES:
    print(f"MODE invalide: {MODE!r}. Valeurs: {sorted(_VALID_MODES)}", file=sys.stderr)
    sys.exit(1)

arclith = Arclith(_CONFIG)

app = arclith.fastapi()
register_routers(app, arclith)


def build_mcp(config_dir: Path | str | None = None) -> fastmcp.FastMCP:
    current_arclith = arclith if config_dir is None else Arclith(Path(config_dir))
    mcp = current_arclith.fastmcp("Todo MCP")
    register_tools(mcp, current_arclith)
    current_arclith.instrument_mcp(mcp)
    return mcp


def _run_api() -> None:
    arclith.run_api("main:app")


def _run_mcp_http() -> None:
    arclith.run_mcp_http(build_mcp())


if __name__ == "__main__":
    match MODE:
        case "api":
            arclith.run_with_probes(_run_api, transports=["api"])
        case "mcp_http":
            arclith.run_with_probes(_run_mcp_http, transports=["mcp_http"])
        case "all":
            arclith.run_with_probes(_run_api, _run_mcp_http, transports=["api", "mcp_http"])
```

## Tests en mémoire

Créer `tests/conftest.py`:

```python
from collections.abc import Iterator
from pathlib import Path
import shutil

import pytest

from todo_list_service.infrastructure.containers.todo_container import clear_todo_repository_cache

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_RUNTIME_CONFIG = _PROJECT_ROOT / "config"


@pytest.fixture
def memory_config(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    shutil.copytree(_RUNTIME_CONFIG, config_dir)
    (config_dir / "adapters" / "adapters.yaml").write_text(
        "logger: console\n"
        "repository: memory\n"
        "observability:\n"
        "  enabled: []\n",
        encoding="utf-8",
    )
    return config_dir


@pytest.fixture(autouse=True)
def reset_todo_repository_cache() -> Iterator[None]:
    clear_todo_repository_cache()
    yield
    clear_todo_repository_cache()
```

Modifier `tests/test_project_bootstrap.py`:

```python
from pathlib import Path

from arclith import Arclith


def test_project_config_loads(memory_config: Path) -> None:
    app = Arclith(memory_config)

    assert app.config.app.name
    assert app.config.adapters.repository == "memory"


def test_package_imports() -> None:
    import todo_list_service

    assert todo_list_service.__name__ == "todo_list_service"
```

Créer `tests/test_todo_mcp.py`:

```python
from pathlib import Path

import pytest
from fastmcp import Client

from main import build_mcp


@pytest.mark.asyncio
async def test_mcp_create_and_list_todos(memory_config: Path) -> None:
    async with Client(build_mcp(memory_config)) as client:
        tools = await client.list_tools()
        assert {tool.name for tool in tools} >= {"create_todo_item", "list_todo_items"}

        result = await client.call_tool(
            "create_todo_item",
            {
                "title": "Tester le MCP",
                "description": "Appeler le meme use case que l'API",
                "due_date": "2026-09-01",
                "status": "todo",
            },
        )

        assert not result.is_error
        assert isinstance(result.structured_content, dict)

        listed = await client.call_tool("list_todo_items", {})
        assert not listed.is_error
        assert isinstance(listed.structured_content, dict)
        assert listed.structured_content["result"] == [result.structured_content]
```

Ces tests construisent une configuration `memory` temporaire. Le MCP crée une todo puis vérifie que
`list_todo_items` relit exactement le même payload dans le même processus.

Lancer:

```bash
uv run python -m pytest tests/test_project_bootstrap.py tests/test_todo_mcp.py
```

## Smoke HTTP MCP

```bash
MODE=mcp_http uv run python main.py
```

Le serveur écoute sur:

```text
http://127.0.0.1:8121/mcp
```

Étape suivante: [tester dans LM Studio](05-mcp-lm-studio.md).
