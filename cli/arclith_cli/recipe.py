from __future__ import annotations

import copy
import hashlib
import os
import re
import tomllib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from arclith_cli import __version__
from arclith_cli.capability_models import AdapterSpec
from arclith_cli.project_paths import detect_project_paths
from arclith_cli.recipe_models import (
    EXTERNAL_PATH,
    RECIPE_FILENAME,
    RECIPE_SCHEMA_VERSION,
    REDACTED,
    Recipe,
    RecipeError,
    RecipeFileChange,
    RecipeProject,
    RecipeResult,
    RecipeSecretRef,
    RecipeStep,
    load_recipe,
    save_recipe,
)

_SUPPORTED_COMMANDS = {
    "init",
    "new",
    "add-adapter",
    "add-entity",
    "add-usecase",
    "add-intent-interpreter",
}
_SENSITIVE_NAME_RE = re.compile(
    r"(?:^|_)(?:password|passwd|secret|token|api_key|apikey|credential)(?:$|_)",
    re.IGNORECASE,
)
_ENV_NAME_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")
_PATH_FIELD_RE = re.compile(r"(?:^|_)(?:directory|dir|path|output|file)$")
_IGNORED_SNAPSHOT_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    "__pycache__",
    "htmlcov",
    "node_modules",
}


def snapshot_project_files(project_dir: Path) -> dict[str, str]:
    """Return content fingerprints for files that a CLI command may mutate."""
    if not project_dir.exists():
        return {}
    snapshot: dict[str, str] = {}
    for path in sorted(project_dir.rglob("*")):
        relative = path.relative_to(project_dir)
        if _ignore_snapshot_path(relative) or not (path.is_file() or path.is_symlink()):
            continue
        if path.is_symlink():
            try:
                target = os.readlink(path)
            except OSError as exc:
                raise RecipeError(
                    f"Unable to inspect generated symlink {relative}: {exc}"
                ) from exc
            payload = b"symlink\0" + os.fsencode(target)
        else:
            try:
                payload = b"file\0" + path.read_bytes()
            except OSError as exc:
                raise RecipeError(
                    f"Unable to inspect generated file {relative}: {exc}"
                ) from exc
        digest = hashlib.sha256(payload).hexdigest()
        snapshot[relative.as_posix()] = digest
    return snapshot


def record_successful_step(
    project_dir: Path,
    *,
    command: str,
    args: Mapping[str, Any],
    before: Mapping[str, str],
    secret_fields: Mapping[str, str] | None = None,
    secret_references: tuple[RecipeSecretRef, ...] = (),
) -> RecipeStep:
    """Append one successful mutation after its complete filesystem change."""
    project_dir = project_dir.resolve()
    recipe_path = project_dir / RECIPE_FILENAME
    recipe = (
        load_recipe(recipe_path)
        if recipe_path.exists()
        else _new_recipe_for_project(project_dir)
    )
    safe_args, detected_secrets = redact_recipe_args(
        args,
        secret_fields=secret_fields or {},
    )
    all_secrets = _deduplicate_secret_refs((*secret_references, *detected_secrets))
    after = snapshot_project_files(project_dir)
    result = RecipeResult(generated_files=_diff_snapshots(before, after))
    now = _now_iso()
    step = RecipeStep(
        id=_next_step_id(recipe.steps),
        at=now,
        cli_version=__version__,
        command=command,
        status="success",
        args=safe_args,
        secrets=all_secrets,
        result=result,
    )
    save_recipe(
        Recipe(
            version=recipe.version,
            project=recipe.project,
            created_at=recipe.created_at,
            updated_at=now,
            steps=(*recipe.steps, step),
        ),
        recipe_path,
    )
    return step


def adapter_secret_metadata(
    adapter: AdapterSpec,
) -> tuple[dict[str, str], tuple[RecipeSecretRef, ...]]:
    """Build replayable secret metadata from the capability catalogue."""
    secret_fields: dict[str, str] = {}
    for parameter in adapter.parameters:
        if parameter.secret:
            secret_fields[f"params.{parameter.name}"] = _parameter_env_key(
                adapter, parameter.name, parameter.prompt
            )
    references = tuple(
        RecipeSecretRef(
            field_path=mapping.field_path,
            source="env",
            key=mapping.secret_key,
        )
        for mapping in adapter.secret_mappings
    )
    return secret_fields, references


