"""Gates for the effect placement dialog's viewport controls: the legend, the standing
views, the places on the item, and what the character checkbox hides.

The dialog builds its viewport through a host factory, so a stand-in host records what
the dialog asked the viewport for without a helper process anywhere near the test.
"""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from PySide6.QtCore import QObject, QThread, QTimer, Signal  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QScrollArea, QWidget  # noqa: E402

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh  # noqa: E402
from cdmw.services.effect_placement_preview import EffectPlacementPreview  # noqa: E402
from cdmw.ui.new_item.effect_placement_dialog import (  # noqa: E402
    STANDING_VIEW_ANGLES,
    EffectPlacementDialog,
    EffectPlacementWorkspace,
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
    alignment_rotation_finished = Signal(float, float, float)
    alignment_scale_finished = Signal(float, float, float)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.views: list = []
        self.view_roles: list = []
        self.view_fit_roles: list = []
        self.zooms: list = []
        self.hidden: tuple = ()
        self.particles: list = []
        self.transforms: list = []
        self.paused: list = []
        self.backdrops: list = []
        self.camera_bindings: list = []
        self.restored_views: list[dict] = []
        self.gizmo_tools: list = []
        self.remembered: tuple = ()
        self.loaded = None
        self.controller = _Controller(self)

    def set_alignment_gizmo_tool(self, tool: str) -> bool:
        self.gizmo_tools.append(str(tool))
        return True

    def set_view(
        self,
        *,
        yaw,
        pitch,
        zoom_factor=None,
        fit_to_view=None,
        role="replacement",
        fit_role=None,
        **_rest,
    ) -> bool:
        self.views.append((float(yaw), float(pitch), fit_to_view))
        self.view_roles.append(str(role))
        self.view_fit_roles.append(None if fit_role is None else str(fit_role))
        self.zooms.append(None if zoom_factor is None else round(float(zoom_factor), 4))
        return True

    def view_state_snapshot(self) -> dict:
        yaw, pitch, _fit = self.views[-1] if self.views else (-35.0, 20.0, True)
        return {"role": "reference", "yaw": yaw, "pitch": pitch, "zoom_factor": 1.25, "fit_to_view": True}

    def restore_view_state(self, state) -> bool:
        self.restored_views.append(dict(state))
        return True

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

    def set_viewport_display_mode(self, mode: str) -> bool:
        return True

    def set_alignment_state(self, *, enabled: bool) -> bool:
        return True

    def set_camera_drag_bindings(self, **_bindings) -> bool:
        self.camera_bindings.append(dict(_bindings))
        return True


class _AckController(_Controller):
    package_applied = Signal(str, int)


class _AckHost(_Host):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.controller = _AckController(self)
        self.loaded_requests = []

    def load_package(self, package_dir, reset_view: bool = False) -> bool:
        self.loaded = Path(package_dir)
        self.loaded_requests.append((self.loaded, bool(reset_view)))
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
        self.assertEqual(self._legend(dialog), ["anchor", "axes", "item", "body", "reach", "particles"])
        dialog.show_character.setChecked(False)
        dialog.show_reach.setChecked(False)
        # the anchor, its axes, the item and the particles are always drawn, so they
        # are always named
        self.assertEqual(self._legend(dialog), ["anchor", "axes", "item", "particles"])
        self.assertIn("character", dialog.legend_rows["body"].text())
        self.assertIn("1.75 m", dialog.legend_rows["body"].text())

    def test_the_standing_views_turn_the_camera_and_fit_the_item_again(self) -> None:
        dialog = self._dialog()
        self.assertEqual(len(dialog.view_buttons), len(STANDING_VIEW_ANGLES))
        self.assertEqual([button.text() for button in dialog.view_buttons], ["Front", "Side", "Top", "Angled"])
        self.assertTrue(dialog.view_buttons[-1].isChecked(), "the selected opening view is visible")
        for button in dialog.view_buttons:
            button.click()
        self.assertEqual(
            dialog.host.views,
            [(yaw, pitch, True) for yaw, pitch in STANDING_VIEW_ANGLES],
        )
        self.assertEqual(dialog.host.view_roles, ["replacement"] * len(STANDING_VIEW_ANGLES))
        self.assertEqual(dialog.host.view_fit_roles, ["reference"] * len(STANDING_VIEW_ANGLES))

    def test_camera_frames_the_item_through_the_visible_overlay_role(self) -> None:
        """Overlay draws through the editable camera. Camera commands sent to the
        reference role update a hidden stored view and leave the item as a dot."""

        dialog = self._dialog(offset=(3.704, 0.756, -0.344), scale=0.6)
        dialog._host_state("ready", "")
        self.assertEqual(dialog.host.remembered, (), "the editable role keeps its own bounds")
        self.assertEqual(dialog.host.view_roles[-1], "replacement", "the opening fit drives the visible overlay")
        self.assertEqual(dialog.host.view_fit_roles[-1], "reference", "the item supplies the fit bounds")

        dialog._fit_reach_to_item()
        self.assertEqual(dialog.host.view_roles[-1], "replacement", "Fit keeps driving the visible overlay")
        self.assertEqual(dialog.host.view_fit_roles[-1], "reference", "Fit remains centred on the item")
        self.assertEqual(dialog.host.zooms[-1], 1.0, "an item-sized reach uses the item fit")
        self.assertLess(dialog.scale, 0.1, "the reported large-reach case is represented")

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

    def test_a_wearable_origin_starts_the_gizmo_on_the_applied_helmet(self) -> None:
        helmet = _blade()
        helmet._cdmw_effect_item_origin = (0.01, 1.76, -0.05)
        workspace = EffectPlacementWorkspace(
            item_mesh=helmet,
            box_min=(-1.0, -1.0, -1.0),
            box_max=(1.0, 1.0, 1.0),
            host_factory=lambda parent: _Host(parent),
            compatibility_ui=True,
        )
        self.addCleanup(workspace.request_shutdown)
        self.addCleanup(workspace.deleteLater)
        workspace._initial_package_timer.stop()
        workspace._preview = EffectPlacementPreview(
            package_dir=Path("."),
            box_submesh_index=0,
            item_submesh_count=1,
            box_min=(-1.0, -1.0, -1.0),
            box_max=(1.0, 1.0, 1.0),
        )

        workspace._sync_host()

        self.assertEqual(workspace.offset, (0.01, 1.76, -0.05))
        self.assertEqual(
            workspace.host.transforms[-1]["translation"],
            (0.01, 1.76, -0.05),
            "neutral placement sends the resident gizmo to the applied model origin",
        )
        workspace._put_it_at("origin")
        self.assertEqual(workspace.offset, (0.01, 1.76, -0.05))

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
        from cdmw.ui.new_item.effect_placement_dialog_support import PlacementFrame

        dialog._frame = PlacementFrame(quarter)
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

    def test_the_rotate_tool_reaches_the_gizmo_and_a_ring_drag_lands_in_the_boxes(self) -> None:
        """The helper's placement gizmo has carried rotate rings all along; the dialog
        now offers them. A ring drag reports scene-frame degree deltas, and the numbers
        the dialog keeps are the item's own."""

        dialog = self._dialog()
        dialog.rotate_button.click()
        self.assertEqual(dialog.host.gizmo_tools, ["rotate"])
        self.assertTrue(dialog.rotate_button.isChecked())
        self.assertFalse(dialog.move_button.isChecked())

        dialog._rotation_finished(0.0, 0.0, 30.0)
        self.assertEqual(dialog.rotation, (0.0, 0.0, 30.0))
        self.assertEqual([spin.value() for spin in dialog.rotation_spins], [0.0, 0.0, 30.0])
        sent = dialog.host.transforms[-1]["rotation_degrees"]
        self.assertEqual(tuple(round(v, 3) for v in sent), (0.0, 0.0, 30.0))
        # a second drag composes rather than replaces
        dialog._rotation_finished(0.0, 0.0, 30.0)
        self.assertEqual(dialog.rotation, (0.0, 0.0, 60.0))

    def test_a_ring_drag_crosses_the_character_frame_back_into_the_item_s(self) -> None:
        """With the character on screen the scene is a turn away from the item's frame:
        the ring the reader drags is the scene's, the numbers stay the item's, and the
        game's transform gets the item-frame turn."""

        from cdmw.ui.new_item.effect_placement_dialog_support import PlacementFrame

        # a quarter turn about x: the item's +z becomes the scene's -y, so the scene's
        # +y ring is the item's -z axis
        quarter = (1.0, 0.0, 0.0, 0.0, 0.0, 1.0, 0.0, -1.0, 0.0)
        dialog = self._dialog()
        dialog._frame = PlacementFrame(quarter)
        dialog._rotation_finished(0.0, 30.0, 0.0)
        self.assertEqual(tuple(round(v, 3) for v in dialog.rotation), (0.0, 0.0, -30.0))
        # and what goes back out to the viewport is the scene's own euler again
        sent = dialog.host.transforms[-1]["rotation_degrees"]
        self.assertEqual(tuple(round(v, 3) for v in sent), (0.0, 30.0, 0.0))

    def test_rotation_spin_edits_and_deltas_share_one_state(self) -> None:
        dialog = self._dialog(rotation=(0.0, 15.0, 0.0))
        self.assertEqual([spin.value() for spin in dialog.rotation_spins], [0.0, 15.0, 0.0])
        dialog.rotation_spins[1].setValue(45.0)
        self.assertEqual(dialog.rotation, (0.0, 45.0, 0.0))
        sent = dialog.host.transforms[-1]["rotation_degrees"]
        self.assertEqual(tuple(round(v, 3) for v in sent), (0.0, 45.0, 0.0))
        dialog.apply_deltas(rotation_delta=(0.0, 0.0, 90.0))
        self.assertEqual(tuple(round(v, 1) for v in dialog.rotation), (0.0, 45.0, 90.0))

    def test_a_turn_past_a_half_circle_reads_as_the_short_way_round(self) -> None:
        dialog = self._dialog()
        dialog._rotation_finished(0.0, 0.0, 170.0)
        dialog._rotation_finished(0.0, 0.0, 40.0)
        self.assertEqual(tuple(round(v, 1) for v in dialog.rotation), (0.0, 0.0, -150.0))

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
        self.assertEqual(dialog._frame.rotation, quarter, "and the dialog carries its numbers across it")
        self.assertEqual(dialog._preview.body_submesh_count, 1)
        self.assertIn("game's character", dialog.legend_rows["body"].text())
        self.assertIn("size reference", dialog.show_character.toolTip())
        dialog._closed = True

    def test_closing_during_package_build_never_waits_on_the_ui_thread(self) -> None:
        output = Path(tempfile.mkdtemp(prefix="cdmw_effect_shutdown_"))

        def slow_build(*_args, output_root, **_kwargs):
            time.sleep(0.2)
            package = Path(output_root) / "slow" / "package"
            package.mkdir(parents=True, exist_ok=True)
            return EffectPlacementPreview(
                package_dir=package,
                box_submesh_index=0,
                item_submesh_count=1,
                box_min=(-1.0, -1.0, -1.0),
                box_max=(1.0, 1.0, 1.0),
            )

        with patch("cdmw.ui.new_item.effect_placement_dialog.build_effect_placement_package", slow_build):
            dialog = EffectPlacementDialog(
                item_mesh=_blade(),
                box_min=(-1.0, -1.0, -1.0),
                box_max=(1.0, 1.0, 1.0),
                output_root=output,
                host_factory=lambda parent: _Host(parent),
            )
            self.addCleanup(dialog.deleteLater)
            dialog.show()
            self._settle(lambda: dialog._thread is not None and dialog._thread.isRunning())
            started = time.monotonic()
            dialog.reject()
            self.assertLess(time.monotonic() - started, 0.08)
            self.assertTrue(dialog.iter_shutdown_workers())
            self._settle(lambda: dialog._thread is None)
            self.assertEqual(dialog.iter_shutdown_workers(), ())

    def test_effect_decode_runs_on_the_package_worker_without_blocking_the_ui(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="cdmw_effect_decode_worker_", ignore_cleanup_errors=True)
        self.addCleanup(folder.cleanup)
        output = Path(folder.name)
        decode_started = threading.Event()
        decode_cancelled = threading.Event()
        latest_started = threading.Event()
        decode_threads = []

        def decode_preview(cancelled):
            decode_threads.append(QThread.currentThread())
            decode_started.set()
            while True:
                if cancelled():
                    decode_cancelled.set()
                    return None
                time.sleep(0.005)

        def decode_latest(_cancelled):
            latest_started.set()
            return None

        workspace = EffectPlacementWorkspace(
            item_mesh=_blade(),
            box_min=(-1.0, -1.0, -1.0),
            box_max=(1.0, 1.0, 1.0),
            output_root=output,
            host_factory=lambda parent: _Host(parent),
            effect_preview=decode_preview,
            compatibility_ui=True,
        )
        self.addCleanup(workspace.deleteLater)
        workspace.show()
        try:
            self._settle(decode_started.is_set, timeout_ms=2_000)
            self.assertTrue(decode_started.is_set(), "the deferred decoder never reached the package worker")
            self.assertIsNot(decode_threads[0], self.app.thread())

            heartbeat = []
            QTimer.singleShot(0, lambda: heartbeat.append(True))
            self._settle(lambda: bool(heartbeat), timeout_ms=500)
            self.assertTrue(heartbeat, "the UI event loop stalled while the effect decoded")
            self.assertTrue(workspace._thread is not None and workspace._thread.isRunning())

            workspace.set_content(
                item_mesh=_blade(),
                box_min=(-2.0, -2.0, -2.0),
                box_max=(2.0, 2.0, 2.0),
                effect_label="latest",
                effect_preview=decode_latest,
                texture_reader=None,
            )
            self._settle(lambda: decode_cancelled.is_set() and latest_started.is_set(), timeout_ms=2_000)
            self.assertTrue(decode_cancelled.is_set(), "the superseded decoder did not observe cancellation")
            self.assertTrue(latest_started.is_set(), "the serialized lane did not launch the latest decoder")
        finally:
            workspace.request_shutdown()
            self._settle(lambda: workspace._thread is None)

    def test_superseded_effect_package_releases_its_model_source_usage_after_teardown(self) -> None:
        acquired = False
        released = False
        started = False
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            class Usage:
                def release(self) -> None:
                    nonlocal released
                    released = True

            def acquire_usage():
                nonlocal acquired
                acquired = True
                return Usage()

            def build(_mesh, _low, _high, *, output_root, cancelled, **_kwargs):
                nonlocal started
                started = True
                while not cancelled():
                    time.sleep(0.005)
                package = Path(output_root) / "package_cancelled"
                package.mkdir(exist_ok=True)
                return EffectPlacementPreview(
                    package_dir=package,
                    box_submesh_index=0,
                    item_submesh_count=1,
                    box_min=(-1.0, -1.0, -1.0),
                    box_max=(1.0, 1.0, 1.0),
                )

            with patch("cdmw.ui.new_item.effect_placement_dialog.build_effect_placement_package", side_effect=build):
                workspace = EffectPlacementWorkspace(
                    item_mesh=_blade(),
                    box_min=(-1.0, -1.0, -1.0),
                    box_max=(1.0, 1.0, 1.0),
                    output_root=root,
                    host_factory=lambda parent: _AckHost(parent),
                    compatibility_ui=True,
                    model_source_usage=acquire_usage,
                )
                self.addCleanup(workspace.deleteLater)
                workspace.show()
                self._settle(lambda: started)
                self.assertTrue(acquired)
                self.assertFalse(released)

                workspace.set_content(
                    item_mesh=_blade(),
                    box_min=(-1.0, -1.0, -1.0),
                    box_max=(1.0, 1.0, 1.0),
                    effect_label="template",
                    effect_preview=None,
                    texture_reader=None,
                    model_source_usage=None,
                )
                self._settle(lambda: released)
                self.assertTrue(released)
                workspace.request_shutdown()
                self._settle(lambda: workspace._thread is None)

    def test_cleanup_refuses_every_package_outside_the_owned_output_root(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            owned = root / "owned"
            outside = root / "outside"
            outside.mkdir()
            marker = outside / "keep.txt"
            marker.write_text("keep", encoding="utf-8")
            dialog = self._dialog(output_root=owned)
            preview = EffectPlacementPreview(
                package_dir=outside,
                box_submesh_index=0,
                item_submesh_count=1,
                box_min=(-1.0, -1.0, -1.0),
                box_max=(1.0, 1.0, 1.0),
            )
            self.assertFalse(dialog._remove_owned_package(preview))
            self.assertTrue(marker.is_file())

    def test_an_old_package_is_kept_until_the_correlated_load_ack(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first_dir = root / "package_first"
            second_dir = root / "package_second"
            first_dir.mkdir()
            second_dir.mkdir()
            (first_dir / "keep.txt").write_text("old", encoding="utf-8")
            workspace = EffectPlacementWorkspace(
                item_mesh=_blade(),
                box_min=(-1.0, -1.0, -1.0),
                box_max=(1.0, 1.0, 1.0),
                output_root=root,
                host_factory=lambda parent: _AckHost(parent),
                compatibility_ui=True,
            )
            self.addCleanup(workspace.deleteLater)
            first = EffectPlacementPreview(
                package_dir=first_dir,
                box_submesh_index=0,
                item_submesh_count=1,
                box_min=(-1.0, -1.0, -1.0),
                box_max=(1.0, 1.0, 1.0),
            )
            second = EffectPlacementPreview(
                package_dir=second_dir,
                box_submesh_index=0,
                item_submesh_count=1,
                box_min=(-1.0, -1.0, -1.0),
                box_max=(1.0, 1.0, 1.0),
            )
            workspace._preview = first
            workspace._package_generation = 1
            workspace._active_package_generation = 1
            workspace._package_ready((1, second, (), False))
            self.assertTrue(first_dir.is_dir(), "the renderer may still own the old package")
            self.assertIs(workspace._preview, first)
            self.assertEqual(workspace.host.loaded_requests[-1], (second_dir, False))
            workspace.host.controller.package_applied.emit(str(second_dir), 1)
            self.assertFalse(first_dir.exists())
            self.assertTrue(second_dir.is_dir())
            self.assertIs(workspace._preview, second)
            self.assertEqual(workspace.host.restored_views[-1]["role"], "reference")
            workspace.request_shutdown()
            self.assertFalse(second_dir.exists())

    def test_rapid_rebuilds_publish_only_the_latest_package_and_keep_the_camera(self) -> None:
        started = False
        calls = []
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)

            def build(_mesh, _low, _high, *, output_root, cancelled, **_kwargs):
                nonlocal started
                output = Path(output_root)
                calls.append(output)
                index = sum(path == output for path in calls)
                if output == root and index == 1:
                    started = True
                    while not cancelled():
                        time.sleep(0.005)
                package = output / f"package_{index}"
                package.mkdir()
                return EffectPlacementPreview(
                    package_dir=package,
                    box_submesh_index=0,
                    item_submesh_count=1,
                    box_min=(-1.0, -1.0, -1.0),
                    box_max=(1.0, 1.0, 1.0),
                )

            with patch("cdmw.ui.new_item.effect_placement_dialog.build_effect_placement_package", side_effect=build):
                workspace = EffectPlacementWorkspace(
                    item_mesh=_blade(),
                    box_min=(-1.0, -1.0, -1.0),
                    box_max=(1.0, 1.0, 1.0),
                    output_root=root,
                    host_factory=lambda parent: _AckHost(parent),
                    compatibility_ui=True,
                )
                self.addCleanup(workspace.deleteLater)
                workspace.show()
                self._settle(lambda: started)
                workspace.set_content(
                    item_mesh=_blade(),
                    box_min=(-20.0, -20.0, -20.0),
                    box_max=(20.0, 20.0, 20.0),
                    effect_label="fx_latest",
                    effect_preview=None,
                    texture_reader=None,
                    reset_view=False,
                )
                self._settle(lambda: len(workspace.host.loaded_requests) == 1)
                loaded, reset = workspace.host.loaded_requests[0]
                self.assertEqual(loaded, root / "package_2")
                self.assertFalse(reset, "effect/look rebuilds preserve the camera")
                self.assertFalse(workspace.show_reach.isChecked(), "oversized bounds fold away instead of reframing the item")
                self.assertFalse((root / "package_1").exists(), "the stale build was discarded")
                workspace.host.controller.package_applied.emit(str(loaded), 2)
                self.assertIsNotNone(workspace._preview)
                self.assertEqual(workspace.host.restored_views[-1]["zoom_factor"], 1.25)
                workspace.request_shutdown()
                self._settle(lambda: workspace._thread is None)

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

        from cdmw.ui.new_item.effect_placement_dialog_support import BACKDROPS, remembered_backdrop

        dialog = self._dialog()
        self.assertEqual([dialog.backdrop_choice.itemData(row) for row in range(dialog.backdrop_choice.count())],
                         list(BACKDROPS))
        self.assertEqual(dialog.backdrop_choice.currentData(), remembered_backdrop(), "it opens on the last one chosen")

        grey = BACKDROPS.index("#3B3B3B")
        dialog.backdrop_choice.setCurrentIndex(grey)
        self.assertEqual(dialog.host.backdrops[-1], "#3B3B3B", "the viewport is told")
        self.assertEqual(remembered_backdrop(), "#3B3B3B", "and the next dialog opens on it")

        dark = BACKDROPS.index("#101014")
        dialog.backdrop_choice.setCurrentIndex(dark)
        self.assertEqual(remembered_backdrop(), "#101014")

    def test_orbit_inversion_is_visible_shared_and_applied_to_this_viewport(self) -> None:
        with patch(
            "cdmw.ui.new_item.effect_placement_dialog.remembered_orbit_inversion",
            return_value=(True, False),
        ):
            dialog = self._dialog()

        self.assertTrue(dialog.invert_orbit_x_checkbox.isChecked())
        self.assertFalse(dialog.invert_orbit_y_checkbox.isChecked())
        dialog._host_state("ready", "")
        self.assertEqual(
            dialog.host.camera_bindings[-1],
            {"right": "orbit", "invert_orbit_x": True, "invert_orbit_y": False},
        )

        with patch("cdmw.ui.new_item.effect_placement_dialog.remember_orbit_inversion") as remember:
            dialog.invert_orbit_y_checkbox.setChecked(True)
            remember.assert_called_once_with(True, True)
        self.assertTrue(dialog.host.camera_bindings[-1]["invert_orbit_y"])
        dialog._closed = True

    def test_orbit_inversion_uses_the_shared_preview_setting_keys(self) -> None:
        from cdmw.ui.new_item.effect_placement_dialog_support import (
            remember_orbit_inversion,
            remembered_orbit_inversion,
        )

        class Settings:
            values = {
                "preview/invert_orbit_x": "true",
                "preview/invert_orbit_y": 0,
            }

            def __init__(self, *_args) -> None:
                pass

            def value(self, key, default=False):
                return self.values.get(key, default)

            def setValue(self, key, value) -> None:
                self.values[key] = value

        with patch("PySide6.QtCore.QSettings", Settings):
            self.assertEqual(remembered_orbit_inversion(), (True, False))
            remember_orbit_inversion(False, True)
            self.assertEqual(remembered_orbit_inversion(), (False, True))

    def test_the_panel_is_grouped_and_the_legend_folds_away(self) -> None:
        """Fourteen controls, five legend rows and four labels in one column read as a
        wall. What moves the effect and what is drawn are two questions, and the legend
        answers a third that is asked once."""

        from PySide6.QtWidgets import QGroupBox

        dialog = self._dialog()
        groups = [box.title() for box in dialog.findChildren(QGroupBox)]
        self.assertEqual(groups, ["Placement", "Preview"])
        self.assertFalse(dialog.legend_toggle.toggle.isChecked(), "the legend starts folded")
        for label in dialog.legend_rows.values():
            self.assertFalse(label.isVisibleTo(dialog), "and its rows are not taking room")
        dialog.legend_toggle.toggle.setChecked(True)
        self.assertTrue(dialog.legend_rows["anchor"].isVisibleTo(dialog), "one click and it is there")

    def test_guided_presentation_exposes_the_exact_toolbar_and_inspector_controls(self) -> None:
        workspace = EffectPlacementWorkspace(
            item_mesh=_blade(),
            box_min=(-1.0, -1.0, -1.0),
            box_max=(1.0, 1.0, 1.0),
            host_factory=lambda parent: _Host(parent),
            compatibility_ui=False,
        )
        self.addCleanup(workspace.request_shutdown)
        self.addCleanup(workspace.deleteLater)
        workspace.resize(1000, 700)
        workspace.show()
        self.app.processEvents()
        visible_scrolls = [scroll.objectName() for scroll in workspace.findChildren(QScrollArea) if scroll.isVisibleTo(workspace)]
        self.assertEqual(visible_scrolls, ["effect_inspector_scroll"])
        inspector_scroll = workspace.preview_splitter.widget(1)
        self.assertEqual(inspector_scroll.horizontalScrollBar().maximum(), 0)
        inspector_width = inspector_scroll.viewport().width()
        apply_bottom = workspace.apply_button.mapTo(
            inspector_scroll.viewport(), workspace.apply_button.rect().bottomRight()
        ).y()
        self.assertLess(apply_bottom, inspector_scroll.viewport().height(), "Apply stays visible at the 900px-window body height")
        for spin in (*workspace.offset_spins, *workspace.rotation_spins):
            right_edge = spin.mapTo(inspector_scroll.viewport(), spin.rect().bottomRight()).x()
            self.assertLess(right_edge, inspector_width, "every axis value remains visible at the inspector minimum")
        self.assertGreater(workspace.offset_spins[0].x(), 80, "the Position caption and X control do not overlap")
        self.assertGreater(workspace.rotation_spins[0].x(), 80, "the Rotation caption and X control do not overlap")
        orphaned_captions = [
            label.text()
            for label in workspace.findChildren(QLabel)
            if label.parent() is workspace and label.isVisibleTo(workspace) and label.text() in {"Effect", "Model", "View"}
        ]
        self.assertEqual(orphaned_captions, [])
        self.assertEqual(
            [workspace.move_button.text(), workspace.rotate_button.text(), workspace.scale_button.text()],
            ["Move", "Rotate", "Scale"],
        )
        self.assertEqual([button.text() for button in workspace.view_buttons[:3]], ["Front", "Side", "Top"])
        self.assertEqual((workspace.frame_button.text(), workspace.pause_button.text()), ("Frame", "Pause"))
        for button in (
            workspace.move_button,
            workspace.rotate_button,
            workspace.scale_button,
            *workspace.view_buttons[:3],
            workspace.frame_button,
            workspace.pause_button,
        ):
            self.assertFalse(button.icon().isNull(), button.text())
        self.assertEqual([workspace.anchor_choice.itemText(i) for i in range(workspace.anchor_choice.count())], ["Origin", "Center", "End"])
        self.assertEqual(workspace.show_reach.text(), "Show bounds")
        self.assertEqual(workspace.fit_button.text(), "Fit")
        self.assertEqual([workspace.backdrop_choice.itemText(i) for i in range(workspace.backdrop_choice.count())], ["Neutral", "Dark", "Black"])
        self.assertEqual(set(workspace.look_spins), {"intensity", "particle_size", "spawn_rate", "lifetime"})
        workspace.look_spins["intensity"].setValue(20.0)
        self.assertEqual(workspace.look_sliders["intensity"].value(), 1000)
        workspace.look_sliders["intensity"].setValue(0)
        self.assertEqual(workspace.look_spins["intensity"].value(), 1.0)
        workspace.anchor_choice.setCurrentIndex(workspace.anchor_choice.findData("center"))
        self.assertAlmostEqual(workspace.offset[2], -0.35)
        workspace.anchor_choice.setCurrentIndex(workspace.anchor_choice.findData("end"))
        self.assertAlmostEqual(workspace.offset[2], -0.9)
        workspace.scale_spin.setValue(2.0)
        workspace.rotation_spins[1].setValue(45.0)
        workspace.guided_restore_button.click()
        self.assertEqual((workspace.scale, workspace.offset, workspace.rotation), (1.0, (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)))

        from cdmw.services.effect_character_reference import TRAIL_SOCKET

        workspace._effect_sockets = ((TRAIL_SOCKET, (0.1, 0.2, -0.9)),)
        workspace._offer_the_trail_socket()
        trail = workspace.anchor_choice.findData("trail")
        self.assertGreaterEqual(trail, 0)
        self.assertEqual(workspace.anchor_choice.itemText(trail), "Trail Socket")
        workspace.anchor_choice.setCurrentIndex(trail)
        self.assertEqual(tuple(round(value, 6) for value in workspace.offset), (0.1, 0.2, -0.9))

    def test_an_exact_decoder_reason_disables_only_look_authoring(self) -> None:
        workspace = EffectPlacementWorkspace(
            item_mesh=_blade(),
            box_min=(-1.0, -1.0, -1.0),
            box_max=(1.0, 1.0, 1.0),
            host_factory=lambda _parent: None,
        )
        self.addCleanup(workspace.request_shutdown)
        self.addCleanup(workspace.deleteLater)
        reason = "unexpected marker at byte 418"
        workspace.set_decoder_reason(reason)
        self.assertEqual(workspace.decoder_reason.text(), reason)
        self.assertFalse(workspace.colour_as_shipped.isEnabled())
        self.assertTrue(workspace.scale_spin.isEnabled(), "numeric placement remains available")
        workspace.set_decoder_reason("")
        self.assertTrue(workspace.look_spins["intensity"].isEnabled())

        self.assertFalse(workspace.show_reach.isEnabled())
        self.assertFalse(workspace.backdrop_choice.isEnabled())
        self.assertFalse(workspace.show_character.isEnabled())
        self.assertTrue(workspace.fit_button.isEnabled(), "Fit remains a numeric scale operation")

    def test_the_context_and_actions_are_compact_and_specific(self) -> None:
        from PySide6.QtWidgets import QDialogButtonBox

        dialog = self._dialog(effect_label="pafx_weapon_fire", item_label="placed")
        self.assertEqual(dialog.effect_name_label.text(), "pafx_weapon_fire")
        self.assertEqual(dialog.showing_label.text(), "Imported")
        self.assertIn("step 3", dialog.showing_label.toolTip(), "detail stays available without another paragraph")
        self.assertIn("right mouse button", dialog.host.toolTip(), "gesture help moved off the permanent canvas")
        buttons = dialog.findChild(QDialogButtonBox)
        self.assertIsNotNone(buttons)
        self.assertEqual(buttons.button(QDialogButtonBox.StandardButton.Ok).text(), "Apply")

    def test_a_reach_far_larger_than_the_item_starts_hidden(self) -> None:
        dialog = self._dialog()
        self.assertFalse(dialog.show_reach.isChecked())
        self.assertIn("dwarfs the item", dialog.size_label.text())


if __name__ == "__main__":
    unittest.main()
