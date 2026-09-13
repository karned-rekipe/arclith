import shlex
from dataclasses import dataclass
from pathlib import Path

from arclith_cli.adapter_config import read_yaml_mapping
from arclith_cli.capabilities import CAPABILITY_CATALOG
from arclith_cli.capability_models import AdapterSpec, CapabilitySpec


@dataclass(frozen=True)
class AdapterInstallRequest:
    """A validated adapter installation assembled by the TUI."""

    project_root: Path
    capability: CapabilitySpec
    adapter: AdapterSpec
    parameters: tuple[tuple[str, str], ...]
    profile: str | None
    activate: bool

    def command(self) -> str:
        """Render the equivalent direct command without exposing secrets."""
        secret_names = {
            parameter.name for parameter in self.adapter.parameters if parameter.secret
        }
        argv = [
            "arclith-cli",
            "add-adapter",
            "--capability",
            self.capability.name,
            "--adapter",
            self.adapter.name,
        ]
        if self.profile is not None:
            argv.extend(("--profile", self.profile))
        for name, value in self.parameters:
            displayed = "<redacted>" if name in secret_names else value
            argv.extend(("--param", f"{name}={displayed}"))
        if self.capability.activation_config_key is not None:
            argv.append("--activate" if self.activate else "--no-activate")
        argv.append("--yes")
        return f"cd {shlex.quote(str(self.project_root))}\n{shlex.join(argv)}"


def available_capabilities(installed: frozenset[str]) -> tuple[CapabilitySpec, ...]:
    """Return capabilities for which at least one adapter remains installable."""
    return tuple(
        capability
        for capability in CAPABILITY_CATALOG
        if available_adapters(capability, installed)
    )


def available_adapters(
    capability: CapabilitySpec,
    installed: frozenset[str],
) -> tuple[AdapterSpec, ...]:
    """Return adapters not already represented by a project manifest."""
    return tuple(
        adapter
        for adapter in capability.adapters
        if f"{capability.name}/{adapter.name}" not in installed
    )


def default_activation(
    capability: CapabilitySpec,
    active: frozenset[str],
) -> bool:
    """Avoid replacing an active adapter while allowing parallel observability."""
    if capability.activation_config_key is None:
        return False
    if capability.name == "observability":
        return True
    return not any(item.startswith(f"{capability.name}/") for item in active)


def active_adapters(project_root: Path) -> frozenset[str]:
    """Read active provider selections, including defaults without manifests."""
    raw = read_yaml_mapping(project_root / "config" / "adapters" / "adapters.yaml")
    active: set[str] = set()
    for capability in CAPABILITY_CATALOG:
        key = capability.activation_config_key
        if key is None:
            continue
        value = raw.get(key)
        if capability.name == "observability":
            if not isinstance(value, dict):
                continue
            enabled = value.get("enabled")
            if isinstance(enabled, list):
                active.update(
                    f"{capability.name}/{adapter}"
                    for adapter in enabled
                    if isinstance(adapter, str) and adapter.strip()
                )
        elif isinstance(value, str) and value.strip():
            active.add(f"{capability.name}/{value.strip()}")
    return frozenset(active)


def configuration_replacements(
    adapter: AdapterSpec,
    installed: frozenset[str],
) -> tuple[str, ...]:
    """Identify installed adapters whose single-provider config will be replaced."""
    if adapter.config_path is None:
        return ()
    return tuple(
        f"{capability.name}/{installed_adapter.name}"
        for capability in CAPABILITY_CATALOG
        for installed_adapter in capability.adapters
        if f"{capability.name}/{installed_adapter.name}" in installed
        and installed_adapter.config_path == adapter.config_path
    )
