from __future__ import annotations

import weakref
from typing import Callable, Optional

from PySide6.QtCore import QSettings, QTimer
from PySide6.QtWidgets import QApplication, QTreeWidget

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

_COLUMN_SAVE_DEBOUNCE_MS = 400
_SETTINGS_SYNC_DEBOUNCE_MS = 650

_settings_sync_timer: Optional[QTimer] = None
_settings_sync_pending: list[QSettings] = []


def _flush_requested_settings_syncs() -> None:
    pending = list(_settings_sync_pending)
    _settings_sync_pending.clear()
    for settings in pending:
        try:
            settings.sync()
        except (RuntimeError, AttributeError):
            continue


def request_settings_sync(settings: QSettings) -> None:
    """Flush `settings` to disk once, after the writes around it have settled.

    A `QSettings.sync()` is a synchronous disk write. Calling it from a signal
    that fires per resized column meant a burst of writes cost one flush each --
    hundreds during a single drag of a column divider, and fifteen during an
    interface-language change, which re-lays out every translated header. The
    flush is coalesced here so a burst costs one.

    The timer is parented to the application rather than left unparented,
    because a parentless Qt object outlives its interpreter state and takes the
    test suite down somewhere unrelated.
    """
    global _settings_sync_timer
    if not any(existing is settings for existing in _settings_sync_pending):
        _settings_sync_pending.append(settings)
    if _settings_sync_timer is None:
        owner = QApplication.instance()
        if owner is None:
            # No event loop to defer onto; the caller still needs the write.
            _flush_requested_settings_syncs()
            return
        _settings_sync_timer = QTimer(owner)
        _settings_sync_timer.setSingleShot(True)
        _settings_sync_timer.timeout.connect(_flush_requested_settings_syncs)
    _settings_sync_timer.start(_SETTINGS_SYNC_DEBOUNCE_MS)


_pending_column_saves: "weakref.WeakKeyDictionary[QTreeWidget, tuple[QTimer, Callable[[], None]]]" = (
    weakref.WeakKeyDictionary()
)


def flush_pending_tree_column_saves() -> None:
    """Write every debounced column layout now, and flush the settings behind it.

    Debouncing keeps a drag off the disk, but it also opens a window in which a
    layout the reader just changed is only in memory. Closing the window, or any
    other point that must not lose it, calls this.
    """
    for tree, entry in list(_pending_column_saves.items()):
        timer, save = entry
        try:
            if not timer.isActive():
                continue
            timer.stop()
            save()
        except RuntimeError:
            # The tree's C++ object can be gone while its wrapper is alive.
            continue
    _flush_requested_settings_syncs()


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
        request_settings_sync(settings)

    # `sectionResized` fires once per pointer sample while a divider is dragged,
    # and once per header whose text a language change re-laid out. Saving from
    # each one wrote the whole column layout and flushed it to disk; the writes
    # are coalesced onto the settled layout instead.
    save_timer = QTimer(tree)
    save_timer.setSingleShot(True)
    save_timer.setInterval(_COLUMN_SAVE_DEBOUNCE_MS)
    save_timer.timeout.connect(_save)
    _pending_column_saves[tree] = (save_timer, _save)

    if restore_later:
        QTimer.singleShot(0, _restore)
    else:
        _restore()
    header.sectionResized.connect(lambda *_args: save_timer.start())
    header.sectionMoved.connect(lambda *_args: save_timer.start())


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
