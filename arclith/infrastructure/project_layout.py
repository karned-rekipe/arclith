from dataclasses import dataclass, field
from enum import StrEnum
from pathlib import PurePosixPath
import re


_PACKAGE_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")


class ProjectLayoutKind(StrEnum):
    """Supported Arclith project layouts."""

    SRC = "src"


@dataclass(frozen=True, slots=True)
class ProjectLayout:
    """Canonical folder contract for services built on Arclith."""

    package_name: str
    kind: ProjectLayoutKind = ProjectLayoutKind.SRC
    source_root: PurePosixPath = PurePosixPath("src")
    tests_root: PurePosixPath = PurePosixPath("tests")
    config_root: PurePosixPath = PurePosixPath("config")
    entrypoint: PurePosixPath = PurePosixPath("main.py")
    package_root: PurePosixPath = field(init=False)
    domain: PurePosixPath = field(init=False)
    domain_models: PurePosixPath = field(init=False)
    domain_ports: PurePosixPath = field(init=False)
    inbound_ports: PurePosixPath = field(init=False)
    outbound_ports: PurePosixPath = field(init=False)
    application: PurePosixPath = field(init=False)
    application_use_cases: PurePosixPath = field(init=False)
    application_services: PurePosixPath = field(init=False)
    adapters: PurePosixPath = field(init=False)
    inbound_adapters: PurePosixPath = field(init=False)
    outbound_adapters: PurePosixPath = field(init=False)
    legacy_input_adapters: PurePosixPath = field(init=False)
    legacy_output_adapters: PurePosixPath = field(init=False)
    infrastructure: PurePosixPath = field(init=False)

    def __post_init__(self) -> None:
        if self.kind is not ProjectLayoutKind.SRC:
            raise ValueError(f"Unsupported Arclith project layout: {self.kind}")
        if not _PACKAGE_NAME_PATTERN.fullmatch(self.package_name):
            raise ValueError(
                "package_name must be a valid lowercase Python package name "
                "(example: arclith_sample)"
            )

        package_root = self.source_root / self.package_name
        object.__setattr__(self, "package_root", package_root)
        object.__setattr__(self, "domain", package_root / "domain")
        object.__setattr__(self, "domain_models", package_root / "domain" / "models")
        object.__setattr__(self, "domain_ports", package_root / "domain" / "ports")
        object.__setattr__(self, "inbound_ports", package_root / "domain" / "ports" / "inbound")
        object.__setattr__(self, "outbound_ports", package_root / "domain" / "ports" / "outbound")
        object.__setattr__(self, "application", package_root / "application")
        object.__setattr__(
            self,
            "application_use_cases",
            package_root / "application" / "use_cases",
        )
        object.__setattr__(
            self,
            "application_services",
            package_root / "application" / "services",
        )
        object.__setattr__(self, "adapters", package_root / "adapters")
        object.__setattr__(self, "inbound_adapters", package_root / "adapters" / "inbound")
        object.__setattr__(self, "outbound_adapters", package_root / "adapters" / "outbound")
        object.__setattr__(self, "legacy_input_adapters", package_root / "adapters" / "input")
        object.__setattr__(self, "legacy_output_adapters", package_root / "adapters" / "output")
        object.__setattr__(self, "infrastructure", package_root / "infrastructure")

    @classmethod
    def src(
        cls,
        package_name: str,
        *,
        source_root: str | PurePosixPath = "src",
        tests_root: str | PurePosixPath = "tests",
        config_root: str | PurePosixPath = "config",
        entrypoint: str | PurePosixPath = "main.py",
    ) -> "ProjectLayout":
        """Build the recommended namespaced `src/<package>/...` service layout."""
        return cls(
            package_name=package_name,
            kind=ProjectLayoutKind.SRC,
            source_root=PurePosixPath(source_root),
            tests_root=PurePosixPath(tests_root),
            config_root=PurePosixPath(config_root),
            entrypoint=PurePosixPath(entrypoint),
        )

    def layer_paths(self) -> dict[str, PurePosixPath]:
        """Return the four hexagonal layers keyed by conventional layer name."""
        return {
            "domain": self.domain,
            "application": self.application,
            "adapters": self.adapters,
            "infrastructure": self.infrastructure,
        }

    def port_paths(self) -> dict[str, PurePosixPath]:
        """Return canonical inbound/outbound port folders.

        Inbound ports model use cases offered by the core. Outbound ports model dependencies the
        core needs from the outside world, such as repositories, event buses, LLMs, or mailers.
        """
        return {
            "inbound": self.inbound_ports,
            "outbound": self.outbound_ports,
        }

    def adapter_paths(self) -> dict[str, PurePosixPath]:
        """Return canonical inbound/outbound adapter folders."""
        return {
            "inbound": self.inbound_adapters,
            "outbound": self.outbound_adapters,
        }

    def package_paths(self) -> tuple[PurePosixPath, ...]:
        """Return importable package paths expected in the built wheel."""
        return (self.package_root,)

    def import_path(self, *parts: str) -> str:
        """Return a dotted import path inside the application package."""
        return ".".join((self.package_name, *parts))


def canonical_project_layout(package_name: str) -> ProjectLayout:
    """Return the current recommended Arclith layout for an application package."""
    return ProjectLayout.src(package_name)
