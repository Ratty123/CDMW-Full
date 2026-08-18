"""Turning a valid :class:`NewItemSpec` into archive changes.

The planner composes the format owners into one set of patches (whole replacement
payloads for the tables and language files a new item touches) and additions
(brand-new files: a cloned model family and a generated icon). The order inside a
plan is the order the game needs the data to exist in: StringInfo strings first, so
every hash the row carries resolves; part-prefab records, so every stem the strings
name resolves to a file; then the ItemInfo row that points at them; item groups,
the store, the names in every language; and the files.

Nothing here writes to the archives. A :class:`NewItemPlan` is data that
:class:`~cdmw.services.new_item_service.NewItemService` exports as a loose mod or
installs through :class:`~cdmw.services.archive_mutation_service.ArchiveMutationService`.
"""

from __future__ import annotations

import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.item_icon_addition import NewItemIcon, icon_string_for_stem
from cdmw.core.item_icon_registry import ICON_REGISTRY_PATH, IconRegistryError, add_icon_texture
from cdmw.core.pathc_format import PATHC_RELATIVE_PATH, PathcError, encode_pathc, register_dds, register_texture
from cdmw.core.prefab_binary_edit import PrefabEditError
from cdmw.core.effect_binary import decode_effect_binary
from cdmw.core.effect_edit import EMITTER_DIR, EffectEditReport, apply_effect_look, emitter_paths_of, preset_names_of, preset_path, rename_effect_strings, rename_string_values, same_length_stem
from cdmw.core.prefab_component_graft import encode_transform, graft_prefab_component
from cdmw.core.item_model_family import FamilyPart, ItemModelFamily
from cdmw.core.itemgroupinfo_table import add_group_members, apply_item_group_row, groups_containing
from cdmw.core.multichangeinfo_table import allocate_multichange_keys, clone_transition_rows, find_multichange_keys, transition_rows_for
from cdmw.core.iteminfo_row import (
    EnchantLevel,
    ItemInfoRow,
    clone_iteminfo_row,
    level_with_buy_price,
    level_with_stat,
    next_level_like,
    parse_iteminfo_row,
    price_list_with,
    rebuild_stat_block,
    set_max_stack_count,
    socket_slots_for,
)
from cdmw.core.paloc_format import add_localization_entries, encode_paloc, entries_like, text_for_language
from cdmw.core.pappt_format import PAPPT_PREFAB_ROOT, encode_pappt, insert_part_prefabs
from cdmw.core.prefab_binary_edit import rewrite_prefab_paths_any_length
from cdmw.core.storeinfo_table import apply_store_row, insert_stock_entry, swap_stock_item
from cdmw.core.stringinfo_table import append_stringinfo_strings, stringinfo_key
from cdmw.core.structured_binary_editor import append_table_rows
from cdmw.domain.archives.mutation import ArchiveAddRequest, ArchivePatchRequest, MetaFileWrite
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.rules import ValidationIssue
from cdmw.domain.new_item.spec import EnhancementRows, IconSource, ItemGroupsChoice, ModelSource, NewItemSpec, PlacementKind, SheathedModel
from cdmw.models import ArchiveEntry
from cdmw.services.new_item_snapshot import EFFECT_DIR, EFFECT_DONOR_PATH, EFFECT_DONOR_PREFAB, NewItemSnapshot, NewItemSnapshotError


def _effect_file(stem: str) -> str:
    """The archive path of an effect binary by stem."""

    return "".join((EFFECT_DIR, stem, ".pae"))


def _emitter_file(stem: str) -> str:
    """The archive path of an emitter binary by stem."""

    return "".join((EMITTER_DIR, stem, ".paem"))


def _is_sheathed_part_name(name: str) -> bool:
    """`CD_TwoHandWeapon_Sword_IN`, `CD_MainWeapon_Sword_IN_R`: the part a weapon draws sheathed."""

    return re.search(r"_in(_|$)", str(name or ""), re.I) is not None


def _is_sheathed_stem(stem: str) -> bool:
    """`cd_phm_02_sword_0001_in`, `cd_phm_01_sword_0168_r_in_index01`."""

    return re.search(r"_in(_|$)", str(stem or ""), re.I) is not None


class NewItemPlanError(ValueError):
    """Raised when a spec cannot become a plan; carries the validation issues when there are any."""

    def __init__(self, message: str, issues: Sequence[ValidationIssue] = ()) -> None:
        super().__init__(message)
        self.issues = tuple(issues)


@dataclass(frozen=True, slots=True)
class NewItemPlan:
    """Everything a new item changes, as data."""

    spec: NewItemSpec
    patches: Tuple[ArchivePatchRequest, ...]
    additions: Tuple[ArchiveAddRequest, ...]
    #: game-relative path -> bytes, for every patch and every addition (the loose form).
    loose_files: Mapping[str, bytes]
    new_paths: Tuple[str, ...]
    summary_lines: Tuple[str, ...]
    warnings: Tuple[str, ...]
    manifest: Mapping[str, object]
    issues: Tuple[ValidationIssue, ...] = ()
    #: Loose index files beside the archives to rewrite on install (`meta/0.pathc` with
    #: the new textures registered). Not part of a loose mod: the managers build it.
    meta_files: Tuple[MetaFileWrite, ...] = ()

    @property
    def touched_paths(self) -> Tuple[str, ...]:
        return tuple(request.entry.path for request in self.patches) + self.new_paths + tuple(m.path for m in self.meta_files)


