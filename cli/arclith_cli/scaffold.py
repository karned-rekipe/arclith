from __future__ import annotations

import io
import shutil
import zipfile
from contextlib import suppress
from pathlib import Path

import httpx

_TEMPLATE_URL = "https://github.com/karned-rekipe/_sample/archive/refs/heads/{ref}.zip"

_DIRS_TO_REMOVE = {
    "__pycache__",
    ".venv",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".idea",
    ".github",
    ".git",
    ".files",
    ".dev",
    "htmlcov",
}
_FILES_TO_REMOVE = {
    ".coverage",
    "uv.lock",
    "AGENTS.md",
    "README.md",
    ".gitignore",
    "config.yaml",
}
_DATA_FILES_TO_REMOVE = {"ingredient.csv"}


def download_and_extract(
    target_dir: Path, *, ref: str = "main", template_dir: Path | None = None
) -> None:
    if template_dir is not None:
        target_dir.parent.mkdir(parents=True, exist_ok=True)
        _copy_template(template_dir, target_dir)
        _cleanup(target_dir)
        return

    url = _TEMPLATE_URL.format(ref=ref)
    response = httpx.get(url, follow_redirects=True, timeout=60)
    response.raise_for_status()

    with zipfile.ZipFile(io.BytesIO(response.content)) as zf:
        root_prefix = _zip_root(zf)
        target_dir.mkdir(parents=True, exist_ok=False)
        for member in zf.infolist():
            rel = member.filename[len(root_prefix) :]
            if not rel:
                continue
            dest = target_dir / rel
            if member.is_dir():
                dest.mkdir(parents=True, exist_ok=True)
            else:
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(zf.read(member.filename))

    _cleanup(target_dir)


def _copy_template(source_dir: Path, target_dir: Path) -> None:
    if not source_dir.is_dir():
        raise FileNotFoundError(f"Template directory not found: {source_dir}")
    shutil.copytree(
        source_dir,
        target_dir,
        ignore=shutil.ignore_patterns(*_DIRS_TO_REMOVE, *_FILES_TO_REMOVE),
    )


def _zip_root(zf: zipfile.ZipFile) -> str:
    return zf.namelist()[0].split("/")[0] + "/"


def _cleanup(target_dir: Path) -> None:
    # Dirs (traverse deepest first to handle nested __pycache__)
    for item in sorted(target_dir.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if item.is_dir() and item.name in _DIRS_TO_REMOVE:
            shutil.rmtree(item, ignore_errors=True)
        elif item.is_file() and item.name in _FILES_TO_REMOVE:
            item.unlink(missing_ok=True)

    # Data files
    data_dir = target_dir / "data"
    if data_dir.exists():
        for fname in _DATA_FILES_TO_REMOVE:
            (data_dir / fname).unlink(missing_ok=True)
        with suppress(OSError):
            data_dir.rmdir()  # only succeeds if empty
