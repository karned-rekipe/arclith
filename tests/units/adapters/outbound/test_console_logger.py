from typing import Any

from arclith.adapters.outbound.console import logger as console_logger
from arclith.adapters.outbound.console.logger import ConsoleLogger
from arclith.domain.ports.outbound.logger import LogLevel


def test_console_logger_enriches_metadata_with_current_trace(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class BoundLogger:
        def info(self, message: str) -> None:
            captured["message"] = message

    def fake_bind(**kwargs: Any) -> BoundLogger:
        captured["bind"] = kwargs
        return BoundLogger()

    monkeypatch.setattr(console_logger.loguru_logger, "bind", fake_bind)

    correlation = type(
        "Correlation",
        (),
        {
            "current": lambda self: {
                "trace_id": "trace",
                "span_id": "span",
                "trace_sampled": True,
            }
        },
    )()
    ConsoleLogger(correlation=correlation).log(  # type: ignore[arg-type]
        LogLevel.INFO,
        "hello",
        request_id="req-1",
        trace_id="application-trace",
        span_id="application-span",
        trace_sampled=False,
    )

    assert captured["message"] == "hello"
    assert captured["bind"]["meta"] == {
        "trace_id": "trace",
        "span_id": "span",
        "trace_sampled": True,
        "request_id": "req-1",
    }
