from pathlib import Path

from arclith_cli.add_adapter import add_adapter_cmd
from arclith_cli.capabilities import capability_catalog_as_dict, get_capability


def _minimal_project(tmp_path: Path) -> Path:
    project_dir = tmp_path / "demo-service"
    (project_dir / "src" / "demo_service" / "domain" / "models").mkdir(parents=True)
    config_dir = project_dir / "config" / "adapters"
    config_dir.mkdir(parents=True)
    (config_dir / "adapters.yaml").write_text(
        "logger: console\nrepository: memory\nobservability:\n  enabled: []\n",
        encoding="utf-8",
    )
    return project_dir


def test_embedding_capability_catalog_declares_deterministic_adapter() -> None:
    capability = get_capability("embedding")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("deterministic",)
    deterministic = capability.get_adapter("deterministic")
    assert deterministic is not None
    assert deterministic.entity_scoped is False
    assert deterministic.config_path == "config/adapters/outbound/embedding.yaml"
    assert [parameter.name for parameter in deterministic.parameters] == [
        "model_name",
        "dimensions",
        "batch_size",
        "normalize",
        "multitenant",
    ]


def test_embedding_capability_is_exposed_in_json_catalog() -> None:
    payload_by_name = {
        capability["name"]: capability for capability in capability_catalog_as_dict()
    }

    embedding = payload_by_name["embedding"]
    assert embedding["activation_config_key"] is None
    assert [adapter["name"] for adapter in embedding["adapters"]] == ["deterministic"]


def test_add_deterministic_embedding_generates_loadable_config_idempotently(
    tmp_path: Path,
) -> None:
    project_dir = _minimal_project(tmp_path)
    params = {
        "model_name": "deterministic-smoke",
        "dimensions": "24",
        "batch_size": "3",
        "normalize": "true",
        "multitenant": "false",
    }

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="embedding",
            adapter="deterministic",
            adapter_params=params,
            yes=True,
        )

    from arclith import Arclith, DeterministicEmbeddingAdapter

    config_path = project_dir / "config" / "adapters" / "outbound" / "embedding.yaml"
    app = Arclith(project_dir / "config")

    assert config_path.read_text(encoding="utf-8") == (
        "adapter: deterministic\n"
        'model_name: "deterministic-smoke"\n'
        "dimensions: 24\n"
        "batch_size: 3\n"
        "normalize: true\n"
        "multitenant: false\n"
    )
    assert app.config.adapters.embedding is not None
    assert app.config.adapters.embedding.dimensions == 24
    assert isinstance(app.embedding(), DeterministicEmbeddingAdapter)
    assert "embedding:" not in (
        project_dir / "config" / "adapters" / "adapters.yaml"
    ).read_text(encoding="utf-8")
