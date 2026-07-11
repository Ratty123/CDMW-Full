"""Shell theme selection boundary."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import QSettings, Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QAbstractItemView, QHeaderView, QWidget

from cdmw.constants import (
    DEFAULT_UI_DATA_FONT_SIZE,
    DEFAULT_UI_DENSITY,
    DEFAULT_UI_FONT_FAMILY,
    DEFAULT_UI_FONT_SIZE,
    DEFAULT_UI_LOG_COLOR_SCHEME,
    DEFAULT_UI_LOG_FONT_BOLD,
    DEFAULT_UI_LOG_FONT_FAMILY,
    DEFAULT_UI_LOG_FONT_SIZE,
    DEFAULT_UI_LOG_TEXT_STYLE,
    DEFAULT_UI_PREVIEW_COLOR_SCHEME,
    DEFAULT_UI_THEME,
    LOG_FONT_FAMILY_OPTIONS,
    UI_FONT_SIZE_MAX,
    UI_FONT_SIZE_MIN,
    UI_LOG_TEXT_STYLE_OPTIONS,
    UI_TEXT_COLOR_SCHEME_OPTIONS,
)
from cdmw.ui.shell.responsiveness_controller import (
    responsive_control_scale_for_resolution as _responsive_control_scale_for_resolution,
)
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.shell.theme_overlay import ThemeChangeBusyOverlay
from cdmw.ui.shell.settings_bridge import (
    read_bool_setting as _read_bool_setting,
    read_int_setting as _read_int_setting,
)
from cdmw.ui.app_icon import load_app_icon
from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_palette, build_app_stylesheet
from cdmw.ui.layout_utils import available_layout_size_for, available_screen_size_for


def _same_font(left: QFont, right: QFont) -> bool:
    return QFont(left).toString() == QFont(right).toString()


_UI_FONT_CLASS_NAMES = ("QWidget",)
_DATA_FONT_CLASS_NAMES = (
    "QListView",
    "QListWidget",
    "QTreeView",
    "QTreeWidget",
    "QTableView",
    "QTableWidget",
    "QHeaderView",
)


def _install_app_fonts(app: QApplication, app_font: QFont, data_font: QFont) -> None:
    if not _same_font(app.font(), app_font):
        app.setFont(app_font)
    for class_name in _UI_FONT_CLASS_NAMES:
        app.setFont(app_font, class_name)
    for class_name in _DATA_FONT_CLASS_NAMES:
        app.setFont(data_font, class_name)


def _apply_ui_fonts_to_widget_tree(root: QWidget, ui_font: QFont) -> None:
    for widget in (root, *root.findChildren(QWidget)):
        try:
            managed = bool(widget.property("_cdmw_global_font_managed"))
            inherited = int(widget.font().resolveMask()) == 0
        except RuntimeError:
            continue
        if not (managed or inherited):
            continue
        if not _same_font(widget.font(), ui_font):
            widget.setFont(ui_font)
        widget.setProperty("_cdmw_global_font_managed", True)


def _apply_data_fonts_to_widget_tree(root: QWidget, data_font: QFont) -> None:
    for widget in root.findChildren(QAbstractItemView):
        if not _same_font(widget.font(), data_font):
            widget.setFont(data_font)
    for header in root.findChildren(QHeaderView):
        if not _same_font(header.font(), data_font):
            header.setFont(data_font)


def _mark_custom_font(widget: object) -> None:
    if isinstance(widget, QWidget):
        widget.setProperty("_cdmw_global_font_managed", False)


def _resolved_app_fonts(
    app: QApplication,
    settings: QSettings,
    *,
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None,
) -> tuple[QFont, QFont, str, float]:
    ui_font_family = str(settings.value("appearance/ui_font_family", DEFAULT_UI_FONT_FAMILY) or DEFAULT_UI_FONT_FAMILY)
    configured_base_font_size = max(
        UI_FONT_SIZE_MIN,
        min(UI_FONT_SIZE_MAX, _read_int_setting(settings, "appearance/ui_font_size", DEFAULT_UI_FONT_SIZE)),
    )
    configured_data_font_size = max(
        UI_FONT_SIZE_MIN,
        min(UI_FONT_SIZE_MAX, _read_int_setting(settings, "appearance/data_font_size", DEFAULT_UI_DATA_FONT_SIZE)),
    )
    fallback_width, fallback_height = available_screen_size_for(None)
    effective_screen_width = int(screen_width or fallback_width)
    effective_screen_height = int(screen_height or fallback_height)
    screen_scale = _responsive_control_scale_for_resolution(effective_screen_width, effective_screen_height)
    base_font_size = max(UI_FONT_SIZE_MIN, min(UI_FONT_SIZE_MAX, int(round(configured_base_font_size * screen_scale))))
    data_font_size = max(UI_FONT_SIZE_MIN, min(UI_FONT_SIZE_MAX, int(round(configured_data_font_size * screen_scale))))
    density_key = str(settings.value("appearance/ui_density", DEFAULT_UI_DENSITY) or DEFAULT_UI_DENSITY)
    effective_density_key = "compact" if screen_scale < 0.94 else density_key
    app_font = QFont(app.font())
    app_font.setFamily(ui_font_family)
    app_font.setPointSize(base_font_size)
    data_font = QFont(app_font)
    data_font.setPointSize(data_font_size)
    return app_font, data_font, effective_density_key, screen_scale


def apply_app_fonts(
    app: QApplication,
    settings: QSettings,
    *,
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None,
) -> tuple[QFont, QFont]:
    app_font, data_font, _density_key, _screen_scale = _resolved_app_fonts(
        app,
        settings,
        screen_width=screen_width,
        screen_height=screen_height,
    )
    _install_app_fonts(app, app_font, data_font)
    return app_font, data_font


def apply_app_theme(
    app: QApplication,
    settings: QSettings,
    theme_key: str,
    *,
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None,
) -> str:
    resolved_theme = theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME
    app_font, data_font, effective_density_key, screen_scale = _resolved_app_fonts(
        app,
        settings,
        screen_width=screen_width,
        screen_height=screen_height,
    )
    _install_app_fonts(app, app_font, data_font)
    app.setPalette(build_app_palette(resolved_theme))
    app.setStyleSheet(
        build_app_stylesheet(
            resolved_theme,
            density_key=effective_density_key,
            layout_scale=screen_scale,
        )
    )
    return resolved_theme

def build_monospace_font(settings: QSettings) -> QFont:
    point_size = _read_int_setting(settings, "appearance/log_font_size", DEFAULT_UI_LOG_FONT_SIZE)
    selected_family = str(
        settings.value("appearance/log_font_family", DEFAULT_UI_LOG_FONT_FAMILY) or DEFAULT_UI_LOG_FONT_FAMILY
    )
    bold_enabled = _read_bool_setting(settings, "appearance/log_font_bold", DEFAULT_UI_LOG_FONT_BOLD)
    fallback_order = [selected_family] + [family for family in LOG_FONT_FAMILY_OPTIONS if family != selected_family]
    font = QFont(fallback_order[0])
    for family in fallback_order:
        candidate = QFont(family)
        if candidate.exactMatch():
            font = candidate
            break
    font.setStyleHint(QFont.Monospace)
    font.setPointSize(point_size)
    font.setBold(bold_enabled)
    return font

def read_log_text_style(settings: QSettings) -> str:
    value = str(
        settings.value("appearance/log_text_style", DEFAULT_UI_LOG_TEXT_STYLE)
        or DEFAULT_UI_LOG_TEXT_STYLE
    ).strip().lower()
    allowed = {key for key, _label in UI_LOG_TEXT_STYLE_OPTIONS}
    return value if value in allowed else DEFAULT_UI_LOG_TEXT_STYLE

def read_text_color_scheme(settings: QSettings, key: str, default: str) -> str:
    value = str(settings.value(key, default) or default).strip().lower()
    allowed = {scheme_key for scheme_key, _label in UI_TEXT_COLOR_SCHEME_OPTIONS}
    return value if value in allowed else default

def apply_window_text_highlight_style(window: "MainWindow") -> None:
    style = read_log_text_style(window.settings)
    log_scheme = read_text_color_scheme(
        window.settings,
        "appearance/log_color_scheme",
        DEFAULT_UI_LOG_COLOR_SCHEME,
    )
    preview_scheme = read_text_color_scheme(
        window.settings,
        "appearance/preview_color_scheme",
        DEFAULT_UI_PREVIEW_COLOR_SCHEME,
    )
    text_search_tab = created_tool_widget(getattr(window, "text_search_tab", None))
    highlighters = [window.log_highlighter, window.archive_log_highlighter]
    if text_search_tab is not None:
        highlighters.append(text_search_tab.log_highlighter)
    for highlighter in highlighters:
        if hasattr(highlighter, "set_highlight_style"):
            highlighter.set_highlight_style(style)
        if hasattr(highlighter, "set_color_scheme"):
            highlighter.set_color_scheme(log_scheme)
    editors = [
        window.archive_preview_text_edit,
        window.archive_preview_info_edit,
        window.archive_preview_details_edit,
    ]
    if text_search_tab is not None:
        editors.append(text_search_tab.preview_text_edit)
    for editor in editors:
        if hasattr(editor, "set_highlight_style"):
            editor.set_highlight_style(style)
        if hasattr(editor, "set_color_scheme"):
            editor.set_color_scheme(preview_scheme)
    research_tab = created_tool_widget(getattr(window, "research_tab", None))
    if research_tab is not None and hasattr(research_tab, "_apply_archive_picker_preview_text_style"):
        research_tab._apply_archive_picker_preview_text_style()

def apply_window_data_fonts(window: "MainWindow") -> None:
    log_font = build_monospace_font(window.settings)
    window.log_view.setFont(log_font)
    _mark_custom_font(window.log_view)
    window.log_view.document().setDefaultFont(log_font)
    window.archive_log_view.setFont(log_font)
    _mark_custom_font(window.archive_log_view)
    window.archive_log_view.document().setDefaultFont(log_font)
    window.archive_preview_text_edit.apply_font_preferences(log_font, preserve_size=False)
    _mark_custom_font(window.archive_preview_text_edit)
    window.archive_preview_info_edit.apply_font_preferences(log_font, preserve_size=False)
    _mark_custom_font(window.archive_preview_info_edit)
    window.archive_preview_details_edit.apply_font_preferences(log_font, preserve_size=False)
    _mark_custom_font(window.archive_preview_details_edit)
    text_search_tab = created_tool_widget(getattr(window, "text_search_tab", None))
    if text_search_tab is not None:
        text_search_tab.log_view.setFont(log_font)
        _mark_custom_font(text_search_tab.log_view)
        text_search_tab.log_view.document().setDefaultFont(log_font)
        text_search_tab.preview_text_edit.apply_font_preferences(log_font, preserve_size=False)
        _mark_custom_font(text_search_tab.preview_text_edit)
    replace_assistant_tab = created_tool_widget(getattr(window, "replace_assistant_tab", None))
    if replace_assistant_tab is not None:
        replace_assistant_tab.log_view.setFont(log_font)
        _mark_custom_font(replace_assistant_tab.log_view)
        replace_assistant_tab.log_view.document().setDefaultFont(log_font)
        replace_assistant_tab.preview_details_edit.setFont(log_font)
        _mark_custom_font(replace_assistant_tab.preview_details_edit)
        replace_assistant_tab.preview_details_edit.document().setDefaultFont(log_font)
    bold_enabled = _read_bool_setting(window.settings, "appearance/log_font_bold", DEFAULT_UI_LOG_FONT_BOLD)
    window.log_highlighter.set_bold_enabled(bold_enabled)
    window.archive_log_highlighter.set_bold_enabled(bold_enabled)
    if text_search_tab is not None:
        text_search_tab.log_highlighter.set_bold_enabled(bold_enabled)
    apply_window_text_highlight_style(window)


def apply_window_ui_fonts(
    window: "MainWindow",
    app: QApplication | None = None,
    *,
    settings: QSettings | None = None,
) -> tuple[QFont, QFont] | None:
    app = app or QApplication.instance()
    if app is None:
        return None
    layout_widget = window if isinstance(window, QWidget) else None
    screen_width, screen_height = available_layout_size_for(layout_widget)
    ui_font, data_font = apply_app_fonts(
        app,
        settings if settings is not None else window.settings,
        screen_width=screen_width,
        screen_height=screen_height,
    )
    if layout_widget is not None:
        _apply_ui_fonts_to_widget_tree(layout_widget, ui_font)
        root_sync = getattr(layout_widget, "sync_ui_font", None)
        if callable(root_sync):
            root_sync(ui_font)
        _apply_data_fonts_to_widget_tree(layout_widget, data_font)
    else:
        sync_data = getattr(window, "_apply_data_widget_fonts", None)
        if callable(sync_data):
            sync_data(data_font)
    sync_archive_controls = getattr(window, "_sync_archive_controls_font", None)
    if callable(sync_archive_controls):
        sync_archive_controls(ui_font)
    texture_editor_tab = created_tool_widget(getattr(window, "texture_editor_tab", None))
    texture_sync = getattr(texture_editor_tab, "sync_ui_font", None)
    if callable(texture_sync):
        texture_sync(ui_font)
    mesh_editor_tab = created_tool_widget(getattr(window, "mesh_editor_tab", None))
    mesh_sync = getattr(mesh_editor_tab, "sync_ui_font", None)
    if callable(mesh_sync):
        mesh_sync(ui_font, data_font)
    return ui_font, data_font


class ThemeControllerMixin:
    """Deferred shell theme and appearance application for MainWindow."""

    def _handle_theme_changed(self, theme_key: Optional[str] = None) -> None:
        resolved_theme_key = theme_key if theme_key in UI_THEME_SCHEMES else self.current_theme_key
        self._pending_theme_key = resolved_theme_key
        self._pending_appearance_change = {
            "theme_key": resolved_theme_key,
            "changed": ("theme",),
            "requires_theme_apply": True,
            "requires_ui_fonts": True,
            "requires_data_fonts": False,
            "requires_text_colors": False,
            "title": f"Applying {UI_THEME_SCHEMES.get(resolved_theme_key, UI_THEME_SCHEMES[DEFAULT_UI_THEME]).get('label', 'Theme')} theme",
            "detail": "Updating app colors and preview panes...",
        }
        if hasattr(self, "theme_change_overlay"):
            self.theme_change_overlay.show_theme_change(resolved_theme_key)
        self._theme_change_apply_timer.start()

    def _normalize_appearance_change_payload(self, payload: object) -> Dict[str, object]:
        data = dict(payload) if isinstance(payload, dict) else {}
        theme_key = str(data.get("theme_key") or self.current_theme_key or DEFAULT_UI_THEME)
        if theme_key not in UI_THEME_SCHEMES:
            theme_key = DEFAULT_UI_THEME
        changed = data.get("changed", ())
        if isinstance(changed, str):
            changed = (changed,)
        elif not isinstance(changed, tuple):
            try:
                changed = tuple(changed)  # type: ignore[arg-type]
            except Exception:
                changed = ()
        data["theme_key"] = theme_key
        data["changed"] = changed
        data["requires_theme_apply"] = bool(data.get("requires_theme_apply", False))
        data["requires_ui_fonts"] = bool(data.get("requires_ui_fonts", False))
        data["requires_data_fonts"] = bool(data.get("requires_data_fonts", False))
        data["requires_text_colors"] = bool(data.get("requires_text_colors", False))
        if not str(data.get("title") or "").strip():
            theme_label = UI_THEME_SCHEMES.get(theme_key, UI_THEME_SCHEMES[DEFAULT_UI_THEME]).get("label", "Theme")
            if data["requires_theme_apply"]:
                data["title"] = f"Applying {theme_label} theme"
            elif data["requires_ui_fonts"]:
                data["title"] = "Applying UI font"
            elif data["requires_data_fonts"]:
                data["title"] = "Applying text appearance"
            else:
                data["title"] = "Applying text colors"
        if not str(data.get("detail") or "").strip():
            if data["requires_theme_apply"]:
                data["detail"] = "Updating app colors and preview panes..."
            elif data["requires_ui_fonts"]:
                data["detail"] = "Updating app fonts and dense views..."
            else:
                data["detail"] = "Updating logs and preview text..."
        return data

    def _show_appearance_change_overlay(self, payload: object) -> None:
        data = self._normalize_appearance_change_payload(payload)
        if hasattr(self, "theme_change_overlay"):
            self.theme_change_overlay.show_appearance_change(
                str(data["theme_key"]),
                title=str(data["title"]),
                detail=str(data["detail"]),
            )

    def _handle_appearance_change_started(self, payload: object) -> None:
        data = self._normalize_appearance_change_payload(payload)
        if data.get("changed"):
            self._show_appearance_change_overlay(data)

    def _handle_appearance_changed(self, payload: object) -> None:
        data = self._normalize_appearance_change_payload(payload)
        if not data.get("changed"):
            if hasattr(self, "theme_change_overlay"):
                self.theme_change_overlay.finish(0)
            return
        self._pending_appearance_change = data
        self._pending_theme_key = str(data["theme_key"])
        self._show_appearance_change_overlay(data)
        self._theme_change_apply_timer.start()

    def _apply_pending_theme_change(self) -> None:
        if self._theme_change_in_progress:
            self._theme_change_apply_timer.start()
            return
        payload = self._pending_appearance_change
        if payload is None:
            resolved_theme_key = self._pending_theme_key or self.current_theme_key
            payload = self._normalize_appearance_change_payload(
                {
                    "theme_key": resolved_theme_key,
                    "changed": ("theme",),
                    "requires_theme_apply": True,
                    "requires_ui_fonts": True,
                    "requires_data_fonts": False,
                    "requires_text_colors": False,
                }
            )
        else:
            payload = self._normalize_appearance_change_payload(payload)
            resolved_theme_key = str(payload["theme_key"])
        self._pending_theme_key = None
        self._pending_appearance_change = None
        app = QApplication.instance()
        if app is None:
            if hasattr(self, "theme_change_overlay"):
                self.theme_change_overlay.finish(0)
            return
        self._theme_change_in_progress = True
        if hasattr(self, "theme_change_overlay"):
            self._show_appearance_change_overlay(payload)
            self.theme_change_overlay.repaint()
        app.processEvents()
        QApplication.setOverrideCursor(Qt.WaitCursor)
        self._prepare_appearance_apply_steps(payload, app)
        self._appearance_apply_step_timer.start()

    def _finish_appearance_apply_steps(self, *, delay_ms: int = 140) -> None:
        self._appearance_apply_step_timer.stop()
        self._appearance_apply_steps.clear()
        self._appearance_apply_app = None
        try:
            QApplication.restoreOverrideCursor()
        except Exception:
            pass
        self._theme_change_in_progress = False
        if self._pending_appearance_change is not None:
            self._show_appearance_change_overlay(self._pending_appearance_change)
            self._theme_change_apply_timer.start()
        elif self._pending_theme_key is not None:
            self._handle_theme_changed(self._pending_theme_key)
            self._theme_change_apply_timer.start()
        elif hasattr(self, "theme_change_overlay"):
            self.theme_change_overlay.finish(delay_ms)

    def _queue_appearance_apply_step(self, label: str, callback: Callable[[], None]) -> None:
        self._appearance_apply_steps.append((str(label or "Applying appearance"), callback))

    def _prepare_appearance_apply_steps(self, payload: Dict[str, object], app: QApplication) -> None:
        data = self._normalize_appearance_change_payload(payload)
        self._appearance_apply_steps.clear()
        self._appearance_apply_app = app
        resolved_theme_key = str(data["theme_key"])
        if data["requires_theme_apply"]:
            self._queue_appearance_apply_step(
                "Applying app stylesheet",
                lambda resolved_theme_key=resolved_theme_key, app=app: self._apply_theme_application_style(
                    resolved_theme_key,
                    app,
                ),
            )
            self._queue_ui_font_apply_steps(app, schedule_column_autofit=False)
            if data["requires_data_fonts"]:
                self._queue_data_font_apply_steps(schedule_column_autofit=False)
            if data["requires_text_colors"]:
                self._queue_text_highlight_apply_steps()
            self._queue_appearance_apply_step("Updating log themes", lambda: self.log_highlighter.set_theme(self.current_theme_key))
            self._queue_appearance_apply_step("Updating archive log theme", lambda: self.archive_log_highlighter.set_theme(self.current_theme_key))
            self._queue_appearance_apply_step("Updating model preview theme", lambda: self.archive_model_preview.set_theme(self.current_theme_key))
            self._queue_appearance_apply_step("Updating media preview theme", lambda: self.archive_media_preview.set_theme(self.current_theme_key))
            self._queue_appearance_apply_step("Updating archive text preview", lambda: self.archive_preview_text_edit.set_theme(self.current_theme_key))
            self._queue_appearance_apply_step("Updating archive info preview", lambda: self.archive_preview_info_edit.set_theme(self.current_theme_key))
            self._queue_appearance_apply_step("Updating archive details preview", lambda: self.archive_preview_details_edit.set_theme(self.current_theme_key))
            text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
            if text_search_tab is not None:
                self._queue_appearance_apply_step(
                    "Updating text search theme",
                    lambda text_search_tab=text_search_tab: text_search_tab.set_theme(self.current_theme_key),
                )
            research_tab = created_tool_widget(getattr(self, "research_tab", None))
            if research_tab is not None:
                self._queue_appearance_apply_step(
                    "Updating research theme",
                    lambda research_tab=research_tab: research_tab.set_theme(self.current_theme_key),
                )
            self._queue_appearance_apply_step("Updating mesh editor theme", self._sync_mesh_editor_theme)
            self._queue_appearance_apply_step("Syncing settings controls", lambda: self.settings_tab.sync_appearance_controls(self.current_theme_key))
            self._queue_appearance_apply_step("Updating responsive controls", self._apply_responsive_control_minimums)
            self._queue_appearance_apply_step("Scheduling column sizing", self._schedule_column_autofit)
            self._queue_appearance_apply_step("Saving theme setting", self._save_current_theme_setting)
            return
        if data["requires_ui_fonts"]:
            self._queue_ui_font_apply_steps(app, schedule_column_autofit=True)
        if data["requires_data_fonts"]:
            self._queue_data_font_apply_steps(schedule_column_autofit=True)
        if data["requires_text_colors"]:
            self._queue_text_highlight_apply_steps()
        self._queue_appearance_apply_step("Syncing settings controls", lambda: self.settings_tab.sync_appearance_controls(self.current_theme_key))

    def _run_next_appearance_apply_step(self) -> None:
        app = self._appearance_apply_app or QApplication.instance()
        if app is None:
            self._finish_appearance_apply_steps(delay_ms=0)
            return
        if hasattr(self, "theme_change_overlay"):
            self.theme_change_overlay.raise_()
            self.theme_change_overlay.repaint()
        app.processEvents()
        if not self._appearance_apply_steps:
            self._finish_appearance_apply_steps()
            return
        _label, callback = self._appearance_apply_steps.popleft()
        try:
            callback()
        except Exception:
            self._finish_appearance_apply_steps(delay_ms=0)
            raise
        if hasattr(self, "theme_change_overlay"):
            self.theme_change_overlay.raise_()
            self.theme_change_overlay.repaint()
        app.processEvents()
        if self._appearance_apply_steps:
            self._appearance_apply_step_timer.start()
        else:
            self._finish_appearance_apply_steps()

    def _apply_theme_application_style(self, resolved_theme_key: str, app: QApplication) -> None:
        screen_width, screen_height = available_layout_size_for(self)
        self._current_responsive_control_scale = 0.0
        self.current_theme_key = apply_app_theme(
            app,
            self.settings,
            resolved_theme_key,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        self._apply_theme_window_icon(self.current_theme_key)

    def _queue_ui_font_apply_steps(self, app: QApplication, *, schedule_column_autofit: bool) -> None:
        self._queue_appearance_apply_step("Updating app UI fonts", lambda app=app: self._apply_application_ui_fonts(app))
        texture_editor_tab = created_tool_widget(getattr(self, "texture_editor_tab", None))
        if texture_editor_tab is not None:
            self._queue_appearance_apply_step(
                "Updating texture editor font",
                lambda app=app, texture_editor_tab=texture_editor_tab: texture_editor_tab.sync_ui_font(app.font()),
            )
        self._queue_appearance_apply_step("Updating mesh editor font", lambda app=app: self._sync_mesh_editor_font(app))
        self._queue_appearance_apply_step("Updating responsive controls", self._apply_responsive_control_minimums)
        if schedule_column_autofit:
            self._queue_appearance_apply_step("Scheduling column sizing", self._schedule_column_autofit)

    def _apply_application_ui_fonts(self, app: QApplication) -> None:
        screen_width, screen_height = available_layout_size_for(self)
        self._current_responsive_control_scale = 0.0
        ui_font, data_font = apply_app_fonts(
            app,
            self.settings,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        if isinstance(self, QWidget):
            _apply_ui_fonts_to_widget_tree(self, ui_font)
        self._apply_data_widget_fonts(data_font)
        self._sync_archive_controls_font(ui_font)

    def _sync_archive_controls_font(self, ui_font: QFont) -> None:
        archive_controls_group = getattr(self, "archive_controls_group", None)
        if archive_controls_group is None:
            return
        archive_controls_font = QFont(ui_font)
        if archive_controls_font.pointSize() > 0:
            archive_controls_font.setPointSize(max(UI_FONT_SIZE_MIN, archive_controls_font.pointSize() - 1))
        if not _same_font(archive_controls_group.font(), archive_controls_font):
            archive_controls_group.setFont(archive_controls_font)

    def _apply_data_widget_fonts(self, data_font: QFont) -> None:
        _apply_data_fonts_to_widget_tree(self, data_font)

    def _sync_mesh_editor_appearance(self, app: QApplication) -> None:
        self._sync_mesh_editor_theme()
        self._sync_mesh_editor_font(app)

    def _sync_mesh_editor_theme(self) -> None:
        mesh_editor_tab = created_tool_widget(getattr(self, "mesh_editor_tab", None))
        if mesh_editor_tab is None:
            return
        if hasattr(mesh_editor_tab, "set_theme"):
            mesh_editor_tab.set_theme(self.current_theme_key)

    def _sync_mesh_editor_font(self, app: QApplication) -> None:
        mesh_editor_tab = created_tool_widget(getattr(self, "mesh_editor_tab", None))
        if mesh_editor_tab is None:
            return
        screen_width, screen_height = available_layout_size_for(self)
        _ui_font, data_font = apply_app_fonts(
            app,
            self.settings,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        if hasattr(mesh_editor_tab, "sync_ui_font"):
            mesh_editor_tab.sync_ui_font(app.font(), data_font)

    def _save_current_theme_setting(self) -> None:
        if not getattr(self, "_settings_ready", False):
            return
        self.settings.setValue("appearance/theme", self.current_theme_key)
        QTimer.singleShot(650, self.settings.sync)

    def _apply_theme_window_icon(self, theme_key: str) -> None:
        app_icon, _icon_path = load_app_icon(theme_key)
        if app_icon.isNull():
            return
        app = QApplication.instance()
        if app is not None:
            app.setWindowIcon(app_icon)
            icon_filter = getattr(self, "_app_window_icon_filter", None)
            if hasattr(icon_filter, "set_app_icon"):
                icon_filter.set_app_icon(app_icon)
            for widget in app.topLevelWidgets():
                if not isinstance(widget, QWidget) or not widget.isWindow():
                    continue
                try:
                    widget.setWindowIcon(app_icon)
                except RuntimeError:
                    pass
        else:
            self.setWindowIcon(app_icon)
        tray_icon = getattr(self, "app_tray_icon", None)
        if tray_icon is not None:
            try:
                tray_icon.setIcon(app_icon)
            except RuntimeError:
                pass

    def _queue_data_font_apply_steps(self, *, schedule_column_autofit: bool) -> None:
        log_font = build_monospace_font(self.settings)
        targets = [
            ("main log font", self.log_view),
            ("archive log font", self.archive_log_view),
            ("archive preview text font", self.archive_preview_text_edit),
            ("archive preview info font", self.archive_preview_info_edit),
            ("archive preview details font", self.archive_preview_details_edit),
        ]
        text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
        if text_search_tab is not None:
            targets.extend(
                (
                    ("text search log font", text_search_tab.log_view),
                    ("text search preview font", text_search_tab.preview_text_edit),
                )
            )
        replace_assistant_tab = created_tool_widget(getattr(self, "replace_assistant_tab", None))
        if replace_assistant_tab is not None:
            targets.extend(
                (
                    ("replace assistant log font", replace_assistant_tab.log_view),
                    ("replace assistant preview font", replace_assistant_tab.preview_details_edit),
                )
            )
        for label, widget in targets:
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda widget=widget, log_font=log_font: self._apply_single_text_widget_font(widget, log_font),
            )
        bold_enabled = _read_bool_setting(self.settings, "appearance/log_font_bold", DEFAULT_UI_LOG_FONT_BOLD)
        highlighters = [
            ("main log highlighter bold", self.log_highlighter),
            ("archive log highlighter bold", self.archive_log_highlighter),
        ]
        if text_search_tab is not None:
            highlighters.append(("text search log highlighter bold", text_search_tab.log_highlighter))
        for label, highlighter in highlighters:
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda highlighter=highlighter, bold_enabled=bold_enabled: highlighter.set_bold_enabled(bold_enabled),
            )
        if schedule_column_autofit:
            self._queue_appearance_apply_step("Scheduling column sizing", self._schedule_column_autofit)

    def _apply_single_text_widget_font(self, widget: QWidget, font: QFont) -> None:
        if hasattr(widget, "apply_font_preferences"):
            widget.apply_font_preferences(font, preserve_size=False)  # type: ignore[attr-defined]
            _mark_custom_font(widget)
            return
        widget.setFont(font)
        _mark_custom_font(widget)
        document_getter = getattr(widget, "document", None)
        if callable(document_getter):
            document = document_getter()
            if document is not None and hasattr(document, "setDefaultFont"):
                document.setDefaultFont(font)

    def _queue_text_highlight_apply_steps(self) -> None:
        style = read_log_text_style(self.settings)
        log_scheme = read_text_color_scheme(
            self.settings,
            "appearance/log_color_scheme",
            DEFAULT_UI_LOG_COLOR_SCHEME,
        )
        preview_scheme = read_text_color_scheme(
            self.settings,
            "appearance/preview_color_scheme",
            DEFAULT_UI_PREVIEW_COLOR_SCHEME,
        )
        text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
        highlighters = [
            ("main log colors", self.log_highlighter),
            ("archive log colors", self.archive_log_highlighter),
        ]
        if text_search_tab is not None:
            highlighters.append(("text search log colors", text_search_tab.log_highlighter))
        for label, highlighter in highlighters:
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda highlighter=highlighter, style=style, log_scheme=log_scheme: self._apply_single_highlighter_style(
                    highlighter,
                    style,
                    log_scheme,
                ),
            )
        editors = [
            ("archive text preview colors", self.archive_preview_text_edit),
            ("archive info preview colors", self.archive_preview_info_edit),
            ("archive details preview colors", self.archive_preview_details_edit),
        ]
        if text_search_tab is not None:
            editors.append(("text search preview colors", text_search_tab.preview_text_edit))
        for label, editor in editors:
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda editor=editor, style=style, preview_scheme=preview_scheme: self._apply_single_editor_text_style(
                    editor,
                    style,
                    preview_scheme,
                ),
            )
        research_tab = created_tool_widget(getattr(self, "research_tab", None))
        if research_tab is not None and hasattr(research_tab, "_apply_archive_picker_preview_text_style"):
            self._queue_appearance_apply_step(
                "Updating research preview colors",
                lambda research_tab=research_tab: research_tab._apply_archive_picker_preview_text_style(),
            )

    def _apply_single_highlighter_style(self, highlighter: object, style: str, color_scheme: str) -> None:
        if hasattr(highlighter, "set_highlight_style"):
            highlighter.set_highlight_style(style)
        if hasattr(highlighter, "set_color_scheme"):
            highlighter.set_color_scheme(color_scheme)

    def _apply_single_editor_text_style(self, editor: object, style: str, color_scheme: str) -> None:
        if hasattr(editor, "set_highlight_style"):
            editor.set_highlight_style(style)
        if hasattr(editor, "set_color_scheme"):
            editor.set_color_scheme(color_scheme)


class ThemeController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context


__all__ = [
    "ThemeChangeBusyOverlay",
    "ThemeController",
    "ThemeControllerMixin",
    "apply_app_theme",
    "apply_app_fonts",
    "apply_window_data_fonts",
    "apply_window_ui_fonts",
    "apply_window_text_highlight_style",
    "build_monospace_font",
    "read_log_text_style",
    "read_text_color_scheme",
]
