from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

from arclith.infrastructure.config import LangSmithSettings

_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})
_FALSE_VALUES = frozenset({"0", "false", "no", "off"})
_TRACING_MODES = frozenset({"langsmith", "otel", "hybrid"})


@dataclass(frozen=True)
class ResolvedLangSmithConfig:
    project: str
    endpoint: str
    api_key: str = field(repr=False)
    workspace_id: str | None = None
    tracing_enabled: bool = True
    tracing_mode: Literal["langsmith", "otel", "hybrid"] = "otel"
    sampling_rate: float = 1.0
    capture_inputs: bool = False
    capture_outputs: bool = False
    capture_metadata: bool = True


def resolve_langsmith_config(settings: LangSmithSettings) -> ResolvedLangSmithConfig:
    tracing_enabled = _env_bool("LANGSMITH_TRACING", settings.tracing.enabled)
    sampling_rate = _env_float(
        "LANGSMITH_TRACING_SAMPLING_RATE",
        settings.tracing.sampling_rate,
    )
    if not 0.0 <= sampling_rate <= 1.0:
        raise RuntimeError(
            "LANGSMITH_TRACING_SAMPLING_RATE doit etre compris entre 0.0 et 1.0"
        )

    tracing_mode_raw = (
        os.getenv("LANGSMITH_TRACING_MODE", settings.tracing.mode).strip().lower()
    )
    if tracing_mode_raw not in _TRACING_MODES:
        allowed = ", ".join(sorted(_TRACING_MODES))
        raise RuntimeError(f"LANGSMITH_TRACING_MODE invalide. Valeurs: {allowed}")
    tracing_mode: Literal["langsmith", "otel", "hybrid"]
    if tracing_mode_raw == "otel":
        tracing_mode = "otel"
    elif tracing_mode_raw == "hybrid":
        tracing_mode = "hybrid"
    else:
        tracing_mode = "langsmith"

    api_key = os.getenv("LANGSMITH_API_KEY", "").strip()
    if not api_key:
        api_key = os.getenv(settings.api_key_env, "").strip()
    if not api_key:
        key_hint = "LANGSMITH_API_KEY"
        if settings.api_key_env != key_hint:
            key_hint = f"{key_hint} ou {settings.api_key_env}"
        raise RuntimeError(
            "LangSmith est active mais aucune cle API n'est disponible. "
            f"Definissez {key_hint}, "
            "ou retirez langsmith de adapters.observability.enabled."
        )

    workspace_id = os.getenv("LANGSMITH_WORKSPACE_ID", "").strip()
    if not workspace_id:
        workspace_id = os.getenv(settings.workspace_id_env, "").strip()

    return ResolvedLangSmithConfig(
        project=os.getenv("LANGSMITH_PROJECT", settings.project).strip(),
        endpoint=os.getenv("LANGSMITH_ENDPOINT", settings.endpoint).strip(),
        api_key=api_key,
        workspace_id=workspace_id or None,
        tracing_enabled=tracing_enabled,
        tracing_mode=tracing_mode,
        sampling_rate=sampling_rate,
        capture_inputs=not _env_bool(
            "LANGSMITH_HIDE_INPUTS",
            not settings.capture.inputs,
        ),
        capture_outputs=not _env_bool(
            "LANGSMITH_HIDE_OUTPUTS",
            not settings.capture.outputs,
        ),
        capture_metadata=not _env_bool(
            "LANGSMITH_HIDE_METADATA",
            not settings.capture.metadata,
        ),
    )


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    normalized = raw.strip().lower()
    if normalized in _TRUE_VALUES:
        return True
    if normalized in _FALSE_VALUES:
        return False
    raise RuntimeError(f"{name} doit etre un booleen (true/false)")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw)
    except ValueError:
        raise RuntimeError(f"{name} doit etre un nombre") from None
