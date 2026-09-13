"""Static dependency analysis for project-owned entity fields."""

from __future__ import annotations

import ast
from collections.abc import Callable
from copy import deepcopy


def module_imports(tree: ast.Module) -> tuple[ast.Import | ast.ImportFrom, ...]:
    """Return unconditional imports and imports guarded by ``TYPE_CHECKING``."""
    imports = [
        statement
        for statement in tree.body
        if isinstance(statement, (ast.Import, ast.ImportFrom))
    ]
    type_checking_names: set[str] = set()
    typing_modules: set[str] = set()
    for statement in imports:
        if isinstance(statement, ast.ImportFrom) and statement.module in {
            "typing",
            "typing_extensions",
        }:
            type_checking_names.update(
                alias.asname or alias.name
                for alias in statement.names
                if alias.name == "TYPE_CHECKING"
            )
        elif isinstance(statement, ast.Import):
            typing_modules.update(
                alias.asname or alias.name.split(".")[0]
                for alias in statement.names
                if alias.name in {"typing", "typing_extensions"}
            )

    for candidate in tree.body:
        if not isinstance(candidate, ast.If) or not _is_type_checking_guard(
            candidate.test,
            names=type_checking_names,
            modules=typing_modules,
        ):
            continue
        imports.extend(
            child
            for child in candidate.body
            if isinstance(child, (ast.Import, ast.ImportFrom))
        )
    return tuple(imports)


def module_bindings_before(
    tree: ast.Module,
    before_line: int,
) -> dict[str, tuple[ast.Import | ast.ImportFrom, ast.alias] | None]:
    """Return the effective import or local binding before a module line."""
    bindings: dict[str, tuple[ast.Import | ast.ImportFrom, ast.alias] | None] = {}
    imports = set(module_imports(tree))
    statements: list[ast.stmt] = [
        statement for statement in tree.body if statement.lineno <= before_line
    ]
    statements.extend(
        statement
        for statement in imports
        if statement not in tree.body and statement.lineno < before_line
    )
    for statement in sorted(statements, key=lambda item: item.lineno):
        if isinstance(statement, (ast.Import, ast.ImportFrom)):
            if statement not in imports:
                continue
            for alias in statement.names:
                local = alias.asname or (
                    alias.name
                    if isinstance(statement, ast.ImportFrom)
                    else alias.name.split(".")[0]
                )
                bindings[local] = (statement, alias)
            continue
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            for target in targets:
                if isinstance(target, ast.Name):
                    bindings[target.id] = None
            continue
        if isinstance(statement, ast.TypeAlias) and isinstance(
            statement.name,
            ast.Name,
        ):
            bindings[statement.name.id] = None
            continue
        if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[statement.name] = None
    return bindings


def _is_type_checking_guard(
    expression: ast.expr,
    *,
    names: set[str],
    modules: set[str],
) -> bool:
    return (isinstance(expression, ast.Name) and expression.id in names) or (
        isinstance(expression, ast.Attribute)
        and expression.attr == "TYPE_CHECKING"
        and isinstance(expression.value, ast.Name)
        and expression.value.id in modules
    )


def field_dependencies(
    fields: tuple[ast.AnnAssign, ...],
    typing_kind: Callable[[ast.expr], str | None] | None = None,
) -> set[str]:
    """Return free Python names required to evaluate field declarations."""
    typing_kind = typing_kind or _reference_name
    collector = _FreeNameCollector()
    for field in fields:
        collector.visit(field.annotation)
        if field.value is not None:
            collector.visit(field.value)
        collector.names.update(
            _quoted_annotation_dependencies(field.annotation, typing_kind)
        )
    return collector.names


def module_declarations(tree: ast.Module) -> set[str]:
    """Return names that generated contracts can import from the entity module."""
    declared: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            declared.add(statement.name)
        elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            for target in targets:
                declared.update(_bound_names(target))
        elif isinstance(statement, ast.TypeAlias):
            declared.update(_bound_names(statement.name))
    return declared


