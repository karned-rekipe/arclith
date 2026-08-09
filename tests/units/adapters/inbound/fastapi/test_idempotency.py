from typing import Any

from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi.testclient import TestClient

from arclith.adapters.inbound.fastapi.idempotency import IdempotencyMiddleware
from arclith.domain.ports.outbound.logger import Logger, LogLevel


class FakeCache:
    def __init__(self) -> None:
        self.data: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    async def get(self, key: str) -> str | None:
        return self.data.get(key)

    async def set(self, key: str, value: str, ttl_s: int) -> None:
        self.data[key] = value
        self.ttls[key] = ttl_s

    async def delete(self, key: str) -> None:
        self.data.pop(key, None)


class FakeLogger(Logger):
    def __init__(self) -> None:
        self.records: list[dict[str, Any]] = []

    def log(self, level: LogLevel, message: str, **metadata: Any) -> None:
        self.records.append({"level": level, "message": message, "metadata": metadata})


def test_idempotency_cache_miss_caches_success_then_replays_response() -> None:
    app = FastAPI()
    cache = FakeCache()
    logger = FakeLogger()
    calls = 0

    @app.post("/items")
    async def create_item() -> JSONResponse:
        nonlocal calls
        calls += 1
        return JSONResponse({"calls": calls}, status_code=201)

    app.add_middleware(IdempotencyMiddleware, cache=cache, logger=logger, ttl=60)
    client = TestClient(app)

    first = client.post("/items", headers={"Idempotency-Key": "create-1"})
    second = client.post("/items", headers={"Idempotency-Key": "create-1"})

    assert first.status_code == 201
    assert first.json() == {"calls": 1}
    assert second.status_code == 201
    assert second.json() == {"calls": 1}
    assert second.headers["x-idempotency-replay"] == "true"
    assert calls == 1
    assert cache.ttls["idempotency:/items:create-1"] == 60


def test_idempotency_required_rejects_post_without_key() -> None:
    app = FastAPI()
    calls = 0

    @app.post("/items")
    async def create_item() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    app.add_middleware(
        IdempotencyMiddleware,
        cache=FakeCache(),
        logger=FakeLogger(),
        required=True,
    )
    response = TestClient(app).post("/items")

    assert response.status_code == 400
    assert response.json() == {"detail": "Idempotency-Key header is required for POST requests"}
    assert calls == 0


def test_idempotency_does_not_cache_error_responses() -> None:
    app = FastAPI()
    calls = 0

    @app.post("/items")
    async def create_item() -> JSONResponse:
        nonlocal calls
        calls += 1
        return JSONResponse({"calls": calls}, status_code=422)

    app.add_middleware(IdempotencyMiddleware, cache=FakeCache(), logger=FakeLogger())
    client = TestClient(app)

    first = client.post("/items", headers={"Idempotency-Key": "bad-1"})
    second = client.post("/items", headers={"Idempotency-Key": "bad-1"})

    assert first.status_code == 422
    assert first.json() == {"calls": 1}
    assert second.status_code == 422
    assert second.json() == {"calls": 2}
    assert "x-idempotency-replay" not in second.headers
