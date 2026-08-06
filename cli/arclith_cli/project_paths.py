from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ProjectPaths:
    root: Path
    package_root: Path
    package_name: str | None

    @property
    def domain_models(self) -> Path:
        return self.package_root / "domain" / "models"

    @property
    def application_use_cases(self) -> Path:
        return self.package_root / "application" / "use_cases"

    @property
    def application_planners(self) -> Path:
        return self.package_root / "application" / "planners"

    @property
    def adapters_outbound(self) -> Path:
        return self.package_root / "adapters" / "outbound"

    @property
    def adapters_inbound(self) -> Path:
        return self.package_root / "adapters" / "inbound"

    @property
    def containers(self) -> Path:
        return self.package_root / "infrastructure" / "containers"

    def import_path(self, *parts: str) -> str:
        prefix = (self.package_name,) if self.package_name else ()
        return ".".join((*prefix, *parts))


def detect_project_paths(project_dir: Path) -> ProjectPaths:
    """Detect the importable application package for an Arclith project."""
    src_dir = project_dir / "src"
    if src_dir.exists():
        model_candidates = sorted(
            child
            for child in src_dir.iterdir()
            if child.is_dir() and (child / "domain" / "models").exists()
        )
        if model_candidates:
            package_root = model_candidates[0]
            return ProjectPaths(root=project_dir, package_root=package_root, package_name=package_root.name)

        package_candidates = sorted(
            child
            for child in src_dir.iterdir()
            if child.is_dir() and _looks_like_package_root(child)
        )
        if package_candidates:
            package_root = package_candidates[0]
            return ProjectPaths(root=project_dir, package_root=package_root, package_name=package_root.name)

    return ProjectPaths(root=project_dir, package_root=project_dir, package_name=None)


def _looks_like_package_root(path: Path) -> bool:
    if (path / "__init__.py").exists():
        return True

    return any((path / layer).is_dir() for layer in ("domain", "application", "adapters", "infrastructure"))
