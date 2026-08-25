"""Latest-wins package preparation for the resident effect placement viewport."""

from __future__ import annotations

import threading
from pathlib import Path
from typing import TYPE_CHECKING, Callable, Optional, Tuple

from PySide6.QtCore import QThread, Qt, QTimer

from cdmw.services.effect_placement_preview import (
    EffectPlacementPreview,
    mesh_names_textures,
)
from cdmw.services.effect_preview_model import EffectPreview
from cdmw.ui.new_item.effect_placement_constants import REACH_HIDDEN_ABOVE
from cdmw.ui.new_item.effect_placement_dialog_support import (
    PlacementFrame,
    describe_effect_preview,
    placed_item_origin,
)
from cdmw.workers.utility_workers import UtilityWorker

if TYPE_CHECKING:
    from cdmw.services.mesh_workflow_service import ParsedMesh

Vec3 = Tuple[float, float, float]


class EffectPlacementPackageMixin:
    """Keep one host alive while cancellable placement packages are rebuilt."""

    def set_content(
        self,
        *,
        item_mesh: ParsedMesh,
        box_min: Vec3,
        box_max: Vec3,
        effect_label: str,
        effect_preview: Optional[EffectPreview | Callable[[Callable[[], bool]], Optional[EffectPreview]]],
        texture_reader: Optional[Callable[[str], Optional[bytes]]],
        character_builder: Optional[Callable[[], object]] = None,
        model_source_usage: Optional[Callable[[], object]] = None,
        reset_view: bool = False,
    ) -> None:
        self._item_mesh = item_mesh
        self._item_origin = placed_item_origin(item_mesh)
        self._box = (tuple(float(v) for v in box_min), tuple(float(v) for v in box_max))
        self._box_size = tuple(high - low for low, high in zip(*self._box))
        low, high = self._item_bounds()
        item_length = max(high[axis] - low[axis] for axis in range(3))
        reach_length = max(self._box_size) * self.scale
        self._reach_dwarfs_the_item = bool(
            item_length > 0 and reach_length > item_length * REACH_HIDDEN_ABOVE
        )
        if self._reach_dwarfs_the_item and self.show_reach.isChecked():
            self.show_reach.setChecked(False)
        self._effect_preview = effect_preview
        presented_preview = None if callable(effect_preview) else effect_preview
        self.emitters_label.setText(describe_effect_preview(presented_preview))
        self.emitters_toggle.setVisible(presented_preview is not None)
        if presented_preview is None:
            self.caveat.setVisible(False)
        self._texture_reader = texture_reader
        self._character_builder = character_builder
        self._model_source_usage = model_source_usage
        self.effect_name_label.setText(str(effect_label or "-"))
        self._refresh_size_label()
        if self.host is not None:
            self._start_package(reset_view=reset_view)

    def _start_package(self, *, reset_view: bool = True) -> None:
        if self._closed:
            return
        self._package_generation += 1
        acquire_usage = self._model_source_usage
        source_usage = acquire_usage() if callable(acquire_usage) else None
        if callable(acquire_usage) and source_usage is None:
            return
        request = (
            self._package_generation,
            bool(reset_view),
            self._item_mesh,
            self._box,
            self._output_root,
            self._effect_preview,
            self._texture_reader,
            self._character_builder,
            source_usage,
        )
        if self._thread is not None:
            self._release_request_model_source_usage(self._pending_package)
            self._pending_package = request
            if self._worker is not None:
                self._worker.stop()
            self._thread.requestInterruption()
            self.status.setText("Updating the placement preview…")
            return
        self._launch_package(request)

    def _launch_package(self, request: tuple) -> None:
        if self._closed:
            self._release_request_model_source_usage(request)
            return
        generation, reset_view, mesh, box, root, effect_preview, texture_reader, builder, source_usage = request
        self._active_package_generation = int(generation)
        self._pending_package = None
        self._active_model_source_usage = source_usage
        textured = mesh_names_textures(mesh)

        def task(_log, stop_event: threading.Event) -> tuple:
            # Resolve through the compatibility facade so existing factories and tests
            # that patch its long-standing symbol keep controlling package creation.
            from cdmw.ui.new_item import effect_placement_dialog as facade

            character, rotation, effect_sockets = None, None, ()
            resolved_effect_preview = effect_preview(stop_event.is_set) if callable(effect_preview) else effect_preview
            resolved_box = box
            if isinstance(resolved_effect_preview, EffectPreview):
                resolved_box = (resolved_effect_preview.box_min, resolved_effect_preview.box_max)
            if builder is not None and not stop_event.is_set():
                try:
                    reference = builder()
                except Exception:  # noqa: BLE001 - a missing character must not remove numeric placement
                    reference = None
                if reference is not None:
                    character = getattr(reference, "mesh", None)
                    rotation = getattr(reference, "item_rotation", None)
                    effect_sockets = tuple(getattr(reference, "effect_sockets", ()) or ())
            preview = facade.build_effect_placement_package(
                mesh,
                resolved_box[0],
                resolved_box[1],
                output_root=root,
                cancelled=stop_event.is_set,
                include_item_textures=textured,
                character_mesh=character,
                item_rotation=rotation if character is not None else None,
                effect_preview=resolved_effect_preview,
                texture_reader=texture_reader,
            )
            return generation, preview, effect_sockets, reset_view, resolved_effect_preview

        worker = UtilityWorker(task, task_accepts_cancel=True)
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker = thread, worker
        worker.completed.connect(self._package_ready)
        worker.error.connect(self._package_failed)
        worker.finished.connect(self._worker_finished, Qt.ConnectionType.DirectConnection)
        thread.finished.connect(self._build_finished, Qt.ConnectionType.QueuedConnection)
        thread.started.connect(worker.run)
        self.status.setText("Preparing the placement preview…")
        thread.start()

    def _package_ready(self, result: object) -> None:
        generation, sockets, reset_view = self._active_package_generation, (), True
        presented_preview = self._effect_preview
        if isinstance(result, tuple) and len(result) == 5:
            generation, result, sockets, reset_view, presented_preview = result
        elif isinstance(result, tuple) and len(result) == 4:
            generation, result, sockets, reset_view = result
        elif isinstance(result, tuple) and len(result) == 2:
            result, sockets = result
        if not isinstance(result, EffectPlacementPreview):
            return
        if self._closed or int(generation) != self._package_generation or self.host is None:
            self._remove_owned_package(result)
            return
        self._effect_preview = presented_preview
        self._box = (tuple(float(value) for value in result.box_min), tuple(float(value) for value in result.box_max))
        self._box_size = tuple(high - low for low, high in zip(*self._box))
        low, high = self._item_bounds()
        item_length = max(high[axis] - low[axis] for axis in range(3))
        reach_length = max(self._box_size) * self.scale
        self._reach_dwarfs_the_item = bool(
            item_length > 0 and reach_length > item_length * REACH_HIDDEN_ABOVE
        )
        if self._reach_dwarfs_the_item and self.show_reach.isChecked():
            self.show_reach.setChecked(False)
        self._refresh_size_label()
        self.emitters_label.setText(describe_effect_preview(presented_preview))
        self.emitters_toggle.setVisible(presented_preview is not None)
        if self._loading_preview is not None:
            self._retired_previews.append(self._loading_preview)
        self._loading_preview = result
        self._loading_sockets = tuple(sockets or ())
        self._loading_view_state = None
        if not bool(reset_view):
            snapshot = getattr(self.host, "view_state_snapshot", None)
            if callable(snapshot):
                try:
                    value = snapshot()
                except Exception:  # noqa: BLE001 - package loading must still proceed
                    value = None
                if isinstance(value, dict):
                    self._loading_view_state = dict(value)
        if self.host.load_package(result.package_dir, reset_view=bool(reset_view)):
            self.host.set_display_mode("overlay")
            self.status.setText("Loading the viewport...")
            if not self._package_ack_connected:
                self._package_load_applied(str(result.package_dir), 0)
        else:
            self._loading_preview = None
            self._loading_view_state = None
            self._remove_owned_package(result)
            self.status.setText("The resident viewport rejected the placement package.")

    def _package_load_applied(self, package_path: object, _generation: object = 0) -> None:
        loading = self._loading_preview
        if loading is None:
            return
        if Path(str(package_path)).resolve(strict=False) != Path(loading.package_dir).resolve(strict=False):
            return
        previous = self._preview
        if previous is not None and previous is not loading:
            self._retired_previews.append(previous)
        self._preview = loading
        self._loading_preview = None
        preserved_view, self._loading_view_state = self._loading_view_state, None
        self._effect_sockets = self._loading_sockets
        self._loading_sockets = ()
        self._frame = PlacementFrame(loading.item_rotation)
        if loading.item_rotation is not None:
            self._say_the_character_is_the_game_s()
        self._offer_the_trail_socket()
        for retired in self._retired_previews:
            if retired.package_dir != loading.package_dir:
                self._remove_owned_package(retired)
        self._retired_previews = []
        self.status.setText("")
        self._sync_host()
        self._apply_scene_visibility()
        restore_view = getattr(self.host, "restore_view_state", None)
        if preserved_view is not None and callable(restore_view):
            try:
                restore_view(preserved_view)
            except Exception:  # noqa: BLE001 - the loaded scene remains usable
                pass

    def _package_failed(self, message: object) -> None:
        if not self._closed and self._active_package_generation == self._package_generation:
            self.status.setText(f"The placement preview could not be built: {message}")

    def _worker_finished(self) -> None:
        worker = self._worker
        if worker is not None and worker.thread() is QThread.currentThread():
            worker.moveToThread(self.thread())
        QThread.currentThread().quit()

    def _build_finished(self) -> None:
        thread, worker = self._thread, self._worker
        if thread is not None and not thread.wait(0):
            QTimer.singleShot(0, self._build_finished)
            return
        self._thread = None
        self._worker = None
        source_usage, self._active_model_source_usage = self._active_model_source_usage, None
        self._release_model_source_usage(source_usage)
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        pending, self._pending_package = self._pending_package, None
        if pending is not None and not self._closed:
            QTimer.singleShot(0, lambda request=pending: self._launch_package(request))
        else:
            self._release_request_model_source_usage(pending)

    @staticmethod
    def _release_model_source_usage(usage: object | None) -> None:
        release = getattr(usage, "release", None)
        if callable(release):
            release()

    def _release_request_model_source_usage(self, request: Optional[tuple]) -> None:
        if request is not None and len(request) >= 9:
            self._release_model_source_usage(request[8])

    def _host_state(self, state: str, message: str) -> None:
        if self._closed or self.host is None:
            return
        if str(state) == "ready" and self._preview is not None:
            self._renderer_failed = False
            if not self._compatibility_ui:
                self._set_viewport_controls_available(True)
            self.host.set_display_mode("overlay")
            self.host.set_viewport_display_mode("textured")
            self.host.set_alignment_state(enabled=True)
            self._backdrop_changed()
            self._apply_orbit_preferences()
            self._sync_host()
            self._apply_scene_visibility()
            yaw, pitch = self._standing_view_angles[-1]
            self._point_camera(yaw=yaw, pitch=pitch)
            sentences = []
            if self._preview.preview_file is not None and not self._host_draws_particles():
                sentences.append("This viewport build draws no particles yet; the anchor shows where the effect sits.")
            if self._preview.missing_textures:
                sentences.append(f"{len(self._preview.missing_textures)} sprite texture(s) could not be read from the archives.")
            self.status.setText(" ".join(sentences))
            self._show_caveats()
        elif str(state) == "error":
            self._renderer_failed = True
            if not self._compatibility_ui:
                self._set_viewport_controls_available(False)
            self.status.setText(str(message or "The viewport reported an error."))
