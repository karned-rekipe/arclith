from collections import deque
from pathlib import Path

from rich.console import Console
from typer.testing import CliRunner

from arclith_cli.guide import run_interactive_guide, should_launch_guide
from arclith_cli.guide_models import GuideChoice
from arclith_cli.guide_prompts import GuidePrompt
from arclith_cli.main import app
from arclith_cli.recipe import RECIPE_FILENAME, load_recipe

runner = CliRunner()


class _TTY:
    def __init__(self, *, interactive: bool) -> None:
        self._interactive = interactive

    def isatty(self) -> bool:
        return self._interactive


class FakePrompt(GuidePrompt):
    def __init__(
        self,
        *,
        selections: tuple[str, ...],
        texts: tuple[str, ...] = (),
        confirmations: tuple[bool, ...] = (),
        checked: tuple[tuple[str, ...], ...] = (),
    ) -> None:
        self.selections = deque(selections)
        self.texts = deque(texts)
        self.confirmations = deque(confirmations)
        self.checked = deque(checked)

    def select(self, message: str, choices: tuple[GuideChoice, ...]) -> str:
        del message
        answer = self.selections.popleft()
        assert answer in {choice.value for choice in choices}
        return answer

    def text(self, message: str, *, default: str = "", secret: bool = False) -> str:
        del message, default, secret
        return self.texts.popleft()

    def confirm(self, message: str, *, default: bool = True) -> bool:
        del message, default
        return self.confirmations.popleft()

    def checkbox(
        self,
        message: str,
        choices: tuple[GuideChoice, ...],
    ) -> tuple[str, ...]:
        del message, choices
        return self.checked.popleft()


def test_should_launch_guide_only_in_real_terminal() -> None:
    tty = _TTY(interactive=True)
    pipe = _TTY(interactive=False)

    assert should_launch_guide(tty, tty, {"TERM": "xterm-256color"}) is True  # type: ignore[arg-type]
    assert should_launch_guide(pipe, tty, {"TERM": "xterm-256color"}) is False  # type: ignore[arg-type]
    assert should_launch_guide(tty, tty, {"TERM": "dumb"}) is False  # type: ignore[arg-type]


def test_no_arguments_remain_script_safe_and_show_help() -> None:
    result = runner.invoke(app, [])

    assert result.exit_code == 0
    assert "Usage:" in result.output
    assert "guide" in result.output


def test_guide_creates_minimal_project_then_stays_open_until_quit(
    tmp_path: Path,
) -> None:
    prompt = FakePrompt(
        selections=("create", "minimal", "entity", "crud", "quit"),
        texts=(str(tmp_path), "guided-service", "Todo"),
        confirmations=(False, True, True),
    )
    console = Console(record=True, width=120)

    run_interactive_guide(start_dir=tmp_path, prompt=prompt, console=console)

    project = tmp_path / "guided-service"
    assert project.is_dir()
    recipe = load_recipe(project / RECIPE_FILENAME)
    assert [step.command for step in recipe.steps] == ["init", "add-entity"]
    assert recipe.steps[-1].args["profile"] == "crud"
    rendered = console.export_text()
    assert "Projet complet créé" in rendered
    assert "Pour votre shell : cd" in rendered
    assert "guided-service" in rendered
    assert not prompt.selections
    assert not prompt.texts
    assert not prompt.confirmations