def redact_recipe_args(
    args: Mapping[str, Any],
    *,
    secret_fields: Mapping[str, str] | None = None,
) -> tuple[dict[str, Any], tuple[RecipeSecretRef, ...]]:
    """Normalize arguments and replace secret values with replayable references."""
    refs: list[RecipeSecretRef] = []
    safe = _sanitize_value(
        dict(args),
        path=(),
        secret_fields=secret_fields or {},
        refs=refs,
    )
    if not isinstance(safe, dict):  # pragma: no cover - defensive type guard
        raise RecipeError("Recipe arguments must be a mapping.")
    return safe, _deduplicate_secret_refs(tuple(refs))


def select_recipe_steps(
    recipe: Recipe,
    *,
    from_step: str | None = None,
    to_step: str | None = None,
) -> tuple[RecipeStep, ...]:
    """Select an inclusive, ordered replay range by stable step id."""
    if not recipe.steps:
        return ()
    ids = [step.id for step in recipe.steps]
    if from_step is not None and from_step not in ids:
        raise RecipeError(f"Unknown --from-step id: {from_step}")
    if to_step is not None and to_step not in ids:
        raise RecipeError(f"Unknown --to-step id: {to_step}")
    start = ids.index(from_step) if from_step is not None else 0
    end = ids.index(to_step) + 1 if to_step is not None else len(ids)
    if start >= end:
        raise RecipeError("--from-step must not come after --to-step.")
    return recipe.steps[start:end]


def replay_recipe(
    recipe: Recipe,
    steps: tuple[RecipeStep, ...],
    *,
    target_dir: Path,
    strict: bool = False,
) -> tuple[str, ...]:
    """Replay selected recipe actions through the existing Python command helpers."""
    target_dir = target_dir.resolve()
    target_recipe_existed = (target_dir / RECIPE_FILENAME).is_file()
    planned_steps = plan_replay_steps(steps, strict=strict)
    prepared: list[tuple[RecipeStep, dict[str, Any]]] = []
    for step in planned_steps:
        prepared.append((step, _hydrate_step_args(step)))

    executed: list[str] = []
    for step, args in prepared:
        _execute_step(step, args=args, target_dir=target_dir)
        executed.append(step.id)

    if executed and target_dir.is_dir() and not target_recipe_existed:
        copied = Recipe(
            version=recipe.version,
            project=recipe.project,
            created_at=planned_steps[0].at,
            updated_at=planned_steps[-1].at,
            steps=planned_steps,
        )
        save_recipe(copied, target_dir / RECIPE_FILENAME)
    return tuple(executed)


def plan_replay_steps(
    steps: tuple[RecipeStep, ...],
    *,
    strict: bool,
) -> tuple[RecipeStep, ...]:
    """Return the steps that replay will execute after compatibility checks."""
    validate_replay_steps(steps, strict=strict)
    return tuple(step for step in steps if step.command in _SUPPORTED_COMMANDS)


def validate_replay_steps(
    steps: tuple[RecipeStep, ...],
    *,
    strict: bool,
) -> None:
    """Preflight command compatibility without reading secret values or writing files."""
    if not strict:
        return
    unsupported = [
        f"{step.id}:{step.command}"
        for step in steps
        if step.command not in _SUPPORTED_COMMANDS
    ]
    if unsupported:
        raise RecipeError(
            "Unsupported recipe commands in strict mode: " + ", ".join(unsupported)
        )


def step_summary(step: RecipeStep) -> str:
    """Return a compact, secret-free human summary for history and dry-run."""
    args = step.args
    if step.command in {"init", "new"}:
        return str(args.get("project_name") or "project")
    if step.command == "add-adapter":
        capability = args.get("capability", "repository")
        adapter = args.get("adapter", "?")
        entities = args.get("entities") or []
        suffix = f" ({', '.join(map(str, entities))})" if entities else ""
        return f"{capability}/{adapter}{suffix}"
    if step.command == "add-usecase":
        usecase = str(args.get("usecase") or "usecase")
        entity = args.get("entity") or args.get("new_entity")
        return f"{usecase} ({entity})" if entity else f"{usecase} (transverse)"
    for key in ("entity", "usecase", "intent"):
        if key in args:
            return str(args[key])
    return ""


def required_replay_env(steps: tuple[RecipeStep, ...]) -> tuple[str, ...]:
    """List environment variables needed to hydrate redacted replay arguments."""
    return tuple(
        sorted(
            {
                secret.key
                for step in steps
                for secret in step.secrets
                if secret.source == "env" and secret.field_path.startswith("args.")
            }
        )
    )


