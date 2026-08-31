from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console
from rich.prompt import Prompt

from arclith_cli.adapter_config import ARCLITH_DEPENDENCY_RE, read_yaml_mapping
from arclith_cli.capabilities import (
    AdapterSpec,
    CapabilitySpec,
    capability_names,
    get_capability,
)
from arclith_cli.entity_scanner import EntityInfo, scan_entities
from arclith_cli.project_paths import detect_project_paths

console = Console()


def _assert_arclith_project(project_dir: Path) -> None:
    paths = detect_project_paths(project_dir)
    if not paths.domain_models.exists():
        console.print(
            "[red]✗[/red] Aucun dossier [bold]domain/models[/bold] ou [bold]src/<package>/domain/models[/bold] trouvé.\n"
            "    Exécutez [bold]arclith-cli add-adapter[/bold] depuis la racine d'un projet arclith."
        )
        raise typer.Exit(1)
    if not (project_dir / "config" / "adapters").exists():
        console.print(
            "[red]✗[/red] Aucun dossier [bold]config/adapters/[/bold] trouvé.\n"
            "    Le projet doit utiliser la structure [bold]config/[/bold] directory."
        )
        raise typer.Exit(1)


def _assert_capability_prerequisites(
    project_dir: Path,
    adapter: AdapterSpec,
) -> None:
    if adapter.capability != "agent-persistence":
        return
    langgraph_config = (
        project_dir / "config" / "adapters" / "inbound" / "langgraph.yaml"
    )
    existing = read_yaml_mapping(langgraph_config)
    if not isinstance(existing.get("entrypoint"), str):
        console.print(
            "[red]✗[/red] La capability [bold]agent-persistence[/bold] complete "
            "[bold]agent/langgraph[/bold]. Generez d'abord cet adapter."
        )
        raise typer.Exit(1)
    pyproject = project_dir / "pyproject.toml"
    text = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
    if ARCLITH_DEPENDENCY_RE.search(text):
        return
    console.print(
        "[red]✗[/red] Impossible d'ajouter les extras de persistance: "
        "dependance [bold]arclith[/bold] absente de pyproject.toml."
    )
    raise typer.Exit(1)


# ── Step 1 : adapter type ─────────────────────────────────────────────────────


def _resolve_capability(capability_name: str) -> CapabilitySpec:
    capability = get_capability(capability_name)
    if capability is not None:
        return capability

    supported = ", ".join(capability_names())
    console.print(
        f"[red]✗[/red] Capacité inconnue: [bold]{capability_name}[/bold]. Valeurs: {supported}."
    )
    raise typer.Exit(1)


def _prompt_adapter_type(capability: CapabilitySpec) -> AdapterSpec:
    console.print("\n[bold]① Type d'adapter[/bold]")
    adapter_names = capability.adapter_names()
    for i, name in enumerate(adapter_names, 1):
        console.print(f"   [bold cyan]{i}[/bold cyan]  {name}")

    while True:
        raw = Prompt.ask("\n  Votre choix [dim](numéro ou nom)[/dim]").strip()
        if raw.isdigit():
            idx = int(raw) - 1
            if 0 <= idx < len(adapter_names):
                selected = capability.get_adapter(adapter_names[idx])
                if selected is not None:
                    return selected
        else:
            selected = capability.get_adapter(raw)
            if selected is not None:
                return selected
        console.print(
            f"  [red]Choix invalide.[/red] Entrez 1-{len(adapter_names)} ou le nom."
        )


def _resolve_adapter_type(
    capability: CapabilitySpec, adapter: str | None
) -> AdapterSpec:
    if adapter is None:
        return _prompt_adapter_type(capability)

    selected = capability.get_adapter(adapter)
    if selected is not None:
        return selected

    supported = ", ".join(capability.adapter_names())
    console.print(
        f"[red]✗[/red] Adapter inconnu: [bold]{adapter}[/bold]. Valeurs: {supported}."
    )
    raise typer.Exit(1)


def _resolve_profile(
    adapter: AdapterSpec, profile: str | None
) -> dict[str, str | bool]:
    if profile is None:
        return {}
    selected = adapter.get_profile(profile)
    if selected is not None:
        return selected.values()
    allowed = ", ".join(item.name for item in adapter.profiles) or "(aucun)"
    console.print(
        f"[red]✗[/red] Profil inconnu pour [bold]{adapter.name}[/bold]: {profile}. "
        f"Valeurs: {allowed}."
    )
    raise typer.Exit(1)


# ── Step 2 : entity selection ─────────────────────────────────────────────────


def _prompt_entities(project_dir: Path) -> list[EntityInfo]:
    entities = scan_entities(project_dir)
    if not entities:
        console.print(
            "[red]✗[/red] Aucune entité trouvée dans [bold]src/<package>/domain/models/[/bold]."
        )
        raise typer.Exit(1)

    console.print("\n[bold]② Entité(s) cible(s)[/bold]")
    for i, e in enumerate(entities, 1):
        console.print(
            f"   [bold cyan]{i}[/bold cyan]  {e.pascal} [dim]({e.snake})[/dim]"
        )
    console.print(
        f"   [bold cyan]{len(entities) + 1}[/bold cyan]  [italic]toutes[/italic]"
    )

    while True:
        raw = Prompt.ask(
            "\n  Votre choix [dim](numéro(s) séparés par virgule, ou nom)[/dim]"
        ).strip()
        selected = _parse_entity_choice(raw, entities)
        if selected is not None:
            return selected
        console.print("  [red]Choix invalide.[/red]")


def _resolve_entities(
    project_dir: Path,
    entity_names: list[str] | None,
    all_entities: bool,
    *,
    yes: bool,
    adapter: AdapterSpec,
) -> list[EntityInfo]:
    if not adapter.entity_scoped:
        if all_entities or entity_names:
            console.print(
                f"[red]✗[/red] L'adapter [bold]{adapter.name}[/bold] n'est pas lié aux entités. "
                "Retirez [bold]--entity[/bold] et [bold]--all-entities[/bold]."
            )
            raise typer.Exit(1)
        return []

    entities = scan_entities(project_dir)
    if not entities:
        console.print(
            "[red]✗[/red] Aucune entité trouvée dans [bold]src/<package>/domain/models/[/bold]."
        )
        raise typer.Exit(1)

    if all_entities:
        return list(entities)

    if entity_names:
        selected = _parse_entity_choice(",".join(entity_names), entities)
        if selected is not None:
            return selected
        allowed = ", ".join(e.pascal for e in entities)
        console.print(f"[red]✗[/red] Entité inconnue. Valeurs: {allowed}.")
        raise typer.Exit(1)

    if len(entities) == 1:
        return [entities[0]]

    if yes:
        console.print(
            "[red]✗[/red] Plusieurs entités détectées. Utilisez [bold]--entity[/bold] ou [bold]--all-entities[/bold]."
        )
        raise typer.Exit(1)

    return _prompt_entities(project_dir)


def _parse_entity_choice(
    raw: str, entities: list[EntityInfo]
) -> list[EntityInfo] | None:
    all_idx = len(entities) + 1
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    result: list[EntityInfo] = []
    for part in parts:
        if part.isdigit():
            idx = int(part)
            if idx == all_idx:
                return list(entities)
            if 1 <= idx <= len(entities):
                e = entities[idx - 1]
                if e not in result:
                    result.append(e)
            else:
                return None
        else:
            matched = [e for e in entities if e.pascal == part or e.snake == part]
            if not matched:
                return None
            for e in matched:
                if e not in result:
                    result.append(e)
    return result or None


# ── Step 3 : adapter-specific params ─────────────────────────────────────────
