from pathlib import Path
from typing import Any

import pytest
import uvicorn

from arclith import Arclith


def _config_dir(tmp_path: Path) -> Path:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    return config_dir


def test_run_api_enables_reload_for_importable_factory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}

    def fake_run(app: object, **kwargs: Any) -> None:
        received["app"] = app
        received.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)

    Arclith(_config_dir(tmp_path)).run_api("main:build_api", factory=True)

    assert received["app"] == "main:build_api"
    assert received["reload"] is True
    assert received["factory"] is True


def test_run_api_disables_reload_for_application_instance(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    received: dict[str, Any] = {}
    application = object()

    def fake_run(app: object, **kwargs: Any) -> None:
        received["app"] = app
        received.update(kwargs)

    monkeypatch.setattr(uvicorn, "run", fake_run)

    Arclith(_config_dir(tmp_path)).run_api(application)  # type: ignore[arg-type]

    assert received["app"] is application
    assert received["reload"] is False
    assert received["factory"] is False
