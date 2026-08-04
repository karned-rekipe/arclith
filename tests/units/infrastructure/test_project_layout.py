from pathlib import PurePosixPath

import pytest

from arclith.infrastructure.project_layout import ProjectLayout, ProjectLayoutKind, canonical_project_layout


def test_canonical_project_layout_uses_namespaced_src_layout():
    layout = canonical_project_layout("arclith_sample")

    assert layout.kind is ProjectLayoutKind.SRC
    assert layout.package_root == PurePosixPath("src/arclith_sample")
    assert layout.domain == PurePosixPath("src/arclith_sample/domain")
    assert layout.domain_models == PurePosixPath("src/arclith_sample/domain/models")
    assert layout.domain_ports == PurePosixPath("src/arclith_sample/domain/ports")
    assert layout.inbound_ports == PurePosixPath("src/arclith_sample/domain/ports/inbound")
    assert layout.outbound_ports == PurePosixPath("src/arclith_sample/domain/ports/outbound")
    assert layout.application == PurePosixPath("src/arclith_sample/application")
    assert layout.application_use_cases == PurePosixPath("src/arclith_sample/application/use_cases")
    assert layout.application_services == PurePosixPath("src/arclith_sample/application/services")
    assert layout.adapters == PurePosixPath("src/arclith_sample/adapters")
    assert layout.inbound_adapters == PurePosixPath("src/arclith_sample/adapters/inbound")
    assert layout.outbound_adapters == PurePosixPath("src/arclith_sample/adapters/outbound")
    assert layout.infrastructure == PurePosixPath("src/arclith_sample/infrastructure")
    assert layout.tests_root == PurePosixPath("tests")
    assert layout.config_root == PurePosixPath("config")
    assert layout.entrypoint == PurePosixPath("main.py")


def test_project_layout_reports_layer_paths():
    layout = ProjectLayout.src("arclith_sample")

    assert layout.layer_paths() == {
        "domain": PurePosixPath("src/arclith_sample/domain"),
        "application": PurePosixPath("src/arclith_sample/application"),
        "adapters": PurePosixPath("src/arclith_sample/adapters"),
        "infrastructure": PurePosixPath("src/arclith_sample/infrastructure"),
    }
    assert layout.package_paths() == (PurePosixPath("src/arclith_sample"),)


def test_project_layout_reports_port_and_adapter_paths():
    layout = ProjectLayout.src("arclith_sample")

    assert layout.port_paths() == {
        "inbound": PurePosixPath("src/arclith_sample/domain/ports/inbound"),
        "outbound": PurePosixPath("src/arclith_sample/domain/ports/outbound"),
    }
    assert layout.adapter_paths() == {
        "inbound": PurePosixPath("src/arclith_sample/adapters/inbound"),
        "outbound": PurePosixPath("src/arclith_sample/adapters/outbound"),
    }


def test_project_layout_builds_import_paths():
    layout = ProjectLayout.src("arclith_sample")

    assert layout.import_path("domain", "models", "ingredient") == "arclith_sample.domain.models.ingredient"


@pytest.mark.parametrize("package_name", ["ArclithSample", "arclith-sample", "1service", ""])
def test_project_layout_rejects_non_package_names(package_name: str):
    with pytest.raises(ValueError, match="package_name"):
        ProjectLayout.src(package_name)
