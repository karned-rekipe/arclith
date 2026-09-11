"""Readable protocol bindings around the exact same application execute port."""

from dataclasses import dataclass
import ast
import json
from textwrap import dedent

from arclith_cli.binding_contract import UseCaseContract


@dataclass(frozen=True)
class BindingOptions:
    via: str
    feature: str
    public_name: str
    http_path: str
    method: str
    status_code: int
    command_type: str


def render_contract(contract: UseCaseContract) -> str:
    """Snapshot a transport input model so later application edits are explicit."""
    imports = tuple(dict.fromkeys((contract.request, *contract.result_names)))
    header = "\n".join(
        dict.fromkeys(
            (
                *contract.request_imports,
                *contract.response_imports,
                "from pydantic import ConfigDict",
            )
        )
    )
    tree = ast.parse(contract.request_source)
    declaration = tree.body[0]
    assert isinstance(declaration, ast.ClassDef)
    declaration.name = contract.transport_request
    model = ast.unparse(declaration)
    if len(declaration.body) == 2 and isinstance(declaration.body[-1], ast.Pass):
        model = model.replace("\n    pass", "\n\n    pass")
    return (
        '"""Developer-owned transport contract snapshot and pure application mapping."""\n\n'
        "from __future__ import annotations\n\n"
        + header
        + "\n"
        + _parenthesized_import(contract.module, imports)
        + "\n\n"
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
        + f"\n\n\ndef to_application(request: {contract.transport_request}) -> {contract.request}:\n"
        + f"    return {contract.request}.model_validate(request.model_dump(), by_name=True)\n"
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
    contract: UseCaseContract, options: BindingOptions, adapter_import: str
) -> str:
    # Result names are exported by their owning application port, not re-exported
    # through the transport contract module.
    port_names = (contract.port,)
    contract_names = (
        contract.transport_request,
        "to_application",
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
        return header + _fastapi(contract, options)
    if options.via == "fastmcp":
        return header + _fastmcp(contract, options)
    if options.via == "langgraph":
        return header + _langgraph(contract, options)
    return header + _rabbitmq(contract, options)


def _call(contract: UseCaseContract, request: str = "payload") -> str:
    prefix = "await " if contract.asynchronous else ""
    return f"{prefix}use_case.execute(to_application({request}))"


def _fastapi(contract: UseCaseContract, options: BindingOptions) -> str:
    query = options.method in {"GET", "DELETE"}
    annotation = (
        f"Annotated[{contract.transport_request}, Query()]"
        if query
        else contract.transport_request
    )
    extra = "from typing import Annotated\nfrom fastapi import Query\n" if query else ""
    definition = "async def" if contract.asynchronous else "def"
    route_path = options.http_path.removeprefix("/v1")
    return extra + dedent(f"""
        from fastapi import APIRouter


        def register(router: APIRouter, use_case: {contract.port}) -> None:
            {definition} {contract.name}(payload: {annotation}) -> {contract.transport_response}:
                return present_result({_call(contract)})

            router.add_api_route(
                {json.dumps(route_path)},
                {contract.name},
                methods=[{json.dumps(options.method)}],
                response_model={contract.transport_response},
                status_code={options.status_code},
                operation_id={json.dumps(options.public_name)},
                responses={{422: {{"description": "Invalid request"}}}},
            )
    """)


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
