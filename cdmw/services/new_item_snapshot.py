"""The read-only view of the archives a new item is planned against.

`build_snapshot` reads the tables a new item touches once (ItemInfo, StringInfo,
the part-prefab table, StoreInfo, ItemGroupInfo, StatusInfo, EquipTypeInfo and the
English localisation table) and keeps them parsed, off the UI thread, so that
validation and planning are lookups rather than archive reads. `build_context`
projects that snapshot onto the domain's :class:`NewItemContext` for one template.

The snapshot never writes. It holds the archive entries by lower-case path and a
reader, which is also how the planner reaches the template's model files.
"""

from __future__ import annotations

import struct
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.item_model_family import ItemModelFamily, ItemModelFamilyError, discover_item_model_family
from cdmw.core.itemgroupinfo_table import ItemGroupRow, groups_containing, parse_item_group_table
from cdmw.domain.new_item.allocation import DEFAULT_ITEM_KEY_RANGE
from cdmw.core.iteminfo_row import ItemInfoRow, ItemInfoRowError, parse_iteminfo_row, parse_status_names
from cdmw.core.multichangeinfo_table import MultiChangeRow, parse_multichange_table
from cdmw.core.pathc_format import PATHC_RELATIVE_PATH, PathcError, PathcTable, parse_pathc
from cdmw.core.paloc_format import LocalizationTable, language_of_paloc_path, parse_paloc
from cdmw.core.pappt_format import PartPrefabTable, parse_pappt
from cdmw.core.storeinfo_table import StoreInfoError, StoreRow, parse_store_table
from cdmw.core.stringinfo_table import parse_stringinfo, stringinfo_index
from cdmw.core.structured_binary_editor import parse_pabgh_table
from cdmw.domain.cancellation import raise_if_cancelled
from cdmw.domain.new_item.rules import NewItemContext, TemplateFacts, TemplateLevelFacts
from cdmw.models import ArchiveEntry

TABLE_DIR = "gamedata/binary__/client/bin"
PALOC_DIR = "gamedata/stringtable/binary__"
PAPPT_PATH = "character/bin__/partprefabtable.pappt"
#: Where the shipped effect binaries live; a visual effect names one by stem.
EFFECT_DIR = "effect/binary__/releasebin/"
#: The shipped prefab whose EffectComponent is the structural donor for item effects.
EFFECT_DONOR_PREFAB = "character/bin__/prefab/1_pc/01_phm/weapon/10_thrownweapon/cd_phm_10_thrownspear_0001.prefab"
#: The effect the donor names, replaced by the item's own.
EFFECT_DONOR_PATH = "pafx_kliff_titan_lightning_spear_loop_001a.level.effect"
MODEL_ROOT = "character/model/"

ReadEntry = Callable[[ArchiveEntry], bytes]


class NewItemSnapshotError(RuntimeError):
    """Raised when the archives do not hold what a new item needs."""


@dataclass(frozen=True, slots=True)
class TablePair:
    """A `.pabgb` payload and its `.pabgh` directory, with the entries they came from."""

    payload_entry: ArchiveEntry
    header_entry: ArchiveEntry
    payload: bytes
    header: bytes


