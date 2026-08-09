from pathlib import Path

import pytest

from arclith import Arclith
from arclith.adapters.bidirectional.rabbitmq import RabbitMQCommandBus


def test_arclith_rabbitmq_command_bus_requires_enabled_adapter(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    arclith = Arclith(config_dir)

    with pytest.raises(RuntimeError, match="command_bus.enabled"):
        arclith.rabbitmq_command_bus()


def test_arclith_builds_rabbitmq_command_bus_from_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir()
    (config_dir / "command_bus.yaml").write_text(
        "enabled:\n"
        "  - rabbitmq\n"
        "rabbitmq:\n"
        "  url: amqp://broker/\n"
        "  exchange: commands.exchange\n"
        "  queue: commands.queue\n"
        "  routing_key: commands.route\n"
        "  prefetch: 3\n"
        "  consumer_name: worker-a\n"
        "  concurrency: 2\n",
        encoding="utf-8",
    )

    bus = Arclith(config_dir).rabbitmq_command_bus()

    assert isinstance(bus, RabbitMQCommandBus)
