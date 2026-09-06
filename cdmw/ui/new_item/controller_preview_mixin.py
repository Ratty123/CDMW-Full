"""Template, material, character, and preview facts for New Item Studio."""
from __future__ import annotations

import copy
import threading
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
from cdmw.services.new_item_planning import NewItemPlan, NewItemPlanError
from cdmw.services.new_item_service import NewItemInstallRefused, NewItemService
from cdmw.services.new_item_snapshot import NewItemSnapshot, NewItemSnapshotError
from cdmw.ui.new_item.effect_workspace_controller import NewItemEffectWorkspaceControllerMixin
from cdmw.ui.new_item.state import NewItemDraft, StatGrid, glow_choice, spec_from_draft, stat_grid_for, status_label, with_template
from cdmw.workers.effect_catalogue_worker import EffectCatalogueIndexLane
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane
from cdmw.workers.new_item_workers import export_task, install_overlay_task, install_task, overlay_migration_task, overlay_removal_task, plan_task, snapshot_task
from cdmw.workers.utility_workers import UtilityWorker


def _progressive_preview_source(geometry, materials, acquire_usage=None, cached_materials=None):
    from cdmw.ui.new_item.item_preview import ProgressivePreviewSource

    return ProgressivePreviewSource(
        geometry,
        materials,
        acquire_usage,
        supports_fast_material_package=True,
        cached_materials=cached_materials,
    )


def _placement_progressive_source(
    source,
    template_build,
    geometry_build,
    placement,
    character_mesh,
    token,
):
    from cdmw.ui.new_item.item_preview import PlacementScene

    def build_geometry_scene(stop_event):
        return PlacementScene(
            template=geometry_build(stop_event),
            model=source.baked_scene_mesh(),
            placement=placement,
            model_bounds=source.baked_bounds(),
            model_origin=source.baked_origin(),
            character=character_mesh(stop_event),
        )

    def build_material_scene(stop_event, **preview_context):
        from cdmw.ui.new_item.item_preview_materials import compose_template_materials

        return compose_template_materials(
            template_build,
            lambda template: PlacementScene(
                template=template,
                model=source.baked_preview_mesh(),
                placement=placement,
                model_bounds=source.baked_bounds(),
                model_origin=source.baked_origin(),
                character=character_mesh(stop_event),
            ),
            stop_event, token, preview_context,
        )

    return _progressive_preview_source(
        build_geometry_scene,
        build_material_scene,
        source.acquire_usage,
    )


def _imported_model_progressive_source(model):
    from cdmw.ui.new_item.item_preview_materials import as_parsed_mesh

    def imported_geometry(stop_event):
        if stop_event.is_set():
            raise RunCancelled("Imported model preview cancelled")
        return as_parsed_mesh(model)

    def imported_materials(_stop_event, **_preview_context):
        return model

    return _progressive_preview_source(imported_geometry, imported_materials)


def _template_progressive_source(
    token,
    template_key,
    geometry_build,
    material_build,
    include_character,
    character_mesh,
):
    if not include_character:
        from functools import partial

        return token, _progressive_preview_source(
            geometry_build, material_build,
            cached_materials=partial(material_build, cache_only=True),
        )
    from cdmw.ui.new_item.item_preview import PlacementScene

    def build_geometry_character_scene(stop_event):
        return PlacementScene(
            template=None,
            model=geometry_build(stop_event),
            character=character_mesh(stop_event),
        )

    def build_material_character_scene(stop_event, **preview_context):
        from cdmw.ui.new_item.item_preview_materials import compose_template_materials

        return compose_template_materials(
            material_build,
            lambda template: PlacementScene(
                template=None,
                model=template,
                character=character_mesh(stop_event),
            ),
            stop_event, ("template-character", template_key, token), preview_context,
        )

    return (
        ("template-character", template_key, token),
        _progressive_preview_source(
            build_geometry_character_scene,
            build_material_character_scene,
        ),
    )


