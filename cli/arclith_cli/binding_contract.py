"""Inspect declarative application contracts without importing project code."""

import ast
import builtins
import keyword
from dataclasses import dataclass
from pathlib import Path

from arclith_cli.import_origins import absolute_import, pydantic_field_references
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames

_SCALAR_ANNOTATIONS = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "bytes",
        "UUID",
        "date",
        "datetime",
        "time",
        "timedelta",
        "Decimal",
    }
)


@dataclass(frozen=True)
class UseCaseContract:
    name: str
    module: str
    port: str
    request: str
    request_source: str
    request_imports: tuple[str, ...]
    pydantic_field_names: tuple[str, ...]
    pydantic_module_names: tuple[str, ...]
    request_fields: tuple[tuple[str, str], ...]
    path_compatible_fields: tuple[str, ...]
    result: str
    result_names: tuple[str, ...]
    response_fields: tuple[str, ...]
    response_imports: tuple[str, ...]
    implementation_module: str | None
    implementation: str | None
    repository_entity_module: str | None
    repository_entity: str | None
    requires_container: bool
    asynchronous: bool
    query_compatible: bool

    @property
    def transport_request(self) -> str:
        return self.request.removesuffix("Command").removesuffix("Query") + "Request"

    @property
    def transport_response(self) -> str:
        return self.request.removesuffix("Command").removesuffix("Query") + "Response"


def public_identifier(raw: str) -> str:
    """Normalize a CLI component name, rejecting traversal and Python keywords."""
    allowed = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-"
    if not raw or any(char not in allowed for char in raw):
        raise ValueError(f"Expected a Python component name, got {raw!r}")
    name = EntityNames.from_input(raw).snake
    if not name.isidentifier() or name.startswith("_") or keyword.iskeyword(name):
        raise ValueError(f"Invalid public Python component name: {raw!r}")
    return name


def inspect_usecase(paths: ProjectPaths, raw_name: str) -> UseCaseContract:
    """Inspect exactly one port and snapshot only its declarative request shape."""
    name = public_identifier(raw_name)
    matches = sorted(paths.inbound_ports.rglob(f"{name}.py"))
    if len(matches) != 1:
        raise ValueError(
            f"Expected one inbound port named {name}.py; found {len(matches)}. "
            "Run add-usecase first or use an unambiguous name."
        )
    path = matches[0]
    source = path.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(path))
    port = _find_port(tree)
    method = _execute_method(port)
    request = _request_model(tree, method)
    relative = path.relative_to(paths.package_root).with_suffix("")
    module = paths.import_path(*relative.parts)
    result = _annotation(method.returns)
    fields = _request_fields(request)
    request_fields = tuple(
        (field.target.id, ast.unparse(_annotation(field.annotation)))
        for field in fields
        if isinstance(field.target, ast.Name)
    )
    response_fields, response_imports = _response_contract(
        paths,
        tree,
        module,
        result,
    )
    pydantic_field_names, pydantic_module_names = pydantic_field_references(
        paths, tree, module
    )
    (
        implementation_module,
        implementation,
        repository,
        requires_container,
    ) = _implementation_contract(paths, name, port.name)
    return UseCaseContract(
        name=name,
        module=module,
        port=port.name,
        request=request.name,
        request_source=ast.unparse(request),
        request_imports=_request_imports(tree, _used_names(request, fields), module),
        pydantic_field_names=pydantic_field_names,
        pydantic_module_names=pydantic_module_names,
        request_fields=request_fields,
        path_compatible_fields=tuple(
            field.target.id
            for field in fields
            if isinstance(field.target, ast.Name) and _path_annotation(field.annotation)
        ),
        result=ast.unparse(result),
        result_names=tuple(sorted(_loaded_names(result) - set(dir(builtins)))),
        response_fields=response_fields,
        response_imports=response_imports,
        implementation_module=implementation_module,
        implementation=implementation,
        repository_entity_module=repository[0] if repository is not None else None,
        repository_entity=repository[1] if repository is not None else None,
        requires_container=requires_container,
        asynchronous=isinstance(method, ast.AsyncFunctionDef),
        query_compatible=all(_query_annotation(field.annotation) for field in fields),
    )


