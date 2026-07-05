"""Shell theme selection boundary."""

from __future__ import annotations

from typing import Callable, Dict, Optional

from PySide6.QtCore import QRectF, QSettings, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QAbstractItemView, QFrame, QHeaderView, QWidget

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
from cdmw.ui.shell.settings_bridge import (
    read_bool_setting as _read_bool_setting,
    read_int_setting as _read_int_setting,
)
from cdmw.ui.app_icon import load_app_icon
from cdmw.ui.themes import UI_THEME_SCHEMES, build_app_palette, build_app_stylesheet, get_theme
from cdmw.ui.widgets import available_layout_size_for, available_screen_size_for


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
    if not _same_font(app.font(), app_font):
        app.setFont(app_font)
    for class_name in _UI_FONT_CLASS_NAMES:
        app.setFont(app_font, class_name)
    for class_name in _DATA_FONT_CLASS_NAMES:
        app.setFont(data_font, class_name)
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
    app_font, _data_font, effective_density_key, screen_scale = _resolved_app_fonts(
        app,
        settings,
        screen_width=screen_width,
        screen_height=screen_height,
    )
    if not _same_font(app.font(), app_font):
        app.setFont(app_font)
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
    for highlighter in (
        window.log_highlighter,
        window.archive_log_highlighter,
        window.text_search_tab.log_highlighter,
    ):
        if hasattr(highlighter, "set_highlight_style"):
            highlighter.set_highlight_style(style)
        if hasattr(highlighter, "set_color_scheme"):
            highlighter.set_color_scheme(log_scheme)
    for editor in (
        window.archive_preview_text_edit,
        window.archive_preview_info_edit,
        window.archive_preview_details_edit,
        window.text_search_tab.preview_text_edit,
    ):
        if hasattr(editor, "set_highlight_style"):
            editor.set_highlight_style(style)
        if hasattr(editor, "set_color_scheme"):
            editor.set_color_scheme(preview_scheme)
    research_tab = getattr(window, "research_tab", None)
    if research_tab is not None and hasattr(research_tab, "_apply_archive_picker_preview_text_style"):
        research_tab._apply_archive_picker_preview_text_style()

