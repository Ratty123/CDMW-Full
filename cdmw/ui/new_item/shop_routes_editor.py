"""Save multiple reviewed shop routes from the existing shop controls."""
from PySide6.QtWidgets import QHBoxLayout, QLabel, QListWidget, QPushButton, QVBoxLayout, QWidget
from cdmw.domain.new_item.spec import PlacementKind


class ShopRoutesEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller = controller
        layout = QVBoxLayout(self)
        self.routes = QListWidget()
        self.routes.setMaximumHeight(95)
        layout.addWidget(self.routes)
        row = QHBoxLayout()
        self.add = QPushButton("Add route")
        self.add.setToolTip("Save the current shop controls as another acquisition route.")
        self.add.clicked.connect(self._add)
        row.addWidget(self.add)
        self.remove = QPushButton("Remove")
        self.remove.clicked.connect(self._remove)
        row.addWidget(self.remove)
        self.single = QPushButton("Use current shop")
        self.single.setToolTip("Discard the saved route list and use only the current shop controls.")
        self.single.clicked.connect(self._single)
        row.addWidget(self.single)
        layout.addLayout(row)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        self.refresh()

    def refresh(self):
        self.routes.clear()
        selected = self.controller.draft.shop_placements
        for route in selected or ():
            entry = f" · entry {route.stock_index}" if route.stock_index is not None else ""
            self.routes.addItem(f"{route.store_name} · {route.kind.value} · {route.old_item_name or 'new entry'}{entry}")
        self.routes.setVisible(selected is not None)
        self.state.setText("The current shop controls define the route." if selected is None else
                           f"{len(selected)} saved routes will be exported. Add the current controls to include another shop.")

    def _add(self):
        route = self.controller.current_spec().placement
        if route.kind is PlacementKind.NONE:
            self.state.setText("Choose Add or Replace and a shop first.")
            return
        selected = tuple(self.controller.draft.shop_placements or ())
        if route in selected:
            self.state.setText("This route is already selected.")
            return
        self.controller.draft.shop_placements = (*selected, route)
        self.controller.invalidate_plan()
        self.refresh()

    def _remove(self):
        selected = list(self.controller.draft.shop_placements or ())
        index = self.routes.currentRow()
        if 0 <= index < len(selected):
            selected.pop(index)
            self.controller.draft.shop_placements = tuple(selected)
            self.controller.invalidate_plan()
            self.refresh()

    def _single(self):
        self.controller.draft.shop_placements = None
        self.controller.invalidate_plan()
        self.refresh()
