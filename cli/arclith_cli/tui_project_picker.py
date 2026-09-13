from pathlib import Path
from typing import Iterable

from rich.markup import escape
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical
from textual.screen import Screen
from textual.widgets import Button, DirectoryTree, Footer, Header, Input, Static

from arclith_cli.guide_status import find_project_root

_IGNORED_DIRECTORY_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".tox",
        ".venv",
        "__pycache__",
        "node_modules",
    }
)


class ProjectDirectoryTree(DirectoryTree):
    """Directory-only browser that omits generated and dependency folders."""

    def filter_paths(self, paths: Iterable[Path]) -> Iterable[Path]:
        return (
            path
            for path in paths
            if path.is_dir() and path.name not in _IGNORED_DIRECTORY_NAMES
        )


class ProjectPickerScreen(Screen[Path | None]):
    """Pick and validate an existing Arclith project directory."""

    BINDINGS = [
        ("escape", "cancel", "Annuler"),
        ("enter", "open_project", "Ouvrir"),
    ]

    def __init__(self, start_dir: Path) -> None:
        super().__init__()
        self._start_dir = self._existing_directory(start_dir)
        self._selected_root: Path | None = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Vertical(id="picker-shell"):
            yield Static("OUVRIR UN PROJET", classes="eyebrow")
            yield Static(
                "Parcourez vos dossiers ou saisissez un chemin. "
                "Arclith vérifie la structure avant l’ouverture.",
                classes="lead",
            )
            yield Input(value=str(self._start_dir), id="picker-path")
            with Horizontal(id="picker-toolbar"):
                yield Button("Dossier parent", id="picker-parent")
                yield Button("Afficher ce chemin", id="picker-show")
            yield ProjectDirectoryTree(self._start_dir, id="picker-tree")
            yield Static("", id="picker-status")
            with Horizontal(classes="action-row", id="picker-actions"):
                yield Button("Annuler", id="picker-cancel")
                yield Button(
                    "Ouvrir le projet",
                    id="picker-open",
                    variant="primary",
                    disabled=True,
                )
        yield Footer()

    def on_mount(self) -> None:
        self._validate_path()
        self.query_one("#picker-tree", ProjectDirectoryTree).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "picker-path":
            self._validate_path()

    def on_directory_tree_directory_selected(
        self, event: DirectoryTree.DirectorySelected
    ) -> None:
        self.query_one("#picker-path", Input).value = str(event.path)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "picker-cancel":
            self.action_cancel()
        elif event.button.id == "picker-open":
            self.action_open_project()
        elif event.button.id == "picker-parent":
            self._show_parent()
        elif event.button.id == "picker-show":
            self._show_typed_path()

    def action_cancel(self) -> None:
        self.dismiss(None)

    def action_open_project(self) -> None:
        self._validate_path()
        if self._selected_root is not None:
            self.dismiss(self._selected_root)

    def _validate_path(self) -> None:
        candidate = self._typed_path()
        button = self.query_one("#picker-open", Button)
        status = self.query_one("#picker-status", Static)
        self._selected_root = None
        button.disabled = True
        if not candidate.exists():
            status.update(f"[red]Chemin introuvable : {escape(str(candidate))}[/red]")
            return
        if not candidate.is_dir():
            status.update(
                f"[red]Ce chemin n’est pas un dossier : {escape(str(candidate))}[/red]"
            )
            return
        root = find_project_root(candidate)
        if root is None:
            status.update(
                "[yellow]Aucun projet Arclith détecté dans ce dossier ou ses parents.[/yellow]"
            )
            return
        self._selected_root = root
        button.disabled = False
        status.update(
            f"[green]✓ Projet détecté[/green]  [b]{escape(root.name)}[/b]\n"
            f"[dim]{escape(str(root))}[/dim]"
        )

    def _show_parent(self) -> None:
        tree = self.query_one("#picker-tree", ProjectDirectoryTree)
        parent = Path(tree.path).parent
        tree.path = parent
        self.query_one("#picker-path", Input).value = str(parent)

    def _show_typed_path(self) -> None:
        candidate = self._typed_path()
        if not candidate.exists() or not candidate.is_dir():
            self._validate_path()
            return
        self.query_one("#picker-tree", ProjectDirectoryTree).path = candidate

    def _typed_path(self) -> Path:
        raw = self.query_one("#picker-path", Input).value.strip()
        candidate = Path(raw or str(self._start_dir)).expanduser()
        if not candidate.is_absolute():
            candidate = self._start_dir / candidate
        return candidate.absolute()

    @staticmethod
    def _existing_directory(path: Path) -> Path:
        candidate = path.expanduser().absolute()
        if candidate.is_file():
            return candidate.parent
        if candidate.is_dir():
            return candidate
        for parent in candidate.parents:
            if parent.is_dir():
                return parent
        return Path.cwd().absolute()
