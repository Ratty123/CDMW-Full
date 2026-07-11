"""Cached, lazy service boundary for UI mesh workflows."""

from __future__ import annotations

from importlib import import_module

from cdmw.services.mesh_workflow_exports import MESH_WORKFLOW_EXPORTS


__all__ = tuple(name for name in MESH_WORKFLOW_EXPORTS if not name.startswith("_"))


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = MESH_WORKFLOW_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(MESH_WORKFLOW_EXPORTS))
