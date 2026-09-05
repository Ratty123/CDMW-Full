"""Navigation and detachable tool-window helpers for shell MainWindow."""

from __future__ import annotations

import time
from typing import Optional, Tuple

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QStackedWidget, QVBoxLayout, QWidget

from cdmw.ui.shell.lazy_tool_tab import LazyToolTab, as_label
from cdmw.ui.shell.tab_registry import DetachedToolWindow


class NavigationControllerMixin:
    """Route tool activation and detach/attach tool tabs."""

    def focus_archive_locations(self) -> None:
        self._activate_tool_widget(self.settings_tab)
        if hasattr(self.settings_tab, "show_settings_section"):
            self.settings_tab.show_settings_section("paths")
        self.archive.archive_locations_section.set_expanded(True)
        self.textures.setup_section.set_expanded(False)
        self.textures.paths_section.set_expanded(False)
        self.archive.archive_package_root_edit.setFocus()

    def _find_tool_tab_widget(self, widget: QWidget) -> Optional[QStackedWidget]:
        return self.tool_stack if self.tool_stack.indexOf(widget) >= 0 else None

    def _current_navigation_widget(self) -> Optional[QWidget]:
        return self.tool_stack.currentWidget()

    def _select_tab_widget(self, tab_widget: QStackedWidget, widget: QWidget) -> None:
        if tab_widget.indexOf(widget) >= 0:
            tab_widget.setCurrentWidget(widget)

    def _restore_saved_navigation(self) -> None:
        if not self._preference_bool("restore_last_active_tab", True):
            self._activate_tool_key("archive_browser")
            return
        saved_key = str(self.settings.value("ui/active_tool_key", "") or "").strip()
        if saved_key == "dashboard":
            self._activate_tool_key("archive_browser")
            return
        from cdmw.ui.texture_workflow.job import TEXTURE_TOOL_ALIASES
        if saved_key in self._tool_widgets_by_key or saved_key in TEXTURE_TOOL_ALIASES:
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

    def _register_detachable_tool(
        self, key: str, widget: QWidget, title: str, *, detachable: bool = True,
    ) -> None:
        self.tab_registry.register(key, widget, title)
        if detachable:
            self._detachable_tool_order.append(key)
        index = self.tool_stack.addWidget(widget)
        self._tool_tab_home_index_by_key[key] = index

    def _build_window_tool_menu_actions(self) -> None:
        for key in self._detachable_tool_order:
            title = self._tool_titles_by_key[key]
            if getattr(self, "is_compact_shell", False):
                from cdmw.ui.shell.compact.registry import compact_tool_label

                title = compact_tool_label(key, title)
            action = self.window_menu.addAction(as_label(f"Show {title}"))
            action.triggered.connect(lambda _checked=False, tool_key=key: self._activate_tool_key(tool_key))
            self._tool_window_actions[key] = action
        self._update_window_menu_state()

    def _create_detached_tool_placeholder(self, key: str) -> QWidget:
        existing = self._tool_placeholders_by_key.get(key)
        if existing is not None:
            return existing
        title = self._tool_titles_by_key.get(key, "Tool")
        if getattr(self, "is_compact_shell", False):
            from cdmw.ui.shell.compact.registry import compact_tool_label

            title = compact_tool_label(key, title)
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
        return min(self._tool_tab_home_index_by_key.get(key, self.tool_stack.count()), self.tool_stack.count())

    def _detach_current_tool_tab(self) -> None:
        self._detach_tool_key(self._tool_key_for_widget(self._current_navigation_widget()))

    def _attach_current_tool_tab(self) -> None:
        key = self._tool_key_for_widget(self._current_navigation_widget())
        if key:
            self._attach_detached_tool(key)


    def _detach_tool_key(self, key: str) -> None:
        if (
            not key
            or key not in self._detachable_tool_order
            or key in self._detached_tool_windows
        ):
            self._update_window_menu_state()
            return
        widget = self._tool_widgets_by_key.get(key)
        title = self._tool_titles_by_key.get(key, "")
        if getattr(self, "is_compact_shell", False):
            from cdmw.ui.shell.compact.registry import compact_tool_label

            title = compact_tool_label(key, title)
        if widget is None or not title:
            return
        tab_widget = self.tool_stack
        tab_index = tab_widget.indexOf(widget)
        if tab_index < 0:
            return
        placeholder = self._create_detached_tool_placeholder(key)
        tab_widget.removeWidget(widget)
        tab_widget.insertWidget(tab_index, placeholder)
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
        tab_widget = self.tool_stack
        tab_index = tab_widget.indexOf(placeholder) if placeholder is not None else -1
        if tab_index >= 0:
            tab_widget.removeWidget(placeholder)
        else:
            tab_index = self._preferred_tool_tab_index(key)
        tab_widget.insertWidget(tab_index, widget)
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
        from cdmw.ui.texture_workflow.job import TEXTURE_TOOL_ALIASES
        if key in TEXTURE_TOOL_ALIASES:
            self.textures.activate_texture_alias(key)
            key = "textures"
        widget = self._tool_widgets_by_key.get(key)
        if widget is not None:
            self._activate_tool_widget(widget)

    def _activate_tool_widget(self, widget: QWidget) -> None:
        for key in ("texture_editor", "recolor_variants", "replace_assistant"):
            if widget is getattr(self, key + "_tab", None):
                self.textures.activate_texture_alias(key)
                widget = self.textures
                break
        key = self._tool_key_for_widget(widget)
        if key and self._raise_detached_tool(key):
            self._handle_tool_activated(widget)
            self._update_window_menu_state()
            return
        tab_widget = self._find_tool_tab_widget(widget)
        if tab_widget is not None:
            self._select_tab_widget(tab_widget, widget)
        if isinstance(widget, LazyToolTab):
            widget.request_widget()
        self._handle_tool_activated(widget)
        self._update_window_menu_state()

    def _is_tool_visible_or_current(self, widget: QWidget) -> bool:
        key = self._tool_key_for_widget(widget)
        window = self._detached_tool_windows.get(key)
        if window is not None and window.isVisible():
            return True
        return self._current_navigation_widget() is widget

    def _handle_tool_activated(self, widget: QWidget) -> None:
        if self.classic_navigation is not None:
            self.classic_navigation.set_active_tool(self._tool_key_for_widget(widget))
        if isinstance(widget, LazyToolTab) and widget.widget_if_created() is None:
            tool_key = self._tool_key_for_widget(widget)
            pending = getattr(self, "_pending_lazy_tool_activation_keys", None)
            if pending is None:
                pending = self._pending_lazy_tool_activation_keys = set()
            if tool_key not in pending:
                pending.add(tool_key)

                def finish_activation(
                    _created: QWidget,
                    *,
                    container: LazyToolTab = widget,
                    key: str = tool_key,
                ) -> None:
                    pending.discard(key)
                    if self._is_tool_visible_or_current(container):
                        self._handle_tool_activated(container)
                        self._update_window_menu_state()

                widget.when_created(finish_activation)
            widget.request_widget()
            from cdmw.ui.shell.compact.workspace import sync_compact_workspace_selection

            sync_compact_workspace_selection(self, tool_key)
            return
        if widget is self.textures.workflow_tab:
            self.textures.set_texture_mode(self.textures.job.mode)
        elif widget is self.archive_browser_tab:
            self.archive._note_archive_ui_activity()
            self.archive.archive_browser_first_visible_started_at = time.perf_counter()
            if self.archive._archive_browser_render_is_ready():
                self.archive._schedule_archive_browser_first_visible_paint_marker()
            QTimer.singleShot(
                80,
                self.tool_stack,
                lambda: self.archive._refresh_archive_browser_if_pending("tab_activation")
                if self._is_tool_visible_or_current(self.archive_browser_tab)
                else None,
            )
        elif widget is self.research_tab:
            QTimer.singleShot(
                80,
                self.tool_stack,
                lambda: self.research_tab.refresh_archive_picker_if_pending()
                if self._is_tool_visible_or_current(self.research_tab)
                else None,
            )
        elif widget is getattr(self, "model_library_tab", None):
            self.model_library_tab.handle_activated()
        elif widget is getattr(self, "item_icons_tab", None):
            self.item_icons_tab.schedule_targets_refresh(update_preview=False)
        from cdmw.ui.shell.compact.workspace import sync_compact_workspace_selection

        sync_compact_workspace_selection(self, self._tool_key_for_widget(widget))

    def show_settings(self, _checked: bool = False) -> None:
        self._activate_tool_widget(self.settings_tab)

    def _update_window_menu_state(self) -> None:
        if not hasattr(self, "detach_current_tab_action"):
            return
        current_navigation_widget = self._current_navigation_widget()
        current_key = self._tool_key_for_widget(current_navigation_widget)
        current_widget = self._tool_widgets_by_key.get(current_key)
        current_is_docked_tool = bool(
            current_key
            and current_key in self._detachable_tool_order
            and current_widget is current_navigation_widget
        )
        self.detach_current_tab_action.setEnabled(current_is_docked_tool)
        self.attach_current_tool_action.setEnabled(bool(current_key and current_key in self._detached_tool_windows))
        self.attach_all_tools_action.setEnabled(bool(self._detached_tool_windows))


__all__ = ["NavigationControllerMixin"]
