"""Resolve statically declared Pydantic input aliases."""

from __future__ import annotations

import ast


def static_input_aliases(
    kind: str,
    value: ast.expr,
    *,
    alias_path_names: set[str],
    alias_path_modules: set[str],
    alias_choices_names: set[str],
    alias_choices_modules: set[str],
) -> set[str] | None:
    """Return top-level input keys when an alias is entirely static."""
    if isinstance(value, ast.Constant) and isinstance(value.value, str):
        return {value.value}
    if kind == "alias" or not isinstance(value, ast.Call):
        return None
    if _is_pydantic_constructor(
        value,
        "AliasPath",
        alias_path_names,
        alias_path_modules,
    ):
        return _static_alias_path(value)
    if (
        not _is_pydantic_constructor(
            value,
            "AliasChoices",
            alias_choices_names,
            alias_choices_modules,
        )
        or value.keywords
        or not value.args
    ):
        return None
    aliases: set[str] = set()
    for choice in value.args:
        resolved = (
            _static_alias_path(choice)
            if isinstance(choice, ast.Call)
            and _is_pydantic_constructor(
                choice,
                "AliasPath",
                alias_path_names,
                alias_path_modules,
            )
            else static_input_aliases(
                "validation_alias",
                choice,
                alias_path_names=alias_path_names,
                alias_path_modules=alias_path_modules,
                alias_choices_names=set(),
                alias_choices_modules=set(),
            )
        )
        if resolved is None:
            return None
        aliases.update(resolved)
    return aliases


def _static_alias_path(value: ast.Call) -> set[str] | None:
    if not value.args or value.keywords:
        return None
    segments = [
        argument.value
        for argument in value.args
        if isinstance(argument, ast.Constant)
        and type(argument.value) in {str, int}
    ]
    if len(segments) != len(value.args) or not isinstance(segments[0], str):
        return None
    return {segments[0]}


def _is_pydantic_constructor(
    node: ast.Call,
    symbol: str,
    names: set[str],
    modules: set[str],
) -> bool:
    function = node.func
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute)
        and function.attr == symbol
        and _root_name(function.value) in modules
    )


def _root_name(node: ast.expr) -> str | None:
    while isinstance(node, ast.Attribute):
        node = node.value
    return node.id if isinstance(node, ast.Name) else None
