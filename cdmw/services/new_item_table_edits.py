"""Game table edits inside a Create New Item plan.

The spec's `table_edits` change values in existing rows of other game tables (skills,
characters, drop sets and so on). They are applied after the item steps on the table bytes
the plan already holds, so an edit to a table the new item also changes (a drop set that
gains the item as a reward) stacks on that change. Edits reach DMM mod folders only: an
item package records its own item, not changes to unrelated stock rows.
"""

from __future__ import annotations

import threading
from typing import Optional

from cdmw.services.game_table_edits import (
    TableEditError,
    TableEditIndex,
    TableLayer,
    compose_table_edits,
    describe_edit,
    group_edits,
    load_table_index,
)


def _stem(pair) -> str:
    name = pair.payload_entry.path.replace("\\", "/").rsplit("/", 1)[-1]
    return name[: -len(".staticinfobody")] if name.lower().endswith(".staticinfobody") else name


def snapshot_layers(snapshot, table: str, data=None) -> list[TableLayer]:
    """The base and DLC copies of `table` the snapshot read; `data` maps a pair to (body, header)."""

    from cdmw.services.new_item_tables import table_pairs

    layers = []
    for pair in table_pairs(snapshot, table):
        body, header = data(pair) if data is not None else (pair.payload, pair.header)
        layers.append(TableLayer(_stem(pair), bytes(header), bytes(body), pair))
    return layers


def load_snapshot_table_index(snapshot, table: str, *,
                              stop_event: Optional[threading.Event] = None) -> TableEditIndex:
    layers = snapshot_layers(snapshot, table)
    if not layers:
        raise TableEditError(f"The game archives have no {table} table.")
    return load_table_index(table, layers, stop_event=stop_event)


def plan_table_edits(planner) -> None:
    from cdmw.services.new_item_planning import NewItemPlanError

    edits = tuple(getattr(planner.spec, "table_edits", ()) or ())
    if not edits:
        return
    if planner.independent:
        raise NewItemPlanError(
            "Game table edits are written to DMM mod folders only. Clear them on the Game tables tab "
            "to write an item package.")
    try:
        for table, table_edits in group_edits(edits).items():
            layers = snapshot_layers(planner.snapshot, table, planner.table_data)
            composed = compose_table_edits(table, layers, table_edits)
            planner.patch(composed.source.payload_entry, composed.body,
                          f"Game table edits: {len(table_edits)} value(s) in {table}")
            # The row directory is unchanged, but a mod manager reads the pair together.
            planner.patch(composed.source.header_entry, composed.header, f"Game table directory: {table}")
            for edit in table_edits:
                planner.log(describe_edit(edit))
    except TableEditError as exc:
        raise NewItemPlanError(str(exc)) from exc


__all__ = ["load_snapshot_table_index", "plan_table_edits", "snapshot_layers"]
