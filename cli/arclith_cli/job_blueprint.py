"""Render a typed job feature without inventing business work or a transport."""

from pathlib import Path
from textwrap import dedent

from arclith_cli.application_blueprint_files import with_package_initializers
from arclith_cli.entity_scanner import EntityInfo
from arclith_cli.job_spec import JobSpec
from arclith_cli.project_paths import ProjectPaths
from arclith_cli.rename import EntityNames

# Each tuple is an explicit application operation, not a dynamic dispatcher.
_OPERATIONS = (
    ("submit", "Submit", "Command"),
    ("get_status", "GetStatus", "Query"),
    ("cancel", "Cancel", "Command"),
    ("retry", "Retry", "Command"),
    ("get_result", "GetResult", "Query"),
)


def render_job_blueprint(
    paths: ProjectPaths,
    entity: EntityInfo | None,
    feature: str,
    spec: JobSpec,
) -> dict[Path, str]:
    name = EntityNames.from_input(feature).pascal
    model_module = paths.import_path("domain", "models", f"{feature}_job")
    container_module = paths.import_path("infrastructure", "containers", feature)
    files = {
        paths.domain_models / f"{feature}_job.py": _models(spec, entity),
        paths.package_root / "application" / "jobs" / f"{feature}.py": _handler(
            name, spec, model_module
        ),
        paths.containers / f"{feature}.py": _container(
            paths, feature, name, spec, model_module
        ),
        paths.root / "tests" / "application" / f"test_{feature}_job.py": _tests(
            paths,
            feature,
            name,
            spec,
            model_module,
            container_module,
            entity,
        ),
        paths.root / "docs" / "blueprints" / f"{feature}-job.md": _documentation(
            feature, spec, entity
        ),
    }
    for operation, prefix, input_kind in _OPERATIONS:
        operation_class = f"{prefix}{name}"
        port_module = paths.import_path(
            "domain", "ports", "inbound", f"{operation}_{feature}"
        )
        files[paths.inbound_ports / f"{operation}_{feature}.py"] = _port(
            operation,
            operation_class,
            input_kind,
            spec,
            model_module,
        )
        files[paths.application_use_cases / f"{operation}_{feature}.py"] = _use_case(
            operation,
            operation_class,
            input_kind,
            spec,
            model_module,
            port_module,
        )
    return with_package_initializers(paths, files)


def _models(spec: JobSpec, entity: EntityInfo | None) -> str:
    entity_imports = ""
    entity_fields = ""
    if entity is not None:
        entity_imports = "from uuid import UUID as _UUID\nfrom pydantic import field_validator as _field_validator\n"
        entity_fields = dedent(f"""\
            # References {entity.pascal}; existence/authorization belongs to the handler.
            entity_id: str

            @_field_validator("entity_id")
            @classmethod
            def validate_entity_id(cls, value: str) -> str:
                return str(_UUID(value))
        """)
        entity_fields = (
            "\n".join(
                "    " + line if line else "" for line in entity_fields.splitlines()
            )
            + "\n"
        )
    return (
        "from pydantic import BaseModel as _BaseModel, ConfigDict as _ConfigDict\n"
        + entity_imports
        + f"\n\nclass {spec.request}(_BaseModel):\n"
        + '    """Define the small, JSON-native business request here."""\n\n'
        + '    model_config = _ConfigDict(frozen=True, extra="forbid")\n'
        + entity_fields
        + f"\n\nclass {spec.result}(_BaseModel):\n"
        + '    """Define the small result or external storage reference here."""\n\n'
        + '    model_config = _ConfigDict(frozen=True, extra="forbid")\n'
    )


def _handler(name: str, spec: JobSpec, model_module: str) -> str:
    return dedent(f'''\
        from arclith.domain.ports.outbound.job_runner import JobContext, JobHandler
        from {model_module} import {spec.request} as _Request, {spec.result} as _Result


        class {name}Handler(JobHandler[_Request, _Result]):
            async def execute(self, request: _Request, context: JobContext) -> _Result:
                """Implement business work and checkpoint cancellation at safe points.

                The generated contract tests inject their own deterministic fake.
                This production extension point deliberately cannot report success.
                """
                raise NotImplementedError("Implement the job handler")
    ''')


