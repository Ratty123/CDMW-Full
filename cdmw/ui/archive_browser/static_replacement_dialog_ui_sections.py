"""UI section builders for static replacement dialog."""

from __future__ import annotations

import builtins as _builtins
from types import SimpleNamespace

from cdmw.constants import DEFAULT_UI_DATA_FONT_SIZE, DEFAULT_UI_FONT_SIZE, UI_FONT_SIZE_MAX, UI_FONT_SIZE_MIN
from cdmw.ui.mesh_editor.action_bar import MeshEditorActionBar
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key
from cdmw.ui.archive_browser.static_replacement_texture_folder_controller import (
    StaticReplacementTextureFolderScanController,
)
from cdmw.ui.archive_browser.static_replacement_texture_async import (
    AdvancedDdsRowScanRequest,
    StaticReplacementAdvancedDdsController,
)


class _LateLocalProxy:
    def __init__(self, getter: object, name: str) -> None:
        self._getter = getter
        self._name = name

    def _target(self) -> object:
        if not callable(self._getter):
            return self._getter
        return self._getter()

    def __getattr__(self, name: str) -> object:
        target = self._target()
        if target is None:
            raise NameError(f"late-bound UI object {self._name!r} is not available")
        return getattr(target, name)


def _context_builtin(context: dict[str, object], name: str) -> object:
    value = context.get(name)
    return value if callable(value) else getattr(_builtins, name)

def _alignment_dialog_font_sizes(context: dict[str, object]) -> dict[str, int]:
    settings = context.get("settings")
    if settings is None:
        settings = getattr(context.get("self"), "settings", None)

    def _read_size(key: str, default: int) -> int:
        try:
            value = int(settings.value(key, default))  # type: ignore[attr-defined]
        except (AttributeError, TypeError, ValueError):
            value = int(default)
        return clamp_font_points(value, default)

    ui_size = _read_size("appearance/ui_font_size", DEFAULT_UI_FONT_SIZE)
    data_size = _read_size("appearance/data_font_size", DEFAULT_UI_DATA_FONT_SIZE)
    return {"ui": ui_size, "data": data_size, "hint": int(small_font_points(ui_size))}


def _alignment_dialog_control_heights(context: dict[str, object], ui_size: int, data_size: int) -> dict[str, int]:
    """The dialog's control heights from the shared layout metrics (P11), not literal floors.

    At Compact and 10 pt they are the heights the dialog had: 16, 17 and 18 px.
    """

    from cdmw.constants import DEFAULT_UI_DENSITY
    from cdmw.ui.layout_metrics import layout_metrics, stylesheet_metrics

    settings = context.get("settings")
    if settings is None:
        settings = getattr(context.get("self"), "settings", None)
    try:
        density = settings.value("appearance/ui_density", DEFAULT_UI_DENSITY)  # type: ignore[attr-defined]
    except AttributeError:
        density = DEFAULT_UI_DENSITY
    button = stylesheet_metrics(layout_metrics(density, ui_size))["button_min_h"]
    field = stylesheet_metrics(layout_metrics(density, data_size))["button_min_h"] + 1
    return {"button": button, "field": field, "help_button": button + 2}

from cdmw.ui.archive_browser.static_replacement_dialog_factory_owners import (
    create_alignment_setup_options_transform_section as _create_alignment_setup_options_transform_section,
    create_alignment_mesh_geometry_preview_section as _create_alignment_mesh_geometry_preview_section,
    create_alignment_texture_material_section as _create_alignment_texture_material_section,
    create_alignment_source_parts_outliner_section as _create_alignment_source_parts_outliner_section,
)
from cdmw.ui.layout_metrics import clamp_font_points, small_font_points

def create_alignment_setup_options_transform_section(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_setup_options_transform_section(context, globals())

def create_alignment_mesh_geometry_preview_section(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_mesh_geometry_preview_section(context, globals())

def create_alignment_texture_material_section(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_texture_material_section(context, globals())

def create_alignment_source_parts_outliner_section(context: dict[str, object]) -> SimpleNamespace:
    return _create_alignment_source_parts_outliner_section(context, globals())