@dataclass(slots=True)
class NewItemSnapshot:
    entries: Mapping[str, ArchiveEntry]
    read_entry: ReadEntry
    iteminfo: TablePair
    rows: Mapping[int, ItemInfoRow]
    keys_by_name: Mapping[str, int]
    stringinfo: TablePair
    stringinfo_texts: Mapping[int, str]
    pappt_entry: ArchiveEntry
    pappt: PartPrefabTable
    storeinfo: TablePair
    stores: Tuple[StoreRow, ...]
    itemgroupinfo: TablePair
    item_groups: Tuple[ItemGroupRow, ...]
    status_names: Mapping[int, str]
    equip_type_names: Mapping[int, str]
    #: The enhancement transition table; None when the archives have no multichangeinfo pair.
    multichange: Optional[TablePair]
    multichange_rows: Mapping[int, MultiChangeRow]
    #: language code -> the .paloc entry; only English is parsed up front.
    paloc_entries: Mapping[str, ArchiveEntry]
    english: LocalizationTable
    model_stems: FrozenSet[str]
    #: The texture registry beside the archives (`meta/0.pathc`), or None when the
    #: package root has none; a new icon needs a row in it to draw.
    pathc: Optional[PathcTable] = None
    #: Stems of the shipped effect binaries (`effect/binary__/releasebin/<stem>.pae`),
    #: what a visual effect may name.
    effect_stems: FrozenSet[str] = frozenset()
    _status_ranges: Optional[Mapping[int, Tuple[int, int, int, int]]] = field(default=None, repr=False)
    _socket_users: Optional[Mapping[int, int]] = field(default=None, repr=False)
    _item_names: Optional[Mapping[int, str]] = field(default=None, repr=False)
    #: template key -> the validation context built for it; see :func:`build_context`
    _contexts: Dict[int, NewItemContext] = field(default_factory=dict, repr=False)
    _families: Dict[int, ItemModelFamily] = field(default_factory=dict, repr=False)
    _payloads: Dict[str, bytes] = field(default_factory=dict, repr=False)
    _index_maps: Optional[Tuple[Mapping[str, Sequence[ArchiveEntry]], Mapping[str, Sequence[ArchiveEntry]]]] = field(default=None, repr=False)

    # ------------------------------------------------------------------ lookups

    def entry(self, path: str) -> ArchiveEntry:
        key = str(path or "").replace("\\", "/").strip("/").lower()
        entry = self.entries.get(key)
        if entry is None:
            raise NewItemSnapshotError(f"the archives have no entry {path}")
        return entry

    @property
    def socket_item_keys(self) -> FrozenSet[int]:
        """Item keys some shipped row embeds as a socket item (the Abyss Gear "perks")."""

        return frozenset(item for row in self.rows.values() for item in row.socket_items)

    @property
    def perk_item_keys(self) -> FrozenSet[int]:
        """The embedded socket items plus every row of the same item type(s): the whole
        gem catalogue (190 Abyss Gear items of type 2501 in the shipped table), not only
        the ones some item happens to carry."""

        embedded = self.socket_item_keys
        types = {self.rows[key].item_type for key in embedded if key in self.rows and self.rows[key].item_type is not None}
        return embedded | frozenset(key for key, row in self.rows.items() if row.item_type in types)

    def has_entry(self, path: str) -> bool:
        return str(path or "").replace("\\", "/").strip("/").lower() in self.entries

    def archive_index_maps(self) -> Tuple[Mapping[str, Sequence[ArchiveEntry]], Mapping[str, Sequence[ArchiveEntry]]]:
        """The whole listing the way the archive workflows index it: by normalized path
        and by basename, each to the entries that answer. The texture resolver walks these
        (a weapon's textures sit under `character/texture/`, not beside its mesh), so
        they cover every entry. A snapshot opened from Archive Browser retains its
        published indexes; direct/headless callers build them once on first use (a second
        or two over a full install). A race between two fallback builders only builds them
        twice."""

        cached = self._index_maps
        if cached is not None:
            return cached
        by_path: Dict[str, Tuple[ArchiveEntry, ...]] = {}
        grouped: Dict[str, List[ArchiveEntry]] = {}
        for key, entry in self.entries.items():
            by_path[key] = (entry,)
            grouped.setdefault(key.rsplit("/", 1)[-1], []).append(entry)
        maps = (by_path, {name: tuple(items) for name, items in grouped.items()})
        self._index_maps = maps
        return maps

    def payload(self, path: str) -> bytes:
        """The bytes of an archive entry, read once and kept.

        A read that fails is checked against the archive as it is now: another program
        rewriting the game's archives -- a mod manager mounting or unmounting, a game
        update -- moves every payload, and the entries this snapshot was built from then
        point at the wrong bytes. What comes back is not the file, so decompression or
        decryption refuses it, and the crypto message that surfaces says nothing about the
        cause. When the archive's own index disagrees with what this snapshot holds, that
        is the cause, and the answer is to read the archives again.
        """

        key = str(path or "").replace("\\", "/").strip("/").lower()
        cached = self._payloads.get(key)
        if cached is None:
            entry = self.entry(path)
            try:
                cached = bytes(self.read_entry(entry))
            except Exception as exc:  # noqa: BLE001 - re-raised either way, with the cause when there is one
                moved = _entry_moved_on_disk(entry)
                if moved:
                    raise NewItemSnapshotError(
                        f"{entry.path} is not where the workbench last saw it ({moved}). The game's archives have been "
                        "rewritten since they were read -- a mod manager mounting or unmounting them will do that -- so "
                        "read the archives again before building."
                    ) from exc
                raise
            self._payloads[key] = cached
        return cached

    def payload_or_none(self, path: str) -> Optional[bytes]:
        return self.payload(path) if self.has_entry(path) else None

    def row(self, item_key: int) -> ItemInfoRow:
        row = self.rows.get(int(item_key))
        if row is None:
            raise NewItemSnapshotError(f"item {item_key} is not in ItemInfo")
        return row

    def store(self, name: str) -> StoreRow:
        for row in self.stores:
            if row.name == name:
                return row
        raise NewItemSnapshotError(f"there is no store named {name}")

    def family(self, item_key: int) -> ItemModelFamily:
        """The template's model family, resolved once per snapshot."""

        key = int(item_key)
        cached = self._families.get(key)
        if cached is None:
            cached = discover_item_model_family(
                self.row(key),
                stringinfo=self.stringinfo_texts,
                pappt=self.pappt,
                read_entry=self.payload_or_none,
                path_exists=self.has_entry,
            )
            self._families[key] = cached
        return cached

    def paloc_table(self, language: str) -> LocalizationTable:
        if language == "eng":
            return self.english
        entry = self.paloc_entries.get(language)
        if entry is None:
            raise NewItemSnapshotError(f"there is no localisation table for {language}")
        return parse_paloc(self.payload(entry.path), name=entry.path)

    @property
    def languages(self) -> Tuple[str, ...]:
        return tuple(sorted(self.paloc_entries))

    def equip_type_name(self, row: ItemInfoRow) -> str:
        return self.equip_type_names.get(int(row.equip_type_key or 0), "") if row.equip_type_key else ""

    def socket_item_users(self) -> Mapping[int, int]:
        """`{gem item key: how many shipped rows carry it in their socket list}`.

        Two thirds of the gem catalogue is carried by nothing the game ships, and those
        are the ones with no evidence that an equipment row may hold them at all.
        """

        if self._socket_users is None:
            users: Dict[int, int] = {}
            for key, row in self.rows.items():
                if int(key) in DEFAULT_ITEM_KEY_RANGE:
                    continue
                for item in row.socket_items:
                    users[int(item)] = users.get(int(item), 0) + 1
            self._socket_users = users
        return self._socket_users

    def item_names(self) -> Mapping[int, str]:
        """`{item key: internal name}`, the inverse of `keys_by_name`, built once.

        The studio's stat grid names price columns by the money item; it asked for this
        map on every grid build, and it builds the grid on every validation.
        """

        if self._item_names is None:
            self._item_names = {int(key): row.string_key for key, row in self.rows.items()}
        return self._item_names

    def status_value_ranges(self) -> Mapping[int, Tuple[int, int, int, int]]:
        """`{status key: (entries, low, median, high)}` over shipped equipment rows.

        What the game's own ladders carry for a stat is the only measure of a sane value
        for it: `AttackSpeedRate` runs 30,000,000 to 90,000,000 across the five shipped
        rows that carry it, so a 1,000 written into that column is three orders of
        magnitude out. Rows in the studio's own key range are left out, since an item the
        studio wrote is not evidence of what the game ships. The whole corpus measures in
        about a fiftieth of a second and the answer is kept.
        """

        if self._status_ranges is None:
            from statistics import median

            values: Dict[int, List[int]] = {}
            for key, row in self.rows.items():
                if int(key) in DEFAULT_ITEM_KEY_RANGE or not self.equip_type_name(row):
                    continue
                for level in row.enchant_levels:
                    for stat in level.stats:
                        values.setdefault(int(stat.status_key), []).append(int(stat.value))
            self._status_ranges = {
                key: (len(numbers), min(numbers), int(median(numbers)), max(numbers))
                for key, numbers in values.items()
                if numbers
            }
        return self._status_ranges


