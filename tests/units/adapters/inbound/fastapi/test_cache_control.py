from typing import Any

from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

from arclith.adapters.inbound.fastapi.cache_control import CacheControlMiddleware
from arclith.domain.ports.outbound.logger import Logger, LogLevel


class FakeLogger(Logger):
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def log(self, level: LogLevel, message: str, **metadata: Any) -> None:
        self.records.append({"level": level, "message": message, "metadata": metadata})


def _client(app: FastAPI) -> TestClient:
    app.add_middleware(
        CacheControlMiddleware,
        logger=FakeLogger(),
        get_single_max_age=900,
        get_list_max_age=0,
    )
    return TestClient(app)


async def test_cache_control_passes_non_http_scope_unchanged() -> None:
    seen_scopes: list[str] = []

    async def app(scope: dict[str, str], receive: Any, send: Any) -> None:
        seen_scopes.append(scope["type"])

    middleware = CacheControlMiddleware(app, logger=FakeLogger())

    await middleware({"type": "lifespan"}, None, None)

    assert seen_scopes == ["lifespan"]


def test_cache_control_get_single_resource_uses_single_ttl() -> None:
    app = FastAPI()

    @app.get("/items/0123456789abcdef0123456789abcdef")
    async def read_item() -> dict[str, str]:
        return {"uuid": "0123456789abcdef0123456789abcdef"}

    response = _client(app).get("/items/0123456789abcdef0123456789abcdef")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "private, max-age=900"


def test_cache_control_get_collection_uses_list_ttl_zero_as_no_store() -> None:
    app = FastAPI()

    @app.get("/items")
    async def list_items() -> list[str]:
        return []

    response = _client(app).get("/items")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_cache_control_mutation_is_no_store() -> None:
    app = FastAPI()

    @app.post("/items")
    async def create_item() -> dict[str, bool]:
        return {"created": True}

    response = _client(app).post("/items")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, no-store, must-revalidate"


def test_cache_control_preserves_existing_header() -> None:
    app = FastAPI()

    @app.get("/items")
    async def list_items(response: Response) -> list[str]:
        response.headers["Cache-Control"] = "public, max-age=42"
        return []

    response = _client(app).get("/items")

    assert response.status_code == 200
    assert response.headers["cache-control"] == "public, max-age=42"


def test_cache_control_supports_optional_directive_branches() -> None:
    middleware = CacheControlMiddleware(
        app=lambda scope, receive, send: None,
        logger=FakeLogger(),
        mutations_no_store=False,
    )

    assert middleware._get_cache_control("POST", "/items") == "no-cache"
    assert middleware._get_cache_control("HEAD", "/items") == "public, max-age=86400"
    assert middleware._get_cache_control("OPTIONS", "/items") == "public, max-age=86400"
    assert middleware._get_cache_control("TRACE", "/items") is None
