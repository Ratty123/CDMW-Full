"""Adding and removing objects in the Prefab Inspector.

Every other edit the Inspector makes is *pending*: the row remembers a new value
keyed by byte offset, and nothing is written until Save. Adding or removing an
object cannot work that way. Splicing an element in or out moves every byte
after it, so a pending edit's offset would point at the wrong field by the time
it was applied -- and it would still be a plausible offset, so nothing would
notice.

So a structural change is applied **immediately** to the dialog's working
payload, and the tree is rebuilt from the result. That keeps exactly one set of
offsets alive at a time. It also means the change is real before Save, which is
why the dialog keeps the bytes it opened with: "Undo all changes" has to be able
to put the file back.

Pending edits are refused rather than migrated. Mapping them across a splice is
possible in principle and is not worth the failure mode it would introduce; the
modder is asked to save or undo them first, which takes one click and cannot be
wrong.
"""

from __future__ import annotations

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMessageBox, QTreeWidgetItem

from cdmw.services.prefab_structure_service import (
    decode_prefab_binary,
    duplicate_prefab_element,
    locate_element,
    remove_prefab_element,
)
from cdmw.ui.archive_browser.prefab_inspector_editing import OBJECT_ROLE


class PrefabStructureMixin:
    """Object add/remove for :class:`PrefabInspectorDialog`.

    Expects the host to provide ``tree``, ``_document``, ``_original``,
    ``_opened``, ``_structural_changes``, ``_log``, ``_can_edit``,
    ``_value_edits``, ``collect_replacements`` and ``_refresh_pending_state``.
    """

    # -- what the row is -------------------------------------------------
    def _element_site_for(self, item: QTreeWidgetItem | None):
        """The collection element a row stands for, or ``None``.

        Only object headings carry an offset, and only objects that are
        themselves collection elements match one -- a component nested inside
        another object sits *within* an element without being one, and offering
        to delete it would delete its parent.
        """
        if item is None or self._document is None:
            return None
        offset = item.data(0, OBJECT_ROLE)
        if not isinstance(offset, int):
            return None
        return locate_element(self._document, offset)

    def add_structure_actions(self, menu, item: QTreeWidgetItem) -> None:
        """Add the duplicate/remove entries, when the row supports them."""
        site = self._element_site_for(item)
        if site is None:
            return
        menu.addSeparator()
        label = item.text(0)

        duplicate = QAction("Duplicate this object", menu)
        duplicate.setToolTip(
            "Add a second copy of this object to the prefab, with the same files and "
            "the same placement. Change the copy afterwards to point somewhere else."
        )
        duplicate.triggered.connect(lambda: self._resize_at(site, label, insert=True))
        menu.addAction(duplicate)

        remove = QAction("Remove this object", menu)
        if site.sibling_count <= 1:
            remove.setEnabled(False)
            remove.setToolTip(
                "This is the only object in its list. No shipped prefab has an empty "
                "list, so removing it would produce a file unlike anything the game "
                "loads."
            )
        else:
            remove.setToolTip("Take this object out of the prefab, along with anything inside it.")
        remove.triggered.connect(lambda: self._resize_at(site, label, insert=False))
        menu.addAction(remove)

    # -- doing it --------------------------------------------------------
    def _blocked_by_pending_edits(self) -> bool:
        """Refuse while offset-keyed edits are waiting, and say why."""
        pending = len(self.collect_replacements()) + len(self._value_edits)
        if not pending:
            return False
        QMessageBox.information(
            self,
            "Save or undo your other changes first",
            "Adding or removing an object moves everything after it in the file, which "
            "would put your other unsaved changes on the wrong fields.\n\n"
            "Save them or undo them, then add or remove the object.",
        )
        self._log("Refused: save or undo the pending changes before changing the object list.")
        return True

    def _confirm_removal(self, label: str, site) -> bool:
        answer = QMessageBox.question(
            self,
            "Remove this object?",
            f"Remove {label!r} from this prefab?\n\nAnything nested inside it goes too. "
            "You can undo this with 'Undo all changes' until you save.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return answer == QMessageBox.StandardButton.Yes

    def _resize_at(self, site, label: str, *, insert: bool) -> None:
        if not self._can_edit():
            self._log("Refused: this prefab is not fully readable, so objects cannot be added or removed.")
            return
        if self._blocked_by_pending_edits():
            return
        if not insert and not self._confirm_removal(label, site):
            self._log("Nothing removed: you cancelled.")
            return
        action = duplicate_prefab_element if insert else remove_prefab_element
        try:
            result = action(self._original, site.collection_index, site.element_index)
        except Exception as exc:  # noqa: BLE001 - the refusal is the useful part
            self._log(f"Refused: {exc}")
            QMessageBox.warning(self, "That change was refused", str(exc))
            return
        for line in result.proof_lines:
            self._log(line)
        verb = "Duplicated" if insert else "Removed"
        self._structural_changes.append(
            f"{verb} {label!r} in {result.member_name} "
            f"({result.count_before} -> {result.count_after} objects)"
        )
        self._adopt_payload(
            result.data,
            # Land on the copy, not back at the top. Two rows now read the same,
            # so "which one did I just add" is otherwise unanswerable -- and the
            # copy is the row the modder is about to retarget.
            select_element=(site.collection_index, site.element_index + 1) if insert else None,
        )

    def _select_element_row(self, collection_index: int, element_index: int) -> None:
        """Put the cursor on a collection element, by the offset it now sits at."""
        collections = getattr(self._document, "collections", ())
        if collection_index >= len(collections):
            return
        elements = collections[collection_index].elements
        if element_index >= len(elements):
            return
        wanted = elements[element_index][0]
        for index in range(self.tree.topLevelItemCount()):
            item = self.tree.topLevelItem(index)
            if item.data(0, OBJECT_ROLE) == wanted:
                self.tree.setCurrentItem(item)
                self.tree.scrollToItem(item)
                return

    def _adopt_payload(
        self, data: bytes, *, select_element: tuple[int, int] | None = None
    ) -> None:
        """Take the resized bytes as the working file and rebuild the tree.

        Re-decoding rather than patching the rows is the point: every offset the
        tree holds came from the old bytes, and the only way to be sure none
        survives is to build the rows again from the new ones.
        """
        self._original = bytes(data)
        self._document = decode_prefab_binary(self._original)
        self.tree.clear()
        self._populate_objects()
        self._apply_object_filter()
        if select_element is None:
            self._select_first_editable_row()
        else:
            self._select_element_row(*select_element)
        self._refresh_pending_state()
        self.banner.setText(self._banner_text())
        self.objects_hint.setText(self._objects_hint())

    # -- reporting -------------------------------------------------------
    def structural_summary(self) -> str:
        """One line naming what was added or removed, for the log and Save."""
        if not self._structural_changes:
            return ""
        delta = len(self._original) - len(self._opened)
        movement = "grew" if delta > 0 else "shrank" if delta < 0 else "stayed the same"
        return (
            f"{len(self._structural_changes)} object change(s): "
            + "; ".join(self._structural_changes)
            + f"; file {movement}"
            + (f" by {abs(delta)} byte(s)" if delta else "")
        )

    def revert_structural_changes(self) -> None:
        """Put the object list back to what the file held when it was opened."""
        if not self._structural_changes:
            return
        self._structural_changes.clear()
        self._adopt_payload(self._opened)
        self._log("Put the object list back to what the file holds.")


__all__ = ["PrefabStructureMixin"]
