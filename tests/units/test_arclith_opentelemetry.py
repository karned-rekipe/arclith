from pathlib import Path
from typing import Any

import yaml

from arclith import Arclith
from arclith.adapters.outbound.opentelemetry import fastapi as otel_fastapi


def _make_config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    (config_dir / "adapters" / "outbound").mkdir(parents=True)
    (config_dir / "app.yaml").write_text(
        yaml.dump({"name": "demo-api", "version": "1.2.3"}),
        encoding="utf-8",
    )
    (config_dir / "adapters" / "adapters.yaml").write_text(
        yaml.dump({"observability": {"enabled": ["langsmith", "opentelemetry"]}}),
        encoding="utf-8",
    )
    (config_dir / "adapters" / "outbound" / "langsmith.yaml").write_text(
        yaml.dump({"project": "agent-tests"}),
        encoding="utf-8",
    )
    (config_dir / "adapters" / "outbound" / "opentelemetry.yaml").write_text(
        yaml.dump({"instrument_fastapi": True}),
        encoding="utf-8",
    )
    return config_dir


def test_opentelemetry_hook_uses_configured_adapter(tmp_path: Path, monkeypatch) -> None:
    calls: list[dict[str, Any]] = []

    def fake_instrument_fastapi_app(
        app: Any,
        settings: Any,
        *,
        service_name: str,
        service_version: str,
    ) -> None:
        calls.append({
            "app": app,
            "settings": settings,
            "service_name": service_name,
            "service_version": service_version,
        })

    monkeypatch.setattr(otel_fastapi, "instrument_fastapi_app", fake_instrument_fastapi_app)

    arclith = Arclith(_make_config_dir(tmp_path))
    app = object()
    arclith._instrument_fastapi_opentelemetry(app)  # type: ignore[arg-type]

    assert len(calls) == 1
    assert calls[0]["app"] is app
    assert calls[0]["service_name"] == "demo-api"
    assert calls[0]["service_version"] == "1.2.3"
    assert calls[0]["settings"].instrument_fastapi is True


def test_fastapi_instruments_opentelemetry_after_middlewares(tmp_path: Path, monkeypatch) -> None:
    events: list[str] = []

    def fake_add_fastapi_observability(self: Arclith, app: Any) -> None:
        events.append("observability")

    def fake_add_fastapi_http_middlewares(self: Arclith, app: Any) -> None:
        events.append("http")

    def fake_instrument_fastapi_opentelemetry(self: Arclith, app: Any) -> None:
        events.append("opentelemetry")

    monkeypatch.setattr(Arclith, "_add_fastapi_observability", fake_add_fastapi_observability)
    monkeypatch.setattr(Arclith, "_add_fastapi_http_middlewares", fake_add_fastapi_http_middlewares)
    monkeypatch.setattr(Arclith, "_instrument_fastapi_opentelemetry", fake_instrument_fastapi_opentelemetry)

    Arclith(_make_config_dir(tmp_path)).fastapi()

    assert events == ["observability", "http", "opentelemetry"]
