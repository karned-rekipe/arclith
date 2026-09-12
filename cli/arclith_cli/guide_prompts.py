from abc import ABC, abstractmethod

import questionary
from questionary import Choice

from arclith_cli.guide_models import GuideCancelled, GuideChoice


class GuidePrompt(ABC):
    """UI boundary used by the guide controller and deterministic tests."""

    @abstractmethod
    def select(self, message: str, choices: tuple[GuideChoice, ...]) -> str:
        """Select exactly one value."""

    @abstractmethod
    def text(self, message: str, *, default: str = "", secret: bool = False) -> str:
        """Read one text value."""

    @abstractmethod
    def confirm(self, message: str, *, default: bool = True) -> bool:
        """Confirm or reject one decision."""

    @abstractmethod
    def checkbox(
        self,
        message: str,
        choices: tuple[GuideChoice, ...],
    ) -> tuple[str, ...]:
        """Select zero or more values."""


class QuestionaryGuidePrompt(GuidePrompt):
    """Questionary-backed arrow-key interface."""

    def select(self, message: str, choices: tuple[GuideChoice, ...]) -> str:
        default = next(
            (choice.value for choice in choices if choice.checked),
            None,
        )
        answer = questionary.select(
            message,
            choices=[_to_questionary_choice(choice) for choice in choices],
            default=default,
            use_shortcuts=True,
            use_arrow_keys=True,
        ).ask()
        return _required_answer(answer)

    def text(self, message: str, *, default: str = "", secret: bool = False) -> str:
        question = (
            questionary.password(message)
            if secret
            else questionary.text(message, default=default)
        )
        answer = question.ask()
        return _required_answer(answer).strip()

    def confirm(self, message: str, *, default: bool = True) -> bool:
        answer = questionary.confirm(message, default=default).ask()
        if answer is None:
            raise GuideCancelled
        return bool(answer)

    def checkbox(
        self,
        message: str,
        choices: tuple[GuideChoice, ...],
    ) -> tuple[str, ...]:
        answer = questionary.checkbox(
            message,
            choices=[_to_questionary_choice(choice) for choice in choices],
        ).ask()
        if answer is None:
            raise GuideCancelled
        return tuple(str(value) for value in answer)


def _to_questionary_choice(choice: GuideChoice) -> Choice:
    return Choice(
        title=choice.title,
        value=choice.value,
        description=choice.description,
        disabled=choice.disabled,
        checked=choice.checked,
    )


def _required_answer(answer: object) -> str:
    if answer is None:
        raise GuideCancelled
    return str(answer)
