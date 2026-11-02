"""Game table field edits: editable row views, composed base tables and DMM mod folders.

`static_table_records` owns the closed record reads and the in-place byte edits. This
module works on a table's layers (the base copy and any `.dlc_NN` copy that replaces
rows): it lists the rows a user can edit, composes requested edits into the base copy,
and writes the result as a DMM mod folder. DMM merges rows from a mod's base-table copy
and ignores a mod's DLC-table copy, so a row whose effective copy is in the DLC layer is
handled by putting the DLC's version of the row, edited, into the base copy; a row only
the DLC has is refused.
"""

from __future__ import annotations

import json
import tempfile
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional, Sequence

from cdmw.core.static_table_records import (
    EDITABLE_FIELDS,
    EDITABLE_MEMBERS,
    FieldRule,
    StaticTableError,
    TableFieldEdit,
    apply_field_edits,
    decode_static_table,
    editable_kinds,
    table_kind_for_stem,
)
from cdmw.domain.cancellation import raise_if_cancelled

STATIC_TABLE_ROOT = "gamedata/binarystaticinfo__/bin/"
DMM_ARCHIVE_GROUP = "0036"
CDMW_GENERATOR = "Crimson Desert Mod Workbench"
GENERATOR = f"{CDMW_GENERATOR} - game table editor"

TABLE_LABELS = {
    "characterinfo": "Characters and NPCs",
    "dropsetinfo": "Drop sets (loot)",
    "gameplayvariableinfo": "Gameplay switches",
    "inventory": "Inventories and bags",
    "mercenaryinfo": "Mercenaries and pets",
    "skill": "Skills",
    "wantedinfo": "Bounties",
}
FIELD_LABELS = {
    "_defaultSlotCount": "Starting slots",
    "_maxSlotCount": "Maximum slots",
    "_maxLevel": "Maximum level",
    "_cooltime": "Cooldown (raw)",
    "_allowSkillWithLowResource": "Usable with low resource",
    "_increasePrice": "Bounty increase",
    "_defaultLimitHireCount": "Hire limit",
    "_maxLimitHireCount": "Hire limit ceiling",
    "_defaultLimitSummonCount": "Summon limit",
    "_characterScale": "Model scale",
    "_callMercenaryCoolTime": "Companion call cooldown (raw)",
    "_initialVariable": "Starts switched on",
    "_percent": "drop chance",
    "_minValue": "minimum quantity",
    "_maxValue": "maximum quantity",
    "_deadDropPercent": "drop chance on death",
    "_throwDropPercent": "drop chance when thrown",
    "_experience": "experience",
}
MEMBER_GROUPS = {
    "DropInfoData": "Drop",
    "CharacterEquipmentData": "Equipment",
    "CharacterLevelData": "Level",
}


class TableEditError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class TableLayer:
    """One copy of a table: `stem` is `skill` for the base copy, `skill.dlc_01` for a DLC copy."""

    stem: str
    header: bytes
    body: bytes
    source: object = None  # the archive entry pair or snapshot pair it came from

    @property
    def is_base(self) -> bool:
        return "." not in self.stem


@dataclass(frozen=True, slots=True)
class EditableValue:
    target: str | tuple
    label: str
    value: object
    rule: FieldRule
    owner: str = ""


@dataclass(frozen=True, slots=True)
class EditableRow:
    key: int
    name: str
    layer: str
    values: tuple[EditableValue, ...]
    #: The base copy also has this row, so an edit can reach DMM even when a DLC copy supplies it.
    in_base: bool = True

    @property
    def editable(self) -> bool:
        return self.in_base


@dataclass(frozen=True, slots=True)
class TableEditIndex:
    table: str
    rows: tuple[EditableRow, ...]
    refused: int


def table_label(table: str) -> str:
    return TABLE_LABELS.get(table, table)


def target_label(target: str | tuple, owner: str = "") -> str:
    """`Maximum slots`, or `Drop 3: drop chance` for the third entry of a drop list."""

    if isinstance(target, str):
        return FIELD_LABELS.get(target, target)
    indexes = [part for part in target if isinstance(part, int)]
    group = MEMBER_GROUPS.get(owner, owner or "Entry")
    position = " ".join(str(index + 1) for index in indexes)
    return f"{group} {position}: {FIELD_LABELS.get(target[-1], target[-1])}".replace("  ", " ")


