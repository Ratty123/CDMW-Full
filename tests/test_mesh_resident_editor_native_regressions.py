from __future__ import annotations

import json
import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QCoreApplication, QEvent, QPoint, QSettings, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QComboBox, QFrame, QPushButton, QTreeWidget, QTreeWidgetItem

from cdmw.domain.mesh import MeshEditCommand, MeshEditResult, MeshEditSelection
from cdmw.modding.mesh_native_core import native_mesh_core_available
from cdmw.modding.mesh_parser import ParsedMesh
from cdmw.services.mesh_service import MeshService
from cdmw.ui.archive_browser.static_replacement_dialog_prompt_shell import (
    _EmbeddedAlignmentBuilderDialog,
)
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.mesh_editor.controller import MeshEditorController, MeshEditorNativeUpdate
from cdmw.ui.mesh_editor.dotnet_update_queue import (
    MESH_EDIT_REVISION_CAPABILITY,
    MESH_MUTATION_ENVELOPE_CAPABILITY,
    DotNetRevisionUpdateQueue,
)
from cdmw.ui.mesh_editor.tab_dotnet_process import MeshEditorDotNetProcessMixin
from cdmw.ui.mesh_editor.tab_shell import MeshEditorTabShellMixin
from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _install_shared_dotnet_test_process,
)
from tests.test_mesh_service_editing import _quad_mesh


_APP = QApplication.instance() or QApplication([])


class MeshResidentEditorNativeRegressionTests(unittest.TestCase):
    @unittest.skipUnless(native_mesh_core_available(), "native mesh core is unavailable")
    def test_native_vertex_grow_and_shrink_ignore_other_selection_domains(self) -> None:
        controller = MeshEditorController()
        controller.open_mesh(_quad_mesh(), session_id="selection-domain-grow-shrink", mode="edit")
        contaminated_grow = MeshEditSelection.from_maps(
            vertices_by_submesh={0: (0,)},
            faces_by_submesh={0: (1,)},
            source_indices=(0,),
        )
        contaminated_shrink = MeshEditSelection.from_maps(
            vertices_by_submesh={0: (0, 1, 2)},
            faces_by_submesh={0: (1,)},
            source_indices=(0,),
        )
        try:
            controller.apply_command(
                MeshEditCommand(
                    "select",
                    selection=contaminated_grow,
                    params={"operation": "grow", "target_mode": "vertex"},
                )
            )
            self.assertEqual({0: {0, 1, 2}}, controller.session_view().selection.vertex_map())
            self.assertEqual((), controller.session_view().selection.source_indices)

            controller.apply_command(
                MeshEditCommand(
                    "select",
                    selection=contaminated_shrink,
                    params={"operation": "shrink", "target_mode": "vertex"},
                )
            )
            self.assertEqual({0: {0}}, controller.session_view().selection.vertex_map())
            self.assertEqual({}, controller.session_view().selection.face_map())
        finally:
            controller.close_active_session()

    @unittest.skipUnless(native_mesh_core_available(), "native mesh core is unavailable")
    def test_native_select_all_respects_every_dotnet_selection_domain(self) -> None:
        builder = _EmbeddedMeshBuilder()
        controller = builder.controller
        expected = {
            "source": (2, 0, 0, 0),
            "face": (0, 0, 0, 4),
            "edge": (0, 0, 10, 0),
            "vertex": (0, 8, 0, 0),
        }
        try:
            for target_mode, counts in expected.items():
                with self.subTest(target_mode=target_mode):
                    result = controller.apply_command(
                        MeshEditCommand(
                            "select",
                            selection=MeshEditSelection.from_maps(source_indices=(0, 1)),
                            params={"operation": "all", "target_mode": target_mode},
                        )
                    )
                    self.assertNotEqual("error", result.status)
                    selection = controller.session_view().selection
                    observed = (
                        len(selection.source_indices),
                        sum(len(values) for values in selection.vertex_map().values()),
                        sum(len(values) for values in selection.edge_map().values()),
                        sum(len(values) for values in selection.face_map().values()),
                    )
                    self.assertEqual(counts, observed)
                    controller.select(operation="replace")
        finally:
            controller.close_active_session()
            builder.deleteLater()

    def test_mesh_editor_blank_part_tree_click_clears_selection(self) -> None:
        workspace = MeshEditorWorkspace(embedded_controls_only=True)
        workspace.resize(900, 700)
        workspace.show()
        _APP.processEvents()
        outliner = workspace.findChild(QTreeWidget, "MeshEditorOutlinerPanel")
        assert outliner is not None
        item = QTreeWidgetItem(("Part 0",))
        outliner.addTopLevelItem(item)
        item.setSelected(True)
        requests: list[tuple[int, str]] = []
        workspace.part_selection_requested.connect(
            lambda part_index, operation: requests.append((part_index, operation))
        )

        QTest.mouseClick(
            outliner.viewport(),
            Qt.MouseButton.LeftButton,
            pos=QPoint(5, max(5, outliner.viewport().height() - 5)),
        )
        _APP.processEvents()

        self.assertEqual([(-1, "clear")], requests)
        self.assertFalse(item.isSelected())
        workspace.close()
        workspace.deleteLater()

    def test_native_session_clones_preserve_resolved_preview_texture_bindings(self) -> None:
        mesh = _quad_mesh()
        mesh.submeshes[0].preview_texture_path = "C:/cache/body.dds"
        mesh.submeshes[0].preview_texture_dds_path = "C:/cache/body.dds"
        mesh.submeshes[0].preview_material_texture_inputs = (
            SimpleNamespace(semantic_type="base", source_dds_path="C:/cache/body.dds"),
        )
        native_snapshot = {"kind": "native_submesh_snapshot", "submeshes": []}

        def restore(target: ParsedMesh, _snapshot: object) -> bool:
            target.path = mesh.path
            target.format = mesh.format
            target.submeshes = [_quad_mesh().submeshes[0]]
            return True

        with (
            patch("cdmw.services.mesh_service._service_session_native_clone_supported", return_value=True),
            patch("cdmw.services.mesh_service.snapshot_native_mesh_submeshes", return_value=native_snapshot),
            patch("cdmw.services.mesh_service.restore_native_mesh_submesh_snapshot", side_effect=restore),
            patch("cdmw.services.mesh_service.dispose_native_mesh_submesh_snapshot"),
            patch("cdmw.services.mesh_service.clone_mesh_for_editing", side_effect=AssertionError("full clone")),
        ):
            service = MeshService()
            view = service.open_edit_session(mesh, session_id="native-clone-preview-texture", mode="edit")
            cloned = service.working_mesh(view.session_id, clone=True)

        submesh = cloned.submeshes[0]
        self.assertEqual("C:/cache/body.dds", submesh.preview_texture_path)
        self.assertEqual("C:/cache/body.dds", submesh.preview_texture_dds_path)
        self.assertEqual("base", submesh.preview_material_texture_inputs[0].semantic_type)