def apply_window_data_fonts(window: "MainWindow") -> None:
    log_font = build_monospace_font(window.settings)
    window.log_view.setFont(log_font)
    window.log_view.document().setDefaultFont(log_font)
    window.archive_log_view.setFont(log_font)
    window.archive_log_view.document().setDefaultFont(log_font)
    window.archive_preview_text_edit.apply_font_preferences(log_font, preserve_size=False)
    window.archive_preview_info_edit.apply_font_preferences(log_font, preserve_size=False)
    window.archive_preview_details_edit.apply_font_preferences(log_font, preserve_size=False)
    window.text_search_tab.log_view.setFont(log_font)
    window.text_search_tab.log_view.document().setDefaultFont(log_font)
    window.text_search_tab.preview_text_edit.apply_font_preferences(log_font, preserve_size=False)
    window.replace_assistant_tab.log_view.setFont(log_font)
    window.replace_assistant_tab.log_view.document().setDefaultFont(log_font)
    window.replace_assistant_tab.preview_details_edit.setFont(log_font)
    window.replace_assistant_tab.preview_details_edit.document().setDefaultFont(log_font)
    bold_enabled = _read_bool_setting(window.settings, "appearance/log_font_bold", DEFAULT_UI_LOG_FONT_BOLD)
    window.log_highlighter.set_bold_enabled(bold_enabled)
    window.archive_log_highlighter.set_bold_enabled(bold_enabled)
    window.text_search_tab.log_highlighter.set_bold_enabled(bold_enabled)
    apply_window_text_highlight_style(window)


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
            self._queue_appearance_apply_step("Updating text search theme", lambda: self.text_search_tab.set_theme(self.current_theme_key))
            self._queue_appearance_apply_step("Updating research theme", lambda: self.research_tab.set_theme(self.current_theme_key))
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
        self._queue_appearance_apply_step("Updating texture editor font", lambda app=app: self.texture_editor_tab.sync_ui_font(app.font()))
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
        for widget in self.findChildren(QAbstractItemView):
            if not _same_font(widget.font(), data_font):
                widget.setFont(data_font)
        for header in self.findChildren(QHeaderView):
            if not _same_font(header.font(), data_font):
                header.setFont(data_font)

    def _sync_mesh_editor_appearance(self, app: QApplication) -> None:
        self._sync_mesh_editor_theme()
        self._sync_mesh_editor_font(app)

    def _sync_mesh_editor_theme(self) -> None:
        mesh_editor_tab = getattr(self, "mesh_editor_tab", None)
        if mesh_editor_tab is None:
            return
        if hasattr(mesh_editor_tab, "set_theme"):
            mesh_editor_tab.set_theme(self.current_theme_key)

    def _sync_mesh_editor_font(self, app: QApplication) -> None:
        mesh_editor_tab = getattr(self, "mesh_editor_tab", None)
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
        targets = (
            ("main log font", self.log_view),
            ("archive log font", self.archive_log_view),
            ("archive preview text font", self.archive_preview_text_edit),
            ("archive preview info font", self.archive_preview_info_edit),
            ("archive preview details font", self.archive_preview_details_edit),
            ("text search log font", self.text_search_tab.log_view),
            ("text search preview font", self.text_search_tab.preview_text_edit),
            ("replace assistant log font", self.replace_assistant_tab.log_view),
            ("replace assistant preview font", self.replace_assistant_tab.preview_details_edit),
        )
        for label, widget in targets:
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda widget=widget, log_font=log_font: self._apply_single_text_widget_font(widget, log_font),
            )
        bold_enabled = _read_bool_setting(self.settings, "appearance/log_font_bold", DEFAULT_UI_LOG_FONT_BOLD)
        for label, highlighter in (
            ("main log highlighter bold", self.log_highlighter),
            ("archive log highlighter bold", self.archive_log_highlighter),
            ("text search log highlighter bold", self.text_search_tab.log_highlighter),
        ):
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda highlighter=highlighter, bold_enabled=bold_enabled: highlighter.set_bold_enabled(bold_enabled),
            )
        if schedule_column_autofit:
            self._queue_appearance_apply_step("Scheduling column sizing", self._schedule_column_autofit)

    def _apply_single_text_widget_font(self, widget: QWidget, font: QFont) -> None:
        if hasattr(widget, "apply_font_preferences"):
            widget.apply_font_preferences(font, preserve_size=False)  # type: ignore[attr-defined]
            return
        widget.setFont(font)
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
        for label, highlighter in (
            ("main log colors", self.log_highlighter),
            ("archive log colors", self.archive_log_highlighter),
            ("text search log colors", self.text_search_tab.log_highlighter),
        ):
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda highlighter=highlighter, style=style, log_scheme=log_scheme: self._apply_single_highlighter_style(
                    highlighter,
                    style,
                    log_scheme,
                ),
            )
        for label, editor in (
            ("archive text preview colors", self.archive_preview_text_edit),
            ("archive info preview colors", self.archive_preview_info_edit),
            ("archive details preview colors", self.archive_preview_details_edit),
            ("text search preview colors", self.text_search_tab.preview_text_edit),
        ):
            self._queue_appearance_apply_step(
                f"Updating {label}",
                lambda editor=editor, style=style, preview_scheme=preview_scheme: self._apply_single_editor_text_style(
                    editor,
                    style,
                    preview_scheme,
                ),
            )
        research_tab = getattr(self, "research_tab", None)
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