@dataclass(slots=True)
class ModelFiles:
    """An imported build, as the planner needs it: the mesh and its side files."""

    pac_data: bytes
    #: game-relative template path -> bytes for the sidecar and textures the import produced.
    side_files: Mapping[str, bytes] = field(default_factory=dict)
    #: how the materials were written (`MaterialRoute` value), and what that route has to say
    material_route: str = ""
    notes: Tuple[str, ...] = ()
    warnings: Tuple[str, ...] = ()


@dataclass(slots=True)
class _Planner:
    spec: NewItemSpec
    snapshot: NewItemSnapshot
    model: Optional[ModelFiles]
    icon: Optional[NewItemIcon]
    on_log: Optional[Callable[[str], None]]
    stop_event: Optional[threading.Event]
    patches: List[ArchivePatchRequest] = field(default_factory=list)
    additions: List[ArchiveAddRequest] = field(default_factory=list)
    meta_files: List[MetaFileWrite] = field(default_factory=list)
    summary: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    manifest: Dict[str, object] = field(default_factory=dict)
    icon_string: str = ""
    icon_hash: int = 0
    enhancement_map: Dict[int, int] = field(default_factory=dict)
    #: What the graft names: the shipped effect, or the clone with the item's look.
    effect_reference: str = ""

    # ------------------------------------------------------------------ helpers

    def log(self, message: str) -> None:
        if self.on_log is not None:
            self.on_log(message)

    def check(self) -> None:
        raise_if_cancelled(self.stop_event, "New item plan cancelled.")

    @property
    def template(self) -> ItemInfoRow:
        return self.snapshot.row(self.spec.template_key)

    @property
    def family(self) -> ItemModelFamily:
        return self.snapshot.family(self.spec.template_key)

    @property
    def new_stem(self) -> str:
        return str(self.spec.stem or "")

    @property
    def clones_model(self) -> bool:
        """The item gets a model family of its own: an imported build, or the template's
        mesh copied so its prefabs can carry an effect."""

        return self.spec.needs_own_family

    def patch(self, entry: ArchiveEntry, payload: bytes, what: str) -> None:
        self.patches.append(ArchivePatchRequest(entry=entry, payload_data=bytes(payload)))
        self.summary.append(what)

    def add(self, template_entry: ArchiveEntry, path: str, payload: bytes, what: str) -> None:
        if self.snapshot.has_entry(path):
            raise NewItemPlanError(f"{path} already exists in the archives; a new item must not overwrite it")
        if any(request.path.lower() == path.lower() for request in self.additions):
            raise NewItemPlanError(f"{path} is added twice")
        self.additions.append(ArchiveAddRequest.from_template(template_entry, path, payload))
        self.summary.append(what)

    def owned_stem_map(self) -> Mapping[str, str]:
        """old part stem -> new part stem for the template's owned prefabs."""

        return {part.stem: self.family.rename_stem(part.stem, self.new_stem) for part in self.family.owned_parts if part.record is not None}

    @property
    def owns_sheathed_parts(self) -> bool:
        """The item gets sheathed (`_IN`) parts of its own drawing the imported mesh."""

        return self.spec.model_source is ModelSource.IMPORTED and self.spec.sheathed_model is SheathedModel.OWN_MODEL

    def sheathed_parts(self) -> Tuple[FamilyPart, ...]:
        """The template's borrowed `_IN` parts (the sheathed look), with a readable record and mesh."""

        return tuple(
            part for part in self.family.borrowed_parts
            if part.record is not None and part.pac_path
            and (any(_is_sheathed_part_name(p.name) for p in part.record.parts) or _is_sheathed_stem(part.stem))
        )

    def sheathed_stem_map(self) -> Mapping[str, str]:
        """borrowed `_IN` stem -> the item's own `_IN` stem, when the spec asks for them.

        `<new stem>_in`, with the hand from the part name (`_r_in`, `_l_in`) when the
        record says one, and a counter when two would collide.
        """

        if not self.owns_sheathed_parts:
            return {}
        out: Dict[str, str] = {}
        taken = set()
        for part in self.sheathed_parts():
            hand = ""
            for p in part.record.parts:
                match = re.search(r"_IN_([RL])(?![A-Za-z0-9])", p.name, re.I)
                if match:
                    hand = f"_{match.group(1).lower()}"
                    break
            base = self.new_stem + hand + "_in"
            candidate = base
            counter = 2
            while candidate in taken:
                candidate = base + str(counter)
                counter += 1
            taken |= {candidate}
            out[part.stem] = candidate
        return out

    # ------------------------------------------------------------------ steps

    def plan_strings(self) -> None:
        texts: List[str] = []
        if self.clones_model:
            texts.extend(self.owned_stem_map().values())
            texts.extend(self.sheathed_stem_map().values())
        if self.spec.icon is IconSource.GENERATED:
            self.icon_string = planned_icon_string(self.spec, self.snapshot)
            if self.icon is not None and self.icon.icon_string != self.icon_string:
                raise NewItemPlanError(f"the built icon is named {self.icon.icon_string!r}, the plan needs {self.icon_string!r}")
            self.icon_hash = stringinfo_key(self.icon_string)
            texts.append(self.icon_string)
        self.manifest["stringinfo_texts"] = list(texts)
        if not texts:
            return
        pair = self.snapshot.stringinfo
        payload, header, _keys = append_stringinfo_strings(pair.payload, pair.header, texts, name="stringinfo")
        self.patch(pair.payload_entry, payload, f"StringInfo: {len(texts)} new string(s)")
        self.patch(pair.header_entry, header, "StringInfo directory")

    def plan_part_prefabs(self) -> None:
        if not self.clones_model:
            return
        mapping = self.owned_stem_map()
        if not mapping:
            raise NewItemPlanError(f"{self.template.string_key} owns no part-prefab records to clone")
        sheathed = self.sheathed_stem_map()
        index = self.snapshot.pappt.index()
        records = [index[old].cloned(new) for old, new in mapping.items()]
        records += [index[old].cloned(new) for old, new in sheathed.items()]
        table = insert_part_prefabs(self.snapshot.pappt, records, after_stem=next(iter(mapping)))
        self.manifest["pappt_records"] = dict(mapping)
        self.manifest["sheathed_records"] = dict(sheathed)
        self.patch(self.snapshot.pappt_entry, encode_pappt(table), f"partprefabtable.pappt: {len(records)} record(s) cloned")

    def plan_enhancements(self) -> None:
        """Clone the template's own transition rows for the new item, when the spec asks for it."""

        self.manifest["enhancement_rows"] = None
        if self.spec.enhancement is not EnhancementRows.OWN:
            return
        pair = self.snapshot.multichange
        if pair is None:
            raise NewItemPlanError("the archives have no multichangeinfo table, so the item cannot get enhancement rows of its own")
        listed = find_multichange_keys(self.template, self.snapshot.multichange_rows)
        own = transition_rows_for(self.snapshot.multichange_rows, listed, self.template.key)
        if not own:
            self.warnings.append(f"{self.template.string_key} has no enhancement rows of its own to clone; the item shares whatever its template lists.")
            return
        keys = allocate_multichange_keys(self.snapshot.multichange_rows, len(own))
        payload, header, mapping = clone_transition_rows(
            pair.payload, pair.header, own, new_item_key=int(self.spec.item_key), new_item_name=self.spec.internal_name, new_keys=keys,
        )
        self.enhancement_map = dict(mapping)
        self.manifest["enhancement_rows"] = {str(old): new for old, new in mapping.items()}
        self.warnings.append(f"The item has {len(own)} enhancement row(s) of its own; cloned rows are unproven in game.")
        self.patch(pair.payload_entry, payload, f"MultiChangeInfo: {len(own)} transition row(s) cloned")
        self.patch(pair.header_entry, header, "MultiChangeInfo directory")

    def plan_item_row(self) -> bytes:
        template = self.template
        hashes: Dict[int, int] = {}
        if self.clones_model:
            hashes.update({stringinfo_key(old): stringinfo_key(new) for old, new in self.owned_stem_map().items()})
            hashes.update({stringinfo_key(old): stringinfo_key(new) for old, new in self.sheathed_stem_map().items()})
        if self.spec.icon is IconSource.GENERATED and self.family.icon_hash:
            hashes[self.family.icon_hash] = self.icon_hash
        hashes.update(self.enhancement_map)
        row_bytes = clone_iteminfo_row(
            template,
            key=int(self.spec.item_key),
            string_key=self.spec.internal_name,
            name_key=str(self.spec.name_key),
            desc_key=self.spec.desc_key,
            replace_hashes=hashes or None,
        )
        row_bytes = self._apply_row_edits(row_bytes)
        pair = self.snapshot.iteminfo
        payload, header = append_table_rows(pair.payload, pair.header, [row_bytes])
        self.manifest["iteminfo"] = {
            "template_key": template.key, "template_name": template.string_key,
            "item_key": int(self.spec.item_key), "internal_name": self.spec.internal_name,
            "name_key": self.spec.name_key, "desc_key": self.spec.desc_key,
            "hash_swaps": {f"0x{old:08X}": f"0x{new:08X}" for old, new in hashes.items()},
            "rows_before": len(self.snapshot.rows), "rows_after": len(self.snapshot.rows) + 1,
        }
        self.patch(pair.payload_entry, payload, f"ItemInfo: row {self.spec.item_key} {self.spec.internal_name} appended (template {template.string_key})")
        self.patch(pair.header_entry, header, "ItemInfo directory")
        return row_bytes

    def _apply_row_edits(self, row_bytes: bytes) -> bytes:
        spec = self.spec
        row = parse_iteminfo_row(row_bytes, item_keys=set(self.snapshot.rows) | {int(spec.item_key)})
        if spec.max_stack_count is not None and int(spec.max_stack_count) != row.max_stack_count:
            row_bytes = set_max_stack_count(row, int(spec.max_stack_count))
            row = parse_iteminfo_row(row_bytes, item_keys=set(self.snapshot.rows) | {int(spec.item_key)})
        sockets = None if spec.socket_items is None else tuple(int(item) for item in spec.socket_items)
        if sockets is not None and sockets == tuple(row.socket_items):
            sockets = None
        if not (spec.stat_edits or spec.buy_price_edits or spec.price_edits) and sockets is None:
            return row_bytes
        if row.stat_block_offset is None:
            raise NewItemPlanError(f"{self.template.string_key} has no decoded stat block; stats, prices and socket items cannot be edited")
        levels: List[EnchantLevel] = list(row.enchant_levels)
        for edit in spec.stat_edits:
            levels = _grow_levels(levels, edit.level, what=f"stat {edit.status_key}")
            levels[edit.level] = level_with_stat(levels[edit.level], int(edit.status_key), int(edit.value))
        for edit in spec.buy_price_edits:
            levels = _grow_levels(levels, edit.level, what=f"buy price in item {edit.item_key}")
            levels[edit.level] = level_with_buy_price(levels[edit.level], int(edit.item_key), int(edit.price))
        prices = row.price_list
        for edit in spec.price_edits:
            prices = price_list_with(prices, int(edit.item_key), int(edit.price))
        slots = None
        if sockets is not None and len(sockets) > len(row.add_socket_materials):
            # a row uses at most as many socket items as it has slots (`_addSocketMaterialList`)
            slots = socket_slots_for(row, len(sockets))
        rebuilt = rebuild_stat_block(row, levels=levels, price_list=prices, socket_items=sockets, add_socket_materials=slots)
        again = parse_iteminfo_row(rebuilt, item_keys=set(self.snapshot.rows) | {int(spec.item_key)})
        if again.stat_block_offset is None or again.enchant_count != len(levels) or (sockets is not None and again.socket_items != sockets):
            raise NewItemPlanError("the rebuilt stat block did not parse back the way it was written")
        if slots is not None:
            self.summary.append(f"socket slots: grown from {len(row.add_socket_materials)} to {len(slots)} so every socket item has a slot")
            self.manifest["socket_slots"] = [list(item) for item in slots]
        if len(levels) > len(row.enchant_levels):
            self.warnings.append(
                f"The row carries {len(levels) - len(row.enchant_levels)} enchant level(s) the template lacks; "
                "a rebuilt ladder is unproven in game."
            )
        if sockets is not None:
            names = [self.snapshot.rows[item].string_key if item in self.snapshot.rows else str(item) for item in sockets]
            self.summary.append(f"socket items: {len(sockets)} ({', '.join(names)}) instead of the template's {len(row.socket_items)}")
            self.manifest["socket_items"] = list(sockets)
            if len(sockets) > 4:
                self.warnings.append(f"The row carries {len(sockets)} socket items; no shipped item carries more than 4, so that many is unproven in game.")
        self.summary.append(
            f"stats: {len(spec.stat_edits)} stat, {len(spec.buy_price_edits)} buy-price and {len(spec.price_edits)} price edit(s)"
        )
        return rebuilt

    def plan_item_groups(self) -> None:
        template_key = int(self.spec.template_key)
        if self.spec.item_groups is ItemGroupsChoice.EXPLICIT:
            wanted = {int(k) for k in self.spec.explicit_item_groups}
            groups = [g for g in self.snapshot.item_groups if g.key in wanted]
        else:
            groups = list(groups_containing(self.snapshot.item_groups, template_key))
        if not groups:
            self.manifest["item_groups"] = []
            return
        pair = self.snapshot.itemgroupinfo
        payload, header = pair.payload, pair.header
        names = []
        for group in groups:
            grown = add_group_members(group, [int(self.spec.item_key)], after=template_key if template_key in group.members else None)
            payload, header = apply_item_group_row(payload, header, grown)
            names.append(group.name)
        self.manifest["item_groups"] = names
        self.patch(pair.payload_entry, payload, f"ItemGroupInfo: joined {len(groups)} group(s)")
        self.patch(pair.header_entry, header, "ItemGroupInfo directory")

    def plan_store(self) -> None:
        placement = self.spec.placement
        if placement.kind is PlacementKind.NONE:
            self.manifest["store"] = None
            return
        store = self.snapshot.store(placement.store_name)
        if placement.kind is PlacementKind.SWAP:
            old_key = self.snapshot.keys_by_name.get(placement.old_item_name)
            if old_key is None:
                raise NewItemPlanError(f"there is no item named {placement.old_item_name}")
            updated = swap_stock_item(store, old_key, int(self.spec.item_key), keep_requirement=placement.keep_requirement)
            what = f"StoreInfo: {store.name} sells {self.spec.internal_name} instead of {placement.old_item_name}"
            required = next((e.requirement_item_key for e in store.entries_for(old_key) if e.requirement_item_key is not None), None)
        else:
            updated = insert_stock_entry(store, int(self.spec.item_key), keep_requirement=placement.keep_requirement)
            what = f"StoreInfo: {store.name} gains a stock entry for {self.spec.internal_name}"
            self.warnings.append("A whole new stock entry is unproven in game; swapping an existing entry is the proven form.")
            required = store.buyable_entries[-1].requirement_item_key if store.buyable_entries else None
        if required is not None:
            unlock = self.snapshot.rows.get(required)
            unlock_name = unlock.string_key if unlock is not None else str(required)
            if placement.keep_requirement:
                self.warnings.append(f"The shop line keeps its unlock requirement: the buyer needs the knowledge of {unlock_name} before it sells (the shop shows \"Knowledge\" until then).")
            else:
                what += f" (its unlock requirement, the knowledge of {unlock_name}, dropped so it sells freely)"
        if placement.price is not None:
            self.warnings.append("StoreInfo entries carry no price of their own; the shop prices the item from its buy-price list, so the placement price was not written. Use a buy-price edit.")
        pair = self.snapshot.storeinfo
        payload, header = apply_store_row(pair.payload, pair.header, updated)
        self.manifest["store"] = {"name": store.name, "kind": placement.kind.value, "old_item": placement.old_item_name or None, "requirement_kept": bool(placement.keep_requirement)}
        self.patch(pair.payload_entry, payload, what)
        self.patch(pair.header_entry, header, "StoreInfo directory")

    def plan_names(self) -> None:
        template = self.template
        if not template.name_key:
            raise NewItemPlanError(f"{template.string_key} has no name key to copy the category from")
        languages = self.snapshot.languages
        written: Dict[str, Dict[str, str]] = {}
        for language in languages:
            self.check()
            table = self.snapshot.paloc_table(language)
            index = table.index()
            template_name = index.get(template.name_key)
            if template_name is None:
                raise NewItemPlanError(f"the {language} table has no entry {template.name_key} for the template's name")
            name = text_for_language(self.spec.display_names, language) or template_name.text
            texts = {str(self.spec.name_key): name}
            template_desc = index.get(template.desc_key) if template.desc_key else None
            if self.spec.desc_key and template.desc_key:
                if template_desc is None:
                    raise NewItemPlanError(f"the {language} table has no entry {template.desc_key} for the template's description")
                texts[str(self.spec.desc_key)] = text_for_language(self.spec.descriptions, language) or template_desc.text
            new_entries = entries_like(table, template.name_key, {str(self.spec.name_key): texts[str(self.spec.name_key)]})
            if len(texts) == 2:
                new_entries += entries_like(table, template.desc_key, {str(self.spec.desc_key): texts[str(self.spec.desc_key)]})
            grown = add_localization_entries(table, new_entries)
            entry = self.snapshot.paloc_entries[language]
            self.patch(entry, encode_paloc(grown), f"{language}: {len(new_entries)} localisation record(s)")
            written[language] = texts
        self.manifest["localisation"] = written

    def plan_model_files(self) -> None:
        if not self.clones_model:
            self.manifest["model_files"] = []
            self.manifest["effect"] = None
            return
        family = self.family
        renamed = {old: (role, new) for role, old, new in family.renamed(self.new_stem)}
        pac_files = [item for item in family.files_for("pac") if item.exists]
        if not pac_files:
            raise NewItemPlanError(f"{self.template.string_key}'s family has no .pac to replace")
        # The family stem names the mesh the import replaces; a second owned mesh (a
        # sheath) is copied under the new stem so its prefabs keep resolving.
        primary = next((item for item in pac_files if item.path.lower().rsplit("/", 1)[-1] == f"{family.model_stem.lower()}.pac"), pac_files[0])
        if self.model is None:
            if self.spec.model_source is ModelSource.IMPORTED:
                raise NewItemPlanError("the spec imports a model but no build was given")
            # an effect on the template's own model: the family is copied as it is
            self.model = ModelFiles(pac_data=self.snapshot.payload(primary.path))
        pac_map = {item.path: renamed[item.path][1] for item in pac_files}
        old_pac = primary.path
        texture_map = self._texture_renames()
        donor = self._effect_donor()
        written: List[str] = []
        for item in family.files:
            role, new_path = renamed[item.path]
            if role == "icon":
                continue
            if not item.exists:
                self.warnings.append(f"The template has no {role} at {item.path}; the clone goes without one.")
                continue
            if role == "pac":
                payload = self.model.pac_data if item.path == old_pac else self.snapshot.payload(item.path)
            elif role == "prefab":
                result = rewrite_prefab_paths_any_length(self.snapshot.payload(item.path), pac_map)
                if not result.edits:
                    raise NewItemPlanError(f"{item.path} names none of the family's meshes, so it cannot be re-pathed")
                payload = result.data
                if donor is not None:
                    payload = self._graft_effect(payload, donor, new_path)
            elif role == "pac_xml":
                payload = self.model.side_files.get(item.path, self.snapshot.payload(item.path))
                for old_name, new_name in texture_map.items():
                    payload = payload.replace(old_name.encode("utf-8"), new_name.encode("utf-8"))
            else:
                payload = self.snapshot.payload(item.path)
            self.add(self.snapshot.entry(item.path), new_path, payload, f"{role}: {new_path}")
            written.append(new_path)
        for old_path, data in self.model.side_files.items():
            if not old_path.lower().endswith(".dds"):
                continue
            folder, _, name = old_path.replace("\\", "/").rpartition("/")
            new_name = texture_map[name]
            new_path = f"{folder}/{new_name}" if folder else new_name
            template_entry = self.snapshot.entry(old_path) if self.snapshot.has_entry(old_path) else self.snapshot.entry(old_pac)
            self.add(template_entry, new_path, data, f"texture: {new_path}")
            written.append(new_path)
        for old_stem, new_stem in self.sheathed_stem_map().items():
            part = next(p for p in self.sheathed_parts() if p.stem == old_stem)
            new_prefab = part.record.cloned(new_stem).prefab_path
            source = self.snapshot.payload(part.prefab_path)
            result = rewrite_prefab_paths_any_length(source, {part.pac_path: pac_map[old_pac]})
            if not result.edits:
                raise NewItemPlanError(f"{part.prefab_path} names no mesh to re-path to the imported model")
            self.add(self.snapshot.entry(part.prefab_path), new_prefab, result.data, f"sheathed prefab: {new_prefab} (draws the imported mesh instead of {part.pac_path.rsplit('/', 1)[-1]})")
            written.append(new_prefab)
        self.manifest["model_files"] = written
        self.manifest["sheathed_model"] = self.spec.sheathed_model.value if self.spec.model_source is ModelSource.IMPORTED else None
        self.manifest["material_route"] = self.model.material_route or None
        if self.model.material_route:
            self.summary.append(f"materials: {self.model.material_route}")
        for note in self.model.notes:
            self.summary.append(f"  {note}")
        self.warnings.extend(self.model.warnings)

    def _effect_donor(self) -> Optional[bytes]:
        if self.spec.effect is None:
            self.manifest["effect"] = None
            return None
        if not self.snapshot.has_entry(EFFECT_DONOR_PREFAB):
            raise NewItemPlanError(f"the archives have no {EFFECT_DONOR_PREFAB}, the prefab a weapon effect is grafted from")
        self.effect_reference = str(self.spec.effect)
        self.manifest["effect"] = {"path": str(self.spec.effect), "donor": EFFECT_DONOR_PREFAB, "prefabs": []}
        self.warnings.append(f"The effect {self.spec.effect} is grafted into the item's prefabs as an EffectComponent; a grafted fire has drawn in game, and an effect made for another weapon may need a scale or an offset to sit on this one.")
        self._clone_effect_for_look()
        return self.snapshot.payload(EFFECT_DONOR_PREFAB)

    def _clone_effect_for_look(self) -> None:
        """With a look that is not as shipped: the effect and its emitters cloned under
        stems of the item's own (same length, no relocation), edited in place, added; the
        graft then names the clone."""

        look = self.spec.effect_look
        if look.is_default:
            self.manifest["effect"]["look"] = None
            return
        stem, suffix = str(self.spec.effect).split(".", 1)
        effect_path = _effect_file(stem)
        if not self.snapshot.has_entry(effect_path):
            raise NewItemPlanError(f"the archives have no {effect_path}, so its look cannot be edited")
        tag = f"_n{int(self.spec.item_key or 0) % 100000:05d}"
        taken = set(self.snapshot.effect_stems)
        new_stem = same_length_stem(stem, tag, taken=taken)
        taken.add(new_stem)
        source = self.snapshot.payload(effect_path)
        document = decode_effect_binary(source)
        if not document.walk_complete:
            raise NewItemPlanError(f"{effect_path} did not decode fully ({document.walk_note}); its look cannot be edited")
        renames: Dict[str, str] = {stem: new_stem}
        emitter_clones: List[Tuple[str, str, str]] = []
        for emitter_path in emitter_paths_of(document):
            if not self.snapshot.has_entry(emitter_path):
                self.warnings.append(f"The effect names {emitter_path}, which the archives do not have; the clone keeps naming the shipped emitter.")
                continue
            old_emitter = emitter_path.rsplit("/", 1)[-1][: -len(".paem")]
            new_emitter = same_length_stem(old_emitter, tag, taken=taken)
            taken.add(new_emitter)
            renames[old_emitter] = new_emitter
            emitter_clones.append((emitter_path, old_emitter, new_emitter))
        # the render and simulation presets the effect and its emitters name: cloned too,
        # since an emitter's colour is the render preset's unless it overrides it
        emitter_sources = {path: self.snapshot.payload(path) for path, _old, _new in emitter_clones}
        preset_renames: Dict[str, str] = {}
        preset_clones: List[Tuple[str, str, str]] = []
        seen_presets: List[Tuple[str, str]] = []
        for kind, name in preset_names_of(document) + tuple(
            item for data in emitter_sources.values() for item in preset_names_of(decode_effect_binary(data))
        ):
            if (kind, name) in seen_presets:
                continue
            seen_presets.append((kind, name))
            path = preset_path(kind, name)
            if not self.snapshot.has_entry(path):
                continue
            new_name = same_length_stem(name, tag, taken=taken)
            taken.add(new_name)
            preset_renames[name] = new_name
            preset_clones.append((path, kind, new_name))
        report = EffectEditReport()

        def cloned(data: bytes) -> bytes:
            renamed = rename_effect_strings(data, renames)
            if preset_renames:
                renamed = rename_string_values(renamed, preset_renames)
            return renamed

        edited_effect, report = apply_effect_look(cloned(source), look, report=report)
        new_effect_path = _effect_file(new_stem)
        self.add(self.snapshot.entry(effect_path), new_effect_path, edited_effect, f"effect clone: {new_effect_path}")
        written = [new_effect_path]
        for emitter_path, _old, new_emitter in emitter_clones:
            edited, report = apply_effect_look(cloned(emitter_sources[emitter_path]), look, report=report)
            new_path = _emitter_file(new_emitter)
            self.add(self.snapshot.entry(emitter_path), new_path, edited, f"emitter clone: {new_path}")
            written.append(new_path)
        for path, kind, new_name in preset_clones:
            edited, report = apply_effect_look(rename_string_values(self.snapshot.payload(path), preset_renames), look, report=report)
            new_path = preset_path(kind, new_name)
            self.add(self.snapshot.entry(path), new_path, edited, f"preset clone: {new_path}")
            written.append(new_path)
        self.effect_reference = f"{new_stem}.{suffix}"
        self.manifest["effect"]["path"] = self.effect_reference
        self.manifest["effect"]["look"] = {
            "source": str(self.spec.effect), "color": list(look.color) if look.color else None,
            "intensity": look.intensity, "size": look.size, "rate": look.rate, "lifetime": look.lifetime,
            "files": written, "edited": dict(report.edited),
        }
        touched = ", ".join(f"{name} x{count}" for name, count in sorted(report.edited.items())) or "nothing the files carry"
        self.summary.append(f"effect look: {stem} cloned as {new_stem} with {len(emitter_clones)} emitter(s) and {len(preset_clones)} preset(s); edited {touched}")
        if not report.total:
            self.warnings.append("The chosen look edits nothing this effect carries (no colour, brightness, scale, spawn count or lifetime member); the clone draws as shipped.")

    def _graft_effect(self, prefab: bytes, donor: bytes, new_path: str) -> bytes:
        try:
            scale = float(self.spec.effect_scale)
            offset = tuple(float(v) for v in self.spec.effect_offset)
            result = graft_prefab_component(
                prefab, donor, component_type="EffectComponent",
                path_replacements={EFFECT_DONOR_PATH: str(self.effect_reference)},
                offset_transform=encode_transform(scale=(scale, scale, scale), position=offset),
            )
        except PrefabEditError as exc:
            raise NewItemPlanError(f"{new_path}: the effect could not be grafted: {exc}") from exc
        self.manifest["effect"]["prefabs"].append(new_path)
        self.manifest["effect"]["scale"] = scale
        self.manifest["effect"]["offset"] = list(offset)
        placed = f", scale {scale:g}" + (f", offset {offset[0]:g} {offset[1]:g} {offset[2]:g}" if any(offset) else "")
        self.summary.append(f"effect: {self.effect_reference} grafted into {new_path.rsplit('/', 1)[-1]} ({', '.join(result.types_added) or 'types already declared'}{placed})")
        return result.data

    def _texture_renames(self) -> Mapping[str, str]:
        """texture file name -> new file name for the textures the import produced."""

        stem = self.family.model_stem
        out: Dict[str, str] = {}
        if self.model is None:
            return out
        for old_path in self.model.side_files:
            if not old_path.lower().endswith(".dds"):
                continue
            name = old_path.replace("\\", "/").rsplit("/", 1)[-1]
            lower = name.lower()
            if lower.startswith(stem.lower()):
                out[name] = self.new_stem + name[len(stem):]
            else:
                out[name] = f"{self.new_stem}_{name}"
        return out

    def plan_icon(self) -> None:
        if self.spec.icon is not IconSource.GENERATED:
            self.manifest["icon"] = None
            return
        if self.icon is None:
            raise NewItemPlanError("the spec asks for a generated icon but no icon was built")
        icon_files = self.family.files_for("icon")
        template_entry = self.snapshot.entry(icon_files[0].path) if icon_files and icon_files[0].exists else None
        if template_entry is None:
            raise NewItemPlanError(f"{self.template.string_key} has no icon file to shape the new one after")
        self.add(template_entry, self.icon.target_path, self.icon.payload_data, f"icon: {self.icon.target_path}")
        self.manifest["icon"] = {"string": self.icon.icon_string, "hash": f"0x{self.icon.icon_hash:08X}", "path": self.icon.target_path, "registered": False}
        # the UI finds an icon by name through ui/xml/texture/cd_item_icon.xml; without a line there the file draws as the bag
        if not self.snapshot.has_entry(ICON_REGISTRY_PATH):
            self.warnings.append(f"No icon registry ({ICON_REGISTRY_PATH}) in the archives; the generated icon will not draw until it is registered there.")
            return
        template_icon = self.family.icon_string or ""
        try:
            registry = add_icon_texture(self.snapshot.payload(ICON_REGISTRY_PATH), self.icon.icon_string, like=template_icon)
        except IconRegistryError as exc:
            raise NewItemPlanError(f"icon registry: {exc}") from exc
        self.patch(self.snapshot.entry(ICON_REGISTRY_PATH), registry, f"icon registry: {self.icon.icon_string} declared in {ICON_REGISTRY_PATH.rsplit('/', 1)[-1]}")
        self.manifest["icon"]["registered"] = True

    def plan_texture_registry(self) -> None:
        """Register every new `.dds` in `meta/0.pathc`: the game looks textures up there first.

        The icon is registered like the template's icon (same header, checked against
        the new file's own header); an imported model's textures under the shipped
        header their DDS header equals. Without a registry in the snapshot the plan
        still builds, with a warning, since a loose mod leaves this to the manager.
        """

        new_dds = [request for request in self.additions if request.path.lower().endswith(".dds")]
        self.manifest["texture_registry"] = []
        if not new_dds:
            return
        table = self.snapshot.pathc
        if table is None:
            self.warnings.append("No texture registry (meta/0.pathc) was found beside the archives; the new textures will not draw when installed directly until it is rebuilt.")
            return
        icon_files = self.family.files_for("icon")
        template_icon = icon_files[0].path if icon_files and icon_files[0].exists else ""
        registered = []
        for request in new_dds:
            try:
                if self.icon is not None and request.path == self.icon.target_path and template_icon:
                    table = register_texture(table, request.path, like=template_icon, dds_header=request.payload_data)
                else:
                    table = register_dds(table, request.path, request.payload_data)
            except PathcError as exc:
                raise NewItemPlanError(f"texture registry: {exc}") from exc
            registered.append(request.path)
        self.meta_files.append(MetaFileWrite(PATHC_RELATIVE_PATH, encode_pathc(table)))
        self.summary.append(f"texture registry: {len(registered)} new texture(s) registered in {PATHC_RELATIVE_PATH}")
        self.manifest["texture_registry"] = registered


