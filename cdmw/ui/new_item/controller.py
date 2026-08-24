"""The New Item Studio's controller: holds the draft, talks to the service, owns the worker.

The panels never touch the service or the archives. They edit the draft and ask the
controller for facts about the template; the controller runs the snapshot, the plan,
the export and the install through :mod:`cdmw.workers.new_item_workers` on one owned
thread at a time, and reports back through signals. Nothing here writes to the game
except `start_install`, which goes through `ArchiveMutationService`.
"""

from __future__ import annotations

import copy
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable, Dict, Iterable, List, Optional, Tuple

from PySide6.QtCore import QObject, QThread, Qt, QTimer, Signal

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
from cdmw.workers.new_item_workers import export_task, install_overlay_task, install_task, overlay_migration_task, overlay_removal_task, plan_task, snapshot_task
from cdmw.workers.utility_workers import UtilityWorker

#: "not read yet", which None cannot say: an install with no character must not be
#: re-read on every dialog.
_NOT_READ = object()


class NewItemStudioController(NewItemEffectWorkspaceControllerMixin, QObject):
    busy_changed = Signal(bool)
    operation_progress = Signal(str, int, int, str)
    log_message = Signal(str)
    status_message = Signal(str, bool)
    snapshot_ready = Signal()
    snapshot_failed = Signal(str)
    template_changed = Signal(object)
    plan_ready = Signal(object)
    plan_failed = Signal(str, object)
    plan_invalidated = Signal()
    export_finished = Signal(object)
    install_finished = Signal(object)
    model_changed = Signal(object)
    #: a model file was read for the studio (a ModelImportSource), or discarded (None)
    model_import_changed = Signal(object)
    #: a model file was not read, with the reason: the step says so where the reader is,
    #: since the window's status line is not where they are looking
    model_import_failed = Signal(str)
    #: an imported model accepted one stable Mesh Editor revision
    model_part_edit_finished = Signal(object)
    #: the Mesh Editor revision could not be captured or prepared
    model_part_edit_failed = Signal(str)
    #: the imported model's placement over the template moved (a ModelPlacement)
    model_placement_changed = Signal(object)
    effect_catalogue_ready = Signal()
    effect_catalogue_progress = Signal(int, int, str)
    effect_catalogue_failed = Signal(str)
    effect_changed = Signal(object)

    def __init__(
        self,
        *,
        service: Optional[NewItemService] = None,
        read_entry: Optional[Callable[[ArchiveEntry], bytes]] = None,
        synchronous: bool = False,
        parent: Optional[QObject] = None,
    ) -> None:
        super().__init__(parent)
        self.service = service or NewItemService()
        self._read_entry = read_entry
        self._synchronous = bool(synchronous)
        self.snapshot: Optional[NewItemSnapshot] = None
        #: A mod folder to plan on top of, so a second item joins the first one's tables
        #: instead of replacing them. None plans against the archives.
        self.mod_base_folder: Optional[Path] = None
        #: The game's own character for the placement viewport, read once (None means the
        #: archives had no character; _NOT_READ means nobody has asked yet)
        self._character_reference: object = _NOT_READ
        #: (template key, the character holding that template's item), so opening the
        #: placement dialog again does not re-read the prefab
        self._held_character: tuple = ()
        #: (template key, its material part names), read once per template
        self._material_parts: tuple = ()
        self.draft = NewItemDraft()
        self.plan: Optional[NewItemPlan] = None
        self._draft_revision = 0
        self._plan_revision = -1
        self.model_result: object | None = None
        self.model_entry: Optional[ArchiveEntry] = None
        self.model_scene: object | None = None
        #: the model file read for the studio's own placement, and where it sits
        self.model_import: Optional[ModelImportSource] = None
        self.model_placement: ModelPlacement = ModelPlacement()
        #: the template's decoded preview (textures resolved), kept for the current template so
        #: a re-fit or an import does not decode it again (the worker fills it)
        self._template_models: Dict[tuple, object] = {}
        self._thread: Optional[QThread] = None
        self._worker: Optional[UtilityWorker] = None
        self._on_done: Optional[Callable[[object], None]] = None
        self._on_error: Optional[Callable[[str], None]] = None
        self._lane: str = ""
        self._cancel_requested_lane: str = ""
        self._shutdown_requested = False
        self._model_sources_to_cleanup: list[object] = []
        #: What every shipped effect is made of, once indexed (a minute, cached on disk).
        self.effect_catalogue: Optional[EffectCatalogue] = None
        #: Where the catalogue cache lives; None keeps it in memory only.
        self.effect_cache_path: Optional[Path] = None
        self._effect_lane = EffectCatalogueIndexLane(synchronous=self._synchronous, parent=self)
        self._effect_lane.log_message.connect(self.log_message.emit)
        self._effect_lane.progress.connect(self.effect_catalogue_progress.emit)
        self._effect_lane.failed.connect(self.effect_catalogue_failed.emit)
        self._effect_lane.completed.connect(self._publish_effect_catalogue)
        #: Identities this studio has already handed out but the snapshot may not see: a
        #: plan built earlier, or an item written as a loose mod rather than installed.
        #: Without them a second item would take the first one's key and stem, and
        #: installing it would overwrite the first. Kept across sessions in the settings.
        self.issued_keys: set = set()
        self.issued_stems: set = set()
        #: whether those identities are kept across sessions; the app turns it on, so a
        #: test never reads or writes the user's settings
        self._persist_identities = False

    # ------------------------------------------------------------------ facts

    @property
    def busy(self) -> bool:
        return self._thread is not None

    @property
    def ready(self) -> bool:
        return self.snapshot is not None

    @property
    def has_current_plan(self) -> bool:
        return self.plan is not None and self._plan_revision == self._draft_revision

    def invalidate_plan(self) -> None:
        """Advance draft authority and make every older or in-flight plan unusable."""

        self._draft_revision += 1
        self._plan_revision = -1
        self.plan = None
        self.plan_invalidated.emit()

    def _cleanup_model_source(self, source: Optional[ModelImportSource]) -> None:
        cleanup = getattr(source, "cleanup", None)
        if not callable(cleanup):
            return
        if self._thread is not None:
            if not any(item is source for item in self._model_sources_to_cleanup):
                self._model_sources_to_cleanup.append(source)
            return
        cleanup()

    def template_options(self, text: str = "", *, limit: int = 60) -> List[Tuple[int, str, str]]:
        """(key, internal name, equip type) for equipment whose name or key matches `text`."""

        if self.snapshot is None:
            return []
        needle = str(text or "").strip().casefold()
        out: List[Tuple[int, str, str]] = []
        for key, row in self.snapshot.rows.items():
            equip = self.snapshot.equip_type_name(row)
            if not equip:
                continue
            if needle and needle not in row.string_key.casefold() and needle != str(key):
                continue
            out.append((key, row.string_key, equip))
            if len(out) >= limit:
                break
        out.sort(key=lambda item: item[1].casefold())
        return out

    def template_name(self) -> str:
        """The template's internal name, or "" before one is chosen."""

        if self.snapshot is None or self.draft.template_key is None:
            return ""
        row = self.snapshot.rows.get(int(self.draft.template_key))
        return row.string_key if row is not None else ""

    def template_has_sheathed_variant(self) -> bool:
        """Whether the chosen template exposes an alternate ``_IN`` visual part.

        The Model option that clones an imported model into that part is useful
        only for templates that actually have one. Armour, accessories and equipment
        without a sheathed/holstered state should not be shown a no-op weapon control.
        """

        if self.snapshot is None or self.draft.template_key is None:
            return False
        try:
            family = self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001 - an unresolved family has no usable variant
            return False
        from cdmw.services.new_item_effect_targets import is_sheathed_family_part

        return any(is_sheathed_family_part(part) for part in family.borrowed_parts)

    def template_has_model_physics(self) -> bool:
        """Whether the chosen model family has cloth/collision data to preserve."""

        if self.snapshot is None or self.draft.template_key is None:
            return False
        try:
            family = self.snapshot.family(self.draft.template_key)
        except Exception:  # noqa: BLE001 - an unresolved family exposes no option
            return False
        return any(item.exists for item in family.files_for("hkx"))

    def suggest_internal_name(self) -> str:
        """`<Template>_New`, or `_New2`, `_New3`... until no shipped item has the name."""

        template = self.template_name()
        if not template or self.snapshot is None:
            return ""
        taken = {row.string_key.casefold() for row in self.snapshot.rows.values()}
        for index in range(1, 100):
            candidate = f"{template}_New" if index == 1 else f"{template}_New{index}"
            if candidate.casefold() not in taken:
                return candidate
        return ""

    def suggest_identity_allocations(self) -> Tuple[Optional[int], Optional[str]]:
        """The key and, when needed, stem automatic planning would choose now.

        Identity controls use this only to seed an explicit manual override. The
        allocation remains owned by :class:`NewItemService`, including the identities
        reserved by earlier plans that the archive snapshot cannot see yet.
        """

        if self.snapshot is None or self.draft.template_key is None:
            return None, None
        unallocated = replace(
            self.current_spec(),
            item_key=None,
            stem=None,
            name_key=None,
            desc_key=None,
        )
        try:
            allocated = self.service.allocate(
                unallocated,
                self.snapshot,
                reserved_keys=self.issued_keys,
                reserved_stems=self.issued_stems,
            )
        except NewItemPlanError:
            return None, None
        return allocated.item_key, allocated.stem

    def template_summary(self) -> Tuple[str, ...]:
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        row = self.snapshot.row(self.draft.template_key)
        facts = self.service.build_context(self.snapshot, row.key).template
        lines = [
            f"{row.string_key} (item {row.key}), {facts.equip_type_name or 'no equip type'}, item type {row.item_type}",
            f"{len(row.enchant_levels)} enchant level(s), {len(row.price_list)} price entr(ies), stack {row.max_stack_count}",
        ]
        try:
            family = self.snapshot.family(row.key)
            lines.append(f"model {family.model_stem}: owns {', '.join(family.owned_stems) or 'nothing'}; borrows {', '.join(family.borrowed_stems) or 'nothing'}")
            missing = [item.path for item in family.missing_files]
            if missing:
                lines.append(f"missing family files: {', '.join(missing)}")
            lines.extend(baseline_lines(baseline_facts(family, self.snapshot.payload)))
        except Exception as exc:  # noqa: BLE001 - shown, not raised
            lines.append(f"model family: {exc}")
        groups = facts.item_group_keys
        lines.append(f"in {len(groups)} item group(s)")
        return tuple(lines)

    def stat_grid(self) -> Optional[StatGrid]:
        if self.snapshot is None or self.draft.template_key is None:
            return None
        row = self.snapshot.row(self.draft.template_key)
        return stat_grid_for(row, self.snapshot.status_names, self.snapshot.item_names(), self.draft.extra_stat_keys)

    def status_choices(self) -> Tuple[Tuple[int, str, bool], ...]:
        """Every StatusInfo entry as (key, label, carried by shipped equipment): the ones
        some shipped weapon or armour ladder carries first, then the rest by name."""

        if self.snapshot is None:
            return ()
        carried = self._equipment_status_keys()
        out = [(int(key), status_label(name), int(key) in carried) for key, name in self.snapshot.status_names.items()]
        return tuple(sorted(out, key=lambda item: (not item[2], item[1].casefold())))

    def _equipment_status_keys(self) -> frozenset:
        cached = getattr(self, "_equipment_status_cache", None)
        if cached is not None:
            return cached
        keys = set()
        if self.snapshot is not None:
            for row in self.snapshot.rows.values():
                if not self.snapshot.equip_type_name(row):
                    continue
                for level in row.enchant_levels:
                    for stat in level.stats:
                        keys.add(int(stat.status_key))
        self._equipment_status_cache = frozenset(keys)
        return self._equipment_status_cache

    def status_value_range(self, status_key: int):
        """What shipped equipment carries for one stat: `(entries, low, median, high)`,
        or None when no shipped row carries it.

        The studio will happily write any i32 into a stat it adds, and a value the game
        never sees on that stat is where an item goes strange in play: `AttackSpeedRate`
        runs 30,000,000 to 90,000,000 on the five shipped rows that carry it, so the
        1,000 the spin box used to start at is three orders of magnitude out. The whole
        corpus is measured in about half a second, so this is read from the rows rather
        than guessed.
        """

        if self.snapshot is None:
            return None
        return self.snapshot.status_value_ranges().get(int(status_key))

    def store_names(self) -> Tuple[str, ...]:
        return tuple(sorted(store.name for store in self.snapshot.stores)) if self.snapshot else ()

    def store_choices(self) -> Tuple[Tuple[str, str, int, bool], ...]:
        """Every store as (name, label, buyable line count, is the player's camp), the camp
        first, then the rest by name; a label reads "Store_Del_Equipment  (Equipment, 41 lines)"."""

        if self.snapshot is None:
            return ()
        out = []
        for store in self.snapshot.stores:
            name = str(store.name)
            parts = name.split("_")
            camp = len(parts) > 1 and parts[1].lower() == "camp"
            kind = parts[-1] if len(parts) > 2 else (parts[1] if len(parts) > 1 else name)
            count = len(store.buyable_entries)
            place = "your camp (base)" if camp else (parts[1] if len(parts) > 2 else "")
            lines = f"{count} line(s)" if count else "no lines yet"
            label = f"{name}  ({', '.join(item for item in (place, kind) if item)}, {lines})"
            out.append((name, label, count, camp))
        return tuple(sorted(out, key=lambda item: (not item[3], item[0].casefold())))

    def store_stock(self, store_name: str) -> Tuple[Tuple[int, str, str], ...]:
        """(item key, internal name, unlock requirement item name or "") per buyable line."""

        if self.snapshot is None:
            return ()
        try:
            store = self.snapshot.store(store_name)
        except NewItemSnapshotError:
            return ()
        names = []
        for entry in store.entries:
            if not entry.is_buyable:
                continue
            row = self.snapshot.rows.get(entry.item_key)
            requirement = ""
            if entry.requirement_item_key is not None:
                unlock = self.snapshot.rows.get(entry.requirement_item_key)
                requirement = unlock.string_key if unlock is not None else str(entry.requirement_item_key)
            names.append((entry.item_key, row.string_key if row is not None else str(entry.item_key), requirement))
        return tuple(names)

    def line_requirement(self, store_name: str, old_item_name: str) -> str:
        for _key, name, requirement in self.store_stock(store_name):
            if name == old_item_name:
                return requirement
        return ""

    def item_groups(self, text: str = "", *, limit: int = 200) -> Tuple[Tuple[int, str], ...]:
        if self.snapshot is None:
            return ()
        needle = str(text or "").strip().casefold()
        out = [(g.key, g.name) for g in self.snapshot.item_groups if not needle or needle in g.name.casefold()]
        return tuple(sorted(out, key=lambda item: item[1].casefold())[:limit])

    def template_group_names(self) -> Tuple[str, ...]:
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        key = self.draft.template_key
        return tuple(g.name for g in self.snapshot.item_groups if key in g.members)

    def languages(self) -> Tuple[str, ...]:
        return self.snapshot.languages if self.snapshot else ("eng",)

    def perk_catalogue(self, text: str = "", *, limit: int = 400) -> Tuple[Tuple[int, str], ...]:
        """(item key, label) for every gem the archives know (embedded socket items and every
        item of their type), by English name."""

        if self.snapshot is None:
            return ()
        needle = str(text or "").strip().casefold()
        english = self.snapshot.english.index()
        users = self.snapshot.socket_item_users()
        out = []
        for key in self.snapshot.perk_item_keys:
            row = self.snapshot.rows.get(key)
            if row is None:
                continue
            label = self._perk_label(key, row, english, users)
            description_entry = english.get(row.desc_key) if row.desc_key else None
            search_text = " ".join((label, str(row.string_key or ""), str(getattr(description_entry, "text", "") or ""), str(key))).casefold()
            if needle and needle not in search_text:
                continue
            out.append((key, label))
        return tuple(sorted(out, key=lambda item: item[1].casefold())[:limit])

    def perk_label(self, key: int) -> str:
        """One gem's label, read from the row rather than from the (truncated) catalogue."""

        if self.snapshot is None:
            return str(key)
        row = self.snapshot.rows.get(int(key))
        if row is None:
            return str(key)
        return self._perk_label(int(key), row, self.snapshot.english.index(), self.snapshot.socket_item_users())

    @staticmethod
    def _perk_label(key: int, row, english, users) -> str:
        entry = english.get(row.name_key) if row.name_key else None
        label = str(entry.text) if entry is not None else str(row.string_key)
        # Ranked names are self-explanatory; keep the marker for unproven standalone perks.
        ranked = str(row.string_key or "").endswith(("_II", "_III"))
        return label if users.get(int(key)) or ranked else f"{label} — experimental"

    def perk_details(self, key: int) -> str:
        """One perk's localized meaning, category, shipped use and internal identity."""

        if self.snapshot is None:
            return ""
        row = self.snapshot.rows.get(int(key))
        if row is None:
            return ""
        english = self.snapshot.english.index()
        description_entry = english.get(row.desc_key) if row.desc_key else None
        description = str(getattr(description_entry, "text", "") or "").strip()
        internal = str(row.string_key or "")
        lowered = internal.casefold()
        kind = "Ability" if "item_skill" in lowered else "Stat perk" if "item_stat" in lowered else "Perk"
        users = int(self.snapshot.socket_item_users().get(int(key), 0))
        evidence = f"Used by {users} shipped item(s)." if users else "No shipped item embeds it; treat it as experimental."
        meaning = description or "No localized description is available."
        return f"{kind}. {meaning} {evidence} Internal ID: {internal} ({int(key)})."

    def template_socket_items(self) -> Tuple[int, ...]:
        if self.snapshot is None or self.draft.template_key is None:
            return ()
        return tuple(self.snapshot.row(self.draft.template_key).socket_items)

    def item_mesh_as_planned(self):
        """The mesh a visual effect will actually sit on, and a word for what it is:
        the applied import, else the imported model at the placement set so far, else
        the template's own. The effect dialog asks for this rather than
        :meth:`item_mesh_for_preview`, whose imported model only appears once Apply
        the placement has run, so an effect was judged against the template instead.
        Returns `(mesh, kind)` where kind is "placed", "applied" or "template"; the mesh
        is None when there is nothing to parse."""

        source = self.model_import
        if source is not None:
            # the textured preview decode, not the bare scene mesh: a `.pac`'s geometry
            # names no textures, and this is the same mesh the Model step draws. The
            # rebuilt result deliberately borrows the template's material wrappers; it
            # is output authority, but using it here replaces the import's PBR authority
            # with a synthesized template surface after Apply.
            mesh = None
            for candidate in (source.baked_preview_mesh, source.baked_scene_mesh):
                try:
                    baked = bake_mesh(candidate(), self.model_placement)
                except Exception:  # noqa: BLE001 - fall back to whatever else there is
                    continue
                if baked is not None:
                    mesh = baked
                    break
            if mesh is not None:
                return glow_preview_mesh(mesh, glow_choice(self.draft)), "applied" if self.model_result is not None else "placed"
        # A restored applied result may have no live import source. Its preview decode is
        # still preferable to the bare `.pac` geometry that names no textures.
        textured = self._textured_preview_mesh()
        if textured is not None:
            return glow_preview_mesh(textured, glow_choice(self.draft)), "applied"
        mesh = self.item_mesh_for_preview()
        if mesh is None:
            return None, ""
        return glow_preview_mesh(mesh, glow_choice(self.draft)), "applied" if self.model_result is not None else "template"

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

        from cdmw.modding.mesh_parser import parse_pac

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

    def item_preview_source(self):
        """What the Model and icon step's viewport shows, textured the way the Model
        Library and the Builder show it: a `(token, build)` pair, or None when there
        is nothing to show. `build(stop_event)` runs off the UI thread and returns a
        `ModelPreviewData` (the imported model's own preview, textures and all; else
        the template's mesh decoded from the archives with its textures resolved) or,
        when the decode will not go, the bare `ParsedMesh` of `item_mesh_for_preview`.
        `token` names the source, so a view already showing it is left alone."""

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
                )

            def build_material_scene(stop_event):
                from cdmw.ui.new_item.item_preview import PlacementScene

                model = source.baked_preview_mesh()
                return PlacementScene(template=template_build(stop_event), model=model, placement=placement, model_bounds=source.baked_bounds())

            from cdmw.ui.new_item.item_preview import ProgressivePreviewSource

            build = ProgressivePreviewSource(build_geometry_scene, build_material_scene)
            return (("placement", id(source), source.bake_generation, source.mesh_generation, template_token), build)
        result = self.model_result
        model = getattr(result, "preview_model", None)
        if result is not None and model is not None and getattr(model, "meshes", None):
            return (("imported", id(result)), lambda _stop_event: model)
        if result is not None:
            mesh = self.item_mesh_for_preview()
            return (("imported-bare", id(result)), lambda _stop_event: mesh) if mesh is not None else None
        return self._template_preview_build()

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
            from cdmw.modding.mesh_parser import parse_pac

            if stop_event.is_set():
                raise RunCancelled("Template preview cancelled")
            return parse_pac(snapshot.payload(entry.path), entry.path)

        return (("template-geometry", self.draft.template_key, entry.path), build)

    def _template_preview_build(self):
        """`(token, build)` for the template's own mesh: the archive decode with its
        textures, else the bare parse; None without a template."""

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

        def build(stop_event):
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

        return (("template", self.draft.template_key, entry.path), build)

    def character_reference(self):
        """The game's own character for the placement viewport, or None.

        Read once and kept: a rig, a socket file and a body out of the archives is about a
        second, and the dialog is opened again for every effect the reader tries. Call it
        off the UI thread; the placement dialog does.
        """

        if self._character_reference is not _NOT_READ:
            return self._character_reference
        if self.snapshot is None:
            return None  # not remembered: a snapshot arriving later deserves another go
        from cdmw.services.effect_character_reference import character_reference_from_snapshot

        self._character_reference, said = character_reference_from_snapshot(self.snapshot)
        if said:
            self.log_message.emit(said)
        return self._character_reference

    def character_holding_the_item(self):
        """The character with the current template's item in its hand, or None.

        The body is read once; the frame the item mates by comes from the template's own
        prefab and is read per template, because weapons share socket files and only the
        prefab says which one an item uses. Call it off the UI thread.
        """

        reference = self.character_reference()
        snapshot, template = self.snapshot, self.draft.template_key
        if reference is None or snapshot is None:
            return None
        if self._held_character and self._held_character[0] == template:
            return self._held_character[1]
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
        held, said = held_character_from_snapshot(snapshot, reference, prefab_paths=prefabs, model_folder=folder)
        if said:
            self.log_message.emit(said)
        self._held_character = (template, held)
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

    def current_spec(self) -> NewItemSpec:
        return spec_from_draft(self.draft, self.stat_grid())

    def validate(self) -> Tuple[ValidationIssue, ...]:
        if self.snapshot is None:
            return ()
        try:
            spec = self.current_spec()
        except ValueError:
            return ()
        issues = tuple(self.service.validate(spec, self.snapshot))
        if self.model_import is not None and self.model_result is None:
            issues += (ValidationIssue(
                code="model_placement_not_applied",
                field="model",
                message=f"{self.model_import.label} is imported but its placement is not applied yet: step 3, Apply the placement.",
            ),)
        return issues

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
        self._cleanup_model_source(previous_import)
        self.model_placement = ModelPlacement()
        self.template_changed.emit(template_key)
        if had_import:
            self.model_import_changed.emit(None)

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
        return fitted_placement(source.bounds, self.template_bounds(), source_centroid=source.centroid, template_centroid=self.template_centroid())

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

        def task(log, progress, stop_event):
            def report(message: str) -> None:
                log(message)
                progress(0, 0, message)

            report(f"Reading {chosen.name}...")
            result = load_model_import_source(chosen, stop_event=stop_event, blender_path=blender, on_log=report)
            progress(1, 1, "Model source ready")
            return result

        def done(result: object) -> None:
            if not isinstance(result, ModelImportSource):
                self.status_message.emit("The model import finished with an unexpected result.", True)
                return
            previous = self.model_import
            self.model_import = result
            if previous is not result:
                self._cleanup_model_source(previous)
            result.set_bake(self._fitted_placement(result))
            self.model_placement = ModelPlacement()
            if self.model_result is not None:
                self.set_imported_model(None, None)
            self.draft.model_source = ModelSource.IMPORTED
            self.invalidate_plan()
            self.model_import_changed.emit(result)
            self.model_placement_changed.emit(self.model_placement)

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

        previous = self.model_import
        self.model_import = None
        self._cleanup_model_source(previous)
        self.model_placement = ModelPlacement()
        if self.model_result is not None:
            self.set_imported_model(None, None)
        else:
            self.draft.model_source = ModelSource.TEMPLATE
            self.invalidate_plan()
        self.model_import_changed.emit(None)

    # ------------------------------------------------------------------ tasks

    def start_snapshot(self, entries: Iterable[ArchiveEntry], *, package_root: Optional[Path] = None) -> bool:
        """Read the tables from `entries`, or, with none, list the archives under
        `package_root` first (the shell's catalogue backend leaves the legacy list empty)."""

        frozen = tuple(entries)
        if not frozen and package_root is None:
            self.snapshot_failed.emit("The archive list is empty; scan the archives first.")
            return False
        task = snapshot_task(frozen, service=self.service, read_entry=self._read_entry, package_root=package_root)

        def done(result: object) -> None:
            if isinstance(result, NewItemSnapshot):
                self.snapshot = result
                self.invalidate_plan()
                # a different install can have a different character
                self._character_reference = _NOT_READ
                self._held_character = ()
                self._material_parts = ()
                self.snapshot_ready.emit()
            else:
                self.snapshot_failed.emit("The snapshot finished with an unexpected result.")

        return self._run("snapshot", task, done, self.snapshot_failed.emit)

    # ------------------------------------------------------------------ issued identities

    _ISSUED_SETTING = "ui/new_item_issued_identities"

    def _settings(self):
        from PySide6.QtCore import QSettings

        return QSettings("CrimsonDesertModWorkbench", "CrimsonDesertModWorkbench")

    def persist_issued_identities(self) -> None:
        """Keep the identities this studio hands out in the user's settings, and take up
        the ones it kept before. The app calls this; tests leave it off."""

        self._persist_identities = True
        self._load_issued_identities()

    def _load_issued_identities(self) -> None:
        import json

        try:
            raw = str(self._settings().value(self._ISSUED_SETTING, "") or "")
            for item in (json.loads(raw) if raw else []):
                key = int(item.get("key", 0) or 0)
                stem = str(item.get("stem", "") or "")
                if key:
                    self.issued_keys.add(key)
                if stem:
                    self.issued_stems.add(stem)
        except Exception:  # noqa: BLE001 - unreadable settings cost nothing here
            pass

    def remember_issued_identity(self, item_key: int, stem: str = "") -> None:
        """Record an identity a plan handed out, so the next item takes another one."""

        import json

        key = int(item_key or 0)
        if key:
            self.issued_keys.add(key)
        if stem:
            self.issued_stems.add(str(stem))
        if not self._persist_identities:
            return
        try:
            payload = [{"key": value, "stem": ""} for value in sorted(self.issued_keys)[-200:]]
            payload += [{"key": 0, "stem": value} for value in sorted(self.issued_stems)[-200:]]
            self._settings().setValue(self._ISSUED_SETTING, json.dumps(payload))
        except Exception:  # noqa: BLE001 - remembering is best effort; this session's set still holds
            pass

    def set_mod_base(self, folder: Optional[Path]) -> str:
        """Plan the next item on the tables in `folder` rather than on the archives.

        Folder contents are inspected later by the planning worker; this UI-thread call
        only records the selected directory.
        """

        chosen = Path(folder) if folder and Path(folder).is_dir() else None
        if chosen != self.mod_base_folder:
            self.invalidate_plan()
        self.mod_base_folder = chosen
        return f"{chosen.name} already holds a mod and is selected as the base." if chosen is not None else ""

    def start_plan(self) -> bool:
        self.invalidate_plan()
        revision = self._draft_revision
        if self.snapshot is None:
            self.plan_failed.emit("Read the archives first.", ())
            return False
        try:
            spec = self.current_spec()
        except ValueError as exc:
            self.plan_failed.emit(str(exc), ())
            return False
        # Cheap validation stays immediate. Reading an existing mod and resolving an
        # icon folder happen in the planning worker.
        issues = self.service.validate(spec, self.snapshot)
        if has_errors(issues):
            self.plan_failed.emit("; ".join(issue.message for issue in issues if issue.is_error), issues)
            return False
        icon_source: Optional[Path] = None
        if spec.icon is IconSource.GENERATED:
            text = str(self.draft.icon_source_path or "").strip()
            if not text:
                self.plan_failed.emit("Choose an image (or a folder of images) to generate the icon from, or keep the template's icon.", ())
                return False
            icon_source = Path(text)
            if not icon_source.exists():
                self.plan_failed.emit(f"The icon source {icon_source} does not exist.", ())
                return False
        task = plan_task(
            spec, self.snapshot, service=self.service, model=self.model_result, scene=self.model_scene,
            icon_source_path=icon_source, reserved_keys=tuple(self.issued_keys), reserved_stems=tuple(self.issued_stems),
            mod_base_folder=self.mod_base_folder, read_entry=self._read_entry,
        )

        def done(result: object) -> None:
            if revision != self._draft_revision:
                return
            if isinstance(result, NewItemPlan):
                self.plan = result
                self._plan_revision = revision
                self.remember_issued_identity(result.spec.item_key, str(result.spec.stem or ""))
                self.plan_ready.emit(result)
            else:
                self.plan_failed.emit("The plan finished with an unexpected result.", ())

        def failed(message: str) -> None:
            if revision == self._draft_revision:
                shown = message
                prefix = "The mod folder could not be read as a base: "
                if message.startswith(prefix):
                    shown = f"The mod folder could not be read as a base: {message.removeprefix(prefix)}"
                elif icon_source is not None and icon_source.is_dir() and message.startswith("No image in "):
                    shown = f"No image in {icon_source} matched the new item closely enough; pick a file instead."
                self.plan_failed.emit(shown, ())

        return self._run("plan", task, done, failed)

    def start_export(self, package_root: Path, manager: str) -> bool:
        if not self.has_current_plan:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = export_task(self.plan, Path(package_root), service=self.service, manager=manager)
        return self._run("export", task, self.export_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_install(self, mutation_service) -> bool:
        if not self.has_current_plan:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = install_task(self.plan, service=self.service, mutation_service=mutation_service, confirmed=True)
        return self._run("install", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_install_overlay(self, mutation_service) -> bool:
        """Install the plan as its own archive directory instead of into the shipped ones."""

        if not self.has_current_plan:
            self.status_message.emit("Build the plan first.", True)
            return False
        task = install_overlay_task(self.plan, service=self.service, mutation_service=mutation_service, confirmed=True)
        return self._run("install", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_overlay_migration(self, mutation_service, package_root) -> bool:
        """Move what the shipped archives already carry into the overlay, off the UI thread."""

        task = overlay_migration_task(package_root, mutation_service=mutation_service)
        return self._run("overlay", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def start_overlay_removal(self, mutation_service, package_root) -> bool:
        """Unmount the overlay and delete it, off the UI thread."""

        task = overlay_removal_task(package_root, mutation_service=mutation_service)
        return self._run("overlay", task, self.install_finished.emit, lambda message: self.status_message.emit(message, True))

    def _run(
        self,
        lane: str,
        task,
        on_done: Callable[[object], None],
        on_error: Callable[[str], None],
        *,
        task_accepts_progress: bool = False,
    ) -> bool:
        if self._shutdown_requested:
            return False
        if self.busy:
            self.status_message.emit(f"Still busy with the previous step ({self._lane}); wait for it to finish.", True)
            return False
        if self._synchronous:
            try:
                if task_accepts_progress:
                    result = task(
                        self.log_message.emit,
                        lambda current, total, detail: self.operation_progress.emit(
                            lane, int(current), int(total), str(detail or "")
                        ),
                        threading.Event(),
                    )
                else:
                    result = task(self.log_message.emit, threading.Event())
            except (NewItemPlanError, NewItemSnapshotError, NewItemInstallRefused, ValueError, RuntimeError, OSError) as exc:
                on_error(str(exc))
                return True
            on_done(result)
            return True
        worker = UtilityWorker(
            task,
            task_accepts_progress=task_accepts_progress,
            task_accepts_cancel=True,
        )
        thread = QThread(self)
        worker.moveToThread(thread)
        self._thread, self._worker, self._lane = thread, worker, lane
        self._on_done, self._on_error = on_done, on_error
        self.busy_changed.emit(True)
        worker.log_message.connect(self.log_message.emit)
        worker.progress_changed.connect(self._task_progress)
        # Bound methods of this QObject, not closures: a plain function or lambda
        # connected to a worker's signal runs on the worker's own thread, so the panels'
        # slots (and everything they touch in Qt) ran off the UI thread for the whole of
        # an install. Connecting the controller's own methods gives a queued call back
        # onto the thread the controller lives on.
        worker.completed.connect(self._task_completed)
        worker.error.connect(self._task_failed)
        worker.finished.connect(self._worker_finished, Qt.DirectConnection)
        thread.finished.connect(self._task_finished, Qt.QueuedConnection)
        thread.started.connect(worker.run)
        thread.start()
        return True

    def _task_progress(self, current: int, total: int, detail: str) -> None:
        if (
            self._shutdown_requested
            or not self._lane
            or self._cancel_requested_lane == self._lane
        ):
            return
        self.operation_progress.emit(self._lane, int(current), int(total), str(detail or ""))

    def cancel_operation(self, lane: str = "") -> bool:
        """Request cooperative cancellation for the current matching operation."""

        expected = str(lane or "")
        if self._worker is None or (expected and expected != self._lane):
            return False
        self._worker.stop()
        self._cancel_requested_lane = self._lane
        self.operation_progress.emit(self._lane, 0, 0, "Cancelling…")
        return True

    def _task_completed(self, result: object) -> None:
        if self._shutdown_requested:
            cleanup = getattr(result, "cleanup", None)
            if callable(cleanup):
                cleanup()
            return
        if self._cancel_requested_lane == self._lane:
            cleanup = getattr(result, "cleanup", None)
            if callable(cleanup):
                cleanup()
            self.status_message.emit("Operation cancelled.", False)
            return
        handler = self._on_done
        if handler is not None:
            handler(result)

    def _task_failed(self, message: object) -> None:
        if self._shutdown_requested:
            return
        text = str(message)
        if self._cancel_requested_lane == self._lane:
            self.status_message.emit("Operation cancelled.", False)
            return
        handler = self._on_error
        if handler is not None:
            handler(text)

    def _worker_finished(self) -> None:
        """Run on the worker thread: return its QObject, then stop that event loop."""

        worker = self._worker
        if worker is not None and worker.thread() is QThread.currentThread():
            worker.moveToThread(self.thread())
        QThread.currentThread().quit()

    def _task_finished(self) -> None:
        """Run on the controller thread only after the native worker thread ended."""

        thread, worker = self._thread, self._worker
        if thread is not None and not thread.wait(0):
            QTimer.singleShot(0, self._task_finished)
            return
        self._thread = None
        self._worker = None
        self._cancel_requested_lane = ""
        self._lane = ""
        self._on_done = None
        self._on_error = None
        if worker is not None:
            worker.deleteLater()
        if thread is not None:
            thread.deleteLater()
        retired, self._model_sources_to_cleanup = self._model_sources_to_cleanup, []
        for source in retired:
            self._cleanup_model_source(source)
        if self._shutdown_requested:
            self._cleanup_model_source(self.model_import)
            self.model_import = None
        self.busy_changed.emit(False)

    # ------------------------------------------------------------------ shutdown

    def iter_shutdown_workers(self) -> Tuple[Tuple[str, QThread, object], ...]:
        workers = []
        if self._thread is not None:
            workers.append((self._lane or "task", self._thread, self._worker))
        workers.extend(self._effect_lane.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self) -> None:
        self._shutdown_requested = True
        worker = self._worker
        if worker is not None:
            worker.stop()
        thread = self._thread
        if thread is not None:
            thread.requestInterruption()
            thread.quit()
        else:
            self._cleanup_model_source(self.model_import)
            self.model_import = None
        self._effect_lane.request_shutdown()

    def shutdown(self) -> None:
        self.request_shutdown()


__all__ = ["NewItemStudioController"]