def _value_of(rule: FieldRule, raw: int):
    if rule.kind == "float32":
        import struct
        return round(struct.unpack("<f", int(raw).to_bytes(4, "little"))[0], 6)
    return int(raw)


def load_table_index(table: str, layers: Sequence[TableLayer], *,
                     stop_event: Optional[threading.Event] = None) -> TableEditIndex:
    """Every row of `table` with its editable values, taken from the copy the game reads."""

    if table not in editable_kinds():
        raise TableEditError(f"{table_label(table)} has no editable fields.")
    rows: dict[int, EditableRow] = {}
    refused = 0
    base_keys: set[int] = set()
    for layer in sorted(layers, key=lambda item: (not item.is_base, item.stem)):
        raise_if_cancelled(stop_event, "Table loading cancelled.")
        decoded = decode_static_table(table, layer.header, layer.body)
        refused += len(decoded.refused)
        top = EDITABLE_FIELDS.get(table, {})
        for record in decoded.records:
            values = [EditableValue(field.name, target_label(field.name), _value_of(top[field.name], field.value),
                                    top[field.name])
                      for field in record.fields if field.name in top and isinstance(field.value, int)]
            values.extend(EditableValue(member.target, target_label(member.target, member.owner),
                                        _value_of(member.rule, member.value), member.rule, member.owner)
                          for member in record.members)
            if layer.is_base:
                base_keys.add(record.key)
            rows[record.key] = EditableRow(record.key, record.name, layer.stem, tuple(values), record.key in base_keys)
    ordered = tuple(sorted(rows.values(), key=lambda row: (row.name.casefold(), row.key)))
    return TableEditIndex(table, ordered, refused)


def compose_table_edits(table: str, layers: Sequence[TableLayer], edits: Iterable[TableFieldEdit]) -> TableLayer:
    """The base copy of `table` with `edits` applied.

    A row the base copy supplies is edited in place. A row a DLC copy replaces is edited
    in the DLC's version and that whole row is put in the base copy: DMM turns a changed
    base row into a whole-row edit of the DLC's row, so starting from the base version
    would drop what the DLC changed there. A row only a DLC copy has cannot reach DMM.
    """

    from cdmw.core.structured_binary_editor import parse_pabgh_table, replace_table_row

    edits = [edit for edit in edits if edit.table == table]
    if not edits:
        raise TableEditError(f"There are no edits for {table_label(table)}.")
    base = [layer for layer in layers if layer.is_base]
    if len(base) != 1:
        raise TableEditError(f"{table_label(table)} needs exactly one base table copy; found {len(base)}.")
    base = base[0]
    base_keys = {row.row_id for row in parse_pabgh_table(base.header, payload=base.body).rows}
    supplier: dict[int, TableLayer] = {}
    for layer in sorted((item for item in layers if not item.is_base), key=lambda item: item.stem):
        for row in parse_pabgh_table(layer.header, payload=layer.body).rows:
            supplier[row.row_id] = layer
    in_base: dict[tuple, object] = {}
    by_dlc: dict[str, dict[tuple, object]] = {}
    for edit in edits:
        layer = supplier.get(edit.key)
        if layer is None:
            in_base[(edit.key, edit.target)] = edit.value
        elif edit.key not in base_keys:
            raise TableEditError(
                f"{table_label(table)} row {edit.key} exists only in the DLC copy of the table, and DMM does not "
                "take a mod's copy of a DLC table.")
        else:
            by_dlc.setdefault(layer.stem, {})[(edit.key, edit.target)] = edit.value
    header, body = base.header, base.body
    try:
        if in_base:
            result = apply_field_edits(table, header, body, in_base)
            header, body = result.header, result.body
        for stem, values in by_dlc.items():
            layer = next(item for item in layers if item.stem == stem)
            edited = apply_field_edits(table, layer.header, layer.body, values)
            directory = parse_pabgh_table(edited.header, payload=edited.body)
            spans = {row.row_id: (start, end) for row, start, end in directory.row_spans(len(edited.body))}
            for key in sorted({key for key, _target in values}):
                start, end = spans[key]
                body, header = replace_table_row(body, header, key, edited.body[start:end])
    except (StaticTableError, ValueError) as exc:
        raise TableEditError(str(exc)) from exc
    return TableLayer(base.stem, header, body, base.source)