def _execute_step(
    step: RecipeStep,
    *,
    args: dict[str, Any],
    target_dir: Path,
) -> None:
    if step.command == "init":
        from arclith_cli.init_project import init_project_cmd

        init_project_cmd(
            project_name=str(args.get("project_name") or target_dir.name),
            directory=target_dir.parent,
            target_path=target_dir,
        )
        return
    if step.command == "new":
        from arclith_cli.new_project import new_project_cmd

        new_project_cmd(
            entity=str(args["entity"]),
            project_name=str(args.get("project_name") or target_dir.name),
            directory=target_dir.parent,
            port=int(args.get("port", 8000)),
            repo_ref=str(args.get("repo_ref", "main")),
            template_dir=None,
            target_path=target_dir,
        )
        return
    if not target_dir.is_dir():
        raise RecipeError(
            f"Replay target does not exist before step {step.id}: {target_dir}"
        )
    if step.command == "add-entity":
        from arclith_cli.core_scaffold import add_entity_cmd

        add_entity_cmd(project_dir=target_dir, entity_name=str(args["entity"]))
        return
    if step.command == "add-usecase":
        from arclith_cli.core_scaffold import add_usecase_cmd

        raw_entity = args.get("entity")
        raw_new_entity = args.get("new_entity")
        add_usecase_cmd(
            project_dir=target_dir,
            usecase_name=str(args["usecase"]),
            entity_name=str(raw_entity) if raw_entity is not None else None,
            new_entity_name=(
                str(raw_new_entity) if raw_new_entity is not None else None
            ),
        )
        return
    if step.command == "add-intent-interpreter":
        from arclith_cli.core_scaffold import add_intent_interpreter_cmd

        add_intent_interpreter_cmd(
            project_dir=target_dir,
            intent_name=str(args["intent"]),
        )
        return
    if step.command == "add-adapter":
        from arclith_cli.add_adapter import add_adapter_cmd

        raw_params = args.get("params") or {}
        if not isinstance(raw_params, dict):
            raise RecipeError(f"Step {step.id} add-adapter params must be a mapping.")
        raw_entities = args.get("entities") or []
        if not isinstance(raw_entities, list):
            raise RecipeError(f"Step {step.id} add-adapter entities must be a list.")
        add_adapter_cmd(
            project_dir=target_dir,
            capability_name=str(args.get("capability", "repository")),
            adapter=str(args["adapter"]),
            entity_names=[str(item) for item in raw_entities] or None,
            activate=bool(args.get("activate", True)),
            adapter_params=dict(raw_params),
            yes=True,
        )


def _hydrate_step_args(step: RecipeStep) -> dict[str, Any]:
    args = copy.deepcopy(step.args)
    for secret in step.secrets:
        if not secret.field_path.startswith("args."):
            continue
        if secret.source != "env":
            raise RecipeError(
                f"Step {step.id} secret source {secret.source!r} is not supported."
            )
        value = os.getenv(secret.key)
        if value is None:
            raise RecipeError(
                f"Step {step.id} requires environment variable {secret.key} for replay."
            )
        _set_nested_value(args, secret.field_path.removeprefix("args."), value)
    if _contains_placeholder(args, REDACTED):
        raise RecipeError(
            f"Step {step.id} contains a redacted value without a secret reference."
        )
    if _contains_placeholder(args, EXTERNAL_PATH):
        raise RecipeError(
            f"Step {step.id} contains a non-portable external path and cannot be replayed."
        )
    return args


def _set_nested_value(data: dict[str, Any], field_path: str, value: str) -> None:
    parts = field_path.split(".")
    current = data
    for part in parts[:-1]:
        child = current.get(part)
        if not isinstance(child, dict):
            child = {}
            current[part] = child
        current = child
    current[parts[-1]] = value


def _contains_placeholder(value: Any, placeholder: str) -> bool:
    if value == placeholder:
        return True
    if isinstance(value, dict):
        return any(_contains_placeholder(item, placeholder) for item in value.values())
    if isinstance(value, list):
        return any(_contains_placeholder(item, placeholder) for item in value)
    return False


def _new_recipe_for_project(project_dir: Path) -> Recipe:
    project = _read_project_identity(project_dir)
    now = _now_iso()
    return Recipe(
        version=RECIPE_SCHEMA_VERSION,
        project=project,
        created_at=now,
        updated_at=now,
    )


