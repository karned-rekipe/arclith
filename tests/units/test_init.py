import pytest

import arclith


def test_getattr_console_logger():
    cls = arclith.ConsoleLogger
    from arclith.adapters.outbound.console.logger import ConsoleLogger
    assert cls is ConsoleLogger


def test_getattr_unknown_raises():
    with pytest.raises(AttributeError):
        _ = arclith.NonExistentSymbol  # type: ignore[attr-defined]


def test_public_project_layout_exports():
    layout = arclith.canonical_project_layout("arclith_sample")

    assert isinstance(layout, arclith.ProjectLayout)
    assert layout.kind is arclith.ProjectLayoutKind.SRC


def test_public_repository_registry_exports():
    registry = arclith.default_repository_registry(arclith.Entity)

    assert isinstance(registry, arclith.RepositoryRegistry)
    assert arclith.build_repository is not None
