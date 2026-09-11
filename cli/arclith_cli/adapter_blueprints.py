"""Versioned, complete adapter layouts shared by generation and architecture checks.

Every declared extension point is materialized when an adapter is installed.
Developer-owned files are created once: replay fills missing files, never rewrites
implementation. Templates deliberately register no business operation.
"""

from dataclasses import dataclass
from hashlib import sha256
from importlib.resources import files
from pathlib import Path, PurePosixPath
from string import Template

from arclith_cli.capability_models import AdapterSpec
from arclith_cli.project_paths import ProjectPaths

BLUEPRINT_VERSION = "2"


@dataclass(frozen=True)
class AdapterBlueprint:
    """A technology's complete extension points and developer-owned modules."""

    capability: str
    adapter: str
    layer: str
    roles: tuple[str, ...]
    modules: tuple[str, ...]
    reference: str
    version: str = BLUEPRINT_VERSION

    @property
    def directory(self) -> str:
        return self.adapter.replace("-", "_")

    @property
    def root_parts(self) -> tuple[str, ...]:
        if self.layer == "runtime":
            return ("infrastructure", "runtime", self.directory)
        return ("adapters", self.layer, self.directory)


# Capability-level roles are intentionally independent of provider SDK internals.
# A provider may share a directory (e.g. memory repository and memory cache); the
# role sets are additive and no existing implementation is replaced.
_PROFILES: dict[str, tuple[tuple[str, ...], tuple[str, ...]]] = {
    "repository": (
        ("repositories", "models", "mappers", "indexes", "migrations"),
        ("dependencies", "errors"),
    ),
    "storage": (
        ("transfers", "metadata", "policies"),
        ("client", "dependencies", "errors"),
    ),
    "vector-store": (
        ("collections", "mappers", "indexes", "migrations"),
        ("client", "dependencies", "errors"),
    ),
    "cache": (
        ("codecs", "keys", "invalidation", "locks"),
        ("client", "dependencies", "errors"),
    ),
    "logger": (("formatters", "filters", "sinks"), ("setup", "correlation")),
    "secrets": (
        ("resolvers", "rotation", "policies"),
        ("provider", "settings", "errors"),
    ),
    "api": (
        ("middleware", "contracts", "routers", "routers/v1"),
        ("register", "dependencies", "errors", "routers/v1/router"),
    ),
    "mcp": (
        ("middleware", "contracts", "features"),
        ("register", "dependencies", "errors"),
    ),
    "probe": (
        ("checks", "diagnostics"),
        ("register", "health", "readiness", "dependencies"),
    ),
    "http": (
        ("middleware", "policies", "schemas"),
        ("register", "dependencies", "errors"),
    ),
    "command-bus": (
        ("bindings", "contracts", "schemas", "policies"),
        ("register", "codec", "topology", "consumer", "publisher", "dependencies"),
    ),
    "channel": (
        (
            "inbound",
            "outbound",
            "schemas",
            "mappers",
            "presenters",
            "attachments",
            "policies",
        ),
        ("register", "client", "dependencies", "security", "errors"),
    ),
    "runtime": (("bootstrap", "health", "policies"), ("settings", "lifecycle")),
    "auth": (("principals", "mappers", "policies"), ("dependencies", "errors")),
    "tenant": (
        ("resolvers", "mappers", "policies"),
        ("dependencies", "context", "errors"),
    ),
    "license": (("mappers", "policies"), ("dependencies", "errors")),
    "llm": (("models", "mappers", "policies"), ("client", "dependencies", "errors")),
    "embedding": (
        ("models", "mappers", "batching", "policies"),
        ("client", "dependencies", "errors"),
    ),
    "agent": (
        (
            "nodes",
            "contracts",
            "capabilities",
            "subgraphs",
            "tools",
            "prompts",
            "parsers",
            "presenters",
            "policies",
            "persistence",
            "shared",
        ),
        ("agent", "graph", "state", "context", "dependencies", "routing"),
    ),
    "agent-persistence": (
        (
            "persistence",
            "persistence/checkpoints",
            "persistence/stores",
            "persistence/migrations",
        ),
        (),
    ),
    "observability": (
        ("instrumentation", "exporters", "sampling"),
        ("setup", "correlation", "dependencies"),
    ),
}

