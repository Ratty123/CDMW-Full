"""Layer composition, emitter overrides and saved variants in a compact inspector."""
from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import QSettings, QSize, Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTabWidget, QListWidget, QListWidgetItem, QSizePolicy,
    QPushButton, QComboBox, QCheckBox, QDoubleSpinBox, QTableWidget, QHeaderView,
    QTableWidgetItem, QLineEdit, QLabel, QColorDialog, QInputDialog, QMessageBox, QFileDialog, QApplication,
)
from cdmw.domain.new_item.effect_authoring import EMITTER_FIELDS, INTEGER_FIELDS, VECTOR_FIELDS, EffectLayer, EmitterEdit
from cdmw.services.effect_library_store import recipe_json, read_recipe
from cdmw.ui.new_item.state import EffectWorkspaceState


class EffectUserLibrary:
    """Small Qt preference store; recipes refer to game resources by name only."""
    def __init__(self, cache_path=None):
        cache = Path(cache_path).resolve() if cache_path else None
        self.path = ((cache.parents[2] / 'libraries' / 'effects') if cache.parent.name == 'index' and cache.parent.parent.name == 'cache' else cache.parent / 'effects_library') if cache else None
        self.settings = QSettings(str(self.path / 'library.ini'), QSettings.Format.IniFormat) if self.path else None
        self.favourites = set(self.settings.value('favourites', [], type=list)) if self.settings else set()
        try:
            self.recipes = json.loads(str(self.settings.value('recipes', '{}'))) if self.settings else {}
            if not isinstance(self.recipes, dict):
                self.recipes = {}
        except (TypeError, ValueError):
            self.recipes = {}

    def save(self):
        if len(self.recipes) > 64 or sum(len(value) for value in self.recipes.values()) > 8_000_000:
            raise ValueError('Keep up to 64 saved recipes and 8 MB of recipe data in the local library.')
        if self.settings is not None:
            self.path.mkdir(parents=True, exist_ok=True)
            self.settings.setValue('favourites', sorted(self.favourites))
            self.settings.setValue('recipes', json.dumps(self.recipes, ensure_ascii=False))


class _RecipeTabs(QTabWidget):
    """Reserve height for the selected tools, including when inside a scroll area."""

    def sizeHint(self):
        page = self.currentWidget()
        height = page.sizeHint().height() if page is not None else 0
        return QSize(super().sizeHint().width(), height + self.tabBar().sizeHint().height() + 4)

    def minimumSizeHint(self):
        page = self.currentWidget()
        width = page.minimumSizeHint().width() if page is not None else 0
        return QSize(max(width, self.tabBar().minimumSizeHint().width()), self.sizeHint().height())

    def heightForWidth(self, width):
        page = self.currentWidget()
        if page is not None and page.hasHeightForWidth():
            return page.heightForWidth(width) + self.tabBar().sizeHint().height() + 4
        return self.sizeHint().height()


