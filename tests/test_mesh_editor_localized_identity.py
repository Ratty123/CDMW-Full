from __future__ import annotations

import unittest

from PySide6.QtWidgets import QApplication, QTabWidget

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