class ThemeChangeBusyOverlay(QFrame):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ThemeChangeBusyOverlay")
        self.setAttribute(Qt.WA_StyledBackground, False)
        self.setAutoFillBackground(False)
        self.hide()
        self._theme_key = DEFAULT_UI_THEME
        self._theme_label = UI_THEME_SCHEMES[DEFAULT_UI_THEME]["label"]
        self._overlay_title = f"Applying {self._theme_label} theme"
        self._overlay_detail = "Updating app colors and preview panes..."
        self._spinner_degrees = 0
        self._spinner_timer = QTimer(self)
        self._spinner_timer.setInterval(50)
        self._spinner_timer.timeout.connect(self._advance_spinner)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_now)

    def show_theme_change(self, theme_key: str) -> None:
        resolved_theme_key = theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME
        theme_label = str(UI_THEME_SCHEMES[resolved_theme_key].get("label", "Theme"))
        self.show_appearance_change(
            resolved_theme_key,
            title=f"Applying {theme_label} theme",
            detail="Updating app colors and preview panes...",
        )

    def show_appearance_change(self, theme_key: str, *, title: str, detail: str) -> None:
        resolved_theme_key = theme_key if theme_key in UI_THEME_SCHEMES else DEFAULT_UI_THEME
        self._theme_key = resolved_theme_key
        self._theme_label = str(UI_THEME_SCHEMES[resolved_theme_key].get("label", "Theme"))
        self._overlay_title = str(title or f"Applying {self._theme_label} theme")
        self._overlay_detail = str(detail or "Updating app colors and preview panes...")
        parent = self.parentWidget()
        if parent is not None:
            self.setGeometry(parent.rect())
        self._hide_timer.stop()
        self.show()
        self.raise_()
        if not self._spinner_timer.isActive():
            self._spinner_timer.start()
        self.update()

    def finish(self, delay_ms: int = 140) -> None:
        if self.isVisible():
            self._hide_timer.start(max(0, int(delay_ms)))
        else:
            self._hide_now()

    def _hide_now(self) -> None:
        self._hide_timer.stop()
        self._spinner_timer.stop()
        self.hide()

    def _advance_spinner(self) -> None:
        self._spinner_degrees = (self._spinner_degrees + 34) % 360
        self.update()

    def paintEvent(self, event) -> None:  # type: ignore[override]
        rect = QRectF(self.rect())
        if rect.width() <= 2 or rect.height() <= 2:
            return
        theme = get_theme(self._theme_key)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing, True)

        scrim = QColor(str(theme.get("window", "#111111")))
        scrim.setAlpha(196)
        painter.fillRect(rect, scrim)

        panel_width = min(380.0, max(280.0, rect.width() * 0.34))
        panel_height = 122.0
        panel = QRectF(
            rect.center().x() - panel_width / 2.0,
            rect.center().y() - panel_height / 2.0,
            panel_width,
            panel_height,
        )
        surface = QColor(str(theme.get("surface", "#252526")))
        border = QColor(str(theme.get("border_strong", "#3c3c3c")))
        painter.setPen(QPen(border, 1.0))
        painter.setBrush(surface)
        painter.drawRoundedRect(panel, 8.0, 8.0)

        spinner_rect = QRectF(panel.left() + 26.0, panel.top() + 40.0, 36.0, 36.0)
        track = QColor(str(theme.get("border", "#2a2d2e")))
        track.setAlpha(150)
        painter.setPen(QPen(track, 3.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawArc(spinner_rect, 0, 360 * 16)
        accent = QColor(str(theme.get("accent", "#007acc")))
        painter.setPen(QPen(accent, 3.2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        painter.drawArc(spinner_rect, -self._spinner_degrees * 16, 245 * 16)

        title_font = QFont(self.font())
        title_font.setBold(True)
        title_font.setPointSize(max(10, title_font.pointSize() + 1))
        painter.setFont(title_font)
        painter.setPen(QColor(str(theme.get("text_strong", "#f3f3f3"))))
        text_left = spinner_rect.right() + 18.0
        text_rect = QRectF(text_left, panel.top() + 30.0, panel.right() - text_left - 22.0, 28.0)
        painter.drawText(text_rect, Qt.AlignLeft | Qt.AlignVCenter, self._overlay_title)

        body_font = QFont(self.font())
        body_font.setPointSize(max(9, body_font.pointSize()))
        painter.setFont(body_font)
        painter.setPen(QColor(str(theme.get("text_muted", "#9da0a6"))))
        body_rect = QRectF(text_left, panel.top() + 60.0, panel.right() - text_left - 22.0, 34.0)
        painter.drawText(body_rect, Qt.AlignLeft | Qt.AlignTop | Qt.TextWordWrap, self._overlay_detail)


__all__ = [
    "ThemeChangeBusyOverlay",
    "ThemeController",
    "ThemeControllerMixin",
    "apply_app_theme",
    "apply_app_fonts",
    "apply_window_data_fonts",
    "apply_window_text_highlight_style",
    "build_monospace_font",
    "read_log_text_style",
    "read_text_color_scheme",
]