class NewItemPreviewControllerMixin:
    def item_mesh_as_planned(self):
        """Compatibility accessor for the current planned item's preview mesh."""

        return self.item_effect_preview_source()(threading.Event())

    def item_effect_preview_source(self):
        """Capture the selected item before its Effects worker starts decoding."""

        from cdmw.ui.new_item.effect_item_source import PlannedEffectItemSource

        return PlannedEffectItemSource(
            source=self.model_import,
            placement=self.model_placement,
            applied=self.model_result is not None,
            preview_model=getattr(self.model_result, "preview_model", None),
            rebuilt_data=bytes(getattr(self.model_result, "rebuilt_data", b"") or b""),
            snapshot=self.snapshot,
            template_key=self.draft.template_key,
            glow=glow_choice(self.draft),
        )

    def _textured_preview_mesh(self):
        """The applied import as a mesh that names its textures, or None.

        In memory already -- the Builder decoded it for the Model step -- so this is a
        conversion, not a read. The template's own textures are not here: those need an
        archive decode, which does not belong on the thread that opens a dialog.
        """

        model = getattr(self.model_result, "preview_model", None)
        if model is None or not getattr(model, "meshes", None):
            return None
        from cdmw.services.mesh_rust_preview_cache import parsed_mesh_from_model_preview

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
        if data:
            try:
                return parse_pac(data, "imported model")
            except Exception:  # noqa: BLE001
                return None
        if self.snapshot is None or self.draft.template_key is None:
            return None
        entries = self.template_entries()
        primary = self.template_primary_entry()
        if primary is None:
            return None
        ordered = (primary, *(entry for entry in entries if entry.path != primary.path))
        merged = None
        for entry in ordered:
            try:
                parsed = parse_pac(self.snapshot.payload(entry.path), entry.path)
            except Exception:  # noqa: BLE001 - one absent component must not hide the primary
                continue
            if merged is None:
                merged = parsed
                continue
            from cdmw.ui.new_item.item_preview_materials import placement_reference_mesh

            merged = placement_reference_mesh(merged, parsed)
        return merged

    def item_preview_source(self, *, include_character: bool = False):
        """What the Model and icon step's viewport shows, textured the way the Model
        Library and the Builder show it: a `(token, build)` pair, or None when there
        is nothing to show. The builders run off the UI thread and return preview data,
        a placement scene, or a ready native package path when the frame supplies its
        Preview Core context. `token` names the source, so a view already showing it is
        left alone. ``include_character`` adds the selected template's non-editable body
        in the template's own item frame; it never changes the model or build output."""

        include_character = bool(include_character)
        variant_binding = self._active_variant or ()
        character_lock = threading.Lock()
        character_cache: list = []

        def character_mesh(stop_event):
            if not include_character:
                return None
            with character_lock:
                if character_cache:
                    return character_cache[0]
                held = (self.character_holding_the_item(stop_event=stop_event, variant_binding=variant_binding)
                        if variant_binding else self.character_holding_the_item(stop_event=stop_event))
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
            token = (
                "placement", source.cache_identity, source.bake, source.mesh_generation,
                template_token, include_character,
            )
            build = _placement_progressive_source(
                source,
                template_build,
                geometry_build,
                placement,
                character_mesh,
                token,
            )
            return token, build
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
            return (
                ("imported", id(result)),
                _imported_model_progressive_source(model),
            )
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
        return _template_progressive_source(
            token,
            self.draft.template_key,
            geometry_build,
            material_build,
            include_character,
            character_mesh,
        )

    def _template_geometry_build(self):
        """A fast bare template mesh builder for the first progressive viewport stage."""

        snapshot = self.snapshot
        if snapshot is None or self.draft.template_key is None:
            return None
        entries = self.template_entries()
        if not entries:
            return None
        entry = self.template_primary_entry()
        if entry is None:
            return None
        template_key = int(self.draft.template_key)
        ordered_entries = (entry, *(item for item in entries if item.path != entry.path))

        def build(stop_event):
            from cdmw.domain.cancellation import RunCancelled
            from cdmw.services.mesh_workflow_service import parse_pac
            from cdmw.ui.new_item.item_preview_materials import placement_reference_mesh

            merged = None
            for component in ordered_entries:
                if stop_event.is_set():
                    raise RunCancelled("Template preview cancelled")
                parsed = parse_pac(snapshot.payload(component.path), component.path)
                merged = parsed if merged is None else placement_reference_mesh(merged, parsed)
            return merged

        entry_revisions = tuple(
            (
                component.path,
                str(getattr(component, "pamt_path", "") or ""),
                str(getattr(component, "paz_file", "") or ""),
                int(getattr(component, "offset", 0) or 0),
                int(getattr(component, "comp_size", 0) or 0),
            )
            for component in ordered_entries
        )
        return (("template-geometry", template_key, *entry_revisions[0], entry_revisions[1:]), build)

    def _template_preview_build(self):
        """`(token, build)` for the template's textured package or Python fallback."""
        snapshot = self.snapshot
        if snapshot is None or self.draft.template_key is None:
            return None
        entries = self.template_entries()
        if not entries:
            return None
        entry = self.template_primary_entry()
        if entry is None:
            return None
        template_key = int(self.draft.template_key)
        ordered_entries = (entry, *(item for item in entries if item.path != entry.path))
        prefab_entries = self.template_prefab_entries()
        dependencies_list = []
        dependency_identities = set()
        for dependency in (*ordered_entries, *prefab_entries):
            if dependency.identity in dependency_identities:
                continue
            dependency_identities.add(dependency.identity)
            dependencies_list.append(dependency)
        dependencies = tuple(dependencies_list)
        component_paths = tuple(item.path for item in ordered_entries[1:])
        controller = self
        entry_revisions = tuple(
            (
                component.path,
                str(getattr(component, "pamt_path", "") or ""),
                str(getattr(component, "paz_file", "") or ""),
                int(getattr(component, "offset", 0) or 0),
                int(getattr(component, "comp_size", 0) or 0),
            )
            for component in ordered_entries
        )
        dependency_revisions = tuple(
            (
                dependency.path,
                str(getattr(dependency, "pamt_path", "") or ""),
                str(getattr(dependency, "paz_file", "") or ""),
                int(getattr(dependency, "offset", 0) or 0),
                int(getattr(dependency, "comp_size", 0) or 0),
            )
            for dependency in dependencies
        )
        cache_key = (id(snapshot), template_key, dependency_revisions)
        cache = self._template_models
        def build(
            stop_event,
            *,
            output_root=None,
            native_preview_core_cache_root=None,
            render_settings=None,
            cache_mode="off",
            fast_package_ready=None,
            cache_only=False,
            consume_native_package=None,
        ):
            if output_root is not None and native_preview_core_cache_root is not None:
                from cdmw.ui.new_item.template_preview_cache import build_native_template_preview

                package = build_native_template_preview(
                    entry, dependencies, prefab_entries, component_paths,
                    template_key, snapshot, stop_event,
                    output_root=output_root,
                    native_preview_core_cache_root=native_preview_core_cache_root,
                    render_settings=render_settings,
                    cache_mode=cache_mode,
                    fast_package_ready=fast_package_ready,
                    cache_only=cache_only,
                    consume_native_package=consume_native_package,
                )
                if package is not None:
                    return package

            if cache_only:
                return None
            from cdmw.services.archive_preview_service import build_archive_preview_result

            cached = cache.get(cache_key)
            if cached is not None:
                return cached
            by_path, by_basename = snapshot.archive_index_maps()
            models = []
            for component in ordered_entries:
                try:
                    decoded = build_archive_preview_result(
                        component,
                        texture_entries_by_normalized_path=by_path,
                        texture_entries_by_basename=by_basename,
                        enable_hkx_visual_preview=False,
                        stop_event=stop_event,
                    )
                except Exception:  # noqa: BLE001 - the bare mesh still shows
                    decoded = None
                model = getattr(decoded, "preview_model", None) if decoded is not None else None
                if model is not None and getattr(decoded, "preferred_view", "") == "model" and getattr(model, "meshes", None):
                    models.append(model)
            if models:
                model = models[0]
                if len(models) > 1:
                    from cdmw.ui.new_item.item_preview_materials import as_parsed_mesh, placement_reference_mesh

                    merged = as_parsed_mesh(model)
                    for component_model in models[1:]:
                        merged = placement_reference_mesh(merged, as_parsed_mesh(component_model))
                    model = merged
                cache.clear()
                cache[cache_key] = model
                return model
            return controller.item_mesh_for_preview()

        return (("template", template_key, *entry_revisions[0], dependency_revisions[1:]), build)

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

    def character_holding_the_item(self, *, rig_model: str = "", stop_event=None, variant_binding=None):
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
        selected = self._active_variant if variant_binding is None else variant_binding
        context = (requested_rig,selected) if selected else requested_rig
        if self._held_character and self._held_character[:2] == (template, context):
            return self._held_character[2]
        from cdmw.services.effect_character_reference import held_character_from_snapshot

        prefabs: tuple = ()
        folder = ""
        if template is not None:
            try:
                family = snapshot.family(int(template))
                prefabs = tuple(part.prefab_path for part in family.parts if part.prefab_path)
                folder = str(family.model_folder or "")
                if selected:
                    prefabs = (selected[0],)
                    folder = selected[1].removeprefix("character/model/").rsplit("/",1)[0]
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
        self._held_character = (template, context, held)
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

    def template_entries_for(self, template_key: int) -> Tuple[ArchiveEntry, ...]:
        """Every existing model file owned by one shipped template."""

        if self.snapshot is None:
            return ()
        try:
            family = self.snapshot.family(int(template_key))
        except Exception:  # noqa: BLE001
            return ()
        return tuple(self.snapshot.entry(item.path) for item in family.files_for("pac") if item.exists)

    def template_entries(self) -> Tuple[ArchiveEntry, ...]:
        """The selected template's complete model set, for preview and authoring."""

        if self.draft.template_key is None:
            return ()
        if self._active_variant is not None and self.snapshot is not None:
            family = self.snapshot.family(self.draft.template_key)
            prefab,path = self._active_variant
            part = next((value for value in family.parts if value.prefab_path.casefold()==prefab),None)
            if part is None:
                return ()
            paths = (path,*(value for value in part.pac_paths if value.casefold()!=path))
            return tuple(self.snapshot.entry(value) for value in paths if self.snapshot.has_entry(value))
        return self.template_entries_for(self.draft.template_key)

    def template_primary_entry(self, template_key: Optional[int] = None) -> Optional[ArchiveEntry]:
        """The model file whose stem owns the template family, preserving the old primary."""

        key = self.draft.template_key if template_key is None else int(template_key)
        if self.snapshot is None or key is None:
            return None
        entries = self.template_entries() if key == self.draft.template_key else self.template_entries_for(key)
        if not entries:
            return None
        if self._active_variant is not None and key == self.draft.template_key:
            return self.snapshot.entry(self._active_variant[1])
        try:
            stem = self.snapshot.family(key).model_stem.casefold()
        except Exception:  # noqa: BLE001
            return entries[0]
        return next(
            (entry for entry in entries if entry.basename.casefold() == f"{stem}.pac"),
            entries[0],
        )

    def template_prefab_entries(self, template_key: Optional[int] = None) -> Tuple[ArchiveEntry, ...]:
        """Existing prefabs that establish the selected template's model dependencies."""

        key = self.draft.template_key if template_key is None else int(template_key)
        if self.snapshot is None or key is None:
            return ()
        if self._active_variant is not None and key == self.draft.template_key:
            return (self.snapshot.entry(self._active_variant[0]),)
        try:
            family = self.snapshot.family(key)
        except Exception:  # noqa: BLE001
            return ()
        return tuple(
            sorted(
                (
                    self.snapshot.entry(item.path)
                    for item in family.files_for("prefab")
                    if item.exists
                ),
                key=lambda entry: (
                    Path(entry.basename).stem.casefold()
                    != str(family.model_stem or "").casefold()
                ),
            )
        )
