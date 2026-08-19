"""Gates for the effect placement dialog's viewport controls: the legend, the standing
views, the places on the item, and what the character checkbox hides.

The dialog builds its viewport through a host factory, so a stand-in host records what
the dialog asked the viewport for without a helper process anywhere near the test.
"""

from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QObject, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh  # noqa: E402
from cdmw.services.effect_placement_preview import EffectPlacementPreview  # noqa: E402
from cdmw.ui.new_item.effect_placement_dialog import (  # noqa: E402
    STANDING_VIEW_ANGLES,
    EffectPlacementDialog,
)


def _blade() -> ParsedMesh:
    """A sword as the game holds one: the origin is the hand, the blade runs to -z."""

    vertices = [(-0.02, 0.0, -0.9), (0.02, 0.0, -0.9), (0.02, 0.0, 0.2), (-0.02, 0.0, 0.2)]
    submesh = SubMesh(
        name="blade", material="steel", vertices=vertices, uvs=[(0.0, 0.0)] * 4,
        normals=[(0.0, 1.0, 0.0)] * 4, faces=[(0, 1, 2), (0, 2, 3)], vertex_count=4, face_count=2,
    )
    return ParsedMesh(
        path="blade.pac", format="pac", submeshes=[submesh],
        bbox_min=(-0.02, 0.0, -0.9), bbox_max=(0.02, 0.0, 0.2),
        total_vertices=4, total_faces=2, has_uvs=True,
    )


class _Controller(QObject):
    state_changed = Signal(str, str)
    capabilities: tuple = ("effect_particle_preview_v1",)


class _Host(QWidget):
    """What the dialog asks a viewport to do, written down instead of drawn."""

    alignment_drag_finished = Signal(float, float, float)
    alignment_scale_finished = Signal(float, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.views: list = []
        self.hidden: tuple = ()
        self.controller = _Controller(self)

    def set_view(self, *, yaw, pitch, zoom_factor=None, fit_to_view=None, **_rest) -> bool:
        self.views.append((float(yaw), float(pitch), fit_to_view))
        return True

    def set_hidden_source_submeshes(self, indices) -> bool:
        self.hidden = tuple(int(index) for index in indices)
        return True

    def set_alignment_preview_transform(self, **_payload) -> bool:
        return True


class DialogTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.app = QApplication.instance() or QApplication([])

    def _dialog(self, **overrides) -> EffectPlacementDialog:
        dialog = EffectPlacementDialog(
            item_mesh=_blade(), box_min=(-11.0, -10.0, -11.0), box_max=(11.0, 17.0, 11.0),
            host_factory=lambda parent: _Host(parent), **overrides,
        )
        dialog._preview = EffectPlacementPreview(
            package_dir=Path("."), box_submesh_index=0, item_submesh_count=1,
            box_min=(-11.0, -10.0, -11.0), box_max=(11.0, 17.0, 11.0),
            reach_submesh_index=1, body_submesh_index=3,
        )
        self.addCleanup(dialog.deleteLater)
        return dialog

    def _legend(self, dialog) -> list:
        return [key for key, label in dialog.legend_rows.items() if not label.isHidden()]

    def test_the_legend_names_what_is_on_screen_and_nothing_else(self) -> None:
        dialog = self._dialog()
        dialog.show_character.setChecked(True)
        dialog.show_reach.setChecked(True)
        self.assertEqual(self._legend(dialog), ["anchor", "item", "body", "reach", "particles"])
        dialog.show_character.setChecked(False)
        dialog.show_reach.setChecked(False)
        # the anchor, the item and the particles are always drawn, so they are always named
        self.assertEqual(self._legend(dialog), ["anchor", "item", "particles"])
        self.assertIn("character", dialog.legend_rows["body"].text())
        self.assertIn("1.75 m", dialog.legend_rows["body"].text())

    def test_the_standing_views_turn_the_camera_and_fit_the_item_again(self) -> None:
        dialog = self._dialog()
        self.assertEqual(len(dialog.view_buttons), len(STANDING_VIEW_ANGLES))
        self.assertEqual([button.text() for button in dialog.view_buttons], ["Front", "Side", "Top", "Angled"])
        for button in dialog.view_buttons:
            button.click()
        self.assertEqual(
            dialog.host.views,
            [(yaw, pitch, True) for yaw, pitch in STANDING_VIEW_ANGLES],
        )

    def test_the_places_on_the_item_move_the_offset_along_its_long_axis(self) -> None:
        """Three spin boxes and a mesh whose long axis is not obvious make placing an
        effect on the blade a guessing game; the buttons answer it in one click."""

        dialog = self._dialog(offset=(0.3, 0.3, 0.3))
        places = {button.text(): button for button in dialog.findChildren(type(dialog.fit_button))}
        places["Hand"].click()
        self.assertEqual(dialog.offset, (0.0, 0.0, 0.0), "the hand is the item's own origin")
        places["Tip"].click()
        # the blade runs from z 0.2 back to z -0.9, so the tip is the far end of z
        self.assertAlmostEqual(dialog.offset[2], -0.9 * 0.92, places=3)
        self.assertAlmostEqual(dialog.offset[0], 0.0, places=3)
        places["Middle"].click()
        self.assertAlmostEqual(dialog.offset[2], -0.35, places=3)

    def test_hiding_the_character_and_the_reach_hides_those_submeshes(self) -> None:
        dialog = self._dialog()
        dialog.show_reach.setChecked(True)
        dialog.show_character.setChecked(True)
        dialog._apply_scene_visibility()
        self.assertEqual(dialog.host.hidden, ())
        dialog.show_character.setChecked(False)
        self.assertEqual(dialog.host.hidden, (3,), "the character's submesh, not the item's")
        dialog.show_reach.setChecked(False)
        self.assertEqual(dialog.host.hidden, (1, 3))
        self.assertTrue(dialog.legend_rows["body"].isHidden(), "the legend follows what is drawn")

    def test_a_reach_far_larger_than_the_item_starts_hidden(self) -> None:
        dialog = self._dialog()
        self.assertFalse(dialog.show_reach.isChecked())
        self.assertIn("far larger than the item", dialog.size_label.text())


if __name__ == "__main__":
    unittest.main()
