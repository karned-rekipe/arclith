from pathlib import Path

import pytest
from pydantic import ValidationError

from arclith.infrastructure.config import AppConfig, load_config_dir


def test_loads_langgraph_persistence_from_inbound_yaml(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    langgraph_file = config_dir / "adapters" / "inbound" / "langgraph.yaml"
    langgraph_file.parent.mkdir(parents=True)
    langgraph_file.write_text(
        """entrypoint: "./src/app/agent.py:agent"
persistence:
  enabled: true
  mode: embedded
  checkpointer:
    adapter: sqlite
    path: data/checkpoints.sqlite
    setup: false
    ttl_seconds: null
  store:
    adapter: memory
    namespace_template: "{tenant_id}:{user_id}:memories"
    semantic_search:
      enabled: false
      embed: null
      dims: null
      fields: ["$"]
""",
        encoding="utf-8",
    )

    config = load_config_dir(config_dir)

    assert config.langgraph is not None
    assert config.langgraph.persistence is not None
    assert config.langgraph.persistence.enabled is True
    assert config.langgraph.persistence.checkpointer.adapter == "sqlite"
    assert config.langgraph.persistence.checkpointer.path == "data/checkpoints.sqlite"
    assert config.langgraph.persistence.store.adapter == "memory"


def test_missing_persistence_keeps_existing_langgraph_behavior() -> None:
    config = AppConfig.model_validate(
        {"langgraph": {"entrypoint": "./src/app/agent.py:agent"}}
    )

    assert config.langgraph is not None
    assert config.langgraph.persistence is None


@pytest.mark.parametrize(
    "persistence",
    [
        {"checkpointer": {"ttl_seconds": 0}},
        {
            "store": {
                "semantic_search": {
                    "enabled": True,
                    "embed": None,
                    "dims": None,
                }
            }
        },
        {"store": {"namespace_template": "{tenant_id}::memories"}},
    ],
)
def test_rejects_invalid_langgraph_persistence_config(
    persistence: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AppConfig.model_validate(
            {
                "langgraph": {
                    "entrypoint": "./src/app/agent.py:agent",
                    "persistence": persistence,
                }
            }
        )
