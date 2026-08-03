from pathlib import Path

from arclith_cli.project_paths import detect_project_paths


def test_detect_project_paths_uses_src_package(tmp_path: Path):
    package_root = tmp_path / "src" / "my_service"
    (package_root / "domain" / "models").mkdir(parents=True)

    paths = detect_project_paths(tmp_path)

    assert paths.package_root == package_root
    assert paths.package_name == "my_service"
    assert paths.domain_models == package_root / "domain" / "models"
    assert paths.adapters_outbound == package_root / "adapters" / "outbound"
    assert paths.containers == package_root / "infrastructure" / "containers"
    assert paths.import_path("domain", "models", "recipe") == "my_service.domain.models.recipe"


def test_detect_project_paths_supports_root_layout(tmp_path: Path):
    (tmp_path / "domain" / "models").mkdir(parents=True)

    paths = detect_project_paths(tmp_path)

    assert paths.package_root == tmp_path
    assert paths.package_name is None
    assert paths.import_path("domain", "models", "recipe") == "domain.models.recipe"
