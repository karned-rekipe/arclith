from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    ProgressBar,
    Select,
    Static,
)

from arclith_cli.guide_models import ProjectIntent, RepositoryChoice

WIZARD_STEPS = (
    ("Intention", "Choisir le résultat attendu"),
    ("Domaine", "Nommer le projet et son premier comportement"),
    ("Stockage", "Choisir explicitement la persistance"),
    ("Transport", "Configurer l’entrée du service"),
    ("Vérification", "Relire le plan avant génération"),
)
WIZARD_PAGE_IDS = (
    "step-intent",
    "step-domain",
    "step-storage",
    "step-transport",
    "step-review",
)

_INTENT_OPTIONS = (
    ("API REST CRUD", ProjectIntent.API_CRUD.value),
    ("API REST sur mesure", ProjectIntent.API_CUSTOM.value),
    ("Serveur MCP", ProjectIntent.MCP.value),
    ("Agent LangGraph", ProjectIntent.AGENT.value),
    ("Worker RabbitMQ", ProjectIntent.WORKER.value),
    ("Socle minimal", ProjectIntent.MINIMAL.value),
)
_REPOSITORY_OPTIONS = (
    ("Mémoire — rapide et non persistant", RepositoryChoice.MEMORY.value),
    ("MongoDB — documentaire asynchrone", RepositoryChoice.MONGODB.value),
    ("PostgreSQL — JSONB et transactions", RepositoryChoice.POSTGRESQL.value),
)


def compose_project_wizard(parent_dir: Path) -> ComposeResult:
    """Compose the wizard without coupling its layout to navigation logic."""
    yield Header(show_clock=True)
    with Horizontal(id="wizard-shell"):
        with Vertical(id="wizard-sidebar"):
            yield Label("NOUVEAU PROJET", classes="section-title")
            for index, (label, _description) in enumerate(WIZARD_STEPS):
                yield Static(
                    f"○  {label}",
                    id=f"wizard-step-{index}",
                    classes="wizard-step",
                )
            yield Static(
                "Le plan est calculé par le même moteur que les commandes directes.",
                id="wizard-note",
            )
        with Vertical(id="wizard-main"):
            with VerticalScroll(id="wizard-form"):
                yield Static("CRÉATION GUIDÉE", classes="eyebrow")
                yield Label("", id="wizard-title")
                yield Static("", id="wizard-description", classes="lead")
                with Vertical(id="step-intent", classes="wizard-page"):
                    yield Label("Résultat attendu", classes="field-label")
                    yield Select(
                        _INTENT_OPTIONS,
                        value=ProjectIntent.API_CRUD.value,
                        allow_blank=False,
                        id="intent",
                    )
                    yield Static(
                        "Entrée ou espace ouvre la liste · ↑↓ sélectionne.",
                        classes="field-help",
                    )
                with Vertical(id="step-domain", classes="wizard-page"):
                    yield Label("Répertoire parent", classes="field-label")
                    yield Input(value=str(parent_dir), id="parent-dir")
                    yield Label("Nom du projet", classes="field-label")
                    yield Input(value="catalog-service", id="project-name")
                    with Vertical(id="entity-field", classes="form-field"):
                        yield Label(
                            "Première entité",
                            id="entity-label",
                            classes="field-label",
                        )
                        yield Input(value="Product", id="entity")
                    with Vertical(id="usecase-field", classes="form-field"):
                        yield Label("Premier cas d’usage", classes="field-label")
                        yield Input(value="CreateProduct", id="usecase")
                with Vertical(id="step-storage", classes="wizard-page"):
                    with Vertical(id="repository-field", classes="form-field"):
                        yield Label("Repository explicite", classes="field-label")
                        yield Select(
                            _REPOSITORY_OPTIONS,
                            value=RepositoryChoice.MEMORY.value,
                            allow_blank=False,
                            id="repository",
                        )
                        yield Static(
                            "Ce choix reste indépendant du transport.",
                            classes="field-help",
                        )
                    yield Static("", id="storage-note", classes="decision-note")
                with Vertical(id="step-transport", classes="wizard-page"):
                    yield Static("", id="transport-note", classes="decision-note")
                    with Vertical(id="port-field", classes="form-field"):
                        yield Label("Port", classes="field-label")
                        yield Input(value="8000", id="port", type="integer")
                    with Vertical(id="path-field", classes="form-field"):
                        yield Label("Chemin HTTP", classes="field-label")
                        yield Input(value="/v1/products", id="public-path")
                with Vertical(id="step-review", classes="wizard-page"):
                    yield Static(
                        "Aucune écriture n’a encore été effectuée.",
                        classes="decision-note",
                    )
                    yield Static("", id="review-plan")
            yield Static("", id="wizard-error", classes="error-message")
            yield ProgressBar(total=1, show_eta=False, id="creation-progress")
            with Horizontal(id="wizard-actions", classes="action-row"):
                yield Button("Annuler", id="previous-step")
                yield Button("Continuer", id="next-step", variant="primary")
                yield Button("Créer le projet", id="create-project", variant="primary")
        with VerticalScroll(id="plan-panel"):
            yield Label("PLAN DE GÉNÉRATION", classes="section-title")
            yield Static("", id="plan-preview")
    yield Footer()
