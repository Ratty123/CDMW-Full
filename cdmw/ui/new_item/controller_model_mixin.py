"""Draft edits and imported-model lifecycle operations for New Item Studio."""
from __future__ import annotations

import copy
import sys
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal

from cdmw.services.archive_workflow_service import archive_name_search_text_match, parse_archive_search_query
from cdmw.domain.cancellation import RunCancelled, raise_if_cancelled
from cdmw.domain.new_item.rules import ValidationIssue, has_errors
from cdmw.domain.new_item.spec import IconSource, ModelSource, NewItemSpec
from cdmw.models import ArchiveEntry
from cdmw.ui.new_item.blender_setting import blender_for_fbx
from cdmw.ui.new_item.model_import import (
    ModelImportSource,
    ModelPlacement,
    bake_mesh,
    build_placed_import,
    fbx_needing_blender,
    fbx_needs_blender_message,
    fitted_placement,
    load_model_import_source,
    mesh_bounds,
    mesh_centroid,
    prepare_model_import_mesh_edit,
)
from cdmw.services.effect_catalogue import EffectCatalogue
from cdmw.services.new_item_baseline import baseline_facts, baseline_lines
from cdmw.services.new_item_materials import glow_preview_mesh
from cdmw.services.new_item_planning import NewItemPlan, NewItemPlanError
from cdmw.services.new_item_service import NewItemInstallRefused, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot, NewItemSnapshotError
from cdmw.ui.new_item.effect_workspace_controller import NewItemEffectWorkspaceControllerMixin
from cdmw.ui.new_item.state import NewItemDraft, StatGrid, glow_choice, spec_from_draft, stat_grid_for, status_label, with_template
from cdmw.workers.effect_catalogue_worker import EffectCatalogueIndexLane
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane
from cdmw.workers.new_item_workers import export_task, install_overlay_task, install_task, overlay_migration_task, overlay_removal_task, plan_task, snapshot_task
from cdmw.workers.utility_workers import UtilityWorker


_BUILD_PLACED_IMPORT = build_placed_import
_BLENDER_FOR_FBX = blender_for_fbx
_LOAD_MODEL_IMPORT_SOURCE = load_model_import_source


def _controller_override(name: str, fallback):
    module = sys.modules.get("cdmw.ui.new_item.controller")
    return getattr(module, name, fallback) if module is not None else fallback


def build_placed_import(*args, **kwargs):
    return _controller_override("build_placed_import", _BUILD_PLACED_IMPORT)(*args, **kwargs)


def blender_for_fbx(*args, **kwargs):
    return _controller_override("blender_for_fbx", _BLENDER_FOR_FBX)(*args, **kwargs)


def load_model_import_source(*args, **kwargs):
    return _controller_override("load_model_import_source", _LOAD_MODEL_IMPORT_SOURCE)(*args, **kwargs)