def group_edits(edits: Iterable[TableFieldEdit]) -> dict[str, list[TableFieldEdit]]:
    grouped: dict[str, list[TableFieldEdit]] = {}
    for edit in edits:
        if table_kind_for_stem(edit.table) != edit.table:
            raise TableEditError(f"{edit.table} is not an editable table name.")
        grouped.setdefault(edit.table, []).append(edit)
    return grouped


def describe_edit(edit: TableFieldEdit, owner: str = "") -> str:
    return f"{table_label(edit.table)} row {edit.key}, {target_label(edit.target, owner)} = {edit.value}"


def archive_table_layers(
    game_root: Path | str,
    table: str,
    *,
    scan: Optional[Callable[[Path], Iterable[object]]] = None,
    read: Optional[Callable[[object], bytes]] = None,
    stop_event: Optional[threading.Event] = None,
) -> list[TableLayer]:
    """The base and DLC copies of `table` in the game folder, chosen by the item-data rules.

    `source` on each layer is its `(header_entry, body_entry)` pair.
    """

    from cdmw.core.item_sources import resolve_item_data_sources

    text = str(game_root or "").strip()
    if not text or not Path(text).is_dir():
        raise TableEditError("Set the game folder in Archive Browser before editing game tables.")
    if scan is None:
        from cdmw.core.archive_scan_cache import scan_archive_entries as scan
    if read is None:
        from cdmw.core.archive_extraction import read_archive_entry_data
        read = lambda entry: read_archive_entry_data(entry, stop_event=stop_event)[0]  # noqa: E731
    raise_if_cancelled(stop_event, "Reading the game archives was cancelled.")
    entries = [entry for entry in scan(Path(text))
               if str(entry.path).replace("\\", "/").lower().startswith(STATIC_TABLE_ROOT)]
    sources = resolve_item_data_sources(entries, read_entry=read)
    layers = []
    for stem in sorted(sources.tables):
        if stem != table and not stem.startswith(table + "."):
            continue
        body_entry, header_entry = sources.tables[stem]
        raise_if_cancelled(stop_event, "Reading the game archives was cancelled.")
        layers.append(TableLayer(stem, bytes(read(header_entry)), bytes(read(body_entry)), (header_entry, body_entry)))
    if not layers:
        raise TableEditError(f"The game archives have no {table} table.")
    return layers


def composed_files(layer: TableLayer) -> dict[str, tuple[object, bytes]]:
    """The edited pair as {game path: (archive entry, bytes)} for `write_table_edit_mod`."""

    header_entry, body_entry = layer.source
    return {str(body_entry.path).replace("\\", "/"): (body_entry, layer.body),
            str(header_entry.path).replace("\\", "/"): (header_entry, layer.header)}


@dataclass(frozen=True, slots=True)
class TableModResult:
    folder: Path
    replaced: bool
    title: str
    paths: tuple[str, ...]


