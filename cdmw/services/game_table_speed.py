"""Game table speed rows for Speed Tuning (experimental).

AI movement speeds (`aimovespeedinfo`: each row's `_aiMoveSpeedDataList` entries) and the
pushed-object speed rate (`gimmickinfo._pushObjectSpeedRate`). Both are float32 values whose
width holds on every shipped row (checked 2026-11-20); they are edited through Edit Game
Table Values like any other editable field. None of them has been tested in game.
"""

from __future__ import annotations

import threading
from pathlib import Path
from typing import Callable, Iterable, Optional

from cdmw.services.game_table_edits import archive_table_layers, load_table_index, table_label

SPEED_TABLES = ("aimovespeedinfo", "gimmickinfo")
SPEED_FIELDS = frozenset({"_pushObjectSpeedRate", "_targetMoveSpeed", "_minMoveSpeed", "_maxRotationSpeed"})


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


__all__ = ["SPEED_FIELDS", "SPEED_TABLES", "export_speed_table_mod", "speed_rows_from_index", "speed_table_rows"]
