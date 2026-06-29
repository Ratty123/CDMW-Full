from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QPoint, QProcess, QSettings, QThread, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.mesh import MeshEditSelection, MeshEditSessionView
from cdmw.models import ModelPreviewData, ModelPreviewRenderSettings, TextureEditorSourceBinding
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.mesh_editor.action_bar import MeshEditorActionBar
from cdmw.ui.mesh_editor.controller import (
    MeshEditorController,
    MeshEditorNativeUpdate,
    apply_native_update_to_host,
)
from cdmw.ui.mesh_editor.native_preview_runtime import (
    mesh_editor_native_preview_data,
    mesh_editor_native_preview_command,
    mesh_editor_write_native_preview_package,
)
from cdmw.ui.mesh_editor.session import MeshEditorSessionRequest, mesh_editor_source_skeleton
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from cdmw.workers.mesh_editor_workers import MeshFileSessionLoadWorker, MeshNativePreviewPackageWorker, MeshTextureSourceResolveWorker

try:  # pragma: no cover - import guard keeps source tests light.
    from cdmw.models import ArchiveEntry
except Exception:  # pragma: no cover
    ArchiveEntry = object  # type: ignore[assignment]

try:  # pragma: no cover
    from cdmw.modding.scene_importer import SceneImportResult
except Exception:  # pragma: no cover
    SceneImportResult = object  # type: ignore[assignment]


