from __future__ import annotations

import time
from typing import Any

from arclith.adapters.inbound.probes.server import ProbeServer


def _make_server(**kwargs: Any) -> ProbeServer:
    defaults = dict(host="127.0.0.1", port=9000, service_name="test-svc", service_version="1.0.0")
    defaults.update(kwargs)
    return ProbeServer(**defaults)


# ── registration ──────────────────────────────────────────────────────────────

class TestProbeServerRegistration:
    def test_add_collector(self):
        server = _make_server()

        class FakeCollector:
            transport = "api"
            def collect(self) -> dict:
                return {"x": 1}

        server.add_collector(FakeCollector())
        assert len(server._collectors) == 1

    def test_add_readiness_check(self):
        server = _make_server()

        async def check() -> bool:
            return True

        server.add_readiness_check(check)
        assert len(server._readiness_checks) == 1

    def test_set_active_transports(self):
        server = _make_server()
        server.set_active_transports(["api", "mcp_http"])
        assert server._active_transports == ["api", "mcp_http"]

    def test_set_active_transports_makes_copy(self):
        server = _make_server()
        transports = ["api"]
        server.set_active_transports(transports)
        transports.append("mcp")
        assert server._active_transports == ["api"]


# ── HTTP routes ───────────────────────────────────────────────────────────────

class TestProbeServerRoutes:
    def _client(self, server: ProbeServer) -> Any:
        from starlette.testclient import TestClient
        return TestClient(server._build_app())

    def test_health_returns_ok(self):
        client = self._client(_make_server())
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ok"}

    def test_ready_no_checks(self):
        client = self._client(_make_server())
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json() == {"status": "ready"}

    async def test_ready_all_checks_pass(self):
        server = _make_server()

        async def _ok() -> bool:
            return True

        server.add_readiness_check(_ok)
        client = self._client(server)
        resp = client.get("/ready")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ready"

    async def test_ready_one_check_fails(self):
        server = _make_server()

        async def _ok() -> bool:
            return True

        async def _fail() -> bool:
            return False

        server.add_readiness_check(_ok)
        server.add_readiness_check(_fail)
        client = self._client(server)
        resp = client.get("/ready")
        assert resp.status_code == 503
        assert resp.json()["status"] == "not_ready"

    async def test_ready_check_raises_treated_as_fail(self):
        server = _make_server()

        async def _boom() -> bool:
            raise RuntimeError("db down")

        server.add_readiness_check(_boom)
        client = self._client(server)
        resp = client.get("/ready")
        assert resp.status_code == 503

    def test_info_fields(self):
        server = _make_server(service_name="my-svc", service_version="2.3.4")
        server.set_active_transports(["api", "mcp_http"])
        client = self._client(server)
        resp = client.get("/info")
        assert resp.status_code == 200
        data = resp.json()
        assert data["service"] == "my-svc"
        assert data["version"] == "2.3.4"
        assert "python" in data
        assert "platform" in data
        assert data["uptime_s"] >= 0.0
        assert data["active_transports"] == ["api", "mcp_http"]

    def test_metrics_empty(self):
        server = _make_server()
        client = self._client(server)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "collected_at" in data
        assert data["transports"] == {}

    def test_metrics_with_collector(self):
        server = _make_server()

        class FakeCollector:
            transport = "api"
            def collect(self) -> dict:
                return {"request_count": 42}

        server.add_collector(FakeCollector())
        client = self._client(server)
        resp = client.get("/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["transports"]["api"] == {"request_count": 42}

    def test_metrics_multiple_collectors(self):
        server = _make_server()

        class ApiCol:
            transport = "api"
            def collect(self) -> dict:
                return {"requests": 10}

        class McpCol:
            transport = "mcp"
            def collect(self) -> dict:
                return {"calls": 5}

        server.add_collector(ApiCol())
        server.add_collector(McpCol())
        client = self._client(server)
        data = client.get("/metrics").json()
        assert data["transports"]["api"] == {"requests": 10}
        assert data["transports"]["mcp"] == {"calls": 5}

    def test_info_uptime_increases(self):
        server = _make_server()
        server._start_time = time.monotonic() - 5.0
        client = self._client(server)
        data = client.get("/info").json()
        assert data["uptime_s"] >= 5.0
