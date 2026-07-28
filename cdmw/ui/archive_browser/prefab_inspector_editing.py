"""Editing behaviour for the Prefab Inspector, kept out of the dialog shell.

The dialog itself is a tree, a schema tab and some buttons. What a change
*means* -- which rows move together, what the modder is about to write -- lives
here so neither file has to hold both.
"""

from __future__ import annotations

from dataclasses import replace

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTreeWidgetItem

from cdmw.domain.archives.prefab_values import (
    Placement,
    describe_value,
    encode_value,
    editable_kind,
    read_placement,
    write_placement,
)
from cdmw.domain.archives.prefab_glossary import describe_field
from cdmw.ui.archive_browser.prefab_inspector_review import ChangeLine


# Item-data roles live here rather than in the dialog, because the mixin needs
# them and the dialog imports the mixin -- the other direction would be a cycle.
EDIT_ROLE = Qt.ItemDataRole.UserRole + 1
USED_ROLE = Qt.ItemDataRole.UserRole + 2
PLACEMENT_ROLE = Qt.ItemDataRole.UserRole + 3
#: Byte offset of the string a row shows, so an edit names one occurrence
#: rather than every copy of the same path in the file.
OFFSET_ROLE = Qt.ItemDataRole.UserRole + 4
#: (offset, type, raw, member) for a non-transform value whose declared type
#: and byte width agree, so an editor can be offered for it.
VALUE_ROLE = Qt.ItemDataRole.UserRole + 5
#: Byte offset of an object's group, on the heading row for that object. It is
#: what turns "this row" into "this collection element" when the modder asks to
#: duplicate or remove one; rows without it are fields, not objects.
OBJECT_ROLE = Qt.ItemDataRole.UserRole + 6

CHANGED_COLOUR = QColor("#7ec8ff")
WARNING_COLOUR = QColor("#ffb86b")


