from __future__ import annotations

from typing import Callable, Optional

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QTreeWidget

_RENDER_DIAGNOSTIC_MODE_CODES = {
    "lit": 0,
    "white_uniform": 1,
    "shader_marker": 2,
    "fragcoord_checker": 3,
    "vertex_color": 4,
    "normal": 5,
    "uv": 6,
    "cpu_average": 7,
    "base_direct": 8,
    "base_no_tint": 9,
    "base_alpha": 10,
    "normal_raw": 11,
    "material_raw": 12,
    "height_raw": 13,
    "sampler_swap_base_on_unit2": 14,
    "sampler_swap_material_on_unit0": 15,
    "base_color": 16,
    "texture_probe": 17,
    "height_depth": 18,
    "material_response": 19,
    "metal_shine": 20,
    "roughness_response": 21,
    "rich_lit": 22,
    "height_calibrated": 23,
    "relief_control_test": 24,
    "matcap": 25,
    "wireframe": 26,
    "vertex_normals": 27,
    "uv_checker": 28,
    "source_pbr_preview": 29,
    "cd_runtime_approx": 30,
}

def persistent_tree_column_widths_key(settings_key: str) -> str:
    return f"{str(settings_key or '').strip()}/column_widths"


def persistent_tree_column_order_key(settings_key: str) -> str:
    return f"{str(settings_key or '').strip()}/column_order"


def _persistent_int_list(value: object) -> tuple[int, ...]:
    if isinstance(value, (list, tuple)):
        raw_values = value
    else:
        raw_values = str(value or "").replace(";", ",").split(",")
    parsed: list[int] = []
    for raw_value in raw_values:
        try:
            parsed.append(int(str(raw_value).strip()))
        except (TypeError, ValueError):
            return ()
    return tuple(parsed)


def has_persistent_tree_column_widths(
    settings: QSettings,
    settings_key: str,
    column_count: int,
    *,
    minimum_width: int = 1,
) -> bool:
    widths = _persistent_int_list(settings.value(persistent_tree_column_widths_key(settings_key), ""))
    return len(widths) == int(column_count) and all(width >= int(minimum_width) for width in widths)


def restore_persistent_tree_column_widths(
    tree: QTreeWidget,
    settings: QSettings,
    settings_key: str,
    *,
    minimum_width: int = 1,
) -> bool:
    column_count = int(tree.columnCount())
    widths = _persistent_int_list(settings.value(persistent_tree_column_widths_key(settings_key), ""))
    if len(widths) != column_count:
        return False
    if any(width < int(minimum_width) for width in widths):
        return False
    header = tree.header()
    for index, width in enumerate(widths):
        header.resizeSection(index, int(width))
    return True


def restore_persistent_tree_column_order(tree: QTreeWidget, settings: QSettings, settings_key: str) -> bool:
    column_count = int(tree.columnCount())
    order = _persistent_int_list(settings.value(persistent_tree_column_order_key(settings_key), ""))
    if len(order) != column_count or sorted(order) != list(range(column_count)):
        return False
    header = tree.header()
    for visual_index, logical_index in enumerate(order):
        current_visual = header.visualIndex(int(logical_index))
        if current_visual >= 0 and current_visual != visual_index:
            header.moveSection(current_visual, visual_index)
    return True


def make_tree_columns_persistent(
    tree: QTreeWidget,
    settings: QSettings,
    settings_key: str,
    *,
    restore_later: bool = True,
    minimum_width: int = 1,
    save_callback: Optional[Callable[[], None]] = None,
    persist_order: bool = True,
    sections_movable: bool = True,
) -> None:
    header = tree.header()
    header.setSectionsMovable(bool(sections_movable))

    def _restore() -> None:
        restore_persistent_tree_column_widths(tree, settings, settings_key, minimum_width=minimum_width)
        if persist_order:
            restore_persistent_tree_column_order(tree, settings, settings_key)

    def _save() -> None:
        column_count = int(tree.columnCount())
        widths = [str(max(int(minimum_width), int(header.sectionSize(index)))) for index in range(column_count)]
        settings.setValue(persistent_tree_column_widths_key(settings_key), ",".join(widths))
        if persist_order:
            order = [str(int(header.logicalIndex(visual_index))) for visual_index in range(column_count)]
            settings.setValue(persistent_tree_column_order_key(settings_key), ",".join(order))
        if save_callback is not None:
            try:
                save_callback()
            except Exception:
                pass
        settings.sync()

    if restore_later:
        QTimer.singleShot(0, _restore)
    else:
        _restore()
    header.sectionResized.connect(lambda *_args: _save())
    header.sectionMoved.connect(lambda *_args: _save())


from cdmw.ui.layout_utils import (
    _rebalance_splitter_sizes,
    available_layout_size_for,
    available_screen_size_for,
    available_screen_width_for,
    build_bounded_splitter_sizes,
    build_responsive_splitter_sizes,
    clamp_splitter_sizes,
    responsive_screen_compact_scale,
    responsive_sidebar_bounds,
    scaled_px,
    set_sidebar_width_policy,
    ui_scale_for,
)

























from cdmw.ui.panel_widgets import CollapsibleSection, EmptyStatePanel, EmptyStateTreeWidget, FlatSectionPanel







from cdmw.ui.preview_widgets import MediaPreviewWidget, PreviewLabel, PreviewScrollArea




from cdmw.ui.native_preview_panel import NativePreviewPanel







from cdmw.ui.text_preview_widgets import (
    ArchiveDetailsEditor,
    ArchiveDetailsHighlighter,
    CodePreviewEditor,
    LogHighlighter,
    PreviewSyntaxHighlighter,
)





from cdmw.ui.shell.help_dialogs import AboutDialog, QuickStartDialog


_MODEL_PREVIEW_COMPAT_EXPORTS = {
    "_BatchRenderDiagnostic": "BatchRenderDiagnostic",
    "_FramebufferVisibilitySample": "FramebufferVisibilitySample",
    "_ModelPreviewDrawBatch": "ModelPreviewDrawBatch",
    "_TextureVisibilitySample": "TextureVisibilitySample",
}

_WHEEL_GUARD_COMPAT_EXPORTS = frozenset(("NonIntrusiveWheelGuard", "ensure_app_wheel_guard"))


def __getattr__(name: str) -> object:
    if name in _WHEEL_GUARD_COMPAT_EXPORTS:
        from cdmw.ui import wheel_guard

        value = getattr(wheel_guard, name)
        globals()[name] = value
        return value
    target = _MODEL_PREVIEW_COMPAT_EXPORTS.get(name)
    if target is None:
        raise AttributeError(name)
    from cdmw.services import preview_rendering_service as model_preview_prepare

    value = getattr(model_preview_prepare, target)
    globals()[name] = value
    return value
