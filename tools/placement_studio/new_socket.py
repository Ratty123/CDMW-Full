"""The "new attach point" dialog — Tier A2, creating a socket definition.

Creating a definition is the safe half of the pair: a socket nothing references changes nothing in
game, while *referencing* a socket nothing defines is the failure that crashes on load. So this
dialog is deliberately free to create, and the route/retarget paths stay the guarded ones.

It exists to unblock two things the rest of the studio cannot do alone:

* **Aiming a weapon somewhere vanilla never put it.** A one-hand sword defines no back child
  socket, so re-routing it to the back inherits the hip's orientation. Creating a child socket on
  the item gives that placement a frame of its own.
* **Retargeting a draw animation.** A `.paac` socket reference may only be swapped for a name of
  the *same length*, and some chart sockets have no same-length alternative at all —
  `Spine2_B_SubWeapon_Socket` has none of its 25 characters' worth. Creating one is the only way
  through, so the dialog reports name length against a target rather than making the user count.
"""

from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QVBoxLayout,
    QWidget,
)

from .editing import MAX_SOCKET_NAME, socket_name_problem
from .model import Quat, Socket, Vec3


class NewSocketDialog(QDialog):
    """Collects a file, a name, a parent bone and a starting transform."""

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        files: Optional[List[Tuple[str, str]]] = None,
        sockets_by_file: Optional[Dict[str, Dict[str, Socket]]] = None,
        bones: Optional[List[str]] = None,
        preferred_file: str = "",
        copy_from: str = "",
        target_length: int = 0,
        target_length_reason: str = "",
        start_translation: Optional[Vec3] = None,
        preferred_parent: str = "",
        picked_hint: str = "",
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New attach point")
        self._files = list(files or [])
        self._sockets_by_file = dict(sockets_by_file or {})
        self._bones = list(bones or [])
        self._target_length = int(target_length or 0)
        # Where the user clicked, already converted into the parent bone's space.
        self._start_translation = start_translation
        self._preferred_parent = str(preferred_parent or "")
        self._picked_hint = str(picked_hint or "")

        self._file_box = QComboBox()
        for label, path in self._files:
            self._file_box.addItem(label, path)
        if preferred_file:
            position = self._file_box.findData(preferred_file)
            if position >= 0:
                self._file_box.setCurrentIndex(position)
        self._file_box.currentIndexChanged.connect(self._on_file_changed)

        self._name_edit = QLineEdit()
        self._name_edit.setPlaceholderText("Spine2_B_Back_ChildSocket")
        self._name_edit.textChanged.connect(self._revalidate)

        self._length_label = QLabel()
        self._length_label.setWordWrap(True)

        # Starting from an existing socket matters more than it looks: a socket created at the
        # origin sits at the character's feet, which reads as "the tool did nothing".
        self._copy_box = QComboBox()
        self._copy_box.currentIndexChanged.connect(self._on_copy_changed)

        # Editable, because the right parent for a child socket is a bone on the *item*
        # (`B_Weapon_0001`), which is not in the character rig at all.
        self._bone_box = QComboBox()
        self._bone_box.setEditable(True)

        self._problem = QLabel()
        self._problem.setWordWrap(True)
        self._problem.setStyleSheet("color: #e25858;")

        form = QFormLayout()
        form.addRow("Define in:", self._file_box)
        form.addRow("Name:", self._name_edit)
        form.addRow("", self._length_label)
        form.addRow("Copy transform from:", self._copy_box)
        form.addRow("Parent bone:", self._bone_box)

        self._buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        self._buttons.button(QDialogButtonBox.Ok).setText("Create")
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "A new socket changes nothing on its own — route a part to it, or retarget an "
            "animation to it, once it exists."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        layout.addLayout(form)
        if target_length and target_length_reason:
            note = QLabel(target_length_reason)
            note.setWordWrap(True)
            note.setStyleSheet("color: #8a95a8;")
            layout.addWidget(note)
        layout.addWidget(self._problem)
        layout.addWidget(self._buttons)

        self._on_file_changed(self._file_box.currentIndex())
        if copy_from:
            position = self._copy_box.findData(copy_from)
            if position >= 0:
                self._copy_box.setCurrentIndex(position)
        self._revalidate()

    # ── state ───────────────────────────────────────────────────────

    @property
    def game_path(self) -> str:
        return str(self._file_box.currentData() or "")

    @property
    def socket_name(self) -> str:
        return self._name_edit.text().strip()

    def _current_sockets(self) -> Dict[str, Socket]:
        return self._sockets_by_file.get(self.game_path, {})

    def _on_file_changed(self, _index: int) -> None:
        """Offer only sockets from the chosen file — a transform is meaningful per file."""

        previous = self._copy_box.currentData()
        self._copy_box.blockSignals(True)
        self._copy_box.clear()
        self._copy_box.addItem("(identity — at the parent bone)", "")
        for name in sorted(self._current_sockets()):
            self._copy_box.addItem(name, name)
        if previous:
            position = self._copy_box.findData(previous)
            if position >= 0:
                self._copy_box.setCurrentIndex(position)
        self._copy_box.blockSignals(False)

        # Parents this file already uses come first: for an item file that is the one right
        # answer (`B_Weapon_0001`), and for a body file it is the subset that actually carries
        # sockets. The full rig follows for the body case.
        used = sorted({s.parent_bone for s in self._current_sockets().values() if s.parent_bone})
        self._bone_box.blockSignals(True)
        self._bone_box.clear()
        for bone in used:
            self._bone_box.addItem(bone, bone)
        for bone in self._bones:
            if bone not in used:
                self._bone_box.addItem(bone, bone)
        self._bone_box.addItem("(none — world space)", "")
        self._bone_box.blockSignals(False)

        self._on_copy_changed(self._copy_box.currentIndex())
        self._revalidate()

    def _on_copy_changed(self, _index: int) -> None:
        source = self._current_sockets().get(str(self._copy_box.currentData() or ""))
        if source is None:
            return
        # Follow the source's parent bone too: copying a transform without its frame of
        # reference produces a socket that is nowhere near where it was copied from.
        position = self._bone_box.findData(source.parent_bone)
        if position >= 0:
            self._bone_box.setCurrentIndex(position)
        else:
            self._bone_box.setEditText(source.parent_bone)

    def socket(self) -> Socket:
        """The socket to create, transform copied from the chosen source."""

        source = self._current_sockets().get(str(self._copy_box.currentData() or ""))
        bone = str(self._bone_box.currentData() or self._bone_box.currentText().strip())
        if bone.startswith("("):
            bone = ""
        return Socket(
            name=self.socket_name,
            parent_bone=bone,
            rotation=source.rotation if source is not None else Quat(),
            translation=(
                self._start_translation
                if self._start_translation is not None
                else (source.translation if source is not None else Vec3())
            ),
        )

    # ── validation ──────────────────────────────────────────────────

    def _revalidate(self) -> None:
        name = self.socket_name
        problem = socket_name_problem(name) if name else ""
        if not problem and name in self._current_sockets():
            problem = f"{name} is already defined in this file"
        self._problem.setText(problem)

        length = len(name)
        if self._target_length:
            fits = "matches" if length == self._target_length else "does not match"
            self._length_label.setText(
                f"{length} of {MAX_SOCKET_NAME} characters — {fits} the "
                f"{self._target_length} needed to retarget an animation"
            )
            self._length_label.setStyleSheet(
                "color: #78dc8c;" if length == self._target_length else "color: #8a95a8;"
            )
        else:
            self._length_label.setText(f"{length} of {MAX_SOCKET_NAME} characters")
            self._length_label.setStyleSheet("color: #8a95a8;")

        self._buttons.button(QDialogButtonBox.Ok).setEnabled(bool(name) and not problem)


def keyboard_hint() -> str:
    """Shown in the button tooltip; kept here so the wording lives with the dialog."""

    return (
        "Creating one changes nothing by itself — nothing moves until you send an item to it "
        "or point an animation at it."
    )