def _port(
    operation: str, name: str, input_kind: str, spec: JobSpec, model_module: str
) -> str:
    input_fields = (
        "    request: _Request\n    idempotency_key: str | None = None"
        if operation == "submit"
        else "    job_id: JobId"
    )
    output_field = (
        "    job_id: JobId"
        if operation == "submit"
        else "    result: JobResult[_Result]"
        if operation == "get_result"
        else "    job: JobRecord[_Request, _Result]"
    )
    job_imports = "JobId"
    if operation == "get_result":
        job_imports += ", JobResult"
    elif operation != "submit":
        job_imports += ", JobRecord"
    model_imports = f"{spec.request} as _Request"
    if operation == "get_result":
        model_imports = f"{spec.result} as _Result"
    elif operation != "submit":
        model_imports += f", {spec.result} as _Result"
    return (
        "from abc import ABC, abstractmethod\nfrom pydantic import BaseModel, ConfigDict\n\n"
        f"from arclith.domain.models.job import {job_imports}\n"
        f"from {model_module} import {model_imports}\n\n\n"
        f"class {name}{input_kind}(BaseModel):\n"
        '    model_config = ConfigDict(frozen=True, extra="forbid")\n'
        f"{input_fields}\n\n\nclass {name}Result(BaseModel):\n"
        '    model_config = ConfigDict(frozen=True, extra="forbid")\n'
        f"{output_field}\n\n\nclass {name}Port(ABC):\n"
        f"    @abstractmethod\n    async def execute(self, request: {name}{input_kind}) -> {name}Result:\n"
        '        """Execute the typed application operation."""\n'
        "        raise NotImplementedError\n"
    )


def _use_case(
    operation: str,
    name: str,
    input_kind: str,
    spec: JobSpec,
    model_module: str,
    port_module: str,
) -> str:
    extra_import = ""
    if operation == "submit":
        extra_import = "from arclith.domain.models.job import JobRequest\n"
        body = dedent(f"""\
            job_id = await self._service.submit(JobRequest[_Request](
                payload=request.request, idempotency_key=request.idempotency_key,
                cancellable={spec.cancellable!r}, max_attempts={spec.max_attempts},
                retention_days={spec.retention_days},
            ))
            return {name}Result(job_id=job_id)
        """)
    else:
        field = "result" if operation == "get_result" else "job"
        body = f"return {name}Result({field}=await self._service.{operation}(request.job_id))\n"
    indented = "\n".join(
        "        " + line if line else "" for line in body.splitlines()
    )
    return (
        "from arclith.application.services.job_service import JobService\n"
        + extra_import
        + f"from {model_module} import {spec.request} as _Request, {spec.result} as _Result\n"
        + f"from {port_module} import {name}{input_kind}, {name}Port, {name}Result\n\n\n"
        + f"class {name}UseCase({name}Port):\n"
        + "    def __init__(self, service: JobService[_Request, _Result]) -> None:\n"
        + "        self._service = service\n\n"
        + f"    async def execute(self, request: {name}{input_kind}) -> {name}Result:\n"
        + indented
        + "\n"
    )


