import ast
from pathlib import Path

from arclith.adapters.outbound.noop.observability import NoOpTraceAdapter
from arclith.domain.ports.outbound.observability import TracePort


def test_noop_trace_adapter_honors_full_port_contract() -> None:
    tracer = NoOpTraceAdapter()
    headers: dict[str, str] = {}

    assert isinstance(tracer, TracePort)
    with tracer.context(enabled=False, parent={"traceparent": "ignored"}):
        with tracer.span("operation", inputs={"secret": "ignored"}) as span:
            span.set_metadata({"safe": True})
            span.set_outputs({"status": "ok"})
    tracer.inject(headers)
    tracer.flush(1.0)
    tracer.close(1.0)

    assert headers == {}
    assert tracer.diagnostics() == {"backend": "noop", "tracing": False}


def test_core_does_not_import_observability_vendors() -> None:
    root = Path(__file__).parents[4] / "arclith"

    for package in (root / "domain", root / "application"):
        for path in package.rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported_modules = {
                node.module or ""
                for node in ast.walk(tree)
                if isinstance(node, ast.ImportFrom)
            }
            imported_modules.update(
                alias.name
                for node in ast.walk(tree)
                if isinstance(node, ast.Import)
                for alias in node.names
            )
            assert not any(
                module.startswith(("langsmith", "opentelemetry"))
                for module in imported_modules
            ), path
