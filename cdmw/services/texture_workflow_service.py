from __future__ import annotations

from dataclasses import dataclass
from importlib import import_module

from cdmw.services.texture_workflow_exports import TEXTURE_WORKFLOW_EXPORTS


@dataclass(slots=True)
class TextureWorkflowService:
    settings: object | None = None


__all__ = ("TextureWorkflowService",) + tuple(
    name for name in TEXTURE_WORKFLOW_EXPORTS if not name.startswith("_")
)


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = TEXTURE_WORKFLOW_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(TEXTURE_WORKFLOW_EXPORTS))
