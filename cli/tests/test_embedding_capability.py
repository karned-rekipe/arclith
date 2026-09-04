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
        'dependencies = ["arclith>=0.24.0"]\n',
        encoding="utf-8",
    )
    return project_dir


def test_embedding_capability_catalog_declares_deterministic_adapter() -> None:
    capability = get_capability("embedding")

    assert capability is not None
    assert capability.layer == "outbound"
    assert capability.activation_config_key is None
    assert capability.adapter_names() == (
        "deterministic",
        "openai-compatible",
        "openai",
    )
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
    openai_compatible = capability.get_adapter("openai-compatible")
    assert openai_compatible is not None
    assert openai_compatible.entity_scoped is False
    assert openai_compatible.dependency_extra == "embedding"
    assert [parameter.name for parameter in openai_compatible.parameters] == [
        "base_url",
        "api_key",
        "model_name",
        "dimensions",
        "batch_size",
        "timeout",
        "normalize",
        "multitenant",
    ]
    openai = capability.get_adapter("openai")
    assert openai is not None
    assert openai.entity_scoped is False
    assert openai.dependency_extra == "embedding"
    assert openai.secret_mappings[0].field_path == "adapters.embedding.api_key"
    assert openai.secret_mappings[0].secret_key == "OPENAI_API_KEY"
    assert [parameter.name for parameter in openai.parameters] == [
        "base_url",
        "api_key",
        "model_name",
        "dimensions",
        "batch_size",
        "timeout",
        "encoding_format",
        "normalize",
        "multitenant",
    ]
    assert (
        next(
            parameter for parameter in openai.parameters if parameter.name == "api_key"
        ).secret
        is True
    )


def test_embedding_capability_is_exposed_in_json_catalog() -> None:
    payload_by_name = {
        capability["name"]: capability for capability in capability_catalog_as_dict()
    }

    embedding = payload_by_name["embedding"]
    assert embedding["activation_config_key"] is None
    assert [adapter["name"] for adapter in embedding["adapters"]] == [
        "deterministic",
        "openai-compatible",
        "openai",
    ]
    openai = embedding["adapters"][2]
    api_key = next(
        parameter
        for parameter in openai["parameters"]
        if parameter["name"] == "api_key"
    )
    assert api_key["secret"] is True
    assert openai["secret_mappings"] == [
        {
            "field_path": "adapters.embedding.api_key",
            "secret_key": "OPENAI_API_KEY",
        }
    ]


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


def test_add_openai_compatible_embedding_generates_loadable_config_idempotently(
    tmp_path: Path,
) -> None:
    project_dir = _minimal_project(tmp_path)
    params = {
        "base_url": "http://127.0.0.1:1234/v1",
        "api_key": "local-dev",
        "model_name": "nomic-embed-text",
        "dimensions": "768",
        "batch_size": "16",
        "timeout": "12.5",
        "normalize": "false",
        "multitenant": "false",
    }

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="embedding",
            adapter="openai-compatible",
            adapter_params=params,
            yes=True,
        )

    from arclith import Arclith
    from arclith.adapters.outbound.openai_compatible import (
        OpenAICompatibleEmbeddingAdapter,
    )

    config_path = project_dir / "config/adapters/outbound/embedding.yaml"
    app = Arclith(project_dir / "config")

    assert config_path.read_text(encoding="utf-8") == (
        "adapter: openai-compatible\n"
        'base_url: "http://127.0.0.1:1234/v1"\n'
        'api_key: "local-dev"\n'
        'model_name: "nomic-embed-text"\n'
        "dimensions: 768\n"
        "batch_size: 16\n"
        "timeout: 12.5\n"
        "normalize: false\n"
        "multitenant: false\n"
    )
    assert app.config.adapters.embedding is not None
    assert app.config.adapters.embedding.model_name == "nomic-embed-text"
    assert isinstance(app.embedding(), OpenAICompatibleEmbeddingAdapter)
    assert "arclith[embedding]>=0.24.0" in (project_dir / "pyproject.toml").read_text(
        encoding="utf-8"
    )


def test_add_openai_embedding_generates_safe_loadable_config_idempotently(
    tmp_path: Path,
    monkeypatch,
) -> None:
    project_dir = _minimal_project(tmp_path)
    (project_dir / ".env").write_text("EXISTING=value\n", encoding="utf-8")
    params = {
        "model_name": "configured-embedding-model",
        "dimensions": "1536",
    }

    for _ in range(2):
        add_adapter_cmd(
            project_dir=project_dir,
            capability_name="embedding",
            adapter="openai",
            adapter_params=params,
            yes=True,
        )

    config_path = project_dir / "config/adapters/outbound/embedding.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    secrets_text = (project_dir / "config/secrets.yaml").read_text(encoding="utf-8")
    env_text = (project_dir / ".env").read_text(encoding="utf-8")

    assert config_text == (
        "adapter: openai\n"
        'base_url: "https://api.openai.com/v1"\n'
        "api_key: null\n"
        'model_name: "configured-embedding-model"\n'
        "dimensions: 1536\n"
        "batch_size: 64\n"
        "timeout: 30.0\n"
        "encoding_format: float\n"
        "normalize: false\n"
        "multitenant: false\n"
    )
    assert "adapters.embedding.api_key: OPENAI_API_KEY" in secrets_text
    assert secrets_text.count("adapters.embedding.api_key") == 1
    assert env_text == "EXISTING=value\n"
    assert "sk-" not in config_text + secrets_text + env_text
    assert ".env" in (project_dir / ".gitignore").read_text(encoding="utf-8")
    assert "arclith[embedding]>=0.24.0" in (project_dir / "pyproject.toml").read_text(
        encoding="utf-8"
    )

    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    from arclith import Arclith
    from arclith.adapters.outbound.openai import OpenAIEmbeddingAdapter

    app = Arclith(project_dir / "config")

    assert app.config.adapters.embedding is not None
    assert app.config.adapters.embedding.api_key == "test-key"
    assert type(app.embedding()) is OpenAIEmbeddingAdapter


def test_add_openai_embedding_omits_fake_key_and_keeps_dimensions_optional(
    tmp_path: Path,
) -> None:
    project_dir = _minimal_project(tmp_path)

    add_adapter_cmd(
        project_dir=project_dir,
        capability_name="embedding",
        adapter="openai",
        adapter_params={"model_name": "configured-embedding-model"},
        yes=True,
    )

    config_text = (project_dir / "config/adapters/outbound/embedding.yaml").read_text(
        encoding="utf-8"
    )
    env_text = (project_dir / ".env").read_text(encoding="utf-8")

    assert "dimensions: null" in config_text
    assert "api_key: null" in config_text
    assert "OPENAI_API_KEY=" not in env_text
    assert "sk-" not in config_text + env_text
