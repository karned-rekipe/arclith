from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class FilesystemStorageConfig:
    root_path: str | Path
    prefix: str = ""
    create_root: bool = True
