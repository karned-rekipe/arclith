from __future__ import annotations

from typing import Any

# ── Supported adapters ────────────────────────────────────────────────────────

SUPPORTED_ADAPTERS = ["memory", "mongodb", "duckdb"]

# ── Config YAML templates (scoped — no root key) ──────────────────────────────

CONFIG_YAML: dict[str, str] = {
    "memory": "",  # memory needs no config file
    "mongodb": """\
multitenant: false   # true = URI + db_name résolus par requête via JWT → Vault
db_name: {db_name}   # uri → secrets.yaml ou Vault (fallback single-tenant)
""",
    "duckdb": """\
multitenant: false
path: {path}
""",
}

# ── Python repository subclass templates ─────────────────────────────────────

REPO_PYTHON: dict[str, str] = {
    "memory": """\
from arclith.adapters.output.memory.repository import InMemoryRepository
from {domain_import}.models.{snake} import {pascal}
from {domain_import}.ports.output.{snake}_repository import {pascal}Repository


class InMemory{pascal}Repository(InMemoryRepository[{pascal}], {pascal}Repository):
    pass  # TODO: add custom query methods if needed
""",
    "mongodb": """\
from arclith.adapters.output.mongodb.config import MongoDBConfig
from arclith.adapters.output.mongodb.repository import MongoDBRepository
from arclith.domain.ports.logger import Logger
from {domain_import}.models.{snake} import {pascal}
from {domain_import}.ports.output.{snake}_repository import {pascal}Repository


class MongoDB{pascal}Repository(MongoDBRepository[{pascal}], {pascal}Repository):
    def __init__(self, config: MongoDBConfig, logger: Logger) -> None:
        super().__init__(config, {pascal}, logger)

    # TODO: add custom query methods here
    # async def find_by_name(self, name: str) -> list[{pascal}]:
    #     async with self._collection() as col:
    #         return [
    #             self._from_doc(doc)
    #             async for doc in col.find({{"name": name, "deleted_at": None}})
    #         ]
""",
    "duckdb": """\
from arclith.adapters.output.duckdb.repository import DuckDBRepository
from {domain_import}.models.{snake} import {pascal}
from {domain_import}.ports.output.{snake}_repository import {pascal}Repository


class DuckDB{pascal}Repository(DuckDBRepository[{pascal}], {pascal}Repository):
    def __init__(self, path: str) -> None:
        super().__init__(path, {pascal})

    # TODO: add custom query methods here
    # async def find_by_name(self, name: str) -> list[{pascal}]:
    #     rows = self._fetch(
    #         f"SELECT * FROM {{self._table}} WHERE deleted_at IS NULL AND lower(name) LIKE ?",
    #         [f"%{{name.lower()}}%"],
    #     )
    #     return [self._row_to_entity(r) for r in rows]
""",
}

# ── repository.py re-export template ─────────────────────────────────────────

REPO_REEXPORT: dict[str, str] = {
    "memory": """\
from {adapters_import}.output.memory.repositories.{snake}_repository import InMemory{pascal}Repository

__all__ = ["InMemory{pascal}Repository"]
""",
    "mongodb": """\
from {adapters_import}.output.mongodb.repositories.{snake}_repository import MongoDB{pascal}Repository

__all__ = ["MongoDB{pascal}Repository"]
""",
    "duckdb": """\
from {adapters_import}.output.duckdb.repositories.{snake}_repository import DuckDB{pascal}Repository

__all__ = ["DuckDB{pascal}Repository"]
""",
}

# ── Container template (full file, regenerated with all installed adapters) ───

_CONTAINER_HEADER = """\
from __future__ import annotations

from {application_import}.services.{snake}_service import {pascal}Service
from arclith import Arclith, AdapterRegistry
from arclith.infrastructure.config import AppConfig
from arclith.domain.ports.logger import Logger
from {domain_import}.models.{snake} import {pascal}
from {domain_import}.ports.output.{snake}_repository import {pascal}Repository

"""

_CONTAINER_FACTORY: dict[str, str] = {
    "memory": """\
def _build_memory(cfg: AppConfig, log: Logger) -> {pascal}Repository:
    from {adapters_import}.output.memory.repository import InMemory{pascal}Repository
    return InMemory{pascal}Repository()

""",
    "mongodb": """\
def _build_mongodb(cfg: AppConfig, log: Logger) -> {pascal}Repository:
    from {adapters_import}.output.mongodb.repository import MongoDB{pascal}Repository
    from arclith.adapters.output.mongodb.config import MongoDBConfig
    mongo = cfg.adapters.mongodb
    if mongo is None:
        raise RuntimeError("MongoDB settings are required when repository=mongodb")
    return MongoDB{pascal}Repository(MongoDBConfig(uri=mongo.uri, db_name=mongo.db_name), log)

""",
    "duckdb": """\
def _build_duckdb(cfg: AppConfig, log: Logger) -> {pascal}Repository:
    from {adapters_import}.output.duckdb.repository import DuckDB{pascal}Repository
    duckdb = cfg.adapters.duckdb
    if duckdb is None:
        raise RuntimeError("DuckDB settings are required when repository=duckdb")
    return DuckDB{pascal}Repository(duckdb.path)

""",
}

_CONTAINER_FOOTER = """\
_registry: AdapterRegistry[{pascal}] = (
    AdapterRegistry()
{registrations}
)


def build_{snake}_service(arclith: Arclith) -> tuple[{pascal}Service, Logger]:
    arclith.logger.info("🗄️ Repository adapter selected", adapter=arclith.config.adapters.repository)
    repo: {pascal}Repository = _registry.build(arclith.config, arclith.logger)
    return {pascal}Service(repo, arclith.logger, arclith.config.soft_delete.retention_days), arclith.logger
"""


def render_container(pascal: str, snake: str, installed_adapters: list[str], import_vars: dict[str, str]) -> str:
    """Generate the full container file content for a given entity and its adapters."""
    # memory is always included (arclith built-in, needs no extra files)
    adapters = list(dict.fromkeys(["memory"] + installed_adapters))
    vars = {"pascal": pascal, "snake": snake, **import_vars}

    header = _CONTAINER_HEADER.format(**vars)
    factories = "".join(
        _CONTAINER_FACTORY[a].format(**vars)
        for a in adapters
        if a in _CONTAINER_FACTORY
    )
    registrations = "\n".join(
        f"    .register(\"{a}\", _build_{a})"
        for a in adapters
        if a in _CONTAINER_FACTORY
    )
    footer = _CONTAINER_FOOTER.format(**vars, registrations=registrations)
    return header + factories + footer


def render(template: str, vars: dict[str, Any]) -> str:
    return template.format(**vars)
