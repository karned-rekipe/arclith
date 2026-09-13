"""Static dependency analysis for project-owned entity fields."""

from __future__ import annotations

import ast
from copy import deepcopy


def field_dependencies(fields: tuple[ast.AnnAssign, ...]) -> set[str]:
    """Return free Python names required to evaluate field declarations."""
    collector = _FreeNameCollector()
    for field in fields:
        collector.visit(field.annotation)
        if field.value is not None:
            collector.visit(field.value)
        collector.names.update(_quoted_annotation_dependencies(field.annotation))
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
) -> tuple[ast.AnnAssign, ...]:
    """Qualify constants declared on the entity as ``Entity.CONSTANT``."""
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
        result.annotation = qualifier.visit(result.annotation)
        if result.value is not None:
            result.value = qualifier.visit(result.value)
        qualified.append(ast.fix_missing_locations(result))
    return tuple(qualified)


def _quoted_annotation_dependencies(annotation: ast.expr) -> set[str]:
    names: set[str] = set()

    def visit(node: ast.AST) -> None:
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            try:
                parsed = ast.parse(node.value, mode="eval").body
            except SyntaxError:
                return
            collector = _FreeNameCollector()
            collector.visit(parsed)
            names.update(collector.names)
            visit(parsed)
            return
        if isinstance(node, ast.Subscript):
            kind = _reference_name(node.value)
            if kind == "Literal":
                return
            if kind == "Annotated":
                arguments = _subscript_arguments(node.slice)
                if arguments:
                    visit(arguments[0])
                return
        for child in ast.iter_child_nodes(node):
            visit(child)

    visit(annotation)
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
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, (ast.Store, ast.Param))
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