def _entry_moved_on_disk(entry: ArchiveEntry) -> str:
    """How the archive's index now describes `entry`, when that differs from the entry
    itself; an empty string when it agrees or cannot be read."""

    try:
        from cdmw.core.archive_format import parse_archive_pamt

        wanted = str(entry.path).replace("\\", "/").strip("/").lower()
        for candidate in parse_archive_pamt(Path(entry.pamt_path)):
            if str(candidate.path).replace("\\", "/").strip("/").lower() != wanted:
                continue
            if int(candidate.offset) == int(entry.offset) and int(candidate.comp_size) == int(entry.comp_size):
                return ""
            return (
                f"the archive now holds it at offset {int(candidate.offset):,} over {int(candidate.comp_size):,} bytes, "
                f"the workbench read it at {int(entry.offset):,} over {int(entry.comp_size):,}"
            )
        return "the archive no longer lists it at all"
    except Exception:  # noqa: BLE001 - the original error is the one that matters
        return ""


# --------------------------------------------------------------------------- building


def _default_reader(entry: ArchiveEntry) -> bytes:
    return read_archive_entry_data(entry)[0]


def _table_pair(entries: Mapping[str, ArchiveEntry], read: ReadEntry, stem: str) -> TablePair:
    payload_path = f"{TABLE_DIR}/{stem}.pabgb"
    header_path = f"{TABLE_DIR}/{stem}.pabgh"
    payload_entry = entries.get(payload_path)
    header_entry = entries.get(header_path)
    if payload_entry is None or header_entry is None:
        raise NewItemSnapshotError(f"the archives have no {stem}.pabgb/.pabgh pair")
    return TablePair(payload_entry, header_entry, bytes(read(payload_entry)), bytes(read(header_entry)))