class MeshEditorTab(QWidget):
    """Main mesh replacement/editing workspace host.

    The full Mesh Replacement Builder is mounted here for active sessions so the
    D3D11 preview, tabs, build preflight, and archive safety gates stay shared.
    """

    status_message_requested = Signal(str, bool)
    modify_original_requested = Signal(object)
    import_replacement_requested = Signal(object)
    import_preview_requested = Signal(object)
    in_game_swap_requested = Signal(object)
    open_archive_target_requested = Signal(object)
    mesh_action_requested = Signal(object)
    open_texture_source_requested = Signal(str, object)

    def __init__(
        self,
        *,
        settings: QSettings,
        theme_key: str = "graphite",
        get_archive_texture_entries_by_normalized_path: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        get_archive_texture_entries_by_basename: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.theme_key = str(theme_key or "graphite")
        self.current_request: Optional[MeshEditorSessionRequest] = None
        self.current_archive_selection: Optional[ArchiveEntry] = None
        self.current_edit_mode = "object"
        self.current_selection_mode = "vertex"
        self.current_selection_empty = True
        self.current_undo_count = 0
        self.current_redo_count = 0
        self.standalone_controller: MeshEditorController | None = None
        self.standalone_file_load_thread: QThread | None = None
        self.standalone_file_load_worker: MeshFileSessionLoadWorker | None = None
        self.standalone_file_load_target_entry: object | None = None
        self.standalone_file_load_source_skeleton: object | None = None
        self.standalone_file_load_request_id = 0
        self.standalone_texture_source_thread: QThread | None = None
        self.standalone_texture_source_worker: MeshTextureSourceResolveWorker | None = None
        self.standalone_texture_source_request_id = 0
        self.standalone_texture_source_target: object | None = None
        self.get_archive_texture_entries_by_normalized_path = get_archive_texture_entries_by_normalized_path
        self.get_archive_texture_entries_by_basename = get_archive_texture_entries_by_basename
        self.standalone_native_host: object | None = None
        self.standalone_native_process: QProcess | None = None
        self.standalone_native_package_thread: QThread | None = None
        self.standalone_native_package_worker: MeshNativePreviewPackageWorker | None = None
        self.standalone_native_package_request_id = 0
        self.standalone_native_package_reset_view = True
        self.standalone_mesh_label = ""
        self.standalone_source_skeleton: object | None = None
        self.standalone_compare_mode = "edited"
        self.standalone_texture_preview_overrides: dict[int, str] = {}
        self.standalone_native_package_dir: Path | None = None
        self.standalone_native_status_file: Path | None = None
        self.standalone_native_status_signature: tuple[int, int] = (0, 0)
        self.standalone_native_status_payload_text = ""
        self.standalone_native_last_status_payload: dict[str, object] = {}
        self.standalone_native_part_picking_wanted = False
        self.standalone_native_part_picking_enabled = False
        self.standalone_native_status_timer = QTimer(self)
        self.standalone_native_status_timer.setInterval(250)
        self.standalone_native_status_timer.timeout.connect(self._poll_standalone_native_preview_status)
        self.standalone_animation_timer = QTimer(self)
        self.standalone_animation_timer.setInterval(33)
        self.standalone_animation_timer.timeout.connect(self._tick_standalone_animation_playback)
        self.standalone_animation_last_tick = 0.0
        self._wired_standalone_native_host_ids: set[int] = set()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.action_bar = MeshEditorActionBar(parent=self)
        self.action_bar.action_requested.connect(self._handle_action_requested)
        root.addWidget(self.action_bar)

        self.workspace_stack = QStackedWidget(self)
        self.workspace_stack.setObjectName("MeshEditorWorkspaceStack")
        self.empty_state = self._build_empty_state()
        self.standalone_workspace = self._build_standalone_workspace()
        self.embedded_builder_host = QFrame(self)
        self.embedded_builder_host.setObjectName("MeshEditorEmbeddedBuilderHost")
        self.embedded_builder_host.setFrameShape(QFrame.Shape.NoFrame)
        self.embedded_builder_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.embedded_builder_host_layout = QVBoxLayout(self.embedded_builder_host)
        self.embedded_builder_host_layout.setContentsMargins(0, 0, 0, 0)
        self.embedded_builder_host_layout.setSpacing(0)

        self.workspace_stack.addWidget(self.empty_state)
        self.workspace_stack.addWidget(self.standalone_workspace)
        self.workspace_stack.addWidget(self.embedded_builder_host)
        root.addWidget(self.workspace_stack, 1)

        self._sync_state()

    def _build_empty_state(self) -> QWidget:
        page = QFrame(self)
        page.setObjectName("MeshEditorEmptyState")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QFrame(page)
        header.setObjectName("MeshEditorEmptyHeader")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setHorizontalSpacing(8)
        header_layout.setVerticalSpacing(3)

        self.target_label = QLabel("Target: none")
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_label.setWordWrap(True)
        self.session_label = QLabel("Mode: no active session")
        self.session_label.setObjectName("HintLabel")
        self.session_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_archive_button = QPushButton("Show Target In Archive")
        self.open_archive_button.setObjectName("MeshEditorShowTargetArchiveButton")
        self.open_archive_button.clicked.connect(self._emit_open_archive_target)

        header_layout.addWidget(self.target_label, 0, 0)
        header_layout.addWidget(self.session_label, 1, 0)
        header_layout.addWidget(self.open_archive_button, 0, 1, 2, 1)
        header_layout.setColumnStretch(0, 1)
        layout.addWidget(header)

        self.empty_status_label = QLabel("Select a supported archive mesh, then choose a workflow.")
        self.empty_status_label.setObjectName("MeshEditorEmptyStatus")
        self.empty_status_label.setWordWrap(True)
        layout.addWidget(self.empty_status_label)

        workflow_row = QHBoxLayout()
        workflow_row.setSpacing(8)
        self.modify_original_button = QPushButton("Modify Original")
        self.modify_original_button.setObjectName("MeshEditorModifyOriginalButton")
        self.import_replacement_button = QPushButton("Import Replacement")
        self.import_replacement_button.setObjectName("MeshEditorImportReplacementButton")
        self.import_preview_button = QPushButton("Import Preview")
        self.import_preview_button.setObjectName("MeshEditorImportPreviewButton")
        self.in_game_swap_button = QPushButton("In-Game Swap")
        self.in_game_swap_button.setObjectName("MeshEditorInGameSwapButton")
        self.modify_original_button.setToolTip("Create or reopen an editable clone workspace for the selected archive mesh.")
        self.import_replacement_button.setToolTip("Import OBJ, DAE, glTF, GLB, PAC, PAM, or PAMLOD as the replacement source.")
        self.import_preview_button.setToolTip("Run the same import path as preview-only, without writing output.")
        self.in_game_swap_button.setToolTip("Use another loaded archive mesh as the source for this target.")
        for button in (
            self.modify_original_button,
            self.import_replacement_button,
            self.import_preview_button,
            self.in_game_swap_button,
        ):
            button.setMinimumHeight(30)
            workflow_row.addWidget(button)
        workflow_row.addStretch(1)
        layout.addLayout(workflow_row)
        layout.addStretch(1)

        self.modify_original_button.clicked.connect(lambda _checked=False: self._emit_target(self.modify_original_requested))
        self.import_replacement_button.clicked.connect(lambda _checked=False: self._emit_target(self.import_replacement_requested))
        self.import_preview_button.clicked.connect(lambda _checked=False: self._emit_target(self.import_preview_requested))
        self.in_game_swap_button.clicked.connect(lambda _checked=False: self._emit_target(self.in_game_swap_requested))
        return page

    def _build_standalone_workspace(self) -> QWidget:
        page = MeshEditorWorkspace(theme_key=self.theme_key, parent=self)
        page.action_requested.connect(self._handle_action_requested)
        page.native_preview_requested.connect(self._start_standalone_native_preview_requested)
        page.texture_edit_requested.connect(self.open_selected_texture_in_editor)
        page.compare_view_requested.connect(self._set_standalone_compare_mode)
        page.skeleton_pose_requested.connect(self._handle_skeleton_pose_request)
        page.part_selection_requested.connect(self._handle_part_selection)
        page.part_context_action_requested.connect(self._handle_part_context_action)
        page.uv_region_selected.connect(self._handle_uv_region_selection)
        page.uv_lasso_selected.connect(self._handle_uv_lasso_selection)
        self.standalone_preview_stack = page.preview_stack
        self.standalone_native_host_frame = page.native_host_frame
        self.standalone_preview = page.preview
        self.standalone_native_host = page.native_host_frame
        self._wire_standalone_native_part_events(self.standalone_native_host)
        self.standalone_native_preview_button = page.native_preview_button
        self.standalone_status_label = page.status_label
        return page

    def builder_host(self) -> QWidget:
        return self.embedded_builder_host

    def active_builder(self) -> Optional[QWidget]:
        item = self.embedded_builder_host_layout.itemAt(0)
        return item.widget() if item is not None else None

    def has_active_builder(self) -> bool:
        return self.active_builder() is not None

    def has_active_standalone_session(self) -> bool:
        return self.standalone_controller is not None and bool(self.standalone_controller.active_session_id)

    def iter_shutdown_workers(self) -> tuple[tuple[str, QThread | None, object | None], ...]:
        return (
            ("standalone_file_load", self.standalone_file_load_thread, self.standalone_file_load_worker),
            ("standalone_texture_source", self.standalone_texture_source_thread, self.standalone_texture_source_worker),
            ("standalone_native_package", self.standalone_native_package_thread, self.standalone_native_package_worker),
        )

    def request_shutdown(self) -> None:
        self.close_standalone_session()

    def mount_embedded_builder(self, builder: QWidget) -> None:
        self.close_standalone_session()
        while self.embedded_builder_host_layout.count():
            item = self.embedded_builder_host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not builder:
                widget.setParent(None)
                widget.deleteLater()
        self.embedded_builder_host_layout.addWidget(builder)
        self.workspace_stack.setCurrentWidget(self.embedded_builder_host)
        self._sync_state()

    def show_empty_state(self, message: str = "") -> None:
        self.close_standalone_session()
        while self.embedded_builder_host_layout.count():
            item = self.embedded_builder_host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        if message:
            self.empty_status_label.setText(message)
        self.workspace_stack.setCurrentWidget(self.empty_state)
        self.update_editor_session_state(None)

    def set_native_preview_host(self, host: object | None) -> None:
        self.standalone_native_host = host if host is not None else getattr(self, "standalone_native_host_frame", None)
        self._wire_standalone_native_part_events(self.standalone_native_host)
        if self.standalone_native_part_picking_wanted:
            self._request_standalone_native_part_picking(True, retries=2)

    def _wire_standalone_native_part_events(self, host: object | None) -> None:
        if host is None:
            return
        marker = id(host)
        if marker in self._wired_standalone_native_host_ids:
            return
        wired = False
        for signal_name, handler in (
            ("source_part_selected", self._handle_native_source_part_selected),
            ("source_part_context_requested", self._handle_native_source_part_context_requested),
        ):
            signal = getattr(host, signal_name, None)
            connector = getattr(signal, "connect", None)
            if not callable(connector):
                continue
            try:
                connector(handler)
                wired = True
            except (RuntimeError, TypeError):
                pass
        if wired:
            self._wired_standalone_native_host_ids.add(marker)

    def _set_standalone_native_part_picking(self, enabled: bool) -> bool:
        setter = getattr(self.standalone_native_host, "set_source_part_picking", None)
        if not callable(setter):
            self.standalone_native_part_picking_enabled = False
            return False
        try:
            ok = bool(setter(bool(enabled)))
        except RuntimeError:
            self.standalone_native_part_picking_enabled = False
            return False
        self.standalone_native_part_picking_enabled = bool(ok and enabled)
        return ok

    def _request_standalone_native_part_picking(self, enabled: bool, *, retries: int = 0) -> bool:
        self.standalone_native_part_picking_wanted = bool(enabled)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if not enabled:
            self._set_standalone_native_part_picking(False)
            if callable(updater):
                updater("Part pick: preview off", available=False)
            return False
        ok = self._set_standalone_native_part_picking(True)
        if ok:
            if callable(updater):
                updater("Part pick: ready", available=True)
            return True
        if callable(updater):
            updater("Part pick: unavailable, waiting for D3D11 host", available=False)
        if retries > 0:
            QTimer.singleShot(250, lambda remaining=int(retries) - 1: self._retry_standalone_native_part_picking(remaining))
        return False

    def _retry_standalone_native_part_picking(self, retries: int) -> None:
        if (
            self.standalone_native_part_picking_wanted
            and not self.standalone_native_part_picking_enabled
            and self.has_active_standalone_session()
        ):
            self._request_standalone_native_part_picking(True, retries=max(0, int(retries or 0)))

    def _standalone_preview_mesh_snapshot(self) -> ParsedMesh:
        controller = self.standalone_controller
        if controller is None:
            raise RuntimeError("Mesh Editor has no standalone edit session.")
        mesh = controller.base_mesh(clone=True) if self.standalone_compare_mode == "source" else controller.pose_preview_mesh()
        if self.standalone_compare_mode != "source":
            self._apply_texture_preview_overrides(mesh)
        return mesh

    def _standalone_reference_mesh_snapshot(self) -> ParsedMesh | None:
        controller = self.standalone_controller
        if controller is None or self.standalone_compare_mode != "ghost":
            return None
        return controller.base_mesh(clone=True)

    def _apply_texture_preview_overrides(self, mesh: ParsedMesh) -> None:
        if not self.standalone_texture_preview_overrides:
            return
        submeshes = tuple(getattr(mesh, "submeshes", ()) or ())
        for submesh_index, texture_path in tuple(self.standalone_texture_preview_overrides.items()):
            if 0 <= int(submesh_index) < len(submeshes):
                submeshes[int(submesh_index)].texture = str(texture_path)

    def write_standalone_native_preview_package(self, output_root: Path | None = None) -> Path:
        controller = self.standalone_controller
        if controller is None:
            raise RuntimeError("Mesh Editor has no standalone edit session.")
        mesh = self._standalone_preview_mesh_snapshot()
        reference_mesh = self._standalone_reference_mesh_snapshot()
        package_dir = mesh_editor_write_native_preview_package(
            mesh,
            reference_mesh=reference_mesh,
            output_root=output_root,
            display_mode="overlay" if self.standalone_compare_mode == "ghost" else "replacement_only",
            skeleton_overlay=controller.skeleton_overlay_data(),
            use_textures=True,
            high_quality_textures=True,
        )
        self.standalone_native_package_dir = package_dir
        self.standalone_native_status_file = package_dir / "host_status.json"
        return package_dir

    def load_standalone_native_preview_package(
        self,
        package_dir: Path | None = None,
        status_file: Path | None = None,
        *,
        reset_view: bool = True,
    ) -> bool:
        host = self.standalone_native_host
        loader = getattr(host, "load_package", None)
        if not callable(loader):
            return False
        selected_package = package_dir or self.standalone_native_package_dir
        if selected_package is None:
            return False
        package_path = Path(selected_package)
        status_path = Path(status_file or self.standalone_native_status_file or package_path / "host_status.json")
        ok = bool(loader(package_path, status_path, reset_view=bool(reset_view)))
        if ok:
            self.standalone_native_package_dir = package_path
            self.standalone_native_status_file = status_path
            self._reset_standalone_native_status_tracking()
            self.standalone_native_status_timer.start()
            if host is getattr(self, "standalone_native_host_frame", None):
                self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
            self._request_standalone_native_part_picking(True, retries=3)
            self.standalone_status_label.setText(f"Native D3D11 preview loading: {package_path}")
        return ok

    def _launch_standalone_native_preview_package(self, package_dir: Path, *, reset_view: bool = True) -> bool:
        package_dir = Path(package_dir)
        status_file = package_dir / "host_status.json"
        self.standalone_native_package_dir = package_dir
        self.standalone_native_status_file = status_file
        try:
            status_file.unlink(missing_ok=True)
        except OSError:
            pass
        if self._standalone_native_process_running():
            if self.load_standalone_native_preview_package(package_dir, status_file, reset_view=reset_view):
                return True
            self._stop_standalone_native_preview_process()
        host = self.standalone_native_host or getattr(self, "standalone_native_host_frame", None)
        try:
            program, arguments = mesh_editor_native_preview_command(package_dir, status_file, host_widget=host)
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 preview unavailable: {exc}")
            self.status_message_requested.emit(f"Native D3D11 preview unavailable: {exc}", True)
            return False
        process = QProcess(self)
        process.setProgram(program)
        process.setArguments(arguments)
        try:
            process.setWorkingDirectory(str(Path(__file__).resolve().parents[3]))
        except Exception:
            pass
        process.setProcessChannelMode(QProcess.SeparateChannels)
        try:
            process.finished.connect(lambda *_args, target=process: self._handle_standalone_native_preview_finished(target))
            process.errorOccurred.connect(lambda _error, target=process: self._handle_standalone_native_preview_error(target))
        except (AttributeError, RuntimeError, TypeError):
            pass
        self.standalone_native_process = process
        if host is getattr(self, "standalone_native_host_frame", None):
            self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
        self.standalone_status_label.setText(f"Native D3D11 preview launching: {package_dir}")
        self._reset_standalone_native_status_tracking()
        self.standalone_native_status_timer.start()
        process.start()
        self._request_standalone_native_part_picking(True, retries=3)
        return True

    def start_standalone_native_preview(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        package_dir = self.write_standalone_native_preview_package(output_root=output_root)
        return self._launch_standalone_native_preview_package(package_dir, reset_view=reset_view)

    def start_standalone_native_preview_async(self, output_root: Path | None = None, *, reset_view: bool = True) -> bool:
        if self.standalone_native_package_thread is not None:
            self.status_message_requested.emit("Native D3D11 preview package is already preparing.", False)
            return False
        controller = self.standalone_controller
        if controller is None:
            self.standalone_status_label.setText("Native D3D11 preview unavailable: no active session.")
            self.status_message_requested.emit("Native D3D11 preview unavailable: no active session.", True)
            return False
        try:
            # Snapshot safety still covers the old working_mesh(clone=True) path;
            # pose preview swaps in a deformed clone without mutating the session.
            mesh_snapshot = self._standalone_preview_mesh_snapshot()
            reference_snapshot = self._standalone_reference_mesh_snapshot()
            skeleton_overlay = controller.skeleton_overlay_data()
        except Exception as exc:
            self.standalone_status_label.setText(f"Native D3D11 preview unavailable: {exc}")
            self.status_message_requested.emit(f"Native D3D11 preview unavailable: {exc}", True)
            return False
        self.standalone_native_package_request_id += 1
        request_id = self.standalone_native_package_request_id
        worker = MeshNativePreviewPackageWorker(
            request_id,
            mesh_snapshot,
            ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True),
            prepare_native_preview=lambda mesh, reference=reference_snapshot: mesh_editor_native_preview_data(mesh, reference_mesh=reference),
            output_root=output_root,
            model_preview_data=ModelPreviewData(path=str(mesh_snapshot.path or "mesh_editor.pac"), physics_overlay=skeleton_overlay),
            use_textures=True,
            high_quality_textures=True,
            backend="d3d11",
            display_mode="overlay" if self.standalone_compare_mode == "ghost" else "replacement_only",
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_standalone_native_package_ready)
        worker.error.connect(self._handle_standalone_native_package_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_native_package_worker(target_thread, target_worker))
        self.standalone_native_package_thread = thread
        self.standalone_native_package_worker = worker
        self.standalone_native_package_reset_view = bool(reset_view)
        self.standalone_status_label.setText("Preparing native D3D11 preview package...")
        thread.start(QThread.LowPriority)
        return True

    def _handle_standalone_native_package_ready(self, request_id: int, package_dir_object: object, elapsed_ms: float) -> None:
        try:
            package_dir = Path(package_dir_object)
        except TypeError:
            return
        if int(request_id) != int(self.standalone_native_package_request_id):
            shutil.rmtree(package_dir, ignore_errors=True)
            return
        if not self.has_active_standalone_session():
            shutil.rmtree(package_dir, ignore_errors=True)
            return
        if self._launch_standalone_native_preview_package(
            package_dir,
            reset_view=self.standalone_native_package_reset_view,
        ):
            self.status_message_requested.emit(f"Native D3D11 preview started after package build ({float(elapsed_ms):.1f} ms).", False)

    def _handle_standalone_native_package_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_native_package_request_id):
            return
        self.standalone_status_label.setText(f"Native D3D11 preview package failed: {message}")
        self.status_message_requested.emit(f"Native D3D11 preview package failed: {message}", True)

    def _cleanup_standalone_native_package_worker(
        self,
        thread: QThread,
        worker: MeshNativePreviewPackageWorker,
    ) -> None:
        if self.standalone_native_package_thread is thread:
            self.standalone_native_package_thread = None
        if self.standalone_native_package_worker is worker:
            self.standalone_native_package_worker = None

    def _cancel_standalone_native_package_worker(self) -> None:
        worker = self.standalone_native_package_worker
        thread = self.standalone_native_package_thread
        if worker is None and thread is None:
            return
        self.standalone_native_package_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _start_standalone_native_preview_requested(self) -> None:
        if not self.has_active_standalone_session():
            self.status_message_requested.emit("Open a mesh session before starting native D3D11 preview.", True)
            return
        if self.start_standalone_native_preview_async():
            self.status_message_requested.emit("Native D3D11 preview package preparation started.", False)

    def open_mesh_session(
        self,
        mesh: ParsedMesh,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> MeshEditSessionView:
        if not isinstance(mesh, ParsedMesh):
            raise TypeError("mesh must be ParsedMesh")
        self.close_standalone_session()
        self.standalone_compare_mode = "edited"
        self.standalone_controller = MeshEditorController()
        self.standalone_source_skeleton = source_skeleton
        view = self.standalone_controller.open_mesh(
            mesh,
            session_id=str(session_id or "mesh-editor-standalone"),
            mode=str(mode or "object"),
        )
        self._show_standalone_session(view, mesh=mesh, target_entry=target_entry)
        return view

    def open_mesh_file_session(
        self,
        path: Path | str,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> MeshEditSessionView:
        source_path = Path(path)
        self.close_standalone_session()
        self.standalone_compare_mode = "edited"
        self.standalone_controller = MeshEditorController()
        loaded_source_skeleton = mesh_editor_source_skeleton(source_skeleton=source_skeleton, source_path=source_path)
        try:
            view = self.standalone_controller.open_mesh_file(
                source_path,
                session_id=str(session_id or f"mesh-editor-file:{source_path.name}"),
                mode=str(mode or "object"),
            )
        except Exception:
            self.standalone_controller = None
            raise
        self.standalone_source_skeleton = loaded_source_skeleton
        if loaded_source_skeleton is not None:
            self.standalone_controller.attach_skeleton(
                loaded_source_skeleton,
                source_path=str(getattr(loaded_source_skeleton, "path", "") or source_path),
            )
        self._show_standalone_session(view, mesh=self.standalone_controller.working_mesh(clone=False), target_entry=target_entry)
        return view

    def open_mesh_file_session_async(
        self,
        path: Path | str,
        *,
        target_entry: object | None = None,
        session_id: str = "",
        mode: str = "object",
        source_skeleton: object | None = None,
    ) -> int:
        source_path = Path(path)
        self.close_standalone_session()
        self.standalone_file_load_request_id += 1
        request_id = self.standalone_file_load_request_id
        worker = MeshFileSessionLoadWorker(
            request_id,
            source_path,
            session_id=str(session_id or f"mesh-editor-file:{source_path.name}"),
            mode=str(mode or "object"),
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.loaded.connect(self._handle_standalone_file_loaded)
        worker.error.connect(self._handle_standalone_file_load_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_standalone_file_loader(target_thread, target_worker))
        self.standalone_file_load_worker = worker
        self.standalone_file_load_thread = thread
        self.standalone_file_load_target_entry = target_entry
        self.standalone_file_load_source_skeleton = mesh_editor_source_skeleton(
            source_skeleton=source_skeleton,
            source_path=source_path,
        )
        self.current_archive_selection = target_entry  # type: ignore[assignment]
        self.current_request = None
        self.standalone_mesh_label = str(source_path)
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self.standalone_status_label.setText(f"Loading Mesh Editor file: {source_path}")
        self.update_editor_session_state(None)
        thread.start(QThread.LowPriority)
        self.status_message_requested.emit(f"Mesh Editor loading standalone mesh: {source_path.name}", False)
        return request_id

    def _handle_standalone_file_loaded(self, request_id: int, mesh_service: MeshService, view: MeshEditSessionView) -> None:
        if int(request_id) != self.standalone_file_load_request_id:
            return
        self.standalone_controller = MeshEditorController(mesh_service=mesh_service)
        view = self.standalone_controller.attach_session(view.session_id)
        mesh = self.standalone_controller.working_mesh(clone=False)
        self.standalone_source_skeleton = self.standalone_file_load_source_skeleton
        if self.standalone_source_skeleton is not None:
            self.standalone_controller.attach_skeleton(
                self.standalone_source_skeleton,
                source_path=str(getattr(self.standalone_source_skeleton, "path", "") or ""),
            )
        self._show_standalone_session(view, mesh=mesh, target_entry=self.standalone_file_load_target_entry)

    def _handle_standalone_file_load_error(self, request_id: int, message: str) -> None:
        if int(request_id) != self.standalone_file_load_request_id:
            return
        self.standalone_controller = None
        self.standalone_status_label.setText(f"Mesh Editor file load failed: {message}")
        self.status_message_requested.emit(f"Mesh Editor file load failed: {message}", True)
        self.update_editor_session_state(None)

    def _cleanup_standalone_file_loader(self, thread: QThread, worker: MeshFileSessionLoadWorker) -> None:
        if self.standalone_file_load_thread is thread:
            self.standalone_file_load_thread = None
        if self.standalone_file_load_worker is worker:
            self.standalone_file_load_worker = None
            self.standalone_file_load_target_entry = None
            self.standalone_file_load_source_skeleton = None

    def _cancel_standalone_file_load(self) -> None:
        worker = self.standalone_file_load_worker
        thread = self.standalone_file_load_thread
        if worker is None and thread is None:
            return
        self.standalone_file_load_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _show_standalone_session(
        self,
        view: MeshEditSessionView,
        *,
        mesh: ParsedMesh,
        target_entry: object | None = None,
    ) -> None:
        self.current_archive_selection = target_entry  # type: ignore[assignment]
        self.current_request = None
        self.standalone_mesh_label = str(mesh.path or "mesh").strip() or "mesh"
        self._sync_standalone_compare_combo()
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self._refresh_standalone_preview()
        self.update_editor_session_state(view, active_selection_mode=self.standalone_controller.active_selection_mode)
        self.status_message_requested.emit(f"Mesh Editor loaded standalone mesh: {Path(self.standalone_mesh_label).name}", False)

    def close_standalone_session(self) -> None:
        self.standalone_animation_timer.stop()
        self.standalone_animation_last_tick = 0.0
        self._cancel_standalone_file_load()
        self._cancel_standalone_texture_source_resolution()
        self._cancel_standalone_native_package_worker()
        self._stop_standalone_native_preview_process()
        if self.standalone_controller is not None:
            try:
                self.standalone_controller.close_active_session()
            except (KeyError, RuntimeError):
                pass
        self.standalone_controller = None
        self.standalone_mesh_label = ""
        self.standalone_source_skeleton = None
        self.standalone_file_load_source_skeleton = None
        self.standalone_compare_mode = "edited"
        self.standalone_texture_preview_overrides.clear()
        self.standalone_native_package_dir = None
        self.standalone_native_status_file = None
        self._reset_standalone_native_status_tracking()
        self.standalone_native_status_timer.stop()
        self._request_standalone_native_part_picking(False)

    def _reset_standalone_native_status_tracking(self) -> None:
        self.standalone_native_status_signature = (0, 0)
        self.standalone_native_status_payload_text = ""
        self.standalone_native_last_status_payload = {}

    def _poll_standalone_native_preview_status(self) -> None:
        status_file = self.standalone_native_status_file
        if status_file is None:
            return
        try:
            stat = Path(status_file).stat()
        except OSError:
            return
        signature = (int(getattr(stat, "st_mtime_ns", 0) or 0), int(getattr(stat, "st_size", 0) or 0))
        try:
            payload_text = Path(status_file).read_text(encoding="utf-8")
        except OSError as exc:
            self.standalone_status_label.setText(f"Native D3D11 status read failed: {exc}")
            return
        if signature == self.standalone_native_status_signature and payload_text == self.standalone_native_status_payload_text:
            return
        self.standalone_native_status_signature = signature
        self.standalone_native_status_payload_text = payload_text
        try:
            payload = json.loads(payload_text)
        except ValueError as exc:
            self.standalone_status_label.setText(f"Native D3D11 status parse failed: {exc}")
            return
        if not isinstance(payload, dict):
            return
        self.standalone_native_last_status_payload = dict(payload)
        event = str(payload.get("event", "") or "").strip().lower()
        if event == "loaded":
            batch_count = int(payload.get("batch_count", 0) or 0)
            vertex_count = int(payload.get("vertex_count", 0) or 0)
            self._request_standalone_native_part_picking(True, retries=2)
            self.standalone_status_label.setText(
                f"Native D3D11 preview loaded: {batch_count:,} batches, {vertex_count:,} vertices."
            )
            self.status_message_requested.emit("Native D3D11 preview loaded.", False)
        elif event == "loading":
            message = str(payload.get("message", "") or "Loading native D3D11 preview...")
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: loading D3D11 host", available=False)
            self.standalone_status_label.setText(message)
            self.status_message_requested.emit(f"Native D3D11 preview: {message}", False)
        elif event == "error":
            message = str(payload.get("message", "") or "Renderer error.")
            self._request_standalone_native_part_picking(False)
            updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
            if callable(updater):
                updater("Part pick: unavailable, D3D11 renderer error", available=False)
            self.standalone_status_label.setText(f"Native D3D11 preview error: {message}")
            self.status_message_requested.emit(f"Native D3D11 preview error: {message}", True)
        elif event == "closed":
            self._request_standalone_native_part_picking(False)
            self.standalone_status_label.setText("Native D3D11 preview closed.")
            self.status_message_requested.emit("Native D3D11 preview closed.", False)

    def _standalone_native_process_running(self) -> bool:
        process = self.standalone_native_process
        if process is None:
            return False
        try:
            return process.state() != QProcess.NotRunning
        except RuntimeError:
            return False

    def _stop_standalone_native_preview_process(self) -> None:
        process = self.standalone_native_process
        self.standalone_native_process = None
        if process is None:
            return
        try:
            running = process.state() != QProcess.NotRunning
        except RuntimeError:
            running = False
        if running:
            try:
                process.terminate()
                if not process.waitForFinished(1000):
                    process.kill()
                    process.waitForFinished(1000)
            except RuntimeError:
                pass
        try:
            process.deleteLater()
        except RuntimeError:
            pass

    def _archive_texture_indexes(self) -> tuple[Mapping[str, Sequence[ArchiveEntry]], Mapping[str, Sequence[ArchiveEntry]]]:
        path_provider = self.get_archive_texture_entries_by_normalized_path
        basename_provider = self.get_archive_texture_entries_by_basename
        try:
            path_index = path_provider() if callable(path_provider) else {}
        except Exception:
            path_index = {}
        try:
            basename_index = basename_provider() if callable(basename_provider) else {}
        except Exception:
            basename_index = {}
        return path_index or {}, basename_index or {}

    def _start_archive_texture_source_resolution(self, target: object) -> bool:
        if self.standalone_texture_source_thread is not None:
            self.status_message_requested.emit("Mesh Editor texture source is already resolving.", False)
            return True
        target_entry = self.current_archive_selection
        if not isinstance(target_entry, ArchiveEntry):
            return False
        path_index, basename_index = self._archive_texture_indexes()
        if not path_index and not basename_index:
            return False
        self.standalone_texture_source_request_id += 1
        request_id = self.standalone_texture_source_request_id
        worker = MeshTextureSourceResolveWorker(
            request_id,
            str(getattr(target, "texture", "") or ""),
            target_entry=target_entry,
            entries_by_normalized_path=path_index,
            entries_by_basename=basename_index,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.resolved.connect(self._handle_archive_texture_source_resolved)
        worker.error.connect(self._handle_archive_texture_source_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(lambda target_thread=thread, target_worker=worker: self._cleanup_archive_texture_source_worker(target_thread, target_worker))
        self.standalone_texture_source_thread = thread
        self.standalone_texture_source_worker = worker
        self.standalone_texture_source_target = target
        thread.start(QThread.LowPriority)
        self.status_message_requested.emit(f"Resolving Mesh Editor archive texture: {getattr(target, 'display_name', '') or getattr(target, 'texture', '')}", False)
        return True

    def _handle_archive_texture_source_resolved(self, request_id: int, result: object) -> None:
        if int(request_id) != int(self.standalone_texture_source_request_id):
            return
        target = self.standalone_texture_source_target
        source_path = getattr(result, "source_path", None)
        if target is None or source_path is None:
            self.status_message_requested.emit("Mesh Editor archive texture source resolved without a usable path.", True)
            return
        self._open_texture_target_source(target, Path(source_path), archive_path=str(getattr(result, "archive_path", "") or ""))
        message = str(getattr(result, "message", "") or "")
        self.status_message_requested.emit(message or f"Mesh Editor archive texture source ready: {Path(source_path).name}", False)

    def _handle_archive_texture_source_error(self, request_id: int, message: str) -> None:
        if int(request_id) != int(self.standalone_texture_source_request_id):
            return
        self.status_message_requested.emit(str(message or "Mesh Editor archive texture source could not be resolved."), True)

    def _cleanup_archive_texture_source_worker(
        self,
        thread: QThread,
        worker: MeshTextureSourceResolveWorker,
    ) -> None:
        if self.standalone_texture_source_thread is thread:
            self.standalone_texture_source_thread = None
        if self.standalone_texture_source_worker is worker:
            self.standalone_texture_source_worker = None
            self.standalone_texture_source_target = None

    def _cancel_standalone_texture_source_resolution(self) -> None:
        worker = self.standalone_texture_source_worker
        thread = self.standalone_texture_source_thread
        if worker is None and thread is None:
            return
        self.standalone_texture_source_request_id += 1
        if worker is not None:
            try:
                worker.stop()
            except RuntimeError:
                pass
        if thread is not None:
            try:
                thread.requestInterruption()
                thread.quit()
            except RuntimeError:
                pass

    def _handle_standalone_native_preview_finished(self, process: QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self._poll_standalone_native_preview_status()
        self.standalone_native_process = None
        self.standalone_native_status_timer.stop()
        self._request_standalone_native_part_picking(False)
        if self.has_active_standalone_session():
            self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)
            last_event = str(self.standalone_native_last_status_payload.get("event", "") or "").strip().lower()
            if last_event not in {"error", "closed"}:
                self._refresh_standalone_preview()

    def _handle_standalone_native_preview_error(self, process: QProcess) -> None:
        if self.standalone_native_process is not process:
            return
        self.standalone_status_label.setText("Native D3D11 preview process error.")
        self._request_standalone_native_part_picking(False)
        updater = getattr(self.standalone_workspace, "set_native_part_picking_status", None)
        if callable(updater):
            updater("Part pick: unavailable, D3D11 process error", available=False)

    def _entry_path(self, entry: object) -> str:
        return str(getattr(entry, "path", "") or getattr(entry, "name", "") or "").strip()

    def _entry_label(self, entry: object) -> str:
        return str(getattr(entry, "basename", "") or Path(self._entry_path(entry)).name or self._entry_path(entry) or "mesh").strip()

    def set_archive_selection(self, entry: Optional[ArchiveEntry]) -> None:
        self.current_archive_selection = entry
        if self.has_active_builder():
            self._sync_state()
            return
        if self.has_active_standalone_session():
            self._sync_state()
            return
        if (
            entry is not None
            and (
                self.current_request is None
                or (
                    self.current_request.source_path is None
                    and self.current_request.source_entry is None
                )
            )
        ):
            self.current_request = MeshEditorSessionRequest(target_entry=entry, mode="modify_original")
        self._sync_state()

    def open_session(self, request: MeshEditorSessionRequest) -> None:
        self.current_request = request
        self.current_archive_selection = request.target_entry
        self._sync_state()
        self.status_message_requested.emit(f"Mesh Editor loaded target: {self._entry_label(request.target_entry)}", False)

    def update_editor_action_state(
        self,
        *,
        mode: str = "",
        active_selection_mode: str = "",
        selection_empty: bool | None = None,
        undo_count: int | None = None,
        redo_count: int | None = None,
    ) -> None:
        if mode:
            self.current_edit_mode = str(mode)
        if active_selection_mode:
            self.current_selection_mode = str(active_selection_mode)
        if selection_empty is not None:
            self.current_selection_empty = bool(selection_empty)
        if undo_count is not None:
            self.current_undo_count = max(0, int(undo_count or 0))
        if redo_count is not None:
            self.current_redo_count = max(0, int(redo_count or 0))
        self._sync_state()

    def update_editor_session_state(
        self,
        view: MeshEditSessionView | None,
        *,
        active_selection_mode: str = "",
    ) -> None:
        summary = getattr(self.standalone_workspace, "update_session_summary", None)
        if callable(summary):
            summary(view, mesh_label=self.standalone_mesh_label)
        self._refresh_standalone_workspace_summary(view)
        self._refresh_standalone_uv_summary(view)
        self._refresh_standalone_skeleton_summary(view)
        self._refresh_standalone_compare_summary(view)
        self._refresh_standalone_export_validation(view)
        if view is None:
            self.update_editor_action_state(
                mode="object",
                active_selection_mode="vertex",
                selection_empty=True,
                undo_count=0,
                redo_count=0,
            )
            return
        self.update_editor_action_state(
            mode=str(view.mode or "object"),
            active_selection_mode=str(active_selection_mode or self.current_selection_mode or "vertex"),
            selection_empty=bool(view.selection.is_empty()),
            undo_count=int(view.undo_count or 0),
            redo_count=int(view.redo_count or 0),
        )

    def set_active_tool_state(self, *, mode: str = "", active_selection_mode: str = "") -> None:
        self.update_editor_action_state(mode=mode, active_selection_mode=active_selection_mode)

    def _refresh_standalone_export_validation(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_export_validation", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.export_validation_report())
        except Exception:
            updater(None)

    def _refresh_standalone_workspace_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_workspace_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.workspace_summary())
        except Exception:
            updater(None)

    def _refresh_standalone_uv_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_uv_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.uv_summary())
        except Exception:
            updater(None)

    def _refresh_standalone_skeleton_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_skeleton_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.skeleton_summary())
        except Exception:
            updater(None)

    def _refresh_standalone_compare_summary(self, view: MeshEditSessionView | None) -> None:
        updater = getattr(self.standalone_workspace, "update_compare_summary", None)
        if not callable(updater):
            return
        controller = self.standalone_controller
        if view is None or controller is None or controller.active_session_id != view.session_id:
            updater(None)
            return
        try:
            updater(controller.compare_summary())
        except Exception:
            updater(None)

    def _current_target_entry(self) -> Optional[ArchiveEntry]:
        if self.current_request is not None:
            return self.current_request.target_entry
        return self.current_archive_selection

    def _sync_state(self) -> None:
        target = self._current_target_entry()
        has_standalone = self.has_active_standalone_session()
        has_target = target is not None or has_standalone
        has_workflow_target = target is not None
        workflow_mode = str(getattr(self.current_request, "mode", "") or "modify_original")
        path_text = self._entry_path(target) if target is not None else self.standalone_mesh_label
        label_text = self._entry_label(target) if target is not None else Path(self.standalone_mesh_label).name or "none"
        self.target_label.setText(f"Target: {path_text or label_text}")
        self.session_label.setText(
            f"Mode: {'standalone' if has_standalone else workflow_mode.replace('_', ' ')} | Edit: {self.current_edit_mode}"
            if has_target
            else "Mode: no active session"
        )
        self.empty_status_label.setText(
            "Ready: choose Modify Original, Import Replacement, Import Preview, or In-Game Swap. "
            "The full Mesh Replacement Builder opens here; archive writes still require explicit build/export confirmation."
            if has_target
            else "No mesh target loaded. Select a .pac, .pam, or .pamlod in Archive Browser, then Open in Mesh Editor."
        )
        for button in (
            self.open_archive_button,
            self.modify_original_button,
            self.import_replacement_button,
            self.import_preview_button,
            self.in_game_swap_button,
        ):
            button.setEnabled(has_workflow_target)
        self.standalone_native_preview_button.setEnabled(has_standalone)
        self.action_bar.setVisible(False)
        self.action_bar.update_action_state(
            has_target=has_target,
            selection_empty=self.current_selection_empty,
            mode=self.current_edit_mode,
            active_selection_mode=self.current_selection_mode,
            undo_count=self.current_undo_count,
            redo_count=self.current_redo_count,
        )
        workspace_state = getattr(self.standalone_workspace, "update_action_state", None)
        if callable(workspace_state):
            workspace_state(
                has_target=has_target,
                selection_empty=self.current_selection_empty,
                mode=self.current_edit_mode,
                active_selection_mode=self.current_selection_mode,
                undo_count=self.current_undo_count,
                redo_count=self.current_redo_count,
            )

    def _handle_action_requested(self, action: object) -> None:
        if self.has_active_standalone_session():
            self._run_standalone_action(action)
            return
        self.mesh_action_requested.emit(action)

    def _handle_skeleton_pose_request(self, command: str, payload: object) -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before editing skeleton preview.", True)
            return False
        normalized = str(command or "").strip().lower()
        try:
            if normalized == "set_pose_preview":
                controller.set_pose_preview(bool(payload))
            elif normalized == "select_bone":
                controller.select_bone(int(payload))  # type: ignore[arg-type]
            elif normalized == "rotate_selected_bone":
                controller.rotate_selected_bone(payload)  # type: ignore[arg-type]
            elif normalized == "reset_pose":
                controller.reset_pose()
            elif normalized == "set_animation_playback":
                summary = controller.set_animation_playback(bool(payload))
                if summary.animation_playback.enabled:
                    self.standalone_animation_last_tick = time.monotonic()
                    self.standalone_animation_timer.start()
                else:
                    self.standalone_animation_timer.stop()
            elif normalized == "set_animation_loop":
                controller.set_animation_loop(bool(payload))
            elif normalized == "set_animation_speed":
                controller.set_animation_speed(payload)
            elif normalized == "seek_animation":
                controller.seek_animation(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "scrub_animation_fraction":
                controller.scrub_animation_fraction(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "step_animation_frame":
                controller.step_animation_frame(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "step_animation":
                controller.step_animation(payload)
                self.standalone_animation_last_tick = time.monotonic()
            elif normalized == "adjust_selected_vertex_bone_weight":
                controller.adjust_selected_vertex_bone_weight(payload)
            elif normalized == "normalize_selected_vertex_weights":
                controller.normalize_selected_vertex_weights()
            elif normalized == "transfer_selected_vertex_weights_from_source":
                controller.transfer_selected_vertex_weights_from_source(source_skeleton=self.standalone_source_skeleton)
            else:
                return False
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor skeleton preview failed: {exc}", True)
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            native_visible = self.standalone_preview_stack.currentWidget() is self.standalone_native_host_frame
            if native_visible or self._standalone_native_process_running():
                if self.standalone_native_package_thread is None:
                    self.start_standalone_native_preview_async(reset_view=False)
            else:
                self._refresh_standalone_preview()
        self.status_message_requested.emit("Mesh Editor skeleton preview updated.", False)
        return True

    def _tick_standalone_animation_playback(self) -> None:
        controller = self.standalone_controller
        if controller is None:
            self.standalone_animation_timer.stop()
            return
        now = time.monotonic()
        previous = self.standalone_animation_last_tick or now
        self.standalone_animation_last_tick = now
        delta = max(0.0, min(0.25, now - previous))
        try:
            summary = controller.step_animation(delta)
        except Exception as exc:
            self.standalone_animation_timer.stop()
            self.status_message_requested.emit(f"Mesh Editor animation playback failed: {exc}", True)
            return
        if not summary.animation_playback.enabled:
            self.standalone_animation_timer.stop()
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if self.standalone_compare_mode != "source":
            if self.standalone_preview_stack.currentWidget() is self.standalone_native_host_frame:
                if self.standalone_native_package_thread is None:
                    self.start_standalone_native_preview_async(reset_view=False)
            elif self._standalone_native_process_running():
                if self.standalone_native_package_thread is None:
                    self.start_standalone_native_preview_async(reset_view=False)
            else:
                self._refresh_standalone_preview()

    def _handle_uv_region_selection(self, uv_min: object, uv_max: object, operation: str = "replace") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting UVs.", True)
            return False
        try:
            result = controller.select_uv_region(uv_min, uv_max, operation=operation)  # type: ignore[arg-type]
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor UV selection failed: {exc}", True)
            return False
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        if view.selection.is_empty():
            self.status_message_requested.emit("Mesh Editor UV region selection is empty.", False)
        else:
            self.status_message_requested.emit("Mesh Editor UV region selected.", False)
        return True

    def _handle_uv_lasso_selection(self, points: object, operation: str = "replace") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting UVs.", True)
            return False
        try:
            result = controller.select_uv_lasso(points, operation=operation)  # type: ignore[arg-type]
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor UV lasso selection failed: {exc}", True)
            return False
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        if view.selection.is_empty():
            self.status_message_requested.emit("Mesh Editor UV lasso selection is empty.", False)
        else:
            self.status_message_requested.emit("Mesh Editor UV lasso selected.", False)
        return True

    def _handle_native_source_part_selected(self, part_index: int) -> bool:
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return False
        return self._handle_part_selection(normalized_index, "toggle")

    def _handle_native_source_part_context_requested(self, part_index: int, x: int, y: int) -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        try:
            normalized_index = int(part_index)
        except (TypeError, ValueError):
            normalized_index = -1
        if normalized_index < 0:
            return False
        if self._selection_for_part_context(controller, normalized_index) is None:
            return False
        global_pos = self._standalone_native_global_pos(x, y)
        QTimer.singleShot(
            0,
            lambda index=normalized_index, position=global_pos: self.standalone_workspace.show_part_context_menu_for_part(
                index,
                position,
            ),
        )
        return True

    def _standalone_native_global_pos(self, x: int, y: int) -> object | None:
        host = self.standalone_native_host
        cursor = getattr(host, "cursor", None)
        if callable(cursor):
            try:
                return cursor().pos()
            except RuntimeError:
                pass
        mapper = getattr(host, "mapToGlobal", None)
        if callable(mapper):
            try:
                return mapper(QPoint(int(x), int(y)))
            except (RuntimeError, TypeError, ValueError):
                pass
        return None

    def _handle_part_selection(self, part_index: int, operation: str = "toggle") -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before selecting parts.", True)
            return False
        normalized_operation = str(operation or "toggle").strip().lower()
        try:
            if normalized_operation == "clear":
                result = controller.select(source_indices=(), operation="replace")
            elif normalized_operation == "select_all":
                summary = controller.workspace_summary()
                result = controller.select(source_indices=tuple(part.index for part in summary.parts), operation="replace")
            elif normalized_operation == "invert":
                summary = controller.workspace_summary()
                selected_sources = set(controller.session_view().selection.source_indices)
                result = controller.select(
                    source_indices=tuple(part.index for part in summary.parts if part.index not in selected_sources),
                    operation="replace",
                )
            else:
                result = controller.select(
                    source_indices=(int(part_index),),
                    operation=normalized_operation,
                )
            update = controller.native_update_for_result(result)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor part selection failed: {exc}", True)
            return False
        view = controller.session_view()
        self.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)
        self._apply_standalone_native_update(update)
        summary = controller.workspace_summary()
        selected_names = ", ".join(part.name for part in summary.parts if part.selected)
        self.status_message_requested.emit(
            f"Mesh Editor selected {len(view.selection.source_indices)} part(s){': ' + selected_names if selected_names else ''}.",
            False,
        )
        return True

    def _handle_part_context_action(self, action_key: str, part_index: int) -> bool:
        normalized = str(action_key or "").strip().lower()
        if normalized == "select_only":
            return self._handle_part_selection(part_index, "replace")
        if normalized == "toggle_selection":
            return self._handle_part_selection(part_index, "toggle")
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before editing parts.", True)
            return False
        selection = self._selection_for_part_context(controller, part_index)
        if selection is None:
            return False
        if normalized == "open_texture":
            return self.open_selected_texture_in_editor()
        if normalized not in {"delete", "duplicate", "recalculate_normals", "flip_normals"}:
            return False
        params = {"delete_parts": True} if normalized == "delete" else {}
        try:
            execution = controller.run_editor_action(normalized, selection=selection, mode="edit", **params)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor part action failed: {normalized}: {exc}", True)
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if execution.edit_result.ok:
            self._apply_standalone_native_update(execution.native_update)
            self._update_standalone_status()
            self.status_message_requested.emit(f"Mesh Editor part action applied: {normalized}.", False)
            return True
        diagnostic = "; ".join(str(item) for item in tuple(execution.edit_result.diagnostics or ()) if str(item).strip())
        self.status_message_requested.emit(
            f"Mesh Editor part action made no changes: {normalized}{': ' + diagnostic if diagnostic else ''}.",
            False,
        )
        return False

    def _selection_for_part_context(
        self,
        controller: MeshEditorController,
        part_index: int,
    ) -> MeshEditSelection | None:
        try:
            clicked_index = int(part_index)
        except (TypeError, ValueError):
            clicked_index = -1
        if clicked_index < 0:
            return None
        selected_sources = set(controller.session_view().selection.source_indices)
        if clicked_index not in selected_sources:
            result = controller.select(source_indices=(clicked_index,), operation="replace")
            self.update_editor_session_state(
                controller.session_view(),
                active_selection_mode=controller.active_selection_mode,
            )
            self._apply_standalone_native_update(controller.native_update_for_result(result))
            selected_sources = {clicked_index}
        return MeshEditSelection.from_maps(source_indices=selected_sources)

    def _run_standalone_action(self, action: object) -> bool:
        controller = self.standalone_controller
        if controller is None:
            return False
        text = str(getattr(action, "text", "") or getattr(action, "key", "") or "action")
        try:
            execution = controller.run_editor_action(action)
        except Exception as exc:
            self.status_message_requested.emit(f"Mesh Editor action failed: {text}: {exc}", True)
            return False
        self.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        if execution.edit_result.ok:
            self._apply_standalone_native_update(execution.native_update)
            self._update_standalone_status()
            self.status_message_requested.emit(f"Mesh Editor action applied: {text}.", False)
            return True
        diagnostic = "; ".join(str(item) for item in tuple(execution.edit_result.diagnostics or ()) if str(item).strip())
        self.status_message_requested.emit(
            f"Mesh Editor action made no changes: {text}{': ' + diagnostic if diagnostic else ''}.",
            False,
        )
        return False

    def _apply_standalone_native_update(self, update: MeshEditorNativeUpdate) -> bool:
        if self.standalone_native_host is not None and apply_native_update_to_host(self.standalone_native_host, update):
            if self.standalone_native_host is getattr(self, "standalone_native_host_frame", None):
                self.standalone_preview_stack.setCurrentWidget(self.standalone_native_host_frame)
            return True
        self._refresh_standalone_preview()
        return False

    def _refresh_standalone_preview(self) -> None:
        controller = self.standalone_controller
        if controller is None:
            self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)
            self.standalone_preview.clear_model("No active edit session.")
            self.standalone_status_label.setText("No active edit session.")
            return
        self.standalone_preview_stack.setCurrentWidget(self.standalone_preview)
        prepared = controller.source_preview_data() if self.standalone_compare_mode == "source" else controller.native_preview_data()
        model = SimpleNamespace(meshes=tuple(getattr(prepared, "batches", ()) or ()), vertex_count=getattr(prepared, "vertex_count", 0))
        self.standalone_preview.set_prepared_model(model, prepared)
        view = controller.session_view()
        self._set_standalone_status(view)

    def _set_standalone_compare_mode(self, mode: str) -> None:
        normalized = str(mode or "edited").strip().lower()
        if normalized not in {"edited", "source", "ghost"}:
            normalized = "edited"
        self.standalone_compare_mode = normalized
        if not self.has_active_standalone_session():
            return
        if normalized == "source":
            self._refresh_standalone_preview()
            return
        host = self.standalone_native_host
        setter = getattr(host, "set_display_mode", None)
        if callable(setter) and self.standalone_preview_stack.currentWidget() is self.standalone_native_host_frame:
            display_mode = "overlay" if normalized == "ghost" else "replacement_only"
            if setter(display_mode):
                self.standalone_status_label.setText(f"Native D3D11 compare view: {normalized}.")
                return
        self._refresh_standalone_preview()

    def _update_standalone_status(self) -> None:
        if self.standalone_controller is None:
            return
        self._set_standalone_status(self.standalone_controller.session_view())

    def _set_standalone_status(self, view: MeshEditSessionView) -> None:
        self.standalone_status_label.setText(
            f"Session: {view.session_id} | Mode: {view.mode} | Revision: {view.revision} | Undo: {view.undo_count} | Redo: {view.redo_count}"
        )

    def _sync_standalone_compare_combo(self) -> None:
        combo = getattr(self.standalone_workspace, "compare_mode_combo", None)
        if combo is None:
            return
        previous = combo.blockSignals(True)
        try:
            combo.setCurrentText("Edited")
        finally:
            combo.blockSignals(previous)

    def open_selected_texture_in_editor(self) -> bool:
        controller = self.standalone_controller
        if controller is None:
            self.status_message_requested.emit("Open a standalone Mesh Editor session before opening a texture.", True)
            return False
        target = controller.texture_edit_target()
        if target is None:
            self.status_message_requested.emit("Selected mesh part has no texture to open.", True)
            return False
        source_path = Path(target.texture).expanduser()
        if not source_path.exists():
            if self._start_archive_texture_source_resolution(target):
                return True
            self.status_message_requested.emit(f"Selected Mesh Editor texture is not a local file yet: {target.texture}", True)
            return False
        self._open_texture_target_source(target, source_path.resolve())
        return True

    def _open_texture_target_source(self, target: object, source_path: Path, *, archive_path: str = "") -> None:
        controller = self.standalone_controller
        if controller is None:
            return
        resolved = Path(source_path).expanduser().resolve()
        texture = str(getattr(target, "texture", "") or "")
        binding = TextureEditorSourceBinding(
            launch_origin="mesh_editor",
            display_name=str(getattr(target, "display_name", "") or resolved.name),
            source_path=str(resolved),
            source_identity_path=f"{controller.active_session_id}:{getattr(target, 'submesh_index', -1)}:{texture}",
            relative_path=archive_path or texture,
            archive_relative_path=archive_path or texture,
            original_dds_path=str(resolved) if resolved.suffix.lower() == ".dds" else "",
            texture_type="mesh_material",
            semantic_subtype=str(getattr(target, "material", "") or getattr(target, "source_texture_set_key", "") or "unknown"),
        )
        self.open_texture_source_requested.emit(str(resolved), binding)
        self.status_message_requested.emit(f"Opening Mesh Editor texture in Texture Editor: {resolved.name}", False)

    def apply_texture_editor_dds_preview(self, dds_path_text: str, binding: object) -> bool:
        controller = self.standalone_controller
        if controller is None or not isinstance(binding, TextureEditorSourceBinding):
            return False
        if str(binding.launch_origin or "") != "mesh_editor" or str(binding.texture_type or "") != "mesh_material":
            return False
        session_id, submesh_index = _mesh_editor_texture_binding_target(binding.source_identity_path)
        if session_id and session_id != controller.active_session_id:
            return False
        if submesh_index < 0:
            return False
        try:
            dds_path = Path(dds_path_text).expanduser()
        except OSError:
            self.status_message_requested.emit(f"Mesh Editor texture preview path is invalid: {dds_path_text}", True)
            return False
        if not dds_path.is_file():
            self.status_message_requested.emit(f"Mesh Editor texture preview DDS not found: {dds_path}", True)
            return False
        resolved = dds_path.resolve()
        self.standalone_texture_preview_overrides[int(submesh_index)] = str(resolved)
        refresh_started = self.start_standalone_native_preview_async(reset_view=False)
        if refresh_started:
            self.status_message_requested.emit(f"Refreshing Mesh Editor D3D11 texture preview: {resolved.name}", False)
        else:
            self.status_message_requested.emit(f"Mesh Editor texture preview staged: {resolved.name}", False)
        return True

    def _emit_target(self, signal: Signal) -> None:
        target = self._current_target_entry()
        if target is None:
            self.status_message_requested.emit("Select a supported archive mesh first.", True)
            return
        signal.emit(target)

    def _emit_open_archive_target(self) -> None:
        target = self._current_target_entry()
        if target is None:
            return
        self.open_archive_target_requested.emit(target)


def _mesh_editor_texture_binding_target(value: object) -> tuple[str, int]:
    parts = str(value or "").split(":", 2)
    if len(parts) < 2:
        return "", -1
    try:
        submesh_index = int(parts[1])
    except (TypeError, ValueError):
        submesh_index = -1
    return str(parts[0] or ""), submesh_index
