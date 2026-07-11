"""Navigation and detachable tool-window helpers for shell MainWindow."""

from __future__ import annotations

import time
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QVBoxLayout, QWidget

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab
from cdmw.ui.shell.tab_registry import DetachedToolWindow
from cdmw.ui.widgets import QuickStartDialog


class NavigationControllerMixin:
    """Route tool activation and detach/attach tool tabs."""

    def focus_quick_start_sections(self, *, include_chainner: bool) -> None:
        if include_chainner:
            self._activate_tool_widget(self.workflow_tab)
        else:
            self._activate_tool_widget(self.settings_tab)
            if hasattr(self.settings_tab, "show_settings_section"):
                self.settings_tab.show_settings_section("setup")
        self.setup_section.set_expanded(True)
        self.paths_section.set_expanded(True)
        self.archive_locations_section.set_expanded(True)
        self.settings_section.set_expanded(False)
        self.dds_output_section.set_expanded(False)
        self.filters_section.set_expanded(False)
        self.chainner_section.set_expanded(include_chainner)

    def focus_archive_locations(self) -> None:
        self._activate_tool_widget(self.settings_tab)
        if hasattr(self.settings_tab, "show_settings_section"):
            self.settings_tab.show_settings_section("paths")
        self.archive_locations_section.set_expanded(True)
        self.setup_section.set_expanded(False)
        self.paths_section.set_expanded(False)
        self.archive_package_root_edit.setFocus()

    def show_quick_start_dialog(self) -> None:
        dialog = QuickStartDialog(self)
        self.ui_localizer.apply(dialog)
        dialog.exec()

    def _find_tool_tab_widget(self, widget: QWidget) -> Optional[QTabWidget]:
        if self.main_tabs.indexOf(widget) >= 0:
            return self.main_tabs
        for tab_widget in getattr(self, "_tool_group_tabs", ()):
            if tab_widget.indexOf(widget) >= 0:
                return tab_widget
        return None

    def _current_navigation_widget(self) -> Optional[QWidget]:
        current = self.main_tabs.currentWidget()
        if isinstance(current, QTabWidget) and current in getattr(self, "_tool_group_tabs", ()):
            return current.currentWidget()
        return current

    def _select_tab_widget(self, tab_widget: QTabWidget, widget: QWidget) -> None:
        index = tab_widget.indexOf(widget)
        if index < 0:
            return
        tab_widget.setCurrentIndex(index)
        if tab_widget is not self.main_tabs:
            self.main_tabs.setCurrentWidget(tab_widget)

    def _restore_saved_navigation(self) -> None:
        if not self._preference_bool("restore_last_active_tab", True):
            self._activate_tool_key("archive_browser")
            return
        saved_key = str(self.settings.value("ui/active_tool_key", "") or "").strip()
        if saved_key == "dashboard":
            self._activate_tool_key("archive_browser")
            return
        if saved_key in self._tool_widgets_by_key:
            self._activate_tool_key(saved_key)
            return
        if self.settings.contains("ui/main_tab_index"):
            legacy_index = int(self.settings.value("ui/main_tab_index", 0))
            legacy_keys = [
                "texture_workflow",
                "replace_assistant",
                "texture_editor",
                "archive_browser",
                "model_library",
                "research",
                "text_search",
                "item_icons",
                "settings",
            ]
            if 0 <= legacy_index < len(legacy_keys):
                self._activate_tool_key(legacy_keys[legacy_index])
                return
        self._activate_tool_key("archive_browser")

    def _register_detachable_tool(self, key: str, widget: QWidget, title: str) -> None:
        if key in self._tool_widgets_by_key:
            return
        self._detachable_tool_order.append(key)
        self._tool_widgets_by_key[key] = widget
        self._tool_titles_by_key[key] = title
        tab_widget = self._find_tool_tab_widget(widget)
        if tab_widget is not None:
            self._tool_tab_widgets_by_key[key] = tab_widget
            index = tab_widget.indexOf(widget)
            self._tool_tab_labels_by_key[key] = tab_widget.tabText(index) if index >= 0 else title
        else:
            self._tool_tab_labels_by_key[key] = title

    def _build_window_tool_menu_actions(self) -> None:
        for key in self._detachable_tool_order:
            title = self._tool_titles_by_key[key]
            action = self.window_menu.addAction(f"Show {title}")
            action.triggered.connect(lambda _checked=False, tool_key=key: self._activate_tool_key(tool_key))
            self._tool_window_actions[key] = action
        self._update_window_menu_state()

    def _create_detached_tool_placeholder(self, key: str) -> QWidget:
        existing = self._tool_placeholders_by_key.get(key)
        if existing is not None:
            return existing
        title = self._tool_titles_by_key.get(key, "Tool")
        placeholder = QWidget()
        layout = QVBoxLayout(placeholder)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(12)
        layout.addStretch(1)
        title_label = QLabel(f"{title} is open in a separate window.")
        title_label.setObjectName("SectionTitle")
        title_label.setAlignment(Qt.AlignCenter)
        detail_label = QLabel("Use Show Window to bring it forward, or Reattach Tool to return it to this tab.")
        detail_label.setObjectName("HintLabel")
        detail_label.setWordWrap(True)
        detail_label.setAlignment(Qt.AlignCenter)
        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        button_row.addStretch(1)
        show_button = QPushButton("Show Window")
        attach_button = QPushButton("Reattach Tool")
        show_button.clicked.connect(lambda _checked=False, tool_key=key: self._activate_tool_key(tool_key))
        attach_button.clicked.connect(lambda _checked=False, tool_key=key: self._attach_detached_tool(tool_key))
        button_row.addWidget(show_button)
        button_row.addWidget(attach_button)
        button_row.addStretch(1)
        layout.addWidget(title_label)
        layout.addWidget(detail_label)
        layout.addLayout(button_row)
        layout.addStretch(1)
        self._tool_placeholders_by_key[key] = placeholder
        self._tool_keys_by_placeholder[placeholder] = key
        return placeholder

    def _tool_key_for_widget(self, widget: Optional[QWidget]) -> str:
        if widget is None:
            return ""
        for key, tool_widget in self._tool_widgets_by_key.items():
            if tool_widget is widget:
                return key
        return self._tool_keys_by_placeholder.get(widget, "")

    def _preferred_tool_tab_index(self, key: str) -> int:
        tab_widget = self._tool_tab_widgets_by_key.get(key, self.main_tabs)
        try:
            order_index = self._detachable_tool_order.index(key)
        except ValueError:
            return tab_widget.count()
        preferred_index = 0
        for previous_key in self._detachable_tool_order[:order_index]:
            if self._tool_tab_widgets_by_key.get(previous_key, self.main_tabs) is not tab_widget:
                continue
            previous_widget = self._tool_widgets_by_key.get(previous_key)
            previous_placeholder = self._tool_placeholders_by_key.get(previous_key)
            previous_tab_index = -1
            if previous_widget is not None:
                previous_tab_index = tab_widget.indexOf(previous_widget)
            if previous_tab_index < 0 and previous_placeholder is not None:
                previous_tab_index = tab_widget.indexOf(previous_placeholder)
            if previous_tab_index >= 0:
                preferred_index = previous_tab_index + 1
        return min(preferred_index, tab_widget.count())

    def _detach_current_tool_tab(self) -> None:
        self._detach_tool_key(self._tool_key_for_widget(self._current_navigation_widget()))

    def _attach_current_tool_tab(self) -> None:
        key = self._tool_key_for_widget(self._current_navigation_widget())
        if key:
            self._attach_detached_tool(key)

    def _detach_tool_key(self, key: str) -> None:
        if not key or key in self._detached_tool_windows:
            self._update_window_menu_state()
            return
        widget = self._tool_widgets_by_key.get(key)
        title = self._tool_titles_by_key.get(key, "")
        if widget is None or not title:
            return
        tab_widget = self._tool_tab_widgets_by_key.get(key, self.main_tabs)
        tab_index = tab_widget.indexOf(widget)
        if tab_index < 0:
            return
        placeholder = self._create_detached_tool_placeholder(key)
        tab_label = self._tool_tab_labels_by_key.get(key, title)
        tab_widget.removeTab(tab_index)
        tab_widget.insertTab(tab_index, placeholder, tab_label)
        self._select_tab_widget(tab_widget, placeholder)

        window = DetachedToolWindow(self, key, title)
        if not self.windowIcon().isNull():
            window.setWindowIcon(self.windowIcon())
        window.setCentralWidget(widget)
        minimum_width, minimum_height = self._detached_tool_minimum_size(key)
        window.setMinimumSize(minimum_width, minimum_height)
        widget.setVisible(True)
        widget.show()
        widget.updateGeometry()
        geometry = self.settings.value(f"window/detached/{key}/geometry")
        if geometry:
            window.restoreGeometry(geometry)
        else:
            window.resize(
                max(minimum_width, 900, int(self.width() * 0.72)),
                max(minimum_height, 620, int(self.height() * 0.72)),
            )
        self._detached_tool_windows[key] = window
        window.show()
        window.raise_()
        window.activateWindow()
        self._handle_tool_activated(widget)
        self._update_window_menu_state()
        self.schedule_settings_save()

    def _detached_tool_minimum_size(self, key: str) -> Tuple[int, int]:
        if key == "archive_browser":
            return (1180, 680)
        if key == "texture_workflow":
            return (1120, 680)
        if key == "texture_editor":
            return (980, 640)
        if key == "model_library":
            return (1100, 640)
        if key == "item_icons":
            return (980, 640)
        return (900, 620)

    def _attach_detached_tool(self, key: str, *, select_after: bool = True) -> None:
        window = self._detached_tool_windows.pop(key, None)
        widget = self._tool_widgets_by_key.get(key)
        if widget is None:
            return
        if window is not None:
            self._save_detached_tool_geometry(key, window)
            central_widget = window.takeCentralWidget()
            if central_widget is not None:
                widget = central_widget
            window.hide()
            window.deleteLater()
        placeholder = self._tool_placeholders_by_key.get(key)
        tab_widget = self._tool_tab_widgets_by_key.get(key, self.main_tabs)
        tab_index = tab_widget.indexOf(placeholder) if placeholder is not None else -1
        if tab_index >= 0:
            tab_widget.removeTab(tab_index)
        else:
            tab_index = self._preferred_tool_tab_index(key)
        tab_label = self._tool_tab_labels_by_key.get(key, self._tool_titles_by_key.get(key, key))
        tab_widget.insertTab(tab_index, widget, tab_label)
        widget.updateGeometry()
        if select_after:
            self._select_tab_widget(tab_widget, widget)
            widget.setVisible(True)
            widget.show()
            self._handle_tool_activated(widget)
        self._update_window_menu_state()
        self.schedule_settings_save()

    def _attach_all_detached_tools(self, *_args, select_after: bool = False) -> None:
        for key in list(self._detached_tool_windows.keys()):
            self._attach_detached_tool(key, select_after=select_after)

    def _save_detached_tool_geometry(self, key: str, window: DetachedToolWindow) -> None:
        try:
            self.settings.setValue(f"window/detached/{key}/geometry", window.saveGeometry())
        except Exception:
            pass

    def _save_detached_tool_geometries(self) -> None:
        for key, window in list(self._detached_tool_windows.items()):
            self._save_detached_tool_geometry(key, window)

    def _raise_detached_tool(self, key: str) -> bool:
        window = self._detached_tool_windows.get(key)
        if window is None:
            return False
        if window.isMinimized():
            window.showNormal()
        else:
            window.show()
        window.raise_()
        window.activateWindow()
        return True

    def _activate_tool_key(self, key: str) -> None:
        widget = self._tool_widgets_by_key.get(key)
        if widget is not None:
            self._activate_tool_widget(widget)

    def _activate_tool_widget(self, widget: QWidget) -> None:
        key = self._tool_key_for_widget(widget)
        if key and self._raise_detached_tool(key):
            self._handle_tool_activated(widget)
            self._update_window_menu_state()
            return
        tab_widget = self._tool_tab_widgets_by_key.get(key) if key else self._find_tool_tab_widget(widget)
        if tab_widget is not None:
            self._select_tab_widget(tab_widget, widget)
        if isinstance(widget, LazyToolTab):
            widget.ensure_widget()
        self._handle_tool_activated(widget)
        self._update_window_menu_state()

    def _is_tool_visible_or_current(self, widget: QWidget) -> bool:
        key = self._tool_key_for_widget(widget)
        window = self._detached_tool_windows.get(key)
        if window is not None and window.isVisible():
            return True
        return self._current_navigation_widget() is widget

    def _handle_tool_activated(self, widget: QWidget) -> None:
        if widget is self.workflow_tab:
            self._apply_workflow_content_tab_layout()
            self._queue_current_compare_preview_if_visible()
        elif widget is self.archive_browser_tab:
            self._note_archive_ui_activity()
            self.archive_browser_first_visible_started_at = time.perf_counter()
            if self._archive_browser_render_is_ready():
                self._schedule_archive_browser_first_visible_paint_marker()
            QTimer.singleShot(
                80,
                lambda: self._refresh_archive_browser_if_pending("tab_activation")
                if self._is_tool_visible_or_current(self.archive_browser_tab)
                else None,
            )
        elif widget is self.research_tab:
            QTimer.singleShot(
                80,
                lambda: self.research_tab.refresh_archive_picker_if_pending()
                if self._is_tool_visible_or_current(self.research_tab)
                else None,
            )
        elif widget is getattr(self, "model_library_tab", None):
            self.model_library_tab.handle_activated()
        elif widget is getattr(self, "item_icons_tab", None):
            self.item_icons_tab.schedule_targets_refresh(update_preview=False)

    def show_settings(self, _checked: bool = False) -> None:
        self._activate_tool_widget(self.settings_tab)

    def _update_window_menu_state(self) -> None:
        if not hasattr(self, "detach_current_tab_action"):
            return
        current_navigation_widget = self._current_navigation_widget()
        current_key = self._tool_key_for_widget(current_navigation_widget)
        current_widget = self._tool_widgets_by_key.get(current_key)
        current_is_docked_tool = bool(current_key and current_widget is current_navigation_widget)
        self.detach_current_tab_action.setEnabled(current_is_docked_tool)
        self.attach_current_tool_action.setEnabled(bool(current_key and current_key in self._detached_tool_windows))
        self.attach_all_tools_action.setEnabled(bool(self._detached_tool_windows))


__all__ = ["NavigationControllerMixin"]
