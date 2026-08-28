from __future__ import annotations

import importlib
import importlib.util
import json
import os
import sys
from pathlib import Path
from typing import Any


def load_graphs(config_path: str | Path) -> dict[str, Any]:
    path = Path(config_path).resolve()
    payload = json.loads(path.read_text(encoding="utf-8"))
    configured = payload.get("graphs")
    if not isinstance(configured, dict) or not configured:
        raise ValueError("langgraph.json doit declarer au moins un graphe")

    os.environ["ARCLITH_LANGGRAPH_PERSISTENCE_MODE"] = "agent_server"
    graphs: dict[str, Any] = {}
    for assistant_id, entrypoint in configured.items():
        if not isinstance(assistant_id, str) or not assistant_id.strip():
            raise ValueError("Chaque graphe LangGraph doit avoir un nom non vide")
        if not isinstance(entrypoint, str):
            raise ValueError(f"Entrypoint invalide pour le graphe {assistant_id}")
        graph = _load_entrypoint(entrypoint, base_dir=path.parent)
        if not callable(getattr(graph, "ainvoke", None)):
            raise TypeError(f"Le graphe {assistant_id} ne fournit pas ainvoke()")
        if not callable(getattr(graph, "astream", None)):
            raise TypeError(f"Le graphe {assistant_id} ne fournit pas astream()")
        graphs[assistant_id] = graph
    return graphs


def _load_entrypoint(entrypoint: str, *, base_dir: Path) -> Any:
    if ":" not in entrypoint:
        raise ValueError(
            "Un entrypoint LangGraph doit utiliser le format module:attribut"
        )
    module_spec, attribute = entrypoint.rsplit(":", 1)
    module = _load_module(module_spec, base_dir=base_dir)
    graph = getattr(module, attribute, None)
    if graph is None:
        raise AttributeError(f"Attribut LangGraph introuvable: {entrypoint}")
    return graph


def _load_module(module_spec: str, *, base_dir: Path) -> Any:
    if "/" not in module_spec and not module_spec.endswith(".py"):
        return importlib.import_module(module_spec)

    file_path = (base_dir / module_spec).resolve()
    if not file_path.is_file():
        raise FileNotFoundError(f"Module LangGraph introuvable: {file_path}")

    package_root, module_name = _module_name_from_path(file_path)
    if package_root is not None and module_name is not None:
        root = str(package_root)
        if root not in sys.path:
            sys.path.insert(0, root)
        return importlib.import_module(module_name)

    generated_name = f"arclith_runtime_graph_{abs(hash(file_path))}"
    spec = importlib.util.spec_from_file_location(generated_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Impossible de charger le module {file_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[generated_name] = module
    spec.loader.exec_module(module)
    return module


def _module_name_from_path(path: Path) -> tuple[Path | None, str | None]:
    parts = path.parts
    if "src" not in parts:
        return None, None
    src_index = len(parts) - 1 - tuple(reversed(parts)).index("src")
    relative = Path(*parts[src_index + 1 :]).with_suffix("")
    return Path(*parts[: src_index + 1]), ".".join(relative.parts)
