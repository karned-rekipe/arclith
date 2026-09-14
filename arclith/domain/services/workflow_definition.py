"""Canonical definition/schema fingerprint; business changes require a version bump."""

import hashlib
import json

from pydantic import BaseModel

from arclith.domain.models.workflow import WorkflowDefinition


def workflow_definition_digest(
    definition: WorkflowDefinition,
    context_type: type[BaseModel],
    result_type: type[BaseModel],
) -> str:
    definition = WorkflowDefinition.model_validate(definition)
    if (definition.context, definition.result) != (
        context_type.__name__,
        result_type.__name__,
    ):
        raise ValueError("Workflow model names differ from the definition")
    data = {
        "definition": definition.model_dump(mode="json"),
        "context_schema": context_type.model_json_schema(),
        "result_schema": result_type.model_json_schema(),
    }
    return hashlib.sha256(
        json.dumps(
            data, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode()
    ).hexdigest()
