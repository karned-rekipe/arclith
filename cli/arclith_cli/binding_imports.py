"""Render imports active when an application contract model is declared."""

import ast
import builtins

from arclith_cli.entity_contract_ast import module_bindings_before
from arclith_cli.import_origins import absolute_import


def request_imports(
    tree: ast.Module,
    used: set[str],
    module: str,
    *,
    before_line: int,
) -> tuple[str, ...]:
    """Copy only bindings visible to the inspected request or response model."""
    statements: list[str] = []
    bindings = module_bindings_before(tree, before_line)
    resolved = set(dir(builtins)) - bindings.keys()
    selected_nodes: dict[int, tuple[ast.stmt, set[str]]] = {}
    for name in sorted(used & bindings.keys()):
        binding = bindings[name]
        if binding is not None:
            node, _ = binding
        else:
            node = _local_binding_statement(tree, name, before_line)
            if node is None:
                continue
        selected_nodes.setdefault(id(node), (node, set()))[1].add(name)
    for node, names in sorted(
        selected_nodes.values(),
        key=lambda selected: selected[0].lineno,
    ):
        selected: tuple[str, set[str]] | None = None
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            selected = _selected_import(node, names, module)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            selected = _literal_constant(node, names)
        if selected is not None:
            statement, selected_names = selected
            statements.append(statement)
            resolved.update(selected_names)
    unresolved = used - resolved
    if unresolved:
        raise ValueError(
            "Unresolved local request dependencies require an explicit mapper: "
            + ", ".join(sorted(unresolved))
        )
    return tuple(statements)


def _selected_import(
    node: ast.Import | ast.ImportFrom,
    used: set[str],
    module: str,
) -> tuple[str, set[str]] | None:
    names = {alias.asname or alias.name.split(".")[0]: alias for alias in node.names}
    selected = sorted(used & names.keys())
    if not selected:
        return None
    aliases = [names[name] for name in selected]
    statement: ast.Import | ast.ImportFrom
    if isinstance(node, ast.ImportFrom):
        statement = ast.ImportFrom(
            module=absolute_import(node, module),
            names=aliases,
            level=0,
        )
    else:
        statement = ast.Import(names=aliases)
    return ast.unparse(statement), set(selected)


def _literal_constant(
    node: ast.Assign | ast.AnnAssign,
    used: set[str],
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


def _local_binding_statement(
    tree: ast.Module,
    name: str,
    before_line: int,
) -> ast.stmt | None:
    for statement in reversed(tree.body):
        if statement.lineno > before_line:
            continue
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name
            for target in statement.targets
        ):
            return statement
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == name
        ):
            return statement
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if statement.name == name:
                return statement
    return None
