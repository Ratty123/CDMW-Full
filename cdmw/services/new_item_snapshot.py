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
from typing import Callable, Dict, FrozenSet, Iterable, Mapping, Optional, Tuple

from cdmw.core.archive_extraction import read_archive_entry_data
from cdmw.core.item_model_family import ItemModelFamily, ItemModelFamilyError, discover_item_model_family
from cdmw.core.itemgroupinfo_table import ItemGroupRow, groups_containing, parse_item_group_table
from cdmw.core.iteminfo_row import ItemInfoRow, ItemInfoRowError, parse_iteminfo_row, parse_status_names
from cdmw.core.multichangeinfo_table import MultiChangeRow, parse_multichange_table
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
    _families: Dict[int, ItemModelFamily] = field(default_factory=dict, repr=False)
    _payloads: Dict[str, bytes] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ lookups

    def entry(self, path: str) -> ArchiveEntry:
        key = str(path or "").replace("\\", "/").strip("/").lower()
        entry = self.entries.get(key)
        if entry is None:
            raise NewItemSnapshotError(f"the archives have no entry {path}")
        return entry

    def has_entry(self, path: str) -> bool:
        return str(path or "").replace("\\", "/").strip("/").lower() in self.entries

    def payload(self, path: str) -> bytes:
        """The bytes of an archive entry, read once and kept."""

        key = str(path or "").replace("\\", "/").strip("/").lower()
        cached = self._payloads.get(key)
        if cached is None:
            cached = bytes(self.read_entry(self.entry(path)))
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
) -> NewItemSnapshot:
    """Read and parse every table a new item touches. Seconds of work; run it off the UI thread."""

    read = read_entry or _default_reader
    by_path: Dict[str, ArchiveEntry] = {}
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
    for path, entry in by_path.items():
        if path.startswith(PALOC_DIR + "/") and path.endswith(".paloc"):
            language = language_of_paloc_path(path)
            if language:
                paloc_entries[language] = entry
    english_entry = paloc_entries.get("eng")
    if english_entry is None:
        raise NewItemSnapshotError("the archives have no English localisation table")
    english = parse_paloc(bytes(read(english_entry)), name=english_entry.path)

    model_stems = frozenset(
        path[len(MODEL_ROOT):].rsplit("/", 1)[-1][:-4]
        for path in by_path
        if path.startswith(MODEL_ROOT) and path.endswith(".pac")
    )
    log(f"Snapshot ready: {len(rows):,} items, {len(stores):,} stores, {len(item_groups):,} item groups, {len(paloc_entries)} languages.")
    return NewItemSnapshot(
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
    )


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
    )


def build_context(snapshot: NewItemSnapshot, template_key: int) -> NewItemContext:
    """The domain's read-only view for validating a spec against `template_key`."""

    stock_names: Dict[str, FrozenSet[str]] = {}
    for store in snapshot.stores:
        names = set()
        for entry in store.entries:
            row = snapshot.rows.get(entry.item_key)
            if row is not None:
                names.add(row.string_key)
        stock_names[store.name] = frozenset(names)
    return NewItemContext(
        template=template_facts(snapshot, template_key),
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
        store_insert_supported=True,
        stat_shape_edits_supported=True,
    )


__all__ = [
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