_REFERENCES = {
    "api": "https://fastapi.tiangolo.com/tutorial/bigger-applications/",
    "mcp": "https://gofastmcp.com/servers/composition",
    "agent": "https://docs.langchain.com/oss/python/langgraph/application-structure",
    "agent-persistence": "https://docs.langchain.com/oss/python/langgraph/persistence",
    "command-bus": "https://www.rabbitmq.com/docs/reliability",
}

_ROLE_GUIDANCE = {
    "nodes": "Thin state-to-application adapters. Return patches; inject services through composition closures. Public context contains only serializable invocation values.",
    "capabilities": "Group one conversational capability per package: intents, workflow, mapping and presentation.",
    "subgraphs": "Only compiled multi-node graphs with an explicit state and lifecycle belong here.",
    "tools": "One cohesive tool or tool family per module. Translate input into a typed application request.",
    "resources": "Read-only MCP resources and resource templates. Keep public URIs stable.",
    "prompts": "Versioned transport-owned prompt templates; application prompts stay in application.",
    "persistence": "Runtime checkpoints and stores, separate from domain persistence. Version persisted state.",
    "shared": "Only primitives used by at least two capabilities. Avoid generic helpers or utils modules.",
    "routers": "Explicit APIRouter composition by API version and feature. Declare status_code and responses.",
    "middleware": "Transport-wide request concerns. Keep business policies in application or domain.",
    "bindings": "Decode and validate the wire message, then invoke the same typed application port as other transports.",
    "repositories": "Implement outbound ports. Keep queries in the port contract and SDK types inside this adapter.",
    "mappers": "Pure translation functions between transport/provider models and application contracts.",
    "presenters": "Render application results without making business decisions or performing I/O.",
    "policies": "Technical retry, timeout and idempotency policies. Retry only safe/idempotent operations.",
    "migrations": "Explicit version-to-version migrations. Preserve compatibility with already persisted data.",
    "models": "Provider-owned persistence models only; never duplicate the domain entity here without a mapping need.",
    "indexes": "Provider index declarations and reconciliation code; keep query intent in an outbound port.",
    "contracts": "Versioned wire contracts and pure mappings around typed application requests and results.",
    "schemas": "Provider or wire schemas only. Domain validation stays in domain/application models.",
    "features": "One public transport feature per package. Create it through expose-usecase, never by inference.",
    "dependencies": "Transport/provider dependency factories. Concrete assembly remains in infrastructure.",
    "errors": "Translate provider or transport failures at the hexagonal boundary; do not define business errors here.",
    "codec": "Encode and decode the versioned wire envelope without business decisions.",
    "topology": "Declare exchanges, queues and routing keys separately from message handlers.",
    "consumer": "Compose broker consumption with generated bindings; acknowledgement remains framework-owned.",
    "publisher": "Implement outbound publication behind an application port; preserve correlation and trace context.",
}


def get_adapter_blueprint(adapter: AdapterSpec) -> AdapterBlueprint:
    """Fail closed if a new catalog capability has no declared layout."""
    if adapter.capability not in _PROFILES:
        raise ValueError(f"No adapter blueprint for capability {adapter.capability!r}")
    roles, modules = _PROFILES[adapter.capability]
    return AdapterBlueprint(
        capability=adapter.capability,
        adapter=adapter.name,
        layer=adapter.layer,
        roles=roles,
        modules=modules,
        reference=_REFERENCES.get(
            adapter.capability, "https://karned-rekipe.github.io/arclith/capabilities/"
        ),
    )


def _module_guide(role: str) -> str:
    return _ROLE_GUIDANCE.get(
        role,
        f"Keep cohesive {role.replace('_', ' ')} responsibilities in named modules.",
    )


def _package_files(role: str, reference: str) -> dict[str, str]:
    return {
        f"{role}/__init__.py": '"""Developer-owned extension point; explicit imports only."""\n',
        f"{role}/README.md": (
            f"# {role}\n\n{_module_guide(PurePosixPath(role).name)}\n\n"
            "This package is created immediately by Arclith. Add named modules here; "
            "do not move this responsibility to a global `utils.py` or `nodes.py`.\n\n"
            f"[Reference]({reference}). Files are developer-owned and preserved on replay.\n"
        ),
    }


def _template(name: str, variables: dict[str, str]) -> str:
    source = (
        files("arclith_cli")
        .joinpath("templates", "adapters", name)
        .read_text(encoding="utf-8")
    )
    return Template(source).substitute(variables)


