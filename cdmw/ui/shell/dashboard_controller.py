"""Dashboard and archive-cache health UI for shell MainWindow."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cdmw.core.archive import archive_scan_shard_cache_health


class DashboardControllerMixin:
    """Build and refresh dashboard status panels."""

    def _build_dashboard_tab(self) -> None:
        layout = QVBoxLayout(self.dashboard_tab)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        layout.addWidget(scroll)

        content = QWidget()
        content_layout = QVBoxLayout(content)
        content_layout.setContentsMargins(14, 14, 14, 14)
        content_layout.setSpacing(12)
        scroll.setWidget(content)

        title = QLabel("Dashboard")
        title.setObjectName("SectionTitle")
        content_layout.addWidget(title)

        status_grid = QGridLayout()
        status_grid.setContentsMargins(0, 0, 0, 0)
        status_grid.setHorizontalSpacing(12)
        status_grid.setVerticalSpacing(12)
        content_layout.addLayout(status_grid)

        workspace_group = QGroupBox("Workspace")
        workspace_group.setObjectName("DashboardStatusPanel")
        workspace_layout = QGridLayout(workspace_group)
        workspace_layout.setContentsMargins(10, 10, 10, 10)
        workspace_layout.setHorizontalSpacing(10)
        workspace_layout.setVerticalSpacing(6)
        for row, (key, label) in enumerate(
            [
                ("archive_root", "Archive root"),
                ("original_dds_root", "Original DDS root"),
                ("output_root", "Output root"),
                ("texture_editor_png_root", "Texture Editor PNG root"),
                ("texconv", "texconv"),
                ("ncnn", "Real-ESRGAN NCNN"),
            ]
        ):
            self._add_dashboard_status_row(workspace_layout, row, key, label)
        status_grid.addWidget(workspace_group, 0, 0)

        health_group = QGroupBox("Health")
        health_group.setObjectName("DashboardStatusPanel")
        health_layout = QGridLayout(health_group)
        health_layout.setContentsMargins(10, 10, 10, 10)
        health_layout.setHorizontalSpacing(10)
        health_layout.setVerticalSpacing(6)
        for row, (key, label) in enumerate(
            [
                ("archive_index", "Archive index"),
                ("archive_cache", "Archive cache"),
                ("background_tasks", "Background tasks"),
                ("text_search_state", "Text Search"),
                ("replace_queue", "Texture Replacer"),
                ("libraries", "Asset libraries"),
            ]
        ):
            self._add_dashboard_status_row(health_layout, row, key, label)
        status_grid.addWidget(health_group, 0, 1)
        status_grid.setColumnStretch(0, 1)
        status_grid.setColumnStretch(1, 1)

        archive_progress_group = QGroupBox("Archive Cache")
        archive_progress_group.setObjectName("DashboardStatusPanel")
        archive_progress_layout = QGridLayout(archive_progress_group)
        archive_progress_layout.setContentsMargins(10, 10, 10, 10)
        archive_progress_layout.setHorizontalSpacing(10)
        archive_progress_layout.setVerticalSpacing(6)
        self.dashboard_archive_progress_bar = QProgressBar()
        self.dashboard_archive_progress_bar.setRange(0, 100)
        self.dashboard_archive_progress_bar.setValue(int(getattr(self, "_archive_load_progress_percent", 0) or 0))
        self.dashboard_archive_progress_bar.setTextVisible(True)
        self.dashboard_archive_progress_bar.setFormat(f"{self.dashboard_archive_progress_bar.value()}%")
        self.dashboard_archive_progress_bar.setToolTip("Ready to build archive cache.")
        self.dashboard_archive_progress_phase_label = QLabel("Ready")
        self.dashboard_archive_progress_phase_label.setObjectName("DashboardStatusName")
        self.dashboard_archive_progress_phase_label.setAlignment(Qt.AlignCenter)
        self.dashboard_archive_progress_detail_label = QLabel("No archive cache build is running.")
        self.dashboard_archive_progress_detail_label.setObjectName("HintLabel")
        self.dashboard_archive_progress_detail_label.setWordWrap(True)
        archive_progress_layout.addWidget(self.dashboard_archive_progress_bar, 0, 0)
        archive_progress_layout.addWidget(self.dashboard_archive_progress_phase_label, 0, 1)
        archive_progress_layout.addWidget(self.dashboard_archive_progress_detail_label, 1, 0, 1, 2)
        archive_progress_layout.setColumnStretch(0, 1)
        content_layout.addWidget(archive_progress_group)

        recent_group = QGroupBox("Recent Work")
        recent_group.setObjectName("DashboardStatusPanel")
        recent_layout = QGridLayout(recent_group)
        recent_layout.setContentsMargins(10, 10, 10, 10)
        recent_layout.setHorizontalSpacing(10)
        recent_layout.setVerticalSpacing(6)
        for row, (key, label) in enumerate(
            [
                ("recent_archive", "Archive"),
                ("recent_output", "Output"),
                ("recent_replacer", "Replacer output"),
                ("recent_model_library", "Model library"),
                ("recent_icon_library", "Icon library"),
                ("recent_text_search", "Text search"),
            ]
        ):
            self._add_dashboard_status_row(recent_layout, row, key, label)
        content_layout.addWidget(recent_group)

        results_group = QGroupBox("Last Results")
        results_group.setObjectName("DashboardStatusPanel")
        results_layout = QVBoxLayout(results_group)
        results_layout.setContentsMargins(10, 10, 10, 10)
        results_layout.setSpacing(8)
        self.dashboard_last_results_label = QLabel(self._dashboard_last_result_text)
        self.dashboard_last_results_label.setObjectName("HintLabel")
        self.dashboard_last_results_label.setWordWrap(True)
        results_layout.addWidget(self.dashboard_last_results_label)
        result_buttons = QHBoxLayout()
        result_buttons.setSpacing(8)
        self.dashboard_open_output_button = QPushButton("Open Output")
        self.dashboard_review_compare_button = QPushButton("Review Compare")
        self.dashboard_open_log_button = QPushButton("Open Log")
        for button in (
            self.dashboard_open_output_button,
            self.dashboard_review_compare_button,
            self.dashboard_open_log_button,
        ):
            button.setObjectName("DashboardInlineButton")
        self.dashboard_open_output_button.clicked.connect(self.open_output_folder)
        self.dashboard_review_compare_button.clicked.connect(self._dashboard_open_compare)
        self.dashboard_open_log_button.clicked.connect(self._dashboard_open_workflow_log)
        result_buttons.addWidget(self.dashboard_open_output_button)
        result_buttons.addWidget(self.dashboard_review_compare_button)
        result_buttons.addWidget(self.dashboard_open_log_button)
        result_buttons.addStretch(1)
        results_layout.addLayout(result_buttons)
        content_layout.addWidget(results_group)

        content_layout.addStretch(1)
        self._refresh_dashboard()

    def _add_dashboard_status_row(self, layout: QGridLayout, row: int, key: str, label: str) -> None:
        name_label = QLabel(label)
        name_label.setObjectName("DashboardStatusName")
        value_label = QLabel("")
        value_label.setObjectName("DashboardStatusValue")
        value_label.setWordWrap(True)
        value_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(name_label, row, 0)
        layout.addWidget(value_label, row, 1)
        layout.setColumnStretch(1, 1)
        self._dashboard_status_labels[key] = value_label

    def _dashboard_set_status(self, key: str, value: str) -> None:
        label = self._dashboard_status_labels.get(key)
        if label is not None:
            label.setText(str(value or "-"))

    def _set_widget_health_state(self, widget: Optional[QWidget], state: str) -> None:
        if widget is None:
            return
        normalized = str(state or "").strip().lower()
        if normalized not in {"healthy", "building", "missing", "stale", "unhealthy", "unknown"}:
            normalized = ""
        if str(widget.property("healthState") or "") == normalized:
            return
        widget.setProperty("healthState", normalized)
        try:
            widget.style().unpolish(widget)
            widget.style().polish(widget)
        except Exception:
            pass
        widget.update()

    def _dashboard_set_status_health_state(self, key: str, state: str) -> None:
        self._set_widget_health_state(self._dashboard_status_labels.get(key), state)

    def _dashboard_path_status(self, raw_path: str, *, required: bool = False) -> str:
        text = str(raw_path or "").strip()
        if not text:
            return "Not set" if required else "Optional"
        path = Path(text).expanduser()
        try:
            exists = path.exists()
        except OSError:
            exists = False
        return f"{text} ({'ready' if exists else 'missing'})"

    def _set_archive_cache_health(self, state: str, reason: str, *, package_root: str = "") -> None:
        normalized = str(state or "unknown").strip().lower()
        if normalized not in {"unknown", "healthy", "building", "missing", "stale", "unhealthy"}:
            normalized = "unknown"
        reason_text = str(reason or "").strip()
        if not reason_text:
            if normalized == "healthy":
                reason_text = "Cache Status: Healthy."
            elif normalized == "building":
                reason_text = "Cache Status: Building. Archive cache build is running."
            elif normalized in {"missing", "stale", "unhealthy"}:
                reason_text = "Cache Status: Unhealthy. Rebuild archive cache."
            else:
                reason_text = "Cache Status: Unknown. Archive cache has not been checked."
        self._archive_cache_health_state = normalized
        self._archive_cache_health_reason = reason_text
        self._archive_cache_health_checked_path = str(package_root or self.archive_package_root_edit.text().strip() or "")
        self._dashboard_set_status("archive_cache", reason_text)
        self._dashboard_set_status_health_state("archive_cache", normalized)
        self._dashboard_set_archive_progress()

    def _check_archive_cache_health(self, package_root_text: str = "") -> Dict[str, object]:
        root_text = str(package_root_text or self.archive_package_root_edit.text().strip() or "").strip()
        if not root_text:
            self._set_archive_cache_health("unhealthy", "Cache Status: Unhealthy. No Crimson Desert path is set.", package_root="")
            return {"status": "unhealthy", "reason": self._archive_cache_health_reason}
        package_root = Path(root_text).expanduser()
        if not package_root.exists():
            self._set_archive_cache_health(
                "unhealthy",
                f"Cache Status: Unhealthy. Crimson Desert path does not exist: {package_root}",
                package_root=root_text,
            )
            return {"status": "unhealthy", "reason": self._archive_cache_health_reason}
        try:
            report = archive_scan_shard_cache_health(package_root, self.archive_cache_root)
        except Exception as exc:
            report = {"status": "unhealthy", "reason": f"Could not inspect archive cache: {exc}"}
        status = str(report.get("status", "unknown") or "unknown").strip().lower()
        reason = str(report.get("reason", "") or "").strip()
        if status == "healthy":
            self._set_archive_cache_health("healthy", reason or "Cache Status: Healthy.", package_root=root_text)
        elif status == "missing":
            self._set_archive_cache_health(
                "missing",
                reason or "Cache Status: Unhealthy. Archive cache has not been built yet.",
                package_root=root_text,
            )
        elif status == "stale":
            self._set_archive_cache_health(
                "stale",
                reason or "Cache Status: Unhealthy. Archive cache is stale.",
                package_root=root_text,
            )
        else:
            self._set_archive_cache_health(
                "unhealthy",
                reason or "Cache Status: Unhealthy. Archive cache could not be validated.",
                package_root=root_text,
            )
        return dict(report)

    def _warn_if_archive_cache_stale(self, health_report: Mapping[str, object], package_root_text: str) -> None:
        if str(health_report.get("status", "") or "").strip().lower() != "stale":
            return
        root_key = str(package_root_text or "").strip()
        if root_key and root_key == str(getattr(self, "_archive_cache_stale_warning_shown_for", "") or ""):
            return
        self._archive_cache_stale_warning_shown_for = root_key
        reason = str(health_report.get("reason", "") or "Archive cache is stale.").strip()
        finish_startup_splash = getattr(self, "_finish_startup_splash_before_modal", None)
        if callable(finish_startup_splash):
            finish_startup_splash()
        QMessageBox.warning(
            self,
            "Archive Cache Stale",
            (
                f"{reason}\n\n"
                "CDMW will rebuild the archive cache from the current game files now.\n\n"
                "This can happen after a game update, after adding or removing mod archives, "
                "or after repeatedly editing/replacing archive files while testing."
            ),
        )

    def _dashboard_set_archive_progress(self, phase: str = "", detail: str = "", percent: Optional[int] = None) -> None:
        if not hasattr(self, "dashboard_archive_progress_bar"):
            return
        active = bool(getattr(self, "_archive_load_progress_active", False))
        health_state = str(getattr(self, "_archive_cache_health_state", "unknown") or "unknown")
        health_reason = str(getattr(self, "_archive_cache_health_reason", "") or "").strip()
        percent_value = int(
            self.dashboard_archive_progress_bar.value()
            if percent is None
            else min(max(int(percent), 0), 100)
        )
        detail_text = str(detail or getattr(self, "_archive_load_progress_detail", "") or "").strip()
        phase_text = str(phase or "").strip()
        if not active:
            if health_state == "healthy":
                percent_value = 100
                phase_text = "Healthy"
                detail_text = health_reason or "Cache Status: Healthy."
            elif health_state in {"stale", "missing", "unhealthy"}:
                percent_value = 0
                phase_text = "Unhealthy"
                detail_text = health_reason or "Cache Status: Unhealthy. Rebuild archive cache."
            elif health_state == "building":
                phase_text = "Building"
                detail_text = health_reason or "Archive cache build queued."
            else:
                percent_value = 0
                phase_text = "Unknown"
                detail_text = health_reason or "Cache Status: Unknown. Archive cache has not been checked."
        else:
            if not phase_text:
                phase_text = self._archive_progress_phase_for_detail(detail_text)[0] if detail_text else "Working"
            if not detail_text:
                detail_text = "Archive cache build running..."
        progress_health_state = health_state if not active else "building"
        self._set_widget_health_state(self.dashboard_archive_progress_phase_label, progress_health_state)
        self._set_widget_health_state(self.dashboard_archive_progress_detail_label, progress_health_state)
        self.dashboard_archive_progress_bar.setVisible(active)
        self.dashboard_archive_progress_phase_label.setVisible(active)
        self.dashboard_archive_progress_bar.setRange(0, 100)
        self.dashboard_archive_progress_bar.setValue(percent_value)
        self.dashboard_archive_progress_bar.setFormat(f"{percent_value}%")
        self.dashboard_archive_progress_bar.setToolTip(detail_text)
        self.dashboard_archive_progress_phase_label.setText(phase_text)
        self.dashboard_archive_progress_phase_label.setToolTip(detail_text)
        self.dashboard_archive_progress_detail_label.setText(detail_text)
        self.dashboard_archive_progress_detail_label.setToolTip(detail_text)

    def _refresh_dashboard(self) -> None:
        if not getattr(self, "_dashboard_status_labels", None):
            return
        self._dashboard_set_status("archive_root", self._dashboard_path_status(self.archive_package_root_edit.text()))
        self._dashboard_set_status("original_dds_root", self._dashboard_path_status(self.original_dds_edit.text(), required=True))
        self._dashboard_set_status("output_root", self._dashboard_path_status(self.output_root_edit.text(), required=True))
        self._dashboard_set_status("texture_editor_png_root", self._dashboard_path_status(self.texture_editor_png_root_edit.text()))
        self._dashboard_set_status("texconv", self._dashboard_path_status(self.texconv_path_edit.text()))
        ncnn_path = self.ncnn_exe_path_edit.text().strip() if hasattr(self, "ncnn_exe_path_edit") else ""
        self._dashboard_set_status("ncnn", self._dashboard_path_status(ncnn_path))

        archive_total = len(getattr(self, "archive_entries", []) or [])
        archive_shown = len(getattr(self, "archive_filtered_entries", []) or [])
        self._dashboard_set_status(
            "archive_index",
            f"{archive_shown:,} shown / {archive_total:,} loaded" if archive_total else "No archives scanned",
        )
        current_archive_root = self.archive_package_root_edit.text().strip()
        if (
            current_archive_root
            and current_archive_root != str(getattr(self, "_archive_cache_health_checked_path", "") or "")
            and not bool(getattr(self, "_archive_load_progress_active", False))
        ):
            self._check_archive_cache_health(current_archive_root)
        else:
            self._dashboard_set_status(
                "archive_cache",
                str(getattr(self, "_archive_cache_health_reason", "") or "Cache Status: Unknown."),
            )
        running = []
        if getattr(self, "worker_thread", None) is not None:
            running.append("workflow/archive")
        if getattr(self.text_search_tab, "search_worker", None) is not None:
            running.append("text search")
        if getattr(self.replace_assistant_tab, "build_worker", None) is not None:
            running.append("replacer")
        if getattr(self.model_library_tab, "_task_worker", None) is not None:
            running.append("model library")
        self._dashboard_set_status("background_tasks", ", ".join(running) if running else "Idle")
        search_count = len(getattr(self.text_search_tab, "search_results", []) or [])
        self._dashboard_set_status("text_search_state", f"{search_count:,} result(s)" if search_count else "No current search results")
        replacer_items = len(getattr(self.replace_assistant_tab, "items", []) or [])
        self._dashboard_set_status("replace_queue", f"{replacer_items:,} queued item(s)" if replacer_items else "No queued replacements")
        model_count = len(getattr(self.model_library_tab, "local_models", []) or [])
        icon_count = len(getattr(self.item_icons_tab, "records", []) or [])
        self._dashboard_set_status("libraries", f"{model_count:,} local model(s), {icon_count:,} icon source(s)")

        self._dashboard_set_status("recent_archive", self.archive_package_root_edit.text().strip() or "None")
        self._dashboard_set_status("recent_output", self.output_root_edit.text().strip() or "None")
        last_replacer = getattr(self.replace_assistant_tab, "last_built_output_root", None)
        self._dashboard_set_status("recent_replacer", str(last_replacer) if last_replacer else "None")
        catalogue_dir = getattr(self.model_library_tab, "catalogue_dir_edit", None)
        self._dashboard_set_status("recent_model_library", catalogue_dir.text().strip() if catalogue_dir is not None else "None")
        self._dashboard_set_status("recent_icon_library", str(getattr(self.item_icons_tab, "library_root", "")) or "None")
        current_text_path = self.text_search_tab.current_result_path()
        self._dashboard_set_status("recent_text_search", current_text_path or "None")
        self._dashboard_set_archive_progress(percent=int(getattr(self, "_archive_load_progress_percent", 0) or 0))
        if hasattr(self, "dashboard_last_results_label"):
            self.dashboard_last_results_label.setText(self._dashboard_last_result_text)

    def _dashboard_open_compare(self) -> None:
        self._activate_tool_widget(self.workflow_tab)
        compare_index = self.content_tabs.indexOf(self.compare_tab)
        if compare_index >= 0:
            self.content_tabs.setCurrentIndex(compare_index)
        self.refresh_compare_list()
        self._queue_current_compare_preview_if_visible()

    def _dashboard_open_workflow_log(self) -> None:
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)


__all__ = ["DashboardControllerMixin"]
