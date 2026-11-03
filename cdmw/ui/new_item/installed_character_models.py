"""Guided, read-only installed-model picker for the Model & Placement step."""
from pathlib import Path

from PySide6.QtCore import QSettings, QSignalBlocker, QTimer, Qt, Signal
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QFileDialog, QGroupBox,
    QHBoxLayout, QHeaderView, QLabel, QLineEdit, QPlainTextEdit, QPushButton, QToolButton, QTreeWidget, QTreeWidgetItem,
    QVBoxLayout, QWidget)

from cdmw.services.active_ui_translation import translate_active_ui_text as tr
from cdmw.domain.new_item.installed_model_category import character_model_category
from cdmw.services.dmm_character_mods import character_model_paths, scan_character_library
from cdmw.services.dmm_character_models import InstalledCharacterModel
from cdmw.services.dmm_send import DMM_FOLDER_SETTING
from cdmw.services.settings_service import resolve_settings_file_path

CATEGORIES = {
    'chest': 'Chest armor', 'legs': 'Leg armor', 'gloves': 'Gloves', 'boots': 'Boots',
    'helmets': 'Helmets', 'shoulders': 'Shoulders', 'cloaks': 'Cloaks',
    'accessories': 'Accessories', 'head': 'Head & hair', 'body': 'Body', 'other': 'Other parts',
}


def _category_label(key):
    return {'chest': tr('Chest armor'), 'legs': tr('Leg armor'), 'gloves': tr('Gloves'),
            'boots': tr('Boots'), 'helmets': tr('Helmets'), 'shoulders': tr('Shoulders'),
            'cloaks': tr('Cloaks'), 'accessories': tr('Accessories'), 'head': tr('Head & hair'),
            'body': tr('Body'), 'other': tr('Other parts')}[key]