_ENTITY_RESPONSE_FIELDS = (
    "uuid: UUID",
    "created_at: datetime",
    "created_by: str | None",
    "updated_at: datetime",
    "updated_by: str | None",
    "deleted_at: datetime | None",
    "deleted_by: str | None",
    "version: int",
    "is_deleted: bool",
)


def _response_contract(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    result: ast.expr,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if not isinstance(result, ast.Name):
        raise ValueError(
            "Automatic binding requires a direct Pydantic result model; "
            "write an explicit transport presenter for composite results"
        )
    model_tree, model, model_module = _resolve_model(
        paths,
        tree,
        module,
        result.id,
    )
    bases = {ast.unparse(base).split(".")[-1] for base in model.bases}
    if not bases & {"BaseModel", "Entity"}:
        raise ValueError("Automatic binding requires a Pydantic result model")
    fields = _request_fields(model)
    rendered = tuple(ast.unparse(field) for field in fields)
    if "Entity" in bases:
        rendered = (*_ENTITY_RESPONSE_FIELDS, *rendered)
    used: set[str] = set()
    for field in fields:
        used.update(_loaded_names(field))
    imports = _request_imports(model_tree, used, model_module)
    if "Entity" in bases:
        imports = ("from datetime import datetime", "from uuid import UUID", *imports)
    return rendered, tuple(dict.fromkeys(imports))


def _resolve_model(
    paths: ProjectPaths,
    tree: ast.Module,
    module: str,
    symbol: str,
) -> tuple[ast.Module, ast.ClassDef, str]:
    local = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == symbol
    ]
    if len(local) == 1:
        return tree, local[0], module
    imported = _imported_symbol(tree, module, symbol)
    if imported is None:
        raise ValueError(f"Cannot resolve result model {symbol!r}")
    imported_module, imported_symbol = imported
    package_name = paths.package_name
    if package_name is None:
        if not imported_module.startswith(("domain.", "application.")):
            raise ValueError("Automatic result snapshots require a project-owned model")
        relative = imported_module.replace(".", "/")
    else:
        if not imported_module.startswith(package_name + "."):
            raise ValueError("Automatic result snapshots require a project-owned model")
        relative = imported_module.removeprefix(package_name + ".").replace(".", "/")
    path = paths.package_root / f"{relative}.py"
    if not path.is_file():
        raise ValueError(f"Cannot resolve result model module {imported_module!r}")
    model_tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node
        for node in model_tree.body
        if isinstance(node, ast.ClassDef) and node.name == imported_symbol
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one result model named {imported_symbol!r}")
    return model_tree, matches[0], imported_module


def _implementation_contract(
    paths: ProjectPaths,
    name: str,
    port: str,
) -> tuple[str | None, str | None, tuple[str, str] | None, bool]:
    path = paths.application_use_cases / f"{name}.py"
    if not path.is_file():
        return None, None, None, False
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    matches = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef)
        and any(ast.unparse(base).split(".")[-1] == port for base in node.bases)
    ]
    if len(matches) != 1:
        raise ValueError(f"Expected one implementation of {port}")
    implementation = matches[0]
    module = _module_for_path(paths, path)
    constructors = [
        node
        for node in implementation.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "__init__"
    ]
    repository, requires_container = _implementation_dependency(
        tree, module, constructors
    )
    return module, implementation.name, repository, requires_container


def _implementation_dependency(
    tree: ast.Module,
    module: str,
    constructors: list[ast.FunctionDef | ast.AsyncFunctionDef],
) -> tuple[tuple[str, str] | None, bool]:
    if not constructors:
        return None, False
    if len(constructors) != 1 or isinstance(constructors[0], ast.AsyncFunctionDef):
        raise ValueError("Automatic composition requires one synchronous __init__")
    arguments = constructors[0].args
    if (
        arguments.posonlyargs
        or arguments.kwonlyargs
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or not arguments.args
        or arguments.args[0].arg != "self"
    ):
        raise ValueError(
            "Automatic composition supports only self and at most one positional "
            "Repository[Entity] or BaseService[Entity] dependency"
        )
    parameters = arguments.args[1:]
    if len(parameters) > 1:
        raise ValueError(
            "Automatic composition supports a no-argument use case or one "
            "Repository[Entity] or BaseService[Entity] dependency"
        )
    if not parameters:
        return None, False
    annotation = _annotation(parameters[0].annotation)
    if not (
        isinstance(annotation, ast.Subscript)
        and ast.unparse(annotation.value).split(".")[-1]
        in {"Repository", "BaseService"}
        and isinstance(annotation.slice, ast.Name)
    ):
        raise ValueError(
            "Automatic composition requires Repository[Entity] or a feature "
            "container for BaseService[Entity]"
        )
    dependency = ast.unparse(annotation.value).split(".")[-1]
    entity_alias = annotation.slice.id
    imported_entity = _imported_symbol(tree, module, entity_alias)
    if imported_entity is None:
        raise ValueError(f"Cannot resolve repository entity {entity_alias!r}")
    return imported_entity, dependency == "BaseService"


