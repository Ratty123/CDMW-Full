"""Texture Workflow asset-authoring helper panel."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import TYPE_CHECKING

from PySide6.QtCore import QThread, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QVBoxLayout, QWidget

from cdmw.ui.shell.texture_panel_persistence import finish_texture_workflow_panel_body
from cdmw.ui.widgets import CollapsibleSection

if TYPE_CHECKING:
    from cdmw.services.asset_authoring_service import AssetAuthoringService


MATERIAL_MAKER_PROJECT_SETTINGS_KEY = "asset_authoring/material_maker_project_path"
MATERIAL_MAKER_EXPORT_DIR_SETTINGS_KEY = "asset_authoring/material_maker_export_dir"
OPENIMAGEIO_SOURCE_SETTINGS_KEY = "asset_authoring/oiio_source_path"
OPENIMAGEIO_OUTPUT_SETTINGS_KEY = "asset_authoring/oiio_output_path"
OPENIMAGEIO_COMPARE_SETTINGS_KEY = "asset_authoring/oiio_compare_path"
MATERIAL_MAKER_EXPORT_TEMPLATE_SETTING = "asset_authoring/material_maker_export_template"


def material_maker_export_status_text(result: Mapping[str, object] | object) -> tuple[str, bool]:
    if not isinstance(result, Mapping):
        return "Material Maker export returned an invalid report.", True
    export_report = result.get("export_report")
    export = export_report if isinstance(export_report, Mapping) else {}
    status = str(result.get("status") or export.get("status") or "unknown").strip()
    texture_set_report = result.get("texture_set_report")
    texture_set = texture_set_report if isinstance(texture_set_report, Mapping) else {}
    texture_status = str(texture_set.get("status") or "").strip()
    channels = texture_set.get("channels")
    channel_names = sorted(str(name) for name in channels.keys()) if isinstance(channels, Mapping) else []

    if status == "ok" and texture_status == "ok":
        channel_text = ", ".join(channel_names) if channel_names else "none"
        return f"Material Maker export complete. {len(channel_names)} mapped channel(s): {channel_text}.", False
    if status == "ok" and texture_status:
        return f"Material Maker export complete, but texture-set review returned {texture_status}.", texture_status != "ok"
    if status == "ok":
        return "Material Maker export complete, but no texture-set report was returned.", True

    detail = str(export.get("message") or export.get("stderr") or status or "unknown error").strip()
    return f"Material Maker export failed: {detail}", True


def material_maker_export_report_text(result: Mapping[str, object] | object) -> str:
    status_text, _is_error = material_maker_export_status_text(result)
    if not isinstance(result, Mapping):
        return status_text

    lines = [status_text]
    export_report = result.get("export_report")
    export = export_report if isinstance(export_report, Mapping) else {}
    for key, label in (
        ("project_path", "Project"),
        ("output_dir", "Output"),
        ("returncode", "Return code"),
    ):
        value = str(export.get(key, "") or "").strip()
        if value:
            lines.append(f"{label}: {value}")

    texture_set_report = result.get("texture_set_report")
    texture_set = texture_set_report if isinstance(texture_set_report, Mapping) else {}
    channels = texture_set.get("channels")
    if isinstance(channels, Mapping) and channels:
        lines.append("Mapped channels:")
        for channel, payload in sorted(channels.items(), key=lambda item: str(item[0])):
            row = payload if isinstance(payload, Mapping) else {}
            path = str(row.get("path", "") or "").strip()
            profile = str(row.get("profile_hint", "") or "").strip()
            detail = f"{channel}: {path}" if path else str(channel)
            if profile:
                detail += f" ({profile})"
            lines.append(detail)

    warnings = texture_set.get("warnings")
    if isinstance(warnings, list) and warnings:
        lines.append("Warnings:")
        lines.extend(str(item) for item in warnings if str(item).strip())

    unmapped = texture_set.get("unmapped")
    if isinstance(unmapped, list) and unmapped:
        lines.append("Unmapped:")
        lines.extend(str(item) for item in unmapped if str(item).strip())

    return "\n".join(lines)


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
    """Build and run optional asset-authoring integrations in Texture Workflow."""

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

        asset_group = QWidget()
        asset_layout = QGridLayout(asset_group)
        asset_layout.setContentsMargins(0, 0, 0, 0)
        asset_layout.setHorizontalSpacing(10)
        asset_layout.setVerticalSpacing(10)
        asset_layout.setColumnMinimumWidth(0, 136)
        asset_layout.setColumnStretch(1, 1)

        self.material_maker_project_edit = QLineEdit()
        self.material_maker_export_dir_edit = QLineEdit()
        self.material_maker_project_browse_button = self._add_path_row(
            asset_layout,
            0,
            "Material Maker project",
            self.material_maker_project_edit,
            self._browse_material_maker_project,
        )
        self.material_maker_export_dir_browse_button = self._add_path_row(
            asset_layout,
            1,
            "Export folder",
            self.material_maker_export_dir_edit,
            self._browse_material_maker_export_dir,
        )

        button_row = QHBoxLayout()
        button_row.setSpacing(8)
        self.material_maker_open_button = QPushButton("Open Project")
        self.material_maker_export_button = QPushButton("Export Maps")
        self.material_maker_open_export_folder_button = QPushButton("Open Folder")
        self.material_maker_open_button.clicked.connect(self.open_material_maker_project)
        self.material_maker_export_button.clicked.connect(self.start_material_maker_export)
        self.material_maker_open_export_folder_button.clicked.connect(self.open_material_maker_export_folder)
        button_row.addWidget(self.material_maker_open_button)
        button_row.addWidget(self.material_maker_export_button)
        button_row.addWidget(self.material_maker_open_export_folder_button)
        button_row.addStretch(1)

        self.material_maker_export_status_label = QLabel("")
        self.material_maker_export_status_label.setObjectName("HintLabel")
        self.material_maker_export_status_label.setWordWrap(True)
        self.material_maker_export_report_view = QPlainTextEdit()
        self.material_maker_export_report_view.setReadOnly(True)
        self.material_maker_export_report_view.document().setMaximumBlockCount(200)
        self.material_maker_export_report_view.setMaximumHeight(130)

        oiio_group = QWidget()
        oiio_layout = QGridLayout(oiio_group)
        oiio_layout.setContentsMargins(0, 0, 0, 0)
        oiio_layout.setHorizontalSpacing(10)
        oiio_layout.setVerticalSpacing(10)
        oiio_layout.setColumnMinimumWidth(0, 136)
        oiio_layout.setColumnStretch(1, 1)
        self.openimageio_source_path_edit = QLineEdit()
        self.openimageio_output_path_edit = QLineEdit()
        self.openimageio_compare_path_edit = QLineEdit()
        self.openimageio_source_browse_button = self._add_path_row(
            oiio_layout,
            0,
            "OpenImageIO source",
            self.openimageio_source_path_edit,
            self._browse_openimageio_source_path,
        )
        self.openimageio_output_browse_button = self._add_path_row(
            oiio_layout,
            1,
            "Converted output",
            self.openimageio_output_path_edit,
            self._browse_openimageio_output_path,
        )
        self.openimageio_compare_browse_button = self._add_path_row(
            oiio_layout,
            2,
            "Diff against",
            self.openimageio_compare_path_edit,
            self._browse_openimageio_compare_path,
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

        body_layout.addWidget(asset_group)
        body_layout.addLayout(button_row)
        body_layout.addWidget(self.material_maker_export_status_label)
        body_layout.addWidget(self.material_maker_export_report_view)
        body_layout.addWidget(oiio_group)
        body_layout.addLayout(oiio_button_row)
        body_layout.addWidget(self.openimageio_status_label)
        body_layout.addWidget(self.openimageio_report_view)
        finish_texture_workflow_panel_body(self, "asset_authoring")

    def _asset_authoring_service(self) -> AssetAuthoringService:
        from cdmw.services.asset_authoring_service import AssetAuthoringService

        return AssetAuthoringService(settings=None)

    def _material_maker_configured_paths(self) -> dict[str, object]:
        configured: dict[str, object] = {}
        settings = getattr(self, "settings", None)
        value = getattr(settings, "value", None)
        if not callable(value):
            return configured
        material_maker_path = str(value("asset_authoring/material_maker_path", "") or "").strip()
        export_template = value(MATERIAL_MAKER_EXPORT_TEMPLATE_SETTING, "")
        if material_maker_path:
            configured["material_maker"] = material_maker_path
        if export_template:
            configured["material_maker_export_template"] = export_template
        return configured

    def _openimageio_configured_paths(self) -> dict[str, object]:
        configured: dict[str, object] = {}
        settings = getattr(self, "settings", None)
        value = getattr(settings, "value", None)
        if not callable(value):
            return configured
        openimageio_path = str(value("asset_authoring/oiio_path", "") or "").strip()
        if openimageio_path:
            configured["openimageio"] = openimageio_path
        return configured

    def _browse_material_maker_project(self) -> None:
        self._browse_file(
            self.material_maker_project_edit,
            "Select Material Maker Project",
            "Material Maker projects (*.mm *.material *.json);;All files (*.*)",
        )

    def _browse_material_maker_export_dir(self) -> None:
        self._browse_directory(self.material_maker_export_dir_edit, "Select Material Maker Export Folder")

    def _browse_openimageio_source_path(self) -> None:
        self._browse_file(
            self.openimageio_source_path_edit,
            "Select Source Image",
            "Source images (*.psd *.tga *.exr *.tif *.tiff *.ptex *.ptx *.png *.jpg *.jpeg *.bmp);;All files (*.*)",
        )

    def _browse_openimageio_output_path(self) -> None:
        self._browse_file(
            self.openimageio_output_path_edit,
            "Select Converted Output",
            "PNG files (*.png);;All files (*.*)",
            save_mode=True,
        )

    def _browse_openimageio_compare_path(self) -> None:
        self._browse_file(
            self.openimageio_compare_path_edit,
            "Select Diff Target",
            "Images (*.png *.jpg *.jpeg *.bmp *.tga *.tif *.tiff *.exr *.dds);;All files (*.*)",
        )

    def _material_maker_project_path(self) -> Path | None:
        raw = self.material_maker_project_edit.text().strip()
        if not raw:
            self.set_status_message("Material Maker project path is empty.", error=True)
            return None
        path = Path(raw).expanduser()
        if not path.is_file():
            self.set_status_message(f"Material Maker project does not exist: {path}", error=True)
            return None
        return path

    def _material_maker_export_dir_path(self) -> Path | None:
        raw = self.material_maker_export_dir_edit.text().strip()
        if not raw:
            self.set_status_message("Material Maker export folder is empty.", error=True)
            return None
        return Path(raw).expanduser()

    def _openimageio_existing_path(self, line_edit: QLineEdit, label: str) -> Path | None:
        raw = line_edit.text().strip()
        if not raw:
            self.set_status_message(f"{label} path is empty.", error=True)
            return None
        path = Path(raw).expanduser()
        if not path.is_file():
            self.set_status_message(f"{label} does not exist: {path}", error=True)
            return None
        return path

    def _openimageio_output_path(self) -> Path | None:
        raw = self.openimageio_output_path_edit.text().strip()
        if not raw:
            self.set_status_message("OpenImageIO output path is empty.", error=True)
            return None
        return Path(raw).expanduser()

    def open_material_maker_project(self) -> None:
        project_path = self._material_maker_project_path()
        if project_path is None:
            return

        service = self._asset_authoring_service()
        configured_paths = self._material_maker_configured_paths()

        def task(_on_log) -> dict[str, object]:
            return service.open_material_maker_project(project_path, configured_paths)

        def on_complete(result: object) -> None:
            payload = result if isinstance(result, Mapping) else {}
            status = str(payload.get("status") or "unknown")
            if status == "launched":
                message = f"Material Maker launched: {project_path.name}."
                self.set_status_message(message)
                self.append_log(message)
                return
            message = str(payload.get("message") or f"Material Maker launch failed: {status}").strip()
            self.set_status_message(message, error=True)
            self.append_log(f"ERROR: {message}")

        self._run_utility_task(
            status_message="Opening Material Maker project...",
            task=task,
            on_complete=on_complete,
        )

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

        if self._background_task_active():
            if self.worker_thread is not None:
                self.set_status_message(
                    "Another background task is still running. Wait for it to finish before running OpenImageIO.",
                    error=True,
                )
            return

        operation_text = operation.replace("_", " ")
        self.set_status_message(f"Running OpenImageIO {operation_text}...")
        self.append_log(f"Starting OpenImageIO {operation_text}.")
        self.openimageio_status_label.setText(f"Running OpenImageIO {operation_text}...")
        self.openimageio_report_view.clear()
        self.reset_progress()
        self.phase_value.setText("OpenImageIO")
        self.current_file_value.setText(paths[0].name if paths else operation_text)
        self._set_phase_progress(0, 0, f"Running OpenImageIO {operation_text}...", "Steps")
        self._activate_tool_widget(self.workflow_tab)
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
        worker.error.connect(self._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker_refs)

        self.utility_worker = worker
        self.worker_thread = thread
        self.set_busy(True, build_mode=True)
        thread.start()

    def _handle_openimageio_task_complete(self, result: object) -> None:
        operation = str(getattr(self, "_openimageio_active_operation", "") or "")
        status_text, is_error = openimageio_task_status_text(result, operation)
        self.openimageio_status_label.setText(status_text)
        self.openimageio_report_view.setPlainText(openimageio_task_report_text(result, operation))
        self.current_file_value.setText("Completed" if not is_error else "Failed")
        self.set_status_message(status_text, error=is_error)
        self.append_log(status_text if not is_error else f"ERROR: {status_text}")
        if not is_error:
            self._queue_current_compare_preview_if_visible()

    def _handle_openimageio_task_cancelled(self, message: str) -> None:
        self.openimageio_status_label.setText(message)
        self.openimageio_report_view.setPlainText(message)
        self._handle_build_cancelled(message)

    def start_material_maker_export(self) -> None:
        from cdmw.workers.asset_authoring_workers import MaterialMakerExportWorker

        if self._background_task_active():
            if self.worker_thread is not None:
                self.set_status_message(
                    "Another background task is still running. Wait for it to finish before exporting Material Maker maps.",
                    error=True,
                )
            return
        project_path = self._material_maker_project_path()
        output_dir = self._material_maker_export_dir_path()
        if project_path is None or output_dir is None:
            return

        self.set_status_message("Running Material Maker export...")
        self.append_log("Starting Material Maker export.")
        self.material_maker_export_status_label.setText("Running Material Maker export...")
        self.material_maker_export_report_view.clear()
        self.reset_progress()
        self.phase_value.setText("Material Maker")
        self.current_file_value.setText(project_path.name)
        self._activate_tool_widget(self.workflow_tab)
        self.content_tabs.setCurrentIndex(0)

        configured_paths = self._material_maker_configured_paths()
        worker = MaterialMakerExportWorker(
            project_path,
            output_dir,
            configured_paths=configured_paths,
            material_name=project_path.stem,
            service=self._asset_authoring_service(),
        )
        thread = QThread(self)
        worker.moveToThread(thread)

        thread.started.connect(worker.run)
        worker.progress_changed.connect(self._handle_material_maker_export_progress)
        worker.completed.connect(self._handle_material_maker_export_complete)
        worker.cancelled.connect(self._handle_material_maker_export_cancelled)
        worker.error.connect(self._handle_worker_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker_refs)

        self.utility_worker = worker
        self.worker_thread = thread
        self.set_busy(True, build_mode=True)
        thread.start()

    def _handle_material_maker_export_progress(self, current: int, total: int, detail: str) -> None:
        self.phase_value.setText("Material Maker")
        self.current_file_value.setText(str(detail or "Working..."))
        self._set_phase_progress(current, total, str(detail or "Working..."), "Steps")
        self.set_status_message(str(detail or "Running Material Maker export..."))

    def _handle_material_maker_export_complete(self, result: object) -> None:
        status_text, is_error = material_maker_export_status_text(result)
        self.material_maker_export_status_label.setText(status_text)
        self.material_maker_export_report_view.setPlainText(material_maker_export_report_text(result))
        self.current_file_value.setText("Completed" if not is_error else "Failed")
        self.set_status_message(status_text, error=is_error)
        self.append_log(status_text if not is_error else f"ERROR: {status_text}")
        if is_error:
            return
        self._refresh_material_maker_preview_outputs()

    def _handle_material_maker_export_cancelled(self, message: str) -> None:
        self.material_maker_export_status_label.setText(message)
        self.material_maker_export_report_view.setPlainText(message)
        self._handle_build_cancelled(message)

    def _refresh_material_maker_preview_outputs(self) -> None:
        self.refresh_compare_list(select_current=True)
        self._queue_current_compare_preview_if_visible()
        if self._is_tool_visible_or_current(self.archive_browser_tab):
            self._force_refresh_current_model_preview_assets()
            self.append_log("Requested Archive Browser .NET/Vortice Preview refresh for generated texture maps.")
        self._refresh_dashboard()

    def open_material_maker_export_folder(self) -> None:
        output_dir = self._material_maker_export_dir_path()
        if output_dir is None:
            return
        try:
            output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            self.set_status_message(f"Could not create Material Maker export folder: {exc}", error=True)
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(output_dir.resolve())))


__all__ = [
    "MATERIAL_MAKER_EXPORT_DIR_SETTINGS_KEY",
    "MATERIAL_MAKER_PROJECT_SETTINGS_KEY",
    "OPENIMAGEIO_COMPARE_SETTINGS_KEY",
    "OPENIMAGEIO_OUTPUT_SETTINGS_KEY",
    "OPENIMAGEIO_SOURCE_SETTINGS_KEY",
    "TextureWorkflowAssetAuthoringPanelMixin",
    "material_maker_export_report_text",
    "material_maker_export_status_text",
    "openimageio_task_report_text",
    "openimageio_task_status_text",
]
