"""Show exactly what a prefab edit will change, before anything is built.

The inspector previously went straight from "Save changes" to a built payload,
with warnings shown only as a sentence in the status line that nothing stopped
you ignoring. A modder editing game data should see the full list once, in one
place, and should have to acknowledge anything that looks wrong rather than
scroll past it.

Nothing here writes: it is the last read-only step before the payload is built,
and the destination is still chosen afterwards.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)


@dataclass(frozen=True, slots=True)
class ChangeLine:
    """One pending change, as the modder will see it."""

    field: str
    before: str
    after: str
    note: str = ""


class PrefabChangeReview(QDialog):
    """Confirm a set of prefab changes, blocking on unacknowledged warnings."""

    def __init__(
        self,
        changes: Sequence[ChangeLine],
        warnings: Sequence[str],
        *,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review changes")
        self.resize(880, 460)
        self._warnings = tuple(dict.fromkeys(str(item) for item in warnings if item))

        layout = QVBoxLayout(self)
        headline = QLabel(
            f"{len(changes)} change{'' if len(changes) == 1 else 's'} to write into a "
            "separate mod package. Your game files are not touched."
        )
        headline.setWordWrap(True)
        layout.addWidget(headline)

        self.tree = QTreeWidget()
        self.tree.setColumnCount(4)
        self.tree.setHeaderLabels(["What", "Now", "After", "Also"])
        self.tree.setRootIsDecorated(False)
        for change in changes:
            QTreeWidgetItem(self.tree, [change.field, change.before, change.after, change.note])
        for column in range(4):
            self.tree.resizeColumnToContents(column)
        layout.addWidget(self.tree, 1)

        # Retargeting a mesh silently changes its material and physics too,
        # because the engine resolves those from the mesh path rather than from
        # anything the prefab says. Naming them here is the only place a modder
        # finds out before the game does. They are deliberately not copied into
        # the package: they are the game's own files, already installed, and
        # shipping them would add conflicts for no gain.
        self.companion_note: QLabel | None = None
        if any("comes from" in change.note or "will come from" in change.note for change in changes):
            self.companion_note = QLabel(
                "Swapping a model also swaps the material and physics that go with it. "
                "The game finds those by the model's path, so they come from your game "
                "files and are not copied into the package."
            )
            self.companion_note.setWordWrap(True)
            layout.addWidget(self.companion_note)

        self.acknowledge: QCheckBox | None = None
        if self._warnings:
            problems = QLabel(
                "These look wrong:\n  "
                + "\n  ".join(f"- {item}" for item in self._warnings)
            )
            problems.setWordWrap(True)
            layout.addWidget(problems)
            # Blocking, not advisory. A warning you can scroll past is one the
            # tool has decided not to act on.
            self.acknowledge = QCheckBox("Save anyway - I have read the warnings above")
            layout.addWidget(self.acknowledge)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Build the edited file")
        self.buttons.accepted.connect(self.accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)
        self._sync_ok()
        if self.acknowledge is not None:
            self.acknowledge.stateChanged.connect(lambda _state: self._sync_ok())

    def _sync_ok(self) -> None:
        blocked = self.acknowledge is not None and not self.acknowledge.isChecked()
        ok = self.buttons.button(QDialogButtonBox.StandardButton.Ok)
        ok.setEnabled(not blocked)
        ok.setToolTip(
            "Tick the box above to save with unresolved warnings." if blocked else ""
        )


__all__ = ["ChangeLine", "PrefabChangeReview"]
