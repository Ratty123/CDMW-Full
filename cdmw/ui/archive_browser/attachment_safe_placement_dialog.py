"""Safe-placement dialog for archive attachment workflows."""

from __future__ import annotations

import dataclasses
import json
import platform
import shutil
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import QSize, Qt, QProcess, QThread, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.constants import MODEL_PREVIEW_BACKGROUND_COLOR, MODEL_PREVIEW_TEXT_COLOR
from cdmw.services.archive_preview_service import build_archive_preview_result
from cdmw.services.archive_workflow_service import build_prefab_socket_name_patch
from cdmw.services.archive_read_service import read_archive_entry_data
from cdmw.domain.archives.mesh_contracts import ArchiveLooseExportResult
from cdmw.services.archive_mutation_service import ArchivePatchRequest
from cdmw.services.archive_workflow_service import export_archive_payloads_to_mod_ready_loose
from cdmw.models import (
    ArchiveEntry,
    ArchivePreviewResult,
    AssetFamilyGraph,
    AttachmentPlacementEvidence,
    AttachmentSocketInfo,
    ModelPreviewData,
    clamp_model_preview_render_settings,
)
from cdmw.services.preview_rendering_service import find_native_d3d11_host
from cdmw.ui.archive_browser.attachment_task_controller import (
    attachment_task_controller_for_guard,
)
from cdmw.ui.native_d3d11_preview_host import NativeD3D11PreviewHostFrame
from cdmw.ui.shell.diagnostics_controller import d3d11_status_file_signature as _d3d11_status_file_signature
from cdmw.ui.shell.responsiveness_controller import expand_tree_columns_to_available_width
from cdmw.workers.d3d11_package_workers import AlignmentD3D11PackageWorker
from cdmw.workers.attachment_io_workers import (
    AttachmentContextRequest,
    AttachmentContextResult,
    run_attachment_context_resolution,
)
from cdmw.workers.preview_workers import VisualPlacementPreviewWorker


