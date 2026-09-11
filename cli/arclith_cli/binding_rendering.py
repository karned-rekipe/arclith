"""Readable protocol bindings around the exact same application execute port."""

import ast
from dataclasses import dataclass
import json
from textwrap import dedent

from arclith_cli.binding_contract import UseCaseContract
from arclith_cli.http_paths import http_path_parameters


@dataclass(frozen=True)
class BindingOptions:
    via: str
    feature: str
    public_name: str
    http_path: str
    method: str
    status_code: int
    command_type: str


@dataclass(frozen=True)
class ApplicationErrorMapping:
    module: str
    error: str
    status_code: int
    description: str


def render_contract(
    contract: UseCaseContract,
    path_parameters: tuple[str, ...] = (),
) -> str:
    """Snapshot a transport input model so later application edits are explicit."""
    imports = tuple(dict.fromkeys((contract.request, *contract.result_names)))
    path_annotations = _path_annotations(contract, path_parameters)
    annotated_import = (
        ("from typing import Annotated as _Annotated",)
        if any(annotation.metadata for annotation in path_annotations.values())
        else ()
    )
    header = "\n".join(
        dict.fromkeys(
            (
                *contract.request_imports,
                *contract.response_imports,
                *annotated_import,
                "from pydantic import ConfigDict",
            )
        )
    )
    tree = ast.parse(contract.request_source)
    declaration = tree.body[0]
    assert isinstance(declaration, ast.ClassDef)
    declaration.name = contract.transport_request
    declaration.body = [
        statement
        for statement in declaration.body
        if not (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.target.id in path_parameters
        )
    ]
    if not declaration.body:
        declaration.body.append(ast.Pass())
    model = ast.unparse(declaration)
    if len(declaration.body) == 2 and isinstance(declaration.body[-1], ast.Pass):
        model = model.replace("\n    pass", "\n\n    pass")
    aliases = _path_aliases(contract, path_parameters)
    path_aliases = "".join(
        f"type {aliases[parameter]} = {path_annotations[parameter].render()}\n"
        for parameter in path_parameters
    )
    application_payload = "request.model_dump(exclude_unset=True)"
    if path_parameters:
        overrides = ", ".join(
            f"{json.dumps(parameter)}: {parameter}" for parameter in path_parameters
        )
        application_payload = (
            f"{{**request.model_dump(exclude_unset=True), {overrides}}}"
        )
    mapper_parameters = "".join(
        f", {parameter}: {aliases[parameter]}" for parameter in path_parameters
    )
    return (
        '"""Developer-owned transport contract snapshot and pure application mapping."""\n\n'
        "from __future__ import annotations\n\n"
        + header
        + "\n"
        + _parenthesized_import(contract.module, imports)
        + "\n\n"
        + path_aliases
        + ("\n" if path_aliases else "")
        + model
        + "\n\n\nclass "
        + contract.transport_response
        + "(BaseModel):\n"
        + "    model_config = ConfigDict(from_attributes=True)\n"
        + (
            "\n".join(f"    {field}" for field in contract.response_fields)
            if contract.response_fields
            else "    pass"
        )
        + f"\n\n\ndef to_application(request: {contract.transport_request}{mapper_parameters}) -> {contract.request}:\n"
        + f"    return {contract.request}.model_validate({application_payload}, by_name=True)\n"
        + f"\n\ndef present_result(result: {contract.result}) -> {contract.transport_response}:\n"
        + '    """Map the application result into the versioned transport response."""\n'
        + f"    return {contract.transport_response}.model_validate(result, from_attributes=True)\n"
    )


def native_module(contract: UseCaseContract, options: BindingOptions) -> str:
    if options.via == "fastapi":
        return f"routers/v1/{options.feature}/routes/{contract.name}"
    if options.via == "fastmcp":
        return f"features/{options.feature}/tools/{contract.name}"
    return f"{'nodes' if options.via == 'langgraph' else 'bindings'}/{contract.name}"


def render_binding(
    contract: UseCaseContract,
    options: BindingOptions,
    adapter_import: str,
    error_mappings: tuple[ApplicationErrorMapping, ...] = (),
) -> str:
    # Result names are exported by their owning application port, not re-exported
    # through the transport contract module.
    port_names = (contract.port,)
    path_parameters = (
        http_path_parameters(options.http_path) if options.via == "fastapi" else ()
    )
    path_aliases = _path_aliases(contract, path_parameters)
    contract_names = (
        contract.transport_request,
        "to_application",
        *(path_aliases[parameter] for parameter in path_parameters),
        *(
            (contract.transport_response, "present_result")
            if options.via != "rabbitmq"
            else ()
        ),
    )
    header = (
        '"""Developer-owned protocol binding; inject the application port explicitly."""\n\n'
        "from __future__ import annotations\n\n"
        + _parenthesized_import(contract.module, port_names)
        + _parenthesized_import(
            f"{adapter_import}.contracts.{contract.name}", contract_names
        )
    )
    if options.via == "fastapi":
        return header + _fastapi(contract, options, error_mappings)
    if options.via == "fastmcp":
        return header + _fastmcp(contract, options)
    if options.via == "langgraph":
        return header + _langgraph(contract, options)
    return header + _rabbitmq(contract, options)


