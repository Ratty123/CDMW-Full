from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QColor, QPalette  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from cdmw.ui.new_item.workflow_header import (  # noqa: E402
    ACTIVE_DARK_COLOR,
    DEFAULT_STEP_LABELS,
    WorkflowStepState,
    WorkflowHeader,
)


class WorkflowHeaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def setUp(self) -> None:
        self.header = WorkflowHeader()
        self.header.resize(1280, self.header.sizeHint().height())
        self.header.show()
        self.app.processEvents()

    def tearDown(self) -> None:
        self.header.close()
        self.header.deleteLater()
        self.app.processEvents()

    def test_default_steps_and_compatibility_api(self) -> None:
        self.assertEqual(self.header.count(), 7)
        self.assertEqual(self.header.currentRow(), 0)
        self.assertEqual(
            [self.header.item(index).text() for index in range(self.header.count())],
            list(DEFAULT_STEP_LABELS),
        )
        self.assertIsNone(self.header.item(-1))
        self.assertIsNone(self.header.item(self.header.count()))

    def test_click_selects_step_and_emits_once_for_a_change(self) -> None:
        changed: list[int] = []
        self.header.currentRowChanged.connect(changed.append)
        button = self.header.stepButton(3)
        self.assertIsNotNone(button)
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.header.currentRow(), 3)
        self.assertEqual(changed, [3])
        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(changed, [3], "selecting the current row does not emit again")

    def test_keyboard_navigation_clamps_at_bounds_and_supports_home_end(self) -> None:
        changed: list[int] = []
        self.header.currentRowChanged.connect(changed.append)
        self.header.setFocus()
        QTest.keyClick(self.header, Qt.Key.Key_Right)
        QTest.keyClick(self.header, Qt.Key.Key_Right)
        QTest.keyClick(self.header, Qt.Key.Key_Left)
        self.assertEqual(self.header.currentRow(), 1)
        QTest.keyClick(self.header, Qt.Key.Key_End)
        self.assertEqual(self.header.currentRow(), self.header.count() - 1)
        QTest.keyClick(self.header, Qt.Key.Key_Right)
        self.assertEqual(self.header.currentRow(), self.header.count() - 1)
        QTest.keyClick(self.header, Qt.Key.Key_Home)
        self.assertEqual(self.header.currentRow(), 0)
        QTest.keyClick(self.header, Qt.Key.Key_Left)
        self.assertEqual(self.header.currentRow(), 0)
        self.assertEqual(changed, [1, 2, 1, 6, 0])

    def test_keyboard_navigation_also_works_from_a_step_button(self) -> None:
        button = self.header.stepButton(0)
        self.assertIsNotNone(button)
        button.setFocus()
        QTest.keyClick(button, Qt.Key.Key_Right)
        self.assertEqual(self.header.currentRow(), 1)
        self.assertTrue(self.header.stepButton(1).hasFocus())
        QTest.keyClick(self.header.stepButton(1), Qt.Key.Key_End)
        self.assertEqual(self.header.currentRow(), 6)

    def test_invalid_rows_are_ignored_without_signal(self) -> None:
        changed: list[int] = []
        self.header.currentRowChanged.connect(changed.append)
        self.assertFalse(self.header.setCurrentRow(-1))
        self.assertFalse(self.header.setCurrentRow(self.header.count()))
        self.assertFalse(self.header.setCurrentRow("not-a-row"))
        self.assertEqual(self.header.currentRow(), 0)
        self.assertEqual(changed, [])
        self.assertTrue(self.header.setCurrentRow(2))
        self.assertEqual(self.header.currentRow(), 2)

    def test_navigation_promotes_active_and_completed_semantic_states(self) -> None:
        self.assertEqual(self.header.stepState(0), WorkflowStepState.ACTIVE)
        self.assertEqual(self.header.stepState(1), WorkflowStepState.PENDING)

        self.assertTrue(self.header.setCurrentRow(2))
        self.assertEqual(self.header.stepState(0), WorkflowStepState.COMPLETED)
        self.assertEqual(self.header.stepState(2), WorkflowStepState.ACTIVE)
        self.assertEqual(self.header.stepButton(0).property("workflowState"), "completed")
        self.assertEqual(self.header.stepButton(2).property("workflowState"), "active")
        self.assertTrue(self.header.stepButton(2).property("active"))
        self.assertTrue(self.header.stepButton(0).property("completed"))

    def test_blocked_state_is_painted_and_remains_blocked_when_selected(self) -> None:
        item = self.header.item(4)
        self.assertIsNotNone(item)
        self.assertTrue(item.setState(WorkflowStepState.BLOCKED))
        self.assertEqual(item.state(), WorkflowStepState.BLOCKED)
        button = self.header.stepButton(4)
        self.assertEqual(button.property("workflowState"), "blocked")
        self.assertTrue(button.property("workflowBlocked"))
        self.assertEqual(button.property("state"), "blocked")
        self.assertTrue(button.property("blocked"))
        self.assertIn("blocked", button.accessibleDescription())

        QTest.mouseClick(button, Qt.MouseButton.LeftButton)
        self.assertEqual(self.header.currentRow(), 4)
        self.assertEqual(self.header.stepState(4), WorkflowStepState.BLOCKED)
        self.assertTrue(button.property("workflowActive"))
        self.assertTrue(button.property("workflowBlocked"))

    def test_step_metadata_is_available_to_the_parent(self) -> None:
        self.assertTrue(self.header.setStepToolTip(2, "Choose the model and icon."))
        self.assertEqual(self.header.item(2).toolTip(), "Choose the model and icon.")
        self.assertTrue(self.header.setItemAccessibleText(2, "Model and icon: needs review"))
        self.assertEqual(self.header.stepButton(2).accessibleName(), "Model and icon: needs review")
        self.assertTrue(self.header.setItemData(2, 9001, {"valid": False}))
        self.assertEqual(self.header.itemData(2, 9001), {"valid": False})
        self.assertFalse(self.header.setStepToolTip(99, "ignored"))

    def test_header_geometry_has_equal_slots_at_supported_widths(self) -> None:
        for width in (1280, 1600):
            self.header.resize(width, self.header.sizeHint().height())
            self.app.processEvents()
            buttons = [self.header.stepButton(index) for index in range(self.header.count())]
            centers = [button.mapTo(self.header, button.circle_rect().center()) for button in buttons]
            self.assertEqual(len({center.y() for center in centers}), 1)
            self.assertEqual(centers, sorted(centers, key=lambda point: point.x()))
            gaps = [centers[index + 1].x() - centers[index].x() for index in range(6)]
            self.assertLessEqual(max(gaps) - min(gaps), 1)
            for button in buttons:
                circle = button.circle_rect()
                self.assertEqual(circle.width(), 32)
                self.assertEqual(circle.height(), 32)
                self.assertEqual(button.height(), self.header.height())

    def test_dark_palette_uses_required_active_cyan(self) -> None:
        palette = QPalette()
        palette.setColor(QPalette.ColorRole.Window, QColor("#20242a"))
        palette.setColor(QPalette.ColorRole.WindowText, QColor("#f4f6f8"))
        palette.setColor(QPalette.ColorRole.Highlight, QColor("#ff00ff"))
        self.header.setPalette(palette)
        self.app.processEvents()
        self.assertEqual(self.header._active_color.name(), ACTIVE_DARK_COLOR.name())


if __name__ == "__main__":
    unittest.main()
