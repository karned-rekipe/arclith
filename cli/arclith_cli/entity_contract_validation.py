"""Validate statically projected entity input contracts."""

from __future__ import annotations

import ast


def validate_model_config(model: ast.ClassDef, entity_name: str) -> None:
    """Reject model configurations whose input aliases cannot be inspected."""
    for statement in model.body:
        value: ast.expr | None = None
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == "model_config"
            for target in statement.targets
        ):
            value = statement.value
        elif (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id == "model_config"
        ):
            value = statement.value
        if value is None:
            continue
        alias_generator = _configuration_has_key(value, "alias_generator")
        if alias_generator is not False:
            reason = "contains" if alias_generator else "may contain"
            raise ValueError(
                f"{entity_name}.model_config {reason} an alias_generator that cannot "
                "be projected safely; inline a static config and declare explicit "
                "Field(alias=...) values on business fields"
            )


def _configuration_has_key(value: ast.expr, key: str) -> bool | None:
    if isinstance(value, ast.Call):
        if any(keyword.arg is None for keyword in value.keywords):
            return None
        return any(keyword.arg == key for keyword in value.keywords)
    if isinstance(value, ast.Dict):
        if any(
            item is None
            or not isinstance(item, ast.Constant)
            or not isinstance(item.value, str)
            for item in value.keys
        ):
            return None
        return any(
            isinstance(item, ast.Constant) and item.value == key for item in value.keys
        )
    return None


def validate_input_aliases(
    fields: tuple[ast.AnnAssign, ...],
    pydantic_names: set[str],
    pydantic_modules: set[str],
) -> None:
    """Reject ambiguous aliases and aliases colliding with CRUD metadata."""
    reserved = {"uuid", "version"}
    for field in fields:
        assert isinstance(field.target, ast.Name)
        finders: list[_PydanticAliasCollisionFinder] = []
        for expression, parse_deferred_strings in (
            (field.annotation, True),
            (field.value, False),
        ):
            if expression is None:
                continue
            finder = _PydanticAliasCollisionFinder(
                reserved=reserved,
                pydantic_names=pydantic_names,
                pydantic_modules=pydantic_modules,
                parse_deferred_strings=parse_deferred_strings,
            )
            finder.visit(expression)
            finders.append(finder)
        collisions: set[str] = set().union(
            *(finder.collisions for finder in finders)
        )
        if collisions:
            raise ValueError(
                f"Input aliases for {field.target.id!r} collide with technical CRUD "
                f"fields: {', '.join(sorted(collisions))}"
            )
        if any(finder.has_unresolved_alias for finder in finders):
            raise ValueError(
                f"Input aliases for {field.target.id!r} cannot be resolved statically; "
                "use literal strings, AliasPath, or AliasChoices"
            )


class _PydanticAliasCollisionFinder(ast.NodeVisitor):
    def __init__(
        self,
        *,
        reserved: set[str],
        pydantic_names: set[str],
        pydantic_modules: set[str],
        parse_deferred_strings: bool,
    ) -> None:
        self._reserved = reserved
        self._pydantic_names = pydantic_names
        self._pydantic_modules = pydantic_modules
        self._parse_deferred_strings = parse_deferred_strings
        self.collisions: set[str] = set()
        self.has_unresolved_alias = False

    def visit_Constant(self, node: ast.Constant) -> None:
        if not self._parse_deferred_strings or not isinstance(node.value, str):
            return
        try:
            expression = ast.parse(node.value, mode="eval").body
        except SyntaxError:
            return
        self.visit(expression)

    def visit_Subscript(self, node: ast.Subscript) -> None:
        if reference_name(node.value) == "Literal":
            return
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call) -> None:
        if not is_pydantic_field(
            node,
            self._pydantic_names,
            self._pydantic_modules,
        ):
            self.generic_visit(node)
            return
        for keyword in node.keywords:
            if keyword.arg not in {"alias", "validation_alias"}:
                continue
            aliases = _static_input_aliases(keyword.arg, keyword.value)
            if aliases is None:
                self.has_unresolved_alias = True
            else:
                self.collisions.update(aliases & self._reserved)


def _static_input_aliases(kind: str, value: ast.expr) -> set[str] | None:
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value}
    if kind == "alias" or not isinstance(value, ast.Call):
        return None
    reference = reference_name(value.func)
    if reference == "AliasPath":
        return _static_alias_path(value)
    if reference != "AliasChoices":
        return None
    aliases: set[str] = set()
    for choice in value.args:
        resolved = (
            _static_alias_path(choice)
            if isinstance(choice, ast.Call)
            and reference_name(choice.func) == "AliasPath"
            else _static_input_aliases("validation_alias", choice)
        )
        if resolved is None:
            return None
        aliases.update(resolved)
    return aliases


def _static_alias_path(value: ast.Call) -> set[str] | None:
    if not value.args:
        return None
    first = value.args[0]
    if isinstance(first, ast.Constant) and isinstance(first.value, str):
        return {first.value}
    return None


def is_pydantic_field(
    node: ast.expr | None,
    names: set[str],
    modules: set[str],
) -> bool:
    """Return whether an expression is a recognized Pydantic Field call."""
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute)
        and function.attr == "Field"
        and root_name(function.value) in modules
    )


def root_name(node: ast.expr) -> str | None:
    """Return the root identifier from an attribute chain."""
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None


def reference_name(node: ast.expr) -> str | None:
    """Return the final identifier represented by an expression."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return None
