"""Cached lazy service boundary for material-sidecar UI workflows."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    name: ("cdmw.core.material_sidecar_editor", name)
    for name in (
        "MaterialSidecarRelatedFile",
        "detect_material_sidecar_preview_model_candidates",
        "discover_material_sidecar_preview_overrides",
        "discover_material_sidecar_preview_overrides_for_edits",
        "discover_material_sidecar_values",
        "export_material_sidecar_mod_package",
        "is_material_sidecar_entry",
    )
}
__all__ = tuple(_EXPORTS)


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORTS))
