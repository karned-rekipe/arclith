from pathlib import Path

from arclith_cli.guide_executor import replay_recipe_atomically
from arclith_cli.guide_models import GuidePlanError
from arclith_cli.guide_prompts import GuidePrompt
from arclith_cli.guide_rendering import GuideRenderer
from arclith_cli.recipe import RECIPE_FILENAME, load_recipe


def replay_recipe_from_prompt(
    prompt: GuidePrompt,
    renderer: GuideRenderer,
    current_dir: Path,
) -> Path | None:
    """Collect and execute one strict, atomic full-recipe replay."""
    recipe_path = Path(
        _required_text(
            prompt,
            "Chemin de la recette",
            default=str(current_dir / RECIPE_FILENAME),
        )
    ).expanduser()
    recipe = load_recipe(recipe_path)
    target = Path(
        _required_text(
            prompt,
            "Nouveau répertoire cible",
            default=str(current_dir / recipe.project.name),
        )
    ).expanduser()
    renderer.warning(
        f"Rejeu strict de {len(recipe.steps)} étape(s) vers {target.resolve()}"
    )
    if not prompt.confirm("Rejouer cette recette ?", default=True):
        renderer.warning("Rejeu annulé ; aucun fichier n'a été créé.")
        return None
    executed = replay_recipe_atomically(recipe, target_dir=target)
    renderer.success(
        f"Recette rejouée ({len(executed)} étapes) dans {target.resolve()}"
    )
    return target.resolve()


def show_history(renderer: GuideRenderer, project_dir: Path) -> None:
    """Render the reproducible mutation timeline for the current project."""
    recipe = load_recipe(project_dir / RECIPE_FILENAME)
    if not recipe.steps:
        renderer.warning("La recette ne contient encore aucune étape.")
        return
    renderer.warning("Recette reproductible :")
    for step in recipe.steps:
        renderer.warning(f"  {step.id}  {step.command}  {step.at}")


def _required_text(prompt: GuidePrompt, message: str, *, default: str = "") -> str:
    value = prompt.text(message, default=default)
    if not value:
        raise GuidePlanError(f"{message} ne peut pas être vide.")
    return value
