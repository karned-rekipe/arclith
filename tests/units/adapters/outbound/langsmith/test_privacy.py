from dataclasses import dataclass

from pydantic import BaseModel

from arclith.adapters.outbound.langsmith.privacy import trace_metadata, trace_payload


class ExampleModel(BaseModel):
    name: str


@dataclass
class ExampleData:
    value: int


def test_trace_payload_is_empty_when_capture_is_disabled() -> None:
    assert trace_payload({"secret": "value"}, enabled=False) == {}
    assert trace_payload(None, enabled=True) == {}


def test_trace_payload_serializes_supported_values_without_binary_content() -> None:
    payload = trace_payload(
        {
            "model": ExampleModel(name="demo"),
            "data": ExampleData(value=7),
            "sequence": (1, 2),
            "binary": b"secret bytes",
            "custom": object(),
        },
        enabled=True,
    )

    assert payload["model"] == {"name": "demo"}
    assert payload["data"] == {"value": 7}
    assert payload["sequence"] == [1, 2]
    assert payload["binary"] == "<binary omitted>"
    assert isinstance(payload["custom"], str)
    assert trace_payload("hello", enabled=True) == {"value": "hello"}


def test_trace_metadata_honors_capture_switch() -> None:
    assert trace_metadata({"safe": True}, enabled=True) == {"safe": True}
    assert trace_metadata({"safe": True}, enabled=False) == {}
    assert trace_metadata(None, enabled=True) == {}
