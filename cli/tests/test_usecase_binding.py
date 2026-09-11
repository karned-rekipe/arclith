"""Exercise generated bindings as applications, not merely file snapshots."""

import importlib
import json
import os
import subprocess
import sys
import threading
from uuid import uuid4

import pytest
from fastapi import APIRouter, FastAPI
from fastapi.testclient import TestClient
from fastmcp import Client, FastMCP
from typer.testing import CliRunner

from arclith import Arclith
from arclith.application.command_bus import CommandDispatcher, CommandEnvelope
from arclith_cli.add_adapter import add_adapter_cmd
from arclith_cli.binding_manifest import load_manifest
from arclith_cli.core_scaffold import add_entity_cmd, add_usecase_cmd
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

IMPLEMENTATION_SOURCE = """from binding_app.domain.ports.inbound.create_todo import (
    CreateTodoCommand,
    CreateTodoPort,
    CreateTodoResult,
)


class CreateTodoUseCase(CreateTodoPort):
    async def execute(self, command: CreateTodoCommand) -> CreateTodoResult:
        return CreateTodoResult(title=command.title)
"""


@pytest.fixture
def project(tmp_path, monkeypatch):
    root = init_project_cmd(project_name="binding-app", directory=tmp_path)
    package = root / "src/binding_app"
    (package / "domain/ports/inbound/create_todo.py").write_text(
        PORT_SOURCE, encoding="utf-8"
    )
    (package / "application/use_cases/create_todo.py").write_text(
        IMPLEMENTATION_SOURCE, encoding="utf-8"
    )
    for capability, adapter in (("api", "fastapi"), ("mcp", "fastmcp")):
        add_adapter_cmd(
            project_dir=root,
            capability_name=capability,
            adapter=adapter,
            yes=True,
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


def _register_api(api: FastAPI, registry, **use_cases) -> None:
    router = APIRouter(prefix="/v1")
    registry.register(router, **use_cases)
    api.include_router(router)


@pytest.mark.asyncio
async def test_http_mcp_and_broker_share_one_typed_use_case(project):
    http = _bind(project, "fastapi", http_path="/v1/todos", status_code=201)
    mcp = _bind(project, "fastmcp")
    broker = _bind(project, "rabbitmq", command_type="todo.create.v1")
    use_case = _usecase()
    api = FastAPI()
    _register_api(api, http, create_todo=use_case)
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


def test_repeat_accepts_a_legacy_manifest_without_container_metadata(project):
    first = plan_binding(project, "create-todo", via="fastapi", feature="todos")
    apply_binding(first)
    manifest_path = project / ".arclith/bindings/fastapi.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "container" not in manifest["bindings"][0]["factory"]

    repeated = plan_binding(
        project,
        "create-todo",
        via="fastapi",
        feature="todos",
    )

    assert repeated.files == {}


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
    assert "register_create_todo(todos_router, create_todo)" in registry.read_text()
    assert "register_list_todos(todos_router, list_todos)" in registry.read_text()
    manifest = json.loads((project / ".arclith/bindings/fastapi.json").read_text())
    assert len(manifest["bindings"]) == 2


@pytest.mark.parametrize(
    "options",
    [
        {"feature": "../escape"},
        {"public_name": 'x""";evil'},
        {"http_path": "/todos/{uuid}"},
        {"http_path": "/v1/todos/{uuid}"},
        {"http_path": "/v1/todos/{uuid}/{uuid}"},
        {"http_path": "/v1"},
        {"status_code": 204},
        {"method": "TRACE"},
    ],
)
def test_invalid_options_are_rejected_before_writes(project, options):
    before = sorted(project.rglob("*"))
    with pytest.raises(ValueError):
        plan_binding(project, "create-todo", via="fastapi", **options)
    assert sorted(project.rglob("*")) == before


@pytest.mark.parametrize("via", ["fastmcp", "langgraph", "rabbitmq"])
def test_path_parameters_are_rejected_outside_fastapi(project, via):
    if via in {"langgraph", "rabbitmq"}:
        add_adapter_cmd(
            project_dir=project,
            capability_name="agent" if via == "langgraph" else "command-bus",
            adapter=via,
            yes=True,
        )
    before = sorted(project.rglob("*"))

    with pytest.raises(ValueError, match="only by FastAPI"):
        plan_binding(
            project,
            "create-todo",
            via=via,
            http_path="/v1/todos/{title}",
        )

    assert sorted(project.rglob("*")) == before


@pytest.mark.parametrize(
    "field",
    ["payload", "present_result", "request", "to_application", "use_case"],
)
def test_path_parameters_cannot_shadow_generated_binding_names(project, field):
    path = project / "src/binding_app/domain/ports/inbound/create_todo.py"
    path.write_text(
        PORT_SOURCE.replace("title: str", f"{field}: str"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="generated binding names"):
        plan_binding(
            project,
            "create-todo",
            via="fastapi",
            http_path=f"/v1/todos/{{{field}}}",
        )


def test_public_route_collision_is_rejected(project):
    apply_binding(
        plan_binding(project, "create-todo", via="fastapi", http_path="/v1/todos")
    )
    path = project / "src/binding_app/domain/ports/inbound/other.py"
    path.write_text(PORT_SOURCE.replace("CreateTodo", "Other"), encoding="utf-8")
    with pytest.raises(ValueError, match="method and path"):
        plan_binding(project, "other", via="fastapi", http_path="/v1/todos")


def test_public_route_collision_normalizes_path_parameter_names(project):
    apply_binding(
        plan_binding(
            project,
            "create-todo",
            via="fastapi",
            http_path="/v1/todos/{title}",
            method="GET",
        )
    )
    path = project / "src/binding_app/domain/ports/inbound/other.py"
    path.write_text(
        PORT_SOURCE.replace("CreateTodo", "Other").replace("title", "slug"),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="method and path shape"):
        plan_binding(
            project,
            "other",
            via="fastapi",
            http_path="/v1/todos/{slug}",
            method="GET",
        )


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
    _register_api(api, registry, list_todos=QueryUseCase())
    with TestClient(api) as client:
        assert client.get("/v1/todos?title=read&tags=a&tags=b").json() == {
            "title": "read"
        }
        assert client.get("/v1/todos?title=").status_code == 422
    assert recorded[0].tags == ["a", "b"]


def test_list_fields_cannot_be_mapped_to_one_path_segment(project):
    path = project / "src/binding_app/domain/ports/inbound/create_todo.py"
    path.write_text(
        PORT_SOURCE.replace(
            "title: str = Field(min_length=1)",
            "tags: list[str] = []",
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="scalar request fields"):
        plan_binding(
            project,
            "create-todo",
            via="fastapi",
            http_path="/v1/todos/{tags}",
        )


@pytest.mark.parametrize(
    ("annotation", "typing_import"),
    [("UUID | None", ""), ("Optional[UUID]", "from typing import Optional\n")],
)
def test_nullable_scalar_path_annotations_are_supported_consistently(
    project,
    annotation,
    typing_import,
):
    source = PORT_SOURCE.replace(
        "from pydantic import BaseModel, Field",
        f"{typing_import}from uuid import UUID\nfrom pydantic import BaseModel, Field",
    ).replace(
        "title: str = Field(min_length=1)",
        f"uuid: {annotation}",
    )
    (project / "src/binding_app/domain/ports/inbound/create_todo.py").write_text(
        source,
        encoding="utf-8",
    )

    plan = plan_binding(
        project,
        "create-todo",
        via="fastapi",
        http_path="/v1/todos/{uuid}",
    )

    assert plan.options.http_path == "/v1/todos/{uuid}"


def test_aliased_path_field_uses_its_python_name_in_the_drift_guard(project):
    source = PORT_SOURCE.replace(
        "from pydantic import BaseModel, Field",
        "from uuid import UUID\nfrom pydantic import BaseModel, Field",
    ).replace(
        "title: str = Field(min_length=1)",
        'uuid: UUID = Field(alias="id")\n    title: str = Field(min_length=1)',
    )
    (project / "src/binding_app/domain/ports/inbound/create_todo.py").write_text(
        source,
        encoding="utf-8",
    )
    registry = _bind(
        project,
        "fastapi",
        http_path="/v1/todos/{uuid}",
    )
    use_case = _usecase()
    api = FastAPI()
    _register_api(api, registry, create_todo=use_case)
    identifier = uuid4()

    with TestClient(api) as client:
        response = client.post(
            f"/v1/todos/{identifier}",
            json={"title": "Aliased path"},
        )

    assert response.status_code == 200
    assert use_case.commands[0].uuid == identifier
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "tests/adapters/fastapi/test_create_todo_contract.py",
            "-q",
        ],
        capture_output=True,
        text=True,
        env={**os.environ, "PYTHONPATH": str(project / "src")},
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_path_constraints_are_reported_as_request_validation(project):
    source = PORT_SOURCE.replace(
        "title: str = Field(min_length=1)",
        "item_id: int = Field(gt=0)\n    title: str = Field(min_length=1)",
    )
    (project / "src/binding_app/domain/ports/inbound/create_todo.py").write_text(
        source,
        encoding="utf-8",
    )
    registry = _bind(
        project,
        "fastapi",
        http_path="/v1/todos/{item_id}",
    )
    use_case = _usecase()
    api = FastAPI()
    _register_api(api, registry, create_todo=use_case)

    with TestClient(api) as client:
        invalid = client.post("/v1/todos/-1", json={"title": "Invalid"})
        valid = client.post("/v1/todos/1", json={"title": "Valid"})

    assert invalid.status_code == 422
    assert valid.status_code == 200
    assert len(use_case.commands) == 1
    assert use_case.commands[0].item_id == 1


def test_path_type_aliases_preserve_the_exact_field_identifier(project):
    source = PORT_SOURCE.replace(
        "from pydantic import BaseModel, Field",
        "from uuid import UUID\nfrom pydantic import BaseModel, Field",
    ).replace(
        "title: str = Field(min_length=1)",
        "foo_bar: int\n    foo__bar: UUID",
    )
    (project / "src/binding_app/domain/ports/inbound/create_todo.py").write_text(
        source,
        encoding="utf-8",
    )

    apply_binding(
        plan_binding(
            project,
            "create-todo",
            via="fastapi",
            feature="todos",
            http_path="/v1/todos/{foo_bar}/{foo__bar}",
        )
    )

    contract_path = (
        project / "src/binding_app/adapters/inbound/fastapi/contracts/create_todo.py"
    )
    route_path = (
        project
        / "src/binding_app/adapters/inbound/fastapi/routers/v1/todos/routes/create_todo.py"
    )
    contract = contract_path.read_text(encoding="utf-8")
    route = route_path.read_text(encoding="utf-8")
    assert "type PathParam_foo_bar = int" in contract
    assert "type PathParam_foo__bar = UUID" in contract
    compile(contract, str(contract_path), "exec")
    compile(route, str(route_path), "exec")


def test_path_type_alias_avoids_imported_application_symbols(project):
    inbound = project / "src/binding_app/domain/ports/inbound"
    (inbound / "types.py").write_text(
        "type PathParam_uuid = str\n",
        encoding="utf-8",
    )
    source = PORT_SOURCE.replace(
        "from pydantic import BaseModel, Field",
        "from uuid import UUID\n"
        "from pydantic import BaseModel, Field\n"
        "from .types import PathParam_uuid",
    ).replace(
        "title: str = Field(min_length=1)",
        "uuid: UUID\n    marker: PathParam_uuid\n    title: str = Field(min_length=1)",
    )
    (inbound / "create_todo.py").write_text(source, encoding="utf-8")

    apply_binding(
        plan_binding(
            project,
            "create-todo",
            via="fastapi",
            feature="todos",
            http_path="/v1/todos/{uuid}",
        )
    )

    contract = (
        project / "src/binding_app/adapters/inbound/fastapi/contracts/create_todo.py"
    ).read_text(encoding="utf-8")
    route = (
        project
        / "src/binding_app/adapters/inbound/fastapi/routers/v1/todos/routes/create_todo.py"
    ).read_text(encoding="utf-8")
    assert (
        "from binding_app.domain.ports.inbound.types import PathParam_uuid" in contract
    )
    assert "type PathParam_uuid_2 = UUID" in contract
    assert "PathParam_uuid_2" in route


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
    _register_api(api, registry, create_todo=use_case)
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
    _register_api(api, http, create_todo=SyncUseCase())
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
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest), encoding="utf-8")
    before = sorted(project.rglob("*"))
    with pytest.raises(ValueError, match="manifest"):
        plan_binding(project, "create-todo", via="fastapi")
    assert sorted(project.rglob("*")) == before


