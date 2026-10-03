from __future__ import annotations

import json
import hashlib
import os
import struct
import tempfile
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QFont, QKeySequence
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QFrame,
    QGridLayout,
    QHeaderView,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSlider,
    QTabWidget,
    QToolButton,
    QTreeWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.mesh import (
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
    MeshEditCommand,
    MeshEditResult,
    MeshEditSelection,
    MeshExportValidationIssue,
    MeshExportValidationReport,
    summarize_mesh_uvs,
)
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.modding.mesh_exporter import _build_roundtrip_manifest_payload
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.modding.static_mesh_scene_frame import (
    build_authoritative_static_scene_frame,
    static_scene_source_identity,
)
from cdmw.modding.static_mesh_types import StaticReplacementTransform
from cdmw.models import (
    ArchiveEntry,
    PreparedModelPreviewData,
    TextureEditorSourceBinding,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_rust_preview_package import RustPreviewPackage
from cdmw.services.mesh_dotnet_material_state import mesh_dotnet_material_input_signature
from cdmw.services.mesh_texture_sources import MeshTextureSourceResolution, resolve_mesh_texture_source
from cdmw.ui.mesh_editor import (
    MeshEditorActionBar,
    MeshEditorActionExecution,
    MeshEditorController,
    MeshEditorNativeUpdate,
    MeshEditorTab,
)
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from cdmw.workers.mesh_editor_workers import (
    MeshEditCommandWorker,
    MeshEditablePackageExportWorker,
    MeshEditablePackageImportWorker,
    MeshFileSessionLoadWorker,
    MeshRebuildReportWorker,
)
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh, build_synthetic_mesh


def _i32_values(group: object, json_key: str, binary_key: str) -> list[int]:
    if not isinstance(group, dict):
        return []
    raw_json = group.get(json_key)
    if isinstance(raw_json, list):
        return [int(value) for value in raw_json]
    if json_key.endswith("_indices"):
        range_prefix = json_key[: -len("_indices")]
        raw_start = group.get(f"{range_prefix}_start")
        raw_count = group.get(f"{range_prefix}_count")
        if raw_start is not None or raw_count is not None:
            try:
                start = int(raw_start if raw_start is not None else -1)
                count = int(raw_count if raw_count is not None else 0)
            except (TypeError, ValueError, OverflowError):
                return []
            if start >= 0 and count > 0:
                return list(range(start, start + count))
    descriptor = group.get(binary_key)
    if not isinstance(descriptor, dict):
        return []
    path = Path(str(descriptor.get("path") or ""))
    data = path.read_bytes()
    if len(data) % 4:
        return []
    return list(struct.unpack("<" + "i" * (len(data) // 4), data))


def _pab_payload(bones: tuple[tuple[str, int], ...]) -> bytes:
    header = bytearray(0x16)
    header[:4] = b"PAR "
    struct.pack_into("<H", header, 0x14, len(bones))
    identity = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 0.0, 1.0)
    rows: list[bytes] = []
    for index, (name, parent_index) in enumerate(bones):
        encoded = name.encode("ascii")
        row = bytearray()
        row.extend(struct.pack("<I", index + 1))
        row.append(len(encoded))
        row.extend(encoded)
        row.extend(struct.pack("<i", parent_index))
        row.extend(struct.pack("<16f", *identity))
        row.extend(struct.pack("<16f", *identity))
        row.extend(b"\x00" * 128)
        row.extend(struct.pack("<fff", 1.0, 1.0, 1.0))
        row.extend(struct.pack("<ffff", 0.0, 0.0, 0.0, 1.0))
        row.extend(struct.pack("<fff", 0.0, float(index), 0.0))
        rows.append(bytes(row))
    return bytes(header) + b"".join(rows)


class _DummyMeshEditorShell(MeshEditorShellBridgeMixin):
    def __init__(self, tab: MeshEditorTab) -> None:
        self.shell = self
        self.archive = self
        self.mesh_editor_tab = tab
        self.builder: object | None = None
        self.messages: list[tuple[str, bool]] = []

    def _mesh_editor_active_builder(self) -> object | None:
        return self.builder

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.messages.append((message, error))


class _StandaloneNativeHost:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.mesh_edit_stroke_started = _FakeSignal()
        self.mesh_edit_stroke_previewed = _FakeSignal()
        self.mesh_edit_stroke_finished = _FakeSignal()
        self.mesh_edit_stroke_cancelled = _FakeSignal()

    def set_mesh_edit_state(self, **kwargs: object) -> bool:
        self.calls.append(("mesh_edit_state", kwargs))
        return True

    def update_mesh_edit_vertices(self, groups: object) -> bool:
        self.calls.append(("vertices", groups))
        return True

    def replace_mesh_edit_triangles(
        self,
        groups: object,
        *,
        replace_all: bool = False,
        source_submesh_indices: object = (),
    ) -> bool:
        self.calls.append(("triangles", (groups, replace_all, source_submesh_indices)))
        return True

    def set_material_overrides(self, **kwargs: object) -> bool:
        self.calls.append(("material", kwargs))
        return True

    def set_mesh_edit_selection_groups(self, groups: object) -> bool:
        self.calls.append(("selection", groups))
        return True

    def set_display_mode(self, mode: object) -> bool:
        self.calls.append(("display_mode", mode))
        return True

    def load_package(self, package_dir: object, status_file: object, *, reset_view: bool = False) -> bool:
        self.calls.append(("load_package", (Path(package_dir), Path(status_file), bool(reset_view))))
        return True


class _StandaloneNativePickHost(_StandaloneNativeHost):
    def __init__(self) -> None:
        super().__init__()
        self.source_part_selected = _FakeSignal()
        self.source_part_context_requested = _FakeSignal()

    def set_source_part_picking(self, enabled: bool) -> bool:
        self.calls.append(("part_picking", bool(enabled)))
        return True


class _FailingStandaloneNativeHost(_StandaloneNativeHost):
    def update_mesh_edit_vertices(self, groups: object) -> bool:
        self.calls.append(("vertices", groups))
        return False


class _FlakyStandaloneNativePickHost(_StandaloneNativePickHost):
    def __init__(self) -> None:
        super().__init__()
        self.failures = 1

    def set_source_part_picking(self, enabled: bool) -> bool:
        self.calls.append(("part_picking", bool(enabled)))
        if enabled and self.failures > 0:
            self.failures -= 1
            return False
        return True


class _EmbeddedMeshBuilder(QFrame):
    def __init__(self, session_id: str = "embedded-builder") -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        self.dotnet_button = QPushButton(".NET", self)
        self.dotnet_button.setObjectName("MeshAlignmentDotNetExperimentButton")
        self.dotnet_button.setEnabled(False)
        layout.addWidget(self.dotnet_button)
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("MeshAlignmentStickyWorkflowTabs")
        for title in ("Setup", "Parts & Routing", "Mesh Editing", "Diagnostics"):
            self.tabs.addTab(QFrame(self.tabs), title)
        layout.addWidget(self.tabs)
        # Retained static-replacement callers mount a shared preview host;
        # the separate Rust authoring host intentionally has no such controller.
        from cdmw.ui.preview import DotNetPreviewHostFrame, DotNetPreviewProfile

        self.preview_host = DotNetPreviewHostFrame(self, profile=DotNetPreviewProfile.AUTHORING)
        self.preview_host.setObjectName("AlignmentDotNetVorticePreviewHost")
        layout.addWidget(self.preview_host)
        self.controller = MeshEditorController()
        self.controller.open_mesh(_build_two_part_synthetic_mesh(), session_id=str(session_id), mode="edit")
        self.part_actions: list[tuple[str, tuple[int, ...]]] = []
        self.skeleton_bones: list[int] = []
        self.replaced_meshes: list[object] = []
        self.finalized_dotnet_imports: list[str] = []
        self.synced_data_font: QFont | None = None

    def _mesh_editor_embedded_controller(self) -> MeshEditorController:
        return self.controller

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        self.setFont(font)
        self.tabs.setFont(font)
        self.preview_host.setFont(font)
        for child in self.preview_host.findChildren(QWidget):
            child.setFont(font)
        self.synced_data_font = QFont(data_font or font)

    def _mesh_editor_embedded_apply_native_update(self, _native_update: object) -> bool:
        return True

    def _mesh_editor_embedded_replace_working_mesh(self, mesh: object) -> bool:
        self.replaced_meshes.append(mesh)
        return True

    def _mesh_editor_embedded_finalize_dotnet_import(self, reason: str) -> bool:
        self.finalized_dotnet_imports.append(str(reason))
        return True

    def _mesh_editor_embedded_run_part_action(
        self,
        action_key: str,
        source_indices: tuple[int, ...],
        **_kwargs: object,
    ) -> bool:
        self.part_actions.append((str(action_key), tuple(int(index) for index in source_indices)))
        return True

    def _mesh_editor_embedded_set_skeleton_bone(self, bone_index: object) -> bool:
        self.skeleton_bones.append(int(bone_index))
        return True


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list[object] = []

    def connect(self, callback: object) -> None:
        self.callbacks.append(callback)

    def emit(self, *args: object) -> None:
        for callback in tuple(self.callbacks):
            callback(*args)  # type: ignore[misc]


class _FakeSharedDotNetController:
    """Just enough resident controller for the tab's signal wiring."""

    def __init__(self) -> None:
        self.protocol_event = _FakeSignal()
        self.state_changed = _FakeSignal()
        self.package_applied = _FakeSignal()
        self.package_failed = _FakeSignal()
        self.rehydrators: list[object] = []
        self.forgotten_states: list[str] = []

    def set_authoring_rehydrator(self, callback: object) -> None:
        self.rehydrators.append(callback)

    def forget_state(self, key: str) -> None:
        self.forgotten_states.append(str(key))


class _FakeProcess:
    NotRunning = 0
    Running = 1
    SeparateChannels = object()
    instances: list["_FakeProcess"] = []

    def __init__(self, parent: object | None = None) -> None:
        self.parent = parent
        self.program = ""
        self.arguments: list[str] = []
        self.working_directory = ""
        self.channel_mode: object | None = None
        self.started = _FakeSignal()
        self.finished = _FakeSignal()
        self.errorOccurred = _FakeSignal()
        self.readyReadStandardOutput = _FakeSignal()
        self.deleted = False
        self.terminated = False
        self.killed = False
        self.stdin_writes: list[bytes] = []
        self._stdout = bytearray()
        self._state = self.NotRunning
        self.instances.append(self)

    def state(self) -> int:
        return self._state

    def setProgram(self, program: str) -> None:
        self.program = program

    def setArguments(self, arguments: list[str]) -> None:
        self.arguments = list(arguments)

    def setWorkingDirectory(self, path: str) -> None:
        self.working_directory = path

    def setProcessChannelMode(self, mode: object) -> None:
        self.channel_mode = mode

    def start(self) -> None:
        self._state = self.Running
        self.started.emit()

    def terminate(self) -> None:
        self.terminated = True
        self._state = self.NotRunning

    def waitForFinished(self, _msec: int) -> bool:
        return self._state == self.NotRunning

    def write(self, data: object) -> int:
        raw = bytes(data)
        self.stdin_writes.append(raw)
        return len(raw)

    def readAllStandardOutput(self) -> bytes:
        raw = bytes(self._stdout)
        self._stdout.clear()
        return raw

    def emit_stdout(self, text: str) -> None:
        self._stdout.extend(text.encode("utf-8"))
        self.readyReadStandardOutput.emit()

    def kill(self) -> None:
        self.killed = True
        self._state = self.NotRunning

    def deleteLater(self) -> None:
        self.deleted = True


def _dotnet_test_package(package_dir: Path, **extra: object) -> RustPreviewPackage:
    """The package layout the helper is launched against, with its output dir made."""
    output_dir = package_dir / "output"
    output_dir.mkdir(parents=True, exist_ok=True)
    return RustPreviewPackage(
        package_dir=package_dir,
        status_path=output_dir / "dotnet_status.json",
        output_dir=output_dir,
        edit_operations_path=output_dir / "edit_operations.json",
        manifest_path=package_dir / "dotnet_launch.json",
        **extra,
    )


def _install_shared_dotnet_test_process(
    tab: MeshEditorTab,
    process: _FakeProcess,
    *,
    generation: int = 1,
    capabilities: tuple[str, ...] = (),
    session_id: str = "",
) -> object:
    """Attach a fake process to the canonical shared host used by the tab."""
    host = (
        tab.standalone_native_host
        if tab.standalone_dotnet_target_embedded
        else tab.standalone_native_host_frame
    )
    if host.controller is None:
        from cdmw.ui.preview import DotNetPreviewHostFrame, DotNetPreviewProfile

        host = DotNetPreviewHostFrame(tab, profile=DotNetPreviewProfile.AUTHORING)
        if not tab.standalone_dotnet_target_embedded:
            tab.standalone_preview_stack.addWidget(host)
            tab.standalone_native_host_frame = host
        tab.set_native_preview_host(host)
    controller = host.controller
    controller._process = process
    controller._process_generation = int(generation)
    controller._protocol_ready = True
    controller._renderer_ready = True
    controller._session_established = True
    controller._capabilities.update(capabilities)
    package = getattr(tab, "standalone_dotnet_experiment_package", None)
    if package is not None:
        identity = controller._package_identity(package)
        controller._desired_package = package
        controller._desired_package_identity = identity
        controller._applied_package = package
        controller._applied_package_identity = identity
        controller._applied_package_path = str(package.package_dir)
        controller._package_generation = max(1, controller._package_generation)
        controller._applied_package_generation = controller._package_generation
        controller._resident_material_signature = str(
            getattr(tab, "standalone_dotnet_material_signature", "")
            or getattr(package, "material_signature", "")
            or ""
        )
        controller._prewarm_package = None
        controller._launch_is_prewarm = False
    if session_id:
        # A real launch binds the edit session before the helper handshakes, so
        # the two agree from the start. Setting `_session_established` first and
        # binding after would make the controller refuse its own session.
        controller._session_established = False
        controller.set_authoritative_session_id(str(session_id))
        controller._session_established = True
    tab.standalone_dotnet_editor_process = process
    tab.standalone_dotnet_process_generation = int(generation)
    tab.standalone_dotnet_capabilities.update(capabilities)
    tab._wire_shared_dotnet_controller(host)
    return controller


# The standalone file loader runs at QThread.LowPriority
# (cdmw/ui/mesh_editor/tab_session_runtime.py), so under a saturated suite the
# worker can be starved well past the default budget before it even runs. Its
# teardown then needs two more main-loop passes: `worker.finished` is delivered
# cross-thread to `thread.quit`, and `thread.finished` back again to the slot
# that clears the reference. That has no principled wall-clock bound, so waits
# on it get a budget generous enough to absorb scheduling delay while still
# failing a genuine hang. Blocking on QThread.wait() instead would deadlock:
# `quit` is queued to the main thread, which would no longer be pumping.
_LOW_PRIORITY_THREAD_TIMEOUT_SECONDS = 15.0


def _wait_for(app: QApplication, predicate: Callable[[], bool], *, timeout_seconds: float = 2.0) -> bool:
    started = time.monotonic()
    while time.monotonic() - started < timeout_seconds:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.01)
    app.processEvents()
    return bool(predicate())


class MeshEditorActionBarTests(unittest.TestCase):
    def test_action_bar_emits_action_descriptor_and_tracks_checked_modes(self) -> None:
        app = QApplication.instance() or QApplication([])
        action_bar = MeshEditorActionBar()
        emitted: list[object] = []
        action_bar.action_requested.connect(emitted.append)

        action_bar.button_for_key("mode_edit").click()
        action_bar.button_for_key("mode_sculpt").click()
        select_parts_button = action_bar.button_for_key("select_parts")

        self.assertEqual(["mode_edit", "mode_sculpt"], [getattr(action, "key", "") for action in emitted])
        self.assertFalse(action_bar.button_for_key("mode_edit").isChecked())
        self.assertTrue(action_bar.button_for_key("mode_sculpt").isChecked())
        self.assertIsNotNone(select_parts_button)
        assert select_parts_button is not None
        self.assertFalse(select_parts_button.icon().isNull())
        self.assertEqual(Qt.ToolButtonStyle.ToolButtonTextUnderIcon, select_parts_button.toolButtonStyle())
        self.assertEqual("Select", select_parts_button.text())
        self.assertEqual("select", select_parts_button.property("meshEditorCommand"))
        self.assertEqual("", select_parts_button.property("meshEditorSelectionMode"))
        self.assertEqual("select_parts", select_parts_button.property("meshEditorIconKey"))
        self.assertEqual("1", select_parts_button.property("meshEditorShortcut"))
        self.assertEqual("1", select_parts_button.shortcut().toString(QKeySequence.SequenceFormat.PortableText))
        self.assertIn("Shortcut: 1", select_parts_button.toolTip())
        for hidden_key in ("select_vertex", "select_edge", "select_face"):
            self.assertIsNone(action_bar.button_for_key(hidden_key))
        for exact_hidden_key in ("loop_cut", "edge_split", "bridge"):
            button = action_bar.button_for_key(exact_hidden_key)
            self.assertIsNotNone(button)
            assert button is not None
            self.assertTrue(button.isHidden())

        action_bar.set_action_visibility({"select_parts", "loop_cut", "edge_split", "bridge"})
        self.assertFalse(action_bar.button_for_key("loop_cut").isHidden())
        app.processEvents()
        action_bar.deleteLater()


    def _retired_test_dotnet_missing_renderer_ready_stops_embedded_process(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetBlockedReady")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        process = _FakeProcess()
        process._state = process.Running
        tab.standalone_dotnet_editor_process = process  # type: ignore[assignment]

        ok = tab._handle_dotnet_protocol_event({"event": "ready"})

        self.assertFalse(ok)
        self.assertTrue(process.terminated)
        self.assertIsNone(tab.standalone_dotnet_editor_process)
        self.assertFalse(getattr(builder, "_mesh_editor_embedded_dotnet_active", True))
        self.assertEqual("failed", getattr(builder, "_mesh_editor_embedded_dotnet_state", ""))
        app.processEvents()
        tab.deleteLater()


    def _retired_test_mesh_editor_sync_native_preview_uses_pose_payload_before_pose_snapshot(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            package_dir = output_root / "package"
            mesh = build_synthetic_mesh()
            pose_skeleton = object()
            pose_rotations = {0: (0.0, 0.0, 0.0)}
            prepared = PreparedModelPreviewData(source_path="native-pose")
            tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorSyncNativePosePackage"))
            try:
                tab.open_mesh_session(mesh, session_id="sync-native-pose", mode="edit")
                with (
                    patch.object(
                        tab,
                        "_standalone_pose_native_preview_context",
                        return_value=(mesh, pose_skeleton, pose_rotations),
                    ),
                    patch.object(tab, "_standalone_preview_mesh_snapshot", side_effect=AssertionError("snapshot not allowed")),
                    patch("cdmw.ui.mesh_editor.tab.mesh_pose_to_native_preview", return_value=prepared) as native,
                    patch(
                        "cdmw.ui.mesh_editor.tab.mesh_editor_write_prepared_native_preview_package",
                        return_value=package_dir,
                    ) as writer,
                ):
                    self.assertEqual(package_dir, tab.write_standalone_native_preview_package(output_root=output_root))

                native.assert_called_once_with(mesh, skeleton=pose_skeleton, pose_rotations=pose_rotations)
                self.assertIs(writer.call_args.args[0], mesh)
                self.assertIs(writer.call_args.args[1], prepared)
                self.assertEqual(output_root, writer.call_args.kwargs["output_root"])
                self.assertFalse(tab.standalone_native_package_has_reference)
            finally:
                tab.deleteLater()
        app.processEvents()


    def _retired_test_mesh_editor_tab_rejects_legacy_standalone_native_process(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneNativeProcess"))
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-native-process", mode="edit")
        assert tab.standalone_controller is not None
        tab.standalone_controller.attach_skeleton(
            Skeleton(
                path="character/model/body.pab",
                bones=[
                    Bone(index=0, name="Root", parent_index=-1),
                    Bone(index=1, name="Spine", parent_index=0),
                ],
                bone_count=2,
            )
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            output_root = Path(temp_dir)
            _FakeProcess.instances.clear()
            with (
                patch("cdmw.ui.mesh_editor.tab.mesh_editor_write_native_preview_package") as writer,
                patch("cdmw.ui.mesh_editor.tab.mesh_editor_native_preview_command") as command,
                patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess),
            ):
                ok = tab.start_standalone_native_preview(output_root=output_root)

                self.assertFalse(ok)
                writer.assert_not_called()
                command.assert_not_called()
                self.assertEqual([], _FakeProcess.instances)
                self.assertIsNone(tab.standalone_native_process)
        app.processEvents()
        tab.deleteLater()


    def _retired_test_mesh_editor_tab_launches_configured_dotnet_experiment_process(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorDotNetExperimentLaunch")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exe_path = root / "MeshEditorExperiment.exe"
            exe_path.write_text("fake", encoding="utf-8")
            settings.setValue("mesh_editor/dotnet_experiment_executable", str(exe_path))
            package_dir = root / "package"
            output_dir = package_dir / "output"
            output_dir.mkdir(parents=True)
            package = RustPreviewPackage(
                package_dir=package_dir,
                status_path=output_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                manifest_path=package_dir / "dotnet_launch.json",
            )
            package.status_path.write_text(
                json.dumps({"event": "saved", "edited_package": str(output_dir), "message": "saved"}),
                encoding="utf-8-sig",
            )
            _FakeProcess.instances.clear()
            with patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess):
                self.assertTrue(tab._launch_standalone_dotnet_editor_package(package))

                process = _FakeProcess.instances[-1]
                self.assertEqual(str(exe_path), process.program)
                self.assertIn("--input-package", process.arguments)
                self.assertIn(str(package.package_dir), process.arguments)
                self.assertIn("--metadata", process.arguments)
                self.assertIn(str(package.cdmeta_path), process.arguments)
                self.assertIn("--evaluation", process.arguments)
                self.assertIn(str(package.output_dir / "dotnet_evaluation.md"), process.arguments)
                self.assertEqual(str(package.package_dir), process.working_directory)
                self.assertIs(process, tab.standalone_dotnet_editor_process)

                process._state = process.NotRunning
                process.finished.emit(0, 0)

                self.assertIsNone(tab.standalone_dotnet_editor_process)
                self.assertIn("Output package", messages[-1][0])
                self.assertIn("Evaluation", messages[-1][0])
                self.assertFalse(messages[-1][1])
                self.assertTrue((package.output_dir / "dotnet_evaluation.md").is_file())
        app.processEvents()
        tab.deleteLater()

    def _retired_test_mesh_editor_tab_launches_embedded_dotnet_with_parent_hwnd(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetLaunch")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        host = QFrame(builder)
        host.setObjectName("AlignmentNativeD3D11PreviewHost")
        builder.layout().addWidget(host)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exe_path = root / "MeshEditorExperiment.exe"
            exe_path.write_text("fake", encoding="utf-8")
            settings.setValue("mesh_editor/dotnet_experiment_executable", str(exe_path))
            settings.setValue("mesh_editor/use_embedded_dotnet_viewport", True)
            tab.mount_embedded_builder(builder)
            self.assertTrue(getattr(builder, "_mesh_editor_use_embedded_dotnet_viewport", False))

            package_dir = root / "package"
            output_dir = package_dir / "output"
            output_dir.mkdir(parents=True)
            working_mesh = builder.controller.working_mesh(clone=False)
            scene_frame = build_authoritative_static_scene_frame(
                working_mesh,
                working_mesh,
                StaticReplacementTransform(alignment_mode="manual", scale_to_original_length=False),
                source_identity=static_scene_source_identity(working_mesh, None),
                comparison_mode="replacement_only",
                interaction_mode="mesh_edit",
            )
            package = RustPreviewPackage(
                package_dir=package_dir,
                status_path=output_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                manifest_path=package_dir / "dotnet_launch.json",
                material_signature=mesh_dotnet_material_input_signature(working_mesh),
                scene_frame=scene_frame,
            )
            tab.standalone_dotnet_target_embedded = True
            tab.standalone_dotnet_target_controller = builder.controller
            _FakeProcess.instances.clear()
            with patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess):
                self.assertTrue(tab._launch_standalone_dotnet_editor_package(package))

            process = _FakeProcess.instances[-1]
            self.assertIn("--embedded", process.arguments)
            self.assertIn("--parent-hwnd", process.arguments)
            hwnd = int(process.arguments[process.arguments.index("--parent-hwnd") + 1])
            self.assertGreater(hwnd, 0)
            self.assertTrue(tab._request_embedded_dotnet_editor_close())
            self.assertFalse((package_dir / "dotnet_close_requested.txt").exists())
            self.assertTrue(any(b'"event":"deactivate_request"' in write for write in process.stdin_writes))
            self.assertFalse(process.terminated)
            self.assertIs(process, tab.standalone_dotnet_editor_process)
            self.assertEqual("closing", tab.standalone_dotnet_embedded_state)
            self.assertEqual([], builder.finalized_dotnet_imports)
            revision_before_late_event = builder.controller.session_view().revision
            process.emit_stdout(
                '{"event":"command_request","command":"move","delta":[0.05,0,0],'
                '"local_selection":{"vertices_by_submesh":{"0":[0]}}}\n'
            )
            self.assertTrue(
                _wait_for(
                    app,
                    lambda: builder.controller.session_view().revision > revision_before_late_event
                    and not tab._standalone_action_worker_active(),
                )
            )
            self.assertEqual([], builder.finalized_dotnet_imports)
            process.emit_stdout('{"event":"deactivated"}\n')
            self.assertEqual("suspended", tab.standalone_dotnet_embedded_state)
            self.assertEqual(["dotnet_deactivated"], builder.finalized_dotnet_imports)

            tab._start_dotnet_editor_requested(builder.controller, embedded=True)

            self.assertIs(process, tab.standalone_dotnet_editor_process)
            self.assertTrue(any(b'"event":"activate_request"' in write for write in process.stdin_writes))
            self.assertEqual("launching", tab.standalone_dotnet_embedded_state)
            process.emit_stdout('{"event":"activated"}\n')
            self.assertEqual("ready", tab.standalone_dotnet_embedded_state)
            self.assertTrue(getattr(builder, "_mesh_editor_embedded_dotnet_active", False))

            self.assertTrue(tab._request_embedded_dotnet_editor_close())
            self.assertEqual(1, len(builder.finalized_dotnet_imports))
            process.emit_stdout('{"event":"deactivated"}\n')
            finalized_count = len(builder.finalized_dotnet_imports)
            self.assertEqual(2, finalized_count)
            process._state = process.NotRunning
            process.finished.emit(0, 0)

            self.assertEqual(finalized_count, len(builder.finalized_dotnet_imports))
            self.assertEqual("closed", tab.standalone_dotnet_embedded_state)
        app.processEvents()
        tab.deleteLater()


    def _retired_test_mesh_editor_tab_reactivation_repackages_changed_material_inputs(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedDotNetMaterialRefresh"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        mesh = builder.controller.working_mesh(clone=False)
        original_signature = mesh_dotnet_material_input_signature(mesh)
        process = _FakeProcess(tab)
        process._state = process.Running
        package = RustPreviewPackage(
            package_dir=Path("package"),
            status_path=Path("package/dotnet_status.json"),
            output_dir=Path("package/output"),
            edit_operations_path=Path("package/output/edit_operations.json"),
            manifest_path=Path("package/dotnet_launch.json"),
            material_signature=original_signature,
        )
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_dotnet_editor_process = process
        tab.standalone_dotnet_experiment_package = package
        mesh.submeshes[0].texture = "changed_material.dds"

        with patch.object(tab, "_dotnet_editor_executable_path", return_value=None), patch.object(
            tab,
            "_notify_embedded_dotnet_launch_failed",
        ):
            tab._start_dotnet_editor_requested(builder.controller, embedded=True)

        self.assertTrue(process.terminated)
        self.assertIsNone(tab.standalone_dotnet_editor_process)
        self.assertFalse(any(b'"event":"activate_request"' in write for write in process.stdin_writes))
        self.assertEqual("failed", tab.standalone_dotnet_embedded_state)
        app.processEvents()
        tab.deleteLater()

    def _retired_test_mesh_editor_tab_embedded_dotnet_uses_builder_hwnd_without_preview_host(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetNoHostFallback")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exe_path = root / "MeshEditorExperiment.exe"
            exe_path.write_text("fake", encoding="utf-8")
            settings.setValue("mesh_editor/dotnet_experiment_executable", str(exe_path))
            tab.mount_embedded_builder(builder)
            package_dir = root / "package"
            output_dir = package_dir / "output"
            output_dir.mkdir(parents=True)
            package = RustPreviewPackage(
                package_dir=package_dir,
                status_path=output_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                manifest_path=package_dir / "dotnet_launch.json",
            )
            tab.standalone_dotnet_target_embedded = True
            _FakeProcess.instances.clear()
            with patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess):
                self.assertTrue(tab._launch_standalone_dotnet_editor_package(package))

            process = _FakeProcess.instances[-1]
            self.assertIn("--embedded", process.arguments)
            self.assertIn("--parent-hwnd", process.arguments)
            hwnd = int(process.arguments[process.arguments.index("--parent-hwnd") + 1])
            self.assertGreater(hwnd, 0)
        app.processEvents()
        tab.deleteLater()

    def _retired_test_mesh_editor_tab_dotnet_protocol_routes_visible_selection_and_disabled_clipboard(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetProtocol")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        host = QFrame(builder)
        host.setObjectName("AlignmentNativeD3D11PreviewHost")
        builder.layout().addWidget(host)

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exe_path = root / "MeshEditorExperiment.exe"
            exe_path.write_text("fake", encoding="utf-8")
            settings.setValue("mesh_editor/dotnet_experiment_executable", str(exe_path))
            tab.mount_embedded_builder(builder)
            package_dir = root / "package"
            output_dir = package_dir / "output"
            output_dir.mkdir(parents=True)
            package = RustPreviewPackage(
                package_dir=package_dir,
                status_path=output_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                manifest_path=package_dir / "dotnet_launch.json",
            )
            tab.standalone_dotnet_target_embedded = True
            tab.standalone_dotnet_target_controller = builder.controller
            _FakeProcess.instances.clear()
            with patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess):
                self.assertTrue(tab._launch_standalone_dotnet_editor_package(package))

            process = _FakeProcess.instances[-1]
            self.assertTrue(any(b'"event":"session_state"' in write for write in process.stdin_writes))
            process.emit_stdout('{"event":"ready","renderer":{"backend":"wgpu_d3d12_rust","gpu_backed":true,"renderer_blocked":false}}\n')
            self.assertTrue(any(b'"selection_depth_mode":"visible"' in write for write in process.stdin_writes))

            captured: list[MeshEditCommand] = []

            def fake_start_worker(
                _controller: object,
                command: MeshEditCommand,
                *,
                command_name: str,
                request_payload: dict[str, object] | None = None,
            ) -> bool:
                captured.append(command)
                tab._send_dotnet_command_result(
                    command_name,
                    ok=True,
                    status="noop",
                    revision=7,
                    request_payload=request_payload,
                )
                return True

            with patch.object(tab, "_start_dotnet_action_worker", side_effect=fake_start_worker):
                process.emit_stdout(json.dumps({
                    "event": "select_request",
                    "screen_brush": {
                        "x": 10,
                        "y": 20,
                        "radius": 8,
                        "viewport_width": 100,
                        "viewport_height": 80,
                        "world_view_projection": [1.0] * 16,
                    },
                    "target_mode": "face",
                    "selection_depth_mode": "visible",
                    "operation": "add",
                }) + "\n")
            self.assertEqual("select", captured[-1].action)
            screen_payload = captured[-1].params["_native_screen_selection_payload"]
            self.assertIsInstance(screen_payload, dict)
            self.assertEqual("visible", screen_payload["selection_depth_mode"])
            self.assertEqual("source", screen_payload["target_mode"])
            self.assertTrue(any(b'"event":"command_result"' in write for write in process.stdin_writes))

            process.emit_stdout('{"event":"command_request","command":"delete","session_id":"stale"}\n')
            self.assertTrue(any(b"Stale .NET mesh editor session id." in write for write in process.stdin_writes))
            process.emit_stdout('{"event":"command_request","command":"paste"}\n')
            self.assertTrue(any(b'"status":"disabled"' in write and b'"command":"paste"' in write for write in process.stdin_writes))
            process.emit_stdout("{bad json\n")
            self.assertIn("malformed JSON", tab.embedded_workspace.status_label.text())
        app.processEvents()
        tab.deleteLater()

    def _retired_test_mesh_editor_tab_imports_dotnet_output_obj_after_process_exit(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorDotNetExperimentImport")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-dotnet-import", mode="edit")

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            exe_path = root / "MeshEditorExperiment.exe"
            exe_path.write_text("fake", encoding="utf-8")
            settings.setValue("mesh_editor/dotnet_experiment_executable", str(exe_path))
            package_dir = root / "package"
            output_dir = package_dir / "output"
            output_dir.mkdir(parents=True)
            (output_dir / "mesh.obj").write_text("edited", encoding="utf-8")
            package = RustPreviewPackage(
                package_dir=package_dir,
                status_path=output_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                manifest_path=package_dir / "dotnet_launch.json",
            )
            package.status_path.write_text(
                json.dumps(
                    {
                        "event": "saved",
                        "edited_package": str(output_dir),
                        "message": "saved",
                        "metrics": {"average_fps": 72.0, "frame_time_ms": 13.8},
                    }
                ),
                encoding="utf-8",
            )
            started: list[tuple[object, object]] = []

            def fake_start(package_arg: object, payload_arg: object) -> bool:
                started.append((package_arg, payload_arg))
                return True

            _FakeProcess.instances.clear()
            with patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess), patch.object(
                tab,
                "_start_standalone_dotnet_output_import",
                side_effect=fake_start,
            ):
                self.assertTrue(tab._launch_standalone_dotnet_editor_package(package))
                process = _FakeProcess.instances[-1]
                process._state = process.NotRunning
                process.finished.emit(0, 0)

            self.assertEqual(
                [
                    (
                        package,
                        {
                            "event": "saved",
                            "edited_package": str(output_dir),
                            "message": "saved",
                            "metrics": {"average_fps": 72.0, "frame_time_ms": 13.8},
                        },
                    )
                ],
                started,
            )
            self.assertIn("importing", messages[-1][0].lower())
            self.assertFalse(messages[-1][1])
            self.assertTrue((package.output_dir / "dotnet_evaluation.md").is_file())
        tab.close_standalone_session()
        app.processEvents()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
