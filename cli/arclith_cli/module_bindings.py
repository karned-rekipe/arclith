"""Track module bindings without executing project-owned Python code."""

from __future__ import annotations

import ast


def node_line_or_module_end(node: ast.AST, tree: ast.Module) -> int:
    """Return a usable source boundary for synthetic or parsed AST nodes."""

    line = int(getattr(node, "lineno", 0))
    if line:
        return line
    return (
        max(
            (int(getattr(candidate, "lineno", 0)) for candidate in ast.walk(tree)),
            default=0,
        )
        + 1
    )


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
    events = _binding_events(tree, before_line)
    for _, _, statement in events:
        if isinstance(statement, str):
            bindings[statement] = None
            continue
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
        for name in _direct_statement_bound_names(statement):
            bindings[name] = None
    return bindings


def conditional_module_bindings(
    tree: ast.Module,
) -> tuple[tuple[int, int, str], ...]:
    """Return names whose module binding depends on runtime control flow."""
    collector = _ConditionalBindingCollector(set(module_imports(tree)))
    for statement in tree.body:
        if isinstance(
            statement,
            (
                ast.If,
                ast.For,
                ast.AsyncFor,
                ast.While,
                ast.Try,
                ast.TryStar,
                ast.With,
                ast.AsyncWith,
                ast.Match,
            ),
        ):
            collector.visit(statement)
    return tuple(collector.events)


def uncertain_module_bindings_before(
    tree: ast.Module,
    before_line: int,
) -> frozenset[str]:
    """Return bindings whose latest declaration is conditional at a module line."""
    uncertain: dict[str, bool] = {}
    for _, _, event in _binding_events(tree, before_line):
        if isinstance(event, str):
            uncertain[event] = True
            continue
        for name in _direct_statement_bound_names(event):
            uncertain[name] = False
    return frozenset(name for name, is_uncertain in uncertain.items() if is_uncertain)


def _binding_events(
    tree: ast.Module,
    before_line: int,
) -> tuple[tuple[int, int, ast.stmt | str], ...]:
    imports = set(module_imports(tree))
    statements = [
        statement for statement in tree.body if statement.lineno <= before_line
    ]
    statements.extend(
        statement
        for statement in imports
        if statement not in tree.body and statement.lineno < before_line
    )
    events: list[tuple[int, int, ast.stmt | str]] = [
        (statement.lineno, statement.col_offset, statement)
        for statement in statements
    ]
    events.extend(
        (line, column, name)
        for line, column, name in conditional_module_bindings(tree)
        if line < before_line
    )
    named_expressions = _EscapingNamedExprCollector()
    for statement in tree.body:
        named_expressions.visit(statement)
    events.extend(
        (line, column, name)
        for line, column, name in named_expressions.events
        if line < before_line
    )
    return tuple(sorted(events, key=lambda item: item[:2]))


def _direct_statement_bound_names(statement: ast.stmt) -> set[str]:
    if isinstance(statement, ast.Import):
        return {alias.asname or alias.name.split(".")[0] for alias in statement.names}
    if isinstance(statement, ast.ImportFrom):
        return {alias.asname or alias.name for alias in statement.names}
    if isinstance(statement, ast.Assign):
        return {
            name
            for target in statement.targets
            for name in _bound_names(target)
        }
    if isinstance(statement, ast.AnnAssign):
        return _bound_names(statement.target)
    if isinstance(statement, ast.AugAssign):
        return _bound_names(statement.target)
    if isinstance(statement, ast.Delete):
        return {
            name for target in statement.targets for name in _bound_names(target)
        }
    if isinstance(statement, ast.TypeAlias):
        return _bound_names(statement.name)
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return {statement.name}
    return set()


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


def _bound_names(node: ast.AST) -> set[str]:
    return {
        child.id
        for child in ast.walk(node)
        if isinstance(child, ast.Name)
        and isinstance(child.ctx, (ast.Store, ast.Param, ast.Del))
    }


class _EscapingNamedExprCollector(ast.NodeVisitor):
    """Collect walrus targets evaluated in the containing module scope."""

    def __init__(self) -> None:
        self.events: list[tuple[int, int, str]] = []

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.events.extend(
            (
                int(getattr(node.target, "lineno", 0)),
                int(getattr(node.target, "col_offset", 0)),
                name,
            )
            for name in _bound_names(node.target)
        )
        self.visit(node.value)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable_header(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable_header(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for expression in (*node.decorator_list, *node.bases):
            self.visit(expression)
        for keyword in node.keywords:
            self.visit(keyword.value)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self._visit_arguments(node.args)

    def _visit_callable_header(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
    ) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        self._visit_arguments(node.args)

    def _visit_arguments(self, arguments: ast.arguments) -> None:
        for default in (*arguments.defaults, *arguments.kw_defaults):
            if default is not None:
                self.visit(default)


class _ConditionalBindingCollector(ast.NodeVisitor):
    """Collect module-scope bindings nested below control-flow statements."""

    def __init__(
        self,
        accepted_imports: set[ast.Import | ast.ImportFrom],
    ) -> None:
        self._accepted_imports = accepted_imports
        self.events: list[tuple[int, int, str]] = []

    def _record(self, node: ast.AST, name: str) -> None:
        self.events.append(
            (
                int(getattr(node, "lineno", 0)),
                int(getattr(node, "col_offset", 0)),
                name,
            )
        )

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self._record(node, node.id)

    def visit_Import(self, node: ast.Import) -> None:
        if node in self._accepted_imports:
            return
        for alias in node.names:
            self._record(node, alias.asname or alias.name.split(".")[0])

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        if node in self._accepted_imports:
            return
        for alias in node.names:
            self._record(node, alias.asname or alias.name)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._record(node, node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._record(node, node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self._record(node, node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name is not None:
            self._record(node, node.name)
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs) -> None:
        if node.name is not None:
            self._record(node, node.name)
        if node.pattern is not None:
            self.visit(node.pattern)

    def visit_MatchStar(self, node: ast.MatchStar) -> None:
        if node.name is not None:
            self._record(node, node.name)

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest is not None:
            self._record(node, node.rest)
        self.generic_visit(node)
