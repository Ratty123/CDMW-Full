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
    MeshGeometryAnalysis,
    ModelImportSource,
    ModelPlacement,
    analyze_mesh_geometry,
    bake_mesh,
    build_placed_import,
    fbx_needing_blender,
    fbx_needs_blender_message,
    fitted_placement,
    load_model_import_source,
    mesh_bounds,
    mesh_centroid,
    mesh_principal_frame,
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


def _translucency_for_parts(choice, remaining_parts):
    """`choice` limited to the parts that still exist, or None when none do."""
    if choice is None:
        return None
    parts = tuple(name for name in choice.parts if name.casefold() in remaining_parts)
    if not parts:
        return None
    if parts == tuple(choice.parts):
        return choice
    return replace(
        choice, parts=parts,
        part_settings=tuple(row for row in choice.part_settings if row[0].casefold() in remaining_parts),
        surface_settings=tuple(row for row in choice.surface_settings if row[0].casefold() in remaining_parts),
        masks=tuple(row for row in choice.masks if row[0].casefold() in remaining_parts))


def load_model_import_source(*args, **kwargs):
    return _controller_override("load_model_import_source", _LOAD_MODEL_IMPORT_SOURCE)(*args, **kwargs)


class NewItemModelControllerMixin:
    def start_transparency_paint(self, part, mode, on_ready):
        """Capture the selected material and retain its input until preparation ends."""
        if mode not in {"translucency", "blending", "cutout"}:
            raise ValueError("Unknown transparency mode.")
        identity = self.current_variant_identity()
        if self.snapshot is None or identity is None:
            self.status_message.emit("Choose a template and model variant before painting transparency.", True)
            return False
        self._capture_variant(identity)
        appearance = self._variant_states[identity].appearance
        if mode == "translucency":
            valid = appearance.translucency is not None and appearance.translucency.matches(part)
        else:
            from cdmw.domain.mesh.shader_controls import EYE_COVER
            choice = dict(appearance.shader_controls).get(part)
            valid = choice is not None and choice.shader == ("SkinnedMeshWing" if mode == "cutout" else EYE_COVER.shader)
        if not valid:
            self.status_message.emit("Enable transparency on this part before painting its mask.", True)
            return False
        snapshot, source, result, scene = self.snapshot, self.model_import, self.model_result, self.model_scene
        template_key, revision = self.draft.template_key, self._draft_revision
        session = (snapshot, identity, source, result, revision, part, mode)
        # Resolve the real output bindings without committing the user's placement.
        # Freeze the import just as Apply placement does; the worker lease below
        # keeps its source files alive until both conversion and painting are ready.
        build_source = copy.copy(source) if appearance.custom_model and result is None and source is not None else None
        placement = self.model_placement

        def task(log, progress, stop_event):
            from cdmw.services.new_item_transparency_paint import prepare_transparency_paint
            paint_result, paint_scene = result, scene
            try:
                raise_if_cancelled(stop_event)
                if build_source is not None:
                    by_path, by_basename = snapshot.archive_index_maps()
                    paint_result = build_placed_import(
                        snapshot.entry(identity[1]), build_source, placement,
                        entries_by_normalized_path=by_path, entries_by_basename=by_basename,
                        attachment_prefab_data=snapshot.payload(identity[0]),
                        stop_event=stop_event, on_progress=progress,
                    )
                    paint_scene = build_source.scene
                raise_if_cancelled(stop_event)
                return prepare_transparency_paint(snapshot, appearance, part, mode, template_key=template_key,
                    result=paint_result, scene=paint_scene, on_log=log, stop_event=stop_event)
            finally:
                if build_source is not None:
                    cleanup = getattr(paint_result, "cleanup", None)
                    if callable(cleanup):
                        cleanup()

        def done(prepared):
            if self._transparency_paint_current(session):
                on_ready(session, prepared)

        return self._run("transparency_mask", task, done,
                         lambda message: self.status_message.emit(message, True),
                         task_accepts_progress=True,
                         source_owners=(source,) if source is not None else ())

    def _transparency_paint_current(self, session):
        snapshot, identity, source, result, revision, _part, _mode = session
        return (not self._shutdown_requested and snapshot is self.snapshot
                and identity == self.current_variant_identity() and source is self.model_import
                and result is self.model_result and revision == self._draft_revision)

    def start_transparency_mask_io(self, session, task, on_done, on_error):
        if not self._transparency_paint_current(session):
            on_error("The model or material changed. Reopen the painter for the current part.")
            return True
        def done(result):
            if self._transparency_paint_current(session):
                on_done(result)
            else:
                on_error("The model or material changed. Reopen the painter for the current part.")
        return self._run("transparency_mask", task, done, on_error)

    def apply_transparency_paint(self, session, mask, *, target="colour"):
        if not self._transparency_paint_current(session):
            raise ValueError("The model or material changed. Close this painter and reopen it for the current part.")
        part, mode = session[-2:]
        if mode == "translucency":
            choice = self.draft.translucency
            masks = tuple((name, value) for name, value in choice.masks if name.casefold() != part.casefold())
            updated = replace(choice, masks=masks + (((part, mask),) if mask is not None else ()))
            updated.validate()
            self.draft.translucency = updated
        else:
            from cdmw.domain.mesh.shader_controls import ShaderControls
            if target not in {"colour", "surface", "linked"}:
                raise ValueError("Unknown transparency painting target.")
            current = dict(self.draft.shader_controls)[part]
            if isinstance(mask, ShaderControls):
                if mask.shader != current.shader:
                    raise ValueError("The shader changed while painting.")
                changes = {key: getattr(mask, key) for key in ("transparency_mask", "surface_response_mask", "cutout_mask")}
            elif mode == "cutout":
                changes = {"cutout_mask": mask}
            else:
                changes = {}
                if target in {"colour", "linked"}:
                    changes["transparency_mask"] = mask
                if target in {"surface", "linked"}:
                    changes["surface_response_mask"] = mask
            updated = tuple((name, replace(choice, **changes) if name == part else choice)
                            for name, choice in self.draft.shader_controls)
            for _, choice in updated:
                choice.validate()
            self.draft.shader_controls = updated
        self.invalidate_plan()
        self.transparency_mask_changed.emit()

    # ------------------------------------------------------------------ edits

    def set_template(self, template_key: Optional[int]) -> None:
        if template_key is not None and (self.snapshot is None or template_key not in self.snapshot.rows):
            self.status_message.emit(f"Item {template_key} is not in the snapshot.", True)
            return
        if template_key is None:
            self._template_request = None
            self._template_parts = {}
            self._template_shader_options = {}
            self._template_translucency = {}
            self._template_selection_lane.cancel()
            self._commit_template(None)
        else:
            self._template_request = (self.snapshot, template_key)
            self._template_selection_lane.request(self.snapshot, template_key)

    def _template_prepared(self, snapshot, key, facts) -> None:
        if snapshot is not self.snapshot or self._shutdown_requested:
            return
        self._template_request = None
        self._template_parts = facts.parts
        self._template_shader_options = facts.shader_options
        self._template_translucency = facts.translucency
        self._commit_template(key)

    def _template_failed(self, message) -> None:
        self._template_request = None
        self.log_message.emit(message)
        self.status_message.emit(message, True)
        self.template_failed.emit(str(message))

    def _commit_template(self, template_key) -> None:
        self.clear_installed_reference()
        self.reset_variants()
        # A continued package is written back only while its own item is open.
        self.forget_continued_package()
        self.draft = with_template(self.draft, template_key)
        context = self.snapshot._contexts.get(template_key) if self.snapshot is not None else None
        if context is not None and not context.template.equip_type_name and context.template.use_actions:
            from cdmw.domain.new_item.item_settings import ItemSettings
            self.draft.item_settings = ItemSettings(use_actions=context.template.use_actions)
        self.invalidate_plan()
        self.model_result = None
        self.model_entry = None
        self.model_scene = None
        previous_import = self.model_import
        had_import = previous_import is not None
        self.model_import = None
        self.model_placement = ModelPlacement()
        if self.skeleton_edits:
            # Skeleton edits are checked against one template's rigs.
            self._set_skeleton_edits(())
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
            level_to_grid=source.fit_match_grip,
            source_frame=source.principal_frame,
            template_frame=source.fit_template_frame,
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

    def template_is_worn(self) -> bool:
        """Whether the template is worn on the body (armour, clothing), not held or placed."""

        return self._template_is_wearable()

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

    def clear_installed_reference(self) -> None:
        source, self.installed_reference = self.installed_reference, None
        self._cleanup_model_source(source)
        self.installed_reference_changed.emit(None)

    def start_installed_reference(self, request) -> bool:
        """Load an installed asset for viewing only; never put it in the item recipe."""
        snapshot, key, variant = self.snapshot, self.draft.template_key, self._active_variant
        if snapshot is None or key is None:
            return False

        def task(log, progress, stop_event):
            from cdmw.ui.new_item.installed_model_import import load_installed_model
            return load_installed_model(request, snapshot, stop_event=stop_event, on_log=log)

        def done(result):
            if self.snapshot is not snapshot or self.draft.template_key != key or self._active_variant != variant:
                self._cleanup_model_source(result)
                self.installed_reference_failed.emit("The template changed. Choose the fitting reference again.")
                return
            previous, self.installed_reference = self.installed_reference, result
            self.installed_reference_changed.emit(result)
            self._cleanup_model_source(previous)

        return self._run("installed_reference", task, done, self.installed_reference_failed.emit,
                         task_accepts_progress=True)

    def start_model_import(self, path: Path, *, skin_policy="preserve", palette_extension_bones=(), installed_model=None) -> bool:
        """Read a model file (or a zip holding one) for the studio's own placement: the
        scene import and the source's textures, off the UI thread. On success the model
        shows over the template at a first fit; a result built before is dropped."""

        # Compatibility for older callers: installed files are never authored models.
        if installed_model is not None:
            return self.start_installed_reference(installed_model)
        chosen = Path(path)
        if self.snapshot is None or self.draft.template_key is None:
            self.status_message.emit("Choose a template first; the model is placed over its mesh.", True)
            return False

        if self._active_variant is None and self.snapshot.sources and self.snapshot.sources.static_layout:
            primary = self.primary_variant_identity()
            if primary is not None:
                self.select_variant(primary)

        # read on the UI thread, used on the worker: the Blender the reader chose, or ""
        blender = blender_for_fbx()

        import_snapshot = self.snapshot
        import_template_key = int(self.draft.template_key)
        import_variant = self._active_variant
        import_entry = self.template_primary_entry()
        skeleton_edits = self.skeleton_edits
        wearable = self._template_is_wearable()
        template_geometry = self._template_geometry_build()
        template_build = template_geometry[1] if template_geometry is not None else None
        match_grip = self._template_uses_weapon_fit()

        def task(log, progress, stop_event):
            def report(message: str) -> None:
                log(message)
                progress(0, 0, message)

            report(f"Inspecting {chosen.name}...")
            needs_blender = fbx_needing_blender(chosen)
            raise_if_cancelled(stop_event)
            if needs_blender and not blender:
                raise ValueError(fbx_needs_blender_message(needs_blender))
            report(f"Reading {chosen.name}...")
            result = load_model_import_source(chosen, stop_event=stop_event, blender_path=blender, on_log=report)
            try:
                from cdmw.services.mesh_skinning_preflight import has_authored_skin, prepare_new_item_skin
                authored = has_authored_skin(result.scene.mesh)
                if wearable:
                    result.skinning_target = import_entry.path
                if authored:
                    from cdmw.domain.mesh.skin_policy import SkinningChoice
                    choices = tuple(SkinningChoice(i, skin_policy) for i, part in enumerate(result.scene.mesh.submeshes)
                                    if part.interchange_skin or part.bone_indices or part.bone_weights)
                    from cdmw.ui.new_item.model_import import prepare_model_import_mesh_edit
                    mesh, reports = prepare_new_item_skin(
                        result.scene.mesh, import_snapshot, import_entry.path, choices=choices, stop_event=stop_event,
                        **({"palette_extension_bones":tuple(palette_extension_bones)} if palette_extension_bones else {}),
                        **({"skeleton_edits": skeleton_edits} if skeleton_edits else {}))
                    result.skeleton_edit = getattr(mesh, "interchange_skeleton_edit", None)
                    result.scene, result.preview_model, analysis, result.texture_count = prepare_model_import_mesh_edit(
                        mesh, scene=result.scene, model_path=result.model_path, stop_event=stop_event)
                    result.preview_mesh = mesh
                    result.bounds, result.centroid, result.principal_frame = analysis.bounds, analysis.centroid, analysis.principal_frame
                    result.skinning_reports, result.skinning_target = reports, import_entry.path
                    result.skinning_choices = choices
                    result.notes += tuple(item.summary() for item in reports)
                raise_if_cancelled(stop_event, "Model import cancelled before template fitting.")
                template_mesh = None
                if template_build is not None:
                    try:
                        template_mesh = template_build(stop_event)
                    except RunCancelled:
                        raise
                    except Exception:  # noqa: BLE001 - an unreadable template preserves the identity-fit fallback
                        template_mesh = None
                template_analysis = analyze_mesh_geometry(template_mesh)
                result.fit_template_bounds = template_analysis.bounds
                result.fit_template_centroid = template_analysis.centroid
                result.fit_template_frame = template_analysis.principal_frame
                result.fit_match_grip = bool(match_grip)
                # A garment is authored in the body's frame. Matching its shape axes to a
                # differently shaped template turns it at a hidden angle, so it stays as
                # authored; Fit to template remains for a model made elsewhere.
                result.set_bake(
                    ModelPlacement() if authored or wearable else fitted_placement(
                        result.bounds,
                        result.fit_template_bounds,
                        source_centroid=result.centroid,
                        template_centroid=result.fit_template_centroid,
                        match_grip=result.fit_match_grip,
                        level_to_grid=result.fit_match_grip,
                        source_frame=result.principal_frame,
                        template_frame=result.fit_template_frame,
                    )
                )
                if not stop_event.is_set():
                    # The UI reads fitted bounds as soon as this result is published.
                    # Materialize that mesh here so the first read is a cache lookup.
                    result.baked_scene_mesh()
                progress(1, 1, "Model source ready")
                return result
            except BaseException:
                result.cleanup()
                raise

        def done(result: object) -> None:
            if not isinstance(result, ModelImportSource):
                self.status_message.emit("The model import finished with an unexpected result.", True)
                return
            if self.snapshot is not import_snapshot or self.draft.template_key != import_template_key:
                self._cleanup_model_source(result)
                return
            if self._active_variant != import_variant and import_variant is not None:
                # Another row was selected while reading: the model still belongs to
                # the component it was imported for. Store it there, unapplied.
                from cdmw.domain.new_item.authoring import VariantAppearance
                from cdmw.ui.new_item.controller_variant_mixin import VariantModelState
                state = self._variant_states.setdefault(import_variant, VariantModelState(VariantAppearance(*import_variant)))
                previous_source = state.source
                state.source, state.result, state.entry, state.scene = result, None, None, None
                state.placement = ModelPlacement()
                state.glow_parts = ()
                state.appearance = replace(state.appearance, custom_model=True, template_transform=(), glow_parts=(),
                                           translucency=None, shader_controls=(), surface_settings=(), dyes=())
                self.invalidate_plan()
                self.log_message.emit(f"{result.chosen_path.name} was imported for {import_variant[1].rsplit('/', 1)[-1]}; "
                                      "select that component and apply its placement.")
                if previous_source is not result:
                    self._cleanup_model_source(previous_source)
                return
            previous = self.model_import
            self.model_import = result
            self.model_placement = ModelPlacement()
            self.draft.template_transform = ()
            self.draft.glow_parts = ()
            self.draft.translucency = None
            self.draft.shader_controls = ()
            self.draft.surface_settings = ()
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

    def start_add_bones(self) -> bool:
        """Read the current variant's skeleton off the UI thread for the Add Bones dialog.

        ``rig_source_ready`` then carries ``(pab bytes, pab path)``; the dialog's result
        comes back through :meth:`set_skeleton_edit`."""

        snapshot, entry = self.snapshot, self.template_primary_entry()
        if snapshot is None or entry is None:
            self.status_message.emit("Choose a template first; bones are added to its skeleton.", True)
            return False
        template_key, variant = self.draft.template_key, self._active_variant

        def task(log, progress, stop_event):
            from cdmw.services.mesh_skinning_preflight import rig_path, template_skeleton
            progress(0, 0, "Reading the template skeleton")
            _skeleton, data, pab_path, _edit = template_skeleton(snapshot, entry.path)
            raise_if_cancelled(stop_event)
            return data, rig_path(pab_path)

        def done(source):
            if (self.snapshot is not snapshot or self.draft.template_key != template_key
                    or self._active_variant != variant):
                return
            self.rig_source_ready.emit(source)

        def failed(message):
            self.status_message.emit(f"The template skeleton could not be read: {message}", True)

        return self._run("rig_source", task, done, failed, task_accepts_progress=True)

    def set_skeleton_edit(self, pab_path: str, edits) -> None:
        """Keep ``edits`` (validated PabAppendEdit rows) as the skeleton edit for one rig.

        One edit is kept per rig, so a male and a female variant can each have one; no
        edits removes that rig's. A model already imported with its own weights is
        weighted again once the controller is idle."""

        from cdmw.services.pab_skeleton_edit_service import SkeletonEditRecipe
        edits = tuple(edits)
        others = tuple(edit for edit in self.skeleton_edits if edit.path != pab_path)
        if not edits:
            if len(others) != len(self.skeleton_edits):
                self._set_skeleton_edits(others)
                if not self._reweight_for_skeleton_edits():
                    self._warn_stale_skeleton_edit()
            return
        recipe = SkeletonEditRecipe(pab_path, edits)
        if recipe in self.skeleton_edits:
            return
        self._set_skeleton_edits((*others, recipe))
        names = ", ".join(recipe.bone_names)
        if self._reweight_for_skeleton_edits():
            self.status_message.emit(f"Skeleton edit ready: {names}. Weighting the imported model again.", False)
        else:
            self.status_message.emit(
                f"Skeleton edit ready: {names}. Import a rigged model to weight it against this rig.", False)
            # Shown last, so the status line keeps it.
            self._warn_stale_skeleton_edit()

    def clear_skeleton_edit(self) -> None:
        if self.skeleton_edits:
            self._set_skeleton_edits(())
            if not self._reweight_for_skeleton_edits():
                self._warn_stale_skeleton_edit()

    def _warn_stale_skeleton_edit(self) -> None:
        """Say so when the imported model still uses added bones that were changed or removed since."""
        source = self.model_import
        if source is not None and source.skeleton_edit is not None and source.skeleton_edit not in self.skeleton_edits:
            self.status_message.emit("The imported model is weighted to added bones that were changed or removed; "
                                     "import it again to weight it to the current skeleton.", True)

    def _set_skeleton_edits(self, edits) -> None:
        self.skeleton_edits = tuple(sorted(edits, key=lambda edit: edit.path))
        self.skeleton_edit_changed.emit(self.skeleton_edits)

    def _reweight_for_skeleton_edits(self) -> bool:
        """Re-prepare a model imported with its own weights against the current rigs.

        Called from a finishing task, it waits until the controller is idle."""
        source = self.model_import
        if (source is None or source.raw_import_mesh is None or not source.skinning_target
                or not source.skinning_choices or source.mesh_generation != source.skinning_generation):
            return False
        if self.busy:
            self._reweight_pending = True
            return True
        return self.start_model_skinning(source.skinning_choices)

    def _run_pending_reweight(self, busy: bool) -> None:
        if not busy and self._reweight_pending:
            self._reweight_pending = False
            # After every other listener has seen the controller go idle.
            QTimer.singleShot(0, self, self._reweight_for_skeleton_edits)

    def start_rig_export(self, output_dir: Path) -> bool:
        """Write the template skinned to its rig (with the matching skeleton edit's bones) as GLB."""

        snapshot, entry, edits = self.snapshot, self.template_primary_entry(), self.skeleton_edits
        if snapshot is None or entry is None:
            self.status_message.emit("Choose a template first; its mesh and rig are exported.", True)
            return False
        folder = Path(output_dir)

        def task(log, progress, stop_event):
            from cdmw.services.mesh_skinning_preflight import export_template_rig_glb
            progress(0, 0, "Exporting the template rig")
            return export_template_rig_glb(snapshot, entry.path, folder, skeleton_edits=edits, stop_event=stop_event)

        def done(paths):
            self.status_message.emit(f"Rig exported: {paths[0]}", False)

        def failed(message):
            self.status_message.emit(f"The rig could not be exported: {message}", True)

        return self._run("rig_export", task, done, failed, task_accepts_progress=True)

    def start_model_skinning(self, choices) -> bool:
        """Re-prepare explicit per-part decisions from the retained original skin."""
        source, snapshot, variant = self.model_import, self.snapshot, self._active_variant
        if source is None or source.raw_import_mesh is None or not source.skinning_target:
            return False
        if source.mesh_generation != source.skinning_generation:
            self.status_message.emit("Re-import before changing skin policy after Mesh Editor geometry edits.", True)
            return False
        choices, generation = tuple(choices), source.mesh_generation
        draft_revision = self._draft_revision
        source_bake, placement, flip = source.bake, self.model_placement, source.flip_texture_v
        from cdmw.modding.mesh_glb_assets import transpose
        from cdmw.modding.scene_geometry_utils import _multiply_matrix
        # Placement uses row vectors; the donor sampler uses column vectors.
        # Apply the fit first, then placement about the fitted origin.
        transfer_transform = _multiply_matrix(
            transpose(placement.matrix(origin=source.baked_origin())), transpose(source_bake.matrix()))
        target = source.skinning_target
        captured_scene = source.scene
        extension = getattr(captured_scene.mesh, "interchange_palette_extension", None)
        # Added bones come back from whichever skeleton edit matches the rig now.
        previous_added = set(source.skeleton_edit.bone_names) if source.skeleton_edit is not None else set()
        extension_bones = tuple(name for name in (extension.appended_names if extension is not None else ())
                                if name not in previous_added)
        skeleton_edits = self.skeleton_edits

        def task(log, progress, stop_event):
            from cdmw.services.mesh_skinning_preflight import prepare_new_item_skin
            with source.usage():
                progress(0, 0, "Checking imported skin weights")
                mesh, reports = prepare_new_item_skin(source.raw_import_mesh, snapshot, target,
                    choices=choices, stop_event=stop_event, transfer_transform=transfer_transform,
                    palette_extension_bones=extension_bones,
                    **({"skeleton_edits": skeleton_edits} if skeleton_edits else {}))
                skeleton_edit = getattr(mesh, "interchange_skeleton_edit", None)
                prepared = prepare_model_import_mesh_edit(mesh, scene=captured_scene,
                    model_path=source.model_path, stop_event=stop_event)
                baked = bake_mesh(mesh, source_bake)
                for report in reports:
                    log(report.summary())
                return prepared, reports, baked, skeleton_edit

        def done(result):
            if (self.snapshot is not snapshot or self.model_import is not source or self._active_variant != variant
                    or self._draft_revision != draft_revision
                    or source.mesh_generation != generation or source.bake != source_bake
                    or self.model_placement != placement or source.flip_texture_v != flip):
                return
            prepared, reports, baked, skeleton_edit = result
            source.skeleton_edit = skeleton_edit
            scene, preview, analysis, textures = prepared
            source.scene, source.preview_model, source.preview_mesh = scene, preview, scene.mesh
            source.bounds, source.centroid, source.principal_frame = analysis.bounds, analysis.centroid, analysis.principal_frame
            source.texture_count, source.skinning_reports, source.skinning_choices = textures, reports, choices
            source.notes = tuple(item.summary() for item in reports)
            source.mesh_generation += 1
            source.skinning_generation = source.mesh_generation
            source.set_bake(source_bake)
            source._baked_scene_mesh = source._baked_preview_mesh = baked
            source.applied = None
            self.model_placement = placement
            self.set_imported_model(None, None)
            self.model_import_changed.emit(source)
            self.model_placement_changed.emit(self.model_placement)

        def failed(message):
            self.status_message.emit(f"Skin weights could not be prepared: {message}", True)
            self.model_apply_failed.emit(f"Skin weights could not be prepared: {message}")

        return self._run("model_skinning", task, done, failed, task_accepts_progress=True, source_owners=(source,))

    def start_hide_model_variant(self) -> bool:
        """Prepare a reversible hidden companion without changing other family slots."""
        if self.snapshot is None or self.draft.template_key is None:
            return False
        if self._active_variant is None:
            primary = self.primary_variant_identity()
            if primary is None:
                return False
            self.select_variant(primary)
        snapshot, variant, source, entry = self.snapshot, self._active_variant, self.model_import, self.template_primary_entry()
        def model_choices():
            draft = self.draft
            return (draft.model_source, draft.keep_template_physics, draft.material_route, tuple(draft.template_transform),
                    tuple(draft.glow_parts), draft.translucency, tuple(draft.shader_controls), tuple(draft.surface_settings),
                    self.model_placement, self.model_result)
        started_with = model_choices()
        def task(log, stop_event):
            from cdmw.services.new_item_skinning import hide_variant_geometry
            log(f"Hiding geometry in {entry.basename} at every LOD.")
            return hide_variant_geometry(snapshot, entry.path, stop_event=stop_event)
        def done(result):
            # A newer model choice wins over the pending hide; an unrelated edit
            # (a body-visibility choice, say) must not silently drop it.
            if self.snapshot is not snapshot or self._active_variant != variant or self.model_import is not source:
                return
            if model_choices() != started_with:
                self._hidden_restore.pop(variant, None)
                self.status_message.emit("Hide in export was not applied: the component's model changed while it ran.", False)
                return
            self.model_import = None
            self.model_placement = ModelPlacement()
            self.draft.template_transform = ()
            self.draft.glow_parts, self.draft.shader_controls, self.draft.surface_settings = (), (), ()
            self.draft.translucency = None
            self.draft.keep_template_physics = False
            self.set_imported_model(entry, result)
            self.model_import_changed.emit(None)
            self.model_placement_changed.emit(self.model_placement)
            # Show in export restores a stashed import; only an unstashed one is released.
            if not any(stash.source is source for stash in self._hidden_restore.values()):
                self._cleanup_model_source(source)
        def failed(message):
            self._hidden_restore.pop(variant, None)
            self.status_message.emit(f"The variant could not be hidden: {message}", True)
        return self._run("model_hide", task, done, failed, source_owners=(source,) if source else ())

    def set_model_placement(self, placement: ModelPlacement) -> None:
        """Move the active model (the gizmo, the numbers, a fit, a reset). A result
        built at another placement is dropped: it no longer says where the model sits."""

        self.model_placement = placement
        source = self.model_import
        self.draft.template_transform = tuple(placement.matrix()) if source is None and not placement.is_identity else ()
        if self.model_result is not None and source is not None and source.applied != (source.bake, placement):
            self.set_imported_model(None, None)
        self.invalidate_plan()
        self.model_placement_changed.emit(placement)

    def fit_model_placement(self) -> None:
        """Re-fit the model to the template. The fit becomes the placement numbers over
        the model as imported, so its turn shows under Rotation and Reset rotation
        undoes it; an earlier first fit is no longer baked into the mesh."""

        source = self.model_import
        if source is None:
            self.set_model_placement(ModelPlacement())
            return
        # With no bake the anchor is the model's own origin, where the
        # anchored placement is exactly the fitted transform.
        source.set_bake(ModelPlacement())
        if self.model_result is not None:
            self.set_imported_model(None, None)
        self.model_placement = self._fitted_placement(source)
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
        entry = self.template_primary_entry()
        placement = self.model_placement
        snapshot = self.snapshot
        variant = self._active_variant
        source_bake = source.bake
        source_generation = source.mesh_generation
        source_flip = source.flip_texture_v
        source_cloth = (source.own_cloth_guides, source.cloth_profile)
        model_source = self.draft.model_source
        keep_physics = self.draft.keep_template_physics
        # A UI edit must not change the inputs underneath the worker. Source
        # leases still belong to the original import; the copy freezes its values.
        build_source = copy.copy(source)

        def task(log, progress, stop_event):
            with source.usage():
                raise_if_cancelled(stop_event)
                by_path, by_basename = snapshot.archive_index_maps() if snapshot is not None else (None, None)
                log(f"Building {entry.basename} from {source.label} at its placement...")
                return build_placed_import(
                    entry,
                    build_source,
                    placement,
                    entries_by_normalized_path=by_path,
                    entries_by_basename=by_basename,
                    attachment_prefab_data=snapshot.payload(variant[0]) if snapshot is not None and variant else b"",
                    stop_event=stop_event,
                    on_progress=progress,
                    on_log=log,
                    keep_template_physics=keep_physics,
                )

        def done(result: object) -> None:
            if (self.snapshot is not snapshot or self.model_import is not source or self._active_variant != variant
                    or self.model_placement != placement or source.bake != source_bake
                    or source.mesh_generation != source_generation or source.flip_texture_v != source_flip
                    or (source.own_cloth_guides, source.cloth_profile) != source_cloth
                    or self.draft.keep_template_physics != keep_physics
                    or self.draft.model_source != model_source):
                cleanup = getattr(result,"cleanup",None)
                if callable(cleanup):
                    self._model_cleanup_lane.retire(result)
                return
            source.applied = (source.bake, placement)
            self.set_imported_model(entry, result, source.scene)
            self.log_message.emit(f"Placement applied to {entry.basename}.")

        def failed(message: str) -> None:
            said = f"The placement could not be built: {message}"
            self.status_message.emit(said, True)
            self.log_message.emit(said)
            self.model_apply_failed.emit(said)

        return self._run("model_apply", task, done, failed, task_accepts_progress=True, source_owners=(source,))

    def start_model_editor_session(self, on_ready, on_error) -> bool:
        from cdmw.workers.new_item_mesh_session import prepare_new_item_mesh_session
        source = self.model_import
        if source is None:
            return False
        snapshot, variant, generation = self.snapshot, self._active_variant, source.mesh_generation
        mesh = source.scene.mesh
        session_id = f"new-item-model:{id(source):x}:{generation}"
        def task(log, stop_event):
            log("Preparing Mesh Editor…")
            return prepare_new_item_mesh_session(mesh, session_id, stop_event)
        def done(result):
            if (self.model_import is not source or self.snapshot is not snapshot
                    or self._active_variant != variant or source.mesh_generation != generation):
                self._model_cleanup_lane.retire(result)
                return
            try:
                on_ready(result)
            finally:
                if not result.adopted:
                    self._model_cleanup_lane.retire(result)
        return self._run("model_editor", task, done, on_error, source_owners=(source,))

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
        variant, snapshot = self._active_variant, self.snapshot
        source_bake, source_generation = source.bake, source.mesh_generation
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
                if len(prepared) == 4 and isinstance(prepared[2], MeshGeometryAnalysis):
                    edited_scene, preview_model, analysis, texture_count = prepared
                else:
                    edited_scene, preview_model, bounds, centroid, texture_count = prepared
                    analysis = MeshGeometryAnalysis(bounds, centroid, mesh_principal_frame(edited_scene.mesh))
                baked = copy.copy(source)
                baked.bake = source_bake
                baked.scene, baked.preview_model = edited_scene, preview_model
                baked.preview_mesh = edited_scene.mesh
                baked._baked_scene_mesh = baked._baked_preview_mesh = None
                baked.baked_scene_mesh()
                baked.baked_preview_mesh()
                raise_if_cancelled(stop_event)
                return after.revision, (edited_scene, preview_model, analysis, texture_count), baked

        def done(result: object) -> None:
            if (source is not self.model_import or variant != self._active_variant or snapshot is not self.snapshot
                    or source.bake != source_bake or source.mesh_generation != source_generation):
                return
            try:
                revision, prepared, baked = result  # type: ignore[misc]
                current = mesh_controller.session_view()
                if current.session_id != session_id or current.revision != int(revision):
                    raise RuntimeError("The Mesh Editor revision could not be captured safely.")
                edited_scene, preview_model, analysis, texture_count = prepared
            except (AttributeError, KeyError, RuntimeError, TypeError, ValueError) as exc:
                failed(str(exc))
                return
            source.scene = edited_scene
            source.preview_model = preview_model
            source.preview_mesh = edited_scene.mesh
            source.bounds = analysis.bounds
            source.centroid = analysis.centroid
            source.principal_frame = analysis.principal_frame
            source.texture_count = int(texture_count)
            source.mesh_generation += 1
            source._baked_scene_mesh = baked._baked_scene_mesh
            source._baked_preview_mesh = baked._baked_preview_mesh
            source.applied = None
            from cdmw.services.new_item_materials import appearance_preview_part_names
            remaining_parts = {name.casefold() for part in edited_scene.mesh.submeshes
                               for name in appearance_preview_part_names(part)}
            self.draft.surface_settings = tuple((name, choice) for name, choice in self.draft.surface_settings
                                                if name.casefold() in remaining_parts)
            # A part the edit removed cannot keep its settings: planning refuses a
            # glow, glass or shader choice that names no material.
            self.draft.shader_controls = tuple((name, controls) for name, controls in self.draft.shader_controls
                                               if name.casefold() in remaining_parts)
            self.draft.glow_parts = tuple(name for name in self.draft.glow_parts if name.casefold() in remaining_parts)
            self.draft.translucency = _translucency_for_parts(self.draft.translucency, remaining_parts)
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

        return self._run("model_part_edit", task, done, failed, source_owners=(source,))

    def discard_model(self) -> None:
        """Drop the imported model, its placement and any result: back to the template's model."""
        if self._lane in {"model_import", "model_apply", "model_part_edit", "model_editor", "model_skinning", "model_hide"}:
            self.cancel_operation(self._lane)
        previous = self.model_import
        self.model_import = None
        self.model_placement = ModelPlacement()
        self.draft.template_transform = ()
        self.draft.glow_parts = ()
        self.draft.translucency = None
        self.draft.shader_controls = ()
        self.draft.surface_settings = ()
        if self.model_result is not None:
            self.set_imported_model(None, None)
        else:
            self.draft.model_source = ModelSource.TEMPLATE
            self.invalidate_plan()
        self.model_import_changed.emit(None)
        self._cleanup_model_source(previous)
