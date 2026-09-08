"""Explicit dye presets and RGB channel-to-slot bindings for the current variant."""
from PySide6.QtWidgets import (
    QComboBox,QFileDialog,QFormLayout,QGroupBox,QHBoxLayout,QLabel,QLineEdit,
    QListWidget,QPushButton,QSpinBox,QVBoxLayout,QWidget,
)
from cdmw.domain.new_item.authoring import DyeAssignment


class DyeEditor(QGroupBox):
    def __init__(self,controller,panel):
        super().__init__("Dye assignments",panel)
        self.controller,self.panel,self.index = controller,panel,None
        self.setCheckable(True)
        self.setChecked(False)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(4,0,4,0)
        self.contents = QWidget()
        outer.addWidget(self.contents)
        layout = QVBoxLayout(self.contents)
        layout.setContentsMargins(4,4,4,4)
        layout.setSpacing(4)
        self.contents.setVisible(False)
        self.toggled.connect(self.contents.setVisible)
        self.load = QPushButton("Load dye presets")
        self.load.clicked.connect(lambda:controller.start_authoring_index("dyes"))
        from PySide6.QtCore import Qt
        layout.addWidget(self.load,0,Qt.AlignmentFlag.AlignLeft)
        form = QFormLayout()
        form.setHorizontalSpacing(6)
        form.setVerticalSpacing(4)
        self.source = QComboBox()
        self.source.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.source.setMinimumContentsLength(10)
        self.source.currentIndexChanged.connect(self._preset)
        form.addRow("Template part:",self.source)
        self.target = QComboBox()
        self.target.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.target.setMinimumContentsLength(10)
        self.target.setEditable(True)
        self.target.setToolTip("Use the exact exported submesh name. Names are never matched approximately.")
        form.addRow("Target part:",self.target)
        row = QHBoxLayout()
        self.slots = tuple(QSpinBox() for _ in range(3))
        for channel,box in zip("RGB",self.slots):
            box.setRange(-1,11)
            box.setSpecialValueText("None")
            row.addWidget(QLabel(channel))
            row.addWidget(box)
        form.addRow(row)
        self.mask = QLineEdit()
        self.mask.setPlaceholderText("Optional RGB mask DDS for this part's UVs")
        button = QPushButton("DDS…")
        button.clicked.connect(self._mask)
        row = QHBoxLayout()
        row.addWidget(self.mask,1)
        row.addWidget(button)
        form.addRow("Mask:",row)
        layout.addLayout(form)
        row = QHBoxLayout()
        self.add = QPushButton("Set mapping")
        self.add.clicked.connect(self._add)
        row.addWidget(self.add)
        self.remove = QPushButton("Remove mapping")
        self.remove.clicked.connect(self._remove)
        row.addWidget(self.remove)
        layout.addLayout(row)
        self.mappings = QListWidget()
        self.mappings.setMaximumHeight(64)
        layout.addWidget(self.mappings)
        row = QHBoxLayout()
        self.inherit = QPushButton("Inherit template dyes")
        self.inherit.clicked.connect(lambda:self._set(None))
        row.addWidget(self.inherit)
        self.clear = QPushButton("Clear dyes")
        self.clear.clicked.connect(lambda:self._set(()))
        row.addWidget(self.clear)
        layout.addLayout(row)
        self.preview = QPushButton("Preview dye material")
        self.preview.setCheckable(True)
        self.preview.toggled.connect(lambda _checked:panel.refresh_preview())
        layout.addWidget(self.preview)
        self.state = QLabel()
        self.state.setWordWrap(True)
        layout.addWidget(self.state)
        layout.addStretch(1)
        controller.authoring_index_ready.connect(self._ready)
        controller.authoring_index_failed.connect(self._failed)
        controller.snapshot_ready.connect(self._snapshot)
        controller.template_changed.connect(self.refresh)
        controller.variant_changed.connect(self.refresh)
        controller.busy_changed.connect(lambda busy:self.load.setEnabled(not busy))
        self.refresh()

    def _row(self):
        identity = self.controller.current_variant_identity()
        return self.index.rows.get(identity[1]) if self.index and identity else None

    def _values(self):
        identity = self.controller.current_variant_identity()
        state = self.controller._variant_states.get(identity)
        return state.appearance.dyes if state else None

    def _ready(self,kind,index):
        if kind=="dyes":
            self.index=index
            self.refresh()

    def _failed(self,kind,message):
        if kind=="dyes":
            self.state.setText(message)

    def _snapshot(self):
        self.index=None
        self.refresh()

    def refresh(self,*_):
        row = self._row()
        self.source.clear()
        self.target.clear()
        if row:
            for part in row.submeshes:
                self.source.addItem(part.name,part.name)
                self.target.addItem(part.name)
            result = self.controller.model_result
            # Read the applied builder's small in-memory material document. Its
            # exact exported names are authoritative, unlike preview labels.
            payloads = dict(getattr(result,"side_files",{}) or {})
            for supplemental in getattr(result,"supplemental_file_specs",()) or ():
                data = getattr(supplemental,"payload_data",b"")
                if data:
                    payloads[str(supplemental.target_path)] = data
            from cdmw.services.new_item_dyes import material_dye_bindings
            names = set()
            for path,data in payloads.items():
                if str(path).casefold().endswith(".pac_xml") and isinstance(data,bytes):
                    try:
                        names.update(name for _index,name in material_dye_bindings(data))
                    except ValueError:
                        continue
            for name in sorted(names):
                if self.target.findText(name)<0:
                    self.target.addItem(name)
        self._preset()
        self.mappings.clear()
        values=self._values()
        for value in values or ():
            self.mappings.addItem(f"{value.target_submesh} ← {value.source_submesh} · RGB {value.slots}")
        self.add.setEnabled(row is not None)
        self.state.setText("Template assignments inherited." if values is None else f"{len(values)} explicit dye mapping(s).")

    def _preset(self):
        row=self._row()
        part=next((part for part in row.submeshes if part.name==self.source.currentData()),None) if row else None
        if part:
            self.target.setCurrentText(part.name)
            for box,value in zip(self.slots,part.slots):
                box.setValue(value)
            self.source.setToolTip(f"Materials: {', '.join(part.default.tags)}; property overrides: {len(part.overrides)}")

    def _mask(self):
        path,_=QFileDialog.getOpenFileName(self,"Choose a dye RGB mask",self.mask.text(),"DDS masks (*.dds)")
        if path:
            self.mask.setText(path)

    def _set(self,values):
        try:
            self.controller.set_variant_dyes(values)
            self.controller.draft.authoring_errors.pop("dyes",None)
            self.refresh()
            if self.preview.isChecked():
                self.panel.refresh_preview()
        except ValueError as exc:
            self.state.setText(str(exc))

    def _add(self):
        if self.source.currentData() is None or not self.target.currentText().strip():
            return
        assignment=DyeAssignment(self.target.currentText().strip(),self.source.currentData(),tuple(box.value() for box in self.slots),self.mask.text().strip())
        values=self._values()
        if values is None:
            values=tuple(DyeAssignment(part.name,part.name,part.slots) for part in self._row().submeshes)
        self._set(tuple(value for value in values if value.target_submesh!=assignment.target_submesh)+(assignment,))

    def _remove(self):
        values=list(self._values() or ())
        at=self.mappings.currentRow()
        if 0<=at<len(values):
            values.pop(at)
            self._set(tuple(values))
