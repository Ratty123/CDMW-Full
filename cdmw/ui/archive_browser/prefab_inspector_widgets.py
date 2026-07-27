"""Supporting dialogs for the Prefab Inspector.

Two small editors kept out of the inspector itself: one to pick an existing
archive path of the right kind, and one to edit a transform as position,
rotation and scale.
"""

from __future__ import annotations

from typing import Sequence

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.prefab_values import Placement, degrees_to_rotation, rotation_degrees


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
    types, and converted on the way out. Euler angles are ambiguous, so the
    conversion is one-way per edit -- what is stored is the quaternion.
    """

    def __init__(self, placement: Placement, *, title: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"Placement - {title}")
        self._tile = placement.tile
        self.result_placement: Placement | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self._position = [self._spin(value, -1e6, 1e6) for value in placement.position]
        self._rotation = [self._spin(value, -360.0, 360.0) for value in rotation_degrees(placement.rotation)]
        self._scale = [self._spin(value, 0.001, 1000.0) for value in placement.scale]
        form.addRow("Position X, Y, Z", self._triple(self._position))
        form.addRow("Rotation yaw, pitch, roll", self._triple(self._rotation))
        form.addRow("Scale X, Y, Z", self._triple(self._scale))
        layout.addLayout(form)
        layout.addWidget(
            QLabel("Rotation is in degrees. Scale and position are in world units.")
        )

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

    def _accept(self) -> None:
        self.result_placement = Placement(
            scale=tuple(box.value() for box in self._scale),  # type: ignore[arg-type]
            rotation=degrees_to_rotation(*(box.value() for box in self._rotation)),
            position=tuple(box.value() for box in self._position),  # type: ignore[arg-type]
            tile=self._tile,
        )
        self.accept()


__all__ = ["AssetPickerDialog", "PlacementEditDialog"]
