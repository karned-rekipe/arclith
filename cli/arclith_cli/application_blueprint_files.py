from pathlib import Path

from arclith_cli.project_paths import ProjectPaths


def with_package_initializers(
    paths: ProjectPaths,
    files: dict[Path, str],
) -> dict[Path, str]:
    """Add missing package initializers to one rendered blueprint plan."""

    result = dict(files)
    for path in tuple(files):
        for parent in path.parents:
            if parent in {paths.root, paths.package_root.parent}:
                break
            if parent.is_relative_to(paths.package_root) or parent.is_relative_to(
                paths.root / "tests"
            ):
                result.setdefault(parent / "__init__.py", "")
    return result
