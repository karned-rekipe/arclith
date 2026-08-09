from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from arclith import Arclith
from arclith.adapters.inbound.fastapi.etag import ETaggerMiddleware, get_expected_version_from_request
from arclith.domain.ports.outbound.logger import Logger, LogLevel


class FakeLogger(Logger):
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def log(self, level: LogLevel, message: str, **metadata: Any) -> None:
        self.records.append({"level": level, "message": message, "metadata": metadata})


def test_etag_get_adds_header_from_wrapped_response_version() -> None:
    app = FastAPI()

    @app.get("/items/1")
    async def read_item() -> dict[str, dict[str, int]]:
        return {"data": {"version": 3}}

    app.add_middleware(ETaggerMiddleware, logger=FakeLogger())
    response = TestClient(app).get("/items/1")

    assert response.status_code == 200
    assert response.headers["etag"] == '"v3"'
    assert response.json() == {"data": {"version": 3}}


def test_etag_get_if_none_match_returns_304_without_body() -> None:
    app = FastAPI()

    @app.get("/items/1")
    async def read_item() -> dict[str, int]:
        return {"version": 3}

    app.add_middleware(ETaggerMiddleware, logger=FakeLogger())
    response = TestClient(app).get("/items/1", headers={"If-None-Match": '"v3"'})

    assert response.status_code == 304
    assert response.headers["etag"] == '"v3"'
    assert response.content == b""


def test_etag_put_if_match_is_available_without_response_cache_header() -> None:
    app = FastAPI()

    @app.put("/items/1")
    async def update_item(request: Request) -> dict[str, int | None]:
        return {"expected_version": get_expected_version_from_request(request), "version": 4}

    app.add_middleware(ETaggerMiddleware, logger=FakeLogger())
    response = TestClient(app).put("/items/1", headers={"If-Match": 'W/"v3"'})

    assert response.status_code == 200
    assert response.json() == {"expected_version": 3, "version": 4}
    assert "etag" not in response.headers


def test_arclith_fastapi_does_not_add_etag_when_disabled(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    adapters_dir = config_dir / "adapters"
    adapters_dir.mkdir(parents=True)
    (adapters_dir / "adapters.yaml").write_text(
        "logger: console\n"
        "repository: memory\n"
        "observability:\n"
        "  enabled: []\n",
        encoding="utf-8",
    )
    (config_dir / "http.yaml").write_text(
        "idempotency:\n"
        "  enabled: false\n"
        "etag:\n"
        "  enabled: false\n"
        "cache_control:\n"
        "  get_single_max_age: 300\n"
        "  get_list_max_age: 60\n",
        encoding="utf-8",
    )

    app = Arclith(config_dir).fastapi()

    @app.get("/items/1")
    async def read_item() -> dict[str, int]:
        return {"version": 3}

    response = TestClient(app).get("/items/1")

    assert response.status_code == 200
    assert "etag" not in response.headers