def _call(contract: UseCaseContract, request: str = "payload") -> str:
    return _execute(contract, f"to_application({request})")


def _fastapi(
    contract: UseCaseContract,
    options: BindingOptions,
    error_mappings: tuple[ApplicationErrorMapping, ...],
) -> str:
    query = options.method in {"GET", "DELETE"}
    path_parameters = http_path_parameters(options.http_path)
    request_fields = dict(contract.request_fields)
    payload_fields = tuple(
        field for field in request_fields if field not in path_parameters
    )
    annotation = (
        f"Annotated[{contract.transport_request}, Query()]"
        if query
        else contract.transport_request
    )
    extra = (
        "from typing import Annotated\nfrom fastapi import Query\n"
        if query and payload_fields
        else ""
    )
    definition = "async def" if contract.asynchronous else "def"
    route_path = options.http_path.removeprefix("/v1")
    path_aliases = _path_aliases(contract, path_parameters)
    parameters = [
        f"{parameter}: {path_aliases[parameter]}" for parameter in path_parameters
    ]
    if payload_fields:
        parameters.append(f"payload: {annotation}")
    signature = ", ".join(parameters)
    request = "payload" if payload_fields else f"{contract.transport_request}()"
    mapper_arguments = "".join(
        f", {parameter}={parameter}" for parameter in path_parameters
    )
    mapper_call = f"to_application({request}{mapper_arguments})"
    application_call = _execute(contract, "application_request")
    function_lines = _mapper_boundary(mapper_call)
    function_lines.extend(_execution_boundary(application_call, error_mappings))
    fastapi_imports = (
        "APIRouter, HTTPException as _HTTPException" if error_mappings else "APIRouter"
    )
    error_imports = "".join(
        _parenthesized_import(mapping.module, (mapping.error,))
        for mapping in error_mappings
    )
    responses = {422: {"description": "Invalid request"}}
    responses.update(
        {
            mapping.status_code: {"description": mapping.description}
            for mapping in error_mappings
        }
    )
    lines = [
        "from fastapi.exceptions import RequestValidationError as _RequestValidationError",
        "from pydantic import ValidationError as _ValidationError",
        f"from fastapi import {fastapi_imports}",
        "",
        "",
        f"def register(router: APIRouter, use_case: {contract.port}) -> None:",
        f"    {definition} {contract.name}({signature}) -> {contract.transport_response}:",
        *function_lines,
        "",
        "    router.add_api_route(",
        f"        {json.dumps(route_path)},",
        f"        {contract.name},",
        f"        methods=[{json.dumps(options.method)}],",
        f"        response_model={contract.transport_response},",
        f"        status_code={options.status_code},",
        f"        operation_id={json.dumps(options.public_name)},",
        f"        responses={responses!r},",
        "    )",
    ]
    return extra + error_imports + "\n".join(lines) + "\n"


def _mapper_boundary(call: str) -> list[str]:
    return [
        "        try:",
        f"            application_request = {call}",
        "        except _ValidationError as exc:",
        "            raise _RequestValidationError(exc.errors()) from exc",
    ]


def _execution_boundary(
    call: str,
    error_mappings: tuple[ApplicationErrorMapping, ...],
) -> list[str]:
    lines = [
        "        try:",
        f"            application_result = {call}",
        "        except _ValidationError as exc:",
        "            raise _RequestValidationError(exc.errors()) from exc",
    ]
    for mapping in error_mappings:
        lines.extend(
            (
                f"        except {mapping.error} as exc:",
                "            raise _HTTPException(",
                f"                status_code={mapping.status_code}, detail=str(exc)",
                "            ) from exc",
            )
        )
    lines.append("        return present_result(application_result)")
    return lines


@dataclass(frozen=True)
class _PathAnnotation:
    annotation: str
    metadata: str | None

    def render(self) -> str:
        if self.metadata is None:
            return self.annotation
        return f"_Annotated[{self.annotation}, {self.metadata}]"