class PrefabEditingMixin:
    """Change tracking for :class:`PrefabInspectorDialog`.

    Expects the host to provide ``tree``, ``_value_edits``, ``_log``,
    ``_warning_for``, ``_companion_notes`` and the item-data roles.
    """

    def _sync_twin_placements(
        self, edited: QTreeWidgetItem, was: Placement, now: Placement
    ) -> None:
        """Move the object's other transform to match, when they were identical.

        Objects carry ``_worldTransform`` and ``_tiledTransform`` as a pair, and
        in all 5,228 shipped objects that have both, the two hold the same
        scale, rotation and position. Moving one and not the other leaves a
        combination the game's own data never contains, and the tree collapses
        the duplicate to "same as ...", so the second one is not even visible to
        correct by hand.
        """
        parent = edited.parent()
        if parent is None:
            return
        for index in range(parent.childCount()):
            sibling = parent.child(index)
            stored = sibling.data(0, PLACEMENT_ROLE)
            if sibling is edited or not stored:
                continue
            offset, type_name, original_raw, _name = stored
            pending = self._value_edits.get(offset)
            current = read_placement(pending[1] if pending else original_raw)
            if current is None or current != was:
                continue
            # Keep each copy's own tile index; only TiledTransform carries one.
            twin = write_placement(replace(now, tile=current.tile))
            if twin == original_raw:
                self._value_edits.pop(offset, None)
            else:
                self._value_edits[offset] = (original_raw, twin)
            sibling.setText(2, describe_value(type_name, twin))
            sibling.setForeground(
                2, QBrush(CHANGED_COLOUR) if offset in self._value_edits else QBrush()
            )
            self._log(
                f"Moved {describe_field(_name).label.lower()} to match: the two are "
                "identical in every shipped object that carries both."
            )


    def _pending_changes(self) -> tuple[list[ChangeLine], list[str]]:
        """Everything the modder is about to write, with anything that looks wrong.

        Built by walking the tree so each line carries the label the modder saw,
        not the declared member name.
        """
        lines: list[ChangeLine] = []
        warnings: list[str] = []
        counts: dict[str, int] = {}
        # Structural changes are already in the working payload rather than
        # pending on a row, so the tree walk below cannot find them -- but they
        # are the largest thing the modder is about to write, so they lead.
        for description in getattr(self, "_structural_changes", ()):
            lines.append(ChangeLine(field="Object list", before="", after=description))
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, EDIT_ROLE)
                if isinstance(original, str):
                    counts[original] = counts.get(original, 0) + 1
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                original = child.data(2, EDIT_ROLE)
                current = child.text(2).strip()
                if isinstance(original, str) and current and current != original:
                    note = ""
                    others = counts.get(original, 1) - 1
                    if others:
                        # The edit is addressed by offset, so the copies stay
                        # put. Say so; the opposite is what a modder expects.
                        note = f"{_count(others, 'other row')} still points at the old file"
                    # Every companion, not just the first. Retargeting a mesh
                    # does not carry its material and physics along -- the new
                    # mesh's own apply -- so what the modder is really choosing
                    # is a set of three files, and only one of them is on screen.
                    companions = self._companion_notes(current)
                    if companions:
                        note = (note + "; " if note else "") + "; ".join(companions)
                    lines.append(
                        ChangeLine(field=child.text(0), before=original, after=current, note=note)
                    )
                    problem = self._warning_for(original, current)
                    if problem:
                        warnings.append(f"{child.text(0)}: {problem}")
                stored = child.data(0, PLACEMENT_ROLE) or child.data(0, VALUE_ROLE)
                if stored:
                    offset, type_name, original_raw, _member = stored
                    pending = self._value_edits.get(offset)
                    if pending:
                        lines.append(
                            ChangeLine(
                                field=child.text(0),
                                before=describe_value(type_name, pending[0]),
                                after=describe_value(type_name, pending[1]),
                            )
                        )
        return lines, warnings


    def _edit_value_row(self, item: QTreeWidgetItem, column: int) -> None:
        """Double-click dispatch: transforms and plain values differ."""
        if item.data(0, PLACEMENT_ROLE):
            self._edit_placement(item, column)
        elif item.data(0, VALUE_ROLE):
            self._edit_number(item, column)

    def _edit_number(self, item: QTreeWidgetItem, _column: int) -> None:
        """Edit one non-transform value in place; nothing moves."""
        from cdmw.ui.archive_browser.prefab_inspector_widgets import ValueEditDialog

        stored = item.data(0, VALUE_ROLE)
        if not stored:
            return
        offset, type_name, original_raw, member_name = stored
        pending = self._value_edits.get(offset)
        current = pending[1] if pending else original_raw
        meaning = describe_field(member_name)
        editor = ValueEditDialog(
            type_name,
            current,
            title=meaning.label,
            detail=meaning.detail,
            parent=self,
        )
        if not editor.exec() or editor.result_raw is None:
            return
        new_raw = editor.result_raw
        if new_raw == original_raw:
            self._value_edits.pop(offset, None)
        else:
            self._value_edits[offset] = (original_raw, new_raw)
        item.setText(2, describe_value(type_name, new_raw))
        item.setForeground(
            2, QBrush(CHANGED_COLOUR) if offset in self._value_edits else QBrush()
        )
        self._refresh_pending_state()

    def row_has_pending_change(self, item: QTreeWidgetItem) -> bool:
        """Is there something on this row to undo?"""
        original = item.data(2, EDIT_ROLE)
        if isinstance(original, str) and item.text(2).strip() != original:
            return True
        stored = item.data(0, PLACEMENT_ROLE) or item.data(0, VALUE_ROLE)
        return bool(stored) and stored[0] in self._value_edits

    def _revert_row(self, item: QTreeWidgetItem) -> None:
        """Put one row back, leaving every other edit alone.

        "Undo all changes" was the only way back, so one mistyped path cost the
        whole session's work -- which pushes people towards keeping a bad edit
        rather than losing eight good ones.
        """
        reverted = False
        original = item.data(2, EDIT_ROLE)
        if isinstance(original, str) and item.text(2).strip() != original:
            item.setText(2, original)
            reverted = True

        stored = item.data(0, PLACEMENT_ROLE) or item.data(0, VALUE_ROLE)
        if stored and stored[0] in self._value_edits:
            offset, type_name, original_raw, _member = stored
            self._value_edits.pop(offset, None)
            item.setText(2, describe_value(type_name, original_raw))
            item.setForeground(2, QBrush())
            reverted = True
            # A transform and its twin were moved together, so they come back
            # together; leaving one edited would recreate exactly the mismatch
            # the pairing exists to prevent.
            if item.data(0, PLACEMENT_ROLE):
                self._revert_twin_of(item, read_placement(original_raw))
        if reverted:
            self._log(f"Put {item.text(0)} back to the value in the file.")
            self._refresh_pending_state()

    def _revert_twin_of(self, edited: QTreeWidgetItem, was: Placement | None) -> None:
        parent = edited.parent()
        if parent is None or was is None:
            return
        for index in range(parent.childCount()):
            sibling = parent.child(index)
            stored = sibling.data(0, PLACEMENT_ROLE)
            if sibling is edited or not stored or stored[0] not in self._value_edits:
                continue
            offset, type_name, original_raw, _name = stored
            if read_placement(original_raw) != was:
                continue
            self._value_edits.pop(offset, None)
            sibling.setText(2, describe_value(type_name, original_raw))
            sibling.setForeground(2, QBrush())

    def _row_is_changeable(self, item: QTreeWidgetItem) -> bool:
        from PySide6.QtCore import Qt

        return bool(
            item.flags() & Qt.ItemFlag.ItemIsEditable
            or item.data(0, PLACEMENT_ROLE)
            or item.data(0, VALUE_ROLE)
        )

    def _apply_object_filter(self) -> None:
        """Narrow the tree to matching rows, keeping their objects visible.

        A row is worthless without knowing which object it belongs to, so a
        parent stays on screen whenever any of its children match -- and a
        parent that matches on its own name keeps all of its rows.
        """
        needle = self.object_filter.text().strip().lower()
        changeable_only = self.changeable_only_box.isChecked()
        shown = 0
        for index in range(self.tree.topLevelItemCount()):
            parent = self.tree.topLevelItem(index)
            parent_matches = not needle or any(
                needle in parent.text(column).lower() for column in range(3)
            )
            visible_children = 0
            for child_index in range(parent.childCount()):
                child = parent.child(child_index)
                matches = parent_matches or any(
                    needle in child.text(column).lower() for column in range(3)
                )
                if changeable_only and not self._row_is_changeable(child):
                    matches = False
                child.setHidden(not matches)
                visible_children += int(matches)
            parent.setHidden(visible_children == 0 and not (parent_matches and not changeable_only))
            shown += visible_children
        if not needle and not changeable_only:
            self.match_count.setText("")
            return
        self.match_count.setText(
            "Nothing matches." if not shown else f"Showing {shown:,} row(s)."
        )