def _parse_names_by_key(pair: TablePair) -> Mapping[int, str]:
    """4-byte-key tables that put `u32 len` at +4 and the name at +8 (EquipTypeInfo)."""

    table = parse_pabgh_table(pair.header, payload=pair.payload)
    names: Dict[int, str] = {}
    for row, start, end in table.row_spans(len(pair.payload)):
        if end - start < 8:
            continue
        length = struct.unpack_from("<I", pair.payload, start + 4)[0]
        raw = pair.payload[start + 8:start + 8 + length].split(b"\x00", 1)[0]
        names[row.row_id] = raw.decode("utf-8", "replace")
    return names


def build_snapshot(
    entries: Iterable[ArchiveEntry],
    *,
    read_entry: Optional[ReadEntry] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
    entries_by_normalized_path: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    entries_by_basename: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
    entries_by_extension: Optional[Mapping[str, Sequence[ArchiveEntry]]] = None,
) -> NewItemSnapshot:
    """Read and parse every table a new item touches. Seconds of work; run it off the UI thread."""

    read = read_entry or _default_reader
    by_path: Dict[str, ArchiveEntry] = {}
    if entries_by_normalized_path:
        # Archive Browser already paid to normalize and group the complete listing.
        # Reusing that published index avoids normalizing every path again when the
        # studio opens; retain the first mounted answer, matching the old setdefault.
        by_path = {
            str(path): candidates[0]
            for path, candidates in entries_by_normalized_path.items()
            if candidates
        }
    else:
        for entry in entries:
            by_path.setdefault(str(entry.path).replace("\\", "/").strip("/").lower(), entry)
    if not by_path:
        raise NewItemSnapshotError("no archive entries were given")

    def log(message: str) -> None:
        if on_log is not None:
            on_log(message)

    raise_if_cancelled(stop_event, "New item snapshot cancelled.")
    log("Reading ItemInfo...")
    iteminfo = _table_pair(by_path, read, "iteminfo")
    table = parse_pabgh_table(iteminfo.header, payload=iteminfo.payload)
    spans = table.row_spans(len(iteminfo.payload))
    keys = {row.row_id for row, _s, _e in spans}
    rows: Dict[int, ItemInfoRow] = {}
    for row, start, end in spans:
        try:
            rows[row.row_id] = parse_iteminfo_row(iteminfo.payload[start:end], item_keys=keys)
        except ItemInfoRowError:
            continue
    keys_by_name = {row.string_key: key for key, row in rows.items()}

    raise_if_cancelled(stop_event, "New item snapshot cancelled.")
    log("Reading StringInfo and the part-prefab table...")
    stringinfo = _table_pair(by_path, read, "stringinfo")
    texts = stringinfo_index(parse_stringinfo(stringinfo.payload, stringinfo.header, name="stringinfo"))
    pappt_entry = by_path.get(PAPPT_PATH)
    if pappt_entry is None:
        raise NewItemSnapshotError(f"the archives have no {PAPPT_PATH}")
    pappt = parse_pappt(bytes(read(pappt_entry)), name=PAPPT_PATH)

    raise_if_cancelled(stop_event, "New item snapshot cancelled.")
    log("Reading StoreInfo, ItemGroupInfo, StatusInfo and EquipTypeInfo...")
    storeinfo = _table_pair(by_path, read, "storeinfo")
    try:
        stores = parse_store_table(storeinfo.payload, storeinfo.header)
    except StoreInfoError as exc:
        raise NewItemSnapshotError(f"StoreInfo did not decode: {exc}") from exc
    itemgroupinfo = _table_pair(by_path, read, "itemgroupinfo")
    item_groups = parse_item_group_table(itemgroupinfo.payload, itemgroupinfo.header)
    statusinfo = _table_pair(by_path, read, "statusinfo")
    status_names = parse_status_names(statusinfo.payload, statusinfo.header)
    equiptypeinfo = _table_pair(by_path, read, "equiptypeinfo")
    equip_type_names = _parse_names_by_key(equiptypeinfo)
    multichange: Optional[TablePair] = None
    multichange_rows: Dict[int, MultiChangeRow] = {}
    if f"{TABLE_DIR}/multichangeinfo.pabgb" in by_path and f"{TABLE_DIR}/multichangeinfo.pabgh" in by_path:
        multichange = _table_pair(by_path, read, "multichangeinfo")
        multichange_rows = {row.key: row for row in parse_multichange_table(multichange.payload, multichange.header)}

    raise_if_cancelled(stop_event, "New item snapshot cancelled.")
    log("Reading the English localisation table...")
    paloc_entries: Dict[str, ArchiveEntry] = {}
    paloc_candidates = (
        entries_by_extension.get(".paloc", ())
        if entries_by_extension
        else by_path.values()
    )
    for entry in paloc_candidates:
        path = str(entry.path).replace("\\", "/").strip("/").lower()
        if path.startswith(PALOC_DIR + "/") and path.endswith(".paloc"):
            language = language_of_paloc_path(path)
            if language:
                paloc_entries[language] = entry
    english_entry = paloc_entries.get("eng")
    if english_entry is None:
        raise NewItemSnapshotError("the archives have no English localisation table")
    english = parse_paloc(bytes(read(english_entry)), name=english_entry.path)

    model_candidates = entries_by_extension.get(".pac", ()) if entries_by_extension else by_path.values()
    model_paths = (
        str(entry.path).replace("\\", "/").strip("/").lower()
        for entry in model_candidates
    )
    model_stems = frozenset(
        path[len(MODEL_ROOT):].rsplit("/", 1)[-1][:-4]
        for path in model_paths
        if path.startswith(MODEL_ROOT) and path.endswith(".pac")
    )
    effect_candidates = entries_by_extension.get(".pae", ()) if entries_by_extension else by_path.values()
    effect_paths = (
        str(entry.path).replace("\\", "/").strip("/").lower()
        for entry in effect_candidates
    )
    effect_stems = frozenset(
        path[len(EFFECT_DIR):-4]
        for path in effect_paths
        if path.startswith(EFFECT_DIR) and path.endswith(".pae") and "/" not in path[len(EFFECT_DIR):]
    )
    pathc: Optional[PathcTable] = None
    pathc_path = Path(iteminfo.payload_entry.pamt_path).parent.parent / PATHC_RELATIVE_PATH
    if pathc_path.is_file():
        log("Reading the texture registry (meta/0.pathc)...")
        try:
            pathc = parse_pathc(pathc_path.read_bytes())
        except PathcError as exc:
            log(f"The texture registry did not decode; new icons will not be registered: {exc}")
    snapshot = NewItemSnapshot(
        entries=by_path,
        read_entry=read,
        iteminfo=iteminfo,
        rows=rows,
        keys_by_name=keys_by_name,
        stringinfo=stringinfo,
        stringinfo_texts=texts,
        pappt_entry=pappt_entry,
        pappt=pappt,
        storeinfo=storeinfo,
        stores=stores,
        itemgroupinfo=itemgroupinfo,
        item_groups=item_groups,
        status_names=status_names,
        equip_type_names=equip_type_names,
        multichange=multichange,
        multichange_rows=multichange_rows,
        paloc_entries=paloc_entries,
        english=english,
        model_stems=model_stems,
        pathc=pathc,
        effect_stems=effect_stems,
        _index_maps=(entries_by_normalized_path, entries_by_basename)
        if entries_by_normalized_path and entries_by_basename
        else None,
    )
    # Measured here rather than the first time a stat is offered. The measure itself is
    # 17 ms over the corpus; the import it needs is 1.5 s, because an import made after
    # PySide is loaded goes through shiboken's feature hook and that reads the source of
    # every module it touches. Paid on the first template chosen, that was a window that
    # stopped answering; paid here it is a fiftieth of the read that is already happening.
    snapshot.status_value_ranges()
    log(f"Snapshot ready: {len(rows):,} items, {len(stores):,} stores, {len(item_groups):,} item groups, {len(paloc_entries)} languages.")
    return snapshot


