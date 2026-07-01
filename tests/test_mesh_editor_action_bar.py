from __future__ import annotations

import json
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
    QHeaderView,
    QLabel,
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
    MeshEditSelection,
)
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewRenderSettings, TextureEditorSourceBinding
from cdmw.services.mesh_texture_sources import MeshTextureSourceResolution, resolve_mesh_texture_source
from cdmw.ui.mesh_editor import MeshEditorActionBar, MeshEditorController, MeshEditorTab
from cdmw.ui.mesh_editor.actions import mesh_editor_actions_by_key
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin
from cdmw.workers.mesh_editor_workers import MeshFileSessionLoadWorker, MeshNativePreviewPackageWorker
from tools.mesh_editor_dev_harness import _build_two_part_synthetic_mesh, build_synthetic_mesh


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

    def update_mesh_edit_vertices(self, groups: object) -> bool:
        self.calls.append(("vertices", groups))
        return True

    def replace_mesh_edit_triangles(self, groups: object, *, replace_all: bool = False) -> bool:
        self.calls.append(("triangles", (groups, replace_all)))
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
        self.tabs = QTabWidget(self)
        self.tabs.setObjectName("MeshAlignmentStickyWorkflowTabs")
        for title in ("Setup", "Parts & Routing", "Mesh Editing", "Diagnostics"):
            self.tabs.addTab(QFrame(self.tabs), title)
        layout.addWidget(self.tabs)
        self.controller = MeshEditorController()
        self.controller.open_mesh(_build_two_part_synthetic_mesh(), session_id="embedded-builder", mode="edit")
        self.part_actions: list[tuple[str, tuple[int, ...]]] = []
        self.skeleton_bones: list[int] = []
        self.synced_data_font: QFont | None = None

    def _mesh_editor_embedded_controller(self) -> MeshEditorController:
        return self.controller

    def sync_ui_font(self, font: QFont, data_font: QFont | None = None) -> None:
        self.setFont(font)
        self.tabs.setFont(font)
        self.synced_data_font = QFont(data_font or font)

    def _mesh_editor_embedded_apply_native_update(self, _native_update: object) -> bool:
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
        self.deleted = False
        self.terminated = False
        self.killed = False
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
        self.assertEqual("loop_cut", loop_cut_button.property("meshEditorCommand"))
        self.assertEqual("edit", loop_cut_button.property("meshEditorMode"))
        self.assertEqual("edge", loop_cut_button.property("meshEditorSelectionMode"))
        self.assertEqual("loop_cut", loop_cut_button.property("meshEditorIconKey"))
        self.assertEqual("Ctrl+R", loop_cut_button.property("meshEditorShortcut"))
        self.assertEqual("Ctrl+R", loop_cut_button.shortcut().toString(QKeySequence.SequenceFormat.PortableText))
        self.assertIn("Shortcut: Ctrl+R", loop_cut_button.toolTip())
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

    def test_mesh_editor_embedded_builder_keeps_classic_primary_with_advanced_restore(self) -> None:
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
        assert restore is not None
        legacy_restore = builder.tabs.findChild(QPushButton, "MeshEditorLegacyMeshControlsRestoreButton")
        assert legacy_restore is not None
        restore.click()
        self.assertTrue(builder.tabs.isTabVisible(4))
        self.assertEqual("Advanced Mesh Data", builder.tabs.tabText(builder.tabs.currentIndex()))
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

        legacy_restore.click()
        self.assertTrue(builder.tabs.isTabVisible(2))
        self.assertEqual("Mesh Editing", builder.tabs.tabText(builder.tabs.currentIndex()))
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
            ["Parts", "Details", "Rig", "UV Map", "Part Actions", "Review", "Checks", "History"],
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

        workspace.part_context_action_requested.emit("duplicate", 0)
        names_after_clone = [part.name for part in tab.standalone_controller.working_mesh().submeshes]

        workspace.part_context_action_requested.emit("delete", 2)
        names_after_delete = [part.name for part in tab.standalone_controller.working_mesh().submeshes]

        self.assertEqual(
            ["harness_quad", "harness_quad_b", "harness_quad duplicate", "harness_quad_b duplicate"],
            names_after_clone,
        )
        self.assertEqual(("harness_quad", "harness_quad_b", "harness_quad_b duplicate"), tuple(names_after_delete))
        self.assertEqual((), tab.standalone_controller.session_view().selection.source_indices)
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_workspace_part_controls_show_selection_details_and_route_actions(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorPartControls"))

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

        clone.click()
        self.assertEqual(4, len(tab.standalone_controller.working_mesh().submeshes))
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
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorComparePanel"))

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

        compare = tab.standalone_workspace.findChild(QTreeWidget, "MeshEditorComparePanel")
        combo = tab.standalone_workspace.findChild(QComboBox, "MeshEditorCompareModeCombo")
        assert compare is not None
        assert combo is not None
        rows = [(compare.topLevelItem(index).text(0), compare.topLevelItem(index).text(2)) for index in range(compare.topLevelItemCount())]
        self.assertTrue(any(label == "Bounds" for label, _value in rows))
        self.assertTrue(any(label.startswith("0: harness_quad") and "bounds" in value for label, value in rows))

        tab._refresh_standalone_preview()
        edited_vertices = int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0)
        tab.standalone_controller.apply(
            "duplicate",
            selection=MeshEditSelection.from_maps(source_indices=(0,)),
            mode="edit",
        )
        tab.update_editor_session_state(
            tab.standalone_controller.session_view(),
            active_selection_mode=tab.standalone_controller.active_selection_mode,
        )
        tab._refresh_standalone_preview()
        duplicated_vertices = int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0)
        combo.setCurrentText("Source")
        source_vertices = int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0)

        self.assertGreater(duplicated_vertices, edited_vertices)
        self.assertEqual(edited_vertices, source_vertices)
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
        uv_tree = workspace.findChild(QTreeWidget, "MeshEditorUVPanel")
        assert summary is not None
        assert select_all is not None
        assert flip_u is not None
        assert pack is not None
        assert uv_tree is not None
        self.assertIn("UV:", summary.text())
        self.assertFalse(flip_u.isEnabled())
        self.assertFalse(pack.isEnabled())

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
        self.assertGreater(tab.standalone_controller.session_view().revision, previous_revision)
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

    def test_mesh_editor_file_session_loads_sibling_source_skeleton_for_weight_transfer(self) -> None:
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
            target_skeleton = Skeleton(
                bones=[Bone(index=4, name="Spine"), Bone(index=9, name="Root")],
                bone_count=2,
            )

            with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed):
                tab.open_mesh_file_session(mesh_path, session_id="standalone-file-source-skeleton", mode="edit")

            assert tab.standalone_controller is not None
            self.assertEqual(str(skeleton_path.resolve()), getattr(tab.standalone_source_skeleton, "path", ""))
            linked = tab.standalone_controller.skeleton_summary()
            self.assertTrue(linked.skeleton_linked)
            self.assertEqual(str(skeleton_path.resolve()), linked.skeleton_source)
            self.assertEqual(2, len(linked.bones))
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

            weight_transfer_button.click()

            self.assertEqual((4, 9), working.submeshes[0].bone_indices[2])
            self.assertEqual((0.75, 0.25), working.submeshes[0].bone_weights[2])
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

    def test_mesh_editor_shell_wires_texture_open_request_to_texture_editor_bridge(self) -> None:
        source = Path("cdmw/ui/shell/tool_tabs.py").read_text(encoding="utf-8")
        self.assertIn("open_texture_source_requested.connect(self._open_source_in_texture_editor)", source)
        self.assertIn("native_dds_ready.connect(self.mesh_editor_tab.apply_texture_editor_dds_preview)", source)
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

        self.assertTrue(tab.action_bar.button_for_key("transform_rotate").isEnabled())
        tab.action_bar.button_for_key("transform_rotate").click()

        self.assertEqual(["vertices"], [name for name, _payload in host.calls])
        self.assertEqual([0, 1], host.calls[0][1][0]["source_vertex_indices"])
        self.assertNotEqual((-0.75, -0.75, 0.0), tab.standalone_controller.working_mesh().submeshes[0].vertices[0])
        self.assertIn("Revision: 1", tab.standalone_status_label.text())
        self.assertEqual(("Mesh Editor action applied: Rotate.", False), messages[-1])
        self.assertTrue(tab.action_bar.button_for_key("undo").isEnabled())
        tab.action_bar.button_for_key("undo").click()

        self.assertEqual(["vertices", "triangles", "material", "selection"], [name for name, _payload in host.calls])
        self.assertEqual((-0.75, -0.75, 0.0), tab.standalone_controller.working_mesh().submeshes[0].vertices[0])
        self.assertIn("Revision: 2", tab.standalone_status_label.text())
        app.processEvents()
        tab.deleteLater()

    def test_mesh_editor_tab_standalone_session_refreshes_preview_without_native_host(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorStandaloneFallback"))

        tab.open_mesh_session(build_synthetic_mesh(), session_id="standalone-fallback", mode="edit")
        assert tab.standalone_controller is not None
        before_vertices = int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0)
        tab.standalone_controller.select(vertices_by_submesh={0: (0, 1, 2, 3)}, faces_by_submesh={0: (0,)})
        tab.update_editor_session_state(tab.standalone_controller.session_view(), active_selection_mode=tab.standalone_controller.active_selection_mode)

        self.assertIs(tab.workspace_stack.currentWidget(), tab.standalone_workspace)
        self.assertTrue(tab.action_bar.isHidden())
        self.assertTrue(tab.action_bar.button_for_key("extrude").isEnabled())
        tab.action_bar.button_for_key("extrude").click()

        self.assertGreater(int(getattr(tab.standalone_preview, "_vertex_count", 0) or 0), before_vertices)
        self.assertIn("Revision: 1", tab.standalone_status_label.text())
        self.assertTrue(tab.action_bar.button_for_key("undo").isEnabled())
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
            loaded: list[tuple[int, object, object]] = []
            errors: list[tuple[int, str]] = []
            finished: list[bool] = []
            worker = MeshFileSessionLoadWorker(4, mesh_path, session_id="worker-file", mode="edit")
            worker.loaded.connect(lambda request_id, service, view: loaded.append((request_id, service, view)))
            worker.error.connect(lambda request_id, message: errors.append((request_id, message)))
            worker.finished.connect(lambda: finished.append(True))

            with patch("cdmw.services.mesh_service.parse_mesh", return_value=parsed) as parser:
                worker.run()

            parser.assert_called_once_with(b"mesh-bytes", str(mesh_path))
            self.assertEqual([], errors)
            self.assertEqual([True], finished)
            self.assertEqual(1, len(loaded))
            request_id, service, view = loaded[0]
            self.assertEqual(4, request_id)
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

        ok = tab.load_standalone_native_preview_package(
            Path("C:/tmp/mesh-editor-package"),
            Path("C:/tmp/mesh-editor-status.json"),
            reset_view=False,
        )

        self.assertTrue(ok)
        self.assertEqual(
            ("load_package", (Path("C:/tmp/mesh-editor-package"), Path("C:/tmp/mesh-editor-status.json"), False)),
            host.calls[-1],
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
                json.dumps({"event": "loaded", "batch_count": 2, "vertex_count": 3000}),
                encoding="utf-8",
            )
            tab._poll_standalone_native_preview_status()

            self.assertEqual("Native D3D11 preview loaded: 2 batches, 3,000 vertices.", tab.standalone_status_label.text())
            self.assertEqual(("Native D3D11 preview loaded.", False), messages[-1])
            self.assertEqual("loaded", tab.standalone_native_last_status_payload["event"])

            status_file.write_text(json.dumps({"event": "error", "message": "device lost"}), encoding="utf-8")
            tab._poll_standalone_native_preview_status()

            self.assertEqual("Native D3D11 preview error: device lost", tab.standalone_status_label.text())
            self.assertEqual(("Native D3D11 preview error: device lost", True), messages[-1])
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

    def test_mesh_editor_tab_can_set_active_tool_state_without_editing(self) -> None:
        app = QApplication.instance() or QApplication([])
        tab = MeshEditorTab(settings=QSettings("CDMWTests", "MeshEditorToolState"))
        tab.set_archive_selection(SimpleNamespace(path="characters/body.pac", basename="body.pac"))

        tab.set_active_tool_state(mode="sculpt", active_selection_mode="edge")

        self.assertEqual("sculpt", tab.current_edit_mode)
        self.assertEqual("edge", tab.current_selection_mode)
        self.assertTrue(tab.action_bar.button_for_key("mode_sculpt").isChecked())
        self.assertTrue(tab.action_bar.button_for_key("select_edge").isChecked())
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