def _read_project_identity(project_dir: Path) -> RecipeProject:
    name = project_dir.name
    pyproject = project_dir / "pyproject.toml"
    if pyproject.is_file():
        try:
            data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            configured_name = None
        else:
            configured_name = data.get("project", {}).get("name")
        if isinstance(configured_name, str) and configured_name.strip():
            name = configured_name.strip()
    paths = detect_project_paths(project_dir)
    package = paths.package_name or name.replace("-", "_")
    return RecipeProject(name=name, package=package)


def _sanitize_value(
    value: Any,
    *,
    path: tuple[str, ...],
    secret_fields: Mapping[str, str],
    refs: list[RecipeSecretRef],
) -> Any:
    if isinstance(value, Mapping):
        sanitized: dict[str, Any] = {}
        for raw_key, item in value.items():
            key = str(raw_key)
            item_path = (*path, key)
            dotted = ".".join(item_path)
            secret_key = secret_fields.get(dotted)
            if _is_external_path_value(key, item):
                sanitized[key] = EXTERNAL_PATH
            elif secret_key is not None or _is_sensitive_value(key, item):
                replay_key = secret_key or _fallback_env_key(item_path)
                sanitized[key] = REDACTED
                refs.append(
                    RecipeSecretRef(
                        field_path=f"args.{dotted}",
                        source="env",
                        key=replay_key,
                    )
                )
            else:
                sanitized[key] = _sanitize_value(
                    item,
                    path=item_path,
                    secret_fields=secret_fields,
                    refs=refs,
                )
        return sanitized
    if isinstance(value, (list, tuple)):
        return [
            _sanitize_value(
                item,
                path=(*path, str(index)),
                secret_fields=secret_fields,
                refs=refs,
            )
            for index, item in enumerate(value)
        ]
    if isinstance(value, Path):
        return _portable_path(value)
    if isinstance(value, datetime):
        if value.tzinfo is None or value.utcoffset() is None:
            raise RecipeError("Recipe timestamps must be timezone-aware.")
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _is_sensitive_value(key: str, value: Any) -> bool:
    if _SENSITIVE_NAME_RE.search(key):
        return True
    if not isinstance(value, str) or (
        "uri" not in key.lower() and "url" not in key.lower()
    ):
        return False
    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    return parsed.username is not None or parsed.password is not None


def _is_external_path_value(key: str, value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(_PATH_FIELD_RE.search(key.lower()))
        and Path(value).is_absolute()
    )


def _portable_path(path: Path) -> str:
    if path.is_absolute():
        return EXTERNAL_PATH
    normalized = path.as_posix()
    return normalized or "."


def _fallback_env_key(path: tuple[str, ...]) -> str:
    normalized = "_".join(path).upper()
    normalized = re.sub(r"[^A-Z0-9]+", "_", normalized).strip("_")
    return f"ARCLITH_REPLAY_{normalized}"


def _parameter_env_key(adapter: AdapterSpec, name: str, prompt: str) -> str:
    candidates = [
        mapping.secret_key
        for mapping in adapter.secret_mappings
        if name.upper() in mapping.secret_key
    ]
    if len(candidates) == 1:
        return candidates[0]
    if _ENV_NAME_RE.fullmatch(prompt):
        return prompt
    if len(adapter.secret_mappings) == 1:
        return adapter.secret_mappings[0].secret_key
    raw = f"ARCLITH_{adapter.capability}_{adapter.name}_{name}".upper()
    return re.sub(r"[^A-Z0-9]+", "_", raw)


def _deduplicate_secret_refs(
    refs: tuple[RecipeSecretRef, ...],
) -> tuple[RecipeSecretRef, ...]:
    unique: dict[tuple[str, str, str], RecipeSecretRef] = {}
    for ref in refs:
        unique[(ref.field_path, ref.source, ref.key)] = ref
    return tuple(unique.values())


def _diff_snapshots(
    before: Mapping[str, str], after: Mapping[str, str]
) -> tuple[RecipeFileChange, ...]:
    changes: list[RecipeFileChange] = []
    for path in sorted(after):
        if path not in before:
            changes.append(RecipeFileChange(path=path, action="created"))
        elif before[path] != after[path]:
            changes.append(RecipeFileChange(path=path, action="updated"))
    return tuple(changes)


def _next_step_id(steps: tuple[RecipeStep, ...]) -> str:
    next_id = max((int(step.id) for step in steps), default=0) + 1
    if next_id > 9999:
        raise RecipeError("A version 1 recipe cannot contain more than 9999 steps.")
    return f"{next_id:04d}"


def _ignore_snapshot_path(path: Path) -> bool:
    return path.name == RECIPE_FILENAME or any(
        part in _IGNORED_SNAPSHOT_PARTS for part in path.parts
    )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