def planned_icon_string(spec: NewItemSpec, snapshot: NewItemSnapshot) -> str:
    """The `ItemIcon_Prefab_*` string a generated icon for `spec` is named by."""

    if not spec.stem:
        raise NewItemPlanError("a generated icon needs the spec's stem to be allocated")
    family = snapshot.family(spec.template_key)
    return family.renamed_icon_string(str(spec.stem)) or icon_string_for_stem(str(spec.stem))


def _grow_levels(levels: List[EnchantLevel], level: int, *, what: str) -> List[EnchantLevel]:
    if level < 0:
        raise NewItemPlanError(f"enchant level {level} for {what} is negative")
    if level > len(levels):
        raise NewItemPlanError(f"enchant level {level} for {what} skips level {len(levels)}; levels are added one at a time")
    if level == len(levels):
        if not levels:
            raise NewItemPlanError(f"the template has no enchant level to copy for {what}")
        levels = levels + [next_level_like(levels[-1])]
    return levels


def build_plan(
    spec: NewItemSpec,
    snapshot: NewItemSnapshot,
    *,
    model: Optional[ModelFiles] = None,
    icon: Optional[NewItemIcon] = None,
    issues: Sequence[ValidationIssue] = (),
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> NewItemPlan:
    """Compose the plan for an allocated, validated spec."""

    for name in ("item_key", "name_key"):
        if getattr(spec, name) is None:
            raise NewItemPlanError(f"the spec's {name} is not allocated")
    if spec.needs_new_stem and not spec.stem:
        raise NewItemPlanError("the spec needs a stem and none is allocated")
    planner = _Planner(spec=spec, snapshot=snapshot, model=model, icon=icon, on_log=on_log, stop_event=stop_event)
    planner.manifest.update({
        "template_key": int(spec.template_key),
        "item_key": int(spec.item_key),
        "internal_name": spec.internal_name,
        "stem": spec.stem,
        "model_source": spec.model_source.value,
        "icon_source": spec.icon.value,
    })
    try:
        for step, label in (
            (planner.plan_strings, "strings"), (planner.plan_part_prefabs, "part prefabs"), (planner.plan_enhancements, "enhancement rows"),
            (planner.plan_item_row, "item row"),
            (planner.plan_item_groups, "item groups"), (planner.plan_store, "store"), (planner.plan_names, "names"),
            (planner.plan_model_files, "model files"), (planner.plan_icon, "icon"), (planner.plan_texture_registry, "texture registry"),
        ):
            planner.check()
            planner.log(f"Planning {label}...")
            step()
    except NewItemSnapshotError as exc:
        raise NewItemPlanError(str(exc)) from exc
    loose: Dict[str, bytes] = {request.entry.path.replace("\\", "/"): bytes(request.payload_data) for request in planner.patches}
    for request in planner.additions:
        loose[request.path] = bytes(request.payload_data)
    return NewItemPlan(
        spec=spec,
        patches=tuple(planner.patches),
        additions=tuple(planner.additions),
        loose_files=loose,
        new_paths=tuple(request.path for request in planner.additions),
        summary_lines=tuple(planner.summary),
        warnings=tuple(planner.warnings),
        manifest=dict(planner.manifest),
        issues=tuple(issues),
        meta_files=tuple(planner.meta_files),
    )


def model_files_from_import(result: object, *, family: ItemModelFamily) -> ModelFiles:
    """Read a Builder result (`MeshImportPreviewResult`) into :class:`ModelFiles`.

    `rebuilt_data` is the mesh; each supplemental spec is taken by its target path,
    from `payload_data` when the import carried the bytes and from `source_path`
    otherwise. Only the family's own sidecar and `.dds` textures are kept; anything
    else the import produced is reported through the returned object's side files
    being absent, and the planner warns about the sidecar it fell back on.
    """

    data = bytes(getattr(result, "rebuilt_data", b"") or b"")
    if not data:
        raise NewItemPlanError("the imported build carries no rebuilt mesh data")
    side: Dict[str, bytes] = {}
    pac_xml_paths = {item.path.lower() for item in family.files_for("pac_xml")}
    for spec in tuple(getattr(result, "supplemental_file_specs", ()) or ()):
        target = str(getattr(spec, "target_path", "") or "").replace("\\", "/").strip("/")
        if not target:
            continue
        lower = target.lower()
        if not (lower.endswith(".dds") or lower in pac_xml_paths):
            continue
        payload = bytes(getattr(spec, "payload_data", b"") or b"")
        if not payload:
            source = getattr(spec, "source_path", None)
            if source is not None and Path(source).is_file():
                payload = Path(source).read_bytes()
        if payload:
            side[target] = payload
    return ModelFiles(pac_data=data, side_files=side)


__all__ = [
    "ModelFiles",
    "NewItemPlan",
    "NewItemPlanError",
    "build_plan",
    "model_files_from_import",
    "planned_icon_string",
]
