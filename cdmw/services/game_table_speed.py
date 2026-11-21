"""Game table speed rows for Speed Tuning (experimental).

AI movement speeds (`aimovespeedinfo`: each row's `_aiMoveSpeedDataList` entries) and the
pushed-object speed rate (`gimmickinfo._pushObjectSpeedRate`). Both are float32 values whose
width holds on every shipped row (checked 2026-11-20); they are edited through Edit Game
Table Values like any other editable field. None of them has been tested in game.
"""

from __future__ import annotations

import math
import struct
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

from cdmw.core.static_table_records import TableFieldEdit
from cdmw.services.game_table_edits import TableEditError, archive_table_layers, load_table_index, table_label

SPEED_TABLES = ("aimovespeedinfo", "gimmickinfo")
SPEED_FIELDS = frozenset({"_pushObjectSpeedRate", "_targetMoveSpeed", "_minMoveSpeed", "_maxRotationSpeed"})
BULK_MIN_FACTOR, BULK_MAX_FACTOR = 0.01, 100.0
#: What "multiply on every matching row" offers: choice -> (table, the fields scaled together).
SPEED_CHOICES = {
    "move": ("aimovespeedinfo", ("_targetMoveSpeed", "_minMoveSpeed")),
    "turn": ("aimovespeedinfo", ("_maxRotationSpeed",)),
    "push": ("gimmickinfo", ("_pushObjectSpeedRate",)),
}
SPEED_CHOICE_LABELS = {
    "move": "Move and minimum speed",
    "turn": "Turn speed",
    "push": "Pushed object speed rate",
}


def _field(target) -> str:
    return target if isinstance(target, str) else str(target[-1])


def speed_rows_from_index(index) -> list[dict[str, object]]:
    rows = []
    for row in index.rows:
        values = [value for value in row.values if _field(value.target) in SPEED_FIELDS]
        if not values:
            continue
        rows.append({"table": index.table, "table_label": table_label(index.table), "key": row.key, "name": row.name,
                     "editable": row.editable, "values": [
                         {"target": value.target if isinstance(value.target, str) else list(value.target),
                          "label": value.label, "value": value.value, "minimum": value.rule.minimum,
                          "maximum": value.rule.maximum, "note": value.rule.note} for value in values]})
    return rows


def speed_table_rows(
    game_root: Path | str,
    *,
    table: str = "",
    scan: Optional[Callable[[Path], Iterable[object]]] = None,
    stop_event: Optional[threading.Event] = None,
) -> list[dict[str, object]]:
    """Every speed row of the chosen speed table, or of both."""

    rows: list[dict[str, object]] = []
    for kind in (table,) if table else SPEED_TABLES:
        if kind not in SPEED_TABLES:
            raise ValueError(f"{kind} is not a speed table; use {', '.join(SPEED_TABLES)}.")
        layers = archive_table_layers(game_root, kind, scan=scan, stop_event=stop_event)
        rows += speed_rows_from_index(load_table_index(kind, layers, stop_event=stop_event))
    # gimmickinfo has 14,218 rows, nearly all at 1; only rows away from the shipped default lead.
    return rows


def export_speed_table_mod(
    game_root: Path | str,
    edits: Iterable[object],
    *,
    parent: Path | str,
    title: str,
    scan: Optional[Callable[[Path], Iterable[object]]] = None,
    on_log: Optional[Callable[[str], None]] = None,
    stop_event: Optional[threading.Event] = None,
):
    """Write speed field edits (TableFieldEdit rows) as a DMM mod, as Edit Game Table Values does."""

    from cdmw.services.game_table_edits import (
        TableEditError,
        compose_table_edits,
        composed_files,
        group_edits,
        write_table_edit_mod,
    )

    edits = list(edits)
    if not edits:
        raise TableEditError("There are no speed edits to write.")
    for item in edits:
        field = item.target if isinstance(item.target, str) else str(item.target[-1])
        if item.table not in SPEED_TABLES or field not in SPEED_FIELDS:
            raise TableEditError(f"{item.table} {field} is not a game table speed field.")
    if not str(title or "").strip():
        raise TableEditError("Name the mod before writing it.")
    files = {}
    for table, table_edits in group_edits(edits).items():
        layers = archive_table_layers(game_root, table, scan=scan, stop_event=stop_event)
        files.update(composed_files(compose_table_edits(table, layers, table_edits)))
    return write_table_edit_mod(files, parent=Path(parent), title=str(title).strip(), edits=edits,
                                game_root=Path(game_root) if game_root else None, on_log=on_log, stop_event=stop_event)


# --- one factor on every matching row -----------------------------------------------------


@dataclass(frozen=True, slots=True)
class BulkSpeedEdits:
    """One speed value multiplied on every matching row; values that cannot take it are counted."""

    edits: tuple[TableFieldEdit, ...]
    #: (table, key, target) whose result is the game's own value: a change to them is taken back.
    restore: tuple[tuple, ...]
    #: (table, key, target) -> "row name (key)", and -> the class that owns a nested value.
    labels: Mapping[tuple, str]
    owners: Mapping[tuple, str]
    matched: int          # rows the text matches that hold the chosen value
    rows: int             # rows that got at least one edit
    dlc_only: int         # rows only in the DLC copy, which a DMM mod cannot change
    outside_range: int    # values the game holds outside their range, such as -1
    result_outside: int   # values whose result would leave their range


def matching_rows(index, query: str = "") -> tuple:
    """The rows a filter text matches (part of the name, or the exact key); no limit."""

    needle = str(query or "").strip().casefold()
    return tuple(row for row in index.rows
                 if not needle or needle in row.name.casefold() or needle == str(row.key))


