"""Inspect record declarations without executing project-owned code."""

from __future__ import annotations

import ast
from typing import TYPE_CHECKING

from arclith_cli.module_bindings import module_bindings_before

if TYPE_CHECKING:
    from arclith_cli.entity_scanner import EntityInfo


def inspect_immutable_record(entity: EntityInfo) -> bool:
    """Validate the direct record base and report project-owned fields.

    Runtime model customization remains owned by the project. The CLI only
    accepts a directly imported Arclith base and preserves its core settings.
    """
    if not entity.file_path.is_file():
        return False
    tree = ast.parse(entity.file_path.read_text(encoding="utf-8"))
    models = [
        node
        for node in tree.body
        if isinstance(node, ast.ClassDef) and node.name == entity.pascal
    ]
    if len(models) != 1:
        raise ValueError("Expected one top-level ImmutableRecord declaration")
    model = models[0]
    if len(model.bases) != 1 or not is_record_base(tree, model.bases[0], model.lineno):
        raise ValueError("append-only requires a direct Arclith ImmutableRecord base")
    if model.keywords or model.decorator_list:
        raise ValueError(
            "Record class options and decorators require explicit manual composition"
        )
    reserved = {"uuid", "occurred_at", "recorded_at", "model_config", "Config"}
    for node in ast.walk(model):
        if (
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Store)
            and node.id in reserved
        ):
            raise ValueError(
                "Record technical fields and configuration must remain inherited"
            )
        if (
            isinstance(node, ast.ClassDef)
            and node is not model
            and node.name == "Config"
        ):
            raise ValueError(
                "Record technical fields and configuration must remain inherited"
            )
    return any(
        isinstance(statement, ast.AnnAssign)
        and isinstance(statement.target, ast.Name)
        and not statement.target.id.startswith("_")
        for statement in model.body
    )


def is_record_base(tree: ast.Module, base: ast.expr, line: int) -> bool:
    """Recognize direct, aliased and module-qualified imports of the base."""
    reference = ast.unparse(base)
    root, *tail = reference.split(".")
    binding = module_bindings_before(tree, line - 1).get(root)
    if binding is None:
        return False
    statement, alias = binding
    if isinstance(statement, ast.ImportFrom):
        if statement.level:
            return False
        origin = ".".join((statement.module or "", alias.name, *tail))
    else:
        origin = ".".join((alias.name if alias.asname else root, *tail))
    return origin in {
        "arclith.ImmutableRecord",
        "arclith.domain.models.ImmutableRecord",
        "arclith.domain.models.immutable_record.ImmutableRecord",
    }