def render_feature_blueprint(
    kind: str, feature: str, package_name: str
) -> dict[str, str]:
    """Render the canonical feature package required by one public binding.

    ``kind`` accepts FastAPI/FastMCP names or their capability names. Only the
    requested feature is created; no entity or example feature is inferred.
    """
    if not feature.isidentifier() or feature.startswith("_"):
        raise ValueError("feature must be a public Python identifier")
    roles: tuple[str, ...]
    modules: tuple[str, ...]
    if kind in {"api", "fastapi"}:
        base = f"routers/v1/{feature}"
        roles = ("routes",)
        modules = ("router", "schemas", "mappers", "presenters", "openapi")
        reference = _REFERENCES["api"]
    elif kind in {"mcp", "fastmcp"}:
        base = f"features/{feature}"
        roles = ("tools", "resources", "prompts")
        modules = ("register", "schemas", "mappers", "presenters")
        reference = _REFERENCES["mcp"]
    else:
        raise ValueError(f"Unsupported feature blueprint {kind!r}")
    result = _package_files(base, reference)
    for role in roles:
        result.update(_package_files(f"{base}/{role}", reference))
    for module in modules:
        result[f"{base}/{module}.py"] = f'"""{feature}: {_module_guide(module)}"""\n'
    if kind in {"api", "fastapi"}:
        result[f"{base}/router.py"] += (
            "\nfrom fastapi import APIRouter\n\n\n"
            "def build_router() -> APIRouter:\n"
            f'    return APIRouter(tags=["{feature}"])\n'
        )
    return result


def render_adapter_blueprint(
    blueprint: AdapterBlueprint,
    package_name: str,
    features: tuple[str, ...] = (),
    *,
    graph_name: str = "agent",
) -> dict[str, str]:
    """Render the complete file contract relative to ``blueprint.root_parts``."""
    result = {
        "__init__.py": '"""Project-specific adapter; dependencies are supplied by the composition root."""\n'
    }
    for role in blueprint.roles:
        result.update(_package_files(role, blueprint.reference))
    for module in blueprint.modules:
        result[f"{module}.py"] = (
            f'"""{_module_guide(PurePosixPath(module).name)} See README.md."""\n'
        )
    prefix = (
        ".".join((package_name, *blueprint.root_parts))
        if package_name
        else ".".join(blueprint.root_parts)
    )
    variables = {
        "adapter_import": prefix,
        "package_name": package_name,
        "composition_import": (
            f"{package_name}.infrastructure.use_cases_generated"
            if package_name
            else "infrastructure.use_cases_generated"
        ),
        "graph_name": graph_name,
    }
    templates: dict[str, tuple[str, ...]] = {
        "api": ("register", "routers/v1/router"),
        "mcp": ("register",),
        "agent": (
            "agent",
            "graph",
            "state",
            "context",
            "dependencies",
            "nodes/example",
        ),
        "command-bus": ("register", "consumer"),
    }
    for module in templates.get(blueprint.capability, ()):
        result[f"{module}.py"] = _template(
            f"{blueprint.capability}/{module}.py.tmpl", variables
        )
    if blueprint.capability in {"api", "mcp", "command-bus"}:
        result["bindings_generated.py"] = _empty_binding_registry(blueprint.capability)
    layout = "\n".join(f"- `{name}`" for name in sorted(result))
    boundaries = {
        "inbound": "Input -> transport mapper -> typed application Command/Query -> inbound port -> Result -> presenter. Do not import concrete outbound adapters here.",
        "outbound": "Implement the application's outbound port. Keep provider SDK types and persistence mappings inside this adapter; business rules stay in application/domain.",
        "bidirectional": "Separate inbound decoding/validation from outbound publishing. Inbound messages invoke typed application ports; outbound messages implement outbound ports.",
        "runtime": "Assemble application dependencies and manage process startup/shutdown. Runtime configuration does not contain business rules.",
    }
    implementation_note = (
        "Arclith already provides the standard repository implementation. "
        "The generated composition root selects it through `arclith.repository(Entity)`. "
        "Add a project-owned repository module only when an explicit outbound port "
        "requires a provider-specific implementation.\n\n"
        if blueprint.capability == "repository"
        else ""
    )
    result["README.md"] = (
        f"# {blueprint.adapter} adapter\n\nBlueprint version: `{blueprint.version}`.\n\n"
        "This is the canonical, closed extension-point layout for the selected technology. "
        "Do not create parallel `utils.py`, `helpers.py`, transport or provider trees. "
        "Business features are created only with `arclith-cli expose-usecase`.\n\n"
        f"{boundaries[blueprint.layer]} Domain logic belongs to the application/domain.\n\n"
        f"{implementation_note}"
        "Each package README defines what belongs there. Placeholder modules are guidance and may be "
        "implemented when that responsibility is actually needed. Files are developer-owned: rerunning "
        "the scaffold fills missing files and preserves existing code. "
        "Do not register components through import side effects in `__init__.py`.\n\n"
        f"[Official reference]({blueprint.reference}).\n\n## Allowed layout\n\n{layout}\n"
    )
    return result