@pytest.mark.parametrize(
    "status_code", [None, True, "201", 200.0, {}, 199, 300, 500, 204, 205]
)
@pytest.mark.parametrize("source", ["options", "manifest"])
def test_invalid_response_status_fails_closed_without_writes(
    project, status_code, source
):
    options = {}
    usecase = "create-todo"
    if source == "manifest":
        apply_binding(plan_binding(project, "create-todo", via="fastapi"))
        path = project / ".arclith/bindings/fastapi.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["bindings"][0]["options"]["status_code"] = status_code
        path.write_text(json.dumps(manifest), encoding="utf-8")
        usecase = "other"
        (project / "src/binding_app/domain/ports/inbound/other.py").write_text(
            PORT_SOURCE.replace("CreateTodo", "Other"), encoding="utf-8"
        )
    else:
        options["status_code"] = status_code
    before = {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    }
    with pytest.raises(ValueError, match="status"):
        plan_binding(project, usecase, via="fastapi", **options)
    assert {
        path.relative_to(project): path.read_bytes()
        for path in project.rglob("*")
        if path.is_file()
    } == before


@pytest.mark.parametrize(
    ("option", "value"),
    [
        ("feature", "../escape"),
        ("public_name", "123-invalid"),
        ("http_path", "/outside"),
        ("http_path", "/v1"),
        ("method", "TRACE"),
        ("command_type", "todo create v1"),
    ],
)
def test_saved_manifest_options_are_fully_revalidated_before_writes(
    project, option, value
):
    apply_binding(plan_binding(project, "create-todo", via="fastapi"))
    path = project / ".arclith/bindings/fastapi.json"
    manifest = json.loads(path.read_text(encoding="utf-8"))
    manifest["bindings"][0]["options"][option] = value
    path.write_text(json.dumps(manifest), encoding="utf-8")
    (project / "src/binding_app/domain/ports/inbound/other.py").write_text(
        PORT_SOURCE.replace("CreateTodo", "Other"), encoding="utf-8"
    )
    before = {
        file.relative_to(project): file.read_bytes()
        for file in project.rglob("*")
        if file.is_file()
    }

    with pytest.raises(ValueError, match="manifest"):
        plan_binding(project, "other", via="fastapi")

    assert {
        file.relative_to(project): file.read_bytes()
        for file in project.rglob("*")
        if file.is_file()
    } == before


