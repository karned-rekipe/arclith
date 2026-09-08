"""Exercise generated bindings as applications, not merely file snapshots."""

import importlib
import os
import json
import sys
import threading
import subprocess

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from typer.testing import CliRunner

from arclith.application.command_bus import CommandDispatcher, CommandEnvelope
from arclith_cli.add_adapter import add_adapter_cmd
from arclith_cli.init_project import init_project_cmd
from arclith_cli.main import app
from arclith_cli.recipe import load_recipe, replay_recipe
from arclith_cli.usecase_binding import apply_binding, plan_binding

PORT_SOURCE = """from abc import ABC, abstractmethod
from pydantic import BaseModel, Field

class CreateTodoCommand(BaseModel):
    title: str = Field(min_length=1)

class CreateTodoResult(BaseModel):
    title: str

class CreateTodoPort(ABC):
    @abstractmethod
    async def execute(self, command: CreateTodoCommand) -> CreateTodoResult:
        raise NotImplementedError
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = init_project_cmd(project_name="binding-app", directory=tmp_path)
    package = root / "src/binding_app"
    (package / "domain/ports/inbound/create_todo.py").write_text(
        PORT_SOURCE, encoding="utf-8"
    )
    monkeypatch.syspath_prepend(str(root / "src"))
    monkeypatch.chdir(root)
    yield root
    for name in tuple(sys.modules):
        if name == "binding_app" or name.startswith("binding_app."):
            sys.modules.pop(name)


def _bind(root, via, **kwargs):
    if via in {"langgraph", "rabbitmq"}:
        add_adapter_cmd(
            project_dir=root,
            capability_name="agent" if via == "langgraph" else "command-bus",
            adapter=via,
            yes=True,
        )
    plan = plan_binding(root, "create-todo", via=via, feature="todos", **kwargs)
    apply_binding(plan)
    layer = "bidirectional" if via == "rabbitmq" else "inbound"
    return importlib.import_module(
        f"binding_app.adapters.{layer}.{via}.bindings_generated"
    )


def _usecase():
    contracts = importlib.import_module("binding_app.domain.ports.inbound.create_todo")

    class Recorder(contracts.CreateTodoPort):
        def __init__(self):
            self.commands = []

        async def execute(self, command):
            self.commands.append(command)
            return contracts.CreateTodoResult(title=command.title)

    return Recorder()


@pytest.mark.asyncio
async def test_http_mcp_and_broker_share_one_typed_use_case(project):
    http = _bind(project, "fastapi", http_path="/v1/todos", status_code=201)
    mcp = _bind(project, "fastmcp")
    broker = _bind(project, "rabbitmq", command_type="todo.create.v1")
    use_case = _usecase()
    api = FastAPI()
    http.register(api, create_todo=use_case)
    with TestClient(api) as client:
        response = client.post("/v1/todos", json={"title": "Same intent"})
        assert response.status_code == 201
        assert response.json() == {"title": "Same intent"}
        assert client.post("/v1/todos", json={"title": ""}).status_code == 422
    server = FastMCP("binding test")
    mcp.register(server, create_todo=use_case)
    async with Client(server) as client:
        result = await client.call_tool(
            "create_todo", {"payload": {"title": "Same intent"}}
        )
        assert result.structured_content == {"title": "Same intent"}
    dispatcher = CommandDispatcher()
    broker.register(dispatcher, create_todo=use_case)
    await dispatcher.dispatch(
        CommandEnvelope("todo.create.v1", {"title": "Same intent"})
    )
    assert len(use_case.commands) == 3
    assert use_case.commands[0] == use_case.commands[1] == use_case.commands[2]


@pytest.mark.asyncio
async def test_langgraph_binding_runs_and_resumes_with_explicit_state(project):
    from langgraph.checkpoint.memory import InMemorySaver
    from langgraph.graph import END, START, StateGraph

    register = _bind(project, "langgraph")
    node = importlib.import_module(
        "binding_app.adapters.inbound.langgraph.nodes.create_todo"
    )
    use_case = _usecase()
    builder = StateGraph(node.BindingState)
    register.register(builder, create_todo=use_case)
    builder.add_edge(START, "create_todo")
    builder.add_edge("create_todo", END)
    graph = builder.compile(
        checkpointer=InMemorySaver(), interrupt_before=["create_todo"]
    )
    config = {"configurable": {"thread_id": "binding-resume"}}
    await graph.ainvoke({"create_todo_request": {"title": "Resume"}}, config)
    assert use_case.commands == []
    result = await graph.ainvoke(None, config)
    assert result["create_todo_result"].title == "Resume"
    assert len(use_case.commands) == 1


def test_dry_run_and_repeat_preserve_developer_files_and_recipe(project):
    runner = CliRunner()
    command = [
        "expose-usecase",
        "create-todo",
        "--via",
        "fastapi",
        "--feature",
        "todos",
    ]
    before = sorted(
        path.relative_to(project) for path in project.rglob("*") if path.is_file()
    )
    result = runner.invoke(app, [*command, "--dry-run"])
    assert result.exit_code == 0, result.output
    assert before == sorted(
        path.relative_to(project) for path in project.rglob("*") if path.is_file()
    )
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    contract = (
        project / "src/binding_app/adapters/inbound/fastapi/contracts/create_todo.py"
    )
    contract.write_text(
        contract.read_text() + "\n# developer customization\n", encoding="utf-8"
    )
    recipe_path = project / "arclith.recipe.yaml"
    recipe_before = recipe_path.read_text()
    result = runner.invoke(app, command)
    assert result.exit_code == 0, result.output
    assert contract.read_text().endswith("# developer customization\n")
    assert recipe_before == recipe_path.read_text()
    recipe = load_recipe(recipe_path)
    assert recipe.steps[-1].command == "expose-usecase"
    assert replay_recipe(recipe, recipe.steps, target_dir=project, strict=True)


def test_second_binding_keeps_first_registration(project):
    first = plan_binding(project, "create-todo", via="fastapi", feature="todos")
    apply_binding(first)
    port = project / "src/binding_app/domain/ports/inbound/list_todos.py"
    port.write_text(
        PORT_SOURCE.replace("CreateTodo", "ListTodos").replace("Command", "Query"),
        encoding="utf-8",
    )
    second = plan_binding(project, "list-todos", via="fastapi", feature="todos")
    assert second.options.method == "GET"
    apply_binding(second)
    registry = (
        project / "src/binding_app/adapters/inbound/fastapi/bindings_generated.py"
    )
    assert "register_create_todo(target, create_todo)" in registry.read_text()
    assert "register_list_todos(target, list_todos)" in registry.read_text()
    manifest = json.loads((project / ".arclith/bindings/fastapi.json").read_text())
    assert len(manifest["bindings"]) == 2


@pytest.mark.parametrize(
    "options",
    [
        {"feature": "../escape"},
        {"public_name": 'x""";evil'},
        {"http_path": "/todos/{uuid}"},
        {"status_code": 204},
        {"method": "TRACE"},
    ],
)
def test_invalid_options_are_rejected_before_writes(project, options):
    before = sorted(project.rglob("*"))
    with pytest.raises(ValueError):
        plan_binding(project, "create-todo", via="fastapi", **options)
    assert sorted(project.rglob("*")) == before


