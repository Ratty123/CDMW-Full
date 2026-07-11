"""Shell responsiveness policy boundary."""

from __future__ import annotations

import time
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QEvent, QObject, Qt, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QDoubleSpinBox,
    QLineEdit,
    QMainWindow,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QToolButton,
    QTreeWidget,
    QWidget,
)

from cdmw.ui.shell.diagnostics_controller import qt_wrapper_is_valid
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget
from cdmw.ui.layout_utils import (
    available_layout_size_for,
    build_responsive_splitter_sizes,
    clamp_splitter_sizes,
    responsive_sidebar_bounds,
)


class ResponsivenessControllerMixin:
    """Responsive shell layout, splitter, and control-density behavior."""

    def resizeEvent(self, event: object) -> None:
        QMainWindow.resizeEvent(self, event)  # type: ignore[arg-type]
        theme_overlay = getattr(self, "theme_change_overlay", None)
        central_widget = self.centralWidget()
        if theme_overlay is not None and central_widget is not None:
            theme_overlay.setGeometry(central_widget.rect())
        if (
            hasattr(self, "_responsive_resize_timer")
            and not self._shutting_down
            and not getattr(self, "_applying_responsive_layout", False)
        ):
            self._responsive_resize_timer.start()

    def changeEvent(self, event: object) -> None:
        QMainWindow.changeEvent(self, event)  # type: ignore[arg-type]
        try:
            event_type = event.type()  # type: ignore[attr-defined]
        except AttributeError:
            return
        screen_change_type = getattr(QEvent.Type, "ScreenChangeInternal", None)
        if (
            screen_change_type is not None
            and event_type == screen_change_type
            and hasattr(self, "_responsive_resize_timer")
            and not getattr(self, "_applying_responsive_layout", False)
        ):
            self._responsive_metrics_dirty = True
            self._responsive_resize_timer.start()

    def _preference_bool(self, key: str, default: bool) -> bool:
        return self._read_bool(f"preferences/{key}", default)

    def _load_saved_splitter_sizes(self, key: str) -> Optional[List[int]]:
        raw_value = self.settings.value(key)
        if raw_value in (None, ""):
            return None
        if isinstance(raw_value, str):
            parts = [part.strip() for part in raw_value.split(",") if part.strip()]
        elif isinstance(raw_value, (list, tuple)):
            parts = list(raw_value)
        else:
            return None
        sizes: List[int] = []
        for part in parts:
            try:
                value = int(part)
            except (TypeError, ValueError):
                return None
            if value <= 0:
                return None
            sizes.append(value)
        return sizes or None

    def _archive_controls_sidebar_bounds(self) -> Tuple[int, int, int]:
        controls_min, controls_pref, controls_max = responsive_sidebar_bounds(self, role="normal")
        scale = controls_min / 320.0 if controls_min > 0 else 1.0
        screen_width, _screen_height = available_layout_size_for(self)
        if screen_width <= 1366:
            readable_values = (300, 330, 360)
        elif screen_width <= 1600:
            readable_values = (320, 360, 400)
        elif screen_width <= 1920:
            readable_values = (340, 390, 460)
        elif screen_width <= 2560:
            readable_values = (390, 460, 560)
        else:
            readable_values = (440, 520, 700)
        readable_min = int(round(readable_values[0] * scale))
        readable_pref = int(round(readable_values[1] * scale))
        readable_max = int(round(readable_values[2] * scale))
        return (
            max(controls_min, readable_min),
            max(controls_pref, readable_pref),
            max(controls_max, readable_max),
        )

    def _apply_responsive_width_policies(self) -> None:
        screen_width, _screen_height = available_layout_size_for(self)
        controls_min, _controls_pref, controls_max = self._archive_controls_sidebar_bounds()
        files_min, _files_pref, _files_max = responsive_sidebar_bounds(self, role="narrow")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        workflow_nav_min, _workflow_nav_pref, workflow_nav_max = responsive_sidebar_bounds(self, role="workflow")
        workflow_content_min, _workflow_content_pref, _workflow_content_max = responsive_sidebar_bounds(self, role="wide")
        for widget in (getattr(self, "archive_controls_group", None), getattr(self, "archive_controls_scroll", None)):
            if widget is not None:
                widget.setMinimumWidth(controls_min)
                widget.setMaximumWidth(controls_max)
        if hasattr(self, "archive_files_group"):
            self.archive_files_group.setMinimumWidth(files_min)
            self.archive_files_group.setMaximumWidth(16777215)
        if hasattr(self, "archive_preview_group"):
            self.archive_preview_group.setMinimumWidth(preview_min)
            self.archive_preview_group.setMaximumWidth(16777215)
        if hasattr(self, "archive_texture_refs_group"):
            if screen_width <= 1366:
                refs_min = 240
            elif screen_width <= 1920:
                refs_min = 280
            else:
                refs_min = 320
            self.archive_texture_refs_group.setMinimumWidth(refs_min)
            self.archive_asset_family_preferred_width = max(refs_min, min(420, int(screen_width * 0.22)))
        if hasattr(self, "left_panel"):
            self.left_panel.setMinimumWidth(workflow_nav_min)
        if hasattr(self, "left_scroll_area"):
            self.left_scroll_area.setMinimumWidth(workflow_nav_min)
            self.left_scroll_area.setMaximumWidth(workflow_nav_max)
        if hasattr(self, "right_panel"):
            self.right_panel.setMinimumWidth(workflow_content_min)
        self._apply_responsive_label_density()

    def _apply_responsive_label_density(self) -> None:
        layout_width, _layout_height = available_layout_size_for(self)
        preview_width = int(getattr(getattr(self, "archive_preview_group", None), "width", lambda: 0)() or 0)
        compact = layout_width <= 1600 or (0 < preview_width <= 620)
        pairs = (
            ("archive_model_preview_settings_button", "Preview Settings", "Preview Settings"),
            ("archive_asset_family_button", "Asset", "Asset Family"),
        )
        for object_name, compact_text, normal_text in pairs:
            widget = getattr(self, object_name, None)
            if isinstance(widget, QPushButton):
                text = compact_text if compact else normal_text
                if widget.text() != text:
                    widget.setText(text)

    def _cache_responsive_control_widgets(self) -> None:
        control_types = (
            QPushButton,
            QToolButton,
            QComboBox,
            QLineEdit,
            QSpinBox,
            QDoubleSpinBox,
            QProgressBar,
        )
        self._responsive_control_widgets = tuple(
            widget
            for widget in self.findChildren(QWidget)
            if isinstance(widget, control_types)
        )

    def _apply_responsive_control_minimums(self) -> None:
        screen_width, screen_height = available_layout_size_for(self)
        scale = responsive_control_scale_for_resolution(screen_width, screen_height)
        if not getattr(self, "_responsive_control_widgets", ()):
            self._cache_responsive_control_widgets()
        for widget in tuple(getattr(self, "_responsive_control_widgets", ())):
            base_min_width = widget.property("_cdmw_responsive_base_min_width")
            if base_min_width is None:
                base_min_width = int(widget.minimumWidth())
                widget.setProperty("_cdmw_responsive_base_min_width", base_min_width)
            base_min_height = widget.property("_cdmw_responsive_base_min_height")
            if base_min_height is None:
                base_min_height = int(widget.minimumHeight())
                widget.setProperty("_cdmw_responsive_base_min_height", base_min_height)
            base_max_width = widget.property("_cdmw_responsive_base_max_width")
            if base_max_width is None:
                base_max_width = int(widget.maximumWidth())
                widget.setProperty("_cdmw_responsive_base_max_width", base_max_width)
            if int(base_min_width) > 0:
                new_min_width = max(0, int(round(int(base_min_width) * scale)))
                if widget.minimumWidth() != new_min_width:
                    widget.setMinimumWidth(new_min_width)
            if int(base_min_height) > 0:
                new_min_height = max(0, int(round(int(base_min_height) * scale)))
                if widget.minimumHeight() != new_min_height:
                    widget.setMinimumHeight(new_min_height)
            if 0 < int(base_max_width) < 16777215:
                new_max_width = max(widget.minimumWidth(), int(round(int(base_max_width) * scale)))
                if widget.maximumWidth() != new_max_width:
                    widget.setMaximumWidth(new_max_width)

    def _apply_responsive_theme_metrics(self) -> None:
        app = QApplication.instance()
        if app is None:
            return
        screen_width, screen_height = available_layout_size_for(self)
        screen_scale = responsive_control_scale_for_resolution(screen_width, screen_height)
        if abs(screen_scale - float(getattr(self, "_current_responsive_control_scale", 0.0))) < 0.001:
            return
        self._current_responsive_control_scale = screen_scale
        from cdmw.ui.shell.theme_controller import apply_app_fonts, apply_app_theme, apply_window_data_fonts

        self.current_theme_key = apply_app_theme(
            app,
            self.settings,
            self.current_theme_key,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        ui_font, data_font = apply_app_fonts(
            app,
            self.settings,
            screen_width=screen_width,
            screen_height=screen_height,
        )
        if hasattr(self, "_apply_data_widget_fonts"):
            self._apply_data_widget_fonts(data_font)
        if hasattr(self, "_sync_archive_controls_font"):
            self._sync_archive_controls_font(ui_font)
        apply_window_data_fonts(self)
        texture_editor_tab = created_tool_widget(getattr(self, "texture_editor_tab", None))
        if texture_editor_tab is not None:
            texture_editor_tab.sync_ui_font(ui_font)
        mesh_editor_tab = created_tool_widget(getattr(self, "mesh_editor_tab", None))
        if mesh_editor_tab is not None:
            mesh_editor_tab.sync_ui_font(ui_font, data_font)
        if hasattr(self, "settings_tab"):
            self.settings_tab.sync_appearance_controls(self.current_theme_key)

    def _normalize_archive_splitter_sizes(self, sizes: Sequence[int], total_width: int) -> List[int]:
        controls_min, _controls_pref, controls_max = self._archive_controls_sidebar_bounds()
        files_min, _files_pref, _files_max = responsive_sidebar_bounds(self, role="narrow")
        preview_min, _preview_pref, _preview_max = responsive_sidebar_bounds(self, role="wide")
        normalized = clamp_splitter_sizes(
            total_width,
            sizes,
            [controls_min, files_min, preview_min],
            fallback_weights=[18, 31, 51],
        )
        if len(normalized) < 3:
            return normalized
        if normalized[0] > controls_max:
            overflow = normalized[0] - controls_max
            normalized[0] = controls_max
            normalized[2] += overflow
        normalized[2] = max(preview_min, int(total_width) - normalized[0] - normalized[1])
        return normalized

    def _archive_files_preferred_width(self) -> int:
        minimum_width = 320
        if not hasattr(self, "archive_tree"):
            return 540
        header = self.archive_tree.header()
        if header is None:
            return 540
        column_width = 0
        for column in range(self.archive_tree.columnCount()):
            if self.archive_tree.isColumnHidden(column):
                continue
            column_width += max(0, header.sectionSize(column))
        margins_width = 0
        if hasattr(self, "archive_files_group"):
            margins = self.archive_files_group.body_layout.contentsMargins()
            margins_width = margins.left() + margins.right()
        scrollbar_width = self.archive_tree.verticalScrollBar().sizeHint().width()
        frame_width = self.archive_tree.frameWidth() * 2
        return max(minimum_width, column_width + margins_width + scrollbar_width + frame_width + 18)

    def _fit_archive_files_pane_to_columns(self) -> None:
        if not hasattr(self, "archive_splitter"):
            return
        sizes = self.archive_splitter.sizes()
        if len(sizes) < 3:
            return
        preferred_width = self._archive_files_preferred_width()
        if sizes[1] <= preferred_width:
            return
        reclaimed_width = sizes[1] - preferred_width
        sizes[1] = preferred_width
        sizes[2] += reclaimed_width
        self.archive_splitter.setSizes(sizes)

    def _schedule_archive_files_pane_fit_to_columns(self) -> None:
        if not hasattr(self, "archive_tree"):
            return
        if self._archive_tree_visible_column_count() >= self.archive_tree.columnCount():
            return
        QTimer.singleShot(0, self._fit_archive_files_pane_to_columns)

    def _apply_archive_preview_content_responsive_sizes(self) -> None:
        if not hasattr(self, "archive_preview_content_splitter"):
            return
        total_width = max(1, self.archive_preview_content_splitter.width())
        if total_width <= 1:
            total_width = max(1, self.archive_preview_group.width() if hasattr(self, "archive_preview_group") else 1200)
        screen_width, _screen_height = available_layout_size_for(self)
        refs_min = self.archive_texture_refs_group.minimumWidth() if hasattr(self, "archive_texture_refs_group") else 280
        if screen_width <= 1920:
            weights = [72, 28]
        elif screen_width <= 2560:
            weights = [65, 35]
        else:
            weights = [60, 40]
        sizes = build_responsive_splitter_sizes(total_width, weights, [360, refs_min])
        self.archive_preview_content_splitter.setSizes(sizes)

    def _apply_default_splitter_sizes(self, total_width: int) -> None:
        self._apply_responsive_width_policies()
        workflow_nav_min, _workflow_nav_pref, _workflow_nav_max = responsive_sidebar_bounds(self, role="workflow")
        workflow_content_min, _workflow_content_pref, _workflow_content_max = responsive_sidebar_bounds(self, role="wide")
        self.workflow_splitter.setSizes(
            build_responsive_splitter_sizes(total_width, [42, 58], [workflow_nav_min, workflow_content_min])
        )
        available_right_height = max(420, self.height() - 260)
        progress_min_height = getattr(self, "progress_group_min_height", 190)
        self.workflow_right_splitter.setSizes(
            build_responsive_splitter_sizes(
                available_right_height,
                [18, 82],
                [progress_min_height, 320],
            )
        )
        self.compare_splitter.setSizes(
            build_responsive_splitter_sizes(total_width, [22, 78], [220, 520])
        )
        self.archive_splitter.setSizes(
            self._normalize_archive_splitter_sizes(
                build_responsive_splitter_sizes(
                    total_width,
                    [18, 31, 51],
                    [
                        self._archive_controls_sidebar_bounds()[0],
                        responsive_sidebar_bounds(self, role="narrow")[0],
                        responsive_sidebar_bounds(self, role="wide")[0],
                    ],
                ),
                total_width,
            )
        )
        for tab in (
            created_tool_widget(getattr(self, "replace_assistant_tab", None)),
            created_tool_widget(getattr(self, "research_tab", None)),
            created_tool_widget(getattr(self, "text_search_tab", None)),
        ):
            if tab is not None:
                tab.apply_responsive_splitter_sizes(total_width)
        self._apply_archive_preview_content_responsive_sizes()

    def _apply_saved_splitter_sizes_if_enabled(self, total_width: int) -> None:
        self._apply_default_splitter_sizes(total_width)
        if not self._preference_bool("remember_splitter_sizes", True):
            return

        for splitter, setting_key in (
            (self.workflow_splitter, "ui/workflow_splitter_sizes"),
            (self.workflow_right_splitter, "ui/workflow_right_splitter_sizes_v2"),
            (self.compare_splitter, "ui/compare_splitter_sizes_v2"),
            (self.archive_splitter, "ui/archive_splitter_sizes"),
        ):
            sizes = self._load_saved_splitter_sizes(setting_key)
            if sizes:
                if splitter is self.workflow_right_splitter and len(sizes) >= 2:
                    available_right_height = max(420, self.height() - 260)
                    progress_min_height = getattr(self, "progress_group_min_height", 190)
                    sizes = clamp_splitter_sizes(
                        available_right_height,
                        sizes,
                        [progress_min_height, 320],
                        fallback_weights=[18, 82],
                    )
                elif splitter is self.workflow_splitter:
                    workflow_nav_min, _workflow_nav_pref, _workflow_nav_max = responsive_sidebar_bounds(self, role="workflow")
                    workflow_content_min, _workflow_content_pref, _workflow_content_max = responsive_sidebar_bounds(self, role="wide")
                    sizes = clamp_splitter_sizes(
                        total_width,
                        sizes,
                        [workflow_nav_min, workflow_content_min],
                        fallback_weights=[42, 58],
                    )
                elif splitter is self.compare_splitter:
                    sizes = clamp_splitter_sizes(total_width, sizes, [220, 520], fallback_weights=[22, 78])
                elif splitter is self.archive_splitter:
                    sizes = self._normalize_archive_splitter_sizes(sizes, total_width)
                splitter.setSizes(sizes)
        self._schedule_archive_files_pane_fit_to_columns()

        text_search_sizes = self._load_saved_splitter_sizes("ui/text_search_splitter_sizes")
        text_search_tab = created_tool_widget(getattr(self, "text_search_tab", None))
        if text_search_sizes and text_search_tab is not None:
            text_search_tab.set_splitter_sizes(text_search_sizes)
        replace_assistant_sizes = self._load_saved_splitter_sizes("ui/replace_assistant_splitter_sizes")
        replace_assistant_tab = created_tool_widget(getattr(self, "replace_assistant_tab", None))
        if replace_assistant_sizes and replace_assistant_tab is not None:
            replace_assistant_tab.set_splitter_sizes(replace_assistant_sizes, total_width=total_width)
        research_tab = created_tool_widget(getattr(self, "research_tab", None))
        research_main_sizes = self._load_saved_splitter_sizes("ui/research_main_splitter_sizes")
        if research_main_sizes and research_tab is not None:
            research_tab.set_main_splitter_sizes(research_main_sizes, total_width=total_width)
        research_groups_sizes = self._load_saved_splitter_sizes("ui/research_groups_splitter_sizes")
        if research_groups_sizes and research_tab is not None:
            research_tab.set_groups_splitter_sizes(research_groups_sizes, total_width=total_width)
        research_unknown_sizes = self._load_saved_splitter_sizes("ui/research_unknown_splitter_sizes")
        if research_unknown_sizes and research_tab is not None:
            research_tab.set_unknown_splitter_sizes(research_unknown_sizes, total_width=total_width)
        research_reference_sizes = self._load_saved_splitter_sizes("ui/research_reference_splitter_sizes")
        if research_reference_sizes and research_tab is not None:
            research_tab.set_reference_splitter_sizes(research_reference_sizes, total_width=total_width)
        research_analysis_sizes = self._load_saved_splitter_sizes("ui/research_analysis_splitter_sizes")
        if research_analysis_sizes and research_tab is not None:
            research_tab.set_analysis_splitter_sizes(research_analysis_sizes, total_width=total_width)
        research_notes_sizes = self._load_saved_splitter_sizes("ui/research_notes_splitter_sizes")
        if research_notes_sizes and research_tab is not None:
            research_tab.set_notes_splitter_sizes(research_notes_sizes, total_width=total_width)
        self._apply_archive_preview_content_responsive_sizes()

    def _apply_responsive_window_defaults(
        self,
        *,
        restore_saved_splitters: bool = True,
        schedule_column_autofit: bool = True,
        apply_expensive_metrics: bool = True,
        adjust_window_geometry: bool = True,
    ) -> None:
        if getattr(self, "_applying_responsive_layout", False):
            return
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return
        started_at = time.perf_counter()
        self._applying_responsive_layout = True
        try:
            if apply_expensive_metrics:
                self._apply_responsive_theme_metrics()
                self._apply_responsive_control_minimums()
                self._responsive_metrics_dirty = False
            available = screen.availableGeometry()
            if (
                adjust_window_geometry
                and
                not self.isMaximized()
                and not self.isFullScreen()
                and (self.width() > available.width() - 24 or self.height() > available.height() - 24)
            ):
                self.resize(
                    max(self.minimumWidth(), min(int(available.width() * 0.94), available.width() - 24)),
                    max(self.minimumHeight(), min(int(available.height() * 0.92), available.height() - 24)),
                )
            if adjust_window_geometry and not self.isMaximized() and not self.isFullScreen():
                frame = self.frameGeometry()
                x = frame.x()
                y = frame.y()
                max_x = max(available.left(), available.right() - frame.width() + 1)
                max_y = max(available.top(), available.bottom() - frame.height() + 1)
                self.move(
                    min(max(x, available.left()), max_x),
                    min(max(y, available.top()), max_y),
                )
            if restore_saved_splitters:
                total_width = max(1, self.width() - 64)
                self._apply_saved_splitter_sizes_if_enabled(total_width)
            if schedule_column_autofit:
                self._schedule_column_autofit()
        finally:
            elapsed_ms = int(max(0.0, time.perf_counter() - started_at) * 1000)
            self._responsive_resize_last_elapsed_ms = elapsed_ms
            recorder = getattr(self, "_record_runtime_event", None)
            if callable(recorder) and (elapsed_ms >= 40 or apply_expensive_metrics or restore_saved_splitters):
                recorder(
                    "responsive_resize_applied",
                    responsive_resize_elapsed_ms=elapsed_ms,
                    restore_saved_splitters=bool(restore_saved_splitters),
                    apply_expensive_metrics=bool(apply_expensive_metrics),
                    adjust_window_geometry=bool(adjust_window_geometry),
                )
            self._applying_responsive_layout = False

    def _apply_initial_responsive_window_defaults(self) -> None:
        self._apply_responsive_window_defaults(apply_expensive_metrics=False)

    def _apply_responsive_resize_adjustments(self) -> None:
        self._apply_responsive_window_defaults(
            restore_saved_splitters=False,
            schedule_column_autofit=False,
            apply_expensive_metrics=False,
            adjust_window_geometry=False,
        )

    def _screen_signature_for_responsive_layout(self) -> Tuple[int, int, float]:
        screen = self.screen() or QApplication.primaryScreen()
        if screen is None:
            return (0, 0, 0.0)
        geometry = screen.availableGeometry()
        try:
            pixel_ratio = float(screen.devicePixelRatio())
        except Exception:
            pixel_ratio = 1.0
        return (int(geometry.width()), int(geometry.height()), round(pixel_ratio, 3))

    def _handle_responsive_screen_changed(self, _screen: object = None) -> None:
        if getattr(self, "_applying_responsive_layout", False):
            return
        signature = self._screen_signature_for_responsive_layout()
        if signature == getattr(self, "_responsive_last_screen_signature", (0, 0, 0.0)):
            return
        self._responsive_last_screen_signature = signature
        self._responsive_metrics_dirty = True
        self._responsive_resize_timer.start(260)

    def _connect_responsive_screen_signals(self) -> None:
        window_handle = self.windowHandle()
        if window_handle is None or getattr(self, "_responsive_screen_signal_connected", False):
            return
        self._responsive_last_screen_signature = self._screen_signature_for_responsive_layout()
        window_handle.screenChanged.connect(self._handle_responsive_screen_changed)
        self._responsive_screen_signal_connected = True

    def _schedule_column_autofit(self) -> None:
        if self._shutting_down:
            return
        self._column_autofit_timer.start()

    def _fit_tree_columns(
        self,
        tree: QTreeWidget,
        *,
        stretch_column: int,
        min_widths: Dict[int, int],
    ) -> None:
        header = tree.header()
        if header is None or tree.columnCount() <= 0:
            return
        viewport_width = max(tree.viewport().width(), tree.width() - 24, 0)
        if viewport_width <= 0:
            return
        tree.setUpdatesEnabled(False)
        try:
            fixed_width = 0
            for column in range(tree.columnCount()):
                if column == stretch_column:
                    continue
                width = max(min_widths.get(column, 72), header.sectionSize(column))
                header.resizeSection(column, width)
                fixed_width += width
            stretch_width = max(min_widths.get(stretch_column, 180), viewport_width - fixed_width - 12)
            header.resizeSection(stretch_column, stretch_width)
        finally:
            tree.setUpdatesEnabled(True)

    def _autofit_archive_tree_columns(self) -> None:
        header = self.archive_tree.header()
        if header is None:
            return
        if self._parse_archive_tree_column_ints("ui/archive_tree_v4_column_widths", clamp_to_columns=False):
            return
        use_fast_widths = bool(
            hasattr(self.archive_tree, "set_archive_state")
            or len(getattr(self, "archive_filtered_entries", ()) or ()) > 5000
            or len(getattr(self, "archive_entries", ()) or ()) > 5000
        )
        font_metrics = header.fontMetrics()
        min_widths = {
            0: max(180, font_metrics.horizontalAdvance("Name") + 48),
            1: max(160, font_metrics.horizontalAdvance("Exact Item Name") + 28),
            2: max(170, font_metrics.horizontalAdvance("Related Name Hint") + 28),
            3: max(72, font_metrics.horizontalAdvance("Folder") + 28),
            4: max(112, font_metrics.horizontalAdvance("9999.9 KB") + 28),
            5: max(84, font_metrics.horizontalAdvance("Partial") + 28),
            6: max(132, font_metrics.horizontalAdvance("0009/20.pamt") + 28),
            7: max(122, font_metrics.horizontalAdvance("Shadowed original") + 28),
            8: max(220, font_metrics.horizontalAdvance("Path") + 48),
        }
        max_widths = {
            0: 360,
            1: 280,
            2: 260,
            3: 110,
            4: 160,
            5: 120,
            6: 180,
            7: 180,
        }
        self.archive_tree.setUpdatesEnabled(False)
        try:
            for column in range(self.archive_tree.columnCount()):
                if self.archive_tree.isColumnHidden(column):
                    continue
                content_width = 0 if use_fast_widths else self.archive_tree.sizeHintForColumn(column) + 28
                width = max(min_widths.get(column, 72), content_width)
                max_width = max_widths.get(column)
                if max_width is not None and column != 8:
                    width = min(width, max_width)
                header.resizeSection(column, width)
        finally:
            self.archive_tree.setUpdatesEnabled(True)

    def _apply_column_autofit(self) -> None:
        self._autofit_archive_tree_columns()
        for tab in (
            created_tool_widget(getattr(self, "replace_assistant_tab", None)),
            created_tool_widget(getattr(self, "text_search_tab", None)),
            created_tool_widget(getattr(self, "research_tab", None)),
        ):
            if tab is not None:
                tab.auto_fit_columns()



class ResponsivenessController:
    def __init__(self, context: object | None = None) -> None:
        self.context = context


def responsive_control_scale_for_resolution(screen_width: int, screen_height: int) -> float:
    if screen_width <= 1366:
        width_scale = 0.78
    elif screen_width <= 1600:
        width_scale = 0.84
    elif screen_width <= 1920:
        width_scale = 0.90
    elif screen_width <= 2560:
        width_scale = 0.96
    else:
        width_scale = 1.0
    if screen_height <= 768:
        height_scale = 0.78
    elif screen_height <= 900:
        height_scale = 0.84
    elif screen_height <= 1080:
        height_scale = 0.90
    elif screen_height <= 1200:
        height_scale = 0.94
    else:
        height_scale = 1.0
    return min(width_scale, height_scale)


def responsive_control_scale_for_width(screen_width: int) -> float:
    fallback_height = 1080 if screen_width <= 1920 else 1440
    return responsive_control_scale_for_resolution(screen_width, fallback_height)


def expand_tree_columns_to_available_width(tree: QTreeWidget) -> None:
    if not qt_wrapper_is_valid(tree) or not isinstance(tree, QTreeWidget):
        return
    try:
        if bool(tree.property("cdmw_disable_auto_column_fill")):
            return
    except Exception:
        return
    header = tree.header()
    if header is None:
        return
    count = header.count()
    if count <= 0:
        return
    try:
        visible_columns = [column for column in range(count) if not header.isSectionHidden(column)]
        viewport_width = int(tree.viewport().width())
    except Exception:
        return
    if not visible_columns or viewport_width <= 0:
        return
    current_widths = [max(1, int(header.sectionSize(column))) for column in visible_columns]
    total_width = sum(current_widths)
    extra_width = viewport_width - total_width - 2
    if extra_width <= max(12, len(visible_columns) * 3):
        return
    weight_total = max(1, total_width)
    remaining = extra_width
    for index, column in enumerate(visible_columns):
        if index == len(visible_columns) - 1:
            add_width = remaining
        else:
            add_width = max(1, int(round(extra_width * (current_widths[index] / weight_total))))
            remaining -= add_width
        if add_width <= 0:
            continue
        try:
            header.resizeSection(column, int(header.sectionSize(column)) + add_width)
        except Exception:
            pass


class AutoTreeColumnWidthEventFilter(QObject):
    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        try:
            event_type = event.type()
        except RuntimeError:
            return False
        if (
            event_type in (QEvent.Type.Show, QEvent.Type.Resize, QEvent.Type.LayoutRequest)
            and qt_wrapper_is_valid(watched)
            and isinstance(watched, QTreeWidget)
        ):
            QTimer.singleShot(0, lambda tree=watched: expand_tree_columns_to_available_width(tree))
        return False


class TreeHorizontalWheelGuard(QObject):
    def __init__(self, tree: QTreeWidget) -> None:
        super().__init__(tree)
        self._tree = tree

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:  # type: ignore[override]
        if event.type() != QEvent.Type.Wheel:
            return False
        tree = self._tree
        try:
            horizontal_bar = tree.horizontalScrollBar()
            previous_value = int(horizontal_bar.value())
            pixel_delta = event.pixelDelta()  # type: ignore[attr-defined]
            angle_delta = event.angleDelta()  # type: ignore[attr-defined]
            has_horizontal_delta = int(pixel_delta.x()) != 0 or int(angle_delta.x()) != 0
            has_vertical_delta = int(pixel_delta.y()) != 0 or int(angle_delta.y()) != 0
            modifiers = event.modifiers()  # type: ignore[attr-defined]
        except Exception:
            return False
        if not has_horizontal_delta or modifiers & Qt.ShiftModifier:
            return False
        if not has_vertical_delta:
            return True

        def _restore_horizontal_scroll() -> None:
            try:
                horizontal_bar.setValue(max(horizontal_bar.minimum(), min(previous_value, horizontal_bar.maximum())))
            except RuntimeError:
                pass

        QTimer.singleShot(0, _restore_horizontal_scroll)
        return False


__all__ = [
    "AutoTreeColumnWidthEventFilter",
    "ResponsivenessController",
    "ResponsivenessControllerMixin",
    "TreeHorizontalWheelGuard",
    "expand_tree_columns_to_available_width",
    "responsive_control_scale_for_resolution",
    "responsive_control_scale_for_width",
]