class ArchiveAttachmentSafePlacementDialogMixin:
    """D3D11-only safe placement editor for attachment workflows."""

    def _open_archive_attachment_safe_placement_dialog(
        self,
        target_entry: ArchiveEntry,
        donor_entry: Optional[ArchiveEntry],
        target_graph: AssetFamilyGraph,
        donor_graph: Optional[AssetFamilyGraph] = None,
        package_plan_rows: Sequence[dict] = (),
        _context_result: AttachmentContextResult | None = None,
    ) -> None:
        # D3D11-only placement editor: crash dumps showed Qt fail-fast inside Qt renderer widgets.
        target_model_entry = self._attachment_visual_model_entry(target_entry, target_graph)
        donor_graph = donor_graph if isinstance(donor_graph, AssetFamilyGraph) else None
        donor_model_entry = (
            self._attachment_visual_model_entry(donor_entry, donor_graph)
            if isinstance(donor_entry, ArchiveEntry) and isinstance(donor_graph, AssetFamilyGraph)
            else None
        )
        target_evidence = self._attachment_visual_best_evidence(target_graph)
        target_socket_entry: Optional[ArchiveEntry] = self._attachment_socket_entry_from_selection(target_graph)
        donor_socket_entry: Optional[ArchiveEntry] = None
        socket_entry: Optional[ArchiveEntry] = target_socket_entry
        socket_name = str(getattr(target_evidence, "weapon_socket_name", "") or "")
        donor_prefab: Optional[ArchiveEntry] = None
        if isinstance(donor_entry, ArchiveEntry) and isinstance(donor_graph, AssetFamilyGraph):
            donor_prefab = self._choose_attachment_package_donor_prefab(donor_entry, donor_graph, None)
            if isinstance(donor_prefab, ArchiveEntry):
                socket_entries = self._attachment_package_socket_entries_for_prefab(donor_graph, donor_prefab)
                donor_socket_entry = socket_entries[0] if socket_entries else None
                if isinstance(donor_socket_entry, ArchiveEntry):
                    socket_entry = donor_socket_entry
        donor_evidence = self._attachment_visual_evidence_for_prefab(donor_graph, donor_prefab)
        if isinstance(donor_evidence, AttachmentPlacementEvidence) and donor_evidence.weapon_socket_name:
            socket_name = donor_evidence.weapon_socket_name
        extra_socket_roots: List[Path] = []
        context_request = AttachmentContextRequest(
            target_graph=target_graph,
            target_evidence=target_evidence,
            target_model_entry=target_model_entry,
            target_socket_entry=target_socket_entry,
            donor_graph=donor_graph,
            donor_evidence=donor_evidence,
            donor_model_entry=donor_model_entry,
            donor_socket_entry=donor_socket_entry,
        )

        def _run_context_request(request: AttachmentContextRequest, *, stop_event: object) -> object:
            return run_attachment_context_resolution(
                request,
                resolver=self._attachment_visual_resolve_context,
                stop_event=stop_event,
            )

        if not isinstance(_context_result, AttachmentContextResult):
            controller = attachment_task_controller_for_guard(
                self,
                self,
                attribute="_attachment_safe_context_controller",
            )
            plan_snapshot = tuple(dict(row) for row in package_plan_rows)

            def _context_ready(result: object) -> None:
                if not isinstance(result, AttachmentContextResult):
                    QMessageBox.warning(self, "Safe Placement Editor", "Context resolver returned an unexpected result.")
                    return
                self._open_archive_attachment_safe_placement_dialog(
                    target_entry,
                    donor_entry,
                    target_graph,
                    donor_graph,
                    package_plan_rows=plan_snapshot,
                    _context_result=result,
                )

            controller.start(
                context_request,
                _run_context_request,
                status_message=f"Resolving placement context for {target_entry.basename}...",
                on_complete=_context_ready,
                on_error=lambda message: QMessageBox.warning(
                    self,
                    "Safe Placement Editor",
                    message,
                ),
            )
            return
        context_state: Dict[str, Dict[str, object]] = {
            "target": dict(_context_result.target),
            "donor": dict(_context_result.donor),
        }
        dialog = QDialog(self)
        dialog.setWindowTitle(f"Safe Placement Editor - {target_entry.basename}")
        dialog.resize(1280, 780)
        context_task_controller = attachment_task_controller_for_guard(self, dialog)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        intro = QLabel(
            "This editor uses native D3D11 when available and never creates the crashing in-process renderer widget. "
            "Pick a recovered attach point, review the socket chain, optionally drag/tune offset/rotation, then build the same loose package copy plan."
        )
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)
        splitter = QSplitter(Qt.Horizontal)
        layout.addWidget(splitter, 1)

        controls = QWidget()
        controls_layout = QVBoxLayout(controls)
        controls_layout.setContentsMargins(0, 0, 8, 0)
        controls_layout.setSpacing(8)
        candidate_combo = QComboBox()
        controls_layout.addWidget(QLabel("Placement"))
        controls_layout.addWidget(candidate_combo)
        preview_style_combo = QComboBox()
        preview_style_combo.addItem("Socket schematic (recommended)", "schematic")
        if isinstance(target_model_entry, ArchiveEntry):
            preview_style_combo.addItem("Decoded mesh overlay (diagnostic)", "mesh")
        preview_style_combo.setToolTip(
            "Socket schematic uses stable weapon proxies so hip/back placement changes are visible. "
            "Decoded mesh overlay is diagnostic and may be noisy for recovered PAC geometry."
        )
        controls_layout.addWidget(QLabel("Preview style"))
        controls_layout.addWidget(preview_style_combo)
        candidate_tree = QTreeWidget()
        candidate_tree.setColumnCount(5)
        candidate_tree.setHeaderLabels(["Attach point", "Pivot socket", "Parent", "Translation", "Source"])
        candidate_tree.setRootIsDecorated(False)
        candidate_tree.setAlternatingRowColors(True)
        candidate_tree.setUniformRowHeights(True)
        candidate_tree.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        candidate_tree.setEditTriggers(QAbstractItemView.NoEditTriggers)
        candidate_tree.header().setStretchLastSection(True)
        candidate_tree.header().resizeSection(0, 190)
        candidate_tree.header().resizeSection(1, 155)
        candidate_tree.header().resizeSection(2, 150)
        candidate_tree.header().resizeSection(3, 155)
        controls_layout.addWidget(candidate_tree, 1)
        evidence_root_button = QPushButton("Import Socket Evidence Folder...")
        controls_layout.addWidget(evidence_root_button)

        def _spin(value: float, minimum: float, maximum: float, step: float, decimals: int, suffix: str = "") -> QDoubleSpinBox:
            spin = QDoubleSpinBox()
            spin.setRange(minimum, maximum)
            spin.setDecimals(decimals)
            spin.setSingleStep(step)
            spin.setValue(value)
            spin.setKeyboardTracking(False)
            if suffix:
                spin.setSuffix(suffix)
            return spin

        transform_group = QGroupBox("Numeric Adjustment")
        transform_layout = QGridLayout(transform_group)
        transform_layout.setContentsMargins(8, 8, 8, 8)
        offset_spins = [_spin(0.0, -1.0, 1.0, 0.005, 4) for _index in range(3)]
        rotation_spins = [_spin(0.0, -180.0, 180.0, 0.25, 2, " deg") for _index in range(3)]
        for column, axis in enumerate(("X", "Y", "Z"), start=1):
            transform_layout.addWidget(QLabel(axis), 0, column)
        transform_layout.addWidget(QLabel("Offset"), 1, 0)
        for column, spin in enumerate(offset_spins, start=1):
            transform_layout.addWidget(spin, 1, column)
        transform_layout.addWidget(QLabel("Rotation"), 2, 0)
        for column, spin in enumerate(rotation_spins, start=1):
            transform_layout.addWidget(spin, 2, column)
        reset_button = QPushButton("Reset")
        transform_layout.addWidget(reset_button, 3, 0, 1, 4)
        controls_layout.addWidget(transform_group)
        socket_note = QLabel("")
        socket_note.setObjectName("HintLabel")
        socket_note.setWordWrap(True)
        socket_note.setTextInteractionFlags(Qt.TextSelectableByMouse)
        controls_layout.addWidget(socket_note)
        splitter.addWidget(controls)

        preview_group = QGroupBox("Placement Preview")
        preview_layout = QVBoxLayout(preview_group)
        preview_layout.setContentsMargins(8, 8, 8, 8)
        preview_layout.setSpacing(6)
        preview_stack = QStackedWidget()
        placement_d3d11_host_binary = find_native_d3d11_host() if platform.system().lower() == "windows" else None
        placement_d3d11_available = bool(placement_d3d11_host_binary is not None)
        if not placement_d3d11_available:
            if platform.system().lower() != "windows":
                reason = "Native D3D11 placement preview is Windows-only."
            else:
                reason = "Native D3D11 host is missing."
            QMessageBox.critical(
                dialog,
                "Native D3D11 Required",
                f"{reason}\n\nNo fallback preview renderer is available.",
            )
            return
        d3d11_page = QWidget()
        d3d11_layout = QVBoxLayout(d3d11_page)
        d3d11_layout.setContentsMargins(0, 0, 0, 0)
        d3d11_layout.setSpacing(6)
        placement_d3d11_host = NativeD3D11PreviewHostFrame(d3d11_page)
        placement_d3d11_host.setObjectName("PlacementNativeD3D11PreviewHost")
        placement_d3d11_host.setAttribute(Qt.WA_NativeWindow, True)
        placement_d3d11_host.setMinimumSize(QSize(520, 360))
        placement_d3d11_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        d3d11_layout.addWidget(placement_d3d11_host, 1)
        placement_d3d11_status = QLabel("Native D3D11 placement preview is available.")
        placement_d3d11_status.setObjectName("HintLabel")
        placement_d3d11_status.setWordWrap(True)
        d3d11_layout.addWidget(placement_d3d11_status)
        preview_stack.addWidget(d3d11_page)
        preview_stack.setCurrentWidget(d3d11_page)
        preview_layout.addWidget(preview_stack, 1)
        preview_button_row = QHBoxLayout()
        preview_button_row.addStretch(1)
        reload_d3d11_button = QPushButton("Reload D3D11 Preview")
        reload_d3d11_button.setEnabled(True)
        preview_button_row.addWidget(reload_d3d11_button)
        preview_layout.addLayout(preview_button_row)
        splitter.addWidget(preview_group)

        review_panel = QWidget()
        review_layout = QVBoxLayout(review_panel)
        review_layout.setContentsMargins(8, 0, 0, 0)
        review_layout.setSpacing(8)
        evidence_tree = QTreeWidget()
        evidence_tree.setColumnCount(4)
        evidence_tree.setHeaderLabels(["Value", "Current target", "Selected placement", "Meaning"])
        evidence_tree.setRootIsDecorated(True)
        evidence_tree.setAlternatingRowColors(True)
        evidence_tree.setUniformRowHeights(True)
        evidence_tree.header().setStretchLastSection(True)
        evidence_tree.header().resizeSection(0, 150)
        evidence_tree.header().resizeSection(1, 230)
        evidence_tree.header().resizeSection(2, 230)
        review_layout.addWidget(evidence_tree, 1)
        plan_tree = QTreeWidget()
        plan_tree.setColumnCount(4)
        plan_tree.setHeaderLabels(["Package action", "Source file", "Loose target path", "Notes"])
        plan_tree.setRootIsDecorated(False)
        plan_tree.setAlternatingRowColors(True)
        plan_tree.setUniformRowHeights(True)
        plan_tree.header().setStretchLastSection(True)
        plan_tree.header().resizeSection(0, 180)
        plan_tree.header().resizeSection(1, 260)
        plan_tree.header().resizeSection(2, 260)
        review_layout.addWidget(plan_tree, 1)
        splitter.addWidget(review_panel)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)
        splitter.setStretchFactor(2, 3)
        splitter.setSizes([330, 520, 430])
        d3d11_reload_timer = QTimer(dialog)
        d3d11_reload_timer.setSingleShot(True)
        d3d11_reload_timer.setInterval(420)
        d3d11_status_timer = QTimer(dialog)
        d3d11_status_timer.setInterval(250)
        d3d11_state: Dict[str, object] = {
            "request_id": 0,
            "model_thread": None,
            "model_worker": None,
            "package_thread": None,
            "package_worker": None,
            "process": None,
            "active_package": None,
            "status_file": None,
            "status_signature": (0, 0),
            "status_payload_text": "",
            "preview_loaded": False,
            "target_model": None,
            "donor_model": None,
            "body_model": None,
            "editable_indices": (),
            "pending": False,
            "closed": False,
        }

        def _visual_offset() -> Tuple[float, float, float]:
            return tuple(float(spin.value()) for spin in offset_spins)  # type: ignore[return-value]

        def _visual_rotation() -> Tuple[float, float, float]:
            return tuple(float(spin.value()) for spin in rotation_spins)  # type: ignore[return-value]

        def _candidate_base_context() -> Dict[str, object]:
            donor_context = context_state.get("donor", {})
            return donor_context if donor_context else context_state.get("target", {})

        def _candidate_base_evidence() -> Optional[AttachmentPlacementEvidence]:
            return donor_evidence or target_evidence

        def _selected_candidate_socket() -> str:
            return str(candidate_combo.currentData() or "").strip()

        def _placement_preview_style() -> str:
            value = str(preview_style_combo.currentData() or "schematic").strip().casefold()
            if value == "mesh" and isinstance(target_model_entry, ArchiveEntry):
                return "mesh"
            return "schematic"

        def _candidate_context() -> Dict[str, object]:
            base_context = _candidate_base_context()
            socket_override = _selected_candidate_socket()
            if socket_override:
                return self._attachment_visual_context_for_character_socket(base_context, socket_override)
            return dict(base_context or {})

        def _candidate_evidence() -> Optional[AttachmentPlacementEvidence]:
            base_evidence = _candidate_base_evidence()
            socket_override = _selected_candidate_socket()
            if socket_override:
                return self._attachment_visual_evidence_for_character_socket(base_evidence, _candidate_base_context(), socket_override)
            return base_evidence

        def _format_value(value: object) -> str:
            if isinstance(value, (tuple, list)):
                try:
                    return self._format_attachment_transform(tuple(float(component) for component in value))
                except (TypeError, ValueError, OverflowError):
                    return " ".join(str(component) for component in value)
            return str(value or "")

        def _placement_d3d11_theme_payload() -> Dict[str, str]:
            return {
                "background": MODEL_PREVIEW_BACKGROUND_COLOR,
                "text": MODEL_PREVIEW_TEXT_COLOR,
            }

        def _placement_d3d11_cleanup_package(package_dir: object, *, delay_ms: int = 0) -> None:
            if package_dir is None:
                return
            try:
                package_path = Path(package_dir)
            except TypeError:
                return

            def _remove() -> None:
                try:
                    shutil.rmtree(package_path, ignore_errors=True)
                except OSError:
                    pass

            if delay_ms > 0:
                QTimer.singleShot(int(delay_ms), _remove)
            else:
                _remove()

        def _placement_d3d11_active() -> bool:
            return bool(placement_d3d11_available and not bool(d3d11_state.get("closed")))

        def _placement_d3d11_hard_error(message: str) -> None:
            detail = str(message or "Native D3D11 placement preview failed.").strip()
            if "No fallback preview renderer is available." not in detail:
                detail = f"{detail} No fallback preview renderer is available."
            placement_d3d11_status.setText(detail)
            self.set_status_message(detail, error=True)

        def _placement_d3d11_stop_worker() -> None:
            package_worker = d3d11_state.get("package_worker")
            if isinstance(package_worker, AlignmentD3D11PackageWorker):
                package_worker.stop()

        def _placement_d3d11_stop_process() -> None:
            process = d3d11_state.get("process")
            package_dir = d3d11_state.get("active_package")
            d3d11_state["process"] = None
            d3d11_state["active_package"] = None
            d3d11_state["status_file"] = None
            d3d11_state["status_signature"] = (0, 0)
            d3d11_state["status_payload_text"] = ""
            d3d11_state["preview_loaded"] = False
            d3d11_status_timer.stop()
            if not isinstance(process, QProcess):
                _placement_d3d11_cleanup_package(package_dir)
                return
            try:
                process.disconnect()
            except (RuntimeError, TypeError):
                pass
            try:
                if process.state() != QProcess.NotRunning:
                    process.terminate()
                    QTimer.singleShot(1200, lambda process=process: self._kill_archive_isolated_renderer_process_if_running(process))
                    _placement_d3d11_cleanup_package(package_dir, delay_ms=5000)
                else:
                    _placement_d3d11_cleanup_package(package_dir)
                process.deleteLater()
            except RuntimeError:
                _placement_d3d11_cleanup_package(package_dir)

        def _shutdown_placement_d3d11_preview() -> None:
            d3d11_state["closed"] = True
            d3d11_reload_timer.stop()
            d3d11_status_timer.stop()
            d3d11_state["request_id"] = int(d3d11_state.get("request_id", 0) or 0) + 1
            _placement_d3d11_stop_worker()
            _placement_d3d11_stop_process()
            active_package = d3d11_state.get("active_package")
            _placement_d3d11_cleanup_package(active_package)

        def _placement_d3d11_sync_fast_transform() -> None:
            if not _placement_d3d11_active():
                return
            placement_d3d11_host.set_alignment_preview_transform(
                translation=_visual_offset(),
                rotation_degrees=_visual_rotation(),
                scale_xyz=(1.0, 1.0, 1.0),
            )

        def _placement_d3d11_build_preview_model() -> Tuple[Optional[ModelPreviewData], Tuple[int, ...]]:
            if _placement_preview_style() == "schematic":
                return self._build_attachment_placement_schematic_preview_model(
                    target_evidence=target_evidence,
                    donor_evidence=_candidate_evidence(),
                    target_context=context_state.get("target", {}),
                    donor_context=_candidate_context(),
                    visual_offset=(0.0, 0.0, 0.0),
                    visual_rotation_degrees=(0.0, 0.0, 0.0),
                )
            target_model = d3d11_state.get("target_model")
            if not isinstance(target_model, ModelPreviewData):
                return None, ()
            donor_model = d3d11_state.get("donor_model")
            preview_model, editable_indices = self._build_attachment_visual_preview_model(
                target_model,
                donor_model if isinstance(donor_model, ModelPreviewData) else None,
                body_model=None,
                target_evidence=target_evidence,
                donor_evidence=_candidate_evidence(),
                target_context=context_state.get("target", {}),
                donor_context=_candidate_context(),
                visual_offset=(0.0, 0.0, 0.0),
                visual_rotation_degrees=(0.0, 0.0, 0.0),
                mode="target_with_donor",
            )
            return preview_model if isinstance(preview_model, ModelPreviewData) else None, tuple(int(index) for index in editable_indices)

        def _placement_d3d11_start_process(package_dir: Path) -> None:
            status_file = package_dir / "host_status.json"
            try:
                status_file.unlink(missing_ok=True)
            except OSError:
                pass
            existing_process = d3d11_state.get("process")
            if isinstance(existing_process, QProcess) and existing_process.state() != QProcess.NotRunning:
                previous_package = d3d11_state.get("active_package")
                d3d11_state["active_package"] = package_dir
                d3d11_state["status_file"] = status_file
                d3d11_state["status_signature"] = (0, 0)
                d3d11_state["status_payload_text"] = ""
                d3d11_state["preview_loaded"] = False
                if placement_d3d11_host.load_package(package_dir, status_file, reset_view=False):
                    placement_d3d11_host.set_display_mode("overlay")
                    placement_d3d11_host.set_render_tuning(self._current_model_preview_render_settings())
                    _placement_d3d11_cleanup_package(previous_package, delay_ms=5000)
                    d3d11_status_timer.start()
                    placement_d3d11_status.setText("Reloading native D3D11 placement preview...")
                    return
                d3d11_state["active_package"] = previous_package
            _placement_d3d11_stop_process()
            d3d11_state["active_package"] = package_dir
            d3d11_state["status_file"] = status_file
            d3d11_state["status_signature"] = (0, 0)
            d3d11_state["status_payload_text"] = ""
            d3d11_state["preview_loaded"] = False
            process = QProcess(dialog)
            try:
                program, arguments = self._native_d3d11_renderer_command(
                    package_dir,
                    status_file,
                    host_widget=placement_d3d11_host,
                    theme_payload=_placement_d3d11_theme_payload(),
                )
            except Exception as exc:
                _placement_d3d11_hard_error(f"Native D3D11 unavailable: {exc}")
                _placement_d3d11_cleanup_package(package_dir)
                return
            process.setProgram(program)
            process.setArguments(arguments)
            try:
                process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
            except Exception:
                pass
            process.setProcessChannelMode(QProcess.SeparateChannels)
            process.readyReadStandardError.connect(
                lambda process=process: placement_d3d11_status.setText(
                    "Native D3D11 stderr: "
                    + bytes(process.readAllStandardError()).decode("utf-8", errors="replace").strip()[-300:]
                )
                if process is d3d11_state.get("process")
                else None
            )
            process.finished.connect(lambda exit_code, exit_status, process=process: _handle_placement_d3d11_finished(process, exit_code, exit_status))
            process.errorOccurred.connect(lambda error, process=process: placement_d3d11_status.setText(f"Native D3D11 process error: {error}") if process is d3d11_state.get("process") else None)
            d3d11_state["process"] = process
            preview_stack.setCurrentWidget(d3d11_page)
            placement_d3d11_status.setText("Starting native D3D11 placement preview...")
            d3d11_status_timer.start()
            process.start()

        def _handle_placement_d3d11_finished(process: QProcess, exit_code: int, exit_status: object) -> None:
            if process is not d3d11_state.get("process"):
                return
            _poll_placement_d3d11_status()
            d3d11_state["process"] = None
            d3d11_status_timer.stop()
            package_dir = d3d11_state.get("active_package")
            d3d11_state["active_package"] = None
            d3d11_state["status_file"] = None
            _placement_d3d11_cleanup_package(package_dir)
            if int(exit_code) != 0:
                _placement_d3d11_hard_error(f"Native D3D11 exited with code {int(exit_code)} ({exit_status}).")

        def _poll_placement_d3d11_status() -> None:
            status_file = d3d11_state.get("status_file")
            if not isinstance(status_file, Path):
                return
            try:
                stat = status_file.stat()
            except OSError:
                if bool(d3d11_state.get("preview_loaded")):
                    placement_d3d11_status.setText("Native D3D11 placement preview loaded.")
                return
            signature = _d3d11_status_file_signature(stat)
            try:
                payload_text = status_file.read_text(encoding="utf-8")
            except Exception as exc:
                placement_d3d11_status.setText(f"Native D3D11 status read failed: {exc}")
                return
            if (
                signature == d3d11_state.get("status_signature", (0, 0))
                and payload_text == str(d3d11_state.get("status_payload_text", "") or "")
            ):
                if bool(d3d11_state.get("preview_loaded")) and "Loading" in placement_d3d11_status.text():
                    placement_d3d11_status.setText("Native D3D11 placement preview loaded.")
                return
            d3d11_state["status_signature"] = signature
            d3d11_state["status_payload_text"] = payload_text
            try:
                payload = json.loads(payload_text)
            except Exception as exc:
                placement_d3d11_status.setText(f"Native D3D11 status read failed: {exc}")
                return
            if not isinstance(payload, Mapping):
                return
            event = str(payload.get("event", "") or "").strip().lower()
            if event == "loaded":
                d3d11_state["preview_loaded"] = True
                editable_indices = tuple(int(index) for index in tuple(d3d11_state.get("editable_indices", ()) or ()))
                placement_d3d11_host.set_display_mode("overlay")
                placement_d3d11_host.set_render_tuning(self._current_model_preview_render_settings())
                placement_d3d11_host.set_alignment_state(
                    enabled=True,
                    source_submesh_indices=editable_indices,
                    translation_sensitivity=0.0015,
                    rotation_degrees_per_pixel=0.35,
                )
                _placement_d3d11_sync_fast_transform()
                placement_d3d11_status.setText("Native D3D11 placement preview loaded. Drag selected placement mesh to adjust offset; use rotation drag for rotation.")
            elif event == "loading":
                if bool(d3d11_state.get("preview_loaded")):
                    placement_d3d11_status.setToolTip(str(payload.get("message", "") or "Loading native D3D11 placement preview..."))
                    return
                placement_d3d11_status.setText(str(payload.get("message", "") or "Loading native D3D11 placement preview..."))
            elif event == "error":
                d3d11_state["preview_loaded"] = False
                _placement_d3d11_hard_error(str(payload.get("message", "") or "Native D3D11 placement renderer error."))

        def _handle_placement_d3d11_package_ready(request_id: int, package_dir_object: object, prepare_ms: float, package_ms: float) -> None:
            try:
                package_dir = Path(package_dir_object)
            except TypeError:
                return
            if int(request_id) != int(d3d11_state.get("request_id", 0) or 0):
                _placement_d3d11_cleanup_package(package_dir)
                return
            placement_d3d11_status.setText(f"Native D3D11 package ready: prepare {prepare_ms:.0f} ms, package {package_ms:.0f} ms.")
            _placement_d3d11_start_process(package_dir)

        def _handle_placement_d3d11_package_error(request_id: int, message: str) -> None:
            if int(request_id) != int(d3d11_state.get("request_id", 0) or 0):
                return
            _placement_d3d11_hard_error(f"Native D3D11 package failed: {message}")

        def _cleanup_placement_d3d11_package_refs() -> None:
            d3d11_state["package_thread"] = None
            d3d11_state["package_worker"] = None
            if bool(d3d11_state.get("pending")) and _placement_d3d11_active():
                d3d11_state["pending"] = False
                QTimer.singleShot(0, _queue_placement_d3d11_preview)

        def _start_placement_d3d11_package_worker(model: ModelPreviewData, editable_indices: Sequence[int]) -> None:
            if not _placement_d3d11_active():
                return
            if isinstance(d3d11_state.get("package_thread"), QThread):
                d3d11_state["request_id"] = int(d3d11_state.get("request_id", 0) or 0) + 1
                d3d11_state["pending"] = True
                _placement_d3d11_stop_worker()
                placement_d3d11_status.setText("Queued latest native D3D11 placement preview...")
                return
            d3d11_state["request_id"] = int(d3d11_state.get("request_id", 0) or 0) + 1
            request_id = int(d3d11_state["request_id"])
            d3d11_state["editable_indices"] = tuple(int(index) for index in tuple(editable_indices or ()))
            settings = dataclasses.replace(self._current_model_preview_render_settings())
            settings.disable_all_support_maps = True
            settings.disable_normal_map = True
            settings.disable_material_map = True
            settings.disable_height_map = True
            worker = AlignmentD3D11PackageWorker(
                request_id,
                model,
                clamp_model_preview_render_settings(settings),
                use_textures=False,
                high_quality_textures=False,
                enable_material_combiner=False,
                original_reference_material_parity=False,
                display_mode="overlay",
                editor_workspace="placement_visual",
            )
            thread = QThread(dialog)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.completed.connect(_handle_placement_d3d11_package_ready)
            worker.error.connect(_handle_placement_d3d11_package_error)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(_cleanup_placement_d3d11_package_refs)
            d3d11_state["package_worker"] = worker
            d3d11_state["package_thread"] = thread
            placement_d3d11_status.setText("Preparing native D3D11 placement preview package...")
            thread.start()

        def _start_placement_d3d11_model_load() -> None:
            if not _placement_d3d11_active():
                return
            if isinstance(d3d11_state.get("model_thread"), QThread):
                d3d11_state["pending"] = True
                return
            d3d11_state["request_id"] = int(d3d11_state.get("request_id", 0) or 0) + 1
            request_id = int(d3d11_state["request_id"])
            preview_settings_snapshot = self._current_model_preview_render_settings()
            texture_entries_by_normalized_path_snapshot = self.archive_entries_by_normalized_path
            texture_entries_by_basename_snapshot = self.archive_entries_by_basename
            sidecar_entries_by_texture_path_snapshot = self.archive_sidecar_entries_by_texture_path
            sidecar_entries_by_texture_basename_snapshot = self.archive_sidecar_entries_by_texture_basename

            def _task() -> dict:
                target_preview = build_archive_preview_result(
                    target_model_entry,
                    texture_entries_by_normalized_path=texture_entries_by_normalized_path_snapshot,
                    texture_entries_by_basename=texture_entries_by_basename_snapshot,
                    sidecar_entries_by_texture_path=sidecar_entries_by_texture_path_snapshot,
                    sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename_snapshot,
                    visible_texture_mode=preview_settings_snapshot.visible_texture_mode,
                )
                donor_preview = None
                if isinstance(donor_model_entry, ArchiveEntry):
                    donor_preview = build_archive_preview_result(
                        donor_model_entry,
                        texture_entries_by_normalized_path=texture_entries_by_normalized_path_snapshot,
                        texture_entries_by_basename=texture_entries_by_basename_snapshot,
                        sidecar_entries_by_texture_path=sidecar_entries_by_texture_path_snapshot,
                        sidecar_entries_by_texture_basename=sidecar_entries_by_texture_basename_snapshot,
                        visible_texture_mode=preview_settings_snapshot.visible_texture_mode,
                    )
                return {"target": target_preview, "donor": donor_preview}

            worker = VisualPlacementPreviewWorker(request_id, _task)
            thread = QThread(dialog)
            worker.moveToThread(thread)
            thread.started.connect(worker.run)
            worker.completed.connect(_handle_placement_d3d11_models_loaded)
            worker.error.connect(_handle_placement_d3d11_models_error)
            worker.finished.connect(thread.quit)
            worker.finished.connect(worker.deleteLater)
            thread.finished.connect(thread.deleteLater)
            thread.finished.connect(_cleanup_placement_d3d11_model_refs)
            d3d11_state["model_worker"] = worker
            d3d11_state["model_thread"] = thread
            placement_d3d11_status.setText("Loading target/source models for native D3D11 placement preview...")
            thread.start()

        def _handle_placement_d3d11_models_loaded(request_id: int, payload: object) -> None:
            if int(request_id) != int(d3d11_state.get("request_id", 0) or 0):
                return
            if not isinstance(payload, Mapping) or not isinstance(payload.get("target"), ArchivePreviewResult):
                placement_d3d11_status.setText("Native D3D11 placement model load returned an unexpected payload.")
                return
            target_preview = payload.get("target")
            donor_preview = payload.get("donor") if isinstance(payload.get("donor"), ArchivePreviewResult) else None
            target_model = getattr(target_preview, "preview_model", None)
            donor_model = getattr(donor_preview, "preview_model", None) if donor_preview is not None else None
            if not isinstance(target_model, ModelPreviewData):
                placement_d3d11_status.setText("Native D3D11 placement preview has no renderable target model.")
                return
            self._attach_archive_model_preview_images(target_model)
            if isinstance(donor_model, ModelPreviewData):
                self._attach_archive_model_preview_images(donor_model)
            d3d11_state["target_model"] = target_model
            d3d11_state["donor_model"] = donor_model
            _queue_placement_d3d11_preview()

        def _handle_placement_d3d11_models_error(request_id: int, message: str) -> None:
            if int(request_id) != int(d3d11_state.get("request_id", 0) or 0):
                return
            _placement_d3d11_hard_error(f"Native D3D11 placement model load failed: {message}")

        def _cleanup_placement_d3d11_model_refs() -> None:
            d3d11_state["model_thread"] = None
            d3d11_state["model_worker"] = None
            if bool(d3d11_state.get("pending")) and _placement_d3d11_active():
                d3d11_state["pending"] = False
                QTimer.singleShot(0, _queue_placement_d3d11_preview)

        def _queue_placement_d3d11_preview() -> None:
            if not _placement_d3d11_active():
                return
            if _placement_preview_style() == "mesh" and not isinstance(d3d11_state.get("target_model"), ModelPreviewData):
                _start_placement_d3d11_model_load()
                return
            preview_model, editable_indices = _placement_d3d11_build_preview_model()
            if not isinstance(preview_model, ModelPreviewData):
                placement_d3d11_status.setText("Native D3D11 placement preview could not build a renderable model.")
                return
            _start_placement_d3d11_package_worker(preview_model, editable_indices)

        def _queue_placement_d3d11_preview_debounced() -> None:
            if _placement_d3d11_active():
                d3d11_reload_timer.start()

        def _socket_parent(context: Mapping[str, object], evidence: Optional[AttachmentPlacementEvidence]) -> str:
            socket = context.get("character_socket_info")
            if isinstance(socket, AttachmentSocketInfo):
                return str(socket.parent or "")
            return str(getattr(evidence, "character_socket_parent", "") if isinstance(evidence, AttachmentPlacementEvidence) else "")

        def _socket_translation(context: Mapping[str, object], evidence: Optional[AttachmentPlacementEvidence]) -> str:
            socket = context.get("character_socket_info")
            value = socket.translation if isinstance(socket, AttachmentSocketInfo) else getattr(evidence, "character_socket_translation", ())
            return _format_value(value) or "-"

        def _pivot_name(context: Mapping[str, object], evidence: Optional[AttachmentPlacementEvidence]) -> str:
            socket = context.get("weapon_socket_info")
            if isinstance(socket, AttachmentSocketInfo):
                return str(socket.name or "")
            return str(getattr(evidence, "weapon_socket_name", "") if isinstance(evidence, AttachmentPlacementEvidence) else "")

        def _populate_candidates() -> None:
            previous = _selected_candidate_socket()
            candidate_combo.blockSignals(True)
            try:
                candidate_combo.clear()
                candidate_combo.addItem("Keep recovered source placement", "")
                for label, socket_candidate in self._attachment_visual_character_socket_choices(_candidate_base_context()):
                    candidate_combo.addItem(label, socket_candidate)
                if previous:
                    index = candidate_combo.findData(previous)
                    if index >= 0:
                        candidate_combo.setCurrentIndex(index)
            finally:
                candidate_combo.blockSignals(False)
            candidate_tree.clear()
            rows: List[Tuple[str, str, str, str, str, str]] = []
            base_context = _candidate_base_context()
            base_evidence = _candidate_base_evidence()
            rows.append(
                (
                    "Keep recovered source placement",
                    "",
                    str(getattr(base_evidence, "character_socket_name", "") or "-"),
                    str(getattr(base_evidence, "weapon_socket_name", "") or "-"),
                    _socket_parent(base_context, base_evidence) or "-",
                    _socket_translation(base_context, base_evidence),
                )
            )
            for label, socket_candidate in self._attachment_visual_character_socket_choices(base_context):
                candidate_context = self._attachment_visual_context_for_character_socket(base_context, socket_candidate)
                candidate_evidence = self._attachment_visual_evidence_for_character_socket(base_evidence, base_context, socket_candidate)
                rows.append(
                    (
                        label,
                        socket_candidate,
                        socket_candidate,
                        _pivot_name(candidate_context, candidate_evidence) or str(getattr(candidate_evidence, "weapon_socket_name", "") or "-"),
                        _socket_parent(candidate_context, candidate_evidence) or "-",
                        _socket_translation(candidate_context, candidate_evidence),
                    )
                )
            for label, socket_data, attach_name, pivot, parent_name, translation in rows:
                item = QTreeWidgetItem([attach_name, pivot, parent_name, translation, label])
                item.setData(0, Qt.UserRole, socket_data)
                for column, text in enumerate((attach_name, pivot, parent_name, translation, label)):
                    item.setToolTip(column, text)
                candidate_tree.addTopLevelItem(item)
                if socket_data == previous:
                    candidate_tree.setCurrentItem(item)
            if candidate_tree.currentItem() is None and candidate_tree.topLevelItemCount() > 0:
                candidate_tree.setCurrentItem(candidate_tree.topLevelItem(0))
            expand_tree_columns_to_available_width(candidate_tree)

        def _refresh_evidence() -> None:
            target_context = context_state.get("target", {})
            candidate_context = _candidate_context()
            candidate = _candidate_evidence()
            evidence_tree.clear()
            rows = (
                ("Character socket", getattr(target_evidence, "character_socket_name", ""), getattr(candidate, "character_socket_name", ""), "Character-side attach point"),
                ("Character parent", _socket_parent(target_context, target_evidence), _socket_parent(candidate_context, candidate), "Socket parent/bone"),
                ("Character translation", _socket_translation(target_context, target_evidence), _socket_translation(candidate_context, candidate), "Character socket transform"),
                ("Weapon pivot", getattr(target_evidence, "weapon_socket_name", ""), getattr(candidate, "weapon_socket_name", ""), "Weapon-side pivot socket"),
                ("Weapon parent", getattr(target_evidence, "weapon_socket_parent", ""), getattr(candidate, "weapon_socket_parent", ""), "Weapon pivot parent"),
                ("Weapon translation", _format_value(getattr(target_evidence, "weapon_socket_translation", ())), _format_value(getattr(candidate, "weapon_socket_translation", ())), "Weapon pivot transform"),
                ("Prefab", getattr(target_evidence, "prefab_path", ""), getattr(candidate, "prefab_path", ""), "Prefab placement fields"),
                ("Socket XML", getattr(target_evidence, "socket_file_path", ""), getattr(candidate, "socket_file_path", ""), "Weapon socket descriptor"),
                ("Skeleton", str(target_context.get("skeleton_source_path", "") or ""), str(candidate_context.get("skeleton_source_path", "") or ""), "PAB skeleton context"),
            )
            for label, target_value, candidate_value, meaning in rows:
                item = QTreeWidgetItem([label, str(target_value or "-"), str(candidate_value or "-"), meaning])
                for column in range(4):
                    item.setToolTip(column, item.text(column))
                evidence_tree.addTopLevelItem(item)
            expand_tree_columns_to_available_width(evidence_tree)

        def _refresh_plan_tree() -> None:
            plan_tree.clear()
            for row in tuple(package_plan_rows or ()):
                donor = row.get("donor_entry")
                target = row.get("target_entry")
                donor_path = donor.path if isinstance(donor, ArchiveEntry) else "-"
                target_path = target.path if isinstance(target, ArchiveEntry) else "-"
                item = QTreeWidgetItem(
                    [
                        str(row.get("action") or "-"),
                        donor_path,
                        target_path,
                        str(row.get("note") or ""),
                    ]
                )
                for column in range(4):
                    item.setToolTip(column, item.text(column))
                plan_tree.addTopLevelItem(item)
            selected_socket = _selected_candidate_socket()
            if selected_socket:
                plan_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        [
                            "Patch copied prefab socket names",
                            "selected placement",
                            "copied target prefab rows",
                            f"Attach point {selected_socket}; same-length prefab name patch only.",
                        ]
                    )
                )
            selected_socket_name = str(getattr(_candidate_evidence(), "weapon_socket_name", "") or socket_name)
            has_manual_adjustment = any(abs(float(value)) > 1e-9 for value in (*_visual_offset(), *_visual_rotation()))
            if isinstance(socket_entry, ArchiveEntry) and selected_socket_name and has_manual_adjustment:
                plan_tree.addTopLevelItem(
                    QTreeWidgetItem(
                        [
                            "Numeric socket adjustment",
                            socket_entry.path,
                            socket_entry.path,
                            f"Pivot socket {selected_socket_name}; offset/rotation is non-zero.",
                        ]
                    )
                )
            if plan_tree.topLevelItemCount() <= 0:
                plan_tree.addTopLevelItem(QTreeWidgetItem(["No safe package rows", "-", "-", "No source-copy or socket XML path resolved."]))
            expand_tree_columns_to_available_width(plan_tree)

        def _refresh_status() -> None:
            candidate = _candidate_evidence()
            candidate_context = _candidate_context()
            selected_socket_name = str(getattr(candidate, "weapon_socket_name", "") or socket_name)
            socket_note.setText(
                f"Target: {target_entry.path}\n"
                f"Source: {donor_entry.path if isinstance(donor_entry, ArchiveEntry) else 'none'}\n"
                f"Editable socket XML: {socket_entry.path if isinstance(socket_entry, ArchiveEntry) else 'not resolved'}\n"
                f"Pivot socket: {selected_socket_name or 'not resolved'}"
            )
            context_summary = str(candidate_context.get("placement_source_summary", "") or "socket-name proxy fallback")
            placement_d3d11_status.setToolTip(
                f"Selected attach point: {getattr(candidate, 'character_socket_name', '') or 'source default'} | "
                f"pivot: {selected_socket_name or '-'} | "
                f"context: {context_summary}"
            )
            has_manual_adjustment = any(abs(float(value)) > 1e-9 for value in (*_visual_offset(), *_visual_rotation()))
            build_button.setEnabled(bool(package_plan_rows) or (isinstance(socket_entry, ArchiveEntry) and has_manual_adjustment))
            _placement_d3d11_sync_fast_transform()
            _refresh_evidence()
            _refresh_plan_tree()

        def _set_candidate_from_tree(item: Optional[QTreeWidgetItem]) -> None:
            if item is None:
                return
            socket_value = str(item.data(0, Qt.UserRole) or "")
            index = candidate_combo.findData(socket_value)
            if index >= 0 and candidate_combo.currentIndex() != index:
                candidate_combo.setCurrentIndex(index)

        def _import_socket_evidence_root() -> None:
            selected_dir = QFileDialog.getExistingDirectory(
                dialog,
                "Choose Socket Evidence Folder",
                str(Path.home() / "Desktop"),
            )
            if not selected_dir:
                return
            extra_socket_roots.append(Path(selected_dir))
            request = dataclasses.replace(
                context_request,
                extra_roots=tuple(extra_socket_roots),
                request_id=0,
            )

            def _context_ready(result: object) -> None:
                if not isinstance(result, AttachmentContextResult):
                    return
                context_state["target"] = dict(result.target)
                context_state["donor"] = dict(result.donor)
                _populate_candidates()
                _refresh_status()
                _queue_placement_d3d11_preview_debounced()

            started = context_task_controller.start(
                request,
                _run_context_request,
                status_message=f"Resolving socket evidence from {Path(selected_dir).name}...",
                on_complete=_context_ready,
                on_error=lambda message: QMessageBox.warning(dialog, "Socket Evidence", message),
                on_idle=lambda: evidence_root_button.setEnabled(True),
            )
            if started:
                evidence_root_button.setEnabled(False)

        def _reset_adjustment() -> None:
            for spin in offset_spins + rotation_spins:
                spin.blockSignals(True)
                spin.setValue(0.0)
                spin.blockSignals(False)
            _refresh_status()
            _placement_d3d11_sync_fast_transform()

        def _commit_d3d11_translation(dx: float, dy: float, dz: float) -> None:
            for spin, delta in zip(offset_spins, (dx, dy, dz)):
                spin.blockSignals(True)
                spin.setValue(float(spin.value()) + float(delta))
                spin.blockSignals(False)
            _refresh_status()
            _placement_d3d11_sync_fast_transform()

        def _commit_d3d11_rotation(dx: float, dy: float, dz: float) -> None:
            for spin, delta in zip(rotation_spins, (dx, dy, dz)):
                spin.blockSignals(True)
                spin.setValue(float(spin.value()) + float(delta))
                spin.blockSignals(False)
            _refresh_status()
            _placement_d3d11_sync_fast_transform()

        def _build_safe_package() -> None:
            has_manual_adjustment = any(abs(float(value)) > 1e-9 for value in (*_visual_offset(), *_visual_rotation()))
            if not package_plan_rows and not (isinstance(socket_entry, ArchiveEntry) and has_manual_adjustment):
                QMessageBox.warning(
                    dialog,
                    "Build Safe Placement Package",
                    "No source-copy rows were resolved. Add a numeric adjustment if you only want to write socket XML.",
                )
                return
            target_settings = self._collect_archive_mod_ready_export_target(
                browse_title="Choose Safe Placement Package Export Root",
                prompt_for_metadata=True,
                dialog_title="Build Safe Placement Package",
                allow_dmm_texture_structure=False,
            )
            if target_settings is None:
                return
            export_root, package_info, create_no_encrypt_file, _include_related, export_options = target_settings
            selected_evidence = _candidate_evidence()
            selected_socket_name = str(getattr(selected_evidence, "weapon_socket_name", "") or socket_name)
            edited_socket_spec = (
                (
                    socket_entry,
                    selected_socket_name,
                    tuple(_visual_offset()),
                    tuple(_visual_rotation()),
                    self._attachment_visual_context_transform_scale(_candidate_context()),
                )
                if isinstance(socket_entry, ArchiveEntry) and selected_socket_name and has_manual_adjustment
                else None
            )
            plan_snapshot = tuple(dict(row) for row in package_plan_rows)
            diagnostics = [
                f"Target: {target_entry.path}",
                f"Placement source: {donor_entry.path if isinstance(donor_entry, ArchiveEntry) else 'none'}",
                f"Safe editor: D3D11-only socket selection.",
                f"Selected attach point: {getattr(selected_evidence, 'character_socket_name', '') or 'source default'}",
                f"Selected pivot socket: {selected_socket_name or '-'}",
                f"Manual offset: {_format_value(_visual_offset())}",
                f"Manual rotation degrees: {_format_value(_visual_rotation())}",
            ]
            package_info = self._placement_swap_package_info_with_diagnostics(package_info, diagnostics)

            def _task(log: Callable[[str], None]) -> ArchiveLooseExportResult:
                edited_socket_payload = None
                if isinstance(edited_socket_spec, tuple):
                    edited_socket_payload = self._attachment_visual_edited_socket_payload(
                        edited_socket_spec[0],
                        edited_socket_spec[1],
                        visual_offset=edited_socket_spec[2],
                        visual_rotation_degrees=edited_socket_spec[3],
                        translation_scale=edited_socket_spec[4],
                    )
                requests_by_path: Dict[str, ArchivePatchRequest] = {}
                for row in plan_snapshot:
                    donor = row.get("donor_entry")
                    target = row.get("target_entry")
                    if not isinstance(donor, ArchiveEntry) or not isinstance(target, ArchiveEntry):
                        continue
                    payload_data, _decompressed, _note = read_archive_entry_data(donor)
                    if (
                        str(target.extension or "").lower() == ".prefab"
                        and isinstance(selected_evidence, AttachmentPlacementEvidence)
                        and selected_evidence.character_socket_name
                        and selected_evidence.weapon_socket_name
                    ):
                        prefab_patch = build_prefab_socket_name_patch(
                            payload_data,
                            attached_socket_name=selected_evidence.character_socket_name,
                            pivot_socket_name=selected_evidence.weapon_socket_name,
                        )
                        payload_data = prefab_patch.data
                        for proof_line in prefab_patch.proof_lines:
                            log(f"Prefab socket proof: {proof_line}")
                    target_key = target.path.replace("\\", "/").strip().casefold()
                    requests_by_path[target_key] = ArchivePatchRequest(target, payload_data)
                    log(f"Copy placement source bytes: {donor.path} -> {target.path}")
                if isinstance(socket_entry, ArchiveEntry) and isinstance(edited_socket_payload, bytes):
                    target_key = socket_entry.path.replace("\\", "/").strip().casefold()
                    requests_by_path[target_key] = ArchivePatchRequest(socket_entry, edited_socket_payload)
                    log(f"Write numeric socket adjustment: {socket_entry.path} [{selected_socket_name}]")
                if not requests_by_path:
                    raise ValueError("No placement package payloads could be built.")
                return export_archive_payloads_to_mod_ready_loose(
                    tuple(requests_by_path.values()),
                    parent_root=export_root,
                    package_info=package_info,
                    export_options=export_options,
                    create_no_encrypt_file=create_no_encrypt_file,
                    on_log=log,
                )

            def _handle_complete(result: object) -> None:
                if isinstance(result, ArchiveLooseExportResult):
                    QMessageBox.information(
                        dialog,
                        "Safe Placement Package Complete",
                        f"Wrote safe placement loose package:\n{result.package_root}",
                    )
                    self.set_status_message(f"Wrote safe placement package for {target_entry.basename}.")
                    dialog.accept()
                else:
                    self.set_status_message("Safe placement package export finished with an unexpected result payload.", error=True)

            self._run_utility_task(
                status_message=f"Building safe placement package for {target_entry.basename}...",
                task=_task,
                on_complete=_handle_complete,
                show_archive_progress=True,
            )

        button_row = QHBoxLayout()
        button_row.addStretch(1)
        build_button = QPushButton("Build Safe Placement Package...")
        build_button.setEnabled(bool(package_plan_rows))
        close_button = QPushButton("Close")
        button_row.addWidget(build_button)
        button_row.addWidget(close_button)
        layout.addLayout(button_row)

        candidate_tree.currentItemChanged.connect(lambda current, _previous: _set_candidate_from_tree(current))
        candidate_combo.currentIndexChanged.connect(lambda _index=0: (_refresh_status(), _queue_placement_d3d11_preview_debounced()))
        preview_style_combo.currentIndexChanged.connect(lambda _index=0: (_refresh_status(), _queue_placement_d3d11_preview_debounced()))
        for spin in offset_spins + rotation_spins:
            spin.valueChanged.connect(lambda _value=0.0: (_refresh_status(), _placement_d3d11_sync_fast_transform()))
        evidence_root_button.clicked.connect(lambda _checked=False: _import_socket_evidence_root())
        reset_button.clicked.connect(lambda _checked=False: _reset_adjustment())
        reload_d3d11_button.clicked.connect(lambda _checked=False: _queue_placement_d3d11_preview())
        d3d11_reload_timer.timeout.connect(_queue_placement_d3d11_preview)
        d3d11_status_timer.timeout.connect(_poll_placement_d3d11_status)
        placement_d3d11_host.alignment_drag_finished.connect(_commit_d3d11_translation)
        placement_d3d11_host.alignment_rotation_finished.connect(_commit_d3d11_rotation)
        build_button.clicked.connect(lambda _checked=False: _build_safe_package())
        close_button.clicked.connect(dialog.accept)
        dialog.finished.connect(lambda _result=0: _shutdown_placement_d3d11_preview())
        _populate_candidates()
        _refresh_status()
        if placement_d3d11_available:
            QTimer.singleShot(0, _queue_placement_d3d11_preview)
        dialog.exec()


__all__ = ["ArchiveAttachmentSafePlacementDialogMixin"]