class EffectRecipePanel(QWidget):
    changed = Signal(object)
    preview_controls = Signal(object)

    def __init__(self, library: EffectUserLibrary, parent=None):
        super().__init__(parent)
        self.library = library
        self.state = EffectWorkspaceState()
        self.preview = None
        self.syncing = False
        self._fields = {}
        self._curve_colours = [(1., .25, .02), (1., .6, .1), (.25, .02, .01)]
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        tabs = _RecipeTabs()
        tabs.setObjectName('effect_recipe_tabs')
        tabs.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Fixed)
        tabs.currentChanged.connect(tabs.updateGeometry)
        layout.addWidget(tabs)

        layers = QWidget()
        col = QVBoxLayout(layers)
        col.setContentsMargins(0, 4, 0, 4)
        col.setSpacing(4)
        col.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.layers = QListWidget()
        self.layers.setFixedHeight(96)
        self.layers.currentRowChanged.connect(self._select_layer)
        self.layers.itemChanged.connect(self._layer_item_changed)
        col.addWidget(self.layers)
        row = QHBoxLayout()
        for title, callback in (('Add', self.add_layer), ('Duplicate', self.duplicate_layer), ('Remove', self.remove_layer)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch(1)
        col.addLayout(row)
        row = QHBoxLayout()
        for title, delta in (('Up', -1), ('Down', 1)):
            button = QPushButton(title)
            button.clicked.connect(lambda _=False, d=delta: self.move_layer(d))
            row.addWidget(button)
        self.solo_layer = QCheckBox('Solo layer')
        self.solo_layer.toggled.connect(lambda v: self.preview_controls.emit({'solo_layer': self.state.active_layer if v else -1}))
        row.addWidget(self.solo_layer)
        row.addStretch(1)
        col.addLayout(row)
        tabs.addTab(layers, 'Layers')

        emitter = QWidget()
        col = QVBoxLayout(emitter)
        col.setContentsMargins(0, 4, 0, 4)
        col.setSpacing(4)
        col.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.emitter = QComboBox()
        self.emitter.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.emitter.setMinimumContentsLength(12)
        self.emitter.currentIndexChanged.connect(self._show_emitter)
        col.addWidget(self.emitter)
        row = QHBoxLayout()
        self.emitter_enabled = QCheckBox('Enabled')
        self.emitter_enabled.toggled.connect(lambda _: self._edit())
        row.addWidget(self.emitter_enabled)
        self.solo_emitter = QCheckBox('Solo')
        self.solo_emitter.toggled.connect(lambda v: self.preview_controls.emit({'solo_emitter': self.emitter.currentIndex() if v else -1}))
        row.addWidget(self.solo_emitter)
        for title, remove in (('Duplicate', False), ('Remove', True)):
            button = QPushButton(title)
            button.clicked.connect(lambda _=False, r=remove: self._reorder_emitter(r))
            row.addWidget(button)
        col.addLayout(row)
        self.parameters = QTableWidget(0, 3)
        self.parameters.setHorizontalHeaderLabels(('Use', 'Property', 'Value'))
        self.parameters.verticalHeader().hide()
        self.parameters.setFixedHeight(240)
        self.parameters.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.parameters.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        self.parameters.setColumnWidth(1, 120)
        self.parameters.horizontalHeader().setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        self.parameters.itemChanged.connect(lambda _: self._edit())
        col.addWidget(self.parameters)
        row = QHBoxLayout()
        self.colour_curve = QCheckBox('Colour curve')
        self.colour_curve.toggled.connect(lambda _: self._edit())
        row.addWidget(self.colour_curve)
        self.colour_buttons = []
        for i, title in enumerate(('Start', 'Middle', 'End')):
            button = QPushButton(title)
            button.clicked.connect(lambda _=False, index=i: self._choose_colour(index))
            self.colour_buttons.append(button)
            row.addWidget(button)
        col.addLayout(row)
        self.curves = {}
        for key, title, maximum, initial in (('size_curve', 'Size curve', 20., (1.,1.,1.)), ('opacity_curve', 'Opacity curve', 1., (0.,1.,0.))):
            row = QHBoxLayout()
            row.setSpacing(2)
            check = QCheckBox(title)
            check.toggled.connect(lambda _: self._edit())
            row.addWidget(check)
            spins = []
            for value in initial:
                spin = QDoubleSpinBox()
                spin.setRange(0, maximum)
                spin.setValue(value)
                spin.setSingleStep(.1)
                spin.valueChanged.connect(lambda _, curve_key=key: self._curve_changed(curve_key))
                spins.append(spin)
                row.addWidget(spin)
            self.curves[key] = (check, spins)
            col.addLayout(row)
        self.texture = QLineEdit()
        self.texture.setPlaceholderText('Sprite DDS archive path (inherit when empty)')
        self.texture.editingFinished.connect(self._edit)
        col.addWidget(self.texture)
        self.emitter_status = QLabel('Select an effect to inspect its emitters.')
        self.emitter_status.setWordWrap(True)
        col.addWidget(self.emitter_status)
        actions = QHBoxLayout()
        reset = QPushButton('Reset emitter')
        reset.clicked.connect(self._reset_emitter)
        actions.addWidget(reset)
        tabs.addTab(emitter, 'Emitters')
        create = QPushButton('Create from this emitter')
        create.setToolTip('Start a custom effect using only this emitter as a template')
        create.clicked.connect(self.create_from_emitter)
        actions.addWidget(create)
        actions.addStretch(1)
        col.addLayout(actions)

        self._build_saved_tab(tabs)
        for button in self.findChildren(QPushButton):
            button.setSizePolicy(QSizePolicy.Policy.Maximum, QSizePolicy.Policy.Fixed)
        self._refresh_saved()

    def _build_saved_tab(self, tabs: QTabWidget) -> None:
        saved = QWidget()
        col = QVBoxLayout(saved)
        col.setContentsMargins(0, 4, 0, 4)
        col.setSpacing(4)
        col.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.saved = QComboBox()
        self.saved.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
        self.saved.setMinimumContentsLength(12)
        col.addWidget(self.saved)
        row = QHBoxLayout()
        for title, callback in (('Load', self.load_recipe), ('Save as…', self.save_recipe), ('Delete', self.delete_recipe)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch(1)
        col.addLayout(row)
        label = QLabel('Saved effects retain all layers, placements and emitter settings.')
        label.setWordWrap(True)
        col.addWidget(label)
        row = QHBoxLayout()
        for title, callback in (('Import recipe…', self.import_recipe), ('Export recipe…', self.export_recipe)):
            button = QPushButton(title)
            button.clicked.connect(callback)
            row.addWidget(button)
        row.addStretch(1)
        col.addLayout(row)
        tabs.addTab(saved, 'Saved')

    def set_state(self, state):
        self.state = state
        self.syncing = True
        self.layers.clear()
        for layer in state.resolved_layers():
            item = QListWidgetItem(layer.name or layer.stem)
            item.setToolTip(layer.stem)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEditable)
            item.setCheckState(Qt.CheckState.Checked if layer.enabled else Qt.CheckState.Unchecked)
            self.layers.addItem(item)
        self.layers.setCurrentRow(state.active_layer)
        self.syncing = False

    def set_preview(self, preview):
        if preview is None:
            self.solo_emitter.setChecked(False)
        focus = QApplication.focusWidget()
        editing = focus is not None and (self.parameters.isAncestorOf(focus) or focus == self.texture or any(focus in pair[1] for pair in self.curves.values()))
        self.preview = preview
        self.syncing = True
        index = self.emitter.currentIndex()
        self.emitter.clear()
        for slot in getattr(preview, 'editor_emitters', ()):
            self.emitter.addItem(slot['name'].rsplit('/', 1)[-1], slot)
        self.emitter.setCurrentIndex(max(0, min(index, self.emitter.count() - 1)))
        self.syncing = False
        if preview is None or not editing:
            self._show_emitter()

    def _publish(self, layers, index=None):
        self.changed.emit(EffectWorkspaceState.from_layers(tuple(layers), self.state.active_layer if index is None else index))

    def _select_layer(self, index):
        if not self.syncing and index >= 0:
            self._publish(self.state.resolved_layers(), index)
            self.preview_controls.emit({'active_layer': index, 'solo_layer': index if self.solo_layer.isChecked() else -1, 'solo_emitter': -1})

    def _layer_item_changed(self, item):
        if self.syncing:
            return
        layers = list(self.state.resolved_layers())
        index = self.layers.row(item)
        layers[index] = replace(layers[index], name=item.text()[:128], enabled=item.checkState() == Qt.CheckState.Checked)
        self._publish(layers)

    def add_layer(self):
        layers = self.state.resolved_layers()
        if len(layers) < 16 and self.state.stem:
            self._publish((*layers, EffectLayer(self.state.stem, kind=layers[self.state.active_layer].kind)), len(layers))

    def duplicate_layer(self):
        layers = self.state.resolved_layers()
        if layers and len(layers) < 16:
            self._publish((*layers, replace(layers[self.state.active_layer], name='Copy')), len(layers))

    def remove_layer(self):
        layers = list(self.state.resolved_layers())
        if layers:
            del layers[self.state.active_layer]
            self._publish(layers)

    def move_layer(self, delta):
        layers = list(self.state.resolved_layers())
        i, j = self.state.active_layer, self.state.active_layer + delta
        if 0 <= j < len(layers):
            layers[i], layers[j] = layers[j], layers[i]
            self._publish(layers, j)

    def _show_emitter(self, *_):
        if self.syncing:
            return
        slot = self.emitter.currentData() or {}
        self.syncing = True
        index = self.emitter.currentIndex()
        edit = next((e for e in self.state.emitter_edits if e.index == index), EmitterEdit(max(0,index), enabled=slot.get('enabled', True)))
        self.emitter_enabled.setChecked(edit.enabled)
        self.parameters.setRowCount(0)
        self._fields.clear()
        values = dict(edit.values)
        descriptions = [(k,l,lo,hi,d,1) for k,l,lo,hi,d in EMITTER_FIELDS]
        descriptions += [(k,l,-1000.,1000.,0.,3) for k,l in VECTOR_FIELDS]
        descriptions += [(k, label, .05,20.,1.,1) for k,label in (('intensity','Brightness factor'), ('size','Size factor'), ('rate','Spawn factor'), ('lifetime','Lifetime factor'))]
        for key, label, low, high, default, dimensions in descriptions:
            row = self.parameters.rowCount()
            self.parameters.insertRow(row)
            check = QTableWidgetItem()
            check.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsUserCheckable)
            current = values.get(key)
            if not key.startswith('_') and getattr(edit,key) != 1:
                current = (getattr(edit,key),)
            check.setCheckState(Qt.CheckState.Checked if current else Qt.CheckState.Unchecked)
            supported = bool(slot.get('resolved')) and (not key.startswith('_') or key in slot.get('fields',()))
            if not supported:
                check.setFlags(Qt.ItemFlag.NoItemFlags)
            self.parameters.setItem(row,0,check)
            item = QTableWidgetItem(label)
            item.setFlags(Qt.ItemFlag.ItemIsEnabled)
            item.setToolTip(label)
            self.parameters.setItem(row,1,item)
            holder = QWidget()
            line = QVBoxLayout(holder) if dimensions > 1 else QHBoxLayout(holder)
            line.setContentsMargins(0,0,0,0)
            line.setSpacing(1)
            spins=[]
            for axis in range(dimensions):
                spin=QDoubleSpinBox()
                spin.setRange(low,high)
                spin.setDecimals(0 if key in INTEGER_FIELDS else 3)
                if dimensions > 1:
                    spin.setPrefix(('X ', 'Y ', 'Z ')[axis])
                inherited = slot.get('values', {}).get(key, ())
                spin.setValue(current[axis] if current else (inherited[axis] if axis < len(inherited) else default))
                spin.setEnabled(supported)
                spin.valueChanged.connect(lambda _, r=row: self._field_changed(r))
                line.addWidget(spin)
                spins.append(spin)
            self.parameters.setCellWidget(row,2,holder)
            self.parameters.setRowHeight(row, holder.sizeHint().height() + 2)
            self._fields[key]=(check,spins)
        self.colour_curve.setChecked(bool(edit.color_curve))
        if edit.color_curve:
            self._curve_colours = [edit.color_curve[0],edit.color_curve[len(edit.color_curve)//2],edit.color_curve[-1]]
        else:
            self._curve_colours = [(1.,1.,1.)] * 3
        for key,(check,spins) in self.curves.items():
            curve=getattr(edit,key)
            check.setChecked(bool(curve))
            if curve:
                for spin,value in zip(spins,(curve[0],curve[len(curve)//2],curve[-1])):
                    spin.setValue(value)
            else:
                for spin,value in zip(spins,(1.,1.,1.) if key == 'size_curve' else (0.,1.,0.)):
                    spin.setValue(value)
        self.texture.setText(edit.texture)
        resolved = bool(slot.get('resolved'))
        for control in (self.emitter_enabled,self.colour_curve,self.texture,*[x[0] for x in self.curves.values()]):
            control.setEnabled(resolved)
        for _check, spins in self.curves.values():
            for spin in spins:
                spin.setEnabled(resolved)
        self.emitter_status.setText('Editing this emitter’s exported data.' if resolved else 'Emitter dependencies are unresolved; this emitter cannot be edited.')
        self.syncing=False
        self._update_colour_buttons()
        if self.solo_emitter.isChecked():
            self.preview_controls.emit({'solo_emitter': index})

    def _field_changed(self,row):
        if self.syncing:
            return
        self.syncing=True
        self.parameters.item(row,0).setCheckState(Qt.CheckState.Checked)
        self.syncing=False
        self._edit()

    def _curve_changed(self, key):
        if not self.syncing:
            self.syncing = True
            self.curves[key][0].setChecked(True)
            self.syncing = False
            self._edit(curve_changed=key)

    def _edit(self, *, curve_changed=None):
        if self.syncing or self.emitter.currentIndex()<0:
            return
        index=self.emitter.currentIndex()
        previous=next((e for e in self.state.emitter_edits if e.index==index),EmitterEdit(index))
        fields={k:tuple(s.value() for s in spins) for k,(check,spins) in self._fields.items() if check.checkState()==Qt.CheckState.Checked}
        factors={k:fields.pop(k,(1.,))[0] for k in ('intensity','size','rate','lifetime')}
        # Imported recipes can carry 128 samples. Only editing that curve's
        # controls replaces it with the three visible stops.
        curves={k:(getattr(previous,k) if getattr(previous,k) and curve_changed != k else tuple(s.value() for s in spins)) if check.isChecked() else () for k,(check,spins) in self.curves.items()}
        colours = previous.color_curve if previous.color_curve and curve_changed != 'color_curve' else tuple(self._curve_colours)
        edit=replace(previous,enabled=self.emitter_enabled.isChecked(),values=tuple(fields.items()),color_curve=colours if self.colour_curve.isChecked() else (),texture=self.texture.text().strip(),**factors,**curves)
        self.changed.emit(replace(self.state,emitter_edits=tuple(e for e in self.state.emitter_edits if e.index!=index)+(edit,)))

    def _choose_colour(self,index):
        chosen=QColorDialog.getColor(QColor.fromRgbF(*self._curve_colours[index]),self,'Emitter colour')
        if chosen.isValid():
            self._curve_colours[index]=(chosen.redF(),chosen.greenF(),chosen.blueF())
            self._update_colour_buttons()
            self.colour_curve.blockSignals(True)
            self.colour_curve.setChecked(True)
            self.colour_curve.blockSignals(False)
            self._edit(curve_changed='color_curve')

    def _reset_emitter(self):
        self.changed.emit(replace(self.state,emitter_edits=tuple(e for e in self.state.emitter_edits if e.index!=self.emitter.currentIndex())))

    def _update_colour_buttons(self):
        for button, colour in zip(self.colour_buttons, self._curve_colours):
            tint = QColor.fromRgbF(*colour)
            button.setStyleSheet(f'border-bottom: 4px solid {tint.name()};')
            button.setEnabled(bool((self.emitter.currentData() or {}).get('resolved')))

    def create_from_emitter(self):
        index = self.emitter.currentIndex()
        if index < 0:
            return
        source_index = self.state.emitter_order[index] if self.state.emitter_order is not None else index
        edits = tuple(replace(edit, index=0) for edit in self.state.emitter_edits if edit.index == index)
        layer = self.state.resolved_layers()[self.state.active_layer]
        layer = replace(layer, name='Custom effect', look=replace(layer.look, emitter_order=(source_index,), emitters=edits))
        self._publish((layer,), 0)

    def import_recipe(self):
        path, _ = QFileDialog.getOpenFileName(self, 'Import effect recipe', '', 'Effect recipe (*.json)')
        if path:
            try:
                if Path(path).stat().st_size > 2_000_000:
                    raise ValueError('Effect recipe exceeds 2 MB.')
                self._publish(read_recipe(Path(path).read_text(encoding='utf-8')), 0)
            except (OSError, KeyError, TypeError, ValueError) as exc:
                QMessageBox.warning(self, 'Effect could not be loaded', str(exc))

    def export_recipe(self):
        path, _ = QFileDialog.getSaveFileName(self, 'Export effect recipe', 'effect-recipe.json', 'Effect recipe (*.json)')
        if path:
            try:
                text = recipe_json(self.state.resolved_layers())
                from cdmw.services.effect_library_store import write_recipe
                write_recipe(Path(path), text)
            except (OSError, TypeError, ValueError) as exc:
                QMessageBox.warning(self, 'Effect could not be saved', str(exc))

    def _reorder_emitter(self,remove):
        index=self.emitter.currentIndex()
        if index<0:
            return
        order=list(self.state.emitter_order if self.state.emitter_order is not None else range(self.emitter.count()))
        edits=list(self.state.emitter_edits)
        if remove:
            del order[index]
            edits=[replace(e,index=e.index-(e.index>index)) for e in edits if e.index!=index]
        elif len(order)<128:
            order.append(order[index])
            old=next((e for e in edits if e.index==index),None)
            if old:
                edits.append(replace(old,index=len(order)-1))
        self.changed.emit(replace(self.state,emitter_order=tuple(order),emitter_edits=tuple(edits)))

    def _refresh_saved(self):
        self.saved.clear()
        self.saved.addItems(sorted(self.library.recipes))

    def save_recipe(self):
        name,ok=QInputDialog.getText(self,'Save effect','Name')
        if ok and name.strip():
            previous = self.library.recipes.copy()
            try:
                self.library.recipes[name.strip()[:128]]=recipe_json(self.state.resolved_layers())
                self.library.save()
                self._refresh_saved()
            except (TypeError,ValueError,OSError) as exc:
                self.library.recipes = previous
                QMessageBox.warning(self,'Effect could not be saved',str(exc))

    def load_recipe(self):
        text=self.library.recipes.get(self.saved.currentText())
        if text:
            try:
                self._publish(read_recipe(text),0)
            except (KeyError,TypeError,ValueError) as exc:
                QMessageBox.warning(self,'Effect could not be loaded',str(exc))

    def delete_recipe(self):
        self.library.recipes.pop(self.saved.currentText(),None)
        self.library.save()
        self._refresh_saved()
