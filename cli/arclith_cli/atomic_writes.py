"""Atomic, no-replace writes for generated project files."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import TextIO


@dataclass(frozen=True)
class FilePublication:
    """Identity of one file atomically published by this process."""

    path: Path
    device: int
    inode: int


def write_new_text_file(path: Path, content: str) -> FilePublication:
    """Publish complete UTF-8 content only if ``path`` is still absent."""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = -1
    temporary_path: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary_path = Path(temporary_name)
        stream = os.fdopen(descriptor, mode="w", encoding="utf-8", newline="")
        descriptor = -1
        with stream:
            _write_and_sync(stream, content)
        temporary_path.chmod(0o644)
        identity = temporary_path.lstat()
        # A hard link publishes the complete inode atomically and, unlike
        # os.replace(), fails if a concurrent writer already created ``path``.
        os.link(temporary_path, path)
        return FilePublication(
            path=path,
            device=identity.st_dev,
            inode=identity.st_ino,
        )
    finally:
        if descriptor >= 0:
            try:
                os.close(descriptor)
            except OSError:
                # Cleanup is best-effort and must not hide the write outcome.
                pass
        if temporary_path is not None:
            try:
                temporary_path.unlink(missing_ok=True)
            except OSError:
                # A leaked hidden temporary is safer than masking the primary result.
                pass


def _write_and_sync(stream: TextIO, content: str) -> None:
    stream.write(content)
    stream.flush()
    os.fsync(stream.fileno())
