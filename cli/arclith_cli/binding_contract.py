"""Inspect declarative application contracts without importing project code."""

import ast
import builtins
import keyword
from dataclasses import dataclass

from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames


@dataclass(frozen=True)
class UseCaseContract:
    name: str
    module: str
    port: str
    request: str
    request_source: str
    request_imports: tuple[str, ...]
    result: str
    result_names: tuple[str, ...]
    asynchronous: bool
    query_compatible: bool

    @property
    def transport_request(self) -> str:
        return self.request.removesuffix("Command").removesuffix("Query") + "Request"


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
    return UseCaseContract(
        name=name,
        module=module,
        port=port.name,
        request=request.name,
        request_source=ast.unparse(request),
        request_imports=_request_imports(tree, _used_names(request, fields), module),
        result=ast.unparse(result),
        result_names=tuple(sorted(_loaded_names(result) - set(dir(builtins)))),
        asynchronous=isinstance(method, ast.AsyncFunctionDef),
        query_compatible=all(_query_annotation(field.annotation) for field in fields),
    )


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
        return node.id in {
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
    if isinstance(node, ast.Constant):
        return node.value is None
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
        return _query_annotation(node.left) and _query_annotation(node.right)
    if isinstance(node, ast.Subscript):
        return _query_generic(node)
    return False


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


def _absolute_import(node: ast.ImportFrom, module: str) -> str | None:
    if not node.level:
        return node.module
    prefix = module.split(".")[: -node.level]
    if not prefix:
        raise ValueError("Relative request import escapes its package")
    suffix = node.module.split(".") if node.module else []
    return ".".join((*prefix, *suffix))


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
            module=_absolute_import(node, module), names=aliases, level=0
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
