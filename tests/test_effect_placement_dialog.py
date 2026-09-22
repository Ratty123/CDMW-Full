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
from types import SimpleNamespace
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
        self.alignment_states: list = []
        self.lightings: list = []
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
        self.alignment_states.append(bool(enabled))
        return True

    def set_camera_drag_bindings(self, **_bindings) -> bool:
        self.camera_bindings.append(dict(_bindings))
        return True

    def set_lighting_preset(self, preset: str) -> bool:
        self.lightings.append(str(preset))
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


class _DialogTestCase(unittest.TestCase):
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
            reach_submesh_index=1, body_submesh_index=6,
        )
        self.addCleanup(self._shutdown_dialog, dialog)
        return dialog

    def _shutdown_workspace(self, workspace):
        workspace.request_shutdown()
        self._settle(lambda: not workspace.iter_shutdown_workers())
        self.assertFalse(workspace.iter_shutdown_workers())
        workspace.deleteLater()

    def _shutdown_dialog(self, dialog):
        self._shutdown_workspace(dialog.workspace)
        dialog.deleteLater()

    def _settle(self, done, timeout_ms: int = 20_000) -> None:
        """Run the event loop until `done()` or the deadline; a worker thread is only
        finished once the main thread has processed the signals that say so."""

        from PySide6.QtCore import QDeadlineTimer, QEventLoop

        deadline = QDeadlineTimer(timeout_ms)
        while not done() and not deadline.hasExpired():
            self.app.processEvents(QEventLoop.ProcessEventsFlag.AllEvents, 50)

    def _legend(self, dialog) -> list:
        return [key for key, label in dialog.legend_rows.items() if not label.isHidden()]

from tests.effect_placement_dialog_presentation_tests import _DialogPresentationMixin


