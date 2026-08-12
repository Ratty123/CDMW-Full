from __future__ import annotations

import unittest
from types import SimpleNamespace

from PySide6.QtWidgets import QApplication, QTabWidget

from cdmw.domain.mesh import (
    MeshEditSelection,
    MeshUvIslandSummary,
    MeshUvSummary,
)
from cdmw.ui.mesh_editor.tab_state import MeshEditorStateMixin
from cdmw.ui.mesh_editor.workspace import MeshEditorWorkspace


class MeshEditorLocalizedIdentityTests(unittest.TestCase):
    """Panels and captions must be found by identity, never by displayed text."""

    def test_report_panes_focus_after_the_captions_are_translated(self) -> None:
        from pathlib import Path as _Path

        from cdmw.ui.localization import UiLocalizer

        app = QApplication.instance() or QApplication([])
        workspace = MeshEditorWorkspace()
        panels = workspace.findChild(QTabWidget, "MeshEditorRightPanels")
        assert panels is not None

        german = UiLocalizer(language_dir=_Path("__unused__"), language_code="de")
        german.apply(workspace)
        app.processEvents()
        # Guard the premise: if the captions stopped being translated this test would
        # pass for the wrong reason.
        checks_index = next(
            index
            for index in range(panels.count())
            if panels.widget(index) is workspace._right_panels_by_title["checks"]
        )
        self.assertNotEqual("Checks", panels.tabText(checks_index))

        panels.setCurrentIndex(0)
        workspace._focus_right_panel("Checks")
        self.assertEqual(checks_index, panels.currentIndex())

        panels.setCurrentIndex(0)
        workspace._focus_right_panel("Rebuild")
        self.assertIs(
            workspace._right_panels_by_title["rebuild"],
            panels.widget(panels.currentIndex()),
        )

        panels.setCurrentIndex(0)
        workspace._focus_right_panel("Rig")
        self.assertIs(
            workspace._right_panels_by_title["rig"],
            panels.widget(panels.currentIndex()),
        )

        workspace.deleteLater()
        app.processEvents()

    def test_localized_uv_panel_uses_identity_for_cached_selection_refresh(self) -> None:
        from pathlib import Path as _Path

        from cdmw.ui.localization import UiLocalizer

        app = QApplication.instance() or QApplication([])
        workspace = MeshEditorWorkspace()
        panels = workspace.findChild(QTabWidget, "MeshEditorRightPanels")
        assert panels is not None
        workspace.update_uv_summary(
            MeshUvSummary(
                island_count=1,
                selected_island_count=0,
                islands=(
                    MeshUvIslandSummary(
                        index=0,
                        submesh_index=0,
                        part_name="quad",
                        material="mat",
                        texture="quad.dds",
                        vertex_count=6,
                        face_count=4,
                        uv_min=(0.0, 0.0),
                        uv_max=(1.0, 1.0),
                        face_indices=(0, 0, 0, 0),
                    ),
                ),
            )
        )
        german = UiLocalizer(language_dir=_Path("__unused__"), language_code="de")
        german.apply(workspace)
        uv_panel = workspace._right_panels_by_title["uv map"]
        uv_index = next(
            index for index in range(panels.count()) if panels.widget(index) is uv_panel
        )
        panels.setCurrentIndex(uv_index)
        self.assertNotEqual("UV Map", panels.tabText(uv_index))
        harness = SimpleNamespace(
            embedded_workspace=workspace,
            _embedded_builder_controller=lambda: object(),
        )

        MeshEditorStateMixin._refresh_embedded_active_selection_summary(
            harness,
            selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
        )

        summary = workspace._uv_summary
        assert summary is not None
        self.assertEqual(1, summary.selected_island_count)
        self.assertEqual(4, summary.islands[0].selected_face_count)
        workspace.deleteLater()
        app.processEvents()
