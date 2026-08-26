"""Template, material, character, and preview facts for New Item Studio."""
from __future__ import annotations

import copy
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

class NewItemPreviewControllerMixin:
    def item_mesh_as_planned(self):
        """The mesh a visual effect will actually sit on, and a word for what it is:
        the applied import, else the imported model at the placement set so far, else
        the template's own. The effect dialog asks for this rather than
        :meth:`item_mesh_for_preview`, whose imported model only appears once Apply
        the placement has run, so an effect was judged against the template instead.
        Returns `(mesh, kind)` where kind is "placed", "applied" or "template"; the mesh
        is None when there is nothing to parse."""

        wearable = self._template_is_wearable()

        def finish(mesh, kind: str, origin=None):
            preview = glow_preview_mesh(mesh, glow_choice(self.draft))
            if wearable:
                point = None
                try:
                    values = tuple(float(value) for value in origin) if origin is not None else ()
                except (TypeError, ValueError):
                    values = ()
                if len(values) == 3:
                    point = values
                elif (
                    getattr(preview, "bbox_min", None) is not None
                    and getattr(preview, "bbox_max", None) is not None
                ):
                    point = tuple(
                        (float(preview.bbox_min[axis]) + float(preview.bbox_max[axis])) * 0.5
                        for axis in range(3)
                    )
                if point is not None:
                    # The prefab transform is expressed in the item's archive axes. Effects
                    # uses this placed source origin as the neutral helmet/armour anchor.
                    setattr(preview, "_cdmw_effect_item_origin", point)
            return preview, kind

        source = self.model_import
        if source is not None:
            # the textured preview decode, not the bare scene mesh: a `.pac`'s geometry
            # names no textures, and this is the same mesh the Model step draws. The
            # rebuilt result deliberately borrows the template's material wrappers; it
            # is output authority, but using it here replaces the import's PBR authority
            # with a synthesized template surface after Apply.
            mesh = None
            source_origin = None
            origin_reader = getattr(source, "baked_origin", None)
            if callable(origin_reader):
                try:
                    values = tuple(float(value) for value in origin_reader())
                except (TypeError, ValueError):
                    values = ()
                if len(values) == 3:
                    source_origin = values
            for candidate in (source.baked_preview_mesh, source.baked_scene_mesh):
                try:
                    baked = bake_mesh(
                        candidate(),
                        self.model_placement,
                        origin=source_origin,
                    )
                except Exception:  # noqa: BLE001 - fall back to whatever else there is
                    continue
                if baked is not None:
                    mesh = baked
                    break
            if mesh is not None:
                placed_origin = (
                    tuple(source_origin[axis] + self.model_placement.offset[axis] for axis in range(3))
                    if source_origin is not None
                    else None
                )
                return finish(
                    mesh,
                    "applied" if self.model_result is not None else "placed",
                    placed_origin,
                )
        # A restored applied result may have no live import source. Its preview decode is
        # still preferable to the bare `.pac` geometry that names no textures.
        textured = self._textured_preview_mesh()
        if textured is not None:
            return finish(textured, "applied")
        mesh = self.item_mesh_for_preview()
        if mesh is None:
            return None, ""
        return finish(mesh, "applied" if self.model_result is not None else "template")

    def _textured_preview_mesh(self):
        """The applied import as a mesh that names its textures, or None.

        In memory already -- the Builder decoded it for the Model step -- so this is a
        conversion, not a read. The template's own textures are not here: those need an
        archive decode, which does not belong on the thread that opens a dialog.
        """

        model = getattr(self.model_result, "preview_model", None)
        if model is None or not getattr(model, "meshes", None):
            return None
        from cdmw.services.mesh_dotnet_preview_package import parsed_mesh_from_model_preview

        try:
            mesh = parsed_mesh_from_model_preview(model)
        except Exception:  # noqa: BLE001 - the bare geometry still places an effect
            return None
        from cdmw.services.effect_placement_preview import mesh_names_textures

        return mesh if mesh_names_textures(mesh) else None

    def item_mesh_for_preview(self):
        """The item's mesh as it will be: the imported model, else the template's own.
        None when there is nothing to parse (no snapshot, no template, no mesh)."""

        from cdmw.services.mesh_workflow_service import parse_pac

        data = bytes(getattr(self.model_result, "rebuilt_data", b"") or b"")
        label = "imported model"
        if not data and self.snapshot is not None and self.draft.template_key is not None:
            try:
                family = self.snapshot.family(self.draft.template_key)
            except Exception:  # noqa: BLE001 - no mesh is a plain "None"
                return None
            primary = next((item for item in family.files_for("pac") if item.exists and item.path.lower().rsplit("/", 1)[-1] == f"{family.model_stem.lower()}.pac"), None)
            primary = primary or next((item for item in family.files_for("pac") if item.exists), None)
            if primary is None:
                return None
            data = self.snapshot.payload(primary.path)
            label = primary.path
        if not data:
            return None
        try:
            return parse_pac(data, label)
        except Exception:  # noqa: BLE001
            return None

    def item_preview_source(self, *, include_character: bool = False):
        """What the Model and icon step's viewport shows, textured the way the Model
        Library and the Builder show it: a `(token, build)` pair, or None when there
        is nothing to show. The builders run off the UI thread and return preview data,
        a placement scene, or a ready native package path when the frame supplies its
        Preview Core context. `token` names the source, so a view already showing it is
        left alone. ``include_character`` adds the selected template's non-editable body
        in the template's own item frame; it never changes the model or build output."""

        include_character = bool(include_character)
        character_lock = threading.Lock()
        character_cache: list = []

        def character_mesh(stop_event):
            if not include_character:
                return None
            with character_lock:
                if character_cache:
                    return character_cache[0]
                held = self.character_holding_the_item(stop_event=stop_event)
                mesh = getattr(held, "mesh", None)
                rotation = tuple(getattr(held, "item_rotation", ()) or ())
                if mesh is not None and len(rotation) == 9:
                    # Effects keeps the person upright and turns the item into the hand.
                    # Model & Placement must keep its established item-space axes so the
                    # placement numbers and gizmo remain build-authoritative; transpose the
                    # rigid turn onto the body instead. Their relative fit is identical.
                    inverse = (
                        rotation[0], rotation[3], rotation[6],
                        rotation[1], rotation[4], rotation[7],
                        rotation[2], rotation[5], rotation[8],
                    )
                    from cdmw.services.effect_character_reference import rotate_mesh

                    mesh = rotate_mesh(mesh, inverse)
                character_cache.append(mesh)
                return mesh

        source = self.model_import
        if source is not None:
            template = self._template_preview_build()
            template_geometry = self._template_geometry_build()
            if template is None or template_geometry is None:
                return None
            template_token, template_build = template
            _geometry_token, geometry_build = template_geometry
            placement = self.model_placement

            def build_geometry_scene(stop_event):
                from cdmw.ui.new_item.item_preview import PlacementScene

                return PlacementScene(
                    template=geometry_build(stop_event),
                    model=source.baked_scene_mesh(),
                    placement=placement,
                    model_bounds=source.baked_bounds(),
                    model_origin=source.baked_origin(),
                    character=character_mesh(stop_event),
                )

            def build_material_scene(stop_event, **_preview_context):
                from cdmw.ui.new_item.item_preview import PlacementScene

                model = source.baked_preview_mesh()
                return PlacementScene(
                    template=template_build(stop_event),
                    model=model,
                    placement=placement,
                    model_bounds=source.baked_bounds(),
                    model_origin=source.baked_origin(),
                    character=character_mesh(stop_event),
                )

            from cdmw.ui.new_item.item_preview import ProgressivePreviewSource

            build = ProgressivePreviewSource(build_geometry_scene, build_material_scene, source.acquire_usage)
            return ((
                "placement",
                id(source),
                source.bake_generation,
                source.mesh_generation,
                template_token,
                include_character,
            ), build)
        result = self.model_result
        model = getattr(result, "preview_model", None)
        if result is not None and model is not None and getattr(model, "meshes", None):
            if include_character:
                from cdmw.ui.new_item.item_preview import PlacementScene

                return (
                    ("imported-character", id(result), self.draft.template_key),
                    lambda stop_event: PlacementScene(
                        template=None,
                        model=model,
                        character=character_mesh(stop_event),
                    ),
                )
            return (("imported", id(result)), lambda _stop_event: model)
        if result is not None:
            mesh = self.item_mesh_for_preview()
            if mesh is not None and include_character:
                from cdmw.ui.new_item.item_preview import PlacementScene

                return (
                    ("imported-bare-character", id(result), self.draft.template_key),
                    lambda stop_event: PlacementScene(
                        template=None,
                        model=mesh,
                        character=character_mesh(stop_event),
                    ),
                )
            return (("imported-bare", id(result)), lambda _stop_event: mesh) if mesh is not None else None
        template = self._template_preview_build()
        if template is None:
            return None
        geometry = self._template_geometry_build()
        if geometry is None:
            return template
        token, material_build = template
        _geometry_token, geometry_build = geometry
        from cdmw.ui.new_item.item_preview import PlacementScene, ProgressivePreviewSource

        if include_character:
            def build_geometry_character_scene(stop_event):
                return PlacementScene(
                    template=None,
                    model=geometry_build(stop_event),
                    character=character_mesh(stop_event),
                )

            def build_material_character_scene(stop_event, **_preview_context):
                return PlacementScene(
                    template=None,
                    model=material_build(stop_event),
                    character=character_mesh(stop_event),
                )

            return (
                ("template-character", self.draft.template_key, token),
                ProgressivePreviewSource(
                    build_geometry_character_scene,
                    build_material_character_scene,
                ),
            )

        return (token, ProgressivePreviewSource(geometry_build, material_build))

    def _template_geometry_build(self):
        """A fast bare template mesh builder for the first progressive viewport stage."""

        snapshot = self.snapshot
        if snapshot is None or self.draft.template_key is None:
            return None
        entries = self.template_entries()
        if not entries:
            return None
        try:
            family = snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001
            return None
        stem = family.model_stem.lower()
        entry = next((item for item in entries if item.path.lower().rsplit("/", 1)[-1] == f"{stem}.pac"), entries[0])

        def build(stop_event):
            from cdmw.domain.cancellation import RunCancelled
            from cdmw.services.mesh_workflow_service import parse_pac

            if stop_event.is_set():
                raise RunCancelled("Template preview cancelled")
            return parse_pac(snapshot.payload(entry.path), entry.path)

        entry_revision = (
            entry.path,
            str(getattr(entry, "pamt_path", "") or ""),
            str(getattr(entry, "paz_file", "") or ""),
            int(getattr(entry, "offset", 0) or 0),
            int(getattr(entry, "comp_size", 0) or 0),
        )
        return (("template-geometry", self.draft.template_key, *entry_revision), build)

    def _template_preview_build(self):
        """`(token, build)` for the template's textured package or Python fallback."""

        snapshot = self.snapshot
        if snapshot is None or self.draft.template_key is None:
            return None
        entries = self.template_entries()
        if not entries:
            return None
        try:
            family = snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001
            return None
        stem = family.model_stem.lower()
        entry = next((item for item in entries if item.path.lower().rsplit("/", 1)[-1] == f"{stem}.pac"), entries[0])
        controller = self
        cache_key = (id(snapshot), entry.path)
        cache = self._template_models

        def build(
            stop_event,
            *,
            output_root=None,
            native_preview_core_cache_root=None,
            render_settings=None,
            cache_mode="off",
        ):
            if output_root is not None and native_preview_core_cache_root is not None:
                import shutil
                import time

                from cdmw.models import clamp_model_preview_render_settings
                from cdmw.services.mesh_dotnet_preview_package import (
                    build_or_lookup_dotnet_preview_package,
                )
                from cdmw.services.preview_rendering_service import (
                    dotnet_preview_package_cache_budget,
                    run_native_preview_core_preview_job,
                )
                from cdmw.workers.archive_preview_native import (
                    native_preview_core_timeout_seconds,
                )

                preview_root = Path(output_root)
                preview_root.mkdir(parents=True, exist_ok=True)
                native_package = preview_root / f"package_{time.time_ns()}_native"
                native_render_settings = replace(
                    clamp_model_preview_render_settings(render_settings),
                    use_textures_by_default=True,
                )
                try:
                    native_attempt = run_native_preview_core_preview_job(
                        entry,
                        cache_root=Path(native_preview_core_cache_root),
                        render_settings=native_render_settings,
                        dependency_entries=tuple(entries),
                        dependency_entries_complete=False,
                        package_root=Path(entry.pamt_path).parent.parent,
                        output_root=native_package,
                        timeout_seconds=native_preview_core_timeout_seconds(native_render_settings),
                        stop_event=stop_event,
                    )
                    if native_attempt.succeeded:
                        cache_max_bytes, cache_target_bytes = dotnet_preview_package_cache_budget(cache_mode)
                        package = build_or_lookup_dotnet_preview_package(
                            native_attempt.package_path,
                            cache_root=preview_root,
                            archive_identity=(
                                f"new_item_native:{entry.path}:{entry.pamt_path}:"
                                f"{entry.paz_file}:{entry.offset}:{entry.comp_size}"
                            ),
                            cache_mode=cache_mode,
                            max_bytes=cache_max_bytes,
                            target_bytes=cache_target_bytes,
                            cancelled=stop_event.is_set,
                            metadata={"surface": "new_item_studio", "source_path": entry.path},
                        )
                        return Path(package.package_dir)
                except RunCancelled:
                    shutil.rmtree(native_package, ignore_errors=True)
                    raise
                except Exception:  # noqa: BLE001 - the established Python preview remains the fallback
                    pass
                shutil.rmtree(native_package, ignore_errors=True)

            from cdmw.services.archive_preview_service import build_archive_preview_result

            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            by_path, by_basename = snapshot.archive_index_maps()
            try:
                decoded = build_archive_preview_result(
                    entry,
                    texture_entries_by_normalized_path=by_path,
                    texture_entries_by_basename=by_basename,
                    enable_hkx_visual_preview=False,
                    stop_event=stop_event,
                )
            except Exception:  # noqa: BLE001 - the bare mesh still shows
                decoded = None
            model = getattr(decoded, "preview_model", None) if decoded is not None else None
            if model is not None and getattr(decoded, "preferred_view", "") == "model" and getattr(model, "meshes", None):
                cache.clear()
                cache[cache_key] = model
                return model
            return controller.item_mesh_for_preview()

        entry_revision = (
            entry.path,
            str(getattr(entry, "pamt_path", "") or ""),
            str(getattr(entry, "paz_file", "") or ""),
            int(getattr(entry, "offset", 0) or 0),
            int(getattr(entry, "comp_size", 0) or 0),
        )
        return (("template", self.draft.template_key, *entry_revision), build)

    def character_reference(self, model_folder: str = "", *, rig_model: str = "", stop_event=None):
        """The matching rig's own character for the placement viewport, or None.

        Read once per player rig and kept: a rig, a socket file and a body out of the
        archives is about a second, and the dialog is opened again for every effect the
        reader tries. ``rig_model`` overrides the template only for preview. Call it off
        the UI thread; the placement dialog does.
        """

        raise_if_cancelled(stop_event, "Operation cancelled.")
        if self.snapshot is None:
            return None
        from cdmw.services.effect_character_reference import (
            character_reference_from_snapshot,
            character_rig_model,
        )

        requested_rig = str(rig_model or "").replace("\\", "/").strip("/").lower()
        requested_rig = requested_rig.rsplit("/", 1)[-1] if requested_rig else ""
        selected_rig = requested_rig or character_rig_model(model_folder)
        if selected_rig in self._character_references:
            return self._character_references[selected_rig]
        if requested_rig:
            reference, said = character_reference_from_snapshot(
                self.snapshot,
                model_folder=model_folder,
                rig_model=selected_rig,
                stop_event=stop_event,
            )
        else:
            # Preserve the established auto/template seam for existing synchronous callers.
            reference, said = character_reference_from_snapshot(
                self.snapshot,
                model_folder=model_folder,
                stop_event=stop_event,
            )
        self._character_references[selected_rig] = reference
        if said:
            self.log_message.emit(said)
        return reference

    def character_holding_the_item(self, *, rig_model: str = "", stop_event=None):
        """The character wearing or holding the current template's item, or None.

        Wearables stay in the matching rig's bind frame. For weapons, the frame the item
        mates by comes from the template's own prefab and is read per template, because
        weapons share socket files and only the prefab says which one an item uses.
        ``rig_model`` selects a preview-only body without changing the item or template.
        Call it off the UI thread.
        """

        raise_if_cancelled(stop_event, "Operation cancelled.")
        snapshot, template = self.snapshot, self.draft.template_key
        if snapshot is None:
            return None
        requested_rig = str(rig_model or "").replace("\\", "/").strip("/").lower()
        requested_rig = requested_rig.rsplit("/", 1)[-1] if requested_rig else ""
        if self._held_character and self._held_character[:2] == (template, requested_rig):
            return self._held_character[2]
        from cdmw.services.effect_character_reference import held_character_from_snapshot

        prefabs: tuple = ()
        folder = ""
        if template is not None:
            try:
                family = snapshot.family(int(template))
                prefabs = tuple(part.prefab_path for part in family.parts if part.prefab_path)
                folder = str(family.model_folder or "")
            except Exception as exc:  # noqa: BLE001 - the convention frame stands in
                self.log_message.emit(f"The template's prefabs could not be read for the placement viewport: {exc}")
        reference = self.character_reference(
            folder,
            rig_model=requested_rig,
            stop_event=stop_event,
        )
        held, said = held_character_from_snapshot(
            snapshot,
            reference,
            prefab_paths=prefabs,
            model_folder=folder,
            template_key=template,
            stop_event=stop_event,
        )
        if said:
            self.log_message.emit(said)
        self._held_character = (template, requested_rig, held)
        return held

    def material_parts(self) -> Tuple[Tuple[str, str], ...]:
        """The imported model's own materials, for choosing which of them glow.

        The reader's materials, never the template's: `Inside` and `Outside` are words
        they can act on and `cd_phm_02_hammer_sub_0002` is not, and the template's parts
        are not theirs to light in any case. They are in the scene the importer read, so
        they are here from the moment the file is chosen rather than after Apply.

        Empty without an imported model: the route that writes a glow runs only for one.
        """

        source = self.model_import
        if source is None:
            return ()
        stamp = (id(source),)
        if self._material_parts and self._material_parts[0] == stamp:
            return self._material_parts[1]
        names: list = []
        try:
            for binding in tuple(getattr(getattr(source, "scene", None), "material_bindings", ()) or ()):
                name = str(getattr(binding, "material_name", "") or "").strip()
                if name and name not in names:
                    names.append(name)
            scene_mesh = getattr(getattr(source, "scene", None), "mesh", None)
            for submesh in tuple(getattr(scene_mesh, "submeshes", ()) or ()):
                if not hasattr(submesh, "cdmw_mesh_edit_topology_source_submesh_index"):
                    continue
                name = str(getattr(submesh, "name", "") or "").strip()
                if name and name not in names:
                    names.append(name)
        except Exception as exc:  # noqa: BLE001 - no list is a smaller loss than no step
            self.log_message.emit(f"The model's materials could not be read: {exc}")
            names = []
        parts = tuple((name, name) for name in names)
        self._material_parts = (stamp, parts)
        return parts

    def import_dependency_context(self):
        """A dependency context for importing a model over the template's mesh: the
        template's family files, everything under the family's model folder, and every
        entry whose basename starts with the family's model stem as the bounded member
        list, with the whole listing behind the path and basename maps (the texture
        resolver walks those, and a weapon's textures sit under `character/texture/`).
        Built from the studio's own listing, so the Archive Browser's selection plays
        no part."""

        from cdmw.ui.archive_browser.workflow_dependencies import ArchiveWorkflowDependencyContext

        if self.snapshot is None or self.draft.template_key is None:
            return None
        try:
            family = self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001
            return None
        folder = str(family.model_folder or "").replace("\\", "/").strip("/").lower()
        stem = str(family.model_stem or "").lower()
        chosen: Dict[str, ArchiveEntry] = {}
        for item in family.files:
            if item.exists:
                key = str(item.path).replace("\\", "/").strip("/").lower()
                entry = self.snapshot.entries.get(key)
                if entry is not None:
                    chosen[key] = entry
        for key, entry in self.snapshot.entries.items():
            basename = key.rsplit("/", 1)[-1]
            if (folder and key.startswith(f"character/model/{folder}/")) or (stem and basename.startswith(stem)):
                chosen[key] = entry
        if not chosen:
            return None
        by_path, by_basename = self.snapshot.archive_index_maps()
        primary = self.template_entries()
        selected = primary[0] if primary else next(iter(chosen.values()))
        return ArchiveWorkflowDependencyContext(
            selected_entry=selected,
            entries=tuple(chosen.values()),
            entries_by_normalized_path=by_path,
            entries_by_basename=by_basename,
            remote=False,
        )

    def template_entries(self) -> Tuple[ArchiveEntry, ...]:
        """The template's own model files, for the Builder to import over."""

        if self.snapshot is None or self.draft.template_key is None:
            return ()
        try:
            family = self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001
            return ()
        return tuple(self.snapshot.entry(item.path) for item in family.files_for("pac") if item.exists)
