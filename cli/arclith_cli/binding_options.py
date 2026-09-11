"""Protocol-specific validation performed before planning any binding files."""

import re

from arclith_cli.binding_contract import UseCaseContract, public_identifier
from arclith_cli.binding_rendering import BindingOptions
from arclith_cli.http_paths import http_path_parameters

SUPPORTED_TRANSPORTS = frozenset({"fastapi", "fastmcp", "langgraph", "rabbitmq"})
_RESERVED_PATH_FIELDS = frozenset(
    {"payload", "present_result", "request", "to_application", "use_case"}
)


def resolve_binding_options(
    contract: UseCaseContract,
    *,
    via: str,
    feature: str | None,
    public_name: str | None,
    http_path: str | None,
    method: str | None,
    status_code: int,
    command_type: str | None,
) -> BindingOptions:
    feature_name = public_identifier(feature or contract.name)
    name = public_name or contract.name
    http_method = (
        method or ("GET" if contract.request.endswith("Query") else "POST")
    ).upper()
    path = http_path or f"/v1/{feature_name}/{contract.name}"
    wire_type = command_type or f"{feature_name}.{contract.name}.v1"
    options = BindingOptions(
        via, feature_name, name, path, http_method, status_code, wire_type
    )
    validate_binding_options(options)
    _validate_transport_request(contract, via, http_method, path)
    return options


def validate_binding_options(options: BindingOptions) -> None:
    """Reapply the complete saved-option contract before rendering a manifest."""
    if options.via not in SUPPORTED_TRANSPORTS:
        raise ValueError("Unsupported binding transport")
    if public_identifier(options.feature) != options.feature:
        raise ValueError("Binding feature must use its normalized Python identifier")
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", options.public_name):
        raise ValueError(
            "Public component name must start with a letter and contain letters, digits, _, ., : or -"
        )
    _validate_http(options.http_path, options.method, options.status_code)
    _validate_command_type(options.command_type)


def _validate_command_type(value: str) -> None:
    if not value.strip() or any(char.isspace() for char in value):
        raise ValueError("Command type must be non-empty and contain no whitespace")


def _validate_http(path: str, method: str, status: int) -> None:
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("Unsupported HTTP method")
    if not path.startswith("/") or any(char in path for char in "?#\\"):
        raise ValueError("Use an absolute HTTP path without a query or fragment")
    if any(char.isspace() or ord(char) < 32 for char in path):
        raise ValueError("HTTP path must not contain whitespace or control characters")
    if path == "/v1":
        raise ValueError("Automatic FastAPI bindings require a path below /v1")
    if not path.startswith("/v1/"):
        raise ValueError("Automatic FastAPI bindings must live below the /v1 router")
    http_path_parameters(path)
    validate_response_status(status)


def validate_response_status(status: int) -> None:
    """Use the same strict response-body contract for CLI options and saved manifests."""
    if isinstance(status, bool) or not isinstance(status, int):
        raise ValueError("Response status must be an integer")
    if not 200 <= status <= 299 or status in {204, 205}:
        raise ValueError("Select a 2xx status that supports the use case result body")


def _validate_transport_request(
    contract: UseCaseContract,
    via: str,
    method: str,
    path: str,
) -> None:
    declared_path_parameters = http_path_parameters(path)
    if via != "fastapi" and declared_path_parameters:
        raise ValueError("HTTP path parameters are supported only by FastAPI bindings")
    path_parameters = declared_path_parameters if via == "fastapi" else ()
    unknown = tuple(
        parameter
        for parameter in path_parameters
        if parameter not in dict(contract.request_fields)
    )
    if unknown:
        raise ValueError(
            "HTTP path parameters must name request fields: " + ", ".join(unknown)
        )
    incompatible = tuple(
        parameter
        for parameter in path_parameters
        if parameter not in contract.path_compatible_fields
    )
    if incompatible:
        raise ValueError(
            "HTTP path parameters require scalar request fields: "
            + ", ".join(incompatible)
        )
    reserved = tuple(
        parameter for parameter in path_parameters if parameter in _RESERVED_PATH_FIELDS
    )
    if reserved:
        raise ValueError(
            "HTTP path parameters collide with generated binding names: "
            + ", ".join(reserved)
        )
    if (
        via == "fastapi"
        and method in {"GET", "DELETE"}
        and not contract.query_compatible
    ):
        raise ValueError(
            "Automatic query parameters require scalar fields or lists of scalars; write an explicit route for nested models"
        )
    if via == "rabbitmq" and contract.request.endswith("Query"):
        raise ValueError(
            "RabbitMQ command bindings cannot expose queries without an explicit RPC contract"
        )
