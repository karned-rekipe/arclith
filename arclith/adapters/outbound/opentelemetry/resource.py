from __future__ import annotations

import os
import platform
import socket
import sys
from typing import Any

from arclith.infrastructure.config import OpenTelemetrySettings


def build_resource(settings: OpenTelemetrySettings) -> Any:
    from opentelemetry.sdk.resources import Resource

    attributes: dict[str, str | bool | int | float] = {}
    detectors = set(settings.resource.detectors)
    if "process" in detectors:
        attributes.update(
            {
                "process.pid": os.getpid(),
                "process.executable.name": os.path.basename(sys.executable),
                "process.runtime.name": platform.python_implementation(),
                "process.runtime.version": platform.python_version(),
            }
        )
    if "host" in detectors:
        attributes["host.name"] = socket.gethostname()
    attributes.update(settings.resource.attributes)
    if settings.service.name:
        attributes["service.name"] = settings.service.name
    if settings.service.namespace:
        attributes["service.namespace"] = settings.service.namespace
    if settings.service.version:
        attributes["service.version"] = settings.service.version
    instance_id = os.getenv(settings.service.instance_id_env, "").strip()
    if instance_id:
        attributes["service.instance.id"] = instance_id
    return Resource.create(attributes)