def test_legacy_root_layout_manifest_accepts_application_and_domain_factories(
    tmp_path,
):
    path = tmp_path / "fastapi.json"
    entry = {
        "usecase": "create_todo",
        "port_module": "domain.ports.inbound.create_todo",
        "port": "CreateTodoPort",
        "binding_module": "adapters.inbound.fastapi.routers.v1.todos.create_todo",
        "options": {
            "via": "fastapi",
            "feature": "todos",
            "public_name": "create_todo",
            "http_path": "/v1/todos",
            "method": "POST",
            "status_code": 201,
            "command_type": "todos.create_todo.v1",
        },
        "factory": {
            "module": "application.use_cases.create_todo",
            "class": "CreateTodoUseCase",
            "repository_entity_module": "domain.models.todo",
            "repository_entity": "Todo",
        },
    }
    path.write_text(json.dumps({"version": "2", "bindings": [entry]}), encoding="utf-8")

    assert load_manifest(
        path,
        "fastapi",
        "adapters.inbound.fastapi",
        "domain.ports.inbound",
    ) == [entry]


@pytest.mark.parametrize(
    "constructor",
    [
        "def __init__(self, *, logger: str) -> None:\n        self.logger = logger",
        "def __init__(self, *dependencies: object) -> None:\n        pass",
        "def __init__(self, **dependencies: object) -> None:\n        pass",
        "def __init__(self, repository: object, /) -> None:\n        pass",
        "async def __init__(self) -> None:\n        pass",
    ],
)
def test_unsupported_use_case_constructors_fail_before_writes(project, constructor):
    source = IMPLEMENTATION_SOURCE.replace(
        "    async def execute",
        f"    {constructor}\n\n    async def execute",
    )
    (project / "src/binding_app/application/use_cases/create_todo.py").write_text(
        source, encoding="utf-8"
    )
    before = sorted(project.rglob("*"))

    with pytest.raises(ValueError, match="composition"):
        plan_binding(project, "create-todo", via="fastapi")

    assert sorted(project.rglob("*")) == before