# --------------------------------------------------------------------------- context


def template_facts(snapshot: NewItemSnapshot, template_key: int) -> TemplateFacts:
    """What the validator needs to know about one template item."""

    row = snapshot.row(template_key)
    model_stem = ""
    owned: Tuple[str, ...] = ()
    try:
        family = snapshot.family(template_key)
        model_stem, owned = family.model_stem, family.owned_stems
    except ItemModelFamilyError:
        pass
    levels = tuple(
        TemplateLevelFacts(
            level=level.level,
            status_keys=tuple(stat.status_key for stat in level.stats),
            buy_price_items=tuple(price.item_key for price in level.buy_prices),
        )
        for level in row.enchant_levels
    )
    return TemplateFacts(
        key=row.key,
        internal_name=row.string_key,
        equip_type_name=snapshot.equip_type_name(row),
        item_type=row.item_type,
        has_description=row.desc_offset is not None,
        has_stat_block=row.stat_block_offset is not None,
        model_stem=model_stem,
        owned_stems=owned,
        levels=levels,
        price_items=tuple(price.item_key for price in row.price_list),
        max_stack_count=int(row.max_stack_count),
        item_group_keys=tuple(group.key for group in groups_containing(snapshot.item_groups, row.key)),
        socket_items=tuple(row.socket_items),
    )


