"""Protocol-specific validation performed before planning any binding files."""

import re

from arclith_cli.binding_contract import UseCaseContract, public_identifier
from arclith_cli.binding_rendering import BindingOptions


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
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_.:-]*", name):
        raise ValueError(
            "Public component name must start with a letter and contain letters, digits, _, ., : or -"
        )
    http_method = (
        method or ("GET" if contract.request.endswith("Query") else "POST")
    ).upper()
    path = http_path or f"/v1/{feature_name}/{contract.name}"
    _validate_http(path, http_method, status_code)
    _validate_transport_request(contract, via, http_method)
    wire_type = command_type or f"{feature_name}.{contract.name}.v1"
    _validate_command_type(wire_type)
    return BindingOptions(
        via, feature_name, name, path, http_method, status_code, wire_type
    )


def _validate_command_type(value: str) -> None:
    if not value.strip() or any(char.isspace() for char in value):
        raise ValueError("Command type must be non-empty and contain no whitespace")


def _validate_http(path: str, method: str, status: int) -> None:
    if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("Unsupported HTTP method")
    if not path.startswith("/") or any(char in path for char in "{}?#\\"):
        raise ValueError(
            "Use a fixed absolute HTTP path; path-parameter mapping requires a hand-written route"
        )
    if any(char.isspace() or ord(char) < 32 for char in path):
        raise ValueError("HTTP path must not contain whitespace or control characters")
    validate_response_status(status)


def validate_response_status(status: int) -> None:
    """Use the same strict response-body contract for CLI options and saved manifests."""
    if isinstance(status, bool) or not isinstance(status, int):
        raise ValueError("Response status must be an integer")
    if not 200 <= status <= 299 or status in {204, 205}:
        raise ValueError("Select a 2xx status that supports the use case result body")


def _validate_transport_request(
    contract: UseCaseContract, via: str, method: str
) -> None:
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
