from __future__ import annotations

import hashlib
import os
import struct
import time
import unittest
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

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
    MeshEditResult,
    MeshEditSelection,
    MeshExportValidationIssue,
    MeshExportValidationReport,
    summarize_mesh_uvs,
)
from cdmw.domain.mesh.authoring_capability import MeshOutputPolicy
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.modding.mesh_exporter import _build_roundtrip_manifest_payload
from cdmw.models import (
    ArchiveEntry,
    TextureEditorSourceBinding,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_rust_preview_package import RustPreviewPackage
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
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh


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


if __name__ == "__main__":
    unittest.main()
