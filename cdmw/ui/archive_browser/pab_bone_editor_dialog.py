"""Add Bones dialog: append child bones to a .pab skeleton with live feedback."""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, replace
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSignalBlocker, Qt, Signal
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QSplitter,
    QStackedWidget,
    QTreeWidget,
    QTreeWidgetItem,
    QVBoxLayout,
    QWidget,
)

from cdmw.modding.skeleton_writer import (
    PabDocument,
    PabEditRefused,
    _invert_affine,
    append_child_bone,
    read_pab_document,
)
from cdmw.services.pab_skeleton_edit_service import (
    PAB_CHAIN_DIRECTIONS,
    PabAppendEdit,
    PabEditJsonError,
    dumps_pab_edit_json,
    euler_degrees_to_quaternion,
    plan_bone_chain,
    quaternion_to_euler_degrees,
    read_pab_edit_json,
)

_SELECTED_COLOUR = QColor("#ff9f1c")
_DIRECTIONS = ("down", "back", "forward", "left", "right", "up")


@dataclass
class AddedBoneRow:
    """One bone the user is adding, with its rotation kept as editable angles.

    A row reopened from an edit keeps that edit's exact quaternion until its angles
    change, so accepting unchanged bones returns the same definitions: two items
    that share a bone must define it bit for bit alike.
    """

    parent: str
    name: str
    position: tuple[float, float, float] = (0.0, 0.0, 0.0)
    angles: tuple[float, float, float] = (0.0, 0.0, 0.0)
    scale: tuple[float, float, float] = (1.0, 1.0, 1.0)
    core_flag: int = 0
    #: the reopened edit's quaternion and the angles shown for it
    exact_rotation: tuple[float, float, float, float] | None = None
    exact_angles: tuple[float, float, float] | None = None

    def edit(self) -> PabAppendEdit:
        rotation = (self.exact_rotation if self.exact_rotation is not None and self.angles == self.exact_angles
                    else euler_degrees_to_quaternion(*self.angles))
        return PabAppendEdit(self.parent, self.name, position=self.position, rotation=rotation,
                             scale=self.scale, core_flag=self.core_flag)

    @classmethod
    def from_edit(cls, edit: PabAppendEdit) -> AddedBoneRow:
        angles = quaternion_to_euler_degrees(edit.rotation)
        return cls(edit.parent, edit.name, tuple(edit.position), angles, tuple(edit.scale), edit.core_flag,
                   tuple(edit.rotation), angles)


#: Common attach points, each with the bone names that serve it on shipped rigs.
_QUICK_PICKS = (
    ("upper_back", ("Bip01 Spine2", "Bip01 Spine3", "Bip01 Spine1", "Bip01 Spine")),
    ("neck", ("Bip01 Neck",)),
    ("head", ("Bip01 Head",)),
    ("hips", ("Bip01 Pelvis",)),
    ("left_shoulder", ("Bip01 L Clavicle",)),
    ("right_shoulder", ("Bip01 R Clavicle",)),
)


def body_bone_names(document: PabDocument) -> set[str]:
    """Bones under the rig's largest root. The other roots are markers.

    Shipped rigs keep root-motion, IK and climb targets (``B_TL_*``,
    ``B_MoveControl_01``) as separate roots at the feet or the origin. They do not
    move with the body, so a cape or hair bone under one stays behind.
    """
    bones = document.bones
    roots = [index for index, bone in enumerate(bones) if bone.parent_index < 0]
    if not roots:
        return set()

    def root_of(index: int) -> int:
        while bones[index].parent_index >= 0:
            index = bones[index].parent_index
        return index

    owner = [root_of(index) for index in range(len(bones))]
    body_root = max(roots, key=owner.count)
    return {bone.name for bone, root in zip(bones, owner) if root == body_root}


def _bone_name_stem(text: str) -> str:
    """An item name reduced to a short bone-name prefix (ASCII letters, digits, underscores)."""
    stem = "".join(character if character.isascii() and (character.isalnum() or character == "_") else "_"
                   for character in str(text or "").strip()).strip("_")
    return stem[:24]


def _valid_bone_name(name: str) -> bool:
    return name.isascii() and 1 <= len(name) <= 255 and all(0x20 <= ord(character) <= 0x7E for character in name)


def _to_character(position, parent_matrix) -> tuple[float, float, float]:
    """A parent-space offset expressed along the character's axes (row-vector bind matrix)."""
    return tuple(sum(position[k] * parent_matrix[k * 4 + column] for k in range(3)) for column in range(3))


