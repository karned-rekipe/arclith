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
    (project_dir / "pyproject.toml").write_text(
        '[project]\nname = "demo-service"\nversion = "0.1.0"\n'
        'dependencies = ["arclith>=0.21.0"]\n',
        encoding="utf-8",
    )
    return project_dir


def test_vector_store_capability_catalog_declares_memory_adapter() -> None:
    capability = get_capability("vector-store")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == ("memory", "qdrant")
    memory = capability.get_adapter("memory")
    assert memory is not None
    assert memory.entity_scoped is False
    assert memory.dependency_extra is None
    assert memory.config_path == "config/adapters/outbound/vector_store.yaml"
    assert [parameter.name for parameter in memory.parameters] == [
        "collection_name",
        "vector_size",
        "distance",
        "multitenant",
    ]


def test_vector_store_capability_is_exposed_in_json_catalog() -> None:
    payload_by_name = {
        capability["name"]: capability for capability in capability_catalog_as_dict()
    }

    vector_store = payload_by_name["vector-store"]
    assert vector_store["activation_config_key"] is None
    assert [adapter["name"] for adapter in vector_store["adapters"]] == [
        "memory",
        "qdrant",
    ]


def test_vector_store_capability_declares_qdrant_adapter() -> None:
    capability = get_capability("vector-store")

    assert capability is not None
    qdrant = capability.get_adapter("qdrant")
    assert qdrant is not None
    assert qdrant.entity_scoped is False
    assert qdrant.dependency_extra == "qdrant"
    assert qdrant.config_path == "config/adapters/outbound/vector_store.yaml"
    assert [mapping.field_path for mapping in qdrant.secret_mappings] == [
        "adapters.vector_store.api_key",
    ]
    assert [mapping.secret_key for mapping in qdrant.secret_mappings] == [
        "QDRANT_API_KEY",
    ]


def test_add_memory_vector_store_generates_loadable_config_idempotently(
    tmp_path: Path,
) -> None:
    project_dir = _minimal_project(tmp_path)
    params = {
        "collection_name": "documents",
        "vector_size": "3",
        "distance": "cosine",
        "multitenant": "false",
    }

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="vector-store",
            adapter="memory",
            adapter_params=params,
            yes=True,
        )

    from arclith import Arclith, MemoryVectorStore

    config_path = project_dir / "config/adapters/outbound/vector_store.yaml"
    app = Arclith(project_dir / "config")

    assert config_path.read_text(encoding="utf-8") == (
        "adapter: memory\n"
        'collection_name: "documents"\n'
        "vector_size: 3\n"
        "distance: cosine\n"
        "multitenant: false\n"
    )
    assert app.config.adapters.vector_store is not None
    assert app.config.adapters.vector_store.vector_size == 3
    assert isinstance(app.vector_store(), MemoryVectorStore)
    assert "vector_store:" not in (
        project_dir / "config/adapters/adapters.yaml"
    ).read_text(encoding="utf-8")


def test_add_qdrant_vector_store_generates_loadable_config_and_secrets(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_dir = _minimal_project(tmp_path)
    params = {
        "url": "http://localhost:6333",
        "collection_name": "documents",
        "vector_size": "1536",
        "distance": "cosine",
        "prefer_grpc": "false",
        "timeout": "5.0",
        "create_collection": "true",
        "multitenant": "false",
    }

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="vector-store",
            adapter="qdrant",
            adapter_params=params,
            yes=True,
        )

    config_text = (
        project_dir / "config/adapters/outbound/vector_store.yaml"
    ).read_text(encoding="utf-8")
    secrets_text = (project_dir / "config/secrets.yaml").read_text(encoding="utf-8")

    assert config_text == (
        "adapter: qdrant\n"
        'url: "http://localhost:6333"\n'
        "api_key: null\n"
        'collection_name: "documents"\n'
        "vector_size: 1536\n"
        "distance: cosine\n"
        "prefer_grpc: false\n"
        "timeout: 5.0\n"
        "create_collection: true\n"
        "multitenant: false\n"
    )
    assert secrets_text.count("adapters.vector_store.api_key") == 1
    assert "adapters.vector_store.api_key: QDRANT_API_KEY" in secrets_text
    assert "adapters.vector_store.url" not in secrets_text

    from arclith import Arclith, QdrantVectorStore

    monkeypatch.setenv("QDRANT_API_KEY", "test-key")
    app = Arclith(project_dir / "config")
    assert isinstance(app.vector_store(), QdrantVectorStore)
    assert app.config.adapters.vector_store is not None
    assert app.config.adapters.vector_store.api_key == "test-key"