def test_public_route_collision_is_rejected(project):
    apply_binding(
        plan_binding(project, "create-todo", via="fastapi", http_path="/v1/todos")
    )
    path = project / "src/binding_app/domain/ports/inbound/other.py"
    path.write_text(PORT_SOURCE.replace("CreateTodo", "Other"), encoding="utf-8")
    with pytest.raises(ValueError, match="method and path"):
        plan_binding(project, "other", via="fastapi", http_path="/v1/todos")


def test_real_get_query_maps_lists_and_validation(project):
    path = project / "src/binding_app/domain/ports/inbound/list_todos.py"
    path.write_text(
        PORT_SOURCE.replace("CreateTodo", "ListTodos")
        .replace("Command", "Query")
        .replace(
            "title: str = Field(min_length=1)",
            "title: str = Field(min_length=1)\n    tags: list[str] = []",
        ),
        encoding="utf-8",
    )
    apply_binding(
        plan_binding(project, "list-todos", via="fastapi", http_path="/v1/todos")
    )
    module = importlib.import_module("binding_app.domain.ports.inbound.list_todos")
    recorded = []

    class QueryUseCase(module.ListTodosPort):
        async def execute(self, query):
            recorded.append(query)
            return module.ListTodosResult(title=query.title)

    registry = importlib.import_module(
        "binding_app.adapters.inbound.fastapi.bindings_generated"
    )
    api = FastAPI()
    registry.register(api, list_todos=QueryUseCase())
    with TestClient(api) as client:
        assert client.get("/v1/todos?title=read&tags=a&tags=b").json() == {
            "title": "read"
        }
        assert client.get("/v1/todos?title=").status_code == 422
    assert recorded[0].tags == ["a", "b"]