def _to_parent(offset, parent_matrix) -> tuple[float, float, float]:
    inverse = _invert_affine(parent_matrix)
    return tuple(sum(offset[k] * inverse[k * 4 + column] for k in range(3)) for column in range(3))


def build_added_bones(source: PabDocument, rows: list[AddedBoneRow]) -> tuple[PabDocument, str]:
    """Apply rows in order; return the skeleton so far and the first refusal, if any."""
    document = source
    for number, row in enumerate(rows, 1):
        edit = row.edit()
        try:
            document = append_child_bone(document, edit.parent, edit.name, position=edit.position,
                                         rotation=edit.rotation, scale=edit.scale)
        except PabEditRefused as exc:
            return document, f"Added bone {number} ({row.name or 'unnamed'}): {exc}"
    return document, ""


class SkeletonSketch(QWidget):
    """Front and side outlines of a skeleton; added bones and the selection stand out."""

    boneClicked = Signal(str)
    #: (title, projection) per panel. Front is seen from in front of the character
    #: (its left on the viewer's right); side from its left, facing right on screen.
    PANELS = (("Front", lambda x, y, z: (x, -y)), ("Side", lambda x, y, z: (-z, -y)))

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("PabBoneEditorSketch")
        self.setMinimumSize(420, 320)
        self._document: PabDocument | None = None
        self._added: set[str] = set()
        self._selected = ""
        self._joints: list[tuple[str, QPointF]] = []

    def set_skeleton(self, document: PabDocument, added: set[str], selected: str) -> None:
        self._document, self._added, self._selected = document, set(added), selected
        self.update()

    def paintEvent(self, _event) -> None:
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        palette = self.palette()
        painter.fillRect(self.rect(), palette.base())
        self._joints = []
        document = self._document
        if document is None or not document.bones:
            return
        positions = [bone.bind_matrix[12:15] for bone in document.bones]
        projected = [[project(*position) for position in positions] for _title, project in self.PANELS]
        span = max(max(max(p[0] for p in panel) - min(p[0] for p in panel),
                       max(p[1] for p in panel) - min(p[1] for p in panel)) for panel in projected)
        span = max(span, 1e-3)
        margin, header = 16.0, 22.0
        panel_width = self.width() / len(self.PANELS)
        scale = min(panel_width - 2 * margin, self.height() - 2 * margin - header) / span
        shipped = QColor(palette.text().color())
        shipped.setAlpha(110)
        added_colour = QColor(palette.highlight().color())
        for panel_index, ((title, _project), points) in enumerate(zip(self.PANELS, projected)):
            left = panel_index * panel_width
            xs, ys = [p[0] for p in points], [p[1] for p in points]
            centre_x, centre_y = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
            screen = [QPointF(left + panel_width / 2 + (x - centre_x) * scale,
                              header + (self.height() - header) / 2 + (y - centre_y) * scale) for x, y in points]
            for index, bone in enumerate(document.bones):
                if bone.parent_index < 0:
                    continue
                is_added = bone.name in self._added
                colour = _SELECTED_COLOUR if bone.name == self._selected else added_colour if is_added else shipped
                painter.setPen(QPen(colour, 3.0 if is_added or bone.name == self._selected else 1.0))
                painter.drawLine(screen[bone.parent_index], screen[index])
            for index, bone in enumerate(document.bones):
                self._joints.append((bone.name, screen[index]))
                if bone.name in self._added or bone.name == self._selected:
                    painter.setPen(Qt.NoPen)
                    painter.setBrush(_SELECTED_COLOUR if bone.name == self._selected else added_colour)
                    radius = 5.0 if bone.name == self._selected else 3.5
                    painter.drawEllipse(screen[index], radius, radius)
            painter.setPen(palette.text().color())
            painter.drawText(QRectF(left + 8, 4, panel_width - 16, header - 4), Qt.AlignLeft,
                             "Front view" if title == "Front" else "Side view")
            if panel_index:
                painter.setPen(QPen(shipped, 1.0))
                painter.drawLine(QPointF(left, 0), QPointF(left, self.height()))

    def mousePressEvent(self, event) -> None:
        position = event.position() if hasattr(event, "position") else QPointF(event.pos())
        best, best_distance = "", 12.0
        for name, point in self._joints:
            distance = math.hypot(point.x() - position.x(), point.y() - position.y())
            if distance < best_distance or (distance == best_distance and name in self._added):
                best, best_distance = name, distance
        if best:
            self.boneClicked.emit(best)


