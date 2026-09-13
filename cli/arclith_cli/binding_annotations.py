"""Resolve annotation spellings accepted by automatic transport bindings."""

import ast
from collections.abc import Iterable
from dataclasses import dataclass

_BUILTIN_SCALAR_ANNOTATIONS = frozenset(
    {
        "str",
        "int",
        "float",
        "bool",
        "bytes",
    }
)


@dataclass(frozen=True)
class BindingAnnotationReferences:
    """Imported names needed to inspect Pydantic and scalar annotations."""

    scalar_names: frozenset[str]
    pydantic_base_names: frozenset[str]
    pydantic_modules: frozenset[str]

    @classmethod
    def from_tree(
        cls,
        tree: ast.Module,
        *,
        pydantic_base_names: Iterable[str] = (),
        pydantic_modules: Iterable[str] = (),
        before_line: int | None = None,
    ) -> "BindingAnnotationReferences":
        scalar_names = set(_BUILTIN_SCALAR_ANNOTATIONS)
        resolved_base_names = set(pydantic_base_names)
        resolved_pydantic_modules = set(pydantic_modules)
        scalar_modules = {
            "uuid": {"UUID"},
            "datetime": {"date", "datetime", "time", "timedelta"},
            "decimal": {"Decimal"},
        }
        for statement in tree.body:
            if before_line is not None and statement.lineno > before_line:
                continue
            if isinstance(statement, ast.ImportFrom):
                exported = scalar_modules.get(statement.module or "", set())
                for alias in statement.names:
                    local = alias.asname or alias.name
                    scalar_names.discard(local)
                    if alias.name in exported:
                        scalar_names.add(local)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                value = statement.value
                scalar_alias = (
                    isinstance(value, ast.Name) and value.id in scalar_names
                    if value is not None
                    else False
                )
                for target in targets:
                    if isinstance(target, ast.Name):
                        scalar_names.discard(target.id)
                        if scalar_alias:
                            scalar_names.add(target.id)
            elif isinstance(statement, ast.TypeAlias) and isinstance(
                statement.name, ast.Name
            ):
                scalar_names.discard(statement.name.id)
                if (
                    isinstance(statement.value, ast.Name)
                    and statement.value.id in scalar_names
                ):
                    scalar_names.add(statement.name.id)
            elif isinstance(
                statement,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef),
            ):
                scalar_names.discard(statement.name)
        return cls(
            scalar_names=frozenset(scalar_names),
            pydantic_base_names=frozenset(resolved_base_names),
            pydantic_modules=frozenset(resolved_pydantic_modules),
        )

    def is_pydantic_base_model(self, base: ast.expr) -> bool:
        """Return whether ``base`` resolves to Pydantic's BaseModel."""
        if isinstance(base, ast.Name):
            return base.id in self.pydantic_base_names
        return (
            isinstance(base, ast.Attribute)
            and base.attr == "BaseModel"
            and _root_name(base.value) in self.pydantic_modules
        )

    def query_compatible(self, node: ast.expr) -> bool:
        """Return whether FastAPI can decode the annotation from a query."""
        node = _annotation(node)
        if isinstance(node, ast.Name):
            return node.id in self.scalar_names
        if isinstance(node, ast.Constant):
            return node.value is None
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self.query_compatible(node.left) and self.query_compatible(
                node.right
            )
        if isinstance(node, ast.Subscript):
            return self._query_generic(node)
        return False

    def path_compatible(self, node: ast.expr) -> bool:
        """Return whether FastAPI can decode the annotation from one path segment."""
        node = _annotation(node)
        if isinstance(node, ast.Name):
            return node.id in self.scalar_names
        if isinstance(node, ast.Constant):
            return False
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.BitOr):
            return self._path_union((node.left, node.right))
        if not isinstance(node, ast.Subscript):
            return False
        name = node.value.id if isinstance(node.value, ast.Name) else ""
        args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if name == "Annotated":
            return self.path_compatible(args[0])
        if name == "Literal":
            return all(
                isinstance(value, ast.Constant)
                and isinstance(value.value, (str, int, float, bool))
                for value in args
            )
        if name in {"Optional", "Union"}:
            return self._path_union(tuple(args))
        return False

    def _path_union(self, nodes: tuple[ast.expr, ...]) -> bool:
        members = [
            node
            for node in nodes
            if not (
                isinstance(normalized := _annotation(node), ast.Constant)
                and normalized.value is None
            )
        ]
        return bool(members) and all(self.path_compatible(node) for node in members)

    def _query_generic(self, node: ast.Subscript) -> bool:
        name = node.value.id if isinstance(node.value, ast.Name) else ""
        args = node.slice.elts if isinstance(node.slice, ast.Tuple) else [node.slice]
        if name == "Annotated":
            return self.query_compatible(args[0])
        if name == "Literal":
            return all(
                isinstance(value, ast.Constant)
                and isinstance(value.value, (str, int, float, bool))
                for value in args
            )
        if name in {
            "list",
            "set",
            "frozenset",
            "List",
            "Set",
            "Optional",
            "Union",
        }:
            return all(self.query_compatible(value) for value in args)
        return False


def _annotation(node: ast.expr) -> ast.expr:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return ast.parse(node.value, mode="eval").body
    return node


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None