def test_aliased_entity_import_builds_a_functional_response_snapshot(project):
    add_entity_cmd(project_dir=project, entity_name="Todo")
    usecase = add_usecase_cmd(
        project_dir=project,
        usecase_name="CreateAliasedTodo",
        entity_name="Todo",
    )
    port = project / "src/binding_app/domain/ports/inbound/create_aliased_todo.py"
    port.write_text(
        port.read_text(encoding="utf-8")
        .replace("import Todo", "import Todo as TodoModel")
        .replace("-> Todo:", "-> TodoModel:"),
        encoding="utf-8",
    )
    usecase.write_text(
        usecase.read_text(encoding="utf-8")
        .replace("import Todo", "import Todo as TodoModel")
        .replace("Repository[Todo]", "Repository[TodoModel]")
        .replace("-> Todo:", "-> TodoModel:")
        .replace("entity = Todo.model_validate", "entity = TodoModel.model_validate"),
        encoding="utf-8",
    )
    apply_binding(
        plan_binding(
            project,
            "create-aliased-todo",
            via="fastapi",
            feature="todos",
            http_path="/v1/todos",
            status_code=201,
        )
    )
    composition = importlib.import_module(
        "binding_app.infrastructure.use_cases_generated"
    )
    registry = importlib.import_module(
        "binding_app.adapters.inbound.fastapi.bindings_generated"
    )
    use_cases = composition.build_use_cases(Arclith(project / "config"))
    api = FastAPI()
    _register_api(api, registry, create_aliased_todo=use_cases.create_aliased_todo)

    with TestClient(api) as client:
        response = client.post("/v1/todos", json={})

    assert response.status_code == 201
    assert response.json()["is_deleted"] is False
    generated = (
        project / "src/binding_app/infrastructure/use_cases_generated.py"
    ).read_text(encoding="utf-8")
    assert "Todo as CreateAliasedTodoEntity" in generated
    assert "TodoModel as CreateAliasedTodoEntity" not in generated


def test_use_cases_for_one_entity_share_one_repository_and_process_graph(project):
    add_entity_cmd(project_dir=project, entity_name="Todo")
    for name in ("StoreTodo", "ArchiveTodo"):
        add_usecase_cmd(project_dir=project, usecase_name=name, entity_name="Todo")
        apply_binding(plan_binding(project, name, via="fastapi", feature="todos"))
    composition = importlib.import_module(
        "binding_app.infrastructure.use_cases_generated"
    )
    use_cases = composition.build_use_cases(Arclith(project / "config"))

    assert use_cases.store_todo._repository is use_cases.archive_todo._repository

    spec = importlib.util.spec_from_file_location(
        "binding_generated_main", project / "main.py"
    )
    assert spec is not None and spec.loader is not None
    generated_main = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(generated_main)
    assert generated_main._build_use_cases() is generated_main._build_use_cases()


def test_binding_plan_does_not_overwrite_a_concurrent_developer_edit(project):
    plan = plan_binding(project, "create-todo", via="fastapi")
    path = project / "src/binding_app/adapters/inbound/fastapi/contracts/create_todo.py"
    path.parent.mkdir(parents=True, exist_ok=True)
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
