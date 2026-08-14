import subprocess
import sys

import pytest

import arclith


def test_getattr_console_logger():
    cls = arclith.ConsoleLogger
    from arclith.adapters.outbound.console.logger import ConsoleLogger

    assert cls is ConsoleLogger


def test_getattr_unknown_raises():
    with pytest.raises(AttributeError):
        _ = arclith.NonExistentSymbol  # type: ignore[attr-defined]


def test_public_project_layout_exports():
    layout = arclith.canonical_project_layout("arclith_sample")

    assert isinstance(layout, arclith.ProjectLayout)
    assert layout.kind is arclith.ProjectLayoutKind.SRC


def test_public_repository_registry_exports():
    registry = arclith.default_repository_registry(arclith.Entity)

    assert isinstance(registry, arclith.RepositoryRegistry)
    assert arclith.build_repository is not None


def test_public_file_storage_exports():
    registry = arclith.default_file_storage_registry()

    assert isinstance(registry, arclith.FileStorageRegistry)
    assert arclith.build_file_storage is not None
    assert arclith.FilesystemFileStorage is not None
    assert arclith.S3FileStorage is not None
    assert arclith.GCSFileStorage is not None


def test_import_arclith_does_not_require_s3_extra():
    script = """
import importlib.abc
import sys


class BlockS3Extras(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "boto3" or fullname.startswith("boto3."):
            raise ModuleNotFoundError(fullname)
        if fullname == "botocore" or fullname.startswith("botocore."):
            raise ModuleNotFoundError(fullname)
        return None


sys.meta_path.insert(0, BlockS3Extras())

import arclith

arclith.default_file_storage_registry()
assert arclith.S3FileStorage is not None
print(arclith.__name__)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "arclith"


def test_import_arclith_does_not_require_gcs_extra():
    script = """
import importlib.abc
import sys


class BlockGCSExtras(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path, target=None):
        if fullname == "google" or fullname.startswith("google."):
            raise ModuleNotFoundError(fullname)
        return None


sys.meta_path.insert(0, BlockGCSExtras())

import arclith

arclith.default_file_storage_registry()
assert arclith.GCSFileStorage is not None
print(arclith.__name__)
"""
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "arclith"