def mod_destination(parent: Path, title: str) -> tuple[Path, bool]:
    """The mod folder for `title`; an existing folder is replaced only when this editor wrote it."""

    from cdmw.domain.packages.layout import sanitize_mod_package_folder_name

    folder = Path(parent) / sanitize_mod_package_folder_name(title)
    if not folder.exists():
        return folder, False
    try:
        manifest = json.loads((folder / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        manifest = None
    if isinstance(manifest, dict) and manifest.get("generator") == GENERATOR:
        return folder, True
    raise TableEditError(f"A folder named {folder.name} already exists and the game table editor did not write it. "
                         "Choose another mod name.")


def _staging_parent(folder: Path) -> Path:
    above = folder.parent.parent
    if above != folder.parent and above.drive.lower() == folder.parent.drive.lower():
        try:
            probe = Path(tempfile.mkdtemp(prefix=".cdmw-probe-", dir=above))
        except OSError:
            return folder.parent
        probe.rmdir()
        return above
    return folder.parent


def write_table_edit_mod(
    composed: Mapping[str, tuple[object, bytes]],
    *,
    parent: Path,
    title: str,
    edits: Sequence[TableFieldEdit],
    game_root: Optional[Path] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
) -> TableModResult:
    """Write `composed` ({game path: (archive entry, bytes)}) as a DMM mod folder under `parent`.

    Only the edited base table bodies are written; their row directories are unchanged.
    The archive is read back before the folder is published.
    """

    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.core.archive_format import parse_archive_pamt
    from cdmw.core.atomic_file import atomic_publish_directory
    from cdmw.domain.archives.mutation import ArchivePatchRequest
    from cdmw.services.archive_overlay_package_service import export_archive_overlay_package

    title = str(title or "").strip()
    if not title:
        raise TableEditError("Name the mod before writing it.")
    if not composed:
        raise TableEditError("There are no table edits to write.")
    folder, replaced = mod_destination(parent, title)
    requests = [ArchivePatchRequest(entry, bytes(data)) for entry, data in composed.values()]
    folder.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".cdmw-tables-", dir=_staging_parent(folder)) as staging:
        stage = Path(staging) / folder.name
        stage.mkdir()
        shared = export_archive_overlay_package(requests, package_root=stage, group=DMM_ARCHIVE_GROUP,
                                                game_root=game_root, on_log=on_log, stop_event=stop_event)
        wanted = {path.lower(): bytes(data) for path, (_entry, data) in composed.items()}
        packaged = parse_archive_pamt(stage / shared.group / "0.pamt")
        if len(packaged) != len(wanted) or any(
                read_archive_entry_data(item)[0] != wanted.get(item.path.replace("\\", "/").lower())
                for item in packaged):
            raise TableEditError("The written mod archive does not read back as the edited tables.")
        lines = [describe_edit(edit) for edit in edits]
        description = f"{len(lines)} game table value(s) changed."
        manifest = {
            "format": "v1", "schema_version": 1, "kind": "archive_override_mod", "name": title, "title": title,
            "game": "Crimson Desert", "target_game": shared.target_game, "version": "1.0", "author": "",
            "description": description, "generator": GENERATOR, "files_dir": ".", "manager_targets": ["dmm"],
            "structure": "archive_group", "archive_group": shared.group, "file_count": shared.file_count,
            "overrides": list(shared.paths),
            "table_edits": [{"table": edit.table, "key": int(edit.key),
                             "target": edit.target if isinstance(edit.target, str) else list(edit.target),
                             "value": edit.value} for edit in edits],
        }
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (stage / "modinfo.json").write_text(json.dumps(
            {"name": title, "title": title, "version": "1.0", "author": "", "description": description},
            indent=2) + "\n", encoding="utf-8")
        (stage / "README.txt").write_text(
            f"{title}\n\n{description}\n\n" + "".join(f"  {line}\n" for line in lines) +
            "\nAdd this folder in DMM and enable it there. These values have not been confirmed in game; "
            "disable the mod in DMM to undo it. The game's own files were only read.\n", encoding="utf-8")
        raise_if_cancelled(stop_event, "Table mod export cancelled.")
        mod_destination(parent, title)
        atomic_publish_directory(stage, folder, replace_existing=True)
    return TableModResult(folder, replaced, title, tuple(shared.paths))


__all__ = [
    "DMM_ARCHIVE_GROUP",
    "EditableRow",
    "EditableValue",
    "GENERATOR",
    "STATIC_TABLE_ROOT",
    "TABLE_LABELS",
    "TableEditError",
    "TableEditIndex",
    "TableLayer",
    "TableModResult",
    "archive_table_layers",
    "composed_files",
    "compose_table_edits",
    "describe_edit",
    "group_edits",
    "load_table_index",
    "mod_destination",
    "table_label",
    "target_label",
    "write_table_edit_mod",
]