def test_pydantic_aliases_and_literal_constants_are_preserved(project):
    source = PORT_SOURCE.replace(
        "class CreateTodoCommand(BaseModel):",
        "MIN_TITLE = 3\n\nclass CreateTodoCommand (BaseModel):",
    ).replace(
        "Field(min_length=1)",
        'Field(min_length=MIN_TITLE, alias="displayTitle", serialization_alias="publicTitle")',
    )
    (project / "src/binding_app/domain/ports/inbound/create_todo.py").write_text(
        source, encoding="utf-8"
    )
    registry = _bind(project, "fastapi", http_path="/v1/todos")
    use_case = _usecase()
    api = FastAPI()
    registry.register(api, create_todo=use_case)
    with TestClient(api) as client:
        assert client.post("/v1/todos", json={"displayTitle": "Aliased"}).json() == {
            "title": "Aliased"
        }
        assert client.post("/v1/todos", json={"displayTitle": "no"}).status_code == 422
    assert use_case.commands[0].title == "Aliased"


def test_forward_annotations_and_relative_imports_are_resolved(project):
    directory = project / "src/binding_app/domain/ports/inbound"
    (directory / "limits.py").write_text(
        "from pydantic import Field\n", encoding="utf-8"
    )
    source = (
        PORT_SOURCE.replace(
            "from pydantic import BaseModel, Field",
            "from pydantic import BaseModel\nfrom .limits import Field",
        )
        .replace("command: CreateTodoCommand", 'command: "CreateTodoCommand"')
        .replace("-> CreateTodoResult", '-> "CreateTodoResult"')
    )
    (directory / "create_todo.py").write_text(source, encoding="utf-8")
    _bind(project, "fastapi")
    contract = importlib.import_module(
        "binding_app.adapters.inbound.fastapi.contracts.create_todo"
    )
    assert (
        contract.to_application(contract.CreateTodoRequest(title="Imported")).title
        == "Imported"
    )


@pytest.mark.asyncio
async def test_sync_use_case_is_offloaded_by_broker_binding(project):
    path = project / "src/binding_app/domain/ports/inbound/create_todo.py"
    path.write_text(
        PORT_SOURCE.replace("async def execute", "def execute"), encoding="utf-8"
    )
    broker = _bind(project, "rabbitmq")
    contracts = importlib.import_module("binding_app.domain.ports.inbound.create_todo")
    threads = []

    class SyncUseCase(contracts.CreateTodoPort):
        def execute(self, command):
            threads.append(threading.get_ident())
            return contracts.CreateTodoResult(title=command.title)

    dispatcher = CommandDispatcher()
    broker.register(dispatcher, create_todo=SyncUseCase())
    await dispatcher.dispatch(
        CommandEnvelope("todos.create_todo.v1", {"title": "Thread"})
    )
    assert threads and threads[0] != threading.get_ident()
    http = _bind(project, "fastapi", http_path="/v1/sync")
    api = FastAPI()
    http.register(api, create_todo=SyncUseCase())
    with TestClient(api) as client:
        assert client.post("/v1/sync", json={"title": "HTTP thread"}).status_code == 200
    mcp = _bind(project, "fastmcp")
    server = FastMCP("sync tools")
    mcp.register(server, create_todo=SyncUseCase())
    async with Client(server) as client:
        await client.call_tool("create_todo", {"payload": {"title": "MCP thread"}})
    assert len(threads) == 3
    assert all(thread != threading.get_ident() for thread in threads)