def _module_for_path(paths: ProjectPaths, path: Path) -> str:
    relative = path.relative_to(paths.package_root).with_suffix("")
    return paths.import_path(*relative.parts)


def _imported_symbol_module(
    tree: ast.Module,
    module: str,
    symbol: str,
) -> str | None:
    imported = _imported_symbol(tree, module, symbol)
    return imported[0] if imported is not None else None


def _imported_symbol(
    tree: ast.Module,
    module: str,
    symbol: str,
) -> tuple[str, str] | None:
    for node in tree.body:
        if not isinstance(node, ast.ImportFrom):
            continue
        for alias in node.names:
            if (alias.asname or alias.name) == symbol:
                return absolute_import(node, module), alias.name
    return None


def _find_port(tree: ast.Module) -> ast.ClassDef:
    ports = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name.endswith("Port")
    ]
    if len(ports) != 1:
        raise ValueError("The module must declare exactly one use case Port")
    return ports[0]


def _execute_method(port: ast.ClassDef) -> ast.FunctionDef | ast.AsyncFunctionDef:
    methods = [
        node
        for node in port.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "execute"
    ]
    if len(methods) != 1:
        raise ValueError("Expected one execute(self, request) method")
    method = methods[0]
    args = method.args
    unsupported = (
        len(args.args) != 2,
        bool(args.posonlyargs),
        bool(args.kwonlyargs),
        args.vararg is not None,
        args.kwarg is not None,
        method.returns is None,
    )
    if any(unsupported):
        raise ValueError("Expected execute(self, request: CommandOrQuery) -> Result")
    return method


def _request_model(
    tree: ast.Module, method: ast.FunctionDef | ast.AsyncFunctionDef
) -> ast.ClassDef:
    annotation = _annotation(method.args.args[1].annotation)
    if not isinstance(annotation, ast.Name):
        raise ValueError("The request must name a local Pydantic Command or Query")
    requests = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == annotation.id
    ]
    if len(requests) != 1 or not requests[0].name.endswith(("Command", "Query")):
        raise ValueError("Declare the Command or Query model beside the inbound port")
    request = requests[0]
    if [ast.unparse(base) for base in request.bases] != ["BaseModel"]:
        raise ValueError("Automatic binding requires a direct BaseModel request")
    _validate_declarative_request(request)
    return request


def _annotation(node: ast.expr | None) -> ast.expr:
    if node is None:
        raise ValueError("Explicit input and result annotations are required")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ast.parse(node.value, mode="eval").body
    return node


def _loaded_names(node: ast.AST) -> set[str]:
    return {
        item.id
        for item in ast.walk(node)
        if isinstance(item, ast.Name) and isinstance(item.ctx, ast.Load)
    }


def _request_fields(request: ast.ClassDef) -> list[ast.AnnAssign]:
    fields = [item for item in request.body if isinstance(item, ast.AnnAssign)]
    return [
        item
        for item in fields
        if isinstance(item.target, ast.Name)
        and not item.target.id.startswith("_")
        and item.target.id != "model_config"
    ]


def _used_names(request: ast.ClassDef, fields: list[ast.AnnAssign]) -> set[str]:
    names = _loaded_names(request)
    for field in fields:
        names.update(_loaded_names(_annotation(field.annotation)))
    return names