def qualify_class_dependencies(
    model: ast.ClassDef,
    fields: tuple[ast.AnnAssign, ...],
    entity_name: str,
    typing_kind: Callable[[ast.expr], str | None] | None = None,
) -> tuple[ast.AnnAssign, ...]:
    """Qualify constants declared on the entity as ``Entity.CONSTANT``."""
    typing_kind = typing_kind or _reference_name
    business_names = {
        field.target.id for field in fields if isinstance(field.target, ast.Name)
    }
    class_names: set[str] = set()
    for statement in model.body:
        if isinstance(statement, (ast.Assign, ast.AnnAssign)):
            targets = (
                statement.targets
                if isinstance(statement, ast.Assign)
                else [statement.target]
            )
            for target in targets:
                class_names.update(_bound_names(target))
        elif isinstance(statement, ast.TypeAlias):
            class_names.update(_bound_names(statement.name))
        elif isinstance(statement, ast.ClassDef):
            class_names.add(statement.name)
    dependencies = class_names - business_names
    if not dependencies:
        return fields
    qualified: list[ast.AnnAssign] = []
    for field in fields:
        result = deepcopy(field)
        qualifier = _ClassDependencyQualifier(entity_name, dependencies)
        result.annotation = _QuotedClassDependencyQualifier(
            entity_name,
            dependencies,
            typing_kind,
        ).visit(result.annotation)
        result.annotation = qualifier.visit(result.annotation)
        if result.value is not None:
            result.value = qualifier.visit(result.value)
        qualified.append(ast.fix_missing_locations(result))
    return tuple(qualified)


def _quoted_annotation_dependencies(
    annotation: ast.expr,
    typing_kind: Callable[[ast.expr], str | None],
) -> set[str]:
    names: set[str] = set()

    def visit(node: ast.AST, *, parse_strings: bool) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if not parse_strings:
                return
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return
            visit(parsed, parse_strings=True)
            return
        if isinstance(node, ast.Name) and isinstance(node.ctx, ast.Load):
            names.add(node.id)
            return
        if isinstance(node, ast.Subscript):
            kind = typing_kind(node.value)
            visit(node.value, parse_strings=parse_strings)
            if kind == "Literal":
                return
            if kind == "Annotated":
                arguments = _subscript_arguments(node.slice)
                if arguments:
                    visit(arguments[0], parse_strings=True)
                for metadata in arguments[1:]:
                    visit(metadata, parse_strings=False)
                return
        for child in ast.iter_child_nodes(node):
            visit(child, parse_strings=parse_strings)

    visit(annotation, parse_strings=True)
    return names


def _reference_name(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None


def _subscript_arguments(node: ast.expr) -> tuple[ast.expr, ...]:
    if isinstance(node, ast.Tuple):
        return tuple(node.elts)
    return (node,)


def _bound_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Param))
    }


def _argument_names(arguments: ast.arguments) -> set[str]:
    positional = (*arguments.posonlyargs, *arguments.args, *arguments.kwonlyargs)
    names = {argument.arg for argument in positional}
    if arguments.vararg is not None:
        names.add(arguments.vararg.arg)
    if arguments.kwarg is not None:
        names.add(arguments.kwarg.arg)
    return names


class _FreeNameCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.names: set[str] = set()
        self._bound: list[set[str]] = []

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load) and not any(
            node.id in scope for scope in reversed(self._bound)
        ):
            self.names.add(node.id)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        for default in (*node.args.defaults, *node.args.kw_defaults):
            if default is not None:
                self.visit(default)
        self._bound.append(_argument_names(node.args))
        self.visit(node.body)
        self._bound.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node.generators, (node.elt,))

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node.generators, (node.key, node.value))

    def _visit_comprehension(
        self,
        generators: list[ast.comprehension],
        outputs: tuple[ast.expr, ...],
    ) -> None:
        first, *remaining = generators
        self.visit(first.iter)
        self._bound.append(_bound_names(first.target))
        for condition in first.ifs:
            self.visit(condition)
        for generator in remaining:
            self.visit(generator.iter)
            self._bound[-1].update(_bound_names(generator.target))
            for condition in generator.ifs:
                self.visit(condition)
        for output in outputs:
            self.visit(output)
        self._bound.pop()


