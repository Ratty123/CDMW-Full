"""Mesh editor UI package."""

from __future__ import annotations

from importlib import import_module


_EXPORTS = {
    "MESH_EDITOR_ACTIONS": ("cdmw.ui.mesh_editor.actions", "MESH_EDITOR_ACTIONS"),
    "MeshEditorAction": ("cdmw.ui.mesh_editor.actions", "MeshEditorAction"),
    "MeshEditorActionBar": ("cdmw.ui.mesh_editor.action_bar", "MeshEditorActionBar"),
    "MeshEditorActionExecution": ("cdmw.ui.mesh_editor.controller", "MeshEditorActionExecution"),
    "MeshEditorController": ("cdmw.ui.mesh_editor.controller", "MeshEditorController"),
    "MeshEditorNativeUpdate": ("cdmw.ui.mesh_editor.controller", "MeshEditorNativeUpdate"),
    "MeshEditorSessionRequest": ("cdmw.ui.mesh_editor.session", "MeshEditorSessionRequest"),
    "MeshEditorTab": ("cdmw.ui.mesh_editor.tab", "MeshEditorTab"),
    "MeshEditorWorkspace": ("cdmw.ui.mesh_editor.workspace", "MeshEditorWorkspace"),
    "apply_native_update_to_host": ("cdmw.ui.mesh_editor.controller", "apply_native_update_to_host"),
    "mesh_editor_native_preview_data": (
        "cdmw.ui.mesh_editor.native_preview_runtime",
        "mesh_editor_native_preview_data",
    ),
    "mesh_editor_native_preview_command": (
        "cdmw.ui.mesh_editor.native_preview_runtime",
        "mesh_editor_native_preview_command",
    ),
    "mesh_editor_write_native_preview_package": (
        "cdmw.ui.mesh_editor.native_preview_runtime",
        "mesh_editor_write_native_preview_package",
    ),
    "mesh_editor_actions_by_key": ("cdmw.ui.mesh_editor.actions", "mesh_editor_actions_by_key"),
    "mesh_editor_actions_for_category": ("cdmw.ui.mesh_editor.actions", "mesh_editor_actions_for_category"),
    "validate_mesh_editor_actions": ("cdmw.ui.mesh_editor.actions", "validate_mesh_editor_actions"),
}


def __getattr__(name: str) -> object:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    module_name, attribute_name = target
    value = getattr(import_module(module_name), attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *_EXPORTS))

__all__ = [
    "MESH_EDITOR_ACTIONS",
    "MeshEditorAction",
    "MeshEditorActionBar",
    "MeshEditorActionExecution",
    "MeshEditorController",
    "MeshEditorNativeUpdate",
    "MeshEditorSessionRequest",
    "MeshEditorTab",
    "MeshEditorWorkspace",
    "apply_native_update_to_host",
    "mesh_editor_native_preview_data",
    "mesh_editor_native_preview_command",
    "mesh_editor_write_native_preview_package",
    "mesh_editor_actions_by_key",
    "mesh_editor_actions_for_category",
    "validate_mesh_editor_actions",
]
