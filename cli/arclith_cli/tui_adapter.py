import io
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

import typer
from rich.markup import escape
from rich.text import Text
from textual import events, work
from textual.app import ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.screen import Screen
from textual.widgets import (
    Button,
    Footer,
    Header,
    Input,
    Label,
    LoadingIndicator,
    Select,
    Static,
    Switch,
)
from textual.widget import Widget

from arclith_cli.add_adapter import add_adapter_and_record
from arclith_cli.capabilities import CAPABILITY_CATALOG
from arclith_cli.capability_models import AdapterSpec, CapabilitySpec, ParameterSpec
from arclith_cli.tui_adapter_catalog import (
    AdapterInstallRequest,
    available_adapters,
    available_capabilities,
    configuration_replacements,
    default_activation,
)

_DEFAULT_PROFILE = "__defaults__"


class AddAdapterScreen(Screen[str | None]):
    """Catalogue-driven adapter installer for an existing project."""

    BINDINGS = [
        ("escape", "cancel", "Annuler"),
        ("ctrl+enter", "install", "Installer"),
    ]

    def __init__(self, project_root: Path, installed: tuple[str, ...]) -> None:
        super().__init__()
        self._project_root = project_root.resolve()
        self._installed = frozenset(installed)
        self._parameter_widgets: dict[str, Widget] = {}
        self._profile_adapter_key: str | None = None
        self._busy = False
        self._updating = False

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        with Horizontal(id="adapter-shell"):
            with Vertical(id="adapter-sidebar"):
                yield Static("◈  ÉTENDRE", id="adapter-brand")
                yield Static(
                    "1  Capability\n\n2  Adapter\n\n3  Paramètres\n\n4  Installation",
                    id="adapter-steps",
                )
                yield Static(self._installed_summary(), id="adapter-installed")
            with Vertical(id="adapter-main"):
                with VerticalScroll(id="adapter-form"):
                    yield Static("CATALOGUE D’ADAPTERS", classes="eyebrow")
                    yield Label("Étendre le projet", id="adapter-title")
                    yield Static(
                        "Choisissez une capability puis configurez son implémentation. "
                        "Les adapters déjà installés sont masqués.",
                        classes="lead",
                    )
                    with Vertical(classes="form-field"):
                        yield Label("Capability", classes="field-label")
                        yield Select(
                            [], prompt="Choisir une capability", id="adapter-capability"
                        )
                        yield Static(
                            "", id="adapter-capability-help", classes="field-help"
                        )
                    with Vertical(classes="form-field"):
                        yield Label("Adapter", classes="field-label")
                        yield Select(
                            [], prompt="Choisir un adapter", id="adapter-choice"
                        )
                        yield Static(
                            "", id="adapter-description", classes="decision-note"
                        )
                        yield Static("", id="adapter-conflict")
                    with Vertical(id="adapter-profile-field", classes="form-field"):
                        yield Label("Profil", classes="field-label")
                        yield Select(
                            [], prompt="Valeurs par défaut", id="adapter-profile"
                        )
                    yield Vertical(id="adapter-parameters")
                    with Horizontal(id="adapter-activation-field"):
                        with Vertical(id="adapter-activation-copy"):
                            yield Label("Activer maintenant", classes="field-label")
                            yield Static(
                                "", id="adapter-activation-help", classes="field-help"
                            )
                        yield Switch(id="adapter-activate")
                    yield Label("Commande reproductible", classes="content-title")
                    yield Static("", id="adapter-command")
                    yield Static("", id="adapter-error", classes="error-message")
                    yield LoadingIndicator(id="adapter-loading")
                with Horizontal(classes="action-row", id="adapter-actions"):
                    yield Button("Annuler", id="adapter-cancel")
                    yield Button(
                        "Installer l’adapter",
                        id="adapter-install",
                        variant="primary",
                        disabled=True,
                    )
        yield Footer()

    async def on_mount(self) -> None:
        self.query_one("#adapter-loading", LoadingIndicator).display = False
        await self._load_catalog()

    def on_resize(self, event: events.Resize) -> None:
        self.query_one("#adapter-sidebar", Vertical).display = event.size.width >= 100

    async def on_select_changed(self, event: Select.Changed) -> None:
        if self._updating:
            return
        if event.select.id == "adapter-capability":
            await self._select_capability()
        elif event.select.id in {"adapter-choice", "adapter-profile"}:
            await self._render_adapter_form()

    def on_input_changed(self, _event: Input.Changed) -> None:
        self._refresh_preview()

    def on_switch_changed(self, _event: Switch.Changed) -> None:
        self._refresh_preview()

    def on_button_pressed(self, event: Button.Pressed) -> None:
        if event.button.id == "adapter-cancel":
            self.action_cancel()
        elif event.button.id == "adapter-install":
            self.action_install()

    def action_cancel(self) -> None:
        if self._busy:
            self.notify("L’installation est en cours.", severity="warning")
            return
        self.dismiss(None)

    def action_install(self) -> None:
        if self._busy:
            return
        request = self._request(validate=True)
        if request is None:
            return
        self._set_busy(True)
        self.query_one("#adapter-error", Static).update(
            f"[cyan]Installation de {escape(request.capability.name)}/"
            f"{escape(request.adapter.name)}…[/cyan]"
        )
        self._install_adapter(request)

    async def _load_catalog(self) -> None:
        capabilities = available_capabilities(self._installed)
        capability_select = self.query_one("#adapter-capability", Select)
        if not capabilities:
            self.query_one("#adapter-error", Static).update(
                "[green]Tous les adapters du catalogue sont déjà installés.[/green]"
            )
            return
        self._updating = True
        capability_select.set_options(
            [(self._label(item.name), item.name) for item in capabilities]
        )
        capability_select.value = capabilities[0].name
        self._updating = False
        await self._select_capability()

    async def _select_capability(self) -> None:
        capability = self._capability()
        if capability is None:
            return
        adapters = available_adapters(capability, self._installed)
        adapter_select = self.query_one("#adapter-choice", Select)
        self.query_one("#adapter-capability-help", Static).update(
            escape(capability.description)
        )
        self._updating = True
        adapter_select.set_options(
            [(self._label(adapter.name), adapter.name) for adapter in adapters]
        )
        adapter_select.value = adapters[0].name
        self._updating = False
        await self._render_adapter_form()

    async def _render_adapter_form(self) -> None:
        capability = self._capability()
        adapter = self._adapter(capability)
        install = self.query_one("#adapter-install", Button)
        if capability is None or adapter is None:
            install.disabled = True
            return
        self.query_one("#adapter-description", Static).update(
            f"[b]{escape(capability.layer)}[/b]  {escape(adapter.description)}"
        )
        replacements = configuration_replacements(adapter, self._installed)
        conflict = self.query_one("#adapter-conflict", Static)
        conflict.display = bool(replacements)
        conflict.update(
            "[yellow]⚠ Cette installation remplacera la configuration de "
            f"{escape(', '.join(replacements))} dans "
            f"{escape(adapter.config_path or '')}.[/yellow]"
        )
        self._configure_profiles(adapter)
        profile_values = self._profile_values(adapter)
        parameters = self.query_one("#adapter-parameters", Vertical)
        await parameters.remove_children()
        self._parameter_widgets.clear()
        fields: list[Vertical] = []
        for index, parameter in enumerate(adapter.parameters):
            widget = self._parameter_widget(parameter, index, profile_values)
            self._parameter_widgets[parameter.name] = widget
            help_text = self._parameter_help(parameter)
            fields.append(
                Vertical(
                    Label(parameter.prompt, classes="field-label"),
                    widget,
                    Static(help_text, classes="field-help") if help_text else Static(),
                    classes="adapter-parameter form-field",
                )
            )
        if fields:
            await parameters.mount(*fields)
        else:
            await parameters.mount(
                Static("Aucun paramètre requis.", classes="decision-note")
            )
        self._configure_activation(capability)
        install.disabled = False
        self._refresh_preview()

    def _configure_profiles(self, adapter: AdapterSpec) -> None:
        field = self.query_one("#adapter-profile-field", Vertical)
        select = self.query_one("#adapter-profile", Select)
        adapter_key = f"{adapter.capability}/{adapter.name}"
        if self._profile_adapter_key == adapter_key:
            field.display = bool(adapter.profiles)
            return
        self._profile_adapter_key = adapter_key
        selected = select.value if isinstance(select.value, str) else _DEFAULT_PROFILE
        options = [("Valeurs du catalogue", _DEFAULT_PROFILE)]
        options.extend(
            (self._label(profile.name), profile.name) for profile in adapter.profiles
        )
        self._updating = True
        select.set_options(options)
        allowed = {value for _, value in options}
        select.value = selected if selected in allowed else _DEFAULT_PROFILE
        self._updating = False
        field.display = bool(adapter.profiles)

    def _configure_activation(self, capability: CapabilitySpec) -> None:
        field = self.query_one("#adapter-activation-field", Horizontal)
        switch = self.query_one("#adapter-activate", Switch)
        supported = capability.activation_config_key is not None
        field.display = supported
        switch.value = default_activation(capability, self._installed)
        existing = any(
            item.startswith(f"{capability.name}/") for item in self._installed
        )
        if existing and capability.name != "observability":
            help_text = (
                "Désactivé par sécurité : l’adapter actuel reste sélectionné. "
                "Activez ce bouton pour le remplacer."
            )
        elif capability.name == "observability":
            help_text = (
                "Les providers d’observabilité peuvent être activés en parallèle."
            )
        else:
            help_text = "Met à jour config/adapters/adapters.yaml."
        self.query_one("#adapter-activation-help", Static).update(help_text)

    def _parameter_widget(
        self,
        parameter: ParameterSpec,
        index: int,
        profile_values: dict[str, str | bool],
    ) -> Widget:
        value = self._parameter_default(parameter, profile_values)
        widget_id = f"adapter-param-{index}"
        if parameter.kind == "boolean":
            return Switch(value=self._as_bool(value), id=widget_id)
        if parameter.choices and not parameter.csv_choices:
            choices = [(self._label(choice), choice) for choice in parameter.choices]
            selected = (
                str(value) if str(value) in parameter.choices else parameter.choices[0]
            )
            return Select(choices, value=selected, id=widget_id)
        return Input(value=str(value), password=parameter.secret, id=widget_id)

    def _parameter_default(
        self,
        parameter: ParameterSpec,
        profile_values: dict[str, str | bool],
    ) -> str | bool:
        if parameter.name in profile_values:
            return profile_values[parameter.name]
        if parameter.default_from_project_name:
            return self._project_root.name
        if parameter.default is not None:
            return parameter.default
        return ""

    @staticmethod
    def _parameter_help(parameter: ParameterSpec) -> str:
        details: list[str] = []
        if parameter.required:
            details.append("requis")
        if parameter.secret:
            details.append("secret — masqué dans la commande et la recette")
        if parameter.choices:
            separator = ", " if parameter.csv_choices else " · "
            details.append(f"valeurs : {separator.join(parameter.choices)}")
        return " · ".join(details)

    def _profile_values(self, adapter: AdapterSpec) -> dict[str, str | bool]:
        profile_name = self._profile_name()
        if profile_name is None:
            return {}
        profile = adapter.get_profile(profile_name)
        return profile.values() if profile is not None else {}

    def _request(self, *, validate: bool) -> AdapterInstallRequest | None:
        capability = self._capability()
        adapter = self._adapter(capability)
        if capability is None or adapter is None:
            if validate:
                self.query_one("#adapter-error", Static).update(
                    "[red]Sélectionnez une capability et un adapter.[/red]"
                )
            return None
        parameters: list[tuple[str, str]] = []
        for parameter in adapter.parameters:
            widget = self._parameter_widgets[parameter.name]
            value = self._widget_value(widget)
            if validate and parameter.required and not value:
                self.query_one("#adapter-error", Static).update(
                    f"[red]Paramètre requis : {escape(parameter.prompt)}.[/red]"
                )
                widget.focus()
                return None
            parameters.append((parameter.name, value))
        activate = (
            self.query_one("#adapter-activate", Switch).value
            if capability.activation_config_key is not None
            else False
        )
        return AdapterInstallRequest(
            project_root=self._project_root,
            capability=capability,
            adapter=adapter,
            parameters=tuple(parameters),
            profile=self._profile_name(),
            activate=activate,
        )

    def _refresh_preview(self) -> None:
        if not self.is_mounted:
            return
        request = self._request(validate=False)
        preview = request.command() if request is not None else "Commande incomplète"
        self.query_one("#adapter-command", Static).update(escape(preview))

    @work(thread=True, exclusive=True, group="adapter-installation")
    def _install_adapter(self, request: AdapterInstallRequest) -> None:
        captured = io.StringIO()
        try:
            with redirect_stdout(captured), redirect_stderr(captured):
                add_adapter_and_record(
                    project_dir=request.project_root,
                    capability_name=request.capability.name,
                    adapter=request.adapter.name,
                    entity_names=None,
                    all_entities=False,
                    activate=request.activate,
                    db_name=None,
                    multitenant=None,
                    duckdb_path=None,
                    adapter_params=dict(request.parameters),
                    profile=request.profile,
                    yes=True,
                    dry_run=False,
                    record=True,
                )
        except (OSError, RuntimeError, SyntaxError, ValueError, typer.Exit) as exc:
            output = Text.from_ansi(captured.getvalue()).plain.strip()
            message = output or str(exc) or "L’installation a été refusée."
            self.app.call_from_thread(self._installation_failed, message)
            return
        key = f"{request.capability.name}/{request.adapter.name}"
        self.app.call_from_thread(self._installation_succeeded, key)

    def _installation_failed(self, message: str) -> None:
        self._set_busy(False)
        self.query_one("#adapter-error", Static).update(f"[red]{escape(message)}[/red]")

    def _installation_succeeded(self, key: str) -> None:
        self.notify(f"Adapter installé : {key}", title="Arclith")
        self.dismiss(key)

    def _set_busy(self, busy: bool) -> None:
        self._busy = busy
        self.query_one("#adapter-loading", LoadingIndicator).display = busy
        for selector in (
            "#adapter-capability",
            "#adapter-choice",
            "#adapter-profile",
            "#adapter-activate",
            "#adapter-install",
            "#adapter-cancel",
        ):
            self.query_one(selector).disabled = busy
        for widget in self._parameter_widgets.values():
            widget.disabled = busy

    def _capability(self) -> CapabilitySpec | None:
        value = self.query_one("#adapter-capability", Select).value
        if not isinstance(value, str):
            return None
        return next(
            (
                capability
                for capability in CAPABILITY_CATALOG
                if capability.name == value
            ),
            None,
        )

    def _adapter(self, capability: CapabilitySpec | None) -> AdapterSpec | None:
        if capability is None:
            return None
        value = self.query_one("#adapter-choice", Select).value
        return capability.get_adapter(value) if isinstance(value, str) else None

    def _profile_name(self) -> str | None:
        value = self.query_one("#adapter-profile", Select).value
        if not isinstance(value, str) or value == _DEFAULT_PROFILE:
            return None
        return value

    @staticmethod
    def _widget_value(widget: Widget) -> str:
        if isinstance(widget, Switch):
            return "true" if widget.value else "false"
        if isinstance(widget, Select):
            return str(widget.value) if isinstance(widget.value, str) else ""
        if isinstance(widget, Input):
            return widget.value.strip()
        return ""

    @staticmethod
    def _as_bool(value: str | bool) -> bool:
        if isinstance(value, bool):
            return value
        return value.strip().lower() in {"1", "true", "yes", "on"}

    @staticmethod
    def _label(value: str) -> str:
        return value.replace("-", " ").replace("_", " ").title()

    def _installed_summary(self) -> str:
        if not self._installed:
            return "[dim]Aucun adapter installé[/dim]"
        items = "\n".join(f"• {escape(item)}" for item in sorted(self._installed))
        return f"[dim]DÉJÀ INSTALLÉS[/dim]\n\n{items}"