def speed_choices(table: str) -> tuple[tuple[str, str], ...]:
    """(choice, label) for the values of `table` that can be multiplied on many rows."""

    return tuple((choice, SPEED_CHOICE_LABELS[choice]) for choice, (owner, _fields) in SPEED_CHOICES.items()
                 if owner == table)


def _same_float32(left: float, right: float) -> bool:
    try:
        return struct.pack("<f", left) == struct.pack("<f", right)
    except (OverflowError, struct.error):
        return False


def _choice_fields(index, choice: str) -> tuple[str, ...]:
    if choice not in SPEED_CHOICES:
        raise TableEditError(f"Unknown speed value {choice!r}; use one of {', '.join(SPEED_CHOICES)}.")
    table, fields = SPEED_CHOICES[choice]
    if table != index.table:
        raise TableEditError(f"{SPEED_CHOICE_LABELS[choice]} is a value of the {table_label(table)} table, "
                             f"not of {table_label(index.table)}.")
    return fields


def speed_row_count(index, choice: str, query: str = "") -> int:
    """How many matching rows hold the chosen value."""

    fields = _choice_fields(index, choice)
    return sum(1 for row in matching_rows(index, query)
               if any(_field(value.target) in fields for value in row.values))


def scale_speed_rows(index, *, choice: str, factor: float, query: str = "") -> BulkSpeedEdits:
    """Multiply the chosen speed value by `factor` on every row `query` matches.

    The game's value is multiplied (the index holds it), so asking twice does not stack and
    a factor of 1 takes the changes back. A value outside its range, or whose result would
    leave it, is left as it is and counted, never clamped. Move speed and minimum move speed
    of one entry change together or not at all. Nothing is written.
    """

    fields = _choice_fields(index, choice)
    if isinstance(factor, bool) or not isinstance(factor, (int, float)) or not math.isfinite(float(factor)) \
            or not BULK_MIN_FACTOR <= float(factor) <= BULK_MAX_FACTOR:
        raise TableEditError(f"The factor must be between {BULK_MIN_FACTOR:g} and {BULK_MAX_FACTOR:g}.")
    factor = float(factor)
    edits: list[TableFieldEdit] = []
    restore: list[tuple] = []
    labels: dict[tuple, str] = {}
    owners: dict[tuple, str] = {}
    matched = rows = dlc_only = outside_range = result_outside = 0
    for row in matching_rows(index, query):
        groups: dict[object, list] = {}
        for value in row.values:
            if _field(value.target) in fields:
                # The values of one list entry share everything but the field name.
                groups.setdefault(value.target if isinstance(value.target, str) else tuple(value.target[:-1]),
                                  []).append(value)
        if not groups:
            continue
        matched += 1
        if not row.editable:
            dlc_only += 1
            continue
        changed = False
        for values in groups.values():
            results = []
            for value in values:
                current = float(value.value)
                if not value.rule.minimum <= current <= value.rule.maximum:
                    outside_range += 1
                    continue
                result = round(current * factor, 6)
                if not value.rule.minimum <= result <= value.rule.maximum:
                    result_outside += 1
                    continue
                results.append((value, current, result))
            if len(results) != len(values):
                continue  # one value of the entry cannot be scaled: the entry stays whole
            for value, current, result in results:
                key = (index.table, row.key, value.target)
                if _same_float32(current, result):
                    restore.append(key)
                    continue
                edits.append(TableFieldEdit(index.table, row.key, value.target, result))
                labels[key] = f"{row.name} ({row.key})"
                owners[key] = getattr(value, "owner", "") or ""
                changed = True
        rows += changed
    return BulkSpeedEdits(tuple(edits), tuple(restore), labels, owners, matched, rows, dlc_only, outside_range,
                          result_outside)


def scaled_speed_table_edits(
    game_root: Path | str,
    *,
    choice: str,
    factor: float,
    query: str = "",
    scan: Optional[Callable[[Path], Iterable[object]]] = None,
    stop_event: Optional[threading.Event] = None,
) -> BulkSpeedEdits:
    """`scale_speed_rows` on the table read from the game folder, for callers without the page."""

    if choice not in SPEED_CHOICES:
        raise TableEditError(f"Unknown speed value {choice!r}; use one of {', '.join(SPEED_CHOICES)}.")
    table = SPEED_CHOICES[choice][0]
    layers = archive_table_layers(game_root, table, scan=scan, stop_event=stop_event)
    return scale_speed_rows(load_table_index(table, layers, stop_event=stop_event), choice=choice, factor=factor,
                            query=query)


def bulk_message(result: BulkSpeedEdits) -> str:
    """One line on what a multiply did, for the page and the tools."""

    if result.edits:
        text = f"{len(result.edits):,} values in {result.rows:,} rows added to Changes in this mod."
    elif result.restore:
        text = f"{len(result.restore):,} values are back at the game's value."
    elif not result.matched:
        text = "No matching row holds this value."
    else:
        text = "No value was changed."
    left = []
    if result.dlc_only:
        left.append(f"{result.dlc_only:,} rows only in the DLC copy")
    if result.outside_range:
        left.append(f"{result.outside_range:,} values outside their range (such as -1)")
    if result.result_outside:
        left.append(f"{result.result_outside:,} results outside the allowed range")
    return text + (" Left as they are: " + ", ".join(left) + "." if left else "")


__all__ = ["BULK_MAX_FACTOR", "BULK_MIN_FACTOR", "BulkSpeedEdits", "SPEED_CHOICES", "SPEED_CHOICE_LABELS",
           "SPEED_FIELDS", "SPEED_TABLES", "bulk_message", "export_speed_table_mod", "matching_rows",
           "scale_speed_rows", "scaled_speed_table_edits", "speed_choices", "speed_row_count",
           "speed_rows_from_index", "speed_table_rows"]
