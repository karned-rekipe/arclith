"""Validate callable contracts required by generated state-machine services."""

from __future__ import annotations

import ast


def state_copy_is_controlled(model: ast.ClassDef, state_field: str) -> bool:
    """Prove the public guard and private lifecycle copy can be called safely."""

    public_copy = _single_method_binding(model, "model_copy")
    lifecycle_copy = _single_method_binding(model, f"_copy_with_{state_field}")
    if public_copy is None or lifecycle_copy is None:
        return False
    if not _has_public_copy_signature(public_copy) or not _has_lifecycle_signature(
        lifecycle_copy
    ):
        return False
    public_body = _method_body(public_copy)
    lifecycle_body = _method_body(lifecycle_copy)
    return (
        len(public_body) == 2
        and _is_state_update_guard(public_body[0], state_field)
        and _is_public_model_copy_return(public_body[1])
        and len(lifecycle_body) == 1
        and _is_lifecycle_model_copy_return(lifecycle_body[0], state_field)
    )


def _single_method_binding(
    model: ast.ClassDef,
    name: str,
) -> ast.FunctionDef | None:
    bindings = [statement for statement in model.body if _binds_name(statement, name)]
    if len(bindings) != 1 or not isinstance(bindings[0], ast.FunctionDef):
        return None
    return bindings[0]


def _binds_name(statement: ast.stmt, name: str) -> bool:
    if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        return statement.name == name
    if isinstance(statement, (ast.Import, ast.ImportFrom)):
        return any(
            (item.asname or item.name.split(".", 1)[0]) == name
            for item in statement.names
        )
    return any(
        isinstance(node, ast.Name)
        and node.id == name
        and isinstance(node.ctx, (ast.Store, ast.Del))
        for node in ast.walk(statement)
    )


def _has_public_copy_signature(method: ast.FunctionDef) -> bool:
    arguments = method.args
    positional = [*arguments.posonlyargs, *arguments.args]
    combined = [argument.arg for argument in (*positional, *arguments.kwonlyargs)]
    if (
        method.decorator_list
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or not positional
        or positional[0].arg != "self"
        or combined != ["self", "update", "deep"]
        or any(argument.arg in {"update", "deep"} for argument in arguments.posonlyargs)
    ):
        return False
    required_positional = len(positional) - len(arguments.defaults)
    if any(
        argument.arg in {"update", "deep"} and index < required_positional
        for index, argument in enumerate(positional)
    ):
        return False
    return all(default is not None for default in arguments.kw_defaults)


def _has_lifecycle_signature(method: ast.FunctionDef) -> bool:
    arguments = method.args
    positional = [*arguments.posonlyargs, *arguments.args]
    return (
        not method.decorator_list
        and arguments.vararg is None
        and arguments.kwarg is None
        and [argument.arg for argument in positional] == ["self", "target"]
        and not arguments.kwonlyargs
    )


def _method_body(method: ast.FunctionDef) -> list[ast.stmt]:
    body = list(method.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        return body[1:]
    return body


def _is_state_update_guard(statement: ast.stmt, state_field: str) -> bool:
    if (
        not isinstance(statement, ast.If)
        or statement.orelse
        or len(statement.body) != 1
        or not isinstance(statement.body[0], ast.Raise)
        or not isinstance(statement.test, ast.BoolOp)
        or not isinstance(statement.test.op, ast.And)
        or len(statement.test.values) != 2
    ):
        return False
    return any(_is_update_not_none(value) for value in statement.test.values) and any(
        _is_state_in_update(value, state_field) for value in statement.test.values
    )


def _is_update_not_none(expression: ast.expr) -> bool:
    return (
        isinstance(expression, ast.Compare)
        and isinstance(expression.left, ast.Name)
        and expression.left.id == "update"
        and len(expression.ops) == 1
        and isinstance(expression.ops[0], ast.IsNot)
        and len(expression.comparators) == 1
        and isinstance(expression.comparators[0], ast.Constant)
        and expression.comparators[0].value is None
    )


def _is_state_in_update(expression: ast.expr, state_field: str) -> bool:
    return (
        isinstance(expression, ast.Compare)
        and isinstance(expression.left, ast.Constant)
        and expression.left.value == state_field
        and len(expression.ops) == 1
        and isinstance(expression.ops[0], ast.In)
        and len(expression.comparators) == 1
        and isinstance(expression.comparators[0], ast.Name)
        and expression.comparators[0].id == "update"
    )


def _is_public_model_copy_return(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    keywords = {keyword.arg: keyword.value for keyword in call.keywords}
    update = keywords.get("update")
    deep = keywords.get("deep")
    return (
        _is_super_model_copy(call)
        and not call.args
        and len(keywords) == 2
        and isinstance(update, ast.Name)
        and update.id == "update"
        and isinstance(deep, ast.Name)
        and deep.id == "deep"
    )


def _is_lifecycle_model_copy_return(statement: ast.stmt, state_field: str) -> bool:
    if not isinstance(statement, ast.Return) or not isinstance(statement.value, ast.Call):
        return False
    call = statement.value
    if not _is_super_model_copy(call) or call.args or len(call.keywords) != 1:
        return False
    keyword = call.keywords[0]
    update = keyword.value
    return (
        keyword.arg == "update"
        and isinstance(update, ast.Dict)
        and len(update.keys) == 1
        and isinstance(update.keys[0], ast.Constant)
        and update.keys[0].value == state_field
        and len(update.values) == 1
        and isinstance(update.values[0], ast.Name)
        and update.values[0].id == "target"
    )


def _is_super_model_copy(call: ast.Call) -> bool:
    function = call.func
    return (
        isinstance(function, ast.Attribute)
        and function.attr == "model_copy"
        and isinstance(function.value, ast.Call)
        and isinstance(function.value.func, ast.Name)
        and function.value.func.id == "super"
        and not function.value.args
        and not function.value.keywords
    )
