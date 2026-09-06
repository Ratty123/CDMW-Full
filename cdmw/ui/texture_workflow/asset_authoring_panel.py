"""Texture Workflow asset-authoring helper panel."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.shell.texture_panel_persistence import finish_texture_workflow_panel_body
from cdmw.ui.widgets import CollapsibleSection

if TYPE_CHECKING:
    from cdmw.services.asset_authoring_service import AssetAuthoringService


OPENIMAGEIO_SOURCE_SETTINGS_KEY = "asset_authoring/oiio_source_path"
OPENIMAGEIO_OUTPUT_SETTINGS_KEY = "asset_authoring/oiio_output_path"
OPENIMAGEIO_COMPARE_SETTINGS_KEY = "asset_authoring/oiio_compare_path"


def openimageio_task_status_text(result: Mapping[str, object] | object, operation: str = "") -> tuple[str, bool]:
    if not isinstance(result, Mapping):
        return "OpenImageIO task returned an invalid report.", True
    operation_text = str(operation or result.get("operation") or "task").replace("_", " ").strip()
    status = str(result.get("status") or "unknown").strip()
    if status == "ok":
        return f"OpenImageIO {operation_text} complete.", False
    if status == "different":
        return "OpenImageIO diff complete. Images differ.", False
    detail = str(result.get("message") or result.get("stderr") or status or "unknown error").strip()
    missing = result.get("missing")
    if isinstance(missing, list) and missing:
        detail = "Missing: " + ", ".join(str(path) for path in missing)
    return f"OpenImageIO {operation_text} failed: {detail}", True


def openimageio_task_report_text(result: Mapping[str, object] | object, operation: str = "") -> str:
    status_text, _is_error = openimageio_task_status_text(result, operation)
    if not isinstance(result, Mapping):
        return status_text

    lines = [status_text]
    for key, label in (
        ("source_path", "Source"),
        ("output_path", "Output"),
        ("left_path", "Left"),
        ("right_path", "Right"),
        ("returncode", "Return code"),
    ):
        value = str(result.get(key, "") or "").strip()
        if value:
            lines.append(f"{label}: {value}")

    metadata = result.get("metadata")
    if isinstance(metadata, Mapping) and metadata:
        width = str(metadata.get("width", "") or "").strip()
        height = str(metadata.get("height", "") or "").strip()
        channels = str(metadata.get("channel_count", "") or "").strip()
        bit_depth = str(metadata.get("bit_depth", "") or "").strip()
        color_space = str(metadata.get("color_space", "") or "").strip()
        parts = []
        if width and height:
            parts.append(f"{width} x {height}")
        if channels:
            parts.append(f"{channels} channel(s)")
        if bit_depth:
            parts.append(f"{bit_depth}-bit")
        if color_space:
            parts.append(color_space)
        if parts:
            lines.append("Metadata: " + ", ".join(parts))

    for key in ("stdout", "stderr"):
        value = str(result.get(key, "") or "").strip()
        if value:
            lines.append(f"{key}:")
            lines.append(value[:2000])

    return "\n".join(lines)


class TextureWorkflowAssetAuthoringPanelMixin:
    """Build and run OpenImageIO asset-authoring tasks in Texture Workflow."""

    def _build_texture_workflow_asset_authoring_section(
        self,
        left_layout: QVBoxLayout,
        *,
        expanded: bool = False,
    ) -> None:
        self.asset_authoring_section = CollapsibleSection(
            "Asset Authoring",
            body_builder=lambda body_layout: TextureWorkflowAssetAuthoringPanelMixin._build_texture_workflow_asset_authoring_body(
                self,
                body_layout,
            ),
        )
        left_layout.addWidget(self.asset_authoring_section)
        self.asset_authoring_section.set_expanded(expanded)

    def _build_texture_workflow_asset_authoring_body(self, body_layout: QVBoxLayout) -> None:

        oiio_group = QWidget()
        oiio_layout = QGridLayout(oiio_group)
        oiio_layout.setContentsMargins(0, 0, 0, 0)
        oiio_layout.setHorizontalSpacing(10)
        oiio_layout.setVerticalSpacing(10)
        oiio_layout.setColumnStretch(0, 1)
        self.openimageio_source_path_edit = QLineEdit()
        self.openimageio_output_path_edit = QLineEdit()
        self.openimageio_compare_path_edit = QLineEdit()
        self.openimageio_source_browse_button = self.shell._add_path_row(
            oiio_layout,
            0,
            "OpenImageIO source",
            self.openimageio_source_path_edit,
            self._browse_openimageio_source_path,
            stacked=True,
        )
        self.openimageio_output_browse_button = self.shell._add_path_row(
            oiio_layout,
            1,
            "Converted output",
            self.openimageio_output_path_edit,
            self._browse_openimageio_output_path,
            stacked=True,
        )
        self.openimageio_compare_browse_button = self.shell._add_path_row(
            oiio_layout,
            2,
            "Diff against",
            self.openimageio_compare_path_edit,
            self._browse_openimageio_compare_path,
            stacked=True,
        )

        oiio_button_row = QHBoxLayout()
        oiio_button_row.setSpacing(8)
        self.openimageio_metadata_button = QPushButton("Metadata")
        self.openimageio_convert_button = QPushButton("Convert")
        self.openimageio_diff_button = QPushButton("Diff")
        self.openimageio_metadata_button.clicked.connect(self.start_openimageio_metadata)
        self.openimageio_convert_button.clicked.connect(self.start_openimageio_convert)
        self.openimageio_diff_button.clicked.connect(self.start_openimageio_diff)
        oiio_button_row.addWidget(self.openimageio_metadata_button)
        oiio_button_row.addWidget(self.openimageio_convert_button)
        oiio_button_row.addWidget(self.openimageio_diff_button)
        oiio_button_row.addStretch(1)
        self.openimageio_status_label = QLabel("")
        self.openimageio_status_label.setObjectName("HintLabel")
        self.openimageio_status_label.setWordWrap(True)
        self.openimageio_report_view = QPlainTextEdit()
        self.openimageio_report_view.setReadOnly(True)
        self.openimageio_report_view.document().setMaximumBlockCount(200)
        self.openimageio_report_view.setMaximumHeight(130)

        body_layout.addWidget(oiio_group)
        body_layout.addLayout(oiio_button_row)
        body_layout.addWidget(self.openimageio_status_label)
        body_layout.addWidget(self.openimageio_report_view)
        finish_texture_workflow_panel_body(self, "asset_authoring")

    def _asset_authoring_service(self) -> AssetAuthoringService:
        from cdmw.services.asset_authoring_service import AssetAuthoringService

        return AssetAuthoringService(settings=None)

    def _openimageio_configured_paths(self) -> dict[str, object]:
        configured: dict[str, object] = {}
        settings = getattr(self.shell, "settings", None)
        value = getattr(settings, "value", None)
        if not callable(value):
            return configured
        openimageio_path = str(value("asset_authoring/oiio_path", "") or "").strip()
        if openimageio_path:
            configured["openimageio"] = openimageio_path
        return configured

    def _browse_openimageio_source_path(self) -> None:
        self.shell._browse_file(
            self.openimageio_source_path_edit,
            "Select Source Image",
            "Source images (*.psd *.tga *.exr *.tif *.tiff *.ptex *.ptx *.png *.jpg *.jpeg *.bmp);;All files (*.*)",
        )

    def _browse_openimageio_output_path(self) -> None:
        self.shell._browse_file(
            self.openimageio_output_path_edit,
            "Select Converted Output",
            "PNG files (*.png);;All files (*.*)",
            save_mode=True,
        )

    def _browse_openimageio_compare_path(self) -> None:
        self.shell._browse_file(
            self.openimageio_compare_path_edit,
            "Select Diff Target",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga *.tif *.tiff *.exr *.dds);;All files (*.*)",
        )

    def _openimageio_existing_path(self, line_edit: QLineEdit, label: str) -> Path | None:
        raw = line_edit.text().strip()
        if not raw:
            self.shell.set_status_message(f"{label} path is empty.", error=True)
            return None
        path = Path(raw).expanduser()
        if not path.is_file():
            self.shell.set_status_message(f"{label} does not exist: {path}", error=True)
            return None
        return path

    def _openimageio_output_path(self) -> Path | None:
        raw = self.openimageio_output_path_edit.text().strip()
        if not raw:
            self.shell.set_status_message("OpenImageIO output path is empty.", error=True)
            return None
        return Path(raw).expanduser()

    def start_openimageio_metadata(self) -> None:
        source_path = self._openimageio_existing_path(self.openimageio_source_path_edit, "OpenImageIO source")
        if source_path is None:
            return
        self._start_openimageio_task("metadata", (source_path,))

    def start_openimageio_convert(self) -> None:
        source_path = self._openimageio_existing_path(self.openimageio_source_path_edit, "OpenImageIO source")
        output_path = self._openimageio_output_path()
        if source_path is None or output_path is None:
            return
        self._start_openimageio_task("convert", (source_path, output_path))

    def start_openimageio_diff(self) -> None:
        left_path = self._openimageio_existing_path(self.openimageio_source_path_edit, "OpenImageIO source")
        right_path = self._openimageio_existing_path(self.openimageio_compare_path_edit, "OpenImageIO diff target")
        if left_path is None or right_path is None:
            return
        self._start_openimageio_task("diff", (left_path, right_path))

    def _start_openimageio_task(self, operation: str, paths: tuple[Path, ...]) -> None:
        from cdmw.workers.asset_authoring_workers import OpenImageIOTaskWorker

        if self.shell._background_task_active():
            if self.shell.worker_thread is not None:
                self.shell.set_status_message(
                    "Another background task is still running. Wait for it to finish before running OpenImageIO.",
                    error=True,
                )
            return

        operation_text = operation.replace("_", " ")
        self.shell.set_status_message(f"Running OpenImageIO {operation_text}...")
        self.shell.append_log(f"Starting OpenImageIO {operation_text}.")
        self.openimageio_status_label.setText(f"Running OpenImageIO {operation_text}...")
        self.openimageio_report_view.clear()
        self.shell.reset_progress()
        self.phase_value.setText("OpenImageIO")
        self.current_file_value.setText(paths[0].name if paths else operation_text)
        self._set_phase_progress(0, 0, f"Running OpenImageIO {operation_text}...", "Steps")
        self.shell._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)

        configured_paths = self._openimageio_configured_paths()
        worker = OpenImageIOTaskWorker(
            operation,
            paths,
            configured_paths=configured_paths,
            service=self._asset_authoring_service(),
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        self._openimageio_active_operation = operation
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_openimageio_task_complete)
        worker.cancelled.connect(self._handle_openimageio_task_cancelled)
        worker.error.connect(self.shell._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self.shell._cleanup_worker_refs)

        self.shell.utility_worker = worker
        self.shell.worker_thread = thread
        self.shell.set_busy(True, build_mode=True)
        thread.start()

    def _handle_openimageio_task_complete(self, result: object) -> None:
        operation = str(getattr(self, "_openimageio_active_operation", "") or "")
        status_text, is_error = openimageio_task_status_text(result, operation)
        self.openimageio_status_label.setText(status_text)
        self.openimageio_report_view.setPlainText(openimageio_task_report_text(result, operation))
        self.current_file_value.setText("Completed" if not is_error else "Failed")
        self.shell.set_status_message(status_text, error=is_error)
        self.shell.append_log(status_text if not is_error else f"ERROR: {status_text}")

    def _handle_openimageio_task_cancelled(self, message: str) -> None:
        self.openimageio_status_label.setText(message)
        self.openimageio_report_view.setPlainText(message)
        self._handle_build_cancelled(message)


__all__ = [
    "OPENIMAGEIO_COMPARE_SETTINGS_KEY",
    "OPENIMAGEIO_OUTPUT_SETTINGS_KEY",
    "OPENIMAGEIO_SOURCE_SETTINGS_KEY",
    "TextureWorkflowAssetAuthoringPanelMixin",
    "openimageio_task_report_text",
    "openimageio_task_status_text",
]