def _path_annotations(
    contract: UseCaseContract,
    parameters: tuple[str, ...],
) -> dict[str, _PathAnnotation]:
    annotations = dict(contract.request_fields)
    field_names = set(contract.pydantic_field_names)
    field_modules = set(contract.pydantic_module_names)
    declaration = ast.parse(contract.request_source).body[0]
    assert isinstance(declaration, ast.ClassDef)
    metadata: dict[str, str] = {}
    for statement in declaration.body:
        if (
            isinstance(statement, ast.AnnAssign)
            and isinstance(statement.target, ast.Name)
            and statement.value is not None
            and _field_metadata(statement.value, field_names, field_modules)
        ):
            metadata[statement.target.id] = ast.unparse(statement.value)
    return {
        parameter: _PathAnnotation(annotations[parameter], metadata.get(parameter))
        for parameter in parameters
    }


def _field_metadata(
    node: ast.expr | None,
    names: set[str],
    modules: set[str],
) -> bool:
    if not isinstance(node, ast.Call):
        return False
    function = node.func
    return (isinstance(function, ast.Name) and function.id in names) or (
        isinstance(function, ast.Attribute)
        and function.attr == "Field"
        and isinstance(function.value, ast.Name)
        and function.value.id in modules
    )


def _path_aliases(
    contract: UseCaseContract,
    parameters: tuple[str, ...],
) -> dict[str, str]:
    occupied = _contract_symbols(contract)
    aliases: dict[str, str] = {}
    for parameter in parameters:
        base = f"PathParam_{parameter}"
        candidate = base
        suffix = 2
        while candidate in occupied:
            candidate = f"{base}_{suffix}"
            suffix += 1
        aliases[parameter] = candidate
        occupied.add(candidate)
    return aliases


def _contract_symbols(contract: UseCaseContract) -> set[str]:
    sources = (contract.request_source, *contract.response_fields)
    symbols = {
        node.id
        for source in sources
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Name)
    }
    symbols.update(
        {
            contract.request,
            contract.transport_request,
            contract.transport_response,
            *contract.result_names,
        }
    )
    return symbols


def _execute(contract: UseCaseContract, request: str) -> str:
    prefix = "await " if contract.asynchronous else ""
    return f"{prefix}use_case.execute({request})"


def _fastmcp(contract: UseCaseContract, options: BindingOptions) -> str:
    definition = "async def" if contract.asynchronous else "def"
    return dedent(f'''
        from typing import Any
        from fastmcp import FastMCP


        def register(server: FastMCP[Any], use_case: {contract.port}) -> None:
            {definition} {contract.name}(payload: {contract.transport_request}) -> {contract.transport_response}:
                """Execute {options.public_name} through the shared application port."""
                return present_result({_call(contract)})

            server.tool({contract.name}, name={json.dumps(options.public_name)})
    ''')


def _langgraph(contract: UseCaseContract, options: BindingOptions) -> str:
    definition = "async def" if contract.asynchronous else "def"
    result_type = "Awaitable[BindingState]" if contract.asynchronous else "BindingState"
    callable_import = "Awaitable, Callable" if contract.asynchronous else "Callable"
    return dedent(f'''
        from collections.abc import {callable_import}
        from typing import TypedDict
        from langgraph.graph import StateGraph


        class BindingState(TypedDict, total=False):
            {contract.name}_request: dict[str, object]
            {contract.name}_result: {contract.transport_response}


        def make_node(use_case: {contract.port}) -> Callable[[BindingState], {result_type}]:
            """Compose BindingState into the graph state before adding this node."""
            {definition} {contract.name}(state: BindingState) -> BindingState:
                payload = {contract.transport_request}.model_validate(state["{contract.name}_request"])
                result = {_call(contract)}
                return {{"{contract.name}_result": present_result(result)}}

            return {contract.name}


        def register(builder: StateGraph, use_case: {contract.port}) -> None:
            builder.add_node({json.dumps(options.public_name)}, make_node(use_case))
    ''')


def _rabbitmq(contract: UseCaseContract, options: BindingOptions) -> str:
    body = (
        "await use_case.execute(to_application(request))"
        if contract.asynchronous
        else "await to_thread(use_case.execute, to_application(request))"
    )
    extra = "from asyncio import to_thread\n" if not contract.asynchronous else ""
    return extra + dedent(f"""
        from collections.abc import Mapping
        from typing import Any
        from arclith.application.command_bus import CommandDispatcher
        from arclith.domain.ports.inbound.command_bus import CommandHandler


        class Handler(CommandHandler):
            command_type = {json.dumps(options.command_type)}

            def __init__(self, use_case: {contract.port}) -> None:
                self._use_case = use_case

            async def handle(
                self,
                payload: Mapping[str, Any],
                headers: Mapping[str, str],
            ) -> None:
                use_case = self._use_case
                request = {contract.transport_request}.model_validate(payload)
                {body}


        def register(dispatcher: CommandDispatcher, use_case: {contract.port}) -> None:
            dispatcher.register(Handler(use_case))
    """)


def _parenthesized_import(module: str, names: tuple[str, ...]) -> str:
    rendered = "".join(f"    {name},\n" for name in names)
    return f"from {module} import (\n{rendered})\n"
