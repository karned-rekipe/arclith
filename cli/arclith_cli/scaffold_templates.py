from __future__ import annotations


def render_entity_template(*, class_name: str) -> str:
    return f'''from __future__ import annotations

from arclith.domain.models.entity import Entity

# Guides:
# - Arclith entity tutorial: https://github.com/karned-rekipe/arclith/blob/main/docs/tutorials/todo-list/02-create-entity.md
# - Arclith architecture: https://github.com/karned-rekipe/arclith/blob/main/arclith/docs/architecture.md
# - Pydantic models: https://docs.pydantic.dev/latest/concepts/models/
# - Pydantic fields: https://docs.pydantic.dev/latest/concepts/fields/
# - Pydantic validators: https://docs.pydantic.dev/latest/concepts/validators/


class {class_name}(Entity):
    """TODO: define the business fields and invariants for this entity.

    Arclith Entity already provides uuid, audit fields, soft-delete fields,
    and optimistic versioning.
    """

    # Example:
    # title: str = Field(min_length=1, max_length=140)
    pass
'''


def render_entity_inbound_port_template(
    *,
    class_name: str,
    entity_class: str,
    entity_module: str,
) -> str:
    return f'''from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

from {entity_module} import {entity_class}

# Guides:
# - Arclith use case tutorial: https://github.com/karned-rekipe/arclith/blob/main/docs/tutorials/todo-list/03-create-usecase.md
# - Arclith architecture: https://github.com/karned-rekipe/arclith/blob/main/arclith/docs/architecture.md
# - Pydantic models: https://docs.pydantic.dev/latest/concepts/models/
# - Pydantic fields: https://docs.pydantic.dev/latest/concepts/fields/


class {class_name}Command(BaseModel):
    """TODO: define validated input data for this use case."""

    pass


class {class_name}Port(ABC):
    @abstractmethod
    async def execute(self, command: {class_name}Command) -> {entity_class}:
        raise NotImplementedError
'''


def render_entity_use_case_template(
    *,
    class_name: str,
    entity_class: str,
    entity_module: str,
    inbound_port_module: str,
) -> str:
    return f'''from __future__ import annotations

from arclith.domain.ports.outbound.repository import Repository

from {entity_module} import {entity_class}
from {inbound_port_module} import {class_name}Command, {class_name}Port


class {class_name}UseCase({class_name}Port):
    def __init__(self, repository: Repository[{entity_class}]) -> None:
        self._repository = repository

    async def execute(self, command: {class_name}Command) -> {entity_class}:
        """TODO: orchestrate business rules and persist or return the entity."""
        raise NotImplementedError("Implement {class_name}UseCase.execute")
'''


def render_transverse_inbound_port_template(*, class_name: str) -> str:
    return f'''from __future__ import annotations

from abc import ABC, abstractmethod

from pydantic import BaseModel

# Guides:
# - Arclith use case tutorial: https://github.com/karned-rekipe/arclith/blob/main/docs/tutorials/todo-list/03-create-usecase.md
# - Arclith architecture: https://github.com/karned-rekipe/arclith/blob/main/arclith/docs/architecture.md
# - Pydantic models: https://docs.pydantic.dev/latest/concepts/models/
# - Pydantic fields: https://docs.pydantic.dev/latest/concepts/fields/


class {class_name}Command(BaseModel):
    """TODO: define validated input data for this use case."""

    pass


class {class_name}Result(BaseModel):
    """TODO: define output data for this use case."""

    pass


class {class_name}Port(ABC):
    @abstractmethod
    async def execute(self, command: {class_name}Command) -> {class_name}Result:
        raise NotImplementedError
'''


def render_transverse_use_case_template(
    *,
    class_name: str,
    inbound_port_module: str,
) -> str:
    return f'''from __future__ import annotations

from {inbound_port_module} import (
    {class_name}Command,
    {class_name}Port,
    {class_name}Result,
)


class {class_name}UseCase({class_name}Port):
    async def execute(self, command: {class_name}Command) -> {class_name}Result:
        """TODO: orchestrate this transverse use case."""
        raise NotImplementedError("Implement {class_name}UseCase.execute")
'''