class DialogTests(_DialogPresentationMixin, _DialogTestCase):
    def test_effect_viewport_receives_shared_render_tuning(self) -> None:
        from cdmw.models import ModelPreviewRenderSettings

        initial = ModelPreviewRenderSettings(d3d11_tone_gamma=1.17, d3d11_ao_strength=0.7)
        dialog = self._dialog(render_settings=initial)
        tuning = []
        dialog.host = _Host()
        dialog.host.set_render_tuning = tuning.append
        dialog._sync_host()
        self.assertEqual(tuning[-1], initial)
        updated = ModelPreviewRenderSettings(d3d11_tone_gamma=0.91, d3d11_ao_strength=0.4)
        dialog.set_render_settings(updated)
        self.assertEqual(tuning[-1], updated)
        dialog.host.deleteLater()
        dialog.host = None

    def test_package_thread_is_initialized_before_child_observers_can_see_it(self) -> None:
        from PySide6.QtCore import QEvent

        workspace = self._dialog().workspace
        observed_types = []

        class ChildObserver(QObject):
            def eventFilter(self, watched, event):  # noqa: N802 - Qt override
                if watched is workspace and event.type() == QEvent.Type.ChildAdded:
                    # Resolving a child during QThread(parent) exposes a provisional
                    # QObject wrapper before the thread's native metadata is ready.
                    observed_types.append(type(event.child()))
                return False

        observer = ChildObserver(workspace)
        workspace.installEventFilter(observer)
        with patch("cdmw.ui.new_item.effect_placement_dialog.build_effect_placement_package", return_value=None):
            try:
                workspace._start_package()
                thread = workspace._thread
                self.assertIsNotNone(thread)
                self.assertIs(thread.parent(), workspace)
                self._settle(lambda: workspace._thread is None)
                self.assertIsNone(workspace._thread, "the worker must finish and release its thread")
                self.assertEqual(observed_types, [QThread])
            finally:
                workspace.removeEventFilter(observer)
                workspace.request_shutdown()
                self._settle(lambda: workspace._thread is None)

    def test_guided_toolbar_pending_resize_is_cancelled_when_panel_is_deleted(self) -> None:
        from unittest.mock import patch
        from PySide6.QtCore import QCoreApplication, QEvent, QSize
        from PySide6.QtGui import QResizeEvent
        from cdmw.ui.new_item.effect_placement_guided import _GuidedToolbarPanel

        panel = _GuidedToolbarPanel()
        panel.resize(400, 50)
        widths = []
        panel.resized.connect(widths.append)
        event = QResizeEvent(QSize(400, 50), QSize(300, 50))
        QCoreApplication.sendEvent(panel, event)
        self.app.processEvents()
        self.assertEqual(widths, [400, 400])
        QCoreApplication.sendEvent(panel, event)
        panel.deleteLater()
        QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
        errors = []
        with patch("sys.excepthook", lambda *args: errors.append(args)):
            self.app.processEvents()
        self.assertEqual(errors, [])
        self.assertEqual(widths, [400, 400, 400])

    def test_content_failure_retains_the_scene_and_marks_only_the_current_request_for_retry(self) -> None:
        from dataclasses import replace
        from unittest.mock import patch

        dialog = self._dialog().workspace
        dialog._initial_package_timer.stop()
        resident = dialog._preview
        dialog._package_failed("Texture could not be read")
        self.assertTrue(dialog._content_failed)
        self.assertIs(dialog._preview, resident)

        dialog._content_failed = False
        dialog._active_package_generation -= 1
        dialog._package_failed("Obsolete failure")
        self.assertFalse(dialog._content_failed)
        self.assertIs(dialog._preview, resident)

        dialog._active_package_generation = dialog._package_generation
        rejected = replace(resident, package_dir=Path("rejected-preview"))
        with patch.object(dialog.host, "load_package", return_value=False), patch.object(dialog, "_remove_owned_package"):
            dialog._package_ready(rejected)
        self.assertTrue(dialog._content_failed, "a rejected package must remain retryable")
        self.assertIs(dialog._preview, resident)

    def test_dense_surface_effect_loads_through_the_worker_and_real_host(self) -> None:
        import json
        from dataclasses import replace

        from cdmw.services.mesh_rust_preview_package import validate_rust_preview_package
        from cdmw.ui.preview.dotnet_host import RustPreviewHostFrame
        from tests.test_effect_placement_preview import _fire_preview

        mesh = _blade()
        part = mesh.submeshes[0]
        vertices, faces = part.vertices, part.faces
        copies = 9_000
        part.vertices = vertices * copies
        part.normals *= copies
        part.uvs *= copies
        part.faces = [tuple(i + k * len(vertices) for i in face) for k in range(copies) for face in faces]
        part.vertex_count, part.face_count = len(part.vertices), len(part.faces)
        mesh.total_vertices, mesh.total_faces = part.vertex_count, part.face_count
        effect = _fire_preview()
        effect = replace(effect, emitters=tuple(replace(emitter, spawn_volume_type=6) for emitter in effect.emitters))
        folder = tempfile.TemporaryDirectory(prefix="cdmw_effect_dense_surface_")
        self.addCleanup(folder.cleanup)
        workspace = EffectPlacementWorkspace(
            item_mesh=mesh, box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
            output_root=Path(folder.name), effect_preview=effect,
            character_builder=lambda **_kwargs: SimpleNamespace(mesh=mesh, item_rotation=None),
            host_factory=RustPreviewHostFrame,
        )
        self.addCleanup(self._shutdown_workspace, workspace)
        controller = workspace.host.controller
        controller.set_visible(False)
        failures = []
        controller.package_failed.connect(lambda *args: failures.append(args))
        workspace._start_package()
        self._settle(lambda: workspace._thread is None)

        self.assertIsNone(workspace._thread)
        self.assertEqual(failures, [], "surface geometry must fit the real preview manifest contract")
        self.assertFalse(workspace._content_failed, workspace.status.text())
        package = Path(controller.desired_package_path)
        self.assertEqual(validate_rust_preview_package(package), ())
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
        self.assertGreater(len(json.dumps(manifest, indent=2).encode()), 16 * 1024 * 1024)
        surfaces = workspace.host._scene_state["effects_overlay"]["spawn_surfaces"]
        for surface in (surfaces["item"], surfaces["character"]):
            self.assertEqual(surface["vertices"], [list(value) for value in part.vertices])
            self.assertEqual(surface["normals"], [list(value) for value in part.normals])
            self.assertEqual(surface["faces"], [list(value) for value in part.faces])
            self.assertEqual(len(surface["areas"]), len(part.faces))
        self.assertIsNone(controller.process, "this is a headless host-loading test")

    def test_oversized_effect_package_fails_before_viewport_handoff(self) -> None:
        from tests.test_effect_placement_preview import _fire_preview

        folder = tempfile.TemporaryDirectory(prefix="cdmw_effect_manifest_limit_")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        marker = root / "keep.txt"
        marker.write_text("unrelated", encoding="utf-8")
        workspace = self._dialog(output_root=root, effect_preview=_fire_preview()).workspace
        resident = workspace._preview
        with patch("cdmw.services.mesh_rust_preview_package._PREVIEW_MANIFEST_MAX_BYTES", 1024):
            workspace._start_package()
            self._settle(lambda: workspace._thread is None)

        self.assertIsNone(workspace._thread)
        self.assertTrue(workspace._content_failed)
        self.assertIn("preview manifest exceeds its size limit", workspace.status.text())
        self.assertIs(workspace._preview, resident)
        self.assertIsNone(workspace.host.loaded)
        self.assertEqual(list(root.iterdir()), [marker], "an invalid build must leave no published or staging package")

    def test_rejected_package_survives_for_retry_and_retires_on_shutdown(self) -> None:
        from cdmw.services.effect_placement_preview import build_effect_placement_package
        from cdmw.ui.preview.dotnet_host import RustPreviewHostFrame

        folder = tempfile.TemporaryDirectory(prefix="cdmw_effect_retry_")
        self.addCleanup(folder.cleanup)
        root = Path(folder.name)
        preview = build_effect_placement_package(_blade(), (-1, -1, -1), (1, 1, 1), output_root=root)
        workspace = EffectPlacementWorkspace(
            item_mesh=_blade(), box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
            output_root=root, host_factory=RustPreviewHostFrame,
        )
        self.addCleanup(self._shutdown_workspace, workspace)
        controller = workspace.host.controller
        controller.set_visible(False)
        failures = []
        controller.package_failed.connect(lambda *args: failures.append(args))
        with patch.object(controller, "_with_preview_runtime_output", side_effect=OSError("temporary output unavailable")):
            workspace._package_ready((0, preview, (), False))
        self._settle(lambda: not workspace.iter_shutdown_workers())
        self.assertTrue(workspace._content_failed)
        self.assertEqual(len(failures), 1)
        self.assertTrue((preview.package_dir / "manifest.json").is_file(), "Retry still owns this input")
        self.assertIs(workspace._loading_preview, preview)

        self.assertTrue(controller.load_package(controller._invalid_retry_package_path))
        controller.package_applied.emit(str(preview.package_dir), 1)
        self.assertEqual(len(failures), 1)
        self.assertIs(workspace._preview, preview)
        self.assertFalse(workspace._content_failed)
        self.assertEqual(workspace.status.text(), "")
        workspace.request_shutdown()
        self._settle(lambda: not workspace.iter_shutdown_workers())
        self.assertFalse(preview.package_dir.exists())

    def test_preview_uses_one_neutral_lighting_without_a_mode_selector(self) -> None:
        changes = []
        dialog = self._dialog(
            lighting_preset="showcase",
            lighting_changed=changes.append,
        )
        dialog._host_state("ready", "")
        self.assertEqual(dialog.host.lightings[-1], "neutral_studio")
        self.assertFalse(hasattr(dialog, "lighting_choice"))
        self.assertEqual(changes, [])

    def test_the_legend_names_what_is_on_screen_and_nothing_else(self) -> None:
        dialog = self._dialog()
        dialog.show_character.setChecked(True)
        dialog.show_reach.setChecked(True)
        self.assertEqual(self._legend(dialog), ["axes", "item", "body", "reach", "particles"])
        dialog.show_character.setChecked(False)
        dialog.show_reach.setChecked(False)
        # The line gizmo remains visible; its opaque helper geometry stays hidden.
        self.assertEqual(self._legend(dialog), ["axes", "item", "particles"])
        self.assertIn("character", dialog.legend_rows["body"].text())
        self.assertIn("1.75 m", dialog.legend_rows["body"].text())

    def test_the_standing_views_turn_the_camera_and_fit_the_item_again(self) -> None:
        dialog = self._dialog()
        self.assertEqual(len(dialog.view_buttons), len(STANDING_VIEW_ANGLES))
        self.assertEqual([button.text() for button in dialog.view_buttons], ["Front", "Side", "Top", "Angled"])
        self.assertTrue(dialog.view_buttons[0].isChecked(), "Front is the selected opening view")
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
        self.assertEqual(dialog.host.view_roles, [], "the package-authored Front camera owns the opening fit")

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
        self.addCleanup(self._shutdown_workspace, workspace)
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
        self.assertEqual(dialog.host.hidden, (0, 2, 3, 4))
        dialog.show_character.setChecked(False)
        self.assertEqual(dialog.host.hidden, (0, 2, 3, 4, 6), "the character's submesh, not the item's")
        dialog.show_reach.setChecked(False)
        self.assertEqual(dialog.host.hidden, (0, 1, 2, 3, 4, 6))
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

    def test_embedded_gizmo_keeps_working_without_solid_helpers_at_any_effect_scale(self) -> None:
        workspace = EffectPlacementWorkspace(
            item_mesh=_blade(), box_min=(-1, -1, -1), box_max=(1, 1, 1),
            host_factory=lambda parent: _Host(parent), compatibility_ui=False,
        )
        workspace._initial_package_timer.stop()
        self.addCleanup(self._shutdown_workspace, workspace)
        workspace._preview = EffectPlacementPreview(
            package_dir=Path("."), box_submesh_index=0, item_submesh_count=1,
            box_min=(-1, -1, -1), box_max=(1, 1, 1), body_submesh_index=6,
        )
        workspace.show_reach.setChecked(False)
        workspace.show_character.setChecked(True)
        workspace._host_state("ready", "")
        hidden = (0, 1, 2, 3, 4)
        self.assertEqual(workspace.host.hidden, hidden)
        self.assertTrue(workspace.host.alignment_states[-1])
        for scale in (workspace.scale_spin.minimum(), workspace.scale_spin.maximum()):
            workspace.scale_spin.setValue(scale)
            self.assertEqual(workspace.host.transforms[-1]["scale_xyz"], (scale,) * 3)
            self.assertEqual(workspace.host.hidden, hidden)
        for tool, button in (("move", workspace.move_button), ("rotate", workspace.rotate_button), ("scale", workspace.scale_button)):
            button.click()
            self.assertEqual(workspace.host.gizmo_tools[-1], tool)
        workspace.host.alignment_drag_finished.emit(0.25, 0, 0)
        workspace.host.alignment_rotation_finished.emit(0, 45, 0)
        workspace.host.alignment_scale_finished.emit(-0.1, -0.1, -0.1)
        self.assertEqual(workspace.offset, (0.25, 0, 0))
        self.assertEqual(workspace.rotation, (0, 45, 0))
        self.assertEqual(workspace.scale, 9.9)
        self.assertIsNone(workspace.host.loaded, "live gizmo edits do not reload the package")
        workspace.host.hidden = ()  # A restarted renderer must receive the mask again.
        workspace._host_state("ready", "")
        self.assertEqual(workspace.host.hidden, hidden)
        self.assertTrue(workspace.host.alignment_states[-1])
        self.assertEqual(workspace.host.transforms[-1]["translation"], (0.25, 0, 0))

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
        self.assertIn("Approximate preview", dialog.caveat.text())
        # the line stays short; the detail moved to its tooltip, because a paragraph here
        # pushed the controls above it off a short panel
        self.assertLess(len(dialog.caveat.text()), 160, dialog.caveat.text())
        self.assertIn("pafx_m_ds_firesword_trail_002a.pam", dialog.caveat.toolTip())

        quiet = self._dialog(effect_preview=SimpleNamespace(emitters=(), notes=()))
        quiet._show_caveats()
        self.assertTrue(quiet.caveat.isHidden())

    def test_geometry_and_shader_limitations_are_visible_without_a_missing_spawn_mesh(self) -> None:
        from types import SimpleNamespace

        notes = ("lightning: particle geometry unavailable", "lightning: procedural deformation is not reproduced")
        dialog = self._dialog(effect_preview=SimpleNamespace(emitters=(), notes=notes))
        dialog._show_caveats()
        self.assertFalse(dialog.caveat.isHidden())
        self.assertIn("2 limitation(s)", dialog.caveat.text())
        self.assertEqual(dialog.caveat.toolTip(), "\n".join(notes))

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
            reach_submesh_index=1, body_submesh_index=6, item_rotation=quarter,
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
            reach_submesh_index=1, body_submesh_index=6, body_submesh_count=4,
        )
        dialog.show_reach.setChecked(True)
        dialog.show_character.setChecked(False)
        self.assertEqual(dialog.host.hidden, (0, 2, 3, 4, 6, 7, 8, 9))

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
        character_calls = []

        def build_character(*, stop_event):
            character_calls.append(stop_event)
            return character

        dialog = self._dialog(
            output_root=Path(folder.name),
            character_builder=build_character,
        )
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
        self.assertEqual(len(character_calls), 1)
        self.assertFalse(character_calls[0].is_set(), "the worker's cooperative stop event reached the archive builder")
        self.assertIn("game's character", dialog.legend_rows["body"].text())
        self.assertIn("size reference", dialog.show_character.toolTip())
        dialog._closed = True

    def test_character_cancellation_stops_before_package_publication(self) -> None:
        from cdmw.domain.cancellation import RunCancelled

        def cancelled_character(*, stop_event):
            self.assertIsInstance(stop_event, threading.Event)
            raise RunCancelled("Operation cancelled.")

        dialog = self._dialog(character_builder=cancelled_character)
        self.addCleanup(dialog.request_shutdown)
        dialog._preview = None
        with patch(
            "cdmw.ui.new_item.effect_placement_dialog.build_effect_placement_package"
        ) as build_package:
            dialog._start_package()
            self._settle(lambda: dialog._thread is None)

        build_package.assert_not_called()
        self.assertIsNone(dialog._preview)

    def test_closing_during_package_build_never_waits_on_the_ui_thread(self) -> None:
        folder = tempfile.TemporaryDirectory(prefix="cdmw_effect_shutdown_")
        self.addCleanup(folder.cleanup)
        output = Path(folder.name)
        build_started = threading.Event()
        release_build = threading.Event()

        def slow_build(*_args, output_root, **_kwargs):
            build_started.set()
            release_build.wait(5.0)
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
            self.addCleanup(self._shutdown_dialog, dialog)
            dialog.show()
            try:
                self._settle(build_started.is_set)
                thread = dialog._thread
                with patch.object(thread, "wait", side_effect=AssertionError("close waited for its worker")) as wait:
                    dialog.reject()
                    wait.assert_not_called()
                self.assertTrue(thread.isRunning())
                self.assertTrue(dialog.iter_shutdown_workers())
            finally:
                release_build.set()
                dialog.request_shutdown()
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
        self.addCleanup(self._shutdown_workspace, workspace)
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

    def test_item_preparation_yields_to_ui_and_cancels_before_packaging_a_superseded_mesh(self) -> None:
        started, cancelled = threading.Event(), threading.Event()
        prepared, published, decode_threads = [], [], []
        latest = _blade()
        latest.path = "latest.pac"

        def slow_item(stop):
            decode_threads.append(QThread.currentThread())
            started.set()
            while not stop.wait(0.005):
                pass
            cancelled.set()
            return _blade(), "stale"

        def package(mesh, low, high, *, output_root, **_kwargs):
            prepared.append(mesh)
            path = Path(output_root) / "package_latest"
            path.mkdir(exist_ok=True)
            return EffectPlacementPreview(
                package_dir=path, box_submesh_index=0, item_submesh_count=1,
                box_min=low, box_max=high,
            )

        with tempfile.TemporaryDirectory() as folder, patch(
            "cdmw.ui.new_item.effect_placement_dialog.build_effect_placement_package", package
        ):
            workspace = EffectPlacementWorkspace(
                item_mesh=None, item_mesh_builder=slow_item,
                box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
                output_root=Path(folder), host_factory=lambda parent: _Host(parent),
            )
            self.addCleanup(self._shutdown_workspace, workspace)
            workspace.item_mesh_ready.connect(lambda mesh, label: published.append((mesh, label, QThread.currentThread())))
            workspace.show()
            try:
                self._settle(started.is_set, timeout_ms=2_000)
                self.assertIsNot(decode_threads[0], self.app.thread())
                heartbeat = []
                QTimer.singleShot(0, lambda: heartbeat.append(True))
                self._settle(lambda: bool(heartbeat), timeout_ms=500)
                self.assertTrue(heartbeat)
                self.assertEqual(prepared, [])
                workspace.set_content(
                    item_mesh=None, item_mesh_builder=lambda _stop: (latest, "placed"),
                    box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
                    effect_label="latest", effect_preview=None, texture_reader=None,
                )
                self._settle(lambda: bool(published), timeout_ms=2_000)
                self.assertTrue(cancelled.is_set())
                self.assertEqual(prepared, [latest], "cancelled item geometry must never reach package creation")
                self.assertEqual(published, [(latest, "placed", self.app.thread())])
                self.assertIs(workspace._item_mesh, latest)
                self.assertEqual(workspace.showing_label.text(), "Imported")
            finally:
                workspace.request_shutdown()
                self._settle(lambda: workspace._thread is None)

    def test_cancelling_pending_content_rejects_results_before_replacement_is_scheduled(self) -> None:
        started, cancelled = threading.Event(), threading.Event()

        def slow_item(stop):
            started.set()
            stop.wait(2.0)
            cancelled.set()
            return _blade(), "stale"

        with tempfile.TemporaryDirectory() as folder:
            workspace = EffectPlacementWorkspace(
                item_mesh=None, item_mesh_builder=slow_item,
                box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
                output_root=Path(folder), host_factory=lambda parent: _AckHost(parent),
            )
            self.addCleanup(self._shutdown_workspace, workspace)
            published = []
            workspace.item_mesh_ready.connect(lambda *values: published.append(values))
            workspace.show()
            try:
                self._settle(started.is_set)
                workspace.cancel_pending_content()
                self._settle(lambda: workspace._thread is None)
                self.assertTrue(cancelled.is_set())
                self.assertEqual(published, [])
                self.assertEqual(workspace.host.loaded_requests, [])

                # A queued launch may already have left _pending_package when the
                # source changes. It must release its usage without starting work.
                released = []
                usage = SimpleNamespace(release=lambda: released.append(True))
                workspace._launch_package((
                    workspace._package_generation - 1, False, _blade(),
                    workspace._box, Path(folder), None, None, None, usage, None,
                ))
                self.assertEqual(released, [True])
                self.assertIsNone(workspace._thread)
            finally:
                workspace.request_shutdown()
                self._settle(lambda: workspace._thread is None)

    def test_item_ready_callback_can_close_without_loading_the_new_package(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            package = root / "package_ready"
            package.mkdir()
            workspace = EffectPlacementWorkspace(
                item_mesh=None, box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
                output_root=root, host_factory=lambda parent: _Host(parent),
            )
            self.addCleanup(self._shutdown_workspace, workspace)
            workspace._package_generation = 1
            workspace.item_mesh_ready.connect(lambda _mesh, _label: workspace.request_shutdown())
            preview = EffectPlacementPreview(
                package_dir=package, box_submesh_index=0, item_submesh_count=1,
                box_min=(-1.0, -1.0, -1.0), box_max=(1.0, 1.0, 1.0),
            )
            workspace._package_ready((1, preview, (), True, None, _blade(), "placed"))
            self.assertTrue(workspace._closed)
            self.assertIsNone(workspace.host.loaded)
            self._settle(lambda: not workspace.iter_shutdown_workers())
            self.assertFalse(package.exists())

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
                self.addCleanup(self._shutdown_workspace, workspace)
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
            self.addCleanup(self._shutdown_workspace, workspace)
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
            self._settle(lambda: not workspace.iter_shutdown_workers())
            self.assertFalse(first_dir.exists())
            self.assertTrue(second_dir.is_dir())
            self.assertIs(workspace._preview, second)
            self.assertEqual(workspace.host.restored_views[-1]["role"], "reference")
            workspace.request_shutdown()
            self._settle(lambda: not workspace.iter_shutdown_workers())
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
                self.addCleanup(self._shutdown_workspace, workspace)
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



if __name__ == "__main__":
    unittest.main()