def build_context(snapshot: NewItemSnapshot, template_key: int) -> NewItemContext:
    """The domain's read-only view for validating a spec against `template_key`.

    Built once per template and kept on the snapshot. The snapshot is read-only, and
    everything here but the template facts is a frozenset over the whole of it: every
    item key and name, every StringInfo text, every part-prefab stem, every English
    localisation key, every store's stock. The studio validates the draft on every edit
    and used to rebuild all of that each time.
    """

    key = int(template_key)
    cached = snapshot._contexts.get(key)
    if cached is not None:
        return cached
    stock_names: Dict[str, FrozenSet[str]] = {}
    for store in snapshot.stores:
        names = set()
        for entry in store.entries:
            row = snapshot.rows.get(entry.item_key)
            if row is not None:
                names.add(row.string_key)
        stock_names[store.name] = frozenset(names)
    context = NewItemContext(
        template=template_facts(snapshot, key),
        item_keys=frozenset(snapshot.rows),
        internal_names=frozenset(snapshot.keys_by_name),
        stringinfo_texts=frozenset(snapshot.stringinfo_texts.values()),
        pappt_stems=frozenset(snapshot.pappt.index()),
        model_stems=snapshot.model_stems,
        store_names=frozenset(store.name for store in snapshot.stores),
        store_stock_names=stock_names,
        localization_keys=frozenset(entry.key for entry in snapshot.english.entries),
        status_keys=frozenset(snapshot.status_names),
        item_group_keys=frozenset(group.key for group in snapshot.item_groups),
        socket_item_keys=snapshot.socket_item_keys,
        effect_stems=snapshot.effect_stems,
        store_insert_supported=True,
        stat_shape_edits_supported=True,
    )
    snapshot._contexts[key] = context
    return context


__all__ = [
    "EFFECT_DIR",
    "EFFECT_DONOR_PATH",
    "EFFECT_DONOR_PREFAB",
    "PALOC_DIR",
    "PAPPT_PATH",
    "TABLE_DIR",
    "NewItemSnapshot",
    "NewItemSnapshotError",
    "TablePair",
    "build_context",
    "build_snapshot",
    "template_facts",
]
