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
from cdmw.ui.new_item.controller_model_mixin import NewItemModelControllerMixin
from cdmw.ui.new_item.controller_preview_mixin import NewItemPreviewControllerMixin
from cdmw.ui.new_item.controller_task_mixin import NewItemTaskControllerMixin
from cdmw.ui.new_item.effect_workspace_controller import NewItemEffectWorkspaceControllerMixin
from cdmw.ui.new_item.state import NewItemDraft, StatGrid, glow_choice, spec_from_draft, stat_grid_for, status_label, with_template
from cdmw.workers.effect_catalogue_worker import EffectCatalogueIndexLane
from cdmw.workers.new_item_cleanup_worker import ModelSourceCleanupLane
from cdmw.workers.new_item_workers import export_task, install_overlay_task, install_task, overlay_migration_task, overlay_removal_task, plan_task, snapshot_task
from cdmw.workers.utility_workers import UtilityWorker

class NewItemStudioController(
    NewItemPreviewControllerMixin,
    NewItemModelControllerMixin,
    NewItemTaskControllerMixin,
    NewItemEffectWorkspaceControllerMixin,
    QObject,
):
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
        #: The game's own character for the placement viewport, read once per player rig.
        #: A cached None means that rig was absent and the placement service uses a stand-in.
        self._character_references: Dict[str, object] = {}
        #: (template key, explicit preview rig or "", held character), so opening the
        #: placement workspace again does not re-read the prefab
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
        self._model_cleanup_lane = ModelSourceCleanupLane(synchronous=self._synchronous, parent=self)
        #: What every shipped effect is made of, once indexed (a minute, cached on disk).
        self.effect_catalogue: Optional[EffectCatalogue] = None
        self._effect_target_compatibility_cache: Dict[tuple, object] = {}
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
        self._model_cleanup_lane.retire(source)

    def template_options(self, text: str = "", *, limit: Optional[int] = 60) -> List[Tuple[int, str, str, str]]:
        """(key, internal name, item name, equip type) for matching equipment."""

        if self.snapshot is None:
            return []
        raw_needle = str(text or "").strip().casefold()
        query = parse_archive_search_query(text)
        display_names = self.snapshot.item_display_names()
        ranked: List[Tuple[int, str, int, str, str, str]] = []

        def term_matches(term, name_fields: Tuple[str, str], all_fields: Tuple[str, str, str, str]) -> bool:
            fields = name_fields if term.field == "name" else all_fields if term.field == "any" else ()
            value = str(term.value or "").casefold()
            return any(
                archive_name_search_text_match(field, term)
                or bool(value and not term.glob and not term.phrase and value in field.casefold())
                for field in fields
                if field
            )

        for key, row in self.snapshot.rows.items():
            equip = self.snapshot.equip_type_name(row)
            if not equip:
                continue

            internal_name = str(row.string_key or "")
            display_name = str(display_names.get(int(key), "") or "")
            name_fields = (internal_name, display_name)
            all_fields = (*name_fields, equip, str(key))

            if not query.is_empty and not any(
                all(
                    not term_matches(term, name_fields, all_fields)
                    if term.negated
                    else term_matches(term, name_fields, all_fields)
                    for term in group
                )
                for group in query.groups
            ):
                continue

            exact_values = {str(key), internal_name.casefold(), display_name.casefold()}
            rank = 0 if raw_needle and raw_needle in exact_values else 1
            ranked.append((rank, internal_name.casefold(), int(key), internal_name, display_name, equip))

        ranked.sort(key=lambda item: (item[0], item[1], item[2]))
        visible = ranked if limit is None else ranked[:limit]
        return [
            (key, internal_name, display_name, equip)
            for _rank, _name, key, internal_name, display_name, equip in visible
        ]

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
        return stat_grid_for(
            row,
            self.snapshot.status_names,
            self.snapshot.item_names(),
            extra_status_keys=self.draft.extra_stat_keys,
            extra_price_keys=tuple(sorted(self.draft.price_values)),
        )

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
