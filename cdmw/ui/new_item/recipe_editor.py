"""Guided recipe presets with explicit ingredient, requirement and output editing."""
from dataclasses import replace
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)
from cdmw.core.item_recipe_links import connected_recipe_keys
from cdmw.domain.new_item.authoring import RecipeInput, RecipeOutput, RecipeOverride
from cdmw.ui.new_item.ui_kit import compact_table_height


class RecipeEditor(QWidget):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.controller, self.index, self._syncing = controller, None, False
        layout = QVBoxLayout(self)
        row = QHBoxLayout()
        self.load = QPushButton("Load recipes and rewards")
        self.load.clicked.connect(lambda: controller.start_authoring_index("acquisition"))
        row.addWidget(self.load)
        self.inherited = QCheckBox("Template recipes only")
        self.inherited.setChecked(True)
        self.inherited.toggled.connect(self._choices)
        row.addWidget(self.inherited)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Find a crafting or enhancement recipe")
        timer = QTimer(self)
        timer.setSingleShot(True)
        timer.setInterval(150)
        timer.timeout.connect(self._choices)
        self.search.textChanged.connect(lambda: timer.start())
        row.addWidget(self.search, 1)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.recipe = QComboBox()
        self.recipe.setMinimumContentsLength(20)
        self.recipe.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.recipe.currentIndexChanged.connect(self._show_recipe)
        row.addWidget(self.recipe, 1)
        self.customize = QCheckBox("Customize this recipe")
        self.customize.toggled.connect(self._toggle)
        row.addWidget(self.customize)
        layout.addLayout(row)
        form = QFormLayout()
        self.tool = QComboBox()
        self.tool.currentIndexChanged.connect(self._commit)
        form.addRow("Required tool:", self.tool)
        self.knowledge = QLineEdit()
        self.knowledge.setPlaceholderText("Knowledge key; 0 removes the requirement")
        self.knowledge.textChanged.connect(self._commit)
        form.addRow("Knowledge:", self.knowledge)
        self.requirements = QLabel()
        self.requirements.setWordWrap(True)
        form.addRow("Conditions:", self.requirements)
        layout.addLayout(form)
        tabs = QTabWidget()
        inputs = QWidget()
        input_layout = QVBoxLayout(inputs)
        self.inputs = QTableWidget(0, 5)
        self.inputs.setHorizontalHeaderLabels(["Kind", "Item / group key", "Quantity", "Level", "Coupon amount"])
        self.inputs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.inputs.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.inputs.cellChanged.connect(self._commit)
        self.inputs.setToolTip("Item key 0 means the new item. Ingredient costs are separate from purchase prices.")
        input_layout.addWidget(self.inputs)
        row = QHBoxLayout()
        self.add = QPushButton("Add ingredient")
        self.add.clicked.connect(self._add)
        row.addWidget(self.add)
        self.remove = QPushButton("Remove ingredient")
        self.remove.clicked.connect(self._remove)
        row.addWidget(self.remove)
        row.addStretch(1)
        input_layout.addLayout(row)
        tabs.addTab(inputs, "Ingredients")
        self.outputs = QTableWidget(0, 4)
        self.outputs.setHorizontalHeaderLabels(["Produce new item", "Minimum", "Maximum", "Result level"])
        self.outputs.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.outputs.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.outputs.cellChanged.connect(self._commit)
        tabs.addTab(self.outputs, "Outputs")
        layout.addWidget(tabs)
        row = QHBoxLayout()
        self.reset = QPushButton("Inherit all recipes")
        self.reset.clicked.connect(lambda: self._reset(None))
        row.addWidget(self.reset)
        self.clear = QPushButton("Clear recipe connections")
        self.clear.clicked.connect(lambda: self._reset(()))
        row.addWidget(self.clear)
        row.addStretch(1)
        layout.addLayout(row)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        layout.addStretch(1)
        controller.authoring_index_ready.connect(self._ready)
        controller.authoring_index_failed.connect(self._failed)
        controller.snapshot_ready.connect(self._snapshot)
        controller.template_changed.connect(self._choices)
        controller.busy_changed.connect(lambda busy: self.load.setEnabled(not busy))
        self._show_recipe()

    def _snapshot(self):
        self.index = None
        self._choices()

    def _ready(self, kind, index):
        if kind == "acquisition":
            self.index = index
            self._syncing = True
            self.tool.clear()
            for key, name in index.tools.items():
                self.tool.addItem(name, key)
            self._syncing = False
            self._choices()

    def _failed(self, kind, message):
        if kind == "acquisition":
            self.state.setText(message)

    def _choices(self):
        old = self.recipe.currentData()
        self.recipe.blockSignals(True)
        self.recipe.clear()
        c = self.controller
        if self.index is not None and c.snapshot is not None and c.draft.template_key in c.snapshot.rows:
            try:
                linked = connected_recipe_keys(c.snapshot.rows[c.draft.template_key], c.snapshot.multichange_rows,
                                               self.index.recipes, self.index.rewards,
                                               related_keys=self.index.recipe_items.get(c.draft.template_key, ()))
            except ValueError as error:
                self.recipe.blockSignals(False)
                self.state.setText(str(error))
                return
            keys = linked if self.inherited.isChecked() else self.index.recipes
            query = self.search.text().strip().casefold()
            for key in keys:
                source = self.index.recipes.get(key)
                name = source.name if source else c.snapshot.multichange_rows[key].name
                if query and query not in f"{key} {name}".casefold():
                    continue
                supported = source is not None and all(r in self.index.rewards for r in source.reward_keys + source.additional_reward_keys)
                self.recipe.addItem(f"{name} · {key}" + ("" if supported else " · unsupported"), key)
                if self.recipe.count() >= 250:
                    break
        if self.recipe.findData(old) >= 0:
            self.recipe.setCurrentIndex(self.recipe.findData(old))
        self.recipe.blockSignals(False)
        self._show_recipe()

    def _source(self):
        return self.index.recipes.get(self.recipe.currentData()) if self.index else None

    def _show_recipe(self):
        self._syncing = True
        source = self._source()
        edit = next((r for r in self.controller.draft.recipes or () if r.recipe_key == self.recipe.currentData()), None)
        supported = (source is not None and all(key in self.index.rewards for key in source.reward_keys + source.additional_reward_keys)
                     and not any(i.character_key or i.gimmick_key for i in source.ingredients))
        self.customize.setEnabled(supported)
        self.customize.setChecked(edit is not None)
        self.inputs.setRowCount(0)
        self.outputs.setRowCount(0)
        if supported:
            self.tool.setCurrentIndex(self.tool.findData(source.tool_key if edit is None or edit.tool_key is None else edit.tool_key))
            knowledge = source.knowledge_key if edit is None or edit.knowledge_key is None else edit.knowledge_key
            self.knowledge.setText(str(knowledge))
            self.requirements.setText(self.index.knowledge.get(knowledge, "No knowledge requirement") if knowledge else "No knowledge requirement")
            self.requirements.setToolTip(f"Elemental status references: {', '.join(str(value.key) for value in source.elemental_statuses) or '—'}\n"
                f"Consume type: {source.consume_type} · flags: {source.flags.hex(' ')}\n"
                "Condition and elemental-material arrays are empty. Source requirements and presentation are preserved.")
            inherited = self._inherited_inputs(source)
            values = inherited if edit is None or edit.inputs is None else edit.inputs
            for value in values:
                self._input_row(value)
            edits = {} if edit is None or edit.outputs is None else {(v.reward_index,v.entry_index):v for v in edit.outputs}
            for ri, key in enumerate(source.reward_keys + source.additional_reward_keys):
                for ei, product in enumerate(self.index.rewards[key].entries):
                    row = self.outputs.rowCount()
                    self.outputs.insertRow(row)
                    selected = edits.get((ri,ei))
                    label = self.controller.snapshot.item_names().get(product.item_key, str(product.item_key))
                    item = QTableWidgetItem(label)
                    item.setFlags((item.flags() | Qt.ItemIsUserCheckable) & ~Qt.ItemIsEditable)
                    item.setData(Qt.UserRole, (ri,ei))
                    item.setToolTip(f"Reward {key} · {'additional' if ri >= len(source.reward_keys) else 'primary'}\n"
                        f"Weight: {product.weight} · sub-weight: {product.sub_weight}\n"
                        f"Condition references: {product.condition_references}")
                    checked = selected is not None or ((edit is None or edit.outputs is None) and product.item_key == self.controller.draft.template_key)
                    item.setCheckState(Qt.Checked if checked else Qt.Unchecked)
                    self.outputs.setItem(row,0,item)
                    self.outputs.setItem(row,1,QTableWidgetItem(str(product.minimum if selected is None else selected.quantity)))
                    maximum = product.maximum if selected is None else (selected.quantity if selected.maximum is None else selected.maximum)
                    self.outputs.setItem(row,2,QTableWidgetItem(str(maximum)))
                    self.outputs.setItem(row,3,QTableWidgetItem(str(product.enhancement if selected is None else selected.enhancement)))
            self.state.setText("Owned copies are created when this recipe is customized.")
        else:
            self.knowledge.clear()
            self.requirements.clear()
            reason = self.index.unsupported["multichangeinfo"].get(self.recipe.currentData(), "Unsupported ingredient or output layout") if self.index else "Load the optional recipe index."
            self.state.setText(reason)
        enabled = supported and edit is not None
        for widget in (self.inputs,self.outputs,self.tool,self.knowledge,self.add,self.remove):
            widget.setEnabled(enabled)
        self._resize_tables()
        self._syncing = False

    def _resize_tables(self):
        compact_table_height(self.inputs, self.inputs.rowCount(), minimum_rows=2, maximum_rows=5)
        compact_table_height(self.outputs, self.outputs.rowCount(), minimum_rows=1, maximum_rows=5)

    def _input_row(self, value):
        row = self.inputs.rowCount()
        self.inputs.insertRow(row)
        for column, text in enumerate((value.kind,value.key,value.quantity,value.enhancement,value.coupon_quantity)):
            item = QTableWidgetItem(str(text))
            if column == 1 and self.controller.snapshot:
                item.setToolTip("New item" if not value.key else self.controller.snapshot.item_names().get(value.key,str(value.key)))
            self.inputs.setItem(row,column,item)

    def _inherited_inputs(self, source):
        # Zero-filled alternative-material placeholders are not ingredients.
        items = tuple(RecipeInput(0 if i.item_key == self.controller.draft.template_key else i.item_key,
            i.quantity, i.enhancement, "item", i.coupon_quantity) for i in source.ingredients
            if i.item_key or i.quantity or i.coupon_quantity)
        return items + tuple(RecipeInput(i.group_key, i.quantity, i.enhancement, "group") for i in source.group_ingredients)

    def _toggle(self, checked):
        if self._syncing:
            return
        if checked:
            draft = self.controller.draft
            # Keep the controls editable while an unrelated crafting preset is
            # waiting for the user to choose which output becomes the new item.
            draft.recipes = tuple(value for value in draft.recipes or () if value.recipe_key != self.recipe.currentData()) + (RecipeOverride(self.recipe.currentData()),)
            self._show_recipe()
            self._commit()
        else:
            draft = self.controller.draft
            draft.recipes = tuple(value for value in draft.recipes or () if value.recipe_key != self.recipe.currentData()) or None
            draft.authoring_errors.pop("recipes", None)
            self.controller.invalidate_plan()
            self._show_recipe()

    def _commit(self, *_):
        if self._syncing or not self.customize.isChecked() or self._source() is None:
            return
        draft = self.controller.draft
        try:
            inputs = []
            for row in range(self.inputs.rowCount()):
                values = [self.inputs.item(row,col).text().strip() for col in range(5)]
                value = RecipeInput(int(values[1]),int(values[2]),int(values[3]),values[0],int(values[4]))
                if value.kind not in ("item","group") or value.quantity < 1 or value.key < 0 or not 0 <= value.enhancement <= 65535 or value.coupon_quantity < 0:
                    raise ValueError("Invalid recipe ingredient")
                inputs.append(value)
            outputs = []
            for row in range(self.outputs.rowCount()):
                item = self.outputs.item(row,0)
                if item.checkState() == Qt.Checked:
                    ri,ei = item.data(Qt.UserRole)
                    output = RecipeOutput(ri,ei,int(self.outputs.item(row,1).text()),
                                          int(self.outputs.item(row,3).text()), int(self.outputs.item(row,2).text()))
                    if not 1 <= output.quantity <= output.maximum <= 0xffffffffffffffff or not -1 <= output.enhancement <= 32767:
                        raise ValueError("Invalid recipe output")
                    outputs.append(output)
            if not outputs:
                raise ValueError("Select an output that produces the new item")
            knowledge = int(self.knowledge.text())
            if knowledge and knowledge not in self.index.knowledge:
                raise ValueError("Unknown knowledge requirement")
            source = self._source()
            inherited_outputs = tuple(RecipeOutput(ri, ei, product.minimum, product.enhancement, product.maximum)
                for ri, key in enumerate(source.reward_keys + source.additional_reward_keys)
                for ei, product in enumerate(self.index.rewards[key].entries) if product.item_key == draft.template_key)
            edit = RecipeOverride(self.recipe.currentData(),
                None if tuple(inputs) == self._inherited_inputs(source) else tuple(inputs),
                None if self.tool.currentData() == source.tool_key else self.tool.currentData(),
                None if knowledge == source.knowledge_key else knowledge,
                None if tuple(outputs) == inherited_outputs else tuple(outputs))
            draft.recipes = tuple(value for value in draft.recipes or () if value.recipe_key != edit.recipe_key) + (edit,)
            draft.authoring_errors.pop("recipes",None)
            self.state.setText("Customized recipe · shared source preserved")
        except (ValueError,AttributeError) as exc:
            draft.authoring_errors["recipes"] = str(exc)
            self.state.setText(str(exc))
        self.controller.invalidate_plan()

    def _add(self):
        self._syncing = True
        self._input_row(RecipeInput(1,1))
        self._syncing = False
        self._resize_tables()
        self._commit()

    def _remove(self):
        if self.inputs.currentRow() >= 0:
            self.inputs.removeRow(self.inputs.currentRow())
            self._resize_tables()
            self._commit()

    def _reset(self, value):
        self.controller.draft.recipes = value
        self.controller.draft.authoring_errors.pop("recipes",None)
        self.controller.invalidate_plan()
        self._show_recipe()