class NewItemModelControllerMixin:
    # ------------------------------------------------------------------ edits

    def set_template(self, template_key: Optional[int]) -> None:
        if template_key is not None and (self.snapshot is None or template_key not in self.snapshot.rows):
            self.status_message.emit(f"Item {template_key} is not in the snapshot.", True)
            return
        self.draft = with_template(self.draft, template_key)
        self.invalidate_plan()
        self.model_result = None
        self.model_entry = None
        self.model_scene = None
        previous_import = self.model_import
        had_import = previous_import is not None
        self.model_import = None
        self.model_placement = ModelPlacement()
        self.template_changed.emit(template_key)
        if had_import:
            self.model_import_changed.emit(None)
        self._cleanup_model_source(previous_import)

    def set_imported_model(self, entry: Optional[ArchiveEntry], result: object | None, scene: object | None = None) -> None:
        """Take a Builder result for the template's mesh; None clears it. `scene` is the
        scene import the Builder ran from, when the hand-off carried it: the plain-PBR
        route reads the source's own textures through it."""

        self.model_result = result
        self.model_entry = entry
        self.model_scene = scene if result is not None else None
        self.draft.model_source = ModelSource.IMPORTED if (result is not None or self.model_import is not None) else ModelSource.TEMPLATE
        self.invalidate_plan()
        self.model_changed.emit(result)

    # ------------------------------------------------------------------ the studio's own import

    def template_bounds(self):
        """The template mesh's bounds in the game's frame, for the first fit; None without one."""

        return mesh_bounds(self._template_mesh())

    def template_centroid(self):
        return mesh_centroid(self._template_mesh())

    def _fitted_placement(self, source: ModelImportSource) -> ModelPlacement:
        return fitted_placement(
            source.bounds,
            source.fit_template_bounds,
            source_centroid=source.centroid,
            template_centroid=source.fit_template_centroid,
            match_grip=source.fit_match_grip,
        )

    def _template_uses_weapon_fit(self) -> bool:
        """Whether this template is hand-carried and benefits from grip alignment."""

        if self.snapshot is None or self.draft.template_key is None:
            return False
        try:
            row, family = self.snapshot.row(self.draft.template_key), self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001 - an unresolved family gets the generic fit
            return False
        from cdmw.domain.new_item.placement import HELD_PLACEMENT_FRAME, equipment_placement_frame

        return equipment_placement_frame(self.snapshot.equip_type_name(row), family.model_folder) == HELD_PLACEMENT_FRAME

    def _template_is_wearable(self) -> bool:
        """Whether Effects should preserve the template's authored body-frame origin."""

        if self.snapshot is None or self.draft.template_key is None:
            return False
        try:
            row, family = self.snapshot.row(self.draft.template_key), self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001 - an unresolved family keeps the ordinary origin
            return False
        from cdmw.domain.new_item.placement import BODY_PLACEMENT_FRAME, equipment_placement_frame
        return equipment_placement_frame(self.snapshot.equip_type_name(row), family.model_folder) == BODY_PLACEMENT_FRAME

    def _template_mesh(self):
        saved, self.model_result = self.model_result, None
        try:
            return self.item_mesh_for_preview()
        finally:
            self.model_result = saved

    def start_model_import(self, path: Path) -> bool:
        """Read a model file (or a zip holding one) for the studio's own placement: the
        scene import and the source's textures, off the UI thread. On success the model
        shows over the template at a first fit; a result built before is dropped."""

        chosen = Path(path)
        if self.snapshot is None or self.draft.template_key is None:
            self.status_message.emit("Choose a template first; the model is placed over its mesh.", True)
            return False

        # read on the UI thread, used on the worker: the Blender the reader chose, or ""
        blender = blender_for_fbx()

        # An FBX with no Blender is refused here rather than inside the read: the question
        # is answered from the file's name and a zip's listing, so nothing is extracted and
        # no worker starts. Starting one only to fail at the end left the step saying
        # "Reading the model file..." while a zip was unpacked for a conversion that could
        # never run.
        needs_blender = fbx_needing_blender(chosen)
        if needs_blender and not blender:
            message = fbx_needs_blender_message(needs_blender)
            self.status_message.emit(message, True)
            self.model_import_failed.emit(message)
            return False

        import_snapshot = self.snapshot
        import_template_key = int(self.draft.template_key)
        template_geometry = self._template_geometry_build()
        template_build = template_geometry[1] if template_geometry is not None else None
        match_grip = self._template_uses_weapon_fit()

        def task(log, progress, stop_event):
            def report(message: str) -> None:
                log(message)
                progress(0, 0, message)

            report(f"Reading {chosen.name}...")
            result = load_model_import_source(chosen, stop_event=stop_event, blender_path=blender, on_log=report)
            template_mesh = None
            if template_build is not None:
                try:
                    template_mesh = template_build(stop_event)
                except RunCancelled:
                    raise
                except Exception:  # noqa: BLE001 - an unreadable template preserves the identity-fit fallback
                    template_mesh = None
            result.fit_template_bounds = mesh_bounds(template_mesh)
            result.fit_template_centroid = mesh_centroid(template_mesh)
            result.fit_match_grip = bool(match_grip)
            result.set_bake(
                fitted_placement(
                    result.bounds,
                    result.fit_template_bounds,
                    source_centroid=result.centroid,
                    template_centroid=result.fit_template_centroid,
                    match_grip=result.fit_match_grip,
                )
            )
            progress(1, 1, "Model source ready")
            return result

        def done(result: object) -> None:
            if not isinstance(result, ModelImportSource):
                self.status_message.emit("The model import finished with an unexpected result.", True)
                return
            if self.snapshot is not import_snapshot or self.draft.template_key != import_template_key:
                self._cleanup_model_source(result)
                return
            previous = self.model_import
            self.model_import = result
            self.model_placement = ModelPlacement()
            if self.model_result is not None:
                self.set_imported_model(None, None)
            self.draft.model_source = ModelSource.IMPORTED
            self.invalidate_plan()
            self.model_import_changed.emit(result)
            self.model_placement_changed.emit(self.model_placement)
            if previous is not result:
                self._cleanup_model_source(previous)

        def failed(message: str) -> None:
            # both places: the window's status line, and the step the reader is looking at,
            # whose note is otherwise left mid-read
            said = f"The model could not be read: {message}"
            self.status_message.emit(said, True)
            self.model_import_failed.emit(said)

        return self._run("model_import", task, done, failed, task_accepts_progress=True)

    def set_model_placement(self, placement: ModelPlacement) -> None:
        """Move the imported model (the gizmo, the numbers, a fit, a reset). A result
        built at another placement is dropped: it no longer says where the model sits."""

        self.model_placement = placement
        source = self.model_import
        if self.model_result is not None and source is not None and source.applied != (source.bake, placement):
            self.set_imported_model(None, None)
        self.invalidate_plan()
        self.model_placement_changed.emit(placement)

    def fit_model_placement(self) -> None:
        """Re-fit the model to the template: the fit is baked into the mesh the viewport
        and the build see, and the numbers go back to zero on top of it."""

        source = self.model_import
        if source is None:
            return
        source.set_bake(self._fitted_placement(source))
        if self.model_result is not None:
            self.set_imported_model(None, None)
        self.model_placement = ModelPlacement()
        self.invalidate_plan()
        self.model_import_changed.emit(source)
        self.model_placement_changed.emit(self.model_placement)

    def start_model_apply(self) -> bool:
        """Build the item's mesh from the imported model at its placement: the Builder's
        import over the template's mesh, headless, off the UI thread. The result is what
        the plan writes (the rebuilt mesh and its side files)."""

        source = self.model_import
        entries = self.template_entries()
        if source is None or not entries:
            self.status_message.emit("Import a model first; there is nothing to place.", True)
            return False
        entry = entries[0]
        placement = self.model_placement
        context = self.import_dependency_context()
        by_path = getattr(context, "entries_by_normalized_path", None)
        by_basename = getattr(context, "entries_by_basename", None)

        def task(log, progress, stop_event):
            with source.usage():
                log(f"Building {entry.basename} from {source.label} at its placement...")
                return build_placed_import(
                    entry,
                    source,
                    placement,
                    entries_by_normalized_path=by_path,
                    entries_by_basename=by_basename,
                    stop_event=stop_event,
                    on_progress=progress,
                )

        def done(result: object) -> None:
            source.applied = (source.bake, placement)
            self.set_imported_model(entry, result, source.scene)

        def failed(message: str) -> None:
            self.status_message.emit(f"The placement could not be built: {message}", True)

        return self._run("model_apply", task, done, failed, task_accepts_progress=True)

    def start_model_part_edit_apply(
        self,
        source: ModelImportSource,
        mesh_controller: object,
        *,
        expected_session_id: str,
        wait_for_updates: Optional[Callable[[float], bool]] = None,
    ) -> bool:
        """Capture one stable Mesh Editor revision and publish it as this import.

        Resident geometry hydration and textured-preview preparation both run in the
        owned worker lane. Publication remains source/session/revision correlated.
        """

        if source is not self.model_import:
            self.status_message.emit("Open this imported model in Mesh Editor first.", True)
            return False
        session_id = str(expected_session_id or "")
        scene = copy.copy(source.scene)
        model_path = Path(source.model_path)

        def task(log, stop_event):
            with source.usage():
                if callable(wait_for_updates) and not wait_for_updates(10.0):
                    raise RuntimeError("The Mesh Editor revision could not be captured safely.")
                if str(getattr(mesh_controller, "active_session_id", "") or "") != session_id:
                    raise RuntimeError("The Mesh Editor revision could not be captured safely.")
                before = mesh_controller.session_view()
                mesh = mesh_controller.working_mesh(clone=True)
                after = mesh_controller.session_view()
                if before.session_id != session_id or after.session_id != session_id or before.revision != after.revision:
                    raise RuntimeError("The Mesh Editor revision could not be captured safely.")
                log("Preparing the Mesh Editor changes...")
                prepared = prepare_model_import_mesh_edit(
                    mesh,
                    scene=scene,
                    model_path=model_path,
                    stop_event=stop_event,
                )
                return after.revision, prepared

        def done(result: object) -> None:
            if source is not self.model_import:
                return
            try:
                revision, prepared = result  # type: ignore[misc]
                current = mesh_controller.session_view()
                if current.session_id != session_id or current.revision != int(revision):
                    raise RuntimeError("The Mesh Editor revision could not be captured safely.")
                edited_scene, preview_model, bounds, centroid, texture_count = prepared
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as exc:
                failed(str(exc))
                return
            source.scene = edited_scene
            source.preview_model = preview_model
            source.bounds = bounds
            source.centroid = centroid
            source.texture_count = int(texture_count)
            source.mesh_generation += 1
            source._baked_scene_mesh = None
            source._baked_preview_mesh = None
            source.applied = None
            self._material_parts = ()
            if self.model_result is not None:
                self.set_imported_model(None, None)
            else:
                self.invalidate_plan()
            self.model_import_changed.emit(source)
            self.model_part_edit_finished.emit(source)

        def failed(message: str) -> None:
            said = f"Mesh Editor changes could not be used: {message}"
            self.status_message.emit(said, True)
            self.model_part_edit_failed.emit(said)

        return self._run("model_part_edit", task, done, failed)

    def discard_model(self) -> None:
        """Drop the imported model, its placement and any result: back to the template's model."""
        if self._lane in {"model_import", "model_apply", "model_part_edit"}:
            self.cancel_operation(self._lane)
        previous = self.model_import
        self.model_import = None
        self.model_placement = ModelPlacement()
        if self.model_result is not None:
            self.set_imported_model(None, None)
        else:
            self.draft.model_source = ModelSource.TEMPLATE
            self.invalidate_plan()
        self.model_import_changed.emit(None)
        self._cleanup_model_source(previous)