class _ClassDependencyQualifier(ast.NodeTransformer):
    def __init__(self, entity_name: str, dependencies: set[str]) -> None:
        self._entity_name = entity_name
        self._dependencies = dependencies
        self._bound: list[set[str]] = []

    def visit_Name(self, node: ast.Name) -> ast.expr:
        if (
            isinstance(node.ctx, ast.Load)
            and node.id in self._dependencies
            and not any(node.id in scope for scope in reversed(self._bound))
        ):
            return ast.copy_location(
                ast.Attribute(
                    value=ast.Name(id=self._entity_name, ctx=ast.Load()),
                    attr=node.id,
                    ctx=ast.Load(),
                ),
                node,
            )
        return node

    def visit_Lambda(self, node: ast.Lambda) -> ast.Lambda:
        node.args.defaults = [self.visit(default) for default in node.args.defaults]
        node.args.kw_defaults = [
            self.visit(default) if default is not None else None
            for default in node.args.kw_defaults
        ]
        self._bound.append(_argument_names(node.args))
        node.body = self.visit(node.body)
        self._bound.pop()
        return node

    def visit_ListComp(self, node: ast.ListComp) -> ast.ListComp:
        self._transform_comprehension(node.generators, (node, "elt"))
        return node

    def visit_SetComp(self, node: ast.SetComp) -> ast.SetComp:
        self._transform_comprehension(node.generators, (node, "elt"))
        return node

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> ast.GeneratorExp:
        self._transform_comprehension(node.generators, (node, "elt"))
        return node

    def visit_DictComp(self, node: ast.DictComp) -> ast.DictComp:
        self._transform_comprehension(
            node.generators,
            (node, "key"),
            (node, "value"),
        )
        return node

    def _transform_comprehension(
        self,
        generators: list[ast.comprehension],
        *outputs: tuple[ast.AST, str],
    ) -> None:
        first, *remaining = generators
        first.iter = self.visit(first.iter)
        self._bound.append(_bound_names(first.target))
        first.ifs = [self.visit(condition) for condition in first.ifs]
        for generator in remaining:
            generator.iter = self.visit(generator.iter)
            self._bound[-1].update(_bound_names(generator.target))
            generator.ifs = [self.visit(condition) for condition in generator.ifs]
        for owner, attribute in outputs:
            setattr(owner, attribute, self.visit(getattr(owner, attribute)))
        self._bound.pop()


class _QuotedClassDependencyQualifier(ast.NodeTransformer):
    """Qualify class dependencies inside deferred annotation strings only."""

    def __init__(
        self,
        entity_name: str,
        dependencies: set[str],
        typing_kind: Callable[[ast.expr], str | None] = _reference_name,
    ) -> None:
        self._entity_name = entity_name
        self._dependencies = dependencies
        self._typing_kind = typing_kind

    def visit_Constant(self, node: ast.Constant) -> ast.Constant:
        if not isinstance(node.value, str):
            return node
        try:
            expression = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return node
        expression = self.visit(expression)
        expression = _ClassDependencyQualifier(
            self._entity_name,
            self._dependencies,
        ).visit(expression)
        result = deepcopy(node)
        result.value = ast.unparse(expression)
        return ast.copy_location(result, node)

    def visit_Subscript(self, node: ast.Subscript) -> ast.Subscript:
        kind = self._typing_kind(node.value)
        if kind == "Literal":
            return node
        if kind == "Annotated":
            arguments = _subscript_arguments(node.slice)
            if arguments:
                transformed = self.visit(arguments[0])
                if isinstance(node.slice, ast.Tuple):
                    node.slice.elts[0] = transformed
                    node.slice.elts[1:] = [
                        metadata
                        if isinstance(metadata, ast.Constant)
                        and isinstance(metadata.value, str)
                        else self.visit(metadata)
                        for metadata in node.slice.elts[1:]
                    ]
                else:
                    node.slice = transformed
            return node
        node.slice = self.visit(node.slice)
        return node

    def visit_Call(self, node: ast.Call) -> ast.Call:
        return node
