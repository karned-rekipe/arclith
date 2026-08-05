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
        candidates = sorted(
            child
            for child in src_dir.iterdir()
            if child.is_dir() and (child / "domain" / "models").exists()
        )
        if candidates:
            package_root = candidates[0]
            return ProjectPaths(root=project_dir, package_root=package_root, package_name=package_root.name)

    return ProjectPaths(root=project_dir, package_root=project_dir, package_name=None)