class InstalledCharacterModels(QDialog):
    loaded = Signal()

    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Installed character models (local test)')
        self.resize(1080, 720)
        self.controller = controller
        self.library = None
        self._paths = ()
        self._names = {}
        self._unresolved = ()
        self._models_snapshot = None
        self._loading = False
        self._open = False
        self._template_category = 'other'
        self._settings = QSettings(str(resolve_settings_file_path()), QSettings.Format.IniFormat)
        self._saved = str(self._settings.value(DMM_FOLDER_SETTING, '') or '')
        self._scan = controller.create_lookup_lane()
        self._models = controller.create_lookup_lane()
        self._scan.completed.connect(self._scanned)
        self._scan.failed.connect(self._scan_failed)
        self._models.completed.connect(self._models_ready)
        self._models.failed.connect(self._models_failed)
        layout = QVBoxLayout(self)
        layout.setSpacing(10)
        self.context = QLabel()
        self.context.setTextFormat(Qt.TextFormat.PlainText)
        self.context.setWordWrap(True)
        layout.addWidget(self.context)
        self.note = QLabel('Preview and fitting only. Installed models and textures are never included in your item. Import your own model to export it.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        source = QGroupBox('Installed mod')
        source_layout = QVBoxLayout(source)
        row = QHBoxLayout()
        self.collection = QComboBox()
        self.collection.setMinimumContentsLength(24)
        self.collection.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.collection.currentIndexChanged.connect(self._collection_changed)
        row.addWidget(self.collection, 1)
        self.refresh_button = QPushButton('Refresh DMM')
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        self.choose_button = QPushButton('Choose DMM folder…')
        self.choose_button.clicked.connect(self._choose)
        row.addWidget(self.choose_button)
        source_layout.addLayout(row)
        self.source_note = QLabel()
        self.source_note.setWordWrap(True)
        source_layout.addWidget(self.source_note)
        layout.addWidget(source)
        row = QHBoxLayout()
        row.addWidget(QLabel('Part'))
        self.category = QComboBox()
        self.category.currentIndexChanged.connect(self._filter)
        row.addWidget(self.category)
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Search item name or model ID')
        self.filter.textChanged.connect(self._filter)
        row.addWidget(self.filter, 1)
        layout.addLayout(row)
        self.models = QTreeWidget()
        self.models.setHeaderLabels(['Item', 'Part', 'Model ID'])
        self.models.setRootIsDecorated(False)
        self.models.setSelectionMode(QAbstractItemView.SingleSelection)
        self.models.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.models.setMinimumHeight(220)
        self.models.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.models.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.models.header().setSectionResizeMode(2, QHeaderView.Interactive)
        self.models.setColumnWidth(2, 290)
        self.models.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.models, 1)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        details = QGroupBox('Selected model')
        details_layout = QVBoxLayout(details)
        self.selection = QLabel('Select a model to see its details.')
        self.selection.setTextFormat(Qt.TextFormat.PlainText)
        self.selection.setWordWrap(True)
        details_layout.addWidget(self.selection)
        self.guidance = QLabel()
        self.guidance.setWordWrap(True)
        details_layout.addWidget(self.guidance)
        layout.addWidget(details)
        self.feedback = QLabel()
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        self.feedback.setWordWrap(True)
        self.feedback.setVisible(False)
        layout.addWidget(self.feedback)
        self.details_button = QToolButton()
        self.details_button.setText('Details')
        self.details_button.setCheckable(True)
        self.details_button.setVisible(False)
        layout.addWidget(self.details_button)
        self.error_details = QPlainTextEdit()
        self.error_details.setReadOnly(True)
        self.error_details.setMaximumHeight(120)
        self.error_details.setVisible(False)
        layout.addWidget(self.error_details)
        self.details_button.toggled.connect(self.error_details.setVisible)
        self.modules = QLabel()
        self.modules.setWordWrap(True)
        layout.addWidget(self.modules)
        row = QHBoxLayout()
        self.close_button = QPushButton('Close')
        self.close_button.clicked.connect(self.reject)
        row.addWidget(self.close_button)
        row.addStretch(1)
        self.load_button = QPushButton('Show fitting reference')
        self.load_button.clicked.connect(self._load)
        row.addWidget(self.load_button)
        layout.addLayout(row)
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self.refresh)
        controller.snapshot_ready.connect(self._snapshot_ready)
        controller.busy_changed.connect(self._enabled)
        controller.template_changed.connect(self._template_changed)
        controller.installed_reference_changed.connect(self._import_ready)
        controller.installed_reference_failed.connect(self._import_failed)
        self.finished.connect(self._closed)
        self._template_changed()

    def open(self):
        self._open = True
        self._template_changed()
        super().open()
        self._timer.start()
        self.refresh()

    def _closed(self, *_args):
        self._open = False
        self._timer.stop()
        self._scan.cancel()
        self._models.cancel()
        # Closing the picker cancels only the import it started. The controller
        # retains the previous usable source until a complete result is accepted.
        if self._loading:
            self.controller.cancel_operation('installed_reference')
        self._loading = False
        self._models_snapshot = None

    def refresh(self, *_args):
        if not self._open or self.controller._shutdown_requested or self.controller.busy or self._scan.busy:
            return
        saved = self._saved
        self._scan.request(saved, lambda stop: scan_character_library(saved, stop_event=stop))

    def _snapshot_ready(self):
        self._models_snapshot = None
        self.refresh()

    def _template_changed(self, *_args):
        entry = self.controller.template_primary_entry() if self.controller.snapshot is not None else None
        self._template_category = character_model_category(entry.path) if entry is not None else 'other'
        snapshot, key = self.controller.snapshot, self.controller.draft.template_key
        name = snapshot.item_display_names().get(key, '') if snapshot is not None else ''
        if not name and snapshot is not None and key is not None:
            name = snapshot.row(key).string_key
        self.context.setText(tr('For {item} · {part}').format(item=name or tr('No template selected'),
            part=_category_label(self._template_category)))
        self._categories()
        self._enabled()

    def _choose(self):
        folder = QFileDialog.getExistingDirectory(self, tr('Choose DMM folder…'), self._saved)
        if folder:
            self._saved = folder
            self._scan.request(folder, lambda stop: scan_character_library(folder, stop_event=stop))

    def _scanned(self, saved, library):
        if not self._open or saved != self._saved:
            return
        changed = self.library is None or library.identity != self.library.identity
        self._settings.setValue(DMM_FOLDER_SETTING, str(library.install))
        if not changed and self._models_snapshot is self.controller.snapshot:
            return
        previous = self.collection.currentData()
        if self.library is not None and changed:
            if self.controller.installed_reference is not None:
                self.controller.clear_installed_reference()
                self._message(tr('Installed files changed. Choose the fitting reference again.'))
        self.library = library
        self.modules.setText(tr('Installed files can be browsed before mounting. Game fit and equipping still need testing.'))
        self.modules.setToolTip(tr('DMM selection — Equip All Armor: {armor}; CharacterCreator.asi: {creator}.').format(
            armor=tr('Selected in DMM') if library.equip_all_selected else tr('Not selected'),
            creator=tr('Selected in DMM') if library.creator_asi_selected else tr('Not selected')))
        with QSignalBlocker(self.collection):
            self.collection.clear()
            mods = sorted((m for m in library.mods if m.kind in {'creator', 'fit', 'module'}),
                          key=lambda m: ({'fit': 0, 'module': 1, 'creator': 2}[m.kind], m.title))
            for mod in mods:
                state = tr('Selected in DMM') if mod.selected else tr('Installed only')
                self.collection.addItem(f'{mod.title} {mod.version} · {state}', mod.identifier)
            index = self.collection.findData(previous)
            if index >= 0:
                self.collection.setCurrentIndex(index)
        self._collection_changed()

    def _collection_changed(self, *_args):
        self._paths, self._unresolved, self._names = (), (), {}
        self.models.clear()
        self._models.cancel()
        library, identifier, snapshot = self.library, self.collection.currentData(), self.controller.snapshot
        self._enabled()
        if library is None or identifier is None:
            self.status.setText(tr('No supported character mods are installed in this DMM library.'))
            return
        kind = library.mod(identifier).kind
        if kind == 'fit':
            note = tr('Refitted armor. Choose the part matching your template. Female Armor Fit and Female Armor Module are alternative sources.')
        elif kind == 'module':
            note = tr('Models named by Female Armor Module’s replacement rules. Loading one does not apply its automatic body-fitting rules.')
        else:
            note = tr('Character Creator includes individual character parts. These are not complete armor outfits.')
        self.source_note.setText(note)
        self.status.setText(tr('Reading installed models…'))
        key = (library.identity, identifier, id(snapshot))
        self._models.request(key, lambda stop: character_model_paths(library, identifier, snapshot, stop_event=stop))

    def _models_ready(self, key, catalogue):
        if not self._open or self.library is None or key != (self.library.identity, self.collection.currentData(), id(self.controller.snapshot)):
            return
        self._models_snapshot = self.controller.snapshot
        self._paths, self._unresolved = catalogue.paths, catalogue.unresolved
        self._names = dict(catalogue.item_names)
        self._categories()

    def _categories(self):
        with QSignalBlocker(self.category):
            self.category.clear()
            self.category.addItem(tr('All parts'), '')
            present = {character_model_category(p) for p in self._paths} | {self._template_category}
            for key in CATEGORIES:
                if key in present:
                    self.category.addItem(_category_label(key), key)
            self.category.setCurrentIndex(max(0, self.category.findData(self._template_category))
                                          if self._template_category != 'other' else 0)
        self._filter()

    def _selected_path(self):
        item = self.models.currentItem()
        return item.data(0, Qt.UserRole) if item is not None else None

    def _filter(self, *_args):
        previous = self._selected_path()
        words = self.filter.text().casefold().split()
        category = self.category.currentData()
        paths = [p for p in self._paths if (not category or character_model_category(p) == category)
                 and all(w in (p + ' ' + ' '.join(self._names.get(p, ()))).casefold() for w in words)]
        with QSignalBlocker(self.models):
            self.models.clear()
            for path in sorted(paths, key=lambda p: (not bool(self._names.get(p)), self._names.get(p, ()), p)):
                names = self._names.get(path, ())
                item = QTreeWidgetItem([names[0] if names else tr('Unnamed model'),
                    _category_label(character_model_category(path)), Path(path).stem])
                item.setData(0, Qt.UserRole, path)
                item.setToolTip(0, '\n'.join(names))
                self.models.addTopLevelItem(item)
                if path == previous:
                    self.models.setCurrentItem(item)
        self.status.setText(tr('{count} models').format(count=len(paths)) if paths else
            tr('No models match this part. Try another installed mod, part or search.'))
        if self._unresolved:
            self.status.setText(self.status.text() + '\n' + tr('{count} replacements could not be resolved against the loaded game. They are unavailable.').format(count=len(self._unresolved)))
        self.status.setToolTip('\n'.join(self._unresolved))
        self._selection_changed()

    def _selection_changed(self, *_args):
        path = self._selected_path()
        if path is None:
            self.selection.setText(tr('Select a model to see its details.'))
            self.guidance.clear()
        else:
            names = self._names.get(path, ())
            self.selection.setText((' · '.join(names[:3]) + ('…' if len(names) > 3 else '') if names else tr('Unnamed model')) + '\n' + path)
            mismatch = self._template_category != 'other' and character_model_category(path) != self._template_category
            self.guidance.setText(tr('Choose {part} for this template. This model belongs to a different part.').format(
                part=_category_label(self._template_category)) if mismatch else
                tr('Compare this reference with your item in the preview. It does not change who can wear the item or apply automatic fitting.'))
        self._enabled()

    def _enabled(self, *_args):
        ready = not self.controller.busy and self.controller.snapshot is not None and self.controller.draft.template_key is not None
        path = self._selected_path()
        match = path is not None and (self._template_category == 'other' or character_model_category(path) == self._template_category)
        self.load_button.setEnabled(ready and match and not self._loading)
        for widget in (self.choose_button, self.refresh_button, self.collection, self.category, self.filter, self.models):
            widget.setEnabled(not self.controller.busy and not self._loading)

    def _scan_failed(self, saved, message):
        if self._open and saved == self._saved:
            self.library = None
            with QSignalBlocker(self.collection):
                self.collection.clear()
            self.source_note.clear()
            self._failed(message)

    def _models_failed(self, key, message):
        if self._open and self.library is not None and key == (self.library.identity, self.collection.currentData(), id(self.controller.snapshot)):
            self._failed(message)

    def _failed(self, message):
        self._paths, self._names = (), {}
        self._models_snapshot = None
        self.models.clear()
        self.status.setText(tr(message))
        self._selection_changed()

    def _message(self, text, detail=''):
        self.feedback.setText(text)
        self.feedback.setVisible(bool(text))
        self.error_details.setPlainText(detail)
        self.details_button.setChecked(False)
        self.details_button.setVisible(bool(detail))
        self.error_details.setVisible(False)

    def _load(self):
        path = self._selected_path()
        if not self.load_button.isEnabled() or self.library is None or path is None:
            return
        self._loading = True
        self._message(tr('Loading fitting reference…'))
        self._enabled()
        request = InstalledCharacterModel(self.library, self.collection.currentData(), path)
        if not self.controller.start_installed_reference(request) and self._loading:
            self._import_failed('')

    def _import_failed(self, message):
        if not self._loading:
            return
        self._loading = False
        self._message(tr('Could not load this model. Your current model is unchanged.'), str(message))
        self._enabled()

    def _import_ready(self, source):
        if not self._loading or source is None:
            return
        self._loading = False
        self._message('')
        self.loaded.emit()
        self.accept()