def _container(
    paths: ProjectPaths, feature: str, name: str, spec: JobSpec, model_module: str
) -> str:
    imports, fields, arguments = [], [], []
    for operation, prefix, _ in _OPERATIONS:
        operation_class = f"{prefix}{name}"
        imports.append(
            f"from {paths.import_path('domain', 'ports', 'inbound', f'{operation}_{feature}')} import {operation_class}Port"
        )
        imports.append(
            f"from {paths.import_path('application', 'use_cases', f'{operation}_{feature}')} import {operation_class}UseCase"
        )
        fields.append(f"    {operation}: {operation_class}Port")
        arguments.append(f"        {operation}={operation_class}UseCase(service),")
    return (
        "from dataclasses import dataclass\n\n"
        "from arclith.application.services.job_service import JobService\n"
        "from arclith.domain.ports.outbound.job_runner import JobRunnerPort\n"
        "from arclith.domain.ports.outbound.job_store import JobStorePort\n"
        f"from {model_module} import {spec.request} as _Request, {spec.result} as _Result\n"
        + "\n".join(imports)
        + f"\n\n\n@dataclass(frozen=True)\nclass {name}UseCases:\n"
        + "\n".join(fields)
        + f"\n\n\ndef build_{feature}_use_cases(\n"
        + "    runner: JobRunnerPort[_Request, _Result], store: JobStorePort[_Request, _Result],\n"
        + f") -> {name}UseCases:\n"
        + '    """Inject adapters explicitly; runner and queries must share this store."""\n'
        + "    service = JobService(runner, store)\n"
        + f"    return {name}UseCases(\n"
        + "\n".join(arguments)
        + "\n    )\n"
    )


def _tests(
    paths: ProjectPaths,
    feature: str,
    name: str,
    spec: JobSpec,
    model_module: str,
    container_module: str,
    entity: EntityInfo | None,
) -> str:
    request_args = (
        'entity_id="01951234-5678-7abc-8ef0-123456789abc"' if entity is not None else ""
    )
    return dedent(f"""\
        import pytest

        from arclith.adapters.outbound.memory.job_runner import InMemoryJobRunner
        from arclith.adapters.outbound.memory.job_store import InMemoryJobStore
        from arclith.domain.errors.job import JobResultUnavailable, JobTransitionError
        from arclith.domain.models.job import JobStatus
        from arclith.domain.ports.outbound.job_runner import JobHandler

        from {model_module} import {spec.request} as _Request, {spec.result} as _Result
        from {paths.import_path("application", "jobs", feature)} import {name}Handler
        from {paths.import_path("domain", "ports", "inbound", f"submit_{feature}")} import Submit{name}Command
        from {paths.import_path("domain", "ports", "inbound", f"get_status_{feature}")} import GetStatus{name}Query
        from {paths.import_path("domain", "ports", "inbound", f"get_result_{feature}")} import GetResult{name}Query
        from {paths.import_path("domain", "ports", "inbound", f"cancel_{feature}")} import Cancel{name}Command
        from {container_module} import build_{feature}_use_cases


        class FakeHandler(JobHandler[_Request, _Result]):
            async def execute(self, request, context):
                await context.cancellation.checkpoint()
                return _Result()


        def compose(handler):
            store = InMemoryJobStore(_Request, _Result)
            runner = InMemoryJobRunner(store, handler)
            return runner, build_{feature}_use_cases(runner, store)


        @pytest.mark.asyncio
        async def test_submission_status_and_fake_execution():
            runner, use_cases = compose(FakeHandler())
            command = Submit{name}Command(request=_Request({request_args}), idempotency_key="example")
            first = await use_cases.submit.execute(command)
            duplicate = await use_cases.submit.execute(command)
            assert first.job_id == duplicate.job_id
            before = await use_cases.get_status.execute(GetStatus{name}Query(job_id=first.job_id))
            assert before.job.status is JobStatus.QUEUED
            with pytest.raises(JobResultUnavailable):
                await use_cases.get_result.execute(GetResult{name}Query(job_id=first.job_id))
            assert (await runner.run(first.job_id)).status is JobStatus.SUCCEEDED
            result = await use_cases.get_result.execute(GetResult{name}Query(job_id=first.job_id))
            assert isinstance(result.result.payload, _Result)


        @pytest.mark.asyncio
        async def test_production_handler_is_an_explicit_extension_point():
            runner, use_cases = compose({name}Handler())
            job = await use_cases.submit.execute(Submit{name}Command(request=_Request({request_args})))
            outcome = await runner.run(job.job_id)
            assert outcome.status is JobStatus.FAILED
            assert outcome.error.code == "handler_not_implemented"


        @pytest.mark.asyncio
        async def test_cancellation_policy():
            _, use_cases = compose(FakeHandler())
            job = await use_cases.submit.execute(Submit{name}Command(request=_Request({request_args})))
            command = Cancel{name}Command(job_id=job.job_id)
            if {spec.cancellable!r}:
                assert (await use_cases.cancel.execute(command)).job.status is JobStatus.CANCELLED
            else:
                with pytest.raises(JobTransitionError):
                    await use_cases.cancel.execute(command)
    """)


