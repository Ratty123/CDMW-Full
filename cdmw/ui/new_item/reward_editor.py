"""Selected existing item-use consumers, with independent reward operations."""
from PySide6.QtWidgets import (
    QComboBox, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QPushButton,
    QSpinBox, QVBoxLayout, QWidget,
)
from cdmw.domain.new_item.authoring import RewardAcquisition
from cdmw.ui.new_item.choice_model import set_choice_rows
from cdmw.domain.cancellation import raise_if_cancelled


class RewardEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller, self.index = controller, None
        self._lookup = controller.create_lookup_lane()
        self._lookup.completed.connect(self._choices_ready)
        self._lookup.failed.connect(self._choices_failed)
        self._details_lookup = controller.create_lookup_lane()
        self._details_lookup.completed.connect(self._details_ready)
        self._details_lookup.failed.connect(self._choices_failed)
        layout = QVBoxLayout(self)
        self.load = QPushButton("Load existing reward sources")
        self.load.clicked.connect(lambda: controller.start_authoring_index("acquisition"))
        layout.addWidget(self.load)
        form = QFormLayout()
        self.consumer = QComboBox()
        self.consumer.setMinimumContentsLength(20)
        self.consumer.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.consumer.currentIndexChanged.connect(self._consumer)
        form.addRow("Existing consumer:", self.consumer)
        self.entry = QComboBox()
        self.entry.currentIndexChanged.connect(self._entry)
        form.addRow("Reward entry:", self.entry)
        self.mode = QComboBox()
        self.mode.addItem("Add the new item", "insert")
        self.mode.addItem("Replace this reward entry", "swap")
        form.addRow("Operation:", self.mode)
        row = QHBoxLayout()
        self.minimum, self.maximum, self.level = QSpinBox(), QSpinBox(), QSpinBox()
        for box in (self.minimum,self.maximum):
            box.setRange(1, 2_000_000_000)
            box.setValue(1)
        self.level.setRange(-1,32767)
        self.level.setSpecialValueText("Template default")
        self.level.setValue(-1)
        row.addWidget(self.minimum)
        row.addWidget(QLabel("to"))
        row.addWidget(self.maximum)
        form.addRow("Quantity:", row)
        form.addRow("Enhancement:", self.level)
        self.weight = QLineEdit()
        self.weight.setPlaceholderText("Keep the selected entry's raw weight")
        self.weight.setToolTip("Raw stored weight. The source's roll policy and conditions are preserved; this field is not a percentage.")
        form.addRow("Advanced weight:", self.weight)
        layout.addLayout(form)
        self.details = QLabel()
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        row = QHBoxLayout()
        self.add = QPushButton("Add reward route")
        self.add.clicked.connect(self._add)
        row.addWidget(self.add)
        self.remove = QPushButton("Remove selected route")
        self.remove.clicked.connect(self._remove)
        row.addWidget(self.remove)
        row.addStretch(1)
        layout.addLayout(row)
        self.routes = QListWidget()
        layout.addWidget(self.routes,1)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        controller.authoring_index_ready.connect(self._ready)
        controller.authoring_index_failed.connect(self._failed)
        controller.snapshot_ready.connect(self._snapshot)
        controller.template_changed.connect(self.refresh)
        controller.busy_changed.connect(lambda busy: self.load.setEnabled(not busy))
        self.refresh()

    def _snapshot(self):
        self._lookup.cancel()
        self._details_lookup.cancel()
        self.index = None
        self.consumer.clear()
        self.refresh()

    def _ready(self, kind, index):
        if kind != "acquisition":
            return
        self.index = index
        snapshot = self.controller.snapshot
        def prepare(stop):
            names = snapshot.item_names()
            rows = []
            for number, value in enumerate(index.consumers):
                if number % 128 == 0:
                    raise_if_cancelled(stop)
                key, position, _use, _reward = value
                rows.append((f"{names.get(key,str(key))} · action {position + 1}", value))
            return tuple(rows)
        self._lookup.request((id(snapshot), id(index)), prepare)

    def _choices_failed(self, _key, message):
        self.state.setText(message)

    def _choices_ready(self, key, rows):
        if key != (id(self.controller.snapshot), id(self.index)):
            return
        self.consumer.blockSignals(True)
        set_choice_rows(self.consumer, rows)
        self.consumer.blockSignals(False)
        self._consumer()
        self.refresh()

    def _failed(self, kind, message):
        if kind == "acquisition":
            self.state.setText(message)

    def _consumer(self):
        self._details_lookup.cancel()
        self.entry.clear()
        self.add.setEnabled(False)
        value = self.consumer.currentData()
        if value is None or self.index is None:
            self.details.clear()
            return
        snapshot, index = self.controller.snapshot, self.index
        self.details.setText("Loading reward details…")
        from cdmw.services.new_item_panel_search import reward_details
        self._details_lookup.request((id(snapshot), id(index), value),
                                     lambda stop: reward_details(snapshot, index, value, stop))

    def _details_ready(self, key, result):
        if key != (id(self.controller.snapshot), id(self.index), self.consumer.currentData()):
            return
        rows, details, self._consumer_tooltip = result
        self.entry.blockSignals(True)
        set_choice_rows(self.entry, rows)
        self.entry.blockSignals(False)
        self.details.setText(details)
        self._entry()
        self.add.setEnabled(bool(rows))

    def _entry(self):
        value, entry_index = self.consumer.currentData(), self.entry.currentData()
        if self.index is None or value is None or entry_index is None:
            return
        entry = self.index.rewards[value[3]].entries[entry_index]
        self.minimum.setValue(entry.minimum)
        self.maximum.setValue(entry.maximum)
        self.level.setValue(entry.enhancement)
        self.weight.clear()
        self.details.setToolTip(getattr(self, "_consumer_tooltip", "") +
            f"\nEntry condition references: {entry.condition_references}\nWeight: {entry.weight} · sub-weight: {entry.sub_weight}")

    def _add(self):
        value, entry = self.consumer.currentData(), self.entry.currentData()
        if value is None or entry is None:
            return
        try:
            weight = int(self.weight.text()) if self.weight.text().strip() else None
            if self.minimum.value() > self.maximum.value() or (weight is not None and not 0 <= weight <= 0xffffffffffffffff):
                raise ValueError("Check the reward quantity range and raw weight.")
            choice = RewardAcquisition(value[0],value[1],entry,self.mode.currentData(), self.minimum.value(),self.maximum.value(),self.level.value(),weight)
            existing = tuple(self.controller.draft.reward_acquisitions or ())
            identity = (choice.consumer_item_key,choice.use_index,choice.entry_index)
            if any((r.consumer_item_key,r.use_index,r.entry_index)==identity for r in existing):
                raise ValueError("This reward entry already has a selected operation.")
            self.controller.draft.reward_acquisitions = existing + (choice,)
            self.controller.invalidate_plan()
            self.refresh()
        except ValueError as exc:
            self.state.setText(str(exc))

    def _remove(self):
        index = self.routes.currentRow()
        values = list(self.controller.draft.reward_acquisitions or ())
        if 0 <= index < len(values):
            values.pop(index)
            self.controller.draft.reward_acquisitions = tuple(values)
            self.controller.invalidate_plan()
            self.refresh()

    def refresh(self):
        self.routes.clear()
        routes = self.controller.draft.reward_acquisitions or ()
        names = self.controller.snapshot.item_names() if routes and self.controller.snapshot else {}
        for route in routes:
            self.routes.addItem(f"{names.get(route.consumer_item_key,str(route.consumer_item_key))} · action {route.use_index+1} · {route.mode} · {route.minimum}–{route.maximum}")
        self.add.setEnabled(self.index is not None and self.entry.count() > 0)
        self.state.setText(f"{self.routes.count()} selected reward route(s)." if self.index else "Load supported existing item-producing reward sources.")
