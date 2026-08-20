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
        self.zooms: list = []
        self.hidden: tuple = ()
        self.particles: list = []
        self.transforms: list = []
        self.paused: list = []
        self.backdrops: list = []
        self.remembered: tuple = ()
        self.loaded = None
        self.controller = _Controller(self)

    def set_view(self, *, yaw, pitch, zoom_factor=None, fit_to_view=None, **_rest) -> bool:
        self.views.append((float(yaw), float(pitch), fit_to_view))
        self.zooms.append(None if zoom_factor is None else round(float(zoom_factor), 4))
        return True

    def view_state_snapshot(self) -> dict:
        yaw, pitch, _fit = self.views[-1] if self.views else (-35.0, 20.0, True)
        return {"yaw": yaw, "pitch": pitch}

    def set_effect_particles_visible(self, visible: bool) -> bool:
        self.particles.append(bool(visible))
        return True

    def set_hidden_source_submeshes(self, indices) -> bool:
        self.hidden = tuple(int(index) for index in indices)
        return True

    def set_effect_particles_paused(self, paused: bool) -> bool:
        self.paused.append(bool(paused))
        return True

    def set_viewport_backdrop(self, color: str) -> bool:
        self.backdrops.append(str(color))
        return True

    def set_alignment_preview_transform(self, **payload) -> bool:
        self.transforms.append(payload)
        return True

    def remember_editable_local_bounds(self, low, high) -> None:
        self.remembered = (tuple(float(v) for v in low), tuple(float(v) for v in high))

    def load_package(self, package_dir, reset_view: bool = False) -> bool:
        self.loaded = Path(package_dir)
        return True

    def set_display_mode(self, mode: str) -> bool:
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

    def _settle(self, done, timeout_ms: int = 20_000) -> None:
        """Run the event loop until `done()` or the deadline; a worker thread is only
        finished once the main thread has processed the signals that say so."""

        from PySide6.QtCore import QDeadlineTimer, QEventLoop

        deadline = QDeadlineTimer(timeout_ms)
        while not done() and not deadline.hasExpired():
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

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

    def test_the_particles_can_be_taken_off_the_item(self) -> None:
        """An effect's fire is a wall of additive sprites, and a placement judged against
        the blade under it needs the blade without the fire on top for a moment."""

        dialog = self._dialog()
        self.assertTrue(dialog.show_particles.isChecked())
        dialog.show_particles.setChecked(False)
        self.assertEqual(dialog.host.particles, [False])
        self.assertTrue(dialog.legend_rows["particles"].isHidden(), "the legend follows what is drawn")
        dialog.show_particles.setChecked(True)
        self.assertEqual(dialog.host.particles, [False, True])
        self.assertFalse(dialog.legend_rows["particles"].isHidden())

    def test_showing_the_reach_zooms_out_far_enough_to_see_it(self) -> None:
        """The frame of an effect made for a boss is twenty metres across a one-metre
        sword: shown at the item's own zoom it is off every edge of the view, so ticking
        the box changed nothing anyone could see."""

        dialog = self._dialog()
        dialog.show_reach.setChecked(True)
        self.assertTrue(dialog.host.zooms, "the camera was sent")
        zoomed = dialog.host.zooms[-1]
        self.assertLess(zoomed, 0.2, "the view holds a reach twenty times the item")
        self.assertGreaterEqual(zoomed, 0.1, "and no further than the host allows")
        dialog.show_reach.setChecked(False)
        self.assertEqual(dialog.host.zooms[-1], 1.0, "back to the item")
        # a standing view keeps whatever the subject needs
        dialog.show_reach.setChecked(True)
        dialog.view_buttons[1].click()
        self.assertEqual(dialog.host.views[-1][:2], (90.0, 8.0))
        self.assertLess(dialog.host.zooms[-1], 0.2)

    def test_an_effect_whose_spawn_mesh_is_missing_says_so_where_it_is_read(self) -> None:
        """A third of the shipped emitters spawn their particles on the surface of a mesh,
        and the archives do not carry all of those meshes. The preview scatters them
        instead, which looked like a compact cloud on the hammer head while the game drew
        a metre of fire along the weapon: the reader has to be told before they trust it."""

        from types import SimpleNamespace

        preview = SimpleNamespace(
            emitters=(),
            notes=("emitter/cdem_x: spawn mesh pafx_m_ds_firesword_trail_002a.pam was not read; particles spawn in a spread instead",),
        )
        dialog = self._dialog(effect_preview=preview)
        dialog._show_caveats()
        self.assertFalse(dialog.caveat.isHidden())
        self.assertIn("pafx_m_ds_firesword_trail_002a.pam", dialog.caveat.text())
        # the line stays short; the detail moved to its tooltip, because a paragraph here
        # pushed the controls above it off a short panel
        self.assertLess(len(dialog.caveat.text()), 160, dialog.caveat.text())
        self.assertIn("stand-in", dialog.caveat.toolTip())

        quiet = self._dialog(effect_preview=SimpleNamespace(emitters=(), notes=()))
        quiet._show_caveats()
        self.assertTrue(quiet.caveat.isHidden())

    def test_the_numbers_stay_the_item_s_while_the_picture_is_the_character_s(self) -> None:
        """The scene is the character standing upright, which is a turn away from the item's
        own frame; the offsets are the item's, because that is what the game reads off the
        weapon's prefab. So an offset goes out turned, and a drag comes back turned back."""

        from cdmw.services.effect_character_reference import rotate_point

        # a quarter turn about x: the item's +z, its blade, becomes the scene's -y
        quarter = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)
        dialog = self._dialog()
        dialog._preview = EffectPlacementPreview(
            package_dir=Path("."), box_submesh_index=0, item_submesh_count=1,
            box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
            reach_submesh_index=1, body_submesh_index=3, item_rotation=quarter,
        )
        dialog._rotation = quarter
        dialog._set_numbers((0.0, 0.0, 0.5), 1.0)
        dialog._sync_host()
        sent = dialog.host.transforms[-1]["translation"]
        self.assertEqual(tuple(round(v, 6) for v in sent), tuple(round(v, 6) for v in rotate_point((0.0, 0.0, 0.5), quarter)))

        # the reader drags a tenth of a metre up the screen; up is not the item's y
        dialog._drag_finished(0.0, 0.1, 0.0)
        self.assertEqual(tuple(round(v, 6) for v in dialog.offset), (0.0, 0.0, 0.4))

        # and with no character the scene is the item's frame, untouched
        plain = self._dialog()
        plain._set_numbers((0.0, 0.0, 0.5), 1.0)
        plain._sync_host()
        self.assertEqual(tuple(plain.host.transforms[-1]["translation"]), (0.0, 0.0, 0.5))
        plain._drag_finished(0.0, 0.1, 0.0)
        self.assertEqual(tuple(round(v, 6) for v in plain.offset), (0.0, 0.1, 0.5))

    def test_the_character_s_submeshes_all_hide_together(self) -> None:
        """The game's character is several meshes; hiding one of them leaves the rest."""

        dialog = self._dialog()
        dialog._preview = EffectPlacementPreview(
            package_dir=Path("."), box_submesh_index=0, item_submesh_count=1,
            box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
            reach_submesh_index=1, body_submesh_index=3, body_submesh_count=4,
        )
        dialog.show_reach.setChecked(True)
        dialog.show_character.setChecked(False)
        self.assertEqual(dialog.host.hidden, (3, 4, 5, 6))

    def test_the_dialog_builds_its_package_with_the_character_it_is_handed(self) -> None:
        """The whole path in one go: the builder runs on the worker thread, its character
        and rotation reach the package, and what comes back turns the dialog's frame and
        the words that promised a stand-in."""

        import tempfile
        from types import SimpleNamespace

        from cdmw.services.effect_character_reference import CHARACTER_SUBMESH_PREFIX

        quarter = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)
        body = SubMesh(
            name=f"{CHARACTER_SUBMESH_PREFIX}0", material=f"{CHARACTER_SUBMESH_PREFIX}body",
            vertices=[(0.0, 0.0, 0.0), (0.1, 0.0, 0.0), (0.0, 1.8, 0.0)], uvs=[(0.0, 0.0)] * 3,
            normals=[(0.0, 0.0, 1.0)] * 3, faces=[(0, 1, 2)], vertex_count=3, face_count=1,
        )
        character = SimpleNamespace(
            mesh=ParsedMesh(
                path="body.pac", format="pac", submeshes=[body], bbox_min=(0.0, 0.0, 0.0),
                bbox_max=(0.1, 1.8, 0.0), total_vertices=3, total_faces=1, has_uvs=True,
            ),
            item_rotation=quarter,
        )
        folder = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        dialog = self._dialog(output_root=Path(folder.name), character_builder=lambda: character)
        # the worker writes into that folder, so it has to be done with it before the
        # folder goes: cleanups run last-registered-first, so this one runs first
        self.addCleanup(lambda: self._settle(lambda: dialog._thread is None))
        dialog._preview = None
        self.assertIn("1.75 m", dialog.legend_rows["body"].text(), "the stand-in's words until one arrives")

        dialog._start_package()
        self._settle(lambda: dialog._preview is not None)
        self.assertIsNotNone(dialog._preview, "the package was built")
        self.assertEqual(dialog._preview.item_rotation, quarter, "the rotation went in and came back")
        self.assertEqual(dialog._rotation, quarter, "and the dialog carries its numbers across it")
        self.assertEqual(dialog._preview.body_submesh_count, 1)
        self.assertIn("game's character", dialog.legend_rows["body"].text())
        self.assertIn("the angle the game holds it", dialog.show_character.toolTip())
        dialog._closed = True

    def test_the_trail_button_appears_only_when_the_item_has_its_own_trail(self) -> None:
        """Weapons share socket files, so a borrowed one puts the trail at another weapon's
        tip. The button is the game's own answer or it is not offered at all."""

        from cdmw.services.effect_character_reference import TRAIL_SOCKET

        dialog = self._dialog()
        dialog._offer_the_trail_socket()
        self.assertFalse(dialog.trail_button.isVisible(), "nothing read yet, nothing offered")

        dialog._effect_sockets = (("FX_Muzzle_00_Socket", (0.0, 0.0, -0.4)),)
        dialog._offer_the_trail_socket()
        self.assertFalse(dialog.trail_button.isVisible(), "a muzzle is not a trail")

        dialog._effect_sockets = ((TRAIL_SOCKET, (0.0, 0.02, -1.1)),)
        dialog._offer_the_trail_socket()
        self.assertTrue(dialog.trail_button.isVisibleTo(dialog), "the item's own trail is offered")
        self.assertIn("-1.10", dialog.trail_button.toolTip(), "and the tooltip says where it is")

        dialog._put_it_at("trail")
        self.assertEqual(tuple(round(v, 6) for v in dialog.offset), (0.0, 0.02, -1.1))

    def test_the_particles_can_be_held_where_they_are(self) -> None:
        """Hiding the fire answers "what is under it". Holding it answers "where exactly is
        this one", which a cloud in motion never lets anyone read."""

        dialog = self._dialog()
        self.assertFalse(dialog.pause_button.isChecked())
        dialog.pause_button.setChecked(True)
        self.assertEqual(dialog.host.paused, [True])
        self.assertEqual(dialog.pause_button.text(), "Paused", "the button says which state it is in")
        dialog.pause_button.setChecked(False)
        self.assertEqual(dialog.host.paused, [True, False])
        self.assertEqual(dialog.pause_button.text(), "Pause")
        self.assertEqual(dialog.host.particles, [], "pausing is not hiding")

    def test_the_backdrop_is_chosen_and_remembered(self) -> None:
        """An effect adds its light to what is behind it, so it reads best on a dark
        backdrop; the Mesh Editor's grey is there for judging the item's own textures,
        which is the other half of what this dialog is for."""

        from cdmw.ui.new_item.effect_placement_dialog import BACKDROPS, _remembered_backdrop

        dialog = self._dialog()
        self.assertEqual([dialog.backdrop_choice.itemData(row) for row in range(dialog.backdrop_choice.count())],
                         list(BACKDROPS))
        self.assertEqual(dialog.backdrop_choice.currentData(), _remembered_backdrop(), "it opens on the last one chosen")

        grey = BACKDROPS.index("#3B3B3B")
        dialog.backdrop_choice.setCurrentIndex(grey)
        self.assertEqual(dialog.host.backdrops[-1], "#3B3B3B", "the viewport is told")
        self.assertEqual(_remembered_backdrop(), "#3B3B3B", "and the next dialog opens on it")

        dark = BACKDROPS.index("#101014")
        dialog.backdrop_choice.setCurrentIndex(dark)
        self.assertEqual(_remembered_backdrop(), "#101014")

    def test_the_panel_is_grouped_and_the_legend_folds_away(self) -> None:
        """Fourteen controls, five legend rows and four labels in one column read as a
        wall. What moves the effect and what is drawn are two questions, and the legend
        answers a third that is asked once."""

        from PySide6.QtWidgets import QGroupBox

        dialog = self._dialog()
        groups = [box.title() for box in dialog.findChildren(QGroupBox)]
        self.assertEqual(groups, ["Place the effect", "What is drawn"])
        self.assertFalse(dialog.legend_toggle.toggle.isChecked(), "the legend starts folded")
        for label in dialog.legend_rows.values():
            self.assertFalse(label.isVisibleTo(dialog), "and its rows are not taking room")
        dialog.legend_toggle.toggle.setChecked(True)
        self.assertTrue(dialog.legend_rows["anchor"].isVisibleTo(dialog), "one click and it is there")

    def test_a_reach_far_larger_than_the_item_starts_hidden(self) -> None:
        dialog = self._dialog()
        self.assertFalse(dialog.show_reach.isChecked())
        self.assertIn("dwarfs the item", dialog.size_label.text())


if __name__ == "__main__":
    unittest.main()