def _validate_declarative_request(request: ast.ClassDef) -> None:
    if request.type_params or request.decorator_list:
        raise ValueError(
            "Generic or decorated request models require an explicit mapper"
        )
    for statement in request.body:
        if isinstance(statement, (ast.AnnAssign, ast.Assign, ast.Pass)):
            continue
        if isinstance(statement, ast.Expr) and isinstance(
            statement.value, ast.Constant
        ):
            continue
        raise ValueError(
            "Request methods and validators require an explicit transport mapper; "
            "only declarative fields are snapshotted"
        )


def _query_annotation(node: ast.expr) -> bool:
    node = _annotation(node)
    if isinstance(node, ast.Name):
        return node.id in _SCALAR_ANNOTATIONS
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _query_annotation(node.left) and _query_annotation(node.right)
    if isinstance(node, ast.Subscript):
        return _query_generic(node)
    return False


def _path_annotation(node: ast.expr) -> bool:
    """Accept values FastAPI can decode from one path segment."""
    node = _annotation(node)
    if isinstance(node, ast.Name):
        return node.id in _SCALAR_ANNOTATIONS
    if isinstance(node, ast.Constant):
        return False
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _path_union((node.left, node.right))
    if not isinstance(node, ast.Subscript):
        return False
    name = node.value.id if isinstance(node.value, ast.Name) else ""
    args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if name == "Annotated":
        return _path_annotation(args[0])
    if name == "Literal":
        return all(
            isinstance(value, ast.Constant)
            and isinstance(value.value, (str, int, float, bool))
            for value in args
        )
    if name in {"Optional", "Union"}:
        return _path_union(tuple(args))
    return False


def _path_union(nodes: tuple[ast.expr, ...]) -> bool:
    members = [
        node
        for node in nodes
        if not (
            isinstance(normalized := _annotation(node), ast.Constant)
            and normalized.value is None
        )
    ]
    return bool(members) and all(_path_annotation(node) for node in members)


def _query_generic(node: ast.Subscript) -> bool:
    name = node.value.id if isinstance(node.value, ast.Name) else ""
    args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
    if name == "Annotated":
        return _query_annotation(args[0])
    if name == "Literal":
        return all(
            isinstance(value, ast.Constant)
            and isinstance(value.value, (str, int, float, bool))
            for value in args
        )
    if name in {"list", "set", "frozenset", "List", "Set", "Optional", "Union"}:
        return all(_query_annotation(value) for value in args)
    return False


def _selected_import(
    node: ast.Import | ast.ImportFrom, used: set[str], module: str
) -> tuple[str, set[str]] | None:
    names = {alias.asname or alias.name.split(".")[0]: alias for alias in node.names}
    selected = sorted(used & names.keys())
    if not selected:
        return None
    aliases = [names[name] for name in selected]
    statement: ast.Import | ast.ImportFrom
    if isinstance(node, ast.ImportFrom):
        statement = ast.ImportFrom(
            module=absolute_import(node, module), names=aliases, level=0
        )
    else:
        statement = ast.Import(names=aliases)
    return ast.unparse(statement), set(selected)


def _literal_constant(
    node: ast.Assign | ast.AnnAssign, used: set[str]
) -> tuple[str, set[str]] | None:
    targets = node.targets if isinstance(node, ast.Assign) else [node.target]
    names = {target.id for target in targets if isinstance(target, ast.Name)}
    if not names & used:
        return None
    if node.value is None:
        raise ValueError("Request constant has no value; write an explicit mapper")
    try:
        ast.literal_eval(node.value)
    except (ValueError, TypeError) as exc:
        raise ValueError(
            "Non-literal module constants need an explicit mapper"
        ) from exc
    return ast.unparse(node), names


def _request_imports(tree: ast.Module, used: set[str], module: str) -> tuple[str, ...]:
    statements: list[str] = []
    resolved = set(dir(builtins))
    for node in tree.body:
        selected = None
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            selected = _selected_import(node, used, module)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            selected = _literal_constant(node, used)
        if selected is not None:
            statement, names = selected
            statements.append(statement)
            resolved.update(names)
    unresolved = used - resolved
    if unresolved:
        raise ValueError(
            "Unresolved local request dependencies require an explicit mapper: "
            + ", ".join(sorted(unresolved))
        )
    return tuple(statements)