class PabBoneEditorDialog(QDialog):
    """Pick a bone, add children or a chain, and save the skeleton as a mod."""

    def __init__(self, data: bytes, virtual_path: str, parent: QWidget | None = None,
                 *, draft_directory: Path | None = None, initial_edits: Sequence[PabAppendEdit] = (),
                 accept_text: str = "", accept_tooltip: str = "", name_stem: str = "") -> None:
        """``initial_edits`` reopens bones added earlier. A caller other than the
        Archive Browser passes its own (already translated) accept label and tooltip;
        ``edits()`` then returns the rows to apply to ``data``. ``name_stem`` (an item
        name, say) starts default bone names, so two items that each add a default
        chain to one shared skeleton do not pick the same names."""
        super().__init__(parent)
        self.setObjectName("PabBoneEditorDialog")
        self._data = bytes(data)
        self._path = virtual_path
        self._draft_directory = draft_directory
        self._source = read_pab_document(self._data, virtual_path)
        self._rows: list[AddedBoneRow] = [AddedBoneRow.from_edit(edit) for edit in initial_edits]
        self._accept_text, self._accept_tooltip = accept_text, accept_tooltip
        self._name_stem = _bone_name_stem(name_stem)
        self._preview = self._source
        self._error = ""
        self._selected = (self._rows[-1].name if self._rows
                          else self._source.bones[0].name if self._source.bones else "")
        self._loading_form = False
        self._body = body_bone_names(self._source)
        stem = Path(virtual_path.replace("\\", "/")).name or "skeleton"
        self.setWindowTitle(f"Add Bones - {stem}")
        self.setWindowFlags(self.windowFlags() | Qt.WindowMaximizeButtonHint)
        self.setSizeGripEnabled(True)
        self.resize(1100, 700)
        self._build()
        self._rebuild_tree()
        self._refresh()

    # Layout ---------------------------------------------------------------
    def _build(self) -> None:
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        steps = QHBoxLayout()
        self.step_labels = [QLabel(self.tr("1. Choose where the new bones attach"), self),
                            QLabel(self.tr("2. Add a child bone or a chain"), self),
                            QLabel(self.tr("3. Adjust them, then save"), self)]
        for label in self.step_labels:
            label.setObjectName("PabBoneEditorStep")
            steps.addWidget(label)
            steps.addSpacing(18)
        steps.addStretch(1)
        layout.addLayout(steps)
        intro = QLabel(
            "Add child bones for capes, long hair or tails. Pick a bone, then add a child bone or a chain. "
            "The game's own bones stay as they are, so existing meshes, animations and sockets keep working.")
        intro.setObjectName("HintLabel")
        intro.setWordWrap(True)
        layout.addWidget(intro)

        splitter = QSplitter(Qt.Horizontal, self)
        layout.addWidget(splitter, 1)

        left = QWidget(splitter)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        picks = QHBoxLayout()
        picks.addWidget(QLabel("Quick pick:", left))
        labels = {"upper_back": self.tr("Upper back"), "neck": self.tr("Neck"), "head": self.tr("Head"),
                  "hips": self.tr("Hips"), "left_shoulder": self.tr("Left shoulder"),
                  "right_shoulder": self.tr("Right shoulder")}
        self.quick_pick_buttons: dict[str, QPushButton] = {}
        names = {bone.name for bone in self._source.bones}
        for key, candidates in _QUICK_PICKS:
            target = next((name for name in candidates if name in names), "")
            if not target:
                continue
            button = QPushButton(labels[key], left)
            button.setToolTip(f"Select {target}.")
            button.clicked.connect(lambda _checked=False, name=target: self._select_bone(name))
            self.quick_pick_buttons[key] = button
            picks.addWidget(button)
        picks.addStretch(1)
        if self.quick_pick_buttons:
            left_layout.addLayout(picks)
        self.search_edit = QLineEdit(left)
        self.search_edit.setPlaceholderText("Find a bone...")
        self.search_edit.setClearButtonEnabled(True)
        self.search_edit.textChanged.connect(self._apply_search)
        left_layout.addWidget(self.search_edit)
        self.bone_tree = QTreeWidget(left)
        self.bone_tree.setHeaderLabels(["Bone", "Status"])
        self.bone_tree.setColumnWidth(0, 380)
        self.bone_tree.currentItemChanged.connect(self._tree_selection_changed)
        left_layout.addWidget(self.bone_tree, 1)
        buttons = QHBoxLayout()
        self.add_child_button = QPushButton("Add Child Bone", left)
        self.add_child_button.setToolTip("Add one bone under the selected bone.")
        self.add_child_button.clicked.connect(self._add_child)
        self.add_chain_button = QPushButton("Add Chain...", left)
        self.add_chain_button.setToolTip("Add a row of bones hanging from the selected bone, for a cape, tail or hair strand.")
        self.add_chain_button.clicked.connect(self._add_chain)
        self.remove_button = QPushButton("Remove", left)
        self.remove_button.setToolTip("Remove the selected added bone and the bones added under it.")
        self.remove_button.clicked.connect(self._remove_selected)
        for button in (self.add_child_button, self.add_chain_button, self.remove_button):
            buttons.addWidget(button)
        left_layout.addLayout(buttons)

        right = QWidget(splitter)
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(0, 0, 0, 0)
        self.sketch = SkeletonSketch(right)
        self.sketch.boneClicked.connect(self._select_bone)
        right_layout.addWidget(self.sketch, 1)

        self.details_group = QGroupBox("Selected bone", right)
        details_layout = QVBoxLayout(self.details_group)
        self.detail_pages = QStackedWidget(self.details_group)
        details_layout.addWidget(self.detail_pages)

        # Game bone: an explanation and where to go next, not greyed-out fields.
        self.game_page = QWidget(self.detail_pages)
        game_layout = QVBoxLayout(self.game_page)
        game_layout.setContentsMargins(0, 0, 0, 0)
        self.game_summary = QLabel(self.game_page)
        self.game_summary.setWordWrap(True)
        self.game_summary.setTextFormat(Qt.PlainText)
        game_layout.addWidget(self.game_summary)
        self.game_reason = QLabel(
            "This is one of the game's own bones, so it cannot be changed here: meshes, animations and "
            "sockets depend on it. To reshape a game bone while an item is worn, use the game's bone offset "
            "table. You can attach new bones to it.", self.game_page)
        self.game_reason.setObjectName("HintLabel")
        self.game_reason.setWordWrap(True)
        game_layout.addWidget(self.game_reason)
        self.game_marker_warning = self._warning_label(self.game_page)
        game_layout.addWidget(self.game_marker_warning)
        here = QHBoxLayout()
        self.add_child_here_button = QPushButton("Add Child Bone Here", self.game_page)
        self.add_child_here_button.clicked.connect(self._add_child)
        self.add_chain_here_button = QPushButton("Add Chain Here...", self.game_page)
        self.add_chain_here_button.clicked.connect(self._add_chain)
        here.addWidget(self.add_child_here_button)
        here.addWidget(self.add_chain_here_button)
        here.addStretch(1)
        game_layout.addLayout(here)
        game_layout.addStretch(1)
        self.detail_pages.addWidget(self.game_page)

        # Added bone: the editable form.
        self.added_page = QWidget(self.detail_pages)
        details = QFormLayout(self.added_page)
        details.setContentsMargins(0, 0, 0, 0)
        self.name_edit = QLineEdit(self.added_page)
        self.name_edit.editingFinished.connect(self._rename_selected)
        details.addRow("Name:", self.name_edit)
        self.parent_label = QLabel(self.added_page)
        details.addRow("Attached to:", self.parent_label)
        self.added_marker_warning = self._warning_label(self.added_page)
        details.addRow("", self.added_marker_warning)
        self.position_boxes = self._vector_boxes(-100.0, 100.0, 4, 0.01, " m")
        self.rotation_boxes = self._vector_boxes(-360.0, 360.0, 2, 5.0, "\u00b0")
        self.scale_boxes = self._vector_boxes(0.01, 100.0, 3, 0.05, "")
        details.addRow("Offset from parent:", self._vector_row(self.position_boxes))
        axes = QLabel("X is the character's left, Y is up, Z is back.", self.added_page)
        axes.setObjectName("HintLabel")
        details.addRow("", axes)
        details.addRow("Rotation from parent:", self._vector_row(self.rotation_boxes))
        details.addRow("Scale:", self._vector_row(self.scale_boxes))
        self.world_label = QLabel(self.added_page)
        self.world_label.setObjectName("HintLabel")
        details.addRow("Character position:", self.world_label)
        self.detail_pages.addWidget(self.added_page)
        right_layout.addWidget(self.details_group)
        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 3)

        self.status_label = QLabel(self)
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)
        limits = QLabel(
            "New bones have no animation or physics of their own, so they follow their parent. "
            "Create New Item can weight a model to them; a skeleton with added bones is untested in game.")
        limits.setObjectName("HintLabel")
        limits.setWordWrap(True)
        layout.addWidget(limits)

        bottom = QHBoxLayout()
        self.open_draft_button = QPushButton("Open Draft...", self)
        self.open_draft_button.setToolTip("Continue from a saved Skeleton Edit JSON draft.")
        self.open_draft_button.clicked.connect(self._open_draft)
        self.save_draft_button = QPushButton("Save Draft...", self)
        self.save_draft_button.setToolTip("Save the added bones as Skeleton Edit JSON to finish later.")
        self.save_draft_button.clicked.connect(self._save_draft)
        bottom.addWidget(self.open_draft_button)
        bottom.addWidget(self.save_draft_button)
        bottom.addStretch(1)
        box = QDialogButtonBox(self)
        self.save_mod_button = box.addButton("Save as Mod...", QDialogButtonBox.AcceptRole)
        self.save_mod_button.setDefault(True)
        self.save_mod_button.setToolTip("Write the skeleton with the added bones as a mod-ready loose package.")
        if self._accept_text:
            self.save_mod_button.setText(self._accept_text)
            self.save_mod_button.setToolTip(self._accept_tooltip)
        box.addButton(QDialogButtonBox.Cancel)
        box.accepted.connect(self.accept)
        box.rejected.connect(self.reject)
        bottom.addWidget(box)
        layout.addLayout(bottom)

    @staticmethod
    def _warning_label(parent: QWidget) -> QLabel:
        label = QLabel(parent)
        label.setWordWrap(True)
        label.setStyleSheet(f"color: {_SELECTED_COLOUR.name()};")
        label.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Minimum)
        label.hide()
        return label

    def _vector_boxes(self, low: float, high: float, decimals: int, step: float, suffix: str) -> list[QDoubleSpinBox]:
        boxes = []
        for _axis in range(3):
            box = QDoubleSpinBox(self)
            box.setRange(low, high)
            box.setDecimals(decimals)
            box.setSingleStep(step)
            box.setSuffix(suffix)
            box.setKeyboardTracking(False)
            box.valueChanged.connect(self._form_values_changed)
            boxes.append(box)
        return boxes

    def _vector_row(self, boxes: list[QDoubleSpinBox]) -> QWidget:
        row = QWidget(self)
        grid = QGridLayout(row)
        grid.setContentsMargins(0, 0, 0, 0)
        for column, (axis, box) in enumerate(zip("XYZ", boxes)):
            grid.addWidget(QLabel(axis, row), 0, column * 2)
            grid.addWidget(box, 0, column * 2 + 1)
        return row

    def keyPressEvent(self, event) -> None:
        # Enter in a name or number field must not press Save as Mod / Use These Bones.
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            event.accept()
            return
        super().keyPressEvent(event)

    # State ------------------------------------------------------------------
    def edits(self) -> tuple[PabAppendEdit, ...]:
        return tuple(row.edit() for row in self._rows)

    def _bind_matrix(self, name: str) -> tuple[float, ...] | None:
        bone = next((item for item in self._preview.bones if item.name == name), None)
        return bone.bind_matrix if bone is not None else None

    def _marker_root(self, name: str) -> str:
        """The marker a bone hangs from, or "" when it is on the body."""
        while True:
            row = self._row(name)
            if row is None:
                break
            name = row.parent
        bone = next((item for item in self._source.bones if item.name == name), None)
        if bone is None or name in self._body:
            return ""
        while bone.parent_index >= 0:
            bone = self._source.bones[bone.parent_index]
        return bone.name

    def _marker_warning(self, name: str) -> str:
        marker = self._marker_root(name)
        if not marker:
            return ""
        return (f"{marker} is a marker that does not move with the body, so bones attached here stay behind "
                "when the character moves. For a cape choose Upper back; for hair choose Head.")

    def _row(self, name: str) -> AddedBoneRow | None:
        return next((row for row in self._rows if row.name == name), None)

    def _default_name(self, stem: str) -> str:
        return "_".join((self._name_stem, stem)) if self._name_stem else stem  # noqa: FLY002 - not interface text

    def _unique_name(self, stem: str) -> str:
        taken = {bone.name for bone in self._source.bones} | {row.name for row in self._rows}
        index = 0
        while f"{stem}_{index:02d}" in taken:
            index += 1
        return f"{stem}_{index:02d}"

    def _update_steps(self) -> None:
        current = 3 if self._rows and not self._error else 2 if self._selected else 1
        for number, label in enumerate(self.step_labels, 1):
            font = QFont(self.font())
            font.setBold(number == current)
            label.setFont(font)

    def _refresh(self) -> None:
        self._preview, self._error = build_added_bones(self._source, self._rows)
        added = {row.name for row in self._rows}
        self.sketch.set_skeleton(self._preview, added, self._selected)
        total = len(self._source.bones) + len(self._rows)
        if self._error:
            self.status_label.setText(self._error)
            self.status_label.setStyleSheet(f"color: {_SELECTED_COLOUR.name()};")
        elif self._rows:
            self.status_label.setText(f"{len(self._source.bones):,} game bones + {len(self._rows):,} added = {total:,}.")
            self.status_label.setStyleSheet("")
        else:
            self.status_label.setText("Select a bone, then use Add Child Bone or Add Chain.")
            self.status_label.setStyleSheet("")
        self.save_mod_button.setEnabled(bool(self._rows) and not self._error)
        self.save_draft_button.setEnabled(bool(self._rows))
        self._update_steps()
        self._load_form()

    def _load_form(self) -> None:
        row = self._row(self._selected)
        self._loading_form = True
        try:
            self.remove_button.setEnabled(row is not None)
            bone = next((item for item in self._preview.bones if item.name == self._selected), None)
            warning = self._marker_warning(self._selected)
            if row is not None:
                self.details_group.setTitle("New bone")
                self.detail_pages.setCurrentWidget(self.added_page)
                self.name_edit.setText(row.name)
                self.parent_label.setText(row.parent)
                self.added_marker_warning.setText(warning)
                self.added_marker_warning.setVisible(bool(warning))
                parent_matrix = self._bind_matrix(row.parent)
                offset = _to_character(row.position, parent_matrix) if parent_matrix else row.position
                for box in self.position_boxes:
                    box.setEnabled(parent_matrix is not None)
                for boxes, values in ((self.position_boxes, offset), (self.rotation_boxes, row.angles),
                                      (self.scale_boxes, row.scale)):
                    for box, value in zip(boxes, values):
                        box.setValue(value)
                if bone is not None:
                    x, y, z = bone.bind_matrix[12:15]
                    self.world_label.setText(f"{x:.3f}, {y:.3f}, {z:.3f} m")
                else:
                    self.world_label.setText("Fix the error above to see it.")
            else:
                self.details_group.setTitle("Game bone")
                self.detail_pages.setCurrentWidget(self.game_page)
                if bone is not None:
                    parent = self._preview.bones[bone.parent_index].name if bone.parent_index >= 0 else "none"
                    x, y, z = bone.bind_matrix[12:15]
                    self.game_summary.setText(
                        f"{bone.name}\nAttached to: {parent}\nPosition on the character: {x:.3f}, {y:.3f}, {z:.3f} m")
                self.game_marker_warning.setText(warning)
                self.game_marker_warning.setVisible(bool(warning))
            for button in (self.add_child_button, self.add_chain_button,
                           self.add_child_here_button, self.add_chain_here_button):
                button.setEnabled(bone is not None)
        finally:
            self._loading_form = False

    # Tree -------------------------------------------------------------------
    def _rebuild_tree(self) -> None:
        self.bone_tree.blockSignals(True)
        self.bone_tree.clear()
        items: dict[str, QTreeWidgetItem] = {}
        bold = QFont(self.bone_tree.font())
        bold.setBold(True)
        dim = self.palette().color(self.palette().ColorGroup.Disabled, self.palette().ColorRole.Text)
        markers = None
        entries = [(bone.name, self._source.bones[bone.parent_index].name if bone.parent_index >= 0 else None, False)
                   for bone in self._source.bones]
        entries += [(row.name, row.parent, True) for row in self._rows]
        for name, parent, added in entries:
            owner = items.get(parent) if parent else None
            if owner is None and name not in self._body:
                if markers is None:
                    markers = QTreeWidgetItem(self.bone_tree)
                    markers.setText(0, "Markers (do not follow the body)")
                    markers.setToolTip(0, "Root-motion, IK and climb targets at the feet or the origin.")
                    markers.setForeground(0, dim)
                    markers.setFlags(markers.flags() & ~Qt.ItemIsSelectable)
                owner = markers
            item = QTreeWidgetItem(owner if owner is not None else self.bone_tree)
            item.setText(0, name)
            item.setData(0, Qt.UserRole, name)
            if added:
                item.setText(1, "Added")
                item.setFont(0, bold)
                item.setFont(1, bold)
            elif name not in self._body:
                item.setText(1, "Marker")
                for column in (0, 1):
                    item.setForeground(column, dim)
            items[name] = item
        if self._source.bones:
            items[self._source.bones[0].name].setExpanded(True)
        self._tree_items = items
        self.bone_tree.blockSignals(False)
        self._apply_search(self.search_edit.text())
        self._select_bone(self._selected)

    def _apply_search(self, text: str) -> None:
        needle = text.strip().casefold()
        for name, item in getattr(self, "_tree_items", {}).items():
            item.setHidden(bool(needle) and needle not in name.casefold())
            parent = item.parent()
            if parent is not None and parent.data(0, Qt.UserRole) is None:
                parent.setHidden(bool(needle))
        if needle:
            for name, item in self._tree_items.items():
                if not item.isHidden():
                    parent = item.parent()
                    while parent is not None:
                        parent.setHidden(False)
                        parent.setExpanded(True)
                        parent = parent.parent()

    def _select_bone(self, name: str) -> None:
        item = getattr(self, "_tree_items", {}).get(name)
        if item is not None:
            self.bone_tree.setCurrentItem(item)
            self.bone_tree.scrollToItem(item)
        self._selected = name
        self._refresh_selection_only()

    def _tree_selection_changed(self, current: QTreeWidgetItem | None, _previous=None) -> None:
        if current is None or current.data(0, Qt.UserRole) is None:
            return
        self._selected = str(current.data(0, Qt.UserRole))
        self._refresh_selection_only()

    def _refresh_selection_only(self) -> None:
        self.sketch.set_skeleton(self._preview, {row.name for row in self._rows}, self._selected)
        self._load_form()

    # Edits ------------------------------------------------------------------
    def _add_child(self) -> None:
        row = AddedBoneRow(self._selected, self._unique_name(self._default_name("NewBone")))
        self._rows.append(row)
        self._selected = row.name
        self._refresh()
        self._rebuild_tree()
        self.name_edit.setFocus()
        self.name_edit.selectAll()

    def _add_chain(self) -> None:
        dialog = QDialog(self)
        dialog.setObjectName("PabBoneChainDialog")
        dialog.setWindowTitle("Add Chain")
        form = QFormLayout(dialog)
        hint = QLabel(f"The first bone starts at {self._selected}; each next bone is one segment further.", dialog)
        hint.setObjectName("HintLabel")
        hint.setWordWrap(True)
        form.addRow(hint)
        prefix = QLineEdit(self._default_name("Cape"), dialog)
        form.addRow("Name prefix:", prefix)
        count = QSpinBox(dialog)
        count.setRange(1, 64)
        count.setValue(5)
        form.addRow("Bones:", count)
        length = QDoubleSpinBox(dialog)
        length.setRange(0.001, 10.0)
        length.setDecimals(3)
        length.setSingleStep(0.01)
        length.setValue(0.12)
        length.setSuffix(" m")
        form.addRow("Segment length:", length)
        direction = QComboBox(dialog)
        labels = {"down": self.tr("Down"), "back": self.tr("Back"), "forward": self.tr("Forward"),
                  "left": self.tr("Character's left"), "right": self.tr("Character's right"), "up": self.tr("Up")}
        for key in _DIRECTIONS:
            direction.addItem(labels[key], key)
        form.addRow("Direction:", direction)
        box = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel, dialog)
        box.accepted.connect(dialog.accept)
        box.rejected.connect(dialog.reject)
        form.addRow(box)
        if dialog.exec() != QDialog.Accepted:
            return
        self.add_chain(prefix.text().strip(), count.value(), length.value(), str(direction.currentData()))

    def add_chain(self, prefix: str, count: int, segment_length: float, direction: str) -> bool:
        """Add a chain under the selected bone; show the refusal and return False if it cannot."""
        try:
            edits = plan_bone_chain(self._preview, self._selected, prefix, count, segment_length,
                                    PAB_CHAIN_DIRECTIONS[direction])
            names = {row.name for row in self._rows}
            clash = next((edit.name for edit in edits if edit.name in names), "")
            if clash:
                raise PabEditRefused(f"Bone {clash!r} already exists; choose another prefix.")
        except PabEditRefused as exc:
            QMessageBox.warning(self, "Add Chain", str(exc))
            return False
        self._rows.extend(AddedBoneRow.from_edit(edit) for edit in edits)
        self._selected = edits[-1].name
        self._refresh()
        self._rebuild_tree()
        return True

    def _remove_selected(self) -> None:
        if self._row(self._selected) is None:
            return
        doomed = {self._selected}
        changed = True
        while changed:
            changed = False
            for row in self._rows:
                if row.parent in doomed and row.name not in doomed:
                    doomed.add(row.name)
                    changed = True
        parent = self._row(self._selected).parent
        self._rows = [row for row in self._rows if row.name not in doomed]
        self._selected = parent
        self._refresh()
        self._rebuild_tree()

    def _rename_selected(self) -> None:
        if self._loading_form:
            return
        row = self._row(self._selected)
        new_name = self.name_edit.text().strip()
        if row is None or new_name == row.name:
            return
        taken = {bone.name for bone in self._source.bones} | {item.name for item in self._rows if item is not row}
        problem = ("A bone needs a name." if not new_name
                   else f"Bone {new_name!r} already exists." if new_name in taken
                   else "Bone names are 1 to 255 printable ASCII characters." if not _valid_bone_name(new_name)
                   else "")
        if problem:
            # Renaming first and checking later moved this bone's children to the
            # other bone's name, and renaming back then took that bone's children too.
            self.status_label.setText(problem)
            with QSignalBlocker(self.name_edit):
                self.name_edit.setText(row.name)
            return
        old_name = row.name
        for item in self._rows:
            if item.parent == old_name:
                item.parent = new_name
        row.name = new_name
        self._selected = new_name
        self._refresh()
        self._rebuild_tree()

    def _form_values_changed(self, _value=None) -> None:
        if self._loading_form:
            return
        row = self._row(self._selected)
        if row is None:
            return
        index = self._rows.index(row)
        parent_matrix = self._bind_matrix(row.parent)

        def edited(boxes, shown):
            """The boxes' values, or None while they still show ``shown`` (rounded)."""
            values = tuple(box.value() for box in boxes)
            return None if values == tuple(round(value, box.decimals()) for value, box in zip(shown, boxes)) else values

        # Only the vector the user changed takes the boxes' rounded values; the
        # others keep their exact values, so an untouched bone stays bit for bit.
        offset = edited(self.position_boxes, _to_character(row.position, parent_matrix) if parent_matrix else row.position)
        angles = edited(self.rotation_boxes, row.angles)
        scale = edited(self.scale_boxes, row.scale)
        self._rows[index] = replace(
            row,
            position=_to_parent(offset, parent_matrix) if parent_matrix and offset is not None else row.position,
            angles=row.angles if angles is None else angles,
            scale=row.scale if scale is None else scale,
        )
        self._refresh()

    # Drafts -----------------------------------------------------------------
    def _draft_path(self) -> str:
        stem = Path(self._path.replace("\\", "/")).stem or "skeleton"
        folder = self._draft_directory or Path.home()
        return str(folder / f"{stem}.skeleton-edit.json")

    def _save_draft(self) -> None:
        selected, _filter = QFileDialog.getSaveFileName(
            self, "Save Draft", self._draft_path(), "Skeleton Edit JSON (*.skeleton-edit.json *.json)")
        if not selected:
            return
        try:
            target = Path(selected)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(dumps_pab_edit_json(self._data, self._path, self.edits()), encoding="utf-8")
        except OSError as exc:
            QMessageBox.warning(self, "Save Draft", f"Could not save the draft:\n{exc}")
            return
        self.status_label.setText(f"Saved draft: {selected}")

    def _open_draft(self) -> None:
        selected, _filter = QFileDialog.getOpenFileName(
            self, "Open Draft", self._draft_path(), "Skeleton Edit JSON (*.skeleton-edit.json *.json);;JSON (*.json)")
        if selected:
            # Editors such as Notepad may save a byte-order mark.
            self.load_draft_text(Path(selected).read_text(encoding="utf-8-sig"))

    def load_draft_text(self, text: str) -> bool:
        try:
            edits = read_pab_edit_json(self._data, text, virtual_path=self._path).add_bones
        except PabEditJsonError as exc:
            QMessageBox.warning(self, "Open Draft", str(exc))
            return False
        self._rows = [AddedBoneRow.from_edit(edit) for edit in edits]
        if self._rows:
            self._selected = self._rows[-1].name
        self._refresh()
        self._rebuild_tree()
        return True


__all__ = ["AddedBoneRow", "PabBoneEditorDialog", "SkeletonSketch", "build_added_bones"]