def _empty_binding_registry(capability: str) -> str:
    imports = {
        "api": "from fastapi import APIRouter",
        "mcp": "from typing import Any\n\nfrom fastmcp import FastMCP",
        "command-bus": (
            "from arclith.application.command_bus import CommandDispatcher"
        ),
    }
    target = {
        "api": "APIRouter",
        "mcp": "FastMCP[Any]",
        "command-bus": "CommandDispatcher",
    }
    return (
        "# Generated by arclith-cli expose-usecase; edit the binding modules instead.\n"
        "from __future__ import annotations\n\n"
        f"{imports[capability]}\n\n\n"
        f"def register(_target: {target[capability]}, _use_cases: object) -> None:\n"
        '    """No public operation is exposed until expose-usecase is run."""\n'
    )


def blueprint_digest(blueprint: AdapterBlueprint) -> str:
    """Digest the template contract, independent of project/feature names."""
    rendered = render_adapter_blueprint(blueprint, "application_package")
    payload = "\n".join(
        f"{path}\0{content}" for path, content in sorted(rendered.items())
    )
    return "sha256:" + sha256(payload.encode("utf-8")).hexdigest()


def write_missing_files(root: Path, rendered: dict[str, str]) -> tuple[Path, ...]:
    """Create developer-owned files once. Reject paths outside the declared root."""
    created: list[Path] = []
    for relative, content in rendered.items():
        relative_path = PurePosixPath(relative)
        if relative_path.is_absolute() or ".." in relative_path.parts:
            raise ValueError(f"Unsafe blueprint path: {relative}")
        path = root / relative
        if path.exists():
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        created.append(path)
    return tuple(created)


def assert_no_module_shadowing(root: Path, blueprint: AdapterBlueprint) -> None:
    """Do not silently hide a legacy nodes.py/router.py behind a new package."""
    conflicts = [
        str(root / f"{role}.py")
        for role in blueprint.roles
        if (root / f"{role}.py").is_file()
        and not (root / role / "__init__.py").exists()
    ]
    if conflicts:
        raise ValueError(
            "Migrate legacy modules before creating packages with the same import name: "
            + ", ".join(conflicts)
        )


def scaffold_adapter_blueprint(
    project_dir: Path,
    paths: ProjectPaths,
    adapter: AdapterSpec,
    *,
    graph_name: str = "agent",
) -> tuple[Path, ...]:
    """Install the selected technology's full layout and native feature roles."""
    blueprint = get_adapter_blueprint(adapter)
    root = paths.package_root.joinpath(*blueprint.root_parts)
    assert_no_module_shadowing(root, blueprint)
    rendered = render_adapter_blueprint(
        blueprint, paths.package_name or "", graph_name=graph_name
    )
    created = write_missing_files(root, rendered)
    # Metadata is template provenance, not a claim that edited code matches it.
    metadata = {
        f"{adapter.capability}-{adapter.name}.yaml": (
            f"blueprint_version: {blueprint.version!r}\n"
            f"template_digest: {blueprint_digest(blueprint)!r}\n"
            f"capability: {adapter.capability}\nadapter: {adapter.name}\n"
            "ownership: developer\n"
            "contract: closed\n"
            "expected_paths:\n"
            + "".join(f"  - {path!r}\n" for path in sorted(rendered))
        )
    }
    write_missing_files(project_dir / ".arclith" / "blueprints", metadata)
    return created


def validate_adapter_blueprint(
    root: Path, blueprint: AdapterBlueprint
) -> tuple[str, ...]:
    """Return missing native files; feature names remain project-specific."""
    expected = {"__init__.py", "README.md"}
    expected.update(f"{module}.py" for module in blueprint.modules)
    for role in blueprint.roles:
        expected.update((f"{role}/__init__.py", f"{role}/README.md"))
    return tuple(sorted(path for path in expected if not (root / path).is_file()))
