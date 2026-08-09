from pathlib import Path

from arclith import Arclith
from arclith.adapters.outbound.console.logger import ConsoleLogger


def test_arclith_logger_uses_configured_console_adapter(tmp_path: Path) -> None:
    config_dir = tmp_path / "config" / "adapters"
    config_dir.mkdir(parents=True)
    (config_dir / "adapters.yaml").write_text(
        "logger: console\n"
        "repository: memory\n"
        "observability:\n"
        "  enabled: []\n",
        encoding="utf-8",
    )

    arclith = Arclith(tmp_path / "config")
    logger = arclith.logger

    assert isinstance(logger, ConsoleLogger)
    assert arclith.logger is logger
