"""Independent socket capacity and opening costs, without changing embedded perks."""
from PySide6.QtCore import QSignalBlocker
from PySide6.QtWidgets import (
    QCheckBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QSpinBox, QTableWidget, QVBoxLayout, QWidget,
)
from cdmw.domain.new_item.authoring import SocketSlot


class SocketEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        self._syncing = False
        layout = QVBoxLayout(self)
        self.customize = QCheckBox("Customize available sockets")
        self.customize.setToolTip("Off preserves the template's slots and costs. Zero slots explicitly removes capacity; selected perks remain selected.")
        layout.addWidget(self.customize)
        row = QHBoxLayout()
        row.addWidget(QLabel("Available slots:"))
        self.count = QSpinBox()
        self.count.setRange(0, 5)
        row.addWidget(self.count)
        self.experimental = QCheckBox("Experimental: up to eight slots")
        row.addWidget(self.experimental)
        layout.addLayout(row)
        self.costs = QTableWidget(0, 3)
        self.costs.setHorizontalHeaderLabels(["Slot", "Unlock material / currency key", "Amount"])
        self.costs.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.costs, 1)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.customize.toggled.connect(self._toggle)
        self.count.valueChanged.connect(self._resize)
        self.experimental.toggled.connect(self._experimental)
        controller.template_changed.connect(self.refresh)
        controller.plan_invalidated.connect(self._status)
        self.refresh()

    def _template_slots(self):
        c = self.controller
        if c.snapshot is None or c.draft.template_key is None:
            return ()
        return tuple(SocketSlot(*slot) for slot in c.snapshot.row(c.draft.template_key).add_socket_materials)

    def refresh(self, *_args):
        self._syncing = True
        slots = self.controller.draft.socket_slots
        inherited = slots is None
        slots = self._template_slots() if inherited else slots
        try:
            self.customize.setChecked(not inherited)
            self.experimental.setChecked(len(slots) > 5)
            self.count.setMaximum(8 if len(slots) > 5 else 5)
            self.count.setValue(len(slots))
            self.count.setEnabled(not inherited)
            self.experimental.setEnabled(not inherited)
            self.costs.setEnabled(not inherited)
            self.costs.setRowCount(len(slots))
            for index, slot in enumerate(slots):
                self.costs.setCellWidget(index, 0, QLabel(str(index + 1)))
                for column, value in ((1, slot.material_key), (2, slot.amount)):
                    edit = QLineEdit(str(value))
                    edit.setProperty("extra", slot.extra)
                    edit.textChanged.connect(self._edited)
                    self.costs.setCellWidget(index, column, edit)
            self.costs.resizeColumnToContents(0)
            self.costs.resizeColumnToContents(1)
        finally:
            self._syncing = False
        self._status()

    def _toggle(self, checked):
        if self._syncing:
            return
        self.controller.draft.socket_slots = self._template_slots() if checked else None
        self.controller.invalidate_plan()
        self.refresh()

    def _experimental(self, checked):
        if self._syncing:
            return
        if not checked and self.count.value() > 5:
            with QSignalBlocker(self.experimental):
                self.experimental.setChecked(True)
            self.state.setText("Reduce the slot count explicitly before leaving experimental mode.")
            return
        self.count.setMaximum(8 if checked else 5)

    def _resize(self, count):
        if self._syncing:
            return
        slots = list(self.controller.draft.socket_slots or ())
        while len(slots) < count:
            prior = slots[-1] if slots else SocketSlot(1, 250)
            amount = prior.amount * 2 if prior.amount < 2000 else prior.amount + 1000
            slots.append(SocketSlot(prior.material_key, amount, prior.extra))
        self.controller.draft.socket_slots = tuple(slots[:count])
        self.controller.invalidate_plan()
        self.refresh()

    def _edited(self, *_args):
        if self._syncing:
            return
        def value(widget):
            try:
                return int(widget.text())
            except ValueError:
                return 0  # Invalid input is retained as an invalid draft, never as inherited data.
        self.controller.draft.socket_slots = tuple(
            SocketSlot(value(self.costs.cellWidget(i, 1)), value(self.costs.cellWidget(i, 2)),
                       int(self.costs.cellWidget(i, 1).property("extra") or 0))
            for i in range(self.costs.rowCount()))
        self.controller.invalidate_plan()
        self._status()

    def _status(self, *_args):
        c = self.controller
        slots = c.draft.socket_slots
        inherited = slots is None
        slots = self._template_slots() if inherited else slots
        perks = c.draft.socket_items
        perks = c.template_socket_items() if perks is None else perks
        if len(perks) > len(slots):
            self.state.setText(f"{len(perks)} selected perks need more than {len(slots)} slots. Increase capacity or remove perks explicitly.")
        else:
            self.state.setText(f"{'Inherited' if inherited else 'Custom'}: {len(slots)} slots · {len(perks)} preinstalled perks")
