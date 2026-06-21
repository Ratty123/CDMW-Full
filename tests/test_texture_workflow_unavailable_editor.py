from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from cdmw.ui.texture_workflow.unavailable_editor import UnavailableTextureEditorTab


class TextureWorkflowUnavailableEditorTests(unittest.TestCase):
    def test_unavailable_editor_exposes_texture_editor_protocol(self) -> None:
        app = QApplication.instance() or QApplication([])
        missing = ModuleNotFoundError("missing dependency")
        missing.name = "cv2"
        tab = UnavailableTextureEditorTab(missing)

        self.assertIn("cv2", tab._message)
        self.assertTrue(hasattr(tab, "status_message_requested"))
        self.assertTrue(hasattr(tab, "browse_archive_requested"))
        self.assertTrue(hasattr(tab, "open_in_compare_requested"))
        tab.sync_ui_font_from_application()
        tab.flush_settings_save()
        tab.shutdown()
        app.processEvents()
        tab.deleteLater()


if __name__ == "__main__":
    unittest.main()