@pytest.mark.parametrize(
    "change, message",
    [
        (
            lambda source: source.replace(
                "command: CreateTodoCommand",
                "command: CreateTodoCommand, *, tenant: str",
            ),
            "execute",
        ),
        (
            lambda source: source.replace(
                "title: str = Field(min_length=1)",
                "title: str\n    def normalize(self):\n        return self.title.strip()",
            ),
            "validators",
        ),
        (
            lambda source: source.replace(
                "class CreateTodoCommand(BaseModel)",
                "class CreateTodoCommand[T](BaseModel)",
            ),
            "Generic",
        ),
        (
            lambda source: source.replace(
                "Field(min_length=1)", "Field(min_length=UNKNOWN_MINIMUM)"
            ),
            "Unresolved",
        ),
    ],
)
def test_unsupported_request_shapes_fail_before_writes(project, change, message):
    (project / "src/binding_app/domain/ports/inbound/create_todo.py").write_text(
        change(PORT_SOURCE), encoding="utf-8"
    )
    before = sorted(project.rglob("*"))
    with pytest.raises(ValueError, match=message):
        plan_binding(project, "create-todo", via="fastapi")
    assert sorted(project.rglob("*")) == before


def test_nested_get_query_requires_an_explicit_mapper(project):
    path = project / "src/binding_app/domain/ports/inbound/create_todo.py"
    path.write_text(
        PORT_SOURCE.replace(
            "title: str = Field(min_length=1)", "filters: dict[str, str]"
        ),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="scalar"):
        plan_binding(project, "create-todo", via="fastapi", method="GET")


@pytest.mark.parametrize(
    "manifest",
    [
        [],
        {},
        {"version": "1", "bindings": ["invalid"]},
        {"version": "1", "bindings": [{}]},
    ],
)
def test_malformed_manifest_is_rejected_without_writes(project, manifest):
    path = project / ".arclith/bindings/fastapi.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = sorted(project.rglob("*"))
    with pytest.raises(ValueError, match="manifest"):
        plan_binding(project, "create-todo", via="fastapi")
    assert sorted(project.rglob("*")) == before


def test_binding_plan_does_not_overwrite_a_concurrent_developer_edit(project):
    plan = plan_binding(project, "create-todo", via="fastapi")
    path = project / "src/binding_app/adapters/inbound/fastapi/contracts/create_todo.py"
    path.write_text("# Concurrent developer implementation\n", encoding="utf-8")
    with pytest.raises(ValueError, match="changed after binding planning"):
        apply_binding(plan)
    assert path.read_text(encoding="utf-8") == "# Concurrent developer implementation\n"
    assert not (project / ".arclith/bindings/fastapi.json").exists()


def test_binding_manifest_symlink_cannot_escape_project(project, tmp_path):
    outside = tmp_path / "external-bindings"
    outside.mkdir()
    (project / ".arclith/bindings").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="escapes the project"):
        plan_binding(project, "create-todo", via="fastapi")
    assert list(outside.iterdir()) == []


def test_generated_python_passes_ruff_and_generated_contract_test(project):
    for via in ("fastapi", "fastmcp", "langgraph", "rabbitmq"):
        _bind(project, via)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            "E4,E7,E9,F",
            str(project / "src"),
            str(project / "tests"),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/adapters", "-q"],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
    )
    assert result.returncode == 0, result.stdout + result.stderr
