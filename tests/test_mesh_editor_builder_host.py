from __future__ import annotations

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTreeWidgetItem

from cdmw.ui.mesh_editor.builder_host import MeshReplacementPartsOutlinerTree


class MeshEditorBuilderHostTests(unittest.TestCase):
    def test_parts_outliner_tree_stores_drop_handler(self) -> None:
        app = QApplication.instance() or QApplication([])
        tree = MeshReplacementPartsOutlinerTree()
        item = QTreeWidgetItem(["part"])
        tree.addTopLevelItem(item)
        calls: list[tuple[object, object]] = []

        def _handler(source: object, target: object) -> bool:
            calls.append((source, target))
            return True

        tree.set_source_drop_handler(_handler)
        self.assertEqual("part", tree.topLevelItem(0).text(0))
        self.assertIs(tree._source_drop_handler, _handler)
        app.processEvents()
        tree.deleteLater()


if __name__ == "__main__":
    unittest.main()
