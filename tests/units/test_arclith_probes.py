from pathlib import Path
from typing import Any

from arclith import Arclith


class FakeProbeServer:
    def __init__(self) -> None:
        self.started = 0
        self.active_transports: list[str] = []
        self.readiness_checks: list[Any] = []

    def set_active_transports(self, transports: list[str]) -> None:
        self.active_transports = list(transports)

    def start_in_background(self) -> None:
        self.started += 1

    def add_readiness_check(self, fn: Any) -> None:
        self.readiness_checks.append(fn)


def _write_config(tmp_path: Path, *, enabled: bool) -> Path:
    config_dir = tmp_path / "config"
    inbound_dir = config_dir / "adapters" / "inbound"
    adapters_dir = config_dir / "adapters"
    inbound_dir.mkdir(parents=True)
    (adapters_dir / "adapters.yaml").write_text(
        "logger: console\n"
        "repository: memory\n"
        "observability:\n"
        "  enabled: []\n",
        encoding="utf-8",
    )
    (inbound_dir / "probe.yaml").write_text(
        "host: 127.0.0.1\n"
        "port: 9100\n"
        f"enabled: {str(enabled).lower()}\n",
        encoding="utf-8",
    )
    return config_dir


def test_run_with_probes_does_not_start_probe_server_when_disabled(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path, enabled=False))
    probe_server = FakeProbeServer()
    arclith.__dict__["_probe_server"] = probe_server
    calls: list[str] = []

    arclith.run_with_probes(lambda: calls.append("api"), transports=["api"])

    assert calls == ["api"]
    assert probe_server.started == 0
    assert probe_server.active_transports == ["api"]


def test_run_with_probes_starts_probe_server_and_records_transports(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path, enabled=True))
    probe_server = FakeProbeServer()
    arclith.__dict__["_probe_server"] = probe_server
    calls: list[str] = []

    arclith.run_with_probes(lambda: calls.append("api"), transports=["api", "mcp_http"])

    assert calls == ["api"]
    assert probe_server.started == 1
    assert probe_server.active_transports == ["api", "mcp_http"]


def test_add_readiness_check_registers_on_probe_server(tmp_path: Path) -> None:
    arclith = Arclith(_write_config(tmp_path, enabled=True))
    probe_server = FakeProbeServer()
    arclith.__dict__["_probe_server"] = probe_server

    async def db_ready() -> bool:
        return True

    arclith.add_readiness_check(db_ready)

    assert probe_server.readiness_checks == [db_ready]
