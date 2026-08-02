"""Mirrored Edit Mesh combos must never invent a value the reader did not pick.

The compact toolbar and the panel each carry a Selection Target, Selection Depth
and Falloff combo, wired to each other in both directions. Each connection read
`max(0, other.findData(value))` -- and `findData` answers -1 when the value is
not in the other combo, so `max(0, -1)` selected index 0. Index 0 of the
selection combos is Vertex.

Choosing Face therefore wrote Face into one combo, failed to find it in the
other, set that one to Vertex, and the reverse connection carried Vertex
straight back. The reader watched their choice revert a frame after making it,
and no log recorded anything, because nothing had failed.
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QComboBox  # noqa: E402

from cdmw.ui.archive_browser.static_replacement_dialog_sections_mesh_geometry_preview_part_01 import (  # noqa: E402
    mirror_mesh_edit_combo_pair,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _combo(entries: list[tuple[str, str]]) -> QComboBox:
    _app()
    combo = QComboBox()
    for label, data in entries:
        combo.addItem(label, data)
    return combo


SELECTION = [("Vertex", "vertex"), ("Edge", "edge"), ("Face", "face")]


class MeshEditComboMirrorTests(unittest.TestCase):
    def test_a_shared_value_mirrors_both_ways(self) -> None:
        first, second = _combo(SELECTION), _combo(SELECTION)
        mirror_mesh_edit_combo_pair(first, second)
        first.setCurrentIndex(2)
        self.assertEqual(second.currentData(), "face")
        second.setCurrentIndex(1)
        self.assertEqual(first.currentData(), "edge")

    def test_choosing_face_does_not_revert_to_vertex(self) -> None:
        """The reported symptom, with the combos deliberately mismatched."""

        full = _combo(SELECTION)
        partial = _combo([("Vertex", "vertex"), ("Edge", "edge")])  # no Face
        mirror_mesh_edit_combo_pair(full, partial)
        full.setCurrentIndex(2)
        self.assertEqual(full.currentData(), "face", "the reader's choice was overwritten")
        self.assertEqual(partial.currentData(), "vertex", "the other combo invented a value")

    def test_an_unknown_value_leaves_the_other_combo_untouched(self) -> None:
        full = _combo(SELECTION)
        partial = _combo([("Vertex", "vertex"), ("Edge", "edge")])
        partial.setCurrentIndex(1)
        mirror_mesh_edit_combo_pair(full, partial)
        full.setCurrentIndex(2)
        self.assertEqual(partial.currentData(), "edge", "an unknown value reset the other combo")

    def test_mirroring_does_not_echo_back_and_forth(self) -> None:
        """Both directions are wired, so an unguarded pair re-enters."""

        first, second = _combo(SELECTION), _combo(SELECTION)
        seen: list[int] = []
        first.currentIndexChanged.connect(seen.append)
        mirror_mesh_edit_combo_pair(first, second)
        second.setCurrentIndex(2)
        self.assertEqual(first.currentData(), "face")
        self.assertEqual(seen, [2], f"the mirror echoed: {seen}")

    def test_setting_the_same_value_changes_nothing(self) -> None:
        first, second = _combo(SELECTION), _combo(SELECTION)
        mirror_mesh_edit_combo_pair(first, second)
        first.setCurrentIndex(1)
        seen: list[int] = []
        second.currentIndexChanged.connect(seen.append)
        first.setCurrentIndex(1)
        self.assertEqual(seen, [])


if __name__ == "__main__":
    unittest.main()