def _documentation(feature: str, spec: JobSpec, entity: EntityInfo | None) -> str:
    target = (
        f"référence `{entity.pascal}` par `entity_id` (UUID sérialisé en chaîne)"
        if entity is not None
        else "standalone, sans entité"
    )
    return dedent(f"""\
        # Job `{feature}`

        Cible : {target}. Spec V1, manifeste V3, paramètres portables et empreintes
        SHA-256. La référence d'entité ne valide ni existence ni autorisation : le
        handler métier les vérifie explicitement. Le job ne modifie pas son entité.

        Compléter `{spec.request}`, `{spec.result}` et le handler sous
        `application/jobs/{feature}.py`. Le handler initial lève NotImplementedError.
        Les tests utilisent un fake explicite, puis vérifient l'échec de ce handler.

        Le container expose submit, get_status, cancel, retry, get_result et exige
        un JobRunnerPort et le même JobStorePort. Les erreurs partagées sont dans
        `arclith.domain.errors.job`. Aucun transport, broker ou SDK n'est installé.

        Pour le développement, instancier InMemoryJobStore(Request, Result), puis
        InMemoryJobRunner(store, handler). Soumettre ne lance aucune tâche : appeler
        explicitement `await runner.run(job_id)` et posséder/attendre cet appel.
        Ce store/runner est local à une boucle asyncio, **non durable**, sans reprise
        après arrêt. Un handler bloquant bloque la boucle ; choisir un adapter
        adapté aux calculs CPU ou à la production.

        Cycle : queued → running → succeeded/failed/cancelled. Max tentatives :
        {spec.max_attempts}, aucun retry automatique. Retry après failed conserve le
        JobId et l'historique, incrémente attempt et remet le job en queued.
        Cancel queued est immédiat ; cancel running demande une annulation
        coopérative via `await context.cancellation.checkpoint()`. Un handler qui
        termine avant reconnaissance peut réussir. Cancellable : {spec.cancellable}.

        Même clé + requête/politique canonique renvoie le job existant ; contenu
        différent lève JobIdempotencyConflict. Après succès, get_result fournit une
        enveloppe V1. Avant succès : JobResultUnavailable. La progression optionnelle
        est un pourcentage fini de 0 à 100, via `context.report_progress`.

        Rétention mémoire : {spec.retention_days} jours après fin de la dernière
        tentative, nettoyage explicite `await store.purge_expired()`. Aucun timer.
        Purger supprime aussi la clé d'idempotence ; sa réutilisation crée un job.
        Les jobs actifs ne sont pas purgés.

        Requête/résultat : valeurs JSON natives, modèles Pydantic, au plus 64 KiB
        et 32 niveaux, sans secrets. Utiliser une référence pour les gros résultats
        et récupérer les credentials via un port hors du payload. Dates/UUID métier
        doivent être encodés explicitement en chaînes. Les erreurs publiques ont
        des codes fixes, sans exception brute. Instrumenter le handler avec JobId,
        correlation ID, tentative, durée, statut ; éviter payload et secrets.

        Job décrit l'exécution, batch la cardinalité, workflow les étapes/reprises.
        Pour RabbitMQ/Celery/Kubernetes, implémenter les ports et leurs garanties de
        stockage/coordination, puis réinjecter le container sans changer ses use cases.
        Ne pas promettre exactly-once distribué ; rendre les effets métier idempotents.
    """)
