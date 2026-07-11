from __future__ import annotations

"""Incremental history-list updates for the Texture Editor."""

from typing import Mapping, Sequence

from PySide6.QtWidgets import QListWidget, QListWidgetItem

from cdmw.ui.texture_workflow.editor_history_state import texture_editor_history_list_item_text


def append_texture_editor_history_list_record(
    history_list: QListWidget,
    snapshots: Sequence[Mapping[str, object]],
    history_index: int,
    previous_count: int,
    previous_index: int,
) -> bool:
    """Append one row without rebuilding the list; return false if out of sync."""

    if history_list.count() != previous_count:
        return False
    history_list.blockSignals(True)
    while history_list.count() > previous_index + 1:
        history_list.takeItem(history_list.count() - 1)
    evicted_count = max(0, previous_index + 2 - len(snapshots))
    for _index in range(evicted_count):
        history_list.takeItem(0)
    if 0 <= history_index - 1 < history_list.count():
        previous = snapshots[history_index - 1]["entry"]
        history_list.item(history_index - 1).setText(
            texture_editor_history_list_item_text(previous.label, current=False)  # type: ignore[union-attr]
        )
    entry = snapshots[history_index]["entry"]
    item = QListWidgetItem(
        texture_editor_history_list_item_text(entry.label, current=True)  # type: ignore[union-attr]
    )
    history_list.addItem(item)
    history_list.setCurrentRow(history_index)
    history_list.blockSignals(False)
    return True


__all__ = ["append_texture_editor_history_list_record"]
