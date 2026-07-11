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
)
from cdmw.modding.mesh_importer import MeshRebuildReport
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.models import (
    ArchiveEntry,
    ModelPreviewData,
    ModelPreviewRenderSettings,
    PreparedModelPreviewData,
    TextureEditorSourceBinding,
)
from cdmw.services.mesh_service import MeshService
from cdmw.services.mesh_dotnet_experiment import MeshDotNetExperimentPackage, mesh_dotnet_material_input_signature
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
    MeshNativePreviewPackageWorker,
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
    def __init__(self) -> None:
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
        self.controller = MeshEditorController()
        self.controller.open_mesh(_build_two_part_synthetic_mesh(), session_id="embedded-builder", mode="edit")
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
        self.synced_data_font = QFont(data_font or font)

    def _mesh_editor_embedded_apply_native_update(self, _native_update: object) -> bool:
        return True

    def _mesh_editor_embedded_replace_working_mesh(self, mesh: object) -> bool:
        self.replaced_meshes.append(mesh)
        return True

    def _mesh_editor_embedded_finalize_dotnet_import(self, reason: str) -> bool:
        self.finalized_dotnet_imports.append(str(reason))
        return True

    def _mesh_editor_embedded_run_part_action(self, action_key: str, source_indices: tuple[int, ...]) -> bool:
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
        loop_cut_button = action_bar.button_for_key("loop_cut")

        self.assertEqual(["mode_edit", "mode_sculpt"], [getattr(action, "key", "") for action in emitted])
        self.assertFalse(action_bar.button_for_key("mode_edit").isChecked())
        self.assertTrue(action_bar.button_for_key("mode_sculpt").isChecked())
        self.assertIsNotNone(loop_cut_button)
        assert loop_cut_button is not None
        self.assertFalse(loop_cut_button.icon().isNull())
        self.assertEqual(Qt.ToolButtonStyle.ToolButtonTextUnderIcon, loop_cut_button.toolButtonStyle())
        self.assertEqual("Loop Cut", loop_cut_button.text())
        self.assertEqual("loop_cut", loop_cut_button.property("meshEditorCommand"))
        self.assertEqual("edit", loop_cut_button.property("meshEditorMode"))
        self.assertEqual("edge", loop_cut_button.property("meshEditorSelectionMode"))
        self.assertEqual("loop_cut", loop_cut_button.property("meshEditorIconKey"))
        self.assertEqual("Ctrl+R", loop_cut_button.property("meshEditorShortcut"))
        self.assertEqual("Ctrl+R", loop_cut_button.shortcut().toString(QKeySequence.SequenceFormat.PortableText))
        self.assertIn("Shortcut: Ctrl+R", loop_cut_button.toolTip())
        app.processEvents()
        action_bar.deleteLater()

    def test_action_bar_tracks_checked_sculpt_tool(self) -> None:
        app = QApplication.instance() or QApplication([])
        action_bar = MeshEditorActionBar()

        action_bar.update_action_state(
            has_target=True,
            selection_empty=False,
            mode="sculpt",
            active_selection_mode="vertex",
            active_tool_key="brush_smooth",
        )

        self.assertTrue(action_bar.button_for_key("brush_smooth").isChecked())
        self.assertFalse(action_bar.button_for_key("brush_inflate").isChecked())
        self.assertFalse(action_bar.button_for_key("select_vertex").isChecked())
        self.assertIn("QToolButton:checked", action_bar.styleSheet())
        self.assertIn("#1769aa", action_bar.styleSheet())

        action_bar.update_action_state(
            has_target=True,
            selection_empty=False,
            mode="sculpt",
            active_selection_mode="vertex",
            active_tool_key="brush_inflate",
        )

        self.assertFalse(action_bar.button_for_key("brush_smooth").isChecked())
        self.assertTrue(action_bar.button_for_key("brush_inflate").isChecked())
        self.assertFalse(action_bar.button_for_key("select_vertex").isChecked())

        action_bar.update_action_state(
            has_target=True,
            selection_empty=False,
            mode="edit",
            active_selection_mode="face",
            active_tool_key="",
        )

        self.assertFalse(action_bar.button_for_key("brush_inflate").isChecked())
        self.assertTrue(action_bar.button_for_key("select_face").isChecked())
        app.processEvents()
        action_bar.deleteLater()

    def test_action_bar_keeps_compact_topology_tools_on_one_row(self) -> None:
        app = QApplication.instance() or QApplication([])
        actions = mesh_editor_actions_by_key()
        action_bar = MeshEditorActionBar(
            tuple(actions[key] for key in ("delete", "subdivide", "refine_smooth", "split", "recalculate_normals"))
        )

        topology_frame = action_bar.findChild(QFrame, "MeshEditorActionCategory_topology")
        self.assertIsNotNone(topology_frame)
        assert topology_frame is not None
        layout = topology_frame.layout()
        self.assertIsInstance(layout, QGridLayout)
        assert isinstance(layout, QGridLayout)
        split_index = layout.indexOf(action_bar.button_for_key("split"))
        row, column, _row_span, _column_span = layout.getItemPosition(split_index)

        self.assertEqual(0, row)
        self.assertEqual(3, column)
        self.assertEqual("Refine", action_bar.button_for_key("refine_smooth").text())
        self.assertEqual("Recalc", action_bar.button_for_key("recalculate_normals").text())
        self.assertEqual("Recalculate Normals", action_bar.button_for_key("recalculate_normals").accessibleName())
        self.assertEqual(Qt.ToolButtonStyle.ToolButtonTextUnderIcon, action_bar.button_for_key("delete").toolButtonStyle())
        self.assertEqual(42, action_bar.button_for_key("delete").height())
        app.processEvents()
        action_bar.deleteLater()

    def test_action_bar_state_disables_selection_history_tools_until_available(self) -> None:
        app = QApplication.instance() or QApplication([])
        action_bar = MeshEditorActionBar()

        action_bar.update_action_state(has_target=True, selection_empty=True, mode="edit", active_selection_mode="face")

        self.assertTrue(action_bar.button_for_key("mode_edit").isChecked())
        self.assertTrue(action_bar.button_for_key("select_face").isChecked())
        self.assertTrue(action_bar.button_for_key("mode_sculpt").isEnabled())
        self.assertTrue(action_bar.button_for_key("brush_grab").isEnabled())
        self.assertFalse(action_bar.button_for_key("recalculate_normals").isEnabled())
        self.assertFalse(action_bar.button_for_key("extrude").isEnabled())
        self.assertFalse(action_bar.button_for_key("material_assign").isEnabled())
        self.assertFalse(action_bar.button_for_key("undo").isEnabled())
        self.assertFalse(action_bar.button_for_key("redo").isEnabled())

        action_bar.update_action_state(
            has_target=True,
            selection_empty=False,
            mode="sculpt",
            active_selection_mode="vertex",
            undo_count=1,
            redo_count=1,
        )

        self.assertTrue(action_bar.button_for_key("mode_sculpt").isChecked())
        self.assertTrue(action_bar.button_for_key("select_vertex").isChecked())
        self.assertTrue(action_bar.button_for_key("brush_grab").isEnabled())
        self.assertFalse(action_bar.button_for_key("extrude").isEnabled())
        self.assertFalse(action_bar.button_for_key("uv_transform").isEnabled())
        self.assertFalse(action_bar.button_for_key("material_assign").isEnabled())
        self.assertFalse(action_bar.button_for_key("material_copy").isEnabled())
        self.assertTrue(action_bar.button_for_key("undo").isEnabled())
        self.assertTrue(action_bar.button_for_key("redo").isEnabled())
        app.processEvents()
        action_bar.deleteLater()

    def test_mesh_editor_tab_exposes_action_bar_signal_for_feature_wiring(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorActionBar"))
        emitted: list[object] = []
        tab.mesh_action_requested.connect(emitted.append)

        self.assertFalse(tab.action_bar.isEnabled())
        self.assertTrue(tab.action_bar.isHidden())
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))
        self.assertTrue(tab.action_bar.isEnabled())
        self.assertTrue(tab.action_bar.isHidden())

        tab.action_bar.button_for_key("extrude").click()
        tab.action_bar.button_for_key("mode_edit").click()

        self.assertFalse(tab.action_bar.button_for_key("extrude").isEnabled())
        self.assertEqual(["mode_edit"], [getattr(action, "key", "") for action in emitted])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_global_action_bar_stays_hidden_in_embedded_builder(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorActionBarScope"))

        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))
        self.assertTrue(tab.action_bar.isHidden())

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-action-scope", mode="edit")
        self.assertIs(tab.workspace_stack.currentWidget(), tab.standalone_workspace)
        self.assertTrue(tab.action_bar.isHidden())

        tab.mount_embedded_builder(QFrame(tab))
        self.assertIs(tab.workspace_stack.currentWidget(), tab.embedded_builder_host)
        self.assertTrue(tab.action_bar.isHidden())

        tab.show_empty_state()
        self.assertIs(tab.workspace_stack.currentWidget(), tab.empty_state)
        self.assertTrue(tab.action_bar.isHidden())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_builder_keeps_advanced_workspace_hidden_without_restore_button(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedMerged"))
        builder = _EmbeddedMeshBuilder()

        tab.mount_embedded_builder(builder)

        self.assertEqual(
            ["Setup", "Parts & Routing", "Mesh Editing", "Diagnostics", "Advanced Mesh Data"],
            [builder.tabs.tabText(index) for index in range(builder.tabs.count())],
        )
        self.assertEqual("Setup", builder.tabs.tabText(builder.tabs.currentIndex()))
        self.assertFalse(builder.tabs.isTabVisible(2))
        self.assertFalse(builder.tabs.isTabVisible(4))
        restore = builder.tabs.findChild(QPushButton, "MeshEditorAdvancedMeshDataRestoreButton")
        self.assertIsNone(restore)
        legacy_restore = builder.tabs.findChild(QPushButton, "MeshEditorLegacyMeshControlsRestoreButton")
        self.assertIsNone(legacy_restore)
        self.assertEqual("Setup", builder.tabs.tabText(builder.tabs.currentIndex()))
        workspace = builder.tabs.findChild(QFrame, "MeshEditorEmbeddedMergedWorkspace")
        self.assertIsNotNone(workspace)
        outliner = workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        material = workspace.findChild(QTreeWidget, "MeshEditorMaterialPanel")
        panels = workspace.findChild(QTabWidget, "MeshEditorRightPanels")
        mode_combo = workspace.findChild(QComboBox, "MeshEditorModeCombo")
        assert outliner is not None
        assert material is not None
        assert panels is not None
        assert mode_combo is not None
        self.assertEqual(0, panels.minimumWidth())
        self.assertEqual(QSizePolicy.Policy.Ignored, panels.sizePolicy().horizontalPolicy())
        self.assertTrue(panels.usesScrollButtons())
        self.assertFalse(panels.tabBar().expanding())
        self.assertLessEqual(mode_combo.maximumWidth(), 118)
        self.assertEqual("0: harness_quad", outliner.topLevelItem(0).text(0))
        self.assertIn("harness.dds", material.topLevelItem(0).text(1))
        status_label = workspace.findChild(QLabel, "MeshEditorStandaloneStatus")
        assert status_label is not None
        self.assertIn("Mesh editing ready", status_label.text())
        self.assertNotIn("Editable session:", status_label.text())
        self.assertIn("Review", [panels.tabText(index) for index in range(panels.count())])
        self.assertIn("Checks", [panels.tabText(index) for index in range(panels.count())])
        self.assertIn("Rebuild", [panels.tabText(index) for index in range(panels.count())])

        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_builder_dotnet_button_routes_to_experiment(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetButton")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))

        tab.mount_embedded_builder(builder)
        button = builder.findChild(QPushButton, "MeshAlignmentDotNetExperimentButton")
        assert button is not None
        self.assertTrue(button.isEnabled())
        self.assertTrue(button.isHidden())

        with patch.object(tab, "_dotnet_editor_executable_path", return_value=None):
            button.click()

        self.assertIn("not configured", messages[-1][0])
        self.assertTrue(messages[-1][1])
        self.assertIsNone(tab.standalone_dotnet_package_thread)
        app.processEvents()
        tab.deleteLater()

    def test_embedded_dotnet_honors_disabled_setting(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            exe_path = Path(tmp) / "cdmw-mesh-dotnet-editor.exe"
            exe_path.write_text("", encoding="utf-8")
            settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetDisabledSetting")
            settings.clear()
            settings.setValue("mesh_editor/dotnet_experiment_executable", str(exe_path))
            settings.setValue("mesh_editor/use_embedded_dotnet_viewport", False)
            tab = MeshEditorTab(settings=settings)
            builder = _EmbeddedMeshBuilder()

            tab.mount_embedded_builder(builder)
            button = builder.findChild(QPushButton, "MeshAlignmentDotNetExperimentButton")
            assert button is not None

            self.assertTrue(getattr(builder, "_mesh_editor_dotnet_available", False))
            self.assertFalse(getattr(builder, "_mesh_editor_use_embedded_dotnet_viewport", True))
            self.assertFalse(getattr(builder, "_mesh_editor_embedded_dotnet_active", True))
            self.assertEqual("closed", getattr(builder, "_mesh_editor_embedded_dotnet_state", ""))
            self.assertTrue(button.isEnabled())
            self.assertTrue(button.isHidden())
            app.processEvents()
            tab.deleteLater()

    def test_embedded_dotnet_auto_start_enabled_by_default_when_helper_available(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            exe_path = Path(tmp) / "cdmw-mesh-dotnet-editor.exe"
            exe_path.write_text("", encoding="utf-8")
            settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetDefaultEnabled")
            settings.clear()
            settings.setValue("mesh_editor/dotnet_experiment_executable", str(exe_path))
            tab = MeshEditorTab(settings=settings)
            builder = _EmbeddedMeshBuilder()

            tab.mount_embedded_builder(builder)

            self.assertTrue(getattr(builder, "_mesh_editor_dotnet_available", False))
            self.assertTrue(getattr(builder, "_mesh_editor_use_embedded_dotnet_viewport", False))
            self.assertFalse(getattr(builder, "_mesh_editor_embedded_dotnet_active", True))
            self.assertEqual("closed", getattr(builder, "_mesh_editor_embedded_dotnet_state", ""))
            self.assertTrue(builder.dotnet_button.isHidden())
            app.processEvents()
            tab.deleteLater()

    def test_dotnet_ready_marks_embedded_active(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetReadyState")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller

        self.assertTrue(tab._handle_dotnet_protocol_event({"event": "ready", "renderer": {"backend": "d3d11_vortice_shader", "gpu_backed": True, "renderer_blocked": False}}))

        self.assertTrue(getattr(builder, "_mesh_editor_embedded_dotnet_active", False))
        self.assertEqual("ready", getattr(builder, "_mesh_editor_embedded_dotnet_state", ""))
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_ready_accepts_material_parity_warning(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetParityReady")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        process = _FakeProcess()
        process._state = process.Running
        tab.standalone_dotnet_editor_process = process  # type: ignore[assignment]

        ok = tab._handle_dotnet_protocol_event(
            {
                "event": "ready",
                "renderer": {
                    "backend": "d3d11_vortice_shader", "gpu_backed": True, "renderer_blocked": False,
                    "native_dds_parity": False,
                    "dds_native_dxgi_upload": False,
                    "dds_upload_mode": "bitmap_rgba_upload",
                },
            }
        )

        self.assertTrue(ok)
        self.assertFalse(process.terminated)
        self.assertIs(process, tab.standalone_dotnet_editor_process)
        self.assertTrue(getattr(builder, "_mesh_editor_embedded_dotnet_active", False))
        self.assertEqual("ready", getattr(builder, "_mesh_editor_embedded_dotnet_state", ""))
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_output_import_accepts_warning_and_keeps_resident_embedded_mesh(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetParityImport")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_target_controller = builder.controller
        with tempfile.TemporaryDirectory() as tmp:
            package_dir = Path(tmp)
            package = MeshDotNetExperimentPackage(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=package_dir / "dotnet_status.json",
                output_dir=package_dir / "output",
                edit_operations_path=package_dir / "output" / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
            )

            ok = tab._start_standalone_dotnet_output_import(
                package,
                {
                    "renderer": {
                        "backend": "d3d11_vortice_shader", "gpu_backed": True, "renderer_blocked": False,
                        "native_dds_parity": False,
                        "dds_native_dxgi_upload": False,
                    },
                },
            )

        self.assertTrue(ok)
        self.assertIsNone(tab.standalone_dotnet_import_thread)
        self.assertEqual(["dotnet_output_ignored"], builder.finalized_dotnet_imports)
        self.assertFalse(builder.replaced_meshes)
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_missing_renderer_ready_stops_embedded_process(self) -> None:
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

    def test_dotnet_process_error_restores_native_controls(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEmbeddedDotNetErrorState")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_embedded = True
        tab._set_embedded_dotnet_state("ready", active=True)
        process = SimpleNamespace(
            errorString=lambda: "boom",
            readAllStandardError=lambda: b"",
            readAllStandardOutput=lambda: b"",
            state=lambda: _FakeProcess.Running,
        )
        tab.standalone_dotnet_editor_process = process  # type: ignore[assignment]

        tab._handle_standalone_dotnet_editor_error(process)  # type: ignore[arg-type]

        self.assertFalse(getattr(builder, "_mesh_editor_embedded_dotnet_active", True))
        self.assertEqual("failed", getattr(builder, "_mesh_editor_embedded_dotnet_state", ""))
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_local_selection_payload_parses_host_selection(self) -> None:
        selection = MeshEditorTab._dotnet_local_selection_payload_to_selection(
            {
                "local_selection": {
                    "vertices_by_submesh": {"0": [2, 1, 1]},
                    "faces_by_submesh": [[1, [4, 3]]],
                    "edges_by_submesh": {"0": [[8, 7], {"vertex_a": 5, "vertex_b": 6}]},
                    "source_indices": ["2", 0],
                }
            }
        )

        self.assertEqual(((0, (1, 2)),), selection.vertices_by_submesh)
        self.assertEqual(((1, (3, 4)),), selection.faces_by_submesh)
        self.assertEqual(((0, ((5, 6), (7, 8))),), selection.edges_by_submesh)
        self.assertEqual((0, 2), selection.source_indices)

    def test_dotnet_local_selection_payload_parses_edge_descriptors(self) -> None:
        selection = MeshEditorTab._dotnet_local_selection_payload_to_selection(
            {
                "local_selection": {
                    "edge_descriptors": [
                        {"source_submesh_index": 2, "vertex_a": 9, "vertex_b": 4},
                    ],
                }
            }
        )

        self.assertEqual(((2, ((4, 9),)),), selection.edges_by_submesh)

    def test_dotnet_selection_request_replaces_resident_selection(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetSelectionRequest"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_dotnet_target_embedded = True
        captured: list[tuple[str, MeshEditSelection | None, dict[str, object]]] = []

        def fake_apply(
            action: str,
            *,
            selection: MeshEditSelection | None = None,
            mode: str | None = None,
            **params: object,
        ) -> MeshEditResult:
            captured.append((action, selection, dict(params)))
            return MeshEditResult(action=action, status="ok", revision=0)

        with patch.object(builder.controller, "apply", side_effect=fake_apply), patch.object(
            tab,
            "_apply_dotnet_result_update",
            return_value=True,
        ):
            self.assertTrue(
                tab._handle_dotnet_protocol_event(
                    {
                        "event": "selection_request",
                        "local_selection": {"vertices_by_submesh": {"0": [2]}},
                    }
                )
            )

        self.assertEqual("select", captured[0][0])
        assert captured[0][1] is not None
        self.assertEqual(((0, (2,)),), captured[0][1].vertices_by_submesh)
        self.assertEqual("replace", captured[0][2]["operation"])
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_stroke_reuses_local_selection_across_incremental_updates(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetStrokeSelection"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_dotnet_target_embedded = True
        captured: list[tuple[str, MeshEditSelection | None, dict[str, object]]] = []

        def fake_apply(
            action: str,
            *,
            selection: MeshEditSelection | None = None,
            mode: str | None = None,
            **params: object,
        ) -> MeshEditResult:
            captured.append((action, selection, dict(params)))
            return MeshEditResult(action=action, status="ok", revision=0)

        screen = {
            "x": 50,
            "y": 50,
            "radius": 24,
            "viewport_width": 100,
            "viewport_height": 100,
            "world_view_projection": [1.0] * 16,
        }
        begin = {
            "stroke_id": "7",
            "tool": "move",
            "screen_brush": screen,
            "screen_drag": {**screen, "start_x": 50, "start_y": 50, "end_x": 50, "end_y": 50},
            "local_selection": {"vertices_by_submesh": {"0": [0]}},
        }
        update = {
            "stroke_id": "7",
            "tool": "move",
            "screen_brush": {**screen, "x": 55},
            "screen_drag": {**screen, "start_x": 50, "start_y": 50, "end_x": 55, "end_y": 50},
        }

        with patch.object(builder.controller, "apply", side_effect=fake_apply), patch.object(
            tab,
            "_apply_dotnet_result_update",
            return_value=True,
        ):
            self.assertTrue(tab._handle_dotnet_stroke_event(begin, "begin"))
            self.assertTrue(tab._handle_dotnet_stroke_event(update, "update"))
            self.assertTrue(tab._handle_dotnet_stroke_event({"stroke_id": "7", "tool": "move"}, "end"))
            assert tab.standalone_live_stroke_dispatcher is not None
            self.assertTrue(tab.standalone_live_stroke_dispatcher.wait_idle(2.0))
            app.processEvents()

        self.assertEqual(["select", "transform", "transform", "transform"], [item[0] for item in captured])
        self.assertNotIn("_native_screen_selection_payload", captured[1][2])
        self.assertNotIn("_native_screen_selection_payload", captured[2][2])
        self.assertEqual((50, 50, 55, 50), tuple(captured[2][2]["screen_drag"][key] for key in ("start_x", "start_y", "end_x", "end_y")))
        self.assertEqual("", tab.standalone_native_mesh_edit_stroke_id)
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_rejects_selection_strokes_and_commands_while_topology_worker_is_active(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorDotNetBusyMutationGate"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_dotnet_target_embedded = True
        process = _FakeProcess(tab)
        process._state = process.Running
        tab.standalone_dotnet_editor_process = process
        tab.standalone_action_worker = object()  # type: ignore[assignment]

        with patch.object(builder.controller, "apply") as apply:
            self.assertTrue(
                tab._handle_dotnet_local_selection_request(
                    {"local_selection": {"vertices_by_submesh": {"0": [0]}}}
                )
            )
            self.assertTrue(tab._handle_dotnet_stroke_event({}, "begin"))
            self.assertTrue(tab._handle_dotnet_command_request({"command": "move", "delta": [0.1, 0.0, 0.0]}))
            apply.assert_not_called()

        busy_results = [write for write in process.stdin_writes if b'"status":"busy"' in write]
        self.assertEqual(3, len(busy_results))
        tab.standalone_action_worker = None
        tab.standalone_dotnet_editor_process = None
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_command_request_sends_topology_action_to_worker_with_local_selection(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorDotNetCommandLocalSelection")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        tab.standalone_dotnet_target_embedded = True
        captured: list[tuple[object, MeshEditCommand, str]] = []

        with patch.object(
            tab,
            "_start_dotnet_action_worker",
            side_effect=lambda controller, command, command_name: captured.append(
                (controller, command, command_name)
            ) or True,
        ):
            self.assertTrue(
                tab._handle_dotnet_command_request(
                    {
                        "event": "command_request",
                        "command": "delete",
                        "local_selection": {
                            "faces_by_submesh": {"0": [1]},
                            "edges_by_submesh": {"0": [[2, 3]]},
                        },
                    }
                )
            )

        self.assertIs(builder.controller, captured[0][0])
        self.assertEqual("delete", captured[0][1].action)
        assert captured[0][1].selection is not None
        self.assertEqual(((0, (1,)),), captured[0][1].selection.faces_by_submesh)
        self.assertEqual(((0, ((2, 3),)),), captured[0][1].selection.edges_by_submesh)
        self.assertEqual("delete", captured[0][2])
        app.processEvents()
        tab.deleteLater()

    def test_dotnet_transform_request_routes_delta_through_host_action(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorDotNetTransformRequest")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        tab.standalone_dotnet_target_controller = builder.controller
        captured: list[tuple[str, MeshEditSelection | None, dict[str, object]]] = []

        def fake_apply_editor_action(
            action: object,
            *,
            selection: MeshEditSelection | None = None,
            mode: str | None = None,
            **params: object,
        ) -> MeshEditResult:
            captured.append((str(action), selection, dict(params)))
            return MeshEditResult(action=str(action), status="ok", revision=builder.controller.session_view().revision)

        builder.controller.apply_editor_action = fake_apply_editor_action  # type: ignore[method-assign]

        self.assertTrue(
            tab._handle_dotnet_command_request(
                {
                    "event": "command_request",
                    "command": "transform_move",
                    "axis": "x",
                    "step": 0.25,
                    "local_selection": {"vertices_by_submesh": {"0": [0]}},
                }
            )
        )

        self.assertEqual("transform_move", captured[0][0])
        self.assertEqual((0.25, 0.0, 0.0), captured[0][2]["delta"])
        assert captured[0][1] is not None
        self.assertEqual(((0, (0,)),), captured[0][1].vertices_by_submesh)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_dotnet_output_import_syncs_builder_mesh(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedDotNetImport"))
        builder = _EmbeddedMeshBuilder()

        tab.mount_embedded_builder(builder)
        controller = builder.controller
        edited = _build_two_part_synthetic_mesh()
        view = controller.mesh_service.replace_working_mesh(controller.session_view().session_id, edited)
        tab.standalone_dotnet_target_controller = controller
        tab.standalone_dotnet_target_embedded = True
        tab.standalone_dotnet_import_request_id = 3

        tab._handle_standalone_dotnet_output_imported(
            3,
            view,
            SimpleNamespace(ok=True, blockers=(), warnings=()),
            1.0,
        )

        self.assertFalse(builder.replaced_meshes)
        self.assertEqual(["dotnet_output_import"], builder.finalized_dotnet_imports)
        self.assertIn("safe to rebuild", tab.embedded_workspace.status_label.text())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_syncs_global_theme_and_font(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorGlobalAppearance"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        font = QFont(app.font())
        font.setPointSize(14)
        data_font = QFont(font)
        data_font.setPointSize(11)

        tab.set_theme("light")
        tab.sync_ui_font(font, data_font)

        self.assertEqual("light", tab.theme_key)
        self.assertEqual("light", tab.standalone_preview._theme_key)
        self.assertEqual(14, tab.action_bar.button_for_key("mode_object").font().pointSize())
        self.assertEqual(11, tab.standalone_workspace.log_list.font().pointSize())
        self.assertEqual(11, tab.standalone_workspace.outliner.font().pointSize())
        self.assertEqual(14, tab.empty_status_label.font().pointSize())
        for object_name in (
            "MeshEditorModeComboLabel",
            "MeshEditorToolCategory_selection",
            "MeshEditorToolCategory_rig",
            "MeshEditorCompareViewLabel",
        ):
            label = tab.standalone_workspace.findChild(QLabel, object_name)
            self.assertIsNotNone(label, object_name)
            self.assertEqual(14, label.font().pointSize(), object_name)
        for object_name in (
            "MeshEditorPosePreviewButton",
            "MeshEditorPartCloneButton",
            "MeshEditorRigSkeletonButton",
        ):
            button = tab.standalone_workspace.findChild(QToolButton, object_name)
            self.assertIsNotNone(button, object_name)
            self.assertEqual(14, button.font().pointSize(), object_name)
        self.assertIsNotNone(tab.embedded_workspace)
        self.assertEqual(11, tab.embedded_workspace.log_list.font().pointSize())
        embedded_label = tab.embedded_workspace.findChild(QLabel, "MeshEditorModeComboLabel")
        self.assertIsNotNone(embedded_label)
        self.assertEqual(14, embedded_label.font().pointSize())
        for widget in tab.findChildren(QWidget):
            if isinstance(widget, (QAbstractItemView, QHeaderView)):
                continue
            if isinstance(widget, (QLabel, QPushButton, QToolButton, QComboBox, QTabWidget)):
                name = widget.objectName() or widget.metaObject().className()
                self.assertEqual(14, widget.font().pointSize(), name)
        for widget in tab.findChildren(QAbstractItemView):
            if widget.objectName():
                self.assertEqual(11, widget.font().pointSize(), widget.objectName())
        for header in tab.findChildren(QHeaderView):
            self.assertEqual(11, header.font().pointSize(), header.objectName() or "QHeaderView")
        self.assertEqual(14, builder.font().pointSize())
        self.assertIsNotNone(builder.synced_data_font)
        self.assertEqual(11, builder.synced_data_font.pointSize())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_merged_part_selection_and_actions_route_to_builder(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedParts"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        workspace = builder.tabs.findChild(QFrame, "MeshEditorEmbeddedMergedWorkspace")
        assert workspace is not None
        outliner = workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        clone = workspace.findChild(QToolButton, "MeshEditorPartCloneButton")
        assert outliner is not None
        assert clone is not None

        outliner.itemClicked.emit(outliner.topLevelItem(0), 0)
        outliner.itemClicked.emit(outliner.topLevelItem(1), 0)

        self.assertEqual((0, 1), builder.controller.session_view().selection.source_indices)
        self.assertEqual("*0: harness_quad", outliner.topLevelItem(0).text(0))
        self.assertEqual("*1: harness_quad_b", outliner.topLevelItem(1).text(0))

        clone.click()
        self.assertEqual([("duplicate", (0, 1))], builder.part_actions)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_context_actions_keep_or_replace_selection(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedContext"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)

        self.assertTrue(tab._handle_embedded_part_selection(0, "replace"))
        self.assertTrue(tab._handle_embedded_part_selection(1, "add"))
        self.assertEqual((0, 1), builder.controller.session_view().selection.source_indices)

        self.assertTrue(tab._handle_embedded_part_context_action("recalculate_normals", 1))
        self.assertEqual((0, 1), builder.controller.session_view().selection.source_indices)
        self.assertEqual(("recalculate_normals", (0, 1)), builder.part_actions[-1])

        self.assertTrue(tab._handle_embedded_part_selection(0, "replace"))
        self.assertTrue(tab._handle_embedded_part_context_action("delete", 1))
        self.assertEqual((1,), builder.controller.session_view().selection.source_indices)
        self.assertEqual(("delete", (1,)), builder.part_actions[-1])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_native_part_click_routes_to_same_selection(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedNativePick"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        picker = getattr(builder, "_mesh_editor_embedded_native_part_selected")

        self.assertTrue(picker(0))
        self.assertEqual((0,), builder.controller.session_view().selection.source_indices)
        self.assertTrue(picker(1))
        self.assertEqual((0, 1), builder.controller.session_view().selection.source_indices)
        self.assertTrue(picker(0))
        self.assertEqual((1,), builder.controller.session_view().selection.source_indices)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_uv_panel_exposes_action_workflow(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedUvActions"))
        builder = _EmbeddedMeshBuilder()
        emitted: list[object] = []
        tab.mesh_action_requested.connect(emitted.append)
        tab.mount_embedded_builder(builder)
        workspace = tab.embedded_workspace
        assert workspace is not None
        select_all = workspace.findChild(QToolButton, "MeshEditorUVSelectAllButton")
        flip_u = workspace.findChild(QToolButton, "MeshEditorUVAction_uv_flip_u")
        summary = workspace.findChild(QLabel, "MeshEditorUVSummaryLabel")
        assert select_all is not None
        assert flip_u is not None
        assert summary is not None

        self.assertIn("UV:", summary.text())
        self.assertFalse(flip_u.isEnabled())
        select_all.click()

        self.assertEqual((0, 1), builder.controller.session_view().selection.source_indices)
        self.assertTrue(flip_u.isEnabled())
        flip_u.click()
        self.assertEqual(["uv_flip_u"], [getattr(action, "key", "") for action in emitted])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_rig_is_readable_and_selects_bones(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedRig"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        builder.controller.attach_skeleton(
            Skeleton(
                path="character/model/body.pab",
                bones=[
                    Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0)),
                    Bone(index=1, name="Spine", parent_index=0, position=(0.0, 1.0, 0.0)),
                ],
                bone_count=2,
            )
        )
        tab._refresh_embedded_workspace_from_builder()
        workspace = tab.embedded_workspace
        assert workspace is not None

        self.assertIsNotNone(workspace.findChild(QLabel, "MeshEditorSkeletonReadOnlyLabel"))
        self.assertIsNone(workspace.findChild(QToolButton, "MeshEditorPosePreviewButton"))
        skeleton = workspace.findChild(QTreeWidget, "MeshEditorSkeletonPanel")
        assert skeleton is not None
        rows = [skeleton.topLevelItem(index) for index in range(skeleton.topLevelItemCount())]
        spine = next(item for item in rows if item.text(0).strip() == "1: Spine")

        skeleton.itemClicked.emit(spine, 0)

        self.assertEqual(1, builder.controller.skeleton_summary().pose.selected_bone_index)
        self.assertEqual([1], builder.skeleton_bones)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_embedded_reports_native_editor_unavailable_and_disables_native_tools(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedNativeUnavailable"))
        builder = _EmbeddedMeshBuilder()

        with patch("cdmw.ui.mesh_editor.tab.native_mesh_core_available", return_value=False):
            tab.mount_embedded_builder(builder)
            builder.controller.select(vertices_by_submesh={0: (0,)})
            tab._refresh_embedded_workspace_from_builder()

            workspace = tab.embedded_workspace
            assert workspace is not None
            delete = workspace.findChild(QToolButton, "MeshEditorPartDeleteButton")
            clone = workspace.findChild(QToolButton, "MeshEditorPartCloneButton")
            clear = workspace.findChild(QToolButton, "MeshEditorPartClearSelectionButton")
            assert delete is not None
            assert clone is not None
            assert clear is not None

            self.assertIn("Native Mesh Editor unavailable", workspace.status_label.text())
            self.assertFalse(delete.isEnabled())
            self.assertFalse(clone.isEnabled())
            self.assertTrue(clear.isEnabled())
            self.assertFalse(tab._handle_embedded_part_context_action("delete", 0))
            self.assertEqual([], builder.part_actions)
            self.assertIn("Native Mesh Editor C++ core is missing", workspace.status_label.text())

        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_standalone_workspace_exposes_blender_style_regions(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorWorkspace"))
        emitted: list[object] = []
        tab.mesh_action_requested.connect(emitted.append)
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))

        workspace = tab.standalone_workspace
        self.assertIsNotNone(workspace.findChild(QFrame, "MeshEditorTopModeBar"))
        self.assertIsNotNone(workspace.findChild(QFrame, "MeshEditorLeftToolPalette"))
        self.assertIsNotNone(workspace.findChild(QFrame, "MeshEditorCentralPreview"))
        self.assertIsNotNone(workspace.findChild(QFrame, "MeshEditorBottomStatusStrip"))
        self.assertIsNotNone(workspace.findChild(QFrame, "MeshEditorUVCanvas"))
        self.assertIsNotNone(workspace.findChild(QComboBox, "MeshEditorSnapModeCombo"))
        self.assertIsNotNone(workspace.findChild(QComboBox, "MeshEditorPivotCombo"))
        self.assertIsNotNone(workspace.findChild(QComboBox, "MeshEditorOrientationCombo"))
        panels = workspace.findChild(QTabWidget, "MeshEditorRightPanels")
        assert panels is not None
        self.assertEqual(
            [
                "Parts",
                "Details",
                "Rig",
                "UV Map",
                "Part Actions",
                "Review",
                "Checks",
                "Rebuild",
                "Performance",
                "History",
            ],
            [panels.tabText(index) for index in range(panels.count())],
        )
        left_pages = workspace.findChild(QTabWidget, "MeshEditorLeftToolPages")
        assert left_pages is not None
        self.assertEqual(["Tools", "Edit", "UV", "Rig"], [left_pages.tabText(index) for index in range(left_pages.count())])

        button = workspace.findChild(QToolButton, "MeshEditorWorkspaceAction_select_edge")
        brush_button = workspace.findChild(QToolButton, "MeshEditorWorkspaceAction_brush_grab")
        skeleton_button = workspace.findChild(QToolButton, "MeshEditorPreviewSkeletonButton")
        pose_preview_button = workspace.findChild(QToolButton, "MeshEditorPreviewPoseButton")
        assert button is not None
        assert brush_button is not None
        assert skeleton_button is not None
        assert pose_preview_button is not None
        self.assertEqual(Qt.ToolButtonStyle.ToolButtonIconOnly, button.toolButtonStyle())
        self.assertIn("Shortcut: 2", button.toolTip())
        button.click()

        self.assertEqual(["select_edge"], [getattr(action, "key", "") for action in emitted])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_part_rows_toggle_persistent_selection(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPartSelection"))

        tab.open_mesh_session(
            _build_two_part_synthetic_mesh(),
            session_id="standalone-part-selection",
            mode="edit",
        )
        assert tab.standalone_controller is not None
        outliner = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        material = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorMaterialPanel")
        assert outliner is not None
        assert material is not None

        outliner.itemClicked.emit(outliner.topLevelItem(0), 0)
        self.assertEqual((0,), tab.standalone_controller.session_view().selection.source_indices)

        outliner = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        assert outliner is not None
        outliner.itemClicked.emit(outliner.topLevelItem(1), 0)
        self.assertEqual((0, 1), tab.standalone_controller.session_view().selection.source_indices)

        outliner = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        material = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorMaterialPanel")
        assert outliner is not None
        assert material is not None
        self.assertEqual("*0: harness_quad", outliner.topLevelItem(0).text(0))
        self.assertEqual("*1: harness_quad_b", outliner.topLevelItem(1).text(0))
        self.assertEqual("*1: harness_material_b", material.topLevelItem(1).text(0))

        material.itemClicked.emit(material.topLevelItem(0), 0)
        self.assertEqual((1,), tab.standalone_controller.session_view().selection.source_indices)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_part_context_clone_and_delete_use_part_selection(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPartContext"))

        tab.open_mesh_session(
            _build_two_part_synthetic_mesh(),
            session_id="standalone-part-context",
            mode="edit",
        )
        assert tab.standalone_controller is not None
        workspace = tab.standalone_workspace
        workspace.part_selection_requested.emit(0, "toggle")
        workspace.part_selection_requested.emit(1, "toggle")
        routed: list[tuple[str, tuple[int, ...]]] = []

        def fake_run(action: object, *, selection: MeshEditSelection | None = None, **_params: object) -> MeshEditorActionExecution:
            routed.append((str(action), tuple(selection.source_indices if selection is not None else ())))
            return MeshEditorActionExecution(
                MeshEditResult(action=str(action), status="ok", revision=1, affected_submesh_indices=tuple(selection.source_indices if selection else ())),
                MeshEditorNativeUpdate(),
            )

        with patch.object(tab.standalone_controller, "run_editor_action", side_effect=fake_run):
            workspace.part_context_action_requested.emit("duplicate", 0)
            workspace.part_context_action_requested.emit("delete", 1)

        self.assertEqual([("duplicate", (0, 1)), ("delete", (0, 1))], routed)
        self.assertEqual((0, 1), tab.standalone_controller.session_view().selection.source_indices)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_part_controls_show_selection_details_and_route_actions(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPartControls"))
        native_available = patch("cdmw.ui.mesh_editor.tab.native_mesh_core_available", return_value=True)
        native_available.start()
        self.addCleanup(native_available.stop)

        tab.open_mesh_session(
            _build_two_part_synthetic_mesh(),
            session_id="standalone-part-controls",
            mode="edit",
        )
        assert tab.standalone_controller is not None
        workspace = tab.standalone_workspace
        summary = workspace.findChild(QLabel, "MeshEditorPartSelectionSummary")
        status = workspace.findChild(QLabel, "MeshEditorPartStatusStrip")
        select_all = workspace.findChild(QToolButton, "MeshEditorPartSelectAllButton")
        clear = workspace.findChild(QToolButton, "MeshEditorPartClearSelectionButton")
        clone = workspace.findChild(QToolButton, "MeshEditorPartCloneButton")
        delete = workspace.findChild(QToolButton, "MeshEditorPartDeleteButton")
        recalc = workspace.findChild(QToolButton, "MeshEditorPartRecalculateNormalsButton")
        flip = workspace.findChild(QToolButton, "MeshEditorPartFlipNormalsButton")
        texture = workspace.findChild(QToolButton, "MeshEditorOpenTextureButton")
        for widget in (summary, status, select_all, clear, clone, delete, recalc, flip, texture):
            assert widget is not None

        self.assertTrue(select_all.isEnabled())
        self.assertFalse(clear.isEnabled())
        self.assertFalse(clone.isEnabled())
        self.assertFalse(delete.isEnabled())
        self.assertFalse(recalc.isEnabled())
        self.assertFalse(flip.isEnabled())
        self.assertFalse(texture.isEnabled())

        select_all.click()
        self.assertEqual((0, 1), tab.standalone_controller.session_view().selection.source_indices)
        self.assertIn("2/2", summary.text())
        self.assertIn("harness_quad_b", summary.text())
        self.assertIn("mat harness_material_b", summary.text())
        self.assertIn("tex harness_b.dds", summary.text())
        self.assertIn("2/2 selected", status.text())
        self.assertTrue(clone.isEnabled())
        self.assertTrue(delete.isEnabled())
        self.assertTrue(recalc.isEnabled())
        self.assertTrue(flip.isEnabled())
        self.assertTrue(texture.isEnabled())

        routed_part_actions: list[tuple[str, int]] = []
        try:
            workspace.part_context_action_requested.disconnect()
        except (TypeError, RuntimeError):
            pass
        workspace.part_context_action_requested.connect(
            lambda action, part_index: routed_part_actions.append((str(action), int(part_index)))
        )
        clone.click()
        self.assertEqual([("duplicate", 0)], routed_part_actions)
        clear.click()
        self.assertEqual((), tab.standalone_controller.session_view().selection.source_indices)
        self.assertFalse(clone.isEnabled())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_open_texture_button_disabled_for_selected_untextured_part(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPartTextureUnavailable"))
        mesh = _build_two_part_synthetic_mesh()
        mesh.submeshes[0].texture = ""

        tab.open_mesh_session(mesh, session_id="standalone-part-texture-unavailable", mode="edit")
        assert tab.standalone_controller is not None
        workspace = tab.standalone_workspace
        texture = workspace.findChild(QToolButton, "MeshEditorOpenTextureButton")
        summary = workspace.findChild(QLabel, "MeshEditorPartSelectionSummary")
        assert texture is not None
        assert summary is not None

        workspace.part_selection_requested.emit(0, "replace")
        self.assertFalse(texture.isEnabled())
        self.assertIn("missing texture", summary.text())
        self.assertIsNone(tab.standalone_controller.texture_edit_target())

        workspace.part_selection_requested.emit(1, "replace")
        self.assertTrue(texture.isEnabled())
        self.assertEqual(1, tab.standalone_controller.texture_edit_target().submesh_index)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_native_preview_part_pick_uses_persistent_part_selection(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorNativePartPick"))
        host = _StandaloneNativePickHost()
        tab.set_native_preview_host(host)
        shown_menus: list[tuple[int, object]] = []

        tab.open_mesh_session(
            _build_two_part_synthetic_mesh(),
            session_id="standalone-native-part-pick",
            mode="edit",
        )
        assert tab.standalone_controller is not None

        host.source_part_selected.emit(0)
        self.assertEqual((0,), tab.standalone_controller.session_view().selection.source_indices)

        host.source_part_selected.emit(1)
        self.assertEqual((0, 1), tab.standalone_controller.session_view().selection.source_indices)

        with patch.object(
            tab.standalone_workspace,
            "show_part_context_menu_for_part",
            side_effect=lambda part_index, global_pos=None: shown_menus.append((int(part_index), global_pos)),
        ):
            host.source_part_context_requested.emit(1, 12, 34)
            app.processEvents()

        self.assertEqual((0, 1), tab.standalone_controller.session_view().selection.source_indices)
        self.assertEqual(1, shown_menus[-1][0])

        host.source_part_selected.emit(1)
        self.assertEqual((0,), tab.standalone_controller.session_view().selection.source_indices)
        with patch.object(
            tab.standalone_workspace,
            "show_part_context_menu_for_part",
            side_effect=lambda part_index, global_pos=None: shown_menus.append((int(part_index), global_pos)),
        ):
            host.source_part_context_requested.emit(1, 22, 44)
            app.processEvents()

        self.assertEqual((1,), tab.standalone_controller.session_view().selection.source_indices)
        self.assertEqual(1, shown_menus[-1][0])

        tab.load_standalone_native_preview_package(
            Path("C:/tmp/mesh-editor-native-pick-package"),
            Path("C:/tmp/mesh-editor-native-pick-status.json"),
            reset_view=False,
        )
        self.assertIn(("part_picking", True), host.calls)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_native_preview_stroke_dispatches_native_session_payload(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorNativeStroke"))
        host = _StandaloneNativeHost()
        tab.set_native_preview_host(host)
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-native-stroke", mode="edit")
        assert tab.standalone_controller is not None
        tab.standalone_controller.select(vertices_by_submesh={0: (0, 1)})
        tab.update_editor_session_state(
            tab.standalone_controller.session_view(),
            active_selection_mode=tab.standalone_controller.active_selection_mode,
        )
        tab.set_active_tool_state(mode="edit", active_tool_key="transform_move")

        mesh_edit_states = [payload for name, payload in host.calls if name == "mesh_edit_state"]
        self.assertTrue(mesh_edit_states)
        self.assertTrue(mesh_edit_states[-1]["enabled"])
        self.assertEqual("move", mesh_edit_states[-1]["tool"])
        self.assertEqual("selection", mesh_edit_states[-1]["target_mode"])

        captured: list[tuple[str, str | None, dict[str, object]]] = []

        def fake_apply(action: str, *, selection: object = None, mode: str | None = None, **params: object) -> MeshEditResult:
            captured.append((str(action), mode, dict(params)))
            phase = str(params.get("stroke_phase") or "")
            changed = ((0, (0, 1)),) if phase == "update" else ()
            native_groups = (
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices": [0, 1],
                    "positions": [0.0, 0.0, 0.0, 0.25, 0.0, 0.0],
                },
            ) if changed else ()
            return MeshEditResult(
                action=str(action),
                status="ok",
                revision=len(captured),
                affected_submesh_indices=(0,) if changed else (),
                changed_vertices_by_submesh=changed,
                metrics={"native_stroke_active": 0.0 if phase == "end" else 1.0},
                native_preview_vertex_update_groups=native_groups,
            )

        vertex_descriptor = {"path": "move_vertices.bin", "count": 2, "components": 1, "type": "i32"}
        begin_drag = {"start_x": 10, "start_y": 20, "end_x": 10, "end_y": 20, "viewport_width": 100, "viewport_height": 80}
        update_drag = {"start_x": 10, "start_y": 20, "end_x": 18, "end_y": 20, "viewport_width": 100, "viewport_height": 80}
        with (
            patch.object(tab, "_native_mesh_editor_available", return_value=True),
            patch.object(tab.standalone_controller, "apply", side_effect=fake_apply),
        ):
            host.mesh_edit_stroke_started.emit(
                {
                    "stroke_id": 7,
                    "tool": "move",
                    "screen_drag": begin_drag,
                    "groups": (
                        {
                            "source_submesh_index": 0,
                            "source_vertex_indices_binary": vertex_descriptor,
                        },
                    ),
                }
            )
            host.mesh_edit_stroke_previewed.emit(
                {
                    "stroke_id": 7,
                    "tool": "move",
                    "screen_drag": update_drag,
                    "groups": (
                        {
                            "source_submesh_index": 0,
                            "source_vertex_indices_binary": vertex_descriptor,
                        },
                    ),
                }
            )
            host.mesh_edit_stroke_finished.emit({"stroke_id": 7, "tool": "move"})
            dispatcher = tab.standalone_live_stroke_dispatcher
            self.assertIsNotNone(dispatcher)
            assert dispatcher is not None
            self.assertTrue(dispatcher.wait_idle(2.0))
            app.processEvents()

        self.assertEqual(["transform", "transform", "transform"], [item[0] for item in captured])
        self.assertEqual(["begin", "update", "end"], [item[2]["stroke_phase"] for item in captured])
        self.assertEqual(["7", "7", "7"], [item[2]["stroke_id"] for item in captured])
        self.assertEqual(begin_drag, captured[0][2]["screen_drag"])
        self.assertEqual(update_drag, captured[1][2]["screen_drag"])
        self.assertNotIn("translate", captured[0][2])
        self.assertNotIn("translate", captured[1][2])
        self.assertEqual(
            [{"index": 0, "indices_binary": vertex_descriptor}],
            captured[0][2]["_native_selection_payload"]["vertices_by_submesh"],  # type: ignore[index]
        )
        self.assertNotIn("_native_selection_payload", captured[1][2])
        self.assertNotIn("_native_selection_payload", captured[2][2])
        self.assertEqual("", tab.standalone_native_mesh_edit_stroke_id)
        self.assertFalse(tab._standalone_action_worker_active())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_native_brush_stroke_forwards_d3d11_candidate_groups(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorNativeBrushStroke"))
        host = _StandaloneNativeHost()
        tab.set_native_preview_host(host)
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-native-brush-stroke", mode="sculpt")
        assert tab.standalone_controller is not None
        tab.set_active_tool_state(mode="sculpt", active_tool_key="brush_grab")

        captured: list[dict[str, object]] = []

        def fake_apply(action: str, *, selection: object = None, mode: str | None = None, **params: object) -> MeshEditResult:
            _ = selection
            self.assertEqual("brush", action)
            self.assertEqual("sculpt", mode)
            captured.append(dict(params))
            return MeshEditResult(action="brush", status="ok", revision=len(captured), metrics={"native_stroke_active": 1.0})

        vertex_descriptor = {"path": "stroke_vertices.bin", "count": 2, "components": 1, "type": "i32"}
        weight_descriptor = {"path": "stroke_weights.bin", "count": 2, "components": 1, "type": "f32"}
        screen_drag = {"start_x": 10, "start_y": 20, "end_x": 10, "end_y": 28, "viewport_width": 100, "viewport_height": 80}
        with (
            patch.object(tab, "_native_mesh_editor_available", return_value=True),
            patch.object(tab.standalone_controller, "apply", side_effect=fake_apply),
        ):
            host.mesh_edit_stroke_started.emit(
                {
                    "stroke_id": 9,
                    "tool": "grab",
                    "screen_drag": screen_drag,
                    "strength": 0.625,
                    "groups": (
                        {
                            "source_submesh_index": 0,
                            "source_vertex_indices_binary": vertex_descriptor,
                            "source_vertex_weights_binary": weight_descriptor,
                        },
                    ),
                }
            )
            dispatcher = tab.standalone_live_stroke_dispatcher
            self.assertIsNotNone(dispatcher)
            assert dispatcher is not None
            self.assertTrue(dispatcher.wait_idle(2.0))
            app.processEvents()

        native_selection = captured[0]["_native_selection_payload"]
        assert isinstance(native_selection, dict)
        self.assertEqual(
            [{"index": 0, "indices_binary": vertex_descriptor, "weights_binary": weight_descriptor}],
            native_selection["vertices_by_submesh"],
        )
        self.assertEqual(screen_drag, captured[0]["screen_drag"])
        self.assertNotIn("delta", captured[0])
        self.assertEqual(0.625, captured[0]["strength"])
        for omitted in ("center", "amount", "radius", "falloff", "iterations", "invert"):
            self.assertNotIn(omitted, captured[0])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_native_preview_part_pick_replays_after_loaded_status(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorNativePartPickReplay"))
            host = _FlakyStandaloneNativePickHost()
            tab.set_native_preview_host(host)
            tab.open_mesh_session(
                _build_two_part_synthetic_mesh(),
                session_id="standalone-native-part-pick-replay",
                mode="edit",
            )
            status = tab.standalone_workspace.findChild(QLabel, "MeshEditorNativePartPickStatus")
            assert status is not None
            package_dir = Path(temp_dir) / "package"
            status_file = Path(temp_dir) / "host_status.json"

            tab.load_standalone_native_preview_package(package_dir, status_file, reset_view=False)
            self.assertFalse(bool(status.property("nativePartPickingAvailable")))
            self.assertIn("unavailable", status.text())

            status_file.write_text(json.dumps({"event": "loaded", "batch_count": 2, "vertex_count": 12}), encoding="utf-8")
            tab._poll_standalone_native_preview_status()

            self.assertGreaterEqual(host.calls.count(("part_picking", True)), 2)
            self.assertTrue(bool(status.property("nativePartPickingAvailable")))
            self.assertIn("ready", status.text())
            app.processEvents()
            tab.deleteLater()

    def test_mesh_editor_workspace_compare_panel_reflects_source_vs_edited_summary(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", f"MeshEditorComparePanel-{time.time_ns()}"))

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-compare", mode="edit")
        assert tab.standalone_controller is not None
        tab.standalone_controller.apply(
            "transform",
            selection=MeshEditSelection.from_maps(vertices_by_submesh={0: (0,)}),
            mode="edit",
            translate=(0.0, 0.0, 0.5),
        )
        tab.update_editor_session_state(
            tab.standalone_controller.session_view(),
            active_selection_mode=tab.standalone_controller.active_selection_mode,
        )
        session = tab.standalone_controller.mesh_service._session(tab.standalone_controller.active_session_id)
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((4, 2),)

        compare = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorComparePanel")
        combo = tab.standalone_workspace.findChild(QComboBox, "MeshEditorCompareModeCombo")
        assert compare is not None
        assert combo is not None
        tab.standalone_compare_mode = "edited"
        rows = [(compare.topLevelItem(index).text(0), compare.topLevelItem(index).text(2)) for index in range(compare.topLevelItemCount())]
        self.assertEqual([("Info", "")], rows)

        self.assertEqual("edited", tab.standalone_compare_mode)
        self.assertTrue(tab.standalone_controller.native_editor_mesh_dirty())
        tab._refresh_standalone_preview()
        edited_vertices = int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0)
        self.assertEqual(0, edited_vertices)
        self.assertIn("Python preview rebuild is disabled", tab.standalone_status_label.text())
        tab.standalone_controller.apply(
            "duplicate",
            selection=MeshEditSelection.from_maps(source_indices=(0,)),
            mode="edit",
        )
        tab.update_editor_session_state(
            tab.standalone_controller.session_view(),
            active_selection_mode=tab.standalone_controller.active_selection_mode,
        )
        session.native_editor_mesh_dirty = True
        session.native_editor_mesh_dirty_counts = ((8, 4),)
        tab._refresh_standalone_preview()
        duplicated_vertices = int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0)
        self.assertEqual(0, duplicated_vertices)
        tab.standalone_compare_mode = "source"
        tab._refresh_standalone_preview()
        source_vertices = int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0)

        self.assertGreater(source_vertices, 0)
        self.assertEqual("source", tab.standalone_compare_mode)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_validator_panel_reflects_controller_report(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorValidatorPanel"))
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].normals = []

        tab.open_mesh_session(mesh, session_id="standalone-validator", mode="edit")

        validator = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorValidatorPanel")
        assert validator is not None
        codes = [validator.topLevelItem(index).text(1) for index in range(validator.topLevelItemCount())]
        self.assertIn("summary", codes)
        self.assertIn("missing_normals", codes)
        tab.standalone_workspace.update_export_validation(
            MeshExportValidationReport(
                mesh_format="pac",
                submesh_count=1,
                vertex_count=3,
                face_count=1,
                parse_confidence="exact",
                no_op_roundtrip_status="PASS",
                no_op_byte_identical=True,
                no_op_unexpected_differences=0,
            )
        )
        codes = [validator.topLevelItem(index).text(1) for index in range(validator.topLevelItemCount())]
        self.assertIn("parse_confidence", codes)
        self.assertIn("no_op_roundtrip", codes)
        status_rows = {
            validator.topLevelItem(index).text(1): validator.topLevelItem(index).text(2)
            for index in range(validator.topLevelItemCount())
            if validator.topLevelItem(index).text(0) == "Status"
        }
        self.assertEqual("pass", status_rows["Validation status"])
        self.assertEqual("yes", status_rows["Rebuild allowed"])
        self.assertEqual("ready", status_rows["Sidecar status"])
        self.assertEqual("safe", status_rows["Topology status"])
        self.assertEqual("preserved", status_rows["Bone data status"])
        self.assertEqual("preserved", status_rows["LOD identity status"])
        self.assertEqual("preserved", status_rows["Submesh identity status"])
        emitted: list[bool] = []
        tab.standalone_workspace.validation_report_requested.connect(lambda: emitted.append(True))
        run_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorRunValidationReportButton")
        assert run_button is not None
        self.assertTrue(run_button.isEnabled())
        run_button.click()
        self.assertEqual([True], emitted)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_runs_validation_report_in_background(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorRunValidationReport"))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].normals = []

        try:
            tab.open_mesh_session(mesh, session_id="run-validation-report", mode="edit")
            run_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorRunValidationReportButton")
            validator = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorValidatorPanel")
            assert run_button is not None
            assert validator is not None
            self.assertTrue(run_button.isEnabled())

            run_button.click()
            deadline = time.time() + 5.0
            while tab.standalone_validation_thread is not None and time.time() < deadline:
                app.processEvents()
                time.sleep(0.01)
            app.processEvents()

            self.assertIsNone(tab.standalone_validation_thread)
            self.assertIsNone(tab.standalone_validation_worker)
            codes = [validator.topLevelItem(index).text(1) for index in range(validator.topLevelItemCount())]
            self.assertIn("missing_normals", codes)
            self.assertIn("Validation finished", messages[-1][0])
            self.assertTrue(messages[-1][1])
        finally:
            tab.close_standalone_session()
            app.processEvents()
            tab.deleteLater()

    def test_mesh_editor_tab_copies_validation_report_json(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorCopyValidationReport"))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].normals = []

        tab.open_mesh_session(mesh, session_id="copy-validation-report", mode="edit")
        copy_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorCopyValidationReportButton")
        assert copy_button is not None
        self.assertTrue(copy_button.isEnabled())

        QApplication.clipboard().clear()
        copy_button.click()
        payload = json.loads(QApplication.clipboard().text())

        self.assertEqual("pac", payload["mesh_format"])
        self.assertFalse(payload["ok"])
        self.assertGreaterEqual(payload["blocker_count"], 1)
        missing_normals = next(issue for issue in payload["issues"] if issue["code"] == "missing_normals")
        self.assertEqual("error", missing_normals["severity"])
        self.assertFalse(missing_normals["can_continue"])
        self.assertEqual(4, missing_normals["expected"])
        self.assertEqual(0, missing_normals["actual"])
        self.assertEqual(0, missing_normals["lod_index"])
        self.assertEqual(0, missing_normals["submesh_index"])
        self.assertEqual(("Validation report copied to clipboard.", False), messages[-1])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_rebuild_panel_reflects_report(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorRebuildReportPanel"))
        tab.open_mesh_session(build_synthetic_mesh(), session_id="rebuild-report-panel", mode="edit")

        rebuild = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorRebuildReportPanel")
        save_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorSaveRebuildReportButton")
        rebuild_asset_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorRebuildPatchedAssetButton")
        preview_rebuilt_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPreviewRebuiltAssetButton")
        package_rebuilt_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPackageRebuiltAssetButton")
        assert rebuild is not None
        assert save_button is not None
        assert rebuild_asset_button is not None
        assert preview_rebuilt_button is not None
        assert package_rebuilt_button is not None
        self.assertEqual("No rebuild report.", rebuild.topLevelItem(0).text(1))
        self.assertFalse(save_button.isEnabled())
        self.assertFalse(preview_rebuilt_button.isEnabled())
        self.assertFalse(package_rebuilt_button.isEnabled())
        tab.standalone_workspace.update_export_validation(None)
        self.assertFalse(rebuild_asset_button.isEnabled())

        report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="a" * 64,
            rebuilt_asset_hash="b" * 64,
            source_size=10,
            rebuilt_size=12,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=False,
            changed_byte_ranges=((2, 4),),
            edited_lods=(0,),
            edited_submeshes=("lod0_submesh0",),
            changed_channels=("positions",),
            edit_operations=(
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
            warnings=("missing_tangents",),
            output_path="out.pac",
        )
        tab.standalone_workspace.update_rebuild_report(report)

        rows = {
            rebuild.topLevelItem(index).text(0): rebuild.topLevelItem(index).text(1)
            for index in range(rebuild.topLevelItemCount())
        }
        self.assertEqual("passed", rows["Validation"])
        self.assertEqual("pac", rows["Format"])
        self.assertEqual("exact", rows["Parse confidence"])
        self.assertEqual("aaaaaaaaaaaa", rows["Source hash"])
        self.assertEqual("bbbbbbbbbbbb", rows["Rebuilt hash"])
        self.assertEqual("1", rows["Changed byte ranges"])
        self.assertEqual("lod0_submesh0", rows["Edited submeshes"])
        self.assertEqual("positions", rows["Changed channels"])
        self.assertEqual("replace_positions_same_count", rows["Edit operations"])
        self.assertEqual("missing_tangents", rows["Warnings"])
        self.assertEqual("out.pac", rows["Output"])
        self.assertTrue(save_button.isEnabled())
        self.assertTrue(preview_rebuilt_button.isEnabled())
        self.assertTrue(package_rebuilt_button.isEnabled())
        save_emitted: list[bool] = []
        tab.standalone_workspace.save_rebuild_report_requested.connect(lambda: save_emitted.append(True))
        save_button.click()
        self.assertEqual([True], save_emitted)
        preview_emitted: list[bool] = []
        tab.standalone_workspace.preview_rebuilt_asset_requested.connect(lambda: preview_emitted.append(True))
        preview_rebuilt_button.click()
        self.assertEqual([True], preview_emitted)
        package_emitted: list[bool] = []
        tab.standalone_workspace.package_rebuilt_asset_requested.connect(lambda: package_emitted.append(True))
        package_rebuilt_button.click()
        self.assertEqual([True], package_emitted)
        emitted: list[bool] = []
        tab.standalone_workspace.rebuild_report_requested.connect(lambda: emitted.append(True))
        tab.standalone_workspace.update_action_state(has_target=True)
        run_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorRunRebuildReportButton")
        assert run_button is not None
        self.assertTrue(run_button.isEnabled())
        run_button.click()
        self.assertEqual([True], emitted)
        tab.standalone_workspace.update_export_validation(
            MeshExportValidationReport(
                mesh_format="pac",
                submesh_count=1,
                vertex_count=4,
                face_count=2,
                parse_confidence="exact",
                no_op_roundtrip_status="PASS",
                no_op_byte_identical=True,
            )
        )
        self.assertTrue(rebuild_asset_button.isEnabled())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_saves_last_rebuild_report_json(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorSaveRebuildReport"))
        report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="a" * 64,
            rebuilt_asset_hash="b" * 64,
            source_size=10,
            rebuilt_size=12,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=False,
            changed_byte_ranges=((2, 4),),
            edited_lods=(0,),
            edited_submeshes=("lod0_submesh0",),
            changed_channels=("positions",),
            edit_operations=(
                {
                    "operation": "replace_positions_same_count",
                    "lod_index": 0,
                    "submesh_index": 0,
                    "vertex_count": 4,
                    "source": "mesh.obj",
                },
            ),
            warnings=("missing_tangents",),
            output_path="out.pac",
        )
        tab.standalone_last_rebuild_report = report
        with tempfile.TemporaryDirectory() as temp_dir:
            target = Path(temp_dir) / "report.json"

            saved = tab._save_standalone_rebuild_report(target)
            payload = json.loads(target.read_text(encoding="utf-8"))

        self.assertEqual(target, saved)
        self.assertEqual("pac", payload["mesh_format"])
        self.assertEqual("exact", payload["parse_confidence"])
        self.assertEqual(False, payload["byte_identical"])
        self.assertEqual([[2, 4]], payload["changed_byte_ranges"])
        self.assertEqual(1, payload["changed_range_count"])
        self.assertEqual(["lod0_submesh0"], payload["edited_submeshes"])
        self.assertEqual(["positions"], payload["changed_channels"])
        self.assertEqual("replace_positions_same_count", payload["edit_operations"][0]["operation"])
        self.assertEqual(["missing_tangents"], payload["warnings"])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_rebuild_asset_requires_passing_validation_and_output_path(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorRebuildPatchedAsset"))
        tab.open_mesh_session(build_synthetic_mesh(), session_id="rebuild-patched-asset", mode="edit")
        tab.standalone_last_export_validation_report = None
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda text, is_error=False: messages.append((text, bool(is_error))))

        with patch.object(tab, "_start_standalone_rebuild_report_requested") as started:
            tab._start_standalone_rebuild_asset_requested()
        self.assertFalse(started.called)
        self.assertEqual(("Run validation successfully before rebuilding a patched asset.", True), messages[-1])

        tab.standalone_last_export_validation_report = MeshExportValidationReport(
            mesh_format="pac",
            submesh_count=1,
            vertex_count=4,
            face_count=2,
            parse_confidence="exact",
            no_op_roundtrip_status="PASS",
            no_op_byte_identical=True,
        )
        with tempfile.TemporaryDirectory() as temp_dir:
            target = str(Path(temp_dir) / "rebuilt.pac")
            with (
                patch("cdmw.ui.mesh_editor.tab.QFileDialog.getSaveFileName", return_value=(target, "")),
                patch.object(tab, "_start_standalone_rebuild_report_requested") as started,
            ):
                tab._start_standalone_rebuild_asset_requested()

            started.assert_called_once_with(output_path=target, action_text="patched asset rebuild")
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_rebuild_asset_allows_developer_override_setting(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorDeveloperRebuildOverride")
        settings.clear()
        settings.setValue("mesh_editor/developer_mode", True)
        settings.setValue("mesh_editor/developer_rebuild_override", True)
        settings.setValue("mesh_editor/developer_rebuild_override_reason", "Forced rebuild for local testing")
        tab = MeshEditorTab(settings=settings)
        tab.open_mesh_session(build_synthetic_mesh(), session_id="rebuild-developer-override", mode="edit")
        tab.standalone_last_export_validation_report = MeshExportValidationReport(
            mesh_format="pac",
            submesh_count=1,
            vertex_count=4,
            face_count=2,
            parse_confidence="fallback_scan",
            no_op_roundtrip_status="PASS",
            no_op_byte_identical=True,
            issues=(
                MeshExportValidationIssue(
                    severity="blocker",
                    code="unsafe_parse_confidence",
                    message="fallback_scan blocked",
                    category="rebuild",
                ),
            ),
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            target = str(Path(temp_dir) / "rebuilt.pac")
            with (
                patch("cdmw.ui.mesh_editor.tab.QFileDialog.getSaveFileName", return_value=(target, "")),
                patch.object(tab, "_start_standalone_rebuild_report_requested") as started,
            ):
                tab._start_standalone_rebuild_asset_requested()

            started.assert_called_once_with(
                output_path=target,
                action_text="patched asset rebuild",
                developer_override=True,
                developer_override_reason="Forced rebuild for local testing",
            )
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_preview_rebuilt_asset_routes_archive_target_and_output_path(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rebuilt_path = temp_path / "rebuilt.pac"
            rebuilt_path.write_bytes(b"pac")
            target_entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=temp_path / "0.pamt",
                paz_file=temp_path / "0.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPreviewRebuiltAsset"))
            tab.open_mesh_session(
                build_synthetic_mesh(),
                session_id="preview-rebuilt-asset",
                mode="edit",
                target_entry=target_entry,
            )
            report = MeshRebuildReport(
                mesh_format="pac",
                source_asset_hash="a" * 64,
                rebuilt_asset_hash="b" * 64,
                source_size=3,
                rebuilt_size=3,
                parse_confidence="exact",
                validation_status="passed",
                byte_identical=True,
                changed_byte_ranges=(),
                output_path=str(rebuilt_path),
            )
            tab.standalone_last_rebuild_report = report
            tab.standalone_last_rebuilt_asset_path = rebuilt_path
            tab.standalone_workspace.update_rebuild_report(report)
            emitted: list[tuple[object, object]] = []
            tab.preview_rebuilt_asset_requested.connect(lambda entry, path: emitted.append((entry, path)))
            packaged: list[tuple[object, object]] = []
            tab.package_rebuilt_asset_requested.connect(lambda entry, path: packaged.append((entry, path)))
            button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPreviewRebuiltAssetButton")
            package_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPackageRebuiltAssetButton")
            assert button is not None
            assert package_button is not None

            button.click()
            package_button.click()

            self.assertEqual([(target_entry, rebuilt_path)], emitted)
            self.assertEqual([(target_entry, rebuilt_path)], packaged)
            app.processEvents()
            tab.deleteLater()

    def test_mesh_editor_workspace_uv_canvas_region_signal_selects_uv_vertices(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorUvCanvasSelect"))

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-uv-region-select", mode="edit")

        uv_canvas = tab.standalone_workspace.findChild(QFrame, "MeshEditorUVCanvas")
        assert uv_canvas is not None
        uv_canvas.region_selected.emit((0.0, 0.0), (0.1, 1.0), "replace")

        assert tab.standalone_controller is not None
        selection = tab.standalone_controller.session_view().selection
        self.assertEqual({0: {0, 2}}, selection.vertex_map())
        self.assertEqual(1, uv_canvas.property("uvSelectedIslandCount"))
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_uv_canvas_lasso_signal_selects_uv_vertices(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorUvCanvasLasso"))

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-uv-lasso-select", mode="edit")

        uv_canvas = tab.standalone_workspace.findChild(QFrame, "MeshEditorUVCanvas")
        assert uv_canvas is not None
        uv_canvas.lasso_selected.emit(((-0.1, -0.1), (0.2, -0.1), (0.2, 1.1), (-0.1, 1.1)), "replace")

        assert tab.standalone_controller is not None
        selection = tab.standalone_controller.session_view().selection
        self.assertEqual({0: {0, 2}}, selection.vertex_map())
        self.assertEqual(1, uv_canvas.property("uvSelectedIslandCount"))
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_uv_panel_exposes_actions_and_selects_island_rows(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorUvPanelActions"))

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-uv-panel-actions", mode="edit")

        workspace = tab.standalone_workspace
        summary = workspace.findChild(QLabel, "MeshEditorUVSummaryLabel")
        select_all = workspace.findChild(QToolButton, "MeshEditorUVSelectAllButton")
        flip_u = workspace.findChild(QToolButton, "MeshEditorUVAction_uv_flip_u")
        pack = workspace.findChild(QToolButton, "MeshEditorUVAction_uv_pack")
        auto_uv = workspace.findChild(QToolButton, "MeshEditorUVAction_uv_auto_unwrap")
        uv_tree = workspace.findChild(QTreeWidget, "MeshEditorUVPanel")
        assert summary is not None
        assert select_all is not None
        assert flip_u is not None
        assert pack is not None
        assert auto_uv is not None
        assert uv_tree is not None
        self.assertIn("UV:", summary.text())
        self.assertFalse(flip_u.isEnabled())
        self.assertFalse(pack.isEnabled())
        self.assertFalse(auto_uv.isEnabled())

        island = next(
            uv_tree.topLevelItem(index)
            for index in range(uv_tree.topLevelItemCount())
            if "Island" in uv_tree.topLevelItem(index).text(0)
        )
        uv_tree.itemClicked.emit(island, 0)

        assert tab.standalone_controller is not None
        self.assertFalse(tab.standalone_controller.session_view().selection.is_empty())
        self.assertTrue(flip_u.isEnabled())
        previous_revision = tab.standalone_controller.session_view().revision
        flip_u.click()
        self.assertTrue(_wait_for(app, lambda: tab.standalone_controller is not None and tab.standalone_controller.session_view().revision > previous_revision))
        self.assertGreater(tab.standalone_controller.session_view().revision, previous_revision)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_auto_uv_dispatches_native_allow_flag_without_preflight(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorAutoUvDispatch"))
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-auto-uv-accept", mode="edit")
        assert tab.standalone_controller is not None
        tab.standalone_controller.select(source_indices=(0,))
        tab.update_editor_session_state(
            tab.standalone_controller.session_view(),
            active_selection_mode=tab.standalone_controller.active_selection_mode,
        )

        auto_uv = tab.standalone_workspace.findChild(QToolButton, "MeshEditorUVAction_uv_auto_unwrap")
        assert auto_uv is not None
        dispatched: list[object] = []

        with patch("cdmw.ui.mesh_editor.tab.QMessageBox.question", side_effect=AssertionError("Auto UV preflight prompt")):
            with patch.object(tab, "_start_standalone_action_worker", side_effect=lambda action, **_kwargs: dispatched.append(action) or True):
                with patch.object(tab.standalone_controller, "working_mesh", side_effect=AssertionError("Auto UV preflight hydrated mesh")):
                    auto_uv.click()

        self.assertEqual(1, len(dispatched))
        params = dict(tuple(getattr(dispatched[0], "params", ()) or ()))
        self.assertTrue(params.get("auto_uv"))
        self.assertTrue(params.get("allow_topology_change"))
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_right_panels_render_part_material_summary(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPartSummary"))
        mesh = build_synthetic_mesh()
        part = mesh.submeshes[0]
        setattr(part, "cdmw_target_material_slot_index", 7)
        setattr(part, "cdmw_source_texture_set_key", "harness_set")

        tab.open_mesh_session(mesh, session_id="standalone-part-summary", mode="edit")
        assert tab.standalone_controller is not None
        tab.standalone_controller.select(source_indices=(0,))
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)

        outliner = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        material = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorMaterialPanel")
        uv = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorUVPanel")
        uv_canvas = tab.standalone_workspace.findChild(QFrame, "MeshEditorUVCanvas")
        assert outliner is not None
        assert material is not None
        assert uv is not None
        assert uv_canvas is not None
        self.assertEqual("*0: harness_quad", outliner.topLevelItem(0).text(0))
        self.assertEqual("2", outliner.topLevelItem(0).text(1))
        self.assertIn("harness_material", material.topLevelItem(0).text(0))
        self.assertIn("harness.dds", material.topLevelItem(0).text(1))
        self.assertEqual("7", material.topLevelItem(0).text(2))
        self.assertIn("UV complete", uv.topLevelItem(0).text(1))
        self.assertIn("tangent missing", uv.topLevelItem(0).text(1))
        uv_rows = [(uv.topLevelItem(index).text(0), uv.topLevelItem(index).text(1)) for index in range(uv.topLevelItemCount())]
        self.assertTrue(any(label.startswith("*Island 0") and "harness.dds" in value for label, value in uv_rows))
        self.assertTrue(any("U 0.000-1.000" in value and "V 0.000-1.000" in value for _label, value in uv_rows))
        self.assertEqual(1, uv_canvas.property("uvIslandCount"))
        self.assertEqual(1, uv_canvas.property("uvSelectedIslandCount"))
        self.assertEqual("harness.dds", uv_canvas.property("uvTextureNames"))
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_skeleton_panel_reflects_skinning_summary(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorSkeletonPanel"))
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (1, 2), (2,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.6, 0.4), (0.75,)]
        mesh.has_bones = True

        tab.open_mesh_session(mesh, session_id="standalone-skeleton-summary", mode="edit")
        assert tab.standalone_controller is not None
        tab.standalone_controller.select(source_indices=(0,), vertices_by_submesh={0: (2,)})
        tab.standalone_controller.working_mesh(clone=False).submeshes[0].bone_indices[2] = ()
        tab.standalone_controller.working_mesh(clone=False).submeshes[0].bone_weights[2] = ()
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)

        skeleton = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorSkeletonPanel")
        assert skeleton is not None
        rows = [(skeleton.topLevelItem(index).text(0), skeleton.topLevelItem(index).text(1)) for index in range(skeleton.topLevelItemCount())]
        self.assertTrue(any(label == "Summary" and "missing metadata" in value for label, value in rows))
        self.assertTrue(any(label == "Validation" and "1 unnormalized" in value for label, value in rows))
        self.assertTrue(any(label == "*0: harness_quad" and "3 bones" in value for label, value in rows))

        tab.standalone_controller.attach_skeleton(
            Skeleton(
                path="character/model/body.pab",
                bones=[
                    Bone(index=0, name="Root", parent_index=-1, position=(0.0, 0.0, 0.0)),
                    Bone(index=1, name="Spine", parent_index=0, position=(0.0, 1.0, 0.0)),
                ],
                bone_count=2,
                parser_mode="fixed",
            ),
            skeleton_descriptor_source="character/prefab/body.prefabdata_xml",
            skeleton_variation_source="character/binary/skeletonvariation/body.pabc",
            animation_constraint_source="character/model/body.papr",
            animation_constraint_evidence={
                "constraint_evidence_status": "read_only_constraint_string_evidence",
                "constraint_string_evidence": 297,
                "constraint_record_candidates": 64,
                "constraint_record_candidate_rows": (
                    {
                        "offset": 4096,
                        "constraint_type": "driver_expression_candidate",
                        "target_bone": "Spine:1:2",
                        "helper_bone": "Root",
                        "parent_bone": "P_Root",
                        "expression": "Local_Euler_Z*3+30.5",
                        "expression_offset": 4096,
                        "target_bone_offset": 4032,
                        "target_bone_delta": 64,
                        "helper_bone_offset": 4048,
                        "helper_bone_delta": 48,
                        "parent_bone_offset": 4064,
                        "parent_bone_delta": 32,
                        "field_confidence": "proven_readable_strings",
                        "field_offset_confidence": "proven_decoded_string_offsets",
                        "record_span_start": 4032,
                        "record_span_end": 4120,
                        "record_span_size": 88,
                        "record_span_field_count": 4,
                        "record_field_sequence": ("target", "helper", "parent", "expression"),
                        "record_field_sequence_confidence": "proven_decoded_string_offset_order",
                        "record_gap_status": "binary_like_interfield_gap_bytes_unbound",
                        "record_gap_classes": ("binary_gap", "binary_gap", "binary_gap"),
                        "record_gap_class_counts": {"binary_gap": 3},
                        "record_gap_count": 3,
                        "record_gap_total_size": 18,
                        "record_gap_max_size": 6,
                        "record_gap_confidence": "observed_between_decoded_string_offsets",
                        "record_gap_scalar_status": "unbound_interfield_scalar_candidates",
                        "record_gap_scalar_kind_counts": {"f32_unit_candidate": 2, "u32_u8_candidate": 1},
                        "record_gap_aligned_word_count": 6,
                        "record_gap_scalar_candidate_count": 3,
                        "record_gap_scalar_confidence": "unbound_aligned_interfield_gap_scan",
                        "record_gap_numeric_match_status": "unbound_scalar_numeric_constant_matches",
                        "record_gap_numeric_match_role_counts": {"channel_coefficient": 1, "additive_offset": 1},
                        "record_gap_numeric_match_scalar_kind_counts": {"f32_small_candidate": 1, "f32_angle_candidate": 1},
                        "record_gap_numeric_match_storage_counts": {"f32": 2},
                        "record_gap_numeric_match_pair_counts": {"target>expression": 2},
                        "record_gap_numeric_match_value_confidence_counts": {
                            "approx_float32_numeric_value_match_layout_unproven": 1,
                            "exact_float32_numeric_value_match_layout_unproven": 1,
                        },
                        "record_gap_numeric_match_signature_counts": {
                            (
                                "role=channel_coefficient|pair=target>expression|storage=f32|"
                                "scalar=f32_small_candidate|"
                                "value=approx_float32_numeric_value_match_layout_unproven|"
                                "prev=0|next=8"
                            ): 1,
                            (
                                "role=additive_offset|pair=target>expression|storage=f32|"
                                "scalar=f32_angle_candidate|"
                                "value=exact_float32_numeric_value_match_layout_unproven|"
                                "prev=4|next=12"
                            ): 1,
                        },
                        "record_gap_numeric_match_candidate_relative_signature_counts": {
                            (
                                "role=channel_coefficient|pair=target>expression|storage=f32|"
                                "scalar=f32_small_candidate|"
                                "value=approx_float32_numeric_value_match_layout_unproven|"
                                "prev=0|next=8|rel=-16"
                            ): 1,
                            (
                                "role=additive_offset|pair=target>expression|storage=f32|"
                                "scalar=f32_angle_candidate|"
                                "value=exact_float32_numeric_value_match_layout_unproven|"
                                "prev=4|next=12|rel=-12"
                            ): 1,
                        },
                        "record_gap_numeric_match_previous_delta_counts": {"0": 1, "4": 1},
                        "record_gap_numeric_match_next_delta_counts": {"8": 1, "12": 1},
                        "record_gap_numeric_match_candidate_relative_offset_counts": {"-16": 1, "-12": 1},
                        "record_gap_numeric_match_count": 2,
                        "record_gap_numeric_match_min_previous_delta": 0,
                        "record_gap_numeric_match_max_previous_delta": 4,
                        "record_gap_numeric_match_min_next_delta": 8,
                        "record_gap_numeric_match_max_next_delta": 12,
                        "record_gap_numeric_match_min_candidate_relative_offset": -16,
                        "record_gap_numeric_match_max_candidate_relative_offset": -12,
                        "record_gap_numeric_match_offset_confidence": "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven",
                        "record_gap_numeric_match_candidate_relative_offset_confidence": "observed_relative_to_inferred_candidate_offset_value_layout_unproven",
                        "record_gap_numeric_match_confidence": "exact_numeric_text_vs_interfield_scalar_match_value_layout_unproven",
                        "record_layout_status": "nearby_string_span_only_value_layout_unproven",
                        "expression_channels": ("Local_Euler_Z",),
                        "expression_channel_confidence": "proven",
                        "limit_operators": (),
                        "limit_operator_confidence": "unknown",
                        "expression_numeric_values": ("3", "30.5"),
                        "expression_numeric_value_confidence": "proven",
                        "expression_numeric_roles": ("channel_coefficient", "additive_offset"),
                        "expression_numeric_role_confidence": "inferred_readable_expression_syntax",
                        "expression_shape": "linear_channel_transform_candidate",
                        "expression_syntax_signature": (
                            "shape=linear_channel_transform_candidate|channels=Local_Euler_Z|"
                            "limits=none|numeric_roles=channel_coefficient>additive_offset"
                        ),
                        "expression_shape_confidence": "inferred_readable_expression_syntax",
                        "expression_shape_status": "solver_semantics_unknown",
                        "expression_semantics_confidence": "unknown",
                        "record_confidence": "inferred_nearby_string_order",
                        "solver_status": "blocked_record_layout_unproven",
                    },
                ),
                "constraint_expression_evidence": {
                    "status": "readable_expression_tokens_solver_semantics_unknown",
                    "token_confidence": "proven",
                    "semantics_confidence": "unknown",
                    "expression_role_counts": {"driver_expression": 1},
                    "shape_counts": {"linear_channel_transform_candidate": 1},
                    "channel_counts": {"Local_Euler_Z": 1},
                    "limit_operator_counts": {},
                    "numeric_role_counts": {"channel_coefficient": 1, "additive_offset": 1},
                    "syntax_signature_counts": {
                        (
                            "role=driver_expression|shape=linear_channel_transform_candidate|"
                            "channels=Local_Euler_Z|limits=none|"
                            "numeric_roles=channel_coefficient>additive_offset"
                        ): 1,
                    },
                    "numeric_value_count": 2,
                },
                "constraint_offset_evidence": {
                    "status": "readable_string_offsets_candidate_record_map",
                    "offset_confidence": "proven",
                    "record_confidence": "inferred_nearby_string_order",
                    "target_offset_count": 1,
                    "helper_offset_count": 1,
                    "parent_offset_count": 1,
                },
                "constraint_role_counts": {
                    "bone_reference": 160,
                    "helper_bone_reference": 47,
                    "driver_expression": 51,
                },
                "constraint_related_physics": 1,
                "constraint_solving_supported": False,
            },
            socket_source="character/model/body.pab.sockets.xml",
        )
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)
        rows = [(skeleton.topLevelItem(index).text(0), skeleton.topLevelItem(index).text(1)) for index in range(skeleton.topLevelItemCount())]
        self.assertTrue(any(label == "Bones" and "2 bones" in value for label, value in rows))
        self.assertTrue(any(label.strip() == "1: Spine" and "parent Root" in value for label, value in rows))
        self.assertTrue(any(label == "Resolver" and "body.pabc" in value and "body.prefabdata_xml" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Evidence" and "297 strings" in value and "64 record candidates" in value and "solver blocked" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Families" and "driver_expression_candidate=1" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Family: driver_expression_candidate" and "candidates=1" in value and "solver ready=0" in value and "target bound=1" in value and "helper bound=1" in value and "parent bound=1" in value and "record layout unproven=1" in value and "expression semantics unknown=1" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Bone Matches" and "1 candidate rows" in value and "target suffix_base_name=1" in value and "helper exact_name=1" in value and "parent prefix_base_name=1" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Expressions" and "channel Local_Euler_Z=1" in value and "shape linear_channel_transform_candidate=1" in value and "numeric role channel_coefficient=1" in value and "syntax signatures 1 unique" in value and "semantics unknown" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Field Offsets" and "target=1" in value and "helper=1" in value and "parent=1" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Numeric Matches" and "2 unbound text/scalar numeric matches" in value and "unbound_scalar_numeric_constant_matches=1" in value and "roles additive_offset=1" in value and "channel_coefficient=1" in value and "storage f32=2" in value and "pairs target>expression=2" in value and "value confidence approx_float32_numeric_value_match_layout_unproven=1" in value and "exact_float32_numeric_value_match_layout_unproven=1" in value and "families driver_expression_candidate=2" in value and "family rows driver_expression_candidate=1" in value and "family roles driver_expression_candidate: additive_offset=1" in value and "family pairs driver_expression_candidate: target>expression=2" in value and "family value confidence driver_expression_candidate: approx_float32_numeric_value_match_layout_unproven=1" in value and "signatures 2 unique" in value and "rel signatures 2 unique" in value and "prev deltas 0=1, 4=1 (range 0-4)" in value and "next deltas 8=1, 12=1 (range 8-12)" in value and "candidate rel offsets -16=1, -12=1 (range -16--12)" in value and "observed_relative_to_decoded_string_gap_boundaries_value_layout_unproven" in value and "observed_relative_to_inferred_candidate_offset_value_layout_unproven" in value and "value layout unproven" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Solver Readiness" and "solver ready=0" in value and "target bound=1" in value and "record layout unproven=1" in value and "expression semantics unknown=1" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint Candidate: 0x1000" and "disabled" in value and "target Spine:1:2 (#1 suffix_base_name)" in value and "helper Root (#0 exact_name)" in value and "parent P_Root (#0 prefix_base_name)" in value and "channels proven: Local_Euler_Z" in value and "numeric constants=2 proven" in value and "numeric roles inferred_readable_expression_syntax: additive_offset=1, channel_coefficient=1" in value and "shape inferred_readable_expression_syntax: linear_channel_transform_candidate" in value and "semantics unknown" in value and "fields proven_decoded_string_offsets" in value and "expr@0x1000" in value and "target@0xFC0(+64)" in value and "span 0xFC0-0x1018" in value and "order target>helper>parent>expression" in value and "layout nearby_string_span_only_value_layout_unproven" in value and "gaps binary_like_interfield_gap_bytes_unbound" in value and "binary_gap=3" in value and "max=6" in value and "scalars unbound_interfield_scalar_candidates" in value and "f32_unit_candidate=2" in value and "u32_u8_candidate=1" in value and "count=3" in value and "numeric matches unbound_scalar_numeric_constant_matches" in value and "additive_offset=1" in value and "channel_coefficient=1" in value and "f32=2" in value and "pairs target>expression=2" in value and "value confidence approx_float32_numeric_value_match_layout_unproven=1" in value and "exact_float32_numeric_value_match_layout_unproven=1" in value and "prev deltas 0=1, 4=1 (range 0-4)" in value and "next deltas 8=1, 12=1 (range 8-12)" in value for label, value in rows))
        self.assertTrue(any(label == "Constraint: bone_reference" and "160 readable" in value for label, value in rows))
        self.assertTrue(any(label == "Authoring: Pose preview" and "preview-only" in value for label, value in rows))
        self.assertTrue(any(label == "Authoring: PAPR constraints" and "blocked" in value for label, value in rows))
        self.assertTrue(any(label == "Animation" and "playback blocked" in value and "bone-track binding" in value for label, value in rows))

        pose_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPosePreviewButton")
        preview_skeleton_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPreviewSkeletonButton")
        preview_pose_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPreviewPoseButton")
        rig_pose_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorRigPosePreviewButton")
        rig_transfer_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorRigWeightTransferButton")
        rotate_x_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPoseRotateXButton")
        reset_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorPoseResetButton")
        weight_increase_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorWeightIncreaseButton")
        weight_transfer_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorWeightTransferButton")
        assert pose_button is not None
        assert preview_skeleton_button is not None
        assert preview_pose_button is not None
        assert rig_pose_button is not None
        assert rig_transfer_button is not None
        assert rotate_x_button is not None
        assert reset_button is not None
        assert weight_increase_button is not None
        assert weight_transfer_button is not None
        self.assertTrue(pose_button.isEnabled())
        self.assertTrue(preview_skeleton_button.isEnabled())
        self.assertTrue(preview_pose_button.isEnabled())
        self.assertTrue(rig_pose_button.isEnabled())
        self.assertTrue(rig_transfer_button.isEnabled())
        self.assertFalse(rotate_x_button.isEnabled())
        self.assertFalse(weight_increase_button.isEnabled())
        self.assertTrue(weight_transfer_button.isEnabled())
        panels = tab.standalone_workspace.findChild(QTabWidget, "MeshEditorRightPanels")
        assert panels is not None
        with patch.object(tab, "start_standalone_native_preview_async", return_value=True) as refresh:
            preview_skeleton_button.click()
        refresh.assert_called_once()
        self.assertEqual("Rig", panels.tabText(panels.currentIndex()))
        preview_pose_button.click()
        self.assertTrue(tab.standalone_controller.skeleton_summary().pose.enabled)
        self.assertTrue(pose_button.isChecked())
        self.assertTrue(rig_pose_button.isChecked())
        preview_pose_button.click()
        self.assertFalse(tab.standalone_controller.skeleton_summary().pose.enabled)
        tab.standalone_controller.select(source_indices=(0,))
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)
        self.assertTrue(weight_transfer_button.isEnabled())
        self.assertFalse(weight_increase_button.isEnabled())
        tab.standalone_controller.select(source_indices=(0,), vertices_by_submesh={0: (2,)})
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)
        spine_item = next(
            skeleton.topLevelItem(index)
            for index in range(skeleton.topLevelItemCount())
            if skeleton.topLevelItem(index).text(0).strip() == "1: Spine"
        )
        tab.standalone_workspace._skeleton_tree_item_clicked(spine_item, 0)
        self.assertTrue(rotate_x_button.isEnabled())
        self.assertTrue(weight_increase_button.isEnabled())
        self.assertTrue(weight_transfer_button.isEnabled())
        pose_button.click()
        rotate_x_button.click()
        weight_transfer_button.click()
        weight_increase_button.click()
        assert tab.standalone_controller is not None
        summary = tab.standalone_controller.skeleton_summary()
        pose = summary.pose
        self.assertTrue(pose.enabled)
        self.assertEqual(1, pose.selected_bone_index)
        self.assertEqual((15.0, 0.0, 0.0), pose.rotation_degrees)
        self.assertAlmostEqual(0.7, summary.selected_vertex_weights[0].selected_bone_weight)
        rows = [(skeleton.topLevelItem(index).text(0), skeleton.topLevelItem(index).text(1)) for index in range(skeleton.topLevelItemCount())]
        self.assertTrue(any(label == "Pose" and "rot 15.0, 0.0, 0.0" in value for label, value in rows))
        self.assertTrue(any(label == "Weights" and "1 selected vertices" in value for label, value in rows))
        self.assertTrue(any(label == "Weight 0:2" and "0.700" in value for label, value in rows))
        self.assertTrue(any(label.strip() == "*1: Spine" for label, _value in rows))
        reset_button.click()
        self.assertEqual((0.0, 0.0, 0.0), tab.standalone_controller.skeleton_summary().pose.rotation_degrees)

        animation_play_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorAnimationPlayButton")
        animation_step_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorAnimationStepButton")
        animation_loop_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorAnimationLoopButton")
        animation_speed_combo = tab.standalone_workspace.findChild(QComboBox, "MeshEditorAnimationSpeedCombo")
        animation_scrub_slider = tab.standalone_workspace.findChild(QSlider, "MeshEditorAnimationScrubSlider")
        assert animation_play_button is not None
        assert animation_step_button is not None
        assert animation_loop_button is not None
        assert animation_speed_combo is not None
        assert animation_scrub_slider is not None
        self.assertFalse(animation_play_button.isEnabled())
        tab.standalone_controller.attach_animation_clip(
            MeshAnimationClip(
                source="safe_spine_clip.paa.json",
                duration_seconds=1.0,
                tracks=(
                    MeshAnimationTrack(
                        bone_name="Spine",
                        rotation_keyframes=(
                            MeshAnimationKeyframe(0.0, (0.0, 0.0, 0.0)),
                            MeshAnimationKeyframe(1.0, (0.0, 0.0, 90.0)),
                        ),
                    ),
                ),
                sequence_segments=(
                    MeshAnimationSequenceSegment(
                        sequence_path="sequencer/binary__/unit_combo.paseqc",
                        clip_path="safe_spine_clip.paa.json",
                        lane_index=3,
                        start_seconds=0.0,
                        end_seconds=1.0,
                        status="paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
                    ),
                ),
                parser_mode="unit_safe_parser",
            )
        )
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)
        rows = [(skeleton.topLevelItem(index).text(0), skeleton.topLevelItem(index).text(1)) for index in range(skeleton.topLevelItemCount())]
        self.assertTrue(animation_play_button.isEnabled())
        self.assertTrue(animation_step_button.isEnabled())
        self.assertTrue(animation_loop_button.isEnabled())
        self.assertTrue(animation_speed_combo.isEnabled())
        self.assertTrue(animation_scrub_slider.isEnabled())
        self.assertTrue(any(label == "Authoring: Animation playback" and "preview-only" in value for label, value in rows))
        self.assertTrue(any(label == "Animation" and "playback ready" in value and "safe_spine_clip" in value for label, value in rows))
        self.assertTrue(any(label == "Animation" and "lane 3" in value for label, value in rows))
        self.assertTrue(any(label == "Animation" and "paseqc_lane_bound" in value for label, value in rows))
        animation_loop_button.click()
        self.assertFalse(tab.standalone_controller.skeleton_summary().animation_playback.loop)
        animation_speed_combo.setCurrentIndex(animation_speed_combo.findText("2x"))
        self.assertEqual(2.0, tab.standalone_controller.skeleton_summary().animation_playback.playback_speed)
        animation_scrub_slider.setValue(250)
        self.assertAlmostEqual(0.25, tab.standalone_controller.skeleton_summary().animation_playback.time_seconds)
        animation_step_button.click()
        stepped = tab.standalone_controller.skeleton_summary().animation_playback
        self.assertTrue(stepped.enabled)
        self.assertGreater(stepped.time_seconds, 0.0)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_passes_source_skeleton_to_weight_transfer(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorSourceSkeletonTransfer"))
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (1,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.25, 0.75), (1.0,)]
        mesh.has_bones = True
        source_skeleton = Skeleton(
            bones=[Bone(index=0, name="Root"), Bone(index=1, name="Spine")],
            bone_count=2,
        )
        target_skeleton = Skeleton(
            bones=[Bone(index=4, name="Spine"), Bone(index=9, name="Root")],
            bone_count=2,
        )

        tab.open_mesh_session(
            mesh,
            session_id="standalone-source-skeleton-transfer",
            mode="edit",
            source_skeleton=source_skeleton,
        )
        assert tab.standalone_controller is not None
        working = tab.standalone_controller.working_mesh(clone=False)
        working.submeshes[0].bone_indices = [(), (), (), ()]
        working.submeshes[0].bone_weights = [(), (), (), ()]
        tab.standalone_controller.attach_skeleton(target_skeleton)
        tab.standalone_controller.select(source_indices=(0,), vertices_by_submesh={0: (2,)})
        tab.update_editor_session_state(
            tab.standalone_controller.session_view(),
            active_selection_mode=tab.standalone_controller.active_selection_mode,
        )

        weight_transfer_button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorWeightTransferButton")
        assert weight_transfer_button is not None
        self.assertTrue(weight_transfer_button.isEnabled())
        weight_transfer_button.click()

        self.assertEqual((4, 9), working.submeshes[0].bone_indices[2])
        self.assertEqual((0.75, 0.25), working.submeshes[0].bone_weights[2])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_skeleton_pose_request_refreshes_visible_native_preview(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorSkeletonPoseNativeRefresh"))
        mesh = build_synthetic_mesh()
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        mesh.has_bones = True
        tab.open_mesh_session(mesh, session_id="standalone-pose-native-refresh", mode="edit")
        assert tab.standalone_controller is not None
        tab.standalone_controller.attach_skeleton(Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1))
        tab.standalone_preview_stack.setCurrentWidget(tab.standalone_native_host_frame)

        with patch.object(tab, "start_standalone_native_preview_async", return_value=True) as refresh:
            ok = tab._handle_skeleton_pose_request("select_bone", 0)

        self.assertTrue(ok)
        refresh.assert_called_once_with(reset_view=False)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_file_session_does_not_auto_load_sibling_source_skeleton(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorSiblingSourceSkeleton"))
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "direct.pam"
            skeleton_path = Path(temp_dir) / "direct.pab"
            mesh_path.write_bytes(b"mesh-bytes")
            skeleton_path.write_bytes(_pab_payload((("Root", -1), ("Spine", 0))))
            parsed = build_synthetic_mesh("pam")
            parsed.submeshes[0].bone_indices = [(0,), (1,), (0, 1), (1,)]
            parsed.submeshes[0].bone_weights = [(1.0,), (1.0,), (0.25, 0.75), (1.0,)]
            parsed.has_bones = True

            with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed):
                tab.open_mesh_file_session(mesh_path, session_id="standalone-file-source-skeleton", mode="edit")

            assert tab.standalone_controller is not None
            self.assertIsNone(tab.standalone_source_skeleton)
            linked = tab.standalone_controller.skeleton_summary()
            self.assertFalse(linked.skeleton_linked)
            self.assertEqual("", linked.skeleton_source)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_open_texture_button_emits_texture_editor_binding(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            texture_path = Path(temp_dir) / "harness.dds"
            texture_path.write_bytes(b"dds")
            mesh = build_synthetic_mesh()
            mesh.submeshes[0].texture = str(texture_path)
            tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorOpenTexture"))
            emitted: list[tuple[str, object]] = []
            tab.open_texture_source_requested.connect(lambda path, binding: emitted.append((path, binding)))

            tab.open_mesh_session(mesh, session_id="standalone-open-texture", mode="edit")
            assert tab.standalone_controller is not None
            tab.standalone_controller.select(source_indices=(0,))
            tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)
            button = tab.standalone_workspace.findChild(QToolButton, "MeshEditorOpenTextureButton")
            assert button is not None
            button.click()

            self.assertEqual(str(texture_path.resolve()), emitted[0][0])
            binding = emitted[0][1]
            self.assertEqual("mesh_editor", getattr(binding, "launch_origin", ""))
            self.assertEqual(str(texture_path.resolve()), getattr(binding, "source_path", ""))
            self.assertEqual("mesh_material", getattr(binding, "texture_type", ""))
            app.processEvents()
            tab.deleteLater()

    def test_mesh_editor_resolves_archive_texture_source_by_basename(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            extracted = temp_path / "body.dds"
            extracted.write_bytes(b"dds")
            pamt_path = temp_path / "0.pamt"
            paz_path = temp_path / "0.paz"
            pamt_path.write_bytes(b"pamt")
            paz_path.write_bytes(b"paz")
            target_entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=pamt_path,
                paz_file=paz_path,
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            texture_entry = ArchiveEntry(
                path="character/model/body.dds",
                pamt_path=pamt_path,
                paz_file=paz_path,
                offset=1,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )

            result = resolve_mesh_texture_source(
                "body",
                target_entry=target_entry,
                entries_by_basename={"body.dds": [texture_entry]},
                ensure_source=lambda _entry, **_kwargs: (extracted, "test-cache"),
            )

            self.assertTrue(result.ok)
            self.assertEqual(extracted.resolve(), result.source_path)
            self.assertEqual(texture_entry, result.archive_entry)
            self.assertEqual("character/model/body.dds", result.archive_path)

    def test_mesh_editor_archive_texture_resolution_emits_texture_binding(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            source_path = Path(temp_dir) / "body.dds"
            source_path.write_bytes(b"dds")
            mesh = build_synthetic_mesh()
            mesh.submeshes[0].texture = "body.dds"
            tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorArchiveTextureBinding"))
            emitted: list[tuple[str, object]] = []
            tab.open_texture_source_requested.connect(lambda path, binding: emitted.append((path, binding)))
            try:
                tab.open_mesh_session(mesh, session_id="archive-texture-binding", mode="edit")
                assert tab.standalone_controller is not None
                tab.standalone_controller.select(source_indices=(0,))
                target = tab.standalone_controller.texture_edit_target()
                assert target is not None
                tab.standalone_texture_source_request_id = 7
                tab.standalone_texture_source_target = target

                tab._handle_archive_texture_source_resolved(
                    7,
                    MeshTextureSourceResolution(
                        source_path=source_path,
                        archive_path="character/model/body.dds",
                        status="archive",
                    ),
                )

                self.assertEqual(str(source_path.resolve()), emitted[0][0])
                binding = emitted[0][1]
                self.assertEqual("mesh_editor", getattr(binding, "launch_origin", ""))
                self.assertEqual("character/model/body.dds", getattr(binding, "archive_relative_path", ""))
                self.assertEqual("character/model/body.dds", getattr(binding, "relative_path", ""))
                self.assertEqual(str(source_path.resolve()), getattr(binding, "original_dds_path", ""))
            finally:
                tab.deleteLater()
        app.processEvents()

    def test_mesh_editor_applies_texture_editor_dds_ready_as_native_preview_override(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            source_path = temp_path / "source.dds"
            preview_path = temp_path / "preview.dds"
            source_path.write_bytes(b"dds source")
            preview_path.write_bytes(b"dds preview")
            mesh = build_synthetic_mesh()
            mesh.submeshes[0].texture = str(source_path)
            tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorTexturePreviewReady"))
            try:
                tab.open_mesh_session(mesh, session_id="texture-preview-ready", mode="edit")
                binding = TextureEditorSourceBinding(
                    launch_origin="mesh_editor",
                    source_identity_path=f"texture-preview-ready:0:{source_path}",
                    texture_type="mesh_material",
                )
                refresh_calls: list[dict[str, object]] = []
                with patch.object(
                    tab,
                    "start_standalone_native_preview_async",
                    side_effect=lambda *args, **kwargs: refresh_calls.append(dict(kwargs)) or True,
                ):
                    self.assertTrue(tab.apply_texture_editor_dds_preview(str(preview_path), binding))

                self.assertEqual({0: str(preview_path.resolve())}, tab.standalone_texture_preview_overrides)
                self.assertEqual([{"reset_view": False}], refresh_calls)
                assert tab.standalone_controller is not None
                self.assertEqual(str(source_path), tab.standalone_controller.working_mesh().submeshes[0].texture)

                package_dir = temp_path / "package"
                with patch("cdmw.ui.mesh_editor.tab.mesh_editor_write_native_preview_package", return_value=package_dir) as writer:
                    self.assertEqual(package_dir, tab.write_standalone_native_preview_package())
                preview_mesh = writer.call_args.args[0]
                self.assertEqual(str(preview_path.resolve()), preview_mesh.submeshes[0].texture)
                self.assertTrue(writer.call_args.kwargs["use_textures"])
            finally:
                tab.deleteLater()
        app.processEvents()

    def test_mesh_editor_sync_native_preview_uses_pose_payload_before_pose_snapshot(self) -> None:
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

    def test_mesh_editor_shell_wires_texture_open_request_to_texture_editor_bridge(self) -> None:
        source = Path("cdmw/ui/shell/tool_tabs.py").read_text(encoding="utf-8")
        self.assertIn("open_texture_source_requested.connect(self._open_source_in_texture_editor)", source)
        self.assertIn(
            "native_dds_ready.connect(lambda *args: self.mesh_editor_tab.apply_texture_editor_dds_result(*args))",
            source,
        )
        self.assertIn("resident_texture_patch_ready.connect", source)
        self.assertIn("apply_texture_editor_region_patch(patch)", source)
        self.assertIn("get_archive_texture_entries_by_normalized_path=", source)
        self.assertIn("get_archive_texture_entries_by_basename=", source)

    def test_mesh_editor_tab_standalone_session_routes_actions_to_native_host(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneHost"))
        host = _StandaloneNativeHost()
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        tab.set_native_preview_host(host)

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-host", mode="edit")
        assert tab.standalone_controller is not None
        self.assertTrue(tab.action_bar.isEnabled())
        self.assertTrue(tab.action_bar.isHidden())
        self.assertFalse(tab.modify_original_button.isEnabled())
        tab.standalone_controller.select(vertices_by_submesh={0: (0, 1)})
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)
        host.calls.clear()

        self.assertTrue(tab.action_bar.button_for_key("transform_rotate").isEnabled())
        tab.action_bar.button_for_key("transform_rotate").click()
        self.assertTrue(_wait_for(app, lambda: len(host.calls) >= 1 and not tab._standalone_action_worker_active()))

        self.assertEqual(["vertices"], [name for name, _payload in host.calls])
        self.assertEqual([0, 1], _i32_values(host.calls[0][1][0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertNotEqual((-0.75, -0.75, 0.0), tab.standalone_controller.working_mesh().submeshes[0].vertices[0])
        self.assertIn("Revision: 1", tab.standalone_status_label.text())
        self.assertEqual(("Mesh Editor action applied: Rotate.", False), messages[-1])
        self.assertTrue(tab.action_bar.button_for_key("undo").isEnabled())
        tab.action_bar.button_for_key("undo").click()
        self.assertTrue(_wait_for(app, lambda: len(host.calls) >= 3 and not tab._standalone_action_worker_active()))

        self.assertEqual(["vertices", "vertices", "selection"], [name for name, _payload in host.calls])
        self.assertEqual([0, 1], _i32_values(host.calls[1][1][0], "source_vertex_indices", "source_vertex_indices_binary"))
        self.assertEqual((-0.75, -0.75, 0.0), tab.standalone_controller.working_mesh().submeshes[0].vertices[0])
        self.assertIn("Revision: 2", tab.standalone_status_label.text())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_records_native_preview_update_metric(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneMetrics"))
        host = _StandaloneNativeHost()
        tab.set_native_preview_host(host)
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-metrics", mode="edit")
        tab.standalone_preview_stack.setCurrentWidget(tab.standalone_native_host_frame)
        host.calls.clear()
        result = MeshEditResult(
            action="brush",
            status="ok",
            revision=1,
            affected_submesh_indices=(0,),
            changed_vertices_by_submesh=((0, (0,)),),
            metrics={"cpp_ms": 1.25},
        )
        update = MeshEditorNativeUpdate(
            vertex_groups=(
                {
                    "source_submesh_index": 0,
                    "source_vertex_indices": [0],
                    "positions": [0.0, 0.0, 0.0],
                },
            ),
        )

        self.assertTrue(tab._finish_standalone_action_execution(MeshEditorActionExecution(result, update), action_text="Brush"))

        self.assertEqual(["vertices"], [name for name, _payload in host.calls])
        assert tab.standalone_last_action_result is not None
        self.assertEqual(1.25, tab.standalone_last_action_result.metrics["cpp_ms"])
        self.assertGreaterEqual(tab.standalone_last_action_result.metrics["d3d11_update_ms"], 0.0)
        self.assertNotIn("qt_preview_refresh_ms", tab.standalone_last_action_result.metrics)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_d3d11_update_failure_does_not_refresh_python_preview(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneNativeUpdateFailure"))
        host = _FailingStandaloneNativeHost()
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        tab.set_native_preview_host(host)
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-stale-native", mode="edit")
        tab.standalone_preview_stack.setCurrentWidget(tab.standalone_native_host_frame)
        host.calls.clear()
        update = MeshEditorNativeUpdate(vertex_groups=({"source_submesh_index": 0, "source_vertex_start": 0, "source_vertex_count": 1},))

        with patch.object(tab, "_refresh_standalone_preview", side_effect=AssertionError("python preview fallback")):
            self.assertFalse(tab._apply_standalone_native_update(update))

        self.assertEqual(["vertices"], [name for name, _payload in host.calls])
        self.assertIs(tab.standalone_native_host_frame, tab.standalone_preview_stack.currentWidget())
        self.assertIn("preview is stale", tab.standalone_status_label.text())
        self.assertEqual((tab.standalone_status_label.text(), True), messages[-1])
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_standalone_native_delta_without_native_host_does_not_refresh_python_preview(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneNoNativeFallback"))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-fallback", mode="edit")
        tab.set_native_preview_host(None)
        result = MeshEditResult(
            action="brush",
            status="ok",
            revision=1,
            changed_vertices_by_submesh=((0, (0,)),),
        )
        update = MeshEditorNativeUpdate(
            vertex_groups=(
                {
                    "preview_backend": "cdmw_mesh_core",
                    "source_submesh_index": 0,
                    "source_vertex_indices": [0],
                    "positions": [0.0, 0.0, 0.0],
                },
            ),
        )

        with patch.object(tab, "_refresh_standalone_preview", side_effect=AssertionError("python preview fallback")):
            self.assertFalse(tab._finish_standalone_action_execution(MeshEditorActionExecution(result, update), action_text="Brush"))

        self.assertIn("preview is stale", tab.standalone_status_label.text())
        self.assertEqual((tab.standalone_status_label.text(), True), messages[-1])
        self.assertIn("d3d11_update_failed_ms", tab.standalone_last_action_metrics)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_opens_standalone_mesh_file_session(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneFileSession"))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "direct.pam"
            mesh_path.write_bytes(b"mesh-bytes")
            parsed = build_synthetic_mesh("pam")
            parsed.path = str(mesh_path)

            with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed) as parser:
                view = tab.open_mesh_file_session(mesh_path, session_id="standalone-file", mode="edit")

            parser.assert_called_once_with(b"mesh-bytes", str(mesh_path))
            self.assertEqual("standalone-file", view.session_id)
            self.assertEqual("edit", view.mode)
            self.assertIs(tab.workspace_stack.currentWidget(), tab.standalone_workspace)
            self.assertIn("direct.pam", tab.target_label.text())
            self.assertEqual(("Mesh Editor loaded standalone mesh: direct.pam", False), messages[-1])
            self.assertTrue(tab.action_bar.isEnabled())
            self.assertFalse(tab.modify_original_button.isEnabled())
            self.assertTrue(tab.standalone_native_preview_button.isEnabled())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_file_session_load_worker_opens_service_session(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            mesh_path = Path(temp_dir) / "worker.pam"
            mesh_path.write_bytes(b"mesh-bytes")
            parsed = build_synthetic_mesh("pam")
            parsed.path = str(mesh_path)
            loaded: list[tuple[int, object, object, object]] = []
            errors: list[tuple[int, str]] = []
            finished: list[bool] = []
            worker = MeshFileSessionLoadWorker(4, mesh_path, session_id="worker-file", mode="edit")
            worker.loaded.connect(lambda request_id, service, view, mesh: loaded.append((request_id, service, view, mesh)))
            worker.error.connect(lambda request_id, message: errors.append((request_id, message)))
            worker.finished.connect(lambda: finished.append(True))

            with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed) as parser:
                worker.run()

            parser.assert_called_once_with(b"mesh-bytes", str(mesh_path))
            self.assertEqual([], errors)
            self.assertEqual([True], finished)
            self.assertEqual(1, len(loaded))
            request_id, service, view, mesh = loaded[0]
            self.assertEqual(4, request_id)
            self.assertIs(parsed, mesh)
            self.assertEqual("worker-file", view.session_id)
            self.assertEqual("edit", view.mode)
            self.assertEqual("edit", service.session_view("worker-file").mode)
        app.processEvents()

    def test_mesh_native_preview_package_worker_writes_package(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorNativePackageWorker"))
        try:
            tab.open_mesh_session(build_synthetic_mesh(), session_id="package-worker", mode="edit")
            assert tab.standalone_controller is not None
            mesh = tab.standalone_controller.working_mesh(clone=True)
            prepared_preview = tab.standalone_controller.native_preview_data()
            model_preview = ModelPreviewData(path=str(mesh.path or "mesh_editor.pac"), physics_overlay=SimpleNamespace(bones=(object(),)))
            prepare_calls: list[object] = []
            with tempfile.TemporaryDirectory() as temp_dir:
                output_root = Path(temp_dir) / "preview_package"
                loaded: list[tuple[int, object, float]] = []
                errors: list[tuple[int, str]] = []
                finished: list[bool] = []
                worker = MeshNativePreviewPackageWorker(
                    7,
                    mesh,
                    ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True),
                    prepare_native_preview=lambda received_mesh: prepare_calls.append(received_mesh) or prepared_preview,
                    output_root=output_root,
                    model_preview_data=model_preview,
                    use_textures=True,
                    high_quality_textures=True,
                )
                worker.completed.connect(lambda request_id, package_dir, elapsed_ms: loaded.append((request_id, package_dir, elapsed_ms)))
                worker.error.connect(lambda request_id, message: errors.append((request_id, message)))
                worker.finished.connect(lambda: finished.append(True))

                with patch("cdmw.workers.mesh_editor_workers.write_isolated_d3d11_preview_package", return_value=output_root) as writer:
                    worker.run()

                self.assertEqual([], errors)
                self.assertEqual([True], finished)
                self.assertEqual(1, len(loaded))
                self.assertEqual(7, loaded[0][0])
                self.assertEqual(output_root, Path(loaded[0][1]))
                self.assertEqual([mesh], prepare_calls)
                self.assertIs(model_preview, writer.call_args.args[0])
                self.assertIs(prepared_preview, writer.call_args.args[1])
                self.assertEqual(output_root, writer.call_args.kwargs["output_root"])
                self.assertTrue(writer.call_args.kwargs["use_textures"])
                self.assertTrue(writer.call_args.kwargs["high_quality_textures"])
        finally:
            tab.deleteLater()
        app.processEvents()

    def test_mesh_rebuild_report_worker_runs_service_report(self) -> None:
        app = QApplication.instance() or QApplication([])
        report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc",
            rebuilt_asset_hash="abc",
            source_size=8,
            rebuilt_size=8,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=True,
            changed_byte_ranges=(),
        )
        calls: list[str] = []
        completed: list[object] = []
        errors: list[tuple[int, str]] = []
        finished: list[bool] = []

        class FakeService:
            def rebuild_report(self, session_id: str) -> object:
                calls.append(session_id)
                return report

        worker = MeshRebuildReportWorker(17, FakeService(), "worker-report", action_text="rebuild report")  # type: ignore[arg-type]
        worker.completed.connect(lambda _request_id, result: completed.append(result))
        worker.error.connect(lambda request_id, message: errors.append((request_id, message)))
        worker.finished.connect(lambda: finished.append(True))

        worker.run()

        self.assertEqual(["worker-report"], calls)
        self.assertEqual([report], completed)
        self.assertEqual([], errors)
        self.assertEqual([True], finished)
        app.processEvents()

    def test_mesh_rebuild_report_worker_writes_asset_when_output_path_is_set(self) -> None:
        app = QApplication.instance() or QApplication([])
        report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc",
            rebuilt_asset_hash="def",
            source_size=8,
            rebuilt_size=7,
            parse_confidence="exact",
            validation_status="passed",
            byte_identical=False,
            changed_byte_ranges=((0, 1),),
            output_path="out.pac",
        )
        calls: list[tuple[str, Path]] = []
        completed: list[object] = []

        class FakeService:
            def rebuild_asset(self, session_id: str, output_path: Path) -> object:
                calls.append((session_id, output_path))
                return report

        worker = MeshRebuildReportWorker(
            19,
            FakeService(),  # type: ignore[arg-type]
            "worker-rebuild-asset",
            action_text="patched asset rebuild",
            output_path="out.pac",
        )
        worker.completed.connect(lambda _request_id, result: completed.append(result))

        worker.run()

        self.assertEqual([("worker-rebuild-asset", Path("out.pac"))], calls)
        self.assertEqual([report], completed)
        app.processEvents()

    def test_mesh_rebuild_report_worker_passes_developer_override(self) -> None:
        app = QApplication.instance() or QApplication([])
        report = MeshRebuildReport(
            mesh_format="pac",
            source_asset_hash="abc",
            rebuilt_asset_hash="def",
            source_size=8,
            rebuilt_size=7,
            parse_confidence="fallback_scan",
            validation_status="developer_override",
            byte_identical=False,
            changed_byte_ranges=((0, 1),),
            output_path="out.pac",
            developer_overrides=("developer_override=true",),
        )
        calls: list[tuple[str, Path, bool, str]] = []
        completed: list[object] = []

        class FakeService:
            def rebuild_asset(
                self,
                session_id: str,
                output_path: Path,
                *,
                developer_override: bool = False,
                developer_override_reason: str = "",
            ) -> object:
                calls.append((session_id, output_path, developer_override, developer_override_reason))
                return report

        worker = MeshRebuildReportWorker(
            20,
            FakeService(),  # type: ignore[arg-type]
            "worker-rebuild-override",
            action_text="patched asset rebuild",
            output_path="out.pac",
            developer_override=True,
            developer_override_reason="Forced rebuild for local testing",
        )
        worker.completed.connect(lambda _request_id, result: completed.append(result))

        worker.run()

        self.assertEqual(
            [("worker-rebuild-override", Path("out.pac"), True, "Forced rebuild for local testing")],
            calls,
        )
        self.assertEqual([report], completed)
        app.processEvents()

    def test_mesh_rebuild_report_worker_can_cancel_before_run(self) -> None:
        app = QApplication.instance() or QApplication([])
        completed: list[object] = []
        cancelled: list[tuple[int, str]] = []
        finished: list[bool] = []
        worker = MeshRebuildReportWorker(18, MeshService(), "worker-report", action_text="rebuild report")
        worker.completed.connect(lambda _request_id, result: completed.append(result))
        worker.cancelled.connect(lambda request_id, message: cancelled.append((request_id, message)))
        worker.finished.connect(lambda: finished.append(True))

        worker.stop()
        worker.run()

        self.assertEqual([], completed)
        self.assertEqual([(18, "Cancelled rebuild report.")], cancelled)
        self.assertEqual([True], finished)
        app.processEvents()

    def test_mesh_edit_command_worker_can_cancel_before_run(self) -> None:
        app = QApplication.instance() or QApplication([])
        completed: list[object] = []
        cancelled: list[tuple[int, str]] = []
        finished: list[bool] = []
        worker = MeshEditCommandWorker(
            13,
            MeshService(),
            "mesh-command-worker-cancel",
            MeshEditCommand("delete"),
            action_text="Delete",
        )
        worker.completed.connect(lambda _request_id, result: completed.append(result))
        worker.cancelled.connect(lambda request_id, message: cancelled.append((request_id, message)))
        worker.finished.connect(lambda: finished.append(True))

        worker.stop()
        worker.run()

        self.assertEqual([], completed)
        self.assertEqual([(13, "Cancelled Delete.")], cancelled)
        self.assertEqual([True], finished)
        app.processEvents()

    def test_mesh_edit_command_worker_applies_immutable_service_command(self) -> None:
        app = QApplication.instance() or QApplication([])
        completed: list[object] = []
        errors: list[tuple[int, str]] = []
        calls: list[tuple[str, MeshEditCommand]] = []

        class FakeService:
            def apply_command(self, session_id: str, command: MeshEditCommand) -> MeshEditResult:
                calls.append((session_id, command))
                return MeshEditResult(action=command.action, status="ok", revision=7)

        original = MeshEditCommand("delete", params={"remove_orphans": True})
        worker = MeshEditCommandWorker(
            14,
            FakeService(),  # type: ignore[arg-type]
            "mesh-command-worker-apply",
            original,
            action_text="Delete",
        )
        worker.completed.connect(lambda _request_id, result: completed.append(result))
        worker.error.connect(lambda request_id, message: errors.append((request_id, message)))

        worker.run()

        self.assertEqual([], errors)
        self.assertEqual(1, len(completed))
        self.assertEqual("mesh-command-worker-apply", calls[0][0])
        applied = calls[0][1]
        self.assertEqual("delete", applied.action)
        self.assertIsNot(applied, original)
        self.assertNotIn("stop_event", original.params)
        self.assertIn("stop_event", applied.params)
        app.processEvents()

    def test_mesh_edit_command_worker_rejects_legacy_display_cleanup(self) -> None:
        app = QApplication.instance() or QApplication([])
        completed: list[object] = []
        errors: list[tuple[int, str]] = []

        class FakeService:
            def apply_command(self, _session_id: str, _command: MeshEditCommand) -> MeshEditResult:
                raise AssertionError("legacy cleanup should not reach service")

        worker = MeshEditCommandWorker(
            15,
            FakeService(),  # type: ignore[arg-type]
            "mesh-command-worker-legacy-cleanup",
            MeshEditCommand("triangulate_display"),
            action_text="Triangulate Display",
        )
        worker.completed.connect(lambda _request_id, result: completed.append(result))
        worker.error.connect(lambda request_id, message: errors.append((request_id, message)))

        worker.run()

        self.assertEqual([], completed)
        self.assertEqual(1, len(errors))
        self.assertEqual(15, errors[0][0])
        self.assertIn("legacy display-shape cleanup", errors[0][1])
        app.processEvents()

    def test_mesh_editor_tab_runs_standalone_topology_action_in_worker_by_default(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneTopologyWorker"))
        controller = MeshEditorController()
        mesh = build_synthetic_mesh("pam")
        controller.open_mesh(mesh, session_id="standalone-large-topology", mode="edit")
        controller.select(source_indices=(0,))
        tab.standalone_controller = controller
        tab.standalone_mesh_label = "large.pam"
        tab.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)
        action = mesh_editor_actions_by_key()["delete"]
        try:
            self.assertTrue(tab._should_run_standalone_action_worker(action, controller))
            with (
                patch.object(controller, "run_editor_action", side_effect=AssertionError("sync topology edit")),
                patch.object(tab, "_start_standalone_action_worker", return_value=True) as starter,
            ):
                self.assertTrue(tab._run_standalone_action(action))
            starter.assert_called_once()
        finally:
            tab.deleteLater()
        app.processEvents()

    def test_mesh_editor_tab_opens_standalone_mesh_file_session_async(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneFileSessionAsync"))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        try:
            with tempfile.TemporaryDirectory() as temp_dir:
                mesh_path = Path(temp_dir) / "async.pam"
                mesh_path.write_bytes(b"mesh-bytes")
                parsed = build_synthetic_mesh("pam")
                parsed.path = str(mesh_path)

                with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed) as parser:
                    request_id = tab.open_mesh_file_session_async(mesh_path, session_id="async-file", mode="edit")
                    self.assertGreater(request_id, 0)
                    self.assertIsNotNone(tab.standalone_file_load_thread)
                    self.assertFalse(tab.action_bar.isEnabled())
                    self.assertTrue(_wait_for(app, lambda: tab.has_active_standalone_session()))
                    self.assertTrue(_wait_for(app, lambda: tab.standalone_file_load_thread is None))

                parser.assert_called_once_with(b"mesh-bytes", str(mesh_path))
                assert tab.standalone_controller is not None
                self.assertEqual("async-file", tab.standalone_controller.active_session_id)
                self.assertIs(tab.workspace_stack.currentWidget(), tab.standalone_workspace)
                self.assertIn("async.pam", tab.target_label.text())
                self.assertEqual(("Mesh Editor loaded standalone mesh: async.pam", False), messages[-1])
                self.assertTrue(tab.action_bar.isEnabled())
                self.assertTrue(tab.standalone_native_preview_button.isEnabled())
        finally:
            tab.request_shutdown()
            app.processEvents()
            tab.deleteLater()

    def test_mesh_editor_tab_loads_prepared_standalone_native_package(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneNativePackage"))
        host = _StandaloneNativeHost()
        tab.set_native_preview_host(host)
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-native-package", mode="edit")
        host.calls.clear()

        ok = tab.load_standalone_native_preview_package(
            Path("C:/tmp/mesh-editor-package"),
            Path("C:/tmp/mesh-editor-status.json"),
            reset_view=False,
        )

        self.assertTrue(ok)
        self.assertIn(
            ("load_package", (Path("C:/tmp/mesh-editor-package"), Path("C:/tmp/mesh-editor-status.json"), False)),
            host.calls,
        )
        self.assertEqual(Path("C:/tmp/mesh-editor-package"), tab.standalone_native_package_dir)
        self.assertIn("Native D3D11 preview loading:", tab.standalone_status_label.text())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_starts_and_stops_standalone_native_process(self) -> None:
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
            package_dir = output_root / "preview_package"
            package_dir.mkdir()
            status_file = package_dir / "host_status.json"
            status_file.write_text("stale", encoding="utf-8")
            _FakeProcess.instances.clear()
            with (
                patch("cdmw.ui.mesh_editor.tab.mesh_editor_write_native_preview_package", return_value=package_dir) as writer,
                patch(
                    "cdmw.ui.mesh_editor.tab.mesh_editor_native_preview_command",
                    return_value=(
                        "C:/native/cdmw-d3d11-preview.exe",
                        ["--preview-package", str(package_dir), "--status-file", str(status_file)],
                    ),
                ) as command,
                patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess),
            ):
                ok = tab.start_standalone_native_preview(output_root=output_root)

                self.assertTrue(ok)
                self.assertFalse(status_file.exists())
                self.assertEqual(output_root, writer.call_args.kwargs["output_root"])
                self.assertEqual(2, len(writer.call_args.kwargs["skeleton_overlay"].bones))
                self.assertIs(tab.standalone_native_host_frame, command.call_args.kwargs["host_widget"])
                process = _FakeProcess.instances[-1]
                self.assertIs(process, tab.standalone_native_process)
                self.assertEqual("C:/native/cdmw-d3d11-preview.exe", process.program)
                self.assertIn("--preview-package", process.arguments)
                self.assertEqual(str(Path(__file__).resolve().parents[1]), process.working_directory)
                self.assertIs(tab.standalone_native_host_frame, tab.standalone_preview_stack.currentWidget())

                tab.close_standalone_session()

                self.assertTrue(process.terminated)
                self.assertTrue(process.deleted)
                self.assertIsNone(tab.standalone_native_process)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_native_preview_button_starts_standalone_process(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneNativeButton"))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        self.assertFalse(tab.standalone_native_preview_button.isEnabled())
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-native-button", mode="edit")
        self.assertTrue(tab.standalone_native_preview_button.isEnabled())

        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "preview_package"
            package_dir.mkdir()
            status_file = package_dir / "host_status.json"
            status_file.write_text("stale", encoding="utf-8")
            _FakeProcess.instances.clear()
            with (
                patch("cdmw.workers.mesh_editor_workers.write_isolated_d3d11_preview_package", return_value=package_dir) as writer,
                patch(
                    "cdmw.ui.mesh_editor.tab.mesh_editor_native_preview_command",
                    return_value=(
                        "C:/native/cdmw-d3d11-preview.exe",
                        ["--preview-package", str(package_dir), "--status-file", str(status_file)],
                    ),
                ),
                patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess),
            ):
                with patch(
                    "cdmw.ui.mesh_editor.controller.MeshEditorController.native_preview_data",
                    side_effect=AssertionError("native_preview_data stayed off UI button path"),
                ):
                    tab.standalone_native_preview_button.click()

                self.assertTrue(_wait_for(app, lambda: bool(_FakeProcess.instances)))
                self.assertIsNone(writer.call_args.kwargs["output_root"])
                self.assertEqual("C:/native/cdmw-d3d11-preview.exe", _FakeProcess.instances[-1].program)
                self.assertFalse(status_file.exists())
                self.assertTrue(any(message.startswith("Native D3D11 preview started after package build") for message, error in messages if not error))
                self.assertIs(tab.standalone_native_host_frame, tab.standalone_preview_stack.currentWidget())
        tab.close_standalone_session()
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_dotnet_experiment_button_requires_configured_executable(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorDotNetExperimentButton")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        button = tab.standalone_workspace.findChild(QPushButton, "MeshEditorDotNetExperimentButton")

        self.assertIsNotNone(button)
        assert button is not None
        self.assertFalse(button.isEnabled())
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-dotnet-button", mode="edit")
        self.assertTrue(button.isEnabled())

        with patch.object(tab, "_dotnet_editor_executable_path", return_value=None):
            button.click()

        self.assertIn("not configured", messages[-1][0])
        self.assertTrue(messages[-1][1])
        self.assertIsNone(tab.standalone_dotnet_package_thread)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_editable_package_buttons_emit_requests(self) -> None:
        app = QApplication.instance() or QApplication([])
        workspace = MeshEditorWorkspace()
        export_button = workspace.findChild(QPushButton, "MeshEditorExportEditablePackageButton")
        import_button = workspace.findChild(QPushButton, "MeshEditorImportEditedPackageButton")
        open_button = workspace.findChild(QPushButton, "MeshEditorOpenEditablePackageFolderButton")
        assert export_button is not None
        assert import_button is not None
        assert open_button is not None
        self.assertFalse(export_button.isEnabled())
        self.assertFalse(import_button.isEnabled())
        self.assertFalse(open_button.isEnabled())

        exports: list[bool] = []
        imports: list[bool] = []
        opens: list[bool] = []
        workspace.export_editable_package_requested.connect(lambda: exports.append(True))
        workspace.import_edited_package_requested.connect(lambda: imports.append(True))
        workspace.open_editable_package_folder_requested.connect(lambda: opens.append(True))
        workspace.update_action_state(has_target=True)

        self.assertTrue(export_button.isEnabled())
        self.assertTrue(import_button.isEnabled())
        self.assertTrue(open_button.isEnabled())
        export_button.click()
        import_button.click()
        open_button.click()

        self.assertEqual([True], exports)
        self.assertEqual([True], imports)
        self.assertEqual([True], opens)
        app.processEvents()
        workspace.deleteLater()

    def test_mesh_editor_workspace_native_performance_status_updates(self) -> None:
        app = QApplication.instance() or QApplication([])
        workspace = MeshEditorWorkspace()
        status = workspace.findChild(QLabel, "MeshEditorNativePerformanceStatus")
        panel = workspace.findChild(QTreeWidget, "MeshEditorPerformancePanel")
        assert status is not None
        assert panel is not None

        self.assertEqual("FPS: -- | Frame: -- ms", status.text())
        self.assertFalse(bool(status.property("nativePerformanceAvailable")))
        self.assertEqual(
            {
                "Current FPS": "--",
                "Average FPS": "--",
                "Frame time": "--",
                "CPU update": "--",
                "GPU upload": "--",
                "Draw calls": "--",
                "Vertices": "--",
                "Indices": "--",
                "Visible submeshes": "--",
                "Texture memory": "--",
            },
            {panel.topLevelItem(index).text(0): panel.topLevelItem(index).text(1) for index in range(panel.topLevelItemCount())},
        )
        workspace.set_native_performance_status(
            {
                "metrics": {
                    "current_fps": 71.8,
                    "average_fps": 72.0,
                    "frame_time_ms": 13.8,
                    "cpu_update_ms": 1.2,
                    "gpu_upload_ms": 4.2,
                    "draw_call_count": 5,
                    "vertex_count": 3000,
                    "index_count": 8994,
                    "visible_submesh_count": 2,
                    "texture_memory_bytes": 2 * 1024 * 1024,
                }
            }
        )

        self.assertEqual("FPS: 71.8 (avg 72.0) | Frame: 13.80 ms | CPU: 1.20 ms | GPU: 4.20 ms", status.text())
        self.assertTrue(bool(status.property("nativePerformanceAvailable")))
        self.assertEqual(
            {
                "Current FPS": "71.8",
                "Average FPS": "72.0",
                "Frame time": "13.80 ms",
                "CPU update": "1.20 ms",
                "GPU upload": "4.20 ms",
                "Draw calls": "5",
                "Vertices": "3,000",
                "Indices": "8,994",
                "Visible submeshes": "2",
                "Texture memory": "2.0 MiB",
            },
            {panel.topLevelItem(index).text(0): panel.topLevelItem(index).text(1) for index in range(panel.topLevelItemCount())},
        )
        self.assertEqual(0, workspace.log_list.count())
        workspace.set_native_performance_status({"metrics": {"frame_time_ms": 33.4, "cpu_update_ms": 2.5, "gpu_upload_ms": 7.0, "draw_call_count": 9}})
        self.assertEqual(1, workspace.log_list.count())
        self.assertIn("Slow native preview frame: 33.40 ms", workspace.log_list.item(0).text())
        workspace.set_native_performance_status({"metrics": {"frame_time_ms": 33.4, "cpu_update_ms": 2.5, "gpu_upload_ms": 7.0, "draw_call_count": 9}})
        self.assertEqual(1, workspace.log_list.count())
        app.processEvents()
        workspace.deleteLater()

    def test_mesh_editor_tab_opens_last_editable_package_folder(self) -> None:
        app = QApplication.instance() or QApplication([])
        settings = QSettings("CDMWTests", "MeshEditorEditablePackageFolder")
        settings.clear()
        tab = MeshEditorTab(settings=settings)
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))

        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir)
            settings.setValue("mesh_editor/last_editable_package_dir", str(package_dir))
            opened: list[str] = []

            def fake_open_url(url: object) -> bool:
                opened.append(url.toLocalFile())  # type: ignore[attr-defined]
                return True

            with patch("cdmw.ui.mesh_editor.tab.QDesktopServices.openUrl", side_effect=fake_open_url):
                self.assertTrue(tab._open_standalone_editable_package_folder())

            self.assertEqual([package_dir.resolve()], [Path(value) for value in opened])
            self.assertIn("Opened editable mesh package folder", messages[-1][0])
            self.assertFalse(messages[-1][1])

        app.processEvents()
        tab.deleteLater()

    def test_mesh_editable_package_workers_export_and_import_with_validation(self) -> None:
        mesh = build_synthetic_mesh()
        source_data = b"source pac bytes"
        source_hash = hashlib.sha256(source_data).hexdigest()
        mesh.submeshes[0].source_vertex_map = [0, 1, 2, 3]
        setattr(mesh, "_cdmw_original_data", source_data)
        setattr(mesh, "_cdmw_mesh_asset_parse_confidence", "exact")
        setattr(mesh, "_cdmw_mesh_asset_source_hash", source_hash)
        setattr(mesh, "_cdmw_no_op_roundtrip_report", {"result": "PASS", "byte_identical": True, "unexpected_differences": 0})
        service = MeshService()
        view = service.open_edit_session(mesh, session_id="editable-package-workers", mode="edit")

        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "package"
            exported: list[object] = []

            def fake_export_obj(_mesh: object, output_dir: str, name: str, **_kwargs: object) -> list[str]:
                root = Path(output_dir)
                obj_path = root / f"{name}.obj"
                mtl_path = root / f"{name}.mtl"
                sidecar_path = Path(f"{obj_path}.meta.json")
                obj_path.write_text(
                    "\n".join(
                        [
                            "# source_path: tools/harness_quad.pac",
                            "# source_format: pac",
                            "mtllib mesh.mtl",
                            "o harness_quad",
                            "usemtl harness_material",
                            "v -0.750000 -0.750000 0.000000",
                            "v 0.750000 -0.750000 0.000000",
                            "v -0.750000 0.750000 0.000000",
                            "v 0.750000 0.750000 0.000000",
                            "vt 0.000000 0.000000",
                            "vt 1.000000 0.000000",
                            "vt 0.000000 1.000000",
                            "vt 1.000000 1.000000",
                            "vn 0.0000 0.0000 1.0000",
                            "vn 0.0000 0.0000 1.0000",
                            "vn 0.0000 0.0000 1.0000",
                            "vn 0.0000 0.0000 1.0000",
                            "s 1",
                            "f 1/1/1 2/2/2 3/3/3",
                            "f 2/2/2 4/4/4 3/3/3",
                            "",
                        ]
                    ),
                    encoding="utf-8",
                )
                mtl_path.write_text("newmtl harness_material\nmap_Kd harness.dds\n", encoding="utf-8")
                sidecar_path.write_text(
                    json.dumps(
                        {
                            "format": "mesh_roundtrip_manifest_v2",
                            "schema_version": 1,
                            "source_path": "tools/harness_quad.pac",
                            "source_format": "pac",
                            "source_asset_hash": source_hash,
                            "source_asset_size": len(source_data),
                            "allowed_edit_operations": [
                                "replace_positions_same_count",
                                "replace_normals_same_count",
                                "replace_uv0_same_count",
                            ],
                            "submeshes": [
                                {
                                    "name": "harness_quad",
                                    "stable_id": "lod0_submesh0",
                                    "material": "harness_material",
                                    "texture": "harness.dds",
                                    "original_vertex_count": 4,
                                    "original_index_count": 6,
                                    "source_vertex_map": [0, 1, 2, 3],
                                }
                            ],
                        }
                    ),
                    encoding="utf-8",
                )
                return [str(obj_path), str(mtl_path), str(sidecar_path)]

            with patch("cdmw.workers.mesh_editor_workers.export_obj", side_effect=fake_export_obj):
                export_worker = MeshEditablePackageExportWorker(1, service, view.session_id, package_dir)
                export_worker.completed.connect(lambda _request_id, result, _elapsed_ms: exported.append(result))
                export_worker.run()

            self.assertTrue((package_dir / "mesh.obj").is_file())
            self.assertTrue((package_dir / "mesh.glb").is_file())
            self.assertTrue((package_dir / "mesh.cdmeta.json").is_file())
            self.assertTrue((package_dir / "original_asset_hash.txt").is_file())
            self.assertEqual(1, len(exported))
            self.assertEqual(package_dir / "mesh.glb", exported[0]["mesh_path"])
            (package_dir / "mesh.glb.meta.json").unlink()

            imported: list[tuple[object, object]] = []
            import_worker = MeshEditablePackageImportWorker(2, service, view.session_id, package_dir)
            import_worker.completed.connect(lambda _request_id, new_view, validation, _elapsed_ms: imported.append((new_view, validation)))
            import_worker.run()

        self.assertEqual(1, len(imported))
        new_view, validation = imported[0]
        self.assertEqual(view.session_id, new_view.session_id)
        self.assertTrue(validation.ok)
        self.assertEqual("replace_positions_same_count", service._sessions[view.session_id].edit_operations[0]["operation"])

    def test_mesh_editor_tab_launches_configured_dotnet_experiment_process(self) -> None:
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
            package = MeshDotNetExperimentPackage(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=package_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
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
                self.assertIn(str(package.package_dir / "dotnet_evaluation.md"), process.arguments)
                self.assertEqual(str(package.package_dir), process.working_directory)
                self.assertIs(process, tab.standalone_dotnet_editor_process)

                process._state = process.NotRunning
                process.finished.emit(0, 0)

                self.assertIsNone(tab.standalone_dotnet_editor_process)
                self.assertIn("Output package", messages[-1][0])
                self.assertIn("Evaluation", messages[-1][0])
                self.assertFalse(messages[-1][1])
                self.assertTrue((package.package_dir / "dotnet_evaluation.md").is_file())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_launches_embedded_dotnet_with_parent_hwnd(self) -> None:
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
            package = MeshDotNetExperimentPackage(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=package_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
                material_signature=mesh_dotnet_material_input_signature(builder.controller.working_mesh(clone=False)),
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
            self.assertGreater(builder.controller.session_view().revision, revision_before_late_event)
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

    def test_mesh_editor_tab_unexpected_embedded_dotnet_exit_keeps_resident_edits(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedDotNetUnexpectedExit"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        builder.controller.select(vertices_by_submesh={0: (0,)})
        builder.controller.apply_editor_action("transform_move", translate=(0.0, 0.0, 0.25))
        resident_revision = builder.controller.session_view().revision
        fallbacks: list[tuple[str, str]] = []
        setattr(builder, "_mesh_editor_embedded_dotnet_failed", lambda reason, detail: fallbacks.append((reason, detail)))

        with tempfile.TemporaryDirectory() as temp_dir:
            package_dir = Path(temp_dir) / "package"
            output_dir = package_dir / "output"
            output_dir.mkdir(parents=True)
            package = MeshDotNetExperimentPackage(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=package_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
            )
            process = _FakeProcess(tab)
            tab.standalone_dotnet_target_embedded = True
            tab.standalone_dotnet_target_controller = builder.controller
            tab.standalone_dotnet_editor_process = process
            tab._set_embedded_dotnet_state("ready", active=True)

            tab._handle_standalone_dotnet_editor_finished(process, package)

        self.assertIsNone(tab.standalone_dotnet_editor_process)
        self.assertIs(builder.controller, tab.standalone_dotnet_target_controller)
        self.assertEqual(resident_revision, builder.controller.session_view().revision)
        self.assertGreater(resident_revision, 0)
        self.assertEqual([], builder.finalized_dotnet_imports)
        self.assertEqual("failed", tab.standalone_dotnet_embedded_state)
        self.assertEqual("mesh_edit_dotnet_fallback", fallbacks[0][0])
        self.assertIn("exited unexpectedly", fallbacks[0][1])
        self.assertFalse(getattr(builder, "_mesh_editor_embedded_dotnet_active", True))
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_reactivation_repackages_changed_material_inputs(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorEmbeddedDotNetMaterialRefresh"))
        builder = _EmbeddedMeshBuilder()
        tab.mount_embedded_builder(builder)
        mesh = builder.controller.working_mesh(clone=False)
        original_signature = mesh_dotnet_material_input_signature(mesh)
        process = _FakeProcess(tab)
        process._state = process.Running
        package = MeshDotNetExperimentPackage(
            package_dir=Path("package"),
            mesh_path=Path("package/mesh.obj"),
            obj_sidecar_path=Path("package/mesh.obj.meta.json"),
            cdmeta_path=Path("package/mesh.cdmeta.json"),
            original_asset_hash_path=Path("package/original_asset_hash.txt"),
            status_path=Path("package/dotnet_status.json"),
            output_dir=Path("package/output"),
            edit_operations_path=Path("package/output/edit_operations.json"),
            launch_manifest_path=Path("package/dotnet_launch.json"),
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

    def test_mesh_editor_tab_embedded_dotnet_uses_builder_hwnd_without_preview_host(self) -> None:
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
            package = MeshDotNetExperimentPackage(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=package_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
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

    def test_mesh_editor_tab_dotnet_protocol_routes_visible_selection_and_disabled_clipboard(self) -> None:
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
            package = MeshDotNetExperimentPackage(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=package_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
            )
            tab.standalone_dotnet_target_embedded = True
            tab.standalone_dotnet_target_controller = builder.controller
            _FakeProcess.instances.clear()
            with patch("cdmw.ui.mesh_editor.tab.QProcess", _FakeProcess):
                self.assertTrue(tab._launch_standalone_dotnet_editor_package(package))

            process = _FakeProcess.instances[-1]
            self.assertTrue(any(b'"event":"session_state"' in write for write in process.stdin_writes))
            process.emit_stdout('{"event":"ready","renderer":{"backend":"d3d11_vortice_shader","gpu_backed":true,"renderer_blocked":false}}\n')
            self.assertTrue(any(b'"selection_depth_mode":"visible"' in write for write in process.stdin_writes))

            captured: list[tuple[str, dict[str, object]]] = []

            def fake_apply(action: str, **params: object) -> MeshEditResult:
                captured.append((action, dict(params)))
                return MeshEditResult(action=action, status="noop", revision=7)

            with patch.object(builder.controller, "apply", side_effect=fake_apply):
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
            self.assertEqual("select", captured[-1][0])
            screen_payload = captured[-1][1]["_native_screen_selection_payload"]
            self.assertIsInstance(screen_payload, dict)
            self.assertEqual("visible", screen_payload["selection_depth_mode"])
            self.assertEqual("face", screen_payload["target_mode"])
            self.assertTrue(any(b'"event":"command_result"' in write for write in process.stdin_writes))

            process.emit_stdout('{"event":"command_request","command":"delete","session_id":"stale"}\n')
            self.assertTrue(any(b"Stale .NET mesh editor session id." in write for write in process.stdin_writes))
            process.emit_stdout('{"event":"command_request","command":"paste"}\n')
            self.assertTrue(any(b'"status":"disabled"' in write and b'"command":"paste"' in write for write in process.stdin_writes))
            process.emit_stdout("{bad json\n")
            self.assertIn("malformed JSON", tab.embedded_workspace.status_label.text())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_imports_dotnet_output_obj_after_process_exit(self) -> None:
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
            package = MeshDotNetExperimentPackage(
                package_dir=package_dir,
                mesh_path=package_dir / "mesh.obj",
                obj_sidecar_path=package_dir / "mesh.obj.meta.json",
                cdmeta_path=package_dir / "mesh.cdmeta.json",
                original_asset_hash_path=package_dir / "original_asset_hash.txt",
                status_path=package_dir / "dotnet_status.json",
                output_dir=output_dir,
                edit_operations_path=output_dir / "edit_operations.json",
                launch_manifest_path=package_dir / "dotnet_launch.json",
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
            self.assertTrue((package.package_dir / "dotnet_evaluation.md").is_file())
        tab.close_standalone_session()
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_polls_standalone_native_status_file(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneNativeStatus"))
        messages: list[tuple[str, bool]] = []
        tab.status_message_requested.connect(lambda message, error=False: messages.append((message, bool(error))))
        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-native-status", mode="edit")

        with tempfile.TemporaryDirectory() as temp_dir:
            status_file = Path(temp_dir) / "host_status.json"
            tab.standalone_native_status_file = status_file
            status_file.write_text(
                json.dumps({"event": "loading", "message": "Uploading geometry", "batch_count": 1}),
                encoding="utf-8",
            )

            tab._poll_standalone_native_preview_status()

            self.assertEqual("Uploading geometry", tab.standalone_status_label.text())
            self.assertEqual(("Native D3D11 preview: Uploading geometry", False), messages[-1])

            status_file.write_text(
                json.dumps(
                    {
                        "event": "loaded",
                        "batch_count": 2,
                        "vertex_count": 3000,
                        "first_frame_ms": 13.8,
                        "geometry_upload_ms": 4.2,
                    }
                ),
                encoding="utf-8",
            )
            tab._poll_standalone_native_preview_status()

            self.assertEqual("Native D3D11 preview loaded: 2 batches, 3,000 vertices.", tab.standalone_status_label.text())
            self.assertEqual(("Native D3D11 preview loaded.", False), messages[-1])
            self.assertEqual("loaded", tab.standalone_native_last_status_payload["event"])
            perf = tab.standalone_workspace.findChild(QLabel, "MeshEditorNativePerformanceStatus")
            panel = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorPerformancePanel")
            assert perf is not None
            assert panel is not None
            self.assertEqual("FPS: 72.5 | Frame: 13.80 ms | GPU: 4.20 ms", perf.text())
            rows = {panel.topLevelItem(index).text(0): panel.topLevelItem(index).text(1) for index in range(panel.topLevelItemCount())}
            self.assertEqual("3,000", rows["Vertices"])
            self.assertEqual("2", rows["Visible submeshes"])
            tab._handle_standalone_native_preview_event({"event": "mesh_edit_stroke_started", "payload": {"frame_count": 4}})
            self.assertEqual("FPS: 72.5 | Frame: 13.80 ms | GPU: 4.20 ms", perf.text())
            tab._handle_standalone_native_preview_event({"event": "status", "metrics": {"average_fps": 60.0, "frame_time_ms": 16.6}})
            self.assertEqual("FPS: 60.0 | Frame: 16.60 ms", perf.text())

            status_file.write_text(json.dumps({"event": "error", "message": "device lost"}), encoding="utf-8")
            tab._poll_standalone_native_preview_status()

            self.assertEqual("Native D3D11 preview error: device lost", tab.standalone_status_label.text())
            self.assertEqual(("Native D3D11 preview error: device lost", True), messages[-1])
            self.assertEqual("FPS: -- | Frame: -- ms", perf.text())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_updates_action_state_from_controller_session_view(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorActionState"))
        controller = MeshEditorController()
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))

        view = controller.open_mesh(build_synthetic_mesh(), session_id="tab-state", mode="edit")
        tab.update_editor_session_state(view, active_selection_mode=controller.active_selection_mode)

        self.assertTrue(tab.action_bar.button_for_key("mode_edit").isChecked())
        self.assertFalse(tab.action_bar.button_for_key("extrude").isEnabled())
        self.assertFalse(tab.action_bar.button_for_key("undo").isEnabled())
        self.assertIn("Edit: edit", tab.session_label.text())

        controller.select(vertices_by_submesh={0: (0,)})
        tab.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)

        self.assertTrue(tab.action_bar.button_for_key("select_vertex").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("extrude").isEnabled())
        self.assertTrue(tab.action_bar.button_for_key("brush_grab").isEnabled())

        controller.apply_editor_action("transform_move", translate=(0.0, 0.0, 0.25))
        tab.update_editor_session_state(controller.session_view(), active_selection_mode=controller.active_selection_mode)

        self.assertTrue(tab.action_bar.button_for_key("undo").isEnabled())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_reports_native_editor_unavailable_and_disables_native_tools(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorNativeUnavailable"))

        with patch("cdmw.ui.mesh_editor.tab.native_mesh_core_available", return_value=False) as native_available:
            tab.open_mesh_session(build_synthetic_mesh(), session_id="native-unavailable-ui", mode="edit")
            native_available.reset_mock()
            assert tab.standalone_controller is not None
            tab.standalone_controller.select(vertices_by_submesh={0: (0,)})
            tab.update_editor_session_state(
                tab.standalone_controller.session_view(),
                active_selection_mode=tab.standalone_controller.active_selection_mode,
            )
            native_available.assert_not_called()

            self.assertIn("Native Mesh Editor unavailable", tab.standalone_status_label.text())
            self.assertTrue(tab.action_bar.button_for_key("mode_edit").isEnabled())
            self.assertTrue(tab.action_bar.button_for_key("select_vertex").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("delete").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("subdivide").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("brush_grab").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("transform_move").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("weighted_normals").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("uv_transform").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("remove_doubles").isEnabled())
            self.assertFalse(tab.action_bar.button_for_key("material_assign").isEnabled())
            workspace_delete = tab.standalone_workspace.button_for_key("delete")
            workspace_transform = tab.standalone_workspace.button_for_key("transform_move")
            workspace_weighted = tab.standalone_workspace.button_for_key("weighted_normals")
            workspace_select = tab.standalone_workspace.button_for_key("select_vertex")
            assert workspace_delete is not None
            assert workspace_transform is not None
            assert workspace_weighted is not None
            assert workspace_select is not None
            self.assertFalse(workspace_delete.isEnabled())
            self.assertFalse(workspace_transform.isEnabled())
            self.assertFalse(workspace_weighted.isEnabled())
            self.assertTrue(workspace_select.isEnabled())
            with patch.object(tab, "_start_standalone_action_worker", side_effect=AssertionError("worker started")):
                self.assertTrue(tab._run_standalone_action(mesh_editor_actions_by_key()["delete"]))
                self.assertTrue(tab._run_standalone_action(mesh_editor_actions_by_key()["transform_move"]))
            self.assertFalse(tab._handle_part_context_action("duplicate", 0))
            self.assertEqual((), tab.standalone_controller.session_view().selection.source_indices)
            self.assertIn("Native Mesh Editor C++ core is missing", tab.standalone_status_label.text())

        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_can_set_active_tool_state_without_editing(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorToolState"))
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))

        tab.set_active_tool_state(mode="sculpt", active_selection_mode="edge")

        self.assertEqual("sculpt", tab.current_edit_mode)
        self.assertEqual("edge", tab.current_selection_mode)
        self.assertTrue(tab.action_bar.button_for_key("mode_sculpt").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("select_edge").isChecked())

        tab.set_active_tool_state(mode="sculpt", active_tool_key="brush_smooth")
        self.assertTrue(tab.action_bar.button_for_key("brush_smooth").isChecked())
        self.assertFalse(tab.action_bar.button_for_key("select_edge").isChecked())

        tab.set_active_tool_state(active_selection_mode="vertex", active_tool_key="")
        self.assertEqual("", tab.current_tool_action_key)
        self.assertFalse(tab.action_bar.button_for_key("brush_smooth").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("select_vertex").isChecked())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_updates_direct_builder_action_state(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorBuilderState"))
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))

        tab.update_editor_action_state(
            mode="edit",
            active_selection_mode="face",
            selection_empty=False,
            undo_count=2,
            redo_count=1,
        )

        self.assertEqual("edit", tab.current_edit_mode)
        self.assertEqual("face", tab.current_selection_mode)
        self.assertFalse(tab.current_selection_empty)
        self.assertTrue(tab.action_bar.button_for_key("mode_edit").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("select_face").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("extrude").isEnabled())
        self.assertTrue(tab.action_bar.button_for_key("material_assign").isEnabled())
        self.assertTrue(tab.action_bar.button_for_key("undo").isEnabled())
        self.assertTrue(tab.action_bar.button_for_key("redo").isEnabled())

        tab.update_editor_action_state(
            mode="object",
            active_selection_mode="vertex",
            selection_empty=True,
            undo_count=0,
            redo_count=0,
        )

        self.assertTrue(tab.action_bar.button_for_key("mode_object").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("select_vertex").isChecked())
        self.assertFalse(tab.action_bar.button_for_key("extrude").isEnabled())
        self.assertFalse(tab.action_bar.button_for_key("brush_grab").isEnabled())
        self.assertFalse(tab.action_bar.button_for_key("undo").isEnabled())
        self.assertFalse(tab.action_bar.button_for_key("redo").isEnabled())
        app.processEvents()
        tab.deleteLater()

    def test_shell_mesh_editor_action_handler_routes_palette_state_and_status(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorShellAction"))
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))
        shell = _DummyMeshEditorShell(tab)
        actions = mesh_editor_actions_by_key()

        shell._mesh_editor_action_requested(actions["mode_sculpt"])
        shell._mesh_editor_action_requested(actions["select_edge"])

        self.assertEqual("sculpt", tab.current_edit_mode)
        self.assertEqual("edge", tab.current_selection_mode)
        self.assertTrue(tab.action_bar.button_for_key("mode_sculpt").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("select_edge").isChecked())
        self.assertEqual(("Mesh Editor tool selected: Edge.", False), shell.messages[-1])
        app.processEvents()
        tab.deleteLater()

    def test_shell_mesh_editor_preview_rebuilt_asset_routes_import_preview_preset(self) -> None:
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            rebuilt_path = temp_path / "rebuilt.pac"
            rebuilt_path.write_bytes(b"pac")
            target_entry = ArchiveEntry(
                path="character/model/body.pac",
                pamt_path=temp_path / "0.pamt",
                paz_file=temp_path / "0.paz",
                offset=0,
                comp_size=1,
                orig_size=1,
                flags=0,
                paz_index=0,
            )
            tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorShellPreviewRebuilt"))
            shell = _DummyMeshEditorShell(tab)
            calls: list[tuple[object, object]] = []
            shell._start_archive_mesh_import_preview = (  # type: ignore[attr-defined]
                lambda entry, *, preset_setup=None: calls.append((entry, preset_setup))
            )
            package_calls: list[tuple[object, object]] = []
            shell._start_archive_mesh_patch = (  # type: ignore[attr-defined]
                lambda entry, *, preset_setup=None: package_calls.append((entry, preset_setup))
            )

            shell._mesh_editor_preview_rebuilt_asset_requested(target_entry, rebuilt_path)
            shell._mesh_editor_package_rebuilt_asset_requested(target_entry, rebuilt_path)

            self.assertEqual(target_entry, calls[0][0])
            setup = calls[0][1]
            self.assertEqual(rebuilt_path, getattr(setup, "scene_path", None))
            self.assertEqual("static_replacement", getattr(setup, "import_mode", ""))
            self.assertIn("Rebuilt asset", getattr(setup, "source_label", ""))
            self.assertEqual(target_entry, package_calls[0][0])
            package_setup = package_calls[0][1]
            self.assertEqual(rebuilt_path, getattr(package_setup, "scene_path", None))
            self.assertEqual("static_replacement", getattr(package_setup, "import_mode", ""))
            self.assertIn("Package", getattr(package_setup, "placement_review_title", ""))
            app.processEvents()
            tab.deleteLater()

    def test_shell_mesh_editor_action_handler_routes_to_embedded_builder(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorShellBuilderAction"))
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))
        shell = _DummyMeshEditorShell(tab)
        actions = mesh_editor_actions_by_key()
        routed: list[object] = []
        shell.builder = SimpleNamespace(
            _mesh_editor_action_bar_action_requested=lambda action: routed.append(action) or True,
        )

        shell._mesh_editor_action_requested(actions["subdivide"])

        self.assertEqual(["subdivide"], [getattr(action, "key", "") for action in routed])
        self.assertEqual(("Mesh Editor action sent: Subdivide.", False), shell.messages[-1])
        app.processEvents()
        tab.deleteLater()

    def test_shell_mesh_editor_action_handler_reports_unsupported_builder_action(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorShellBuilderUnsupported"))
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))
        shell = _DummyMeshEditorShell(tab)
        actions = mesh_editor_actions_by_key()
        shell.builder = SimpleNamespace(_mesh_editor_action_bar_action_requested=lambda _action: False)

        shell._mesh_editor_action_requested(actions["select_edge"])

        self.assertEqual("vertex", tab.current_selection_mode)
        self.assertEqual(
            ("Mesh Editor action is not available in the embedded builder yet: Edge.", False),
            shell.messages[-1],
        )
        app.processEvents()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
