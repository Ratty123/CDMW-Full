"""Supporting dialogs for the Prefab Inspector.

Two small editors kept out of the inspector itself: one to pick an existing
archive path of the right kind, and one to edit a transform as position,
rotation and scale.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.prefab_values import (
    Placement,
    decode_value,
    editable_kind,
    encode_value,
    value_limits,
    degrees_to_rotation,
    is_near_pole,
    rotation_degrees,
)


class AssetPickerDialog(QDialog):
    """Pick an existing archive path, filtered to one kind of asset."""

    def __init__(self, candidates: Sequence[str], *, current: str = "", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Choose an asset")
        self.resize(760, 520)
        self._candidates = tuple(candidates)
        self.chosen = ""

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"{len(self._candidates):,} file(s) of this kind exist in the archives."))
        self.filter_box = QLineEdit()
        self.filter_box.setPlaceholderText("Type part of a name to narrow the list...")
        self.filter_box.textChanged.connect(self._refresh)
        layout.addWidget(self.filter_box)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda _item: self._accept_selection())
        layout.addWidget(self.list, 1)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept_selection)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

        # Seed with the current file's folder, not its name: the useful starting
        # point is its siblings, and its own name matches only itself.
        folder = current.rsplit("/", 1)[0] if "/" in current else ""
        self.filter_box.setText(folder)
        self._refresh(self.filter_box.text())

    def _refresh(self, text: str) -> None:
        needle = str(text or "").strip().lower()
        matches = [item for item in self._candidates if needle in item.lower()] if needle else list(self._candidates)
        self.list.clear()
        # A full list of thousands is unusable and slow to build; narrow instead.
        self.list.addItems(matches[:500])
        if len(matches) > 500:
            self.list.addItem(f"... {len(matches) - 500:,} more, keep typing to narrow")

    def _accept_selection(self) -> None:
        item = self.list.currentItem()
        if item is None or item.text().startswith("... "):
            return
        self.chosen = item.text()
        self.accept()


class PlacementEditDialog(QDialog):
    """Edit one transform as position, rotation and scale.

    Rotation is entered in degrees because quaternions are not something anyone
    types, and converted on the way out. Euler angles are ambiguous, so that
    conversion is lossy -- which is why an untouched box is never converted at
    all. Each of the three groups is written back only if the user actually
    moved one of its boxes; otherwise the decoded value is reused verbatim.

    Without that, nudging a position rewrote the rotation: measured over the
    shipped archives, 0.60% of unit quaternions came back more than a degree
    out, and the worst -- weapon child sockets, which sit at pitch 90 -- by a
    full 90 degrees.
    """

    def __init__(
        self,
        placement: Placement,
        *,
        title: str,
        space: str = "unknown",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Placement - {title}")
        self._tile = placement.tile
        self._source = placement
        self.result_placement: Placement | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._position = [self._spin(value, -1e6, 1e6) for value in placement.position]
        # Seed at more precision than the display rendering: a box that shows a
        # rounded angle would report itself as edited the moment it is read back.
        self._rotation = [
            self._spin(value, -360.0, 360.0)
            for value in rotation_degrees(placement.rotation, digits=6)
        ]
        self._scale = [self._spin(value, 0.001, 1000.0) for value in placement.scale]
        # Take the seeds from the widgets, not the source values: setValue
        # quantises to the box's decimals, so this is the only comparison that
        # can distinguish "untouched" from "typed the same number back".
        self._seeds = {
            id(group): tuple(box.value() for box in group)
            for group in (self._position, self._rotation, self._scale)
        }
        form.addRow("Position X, Y, Z", self._triple(self._position))
        form.addRow("Rotation yaw, pitch, roll", self._triple(self._rotation))
        form.addRow("Scale X, Y, Z", self._triple(self._scale))
        layout.addLayout(form)
        # Naming the wrong basis makes every nudge wrong, so this follows the
        # member rather than asserting "world" for anything with three floats.
        measured = {
            "world": (
                "Position is in world coordinates - where the object sits in the "
                "map, not an offset from anything."
            ),
            "offset": (
                "Position is an offset from the object's own origin, not a place "
                "in the world."
            ),
        }.get(space, "What position is measured from is not established for this field.")
        self.space_label = QLabel(f"Rotation is in degrees. {measured}")
        self.space_label.setWordWrap(True)
        layout.addWidget(self.space_label)
        self.pole_warning = QLabel(
            "This part is rotated straight up or down. At that angle yaw and roll "
            "turn about the same axis, so a rotation typed here will not read back "
            "as the numbers you entered. Position and scale are unaffected."
        )
        self.pole_warning.setWordWrap(True)
        self.pole_warning.setVisible(is_near_pole(placement.rotation))
        layout.addWidget(self.pole_warning)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    @staticmethod
    def _spin(value: float, low: float, high: float) -> QDoubleSpinBox:
        box = QDoubleSpinBox()
        box.setDecimals(4)
        box.setRange(low, high)
        box.setSingleStep(0.1)
        box.setValue(float(value))
        return box

    @staticmethod
    def _triple(boxes: list[QDoubleSpinBox]) -> QWidget:
        holder = QWidget()
        row = QHBoxLayout(holder)
        row.setContentsMargins(0, 0, 0, 0)
        for box in boxes:
            row.addWidget(box)
        return holder

    def _edited(self, group: list[QDoubleSpinBox]) -> bool:
        """Did the user move any box in this group?"""
        return any(box.value() != seed for box, seed in zip(group, self._seeds[id(group)]))

    def _accept(self) -> None:
        self.result_placement = Placement(
            scale=(
                tuple(box.value() for box in self._scale)  # type: ignore[arg-type]
                if self._edited(self._scale)
                else self._source.scale
            ),
            # Only convert back through Euler when the angles were actually
            # typed. Reusing the decoded quaternion is exact; converting is not.
            rotation=(
                degrees_to_rotation(*(box.value() for box in self._rotation))
                if self._edited(self._rotation)
                else self._source.rotation
            ),
            position=(
                tuple(box.value() for box in self._position)  # type: ignore[arg-type]
                if self._edited(self._position)
                else self._source.position
            ),
            tile=self._tile,
        )
        self.accept()


__all__ = ["AssetPickerDialog", "PlacementEditDialog", "ValueEditDialog"]


class ValueEditDialog(QDialog):
    """Edit one non-transform value: a flag, a number, or three numbers.

    The widget follows the member's declared type, so an integer field cannot
    be given a fraction and a bool is a tick rather than free text. Anything
    whose type and byte width do not agree is never offered here at all.
    """

    def __init__(
        self,
        type_name: str,
        raw: bytes,
        *,
        title: str,
        detail: str = "",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Value - {title}")
        self._type_name = type_name
        self._raw = bytes(raw)
        self._kind = editable_kind(type_name, raw)
        self.result_raw: bytes | None = None
        current = decode_value(type_name, raw)

        layout = QVBoxLayout(self)
        if detail:
            note = QLabel(detail)
            note.setWordWrap(True)
            layout.addWidget(note)
        form = QFormLayout()
        self._boxes: list[QDoubleSpinBox | QSpinBox] = []
        self._flag: QCheckBox | None = None
        if self._kind == "bool":
            self._flag = QCheckBox("On")
            self._flag.setChecked(bool(current))
            form.addRow("Setting", self._flag)
        elif self._kind == "int":
            low, high = value_limits(type_name) or (-(2**31), 2**31 - 1)
            box = QSpinBox()
            # QSpinBox is 32-bit; clamp the offered range rather than crash on
            # a 64-bit member, and let encode_value do the real bounds check.
            box.setRange(max(low, -(2**31)), min(high, 2**31 - 1))
            box.setValue(int(current))
            self._boxes.append(box)
            form.addRow("Whole number", box)
        elif self._kind == "float":
            box = QDoubleSpinBox()
            box.setDecimals(6)
            box.setRange(-1e12, 1e12)
            box.setValue(float(current))
            self._boxes.append(box)
            form.addRow("Number", box)
        elif self._kind == "float3":
            holder = QWidget()
            row = QHBoxLayout(holder)
            row.setContentsMargins(0, 0, 0, 0)
            for value in current:  # type: ignore[union-attr]
                box = QDoubleSpinBox()
                box.setDecimals(6)
                box.setRange(-1e12, 1e12)
                box.setValue(float(value))
                self._boxes.append(box)
                row.addWidget(box)
            form.addRow("X, Y, Z", holder)
        layout.addLayout(form)

        self.error = QLabel("")
        self.error.setWordWrap(True)
        self.error.setVisible(False)
        layout.addWidget(self.error)

        self.buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        self.buttons.accepted.connect(self._accept)
        self.buttons.rejected.connect(self.reject)
        layout.addWidget(self.buttons)

    def _current(self) -> object:
        if self._flag is not None:
            return self._flag.isChecked()
        if self._kind == "float3":
            return tuple(box.value() for box in self._boxes)
        return self._boxes[0].value()

    def _accept(self) -> None:
        try:
            self.result_raw = encode_value(self._type_name, self._raw, self._current())
        except (ValueError, TypeError) as exc:
            # Refuse rather than truncate: a value that does not fit is a
            # mistake worth stopping.
            self.error.setText(str(exc))
            self.error.setVisible(True)
            return
        self.accept()
