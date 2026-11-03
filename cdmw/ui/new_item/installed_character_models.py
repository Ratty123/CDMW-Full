"""Private-test model picker backed by the current DMM library."""
from pathlib import Path

from PySide6.QtCore import QSettings, QSignalBlocker, QTimer
from PySide6.QtWidgets import QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from cdmw.services.active_ui_translation import translate_active_ui_text as tr
from cdmw.services.dmm_character_mods import character_model_paths, scan_character_library
from cdmw.services.dmm_character_models import InstalledCharacterModel
from cdmw.services.dmm_send import DMM_FOLDER_SETTING
from cdmw.services.settings_service import resolve_settings_file_path


class InstalledCharacterModels(QGroupBox):
    def __init__(self, controller, parent=None):
        super().__init__(parent)
        self.setTitle('Installed character models (local test)')
        self.controller = controller
        self.library = None
        self._paths = ()
        self._unresolved = ()
        self._models_snapshot = None
        self._settings = QSettings(str(resolve_settings_file_path()), QSettings.Format.IniFormat)
        self._saved = str(self._settings.value(DMM_FOLDER_SETTING, '') or '')
        self._scan = controller.create_lookup_lane()
        self._models = controller.create_lookup_lane()
        self._scan.completed.connect(self._scanned)
        self._scan.failed.connect(self._failed)
        self._models.completed.connect(self._models_ready)
        self._models.failed.connect(self._failed)
        layout = QVBoxLayout(self)
        self.note = QLabel('Reads installed files. Fit and Module are alternatives. Selection in DMM does not confirm a mount. Character Creator body profiles and in-game fit are not verified here.')
        self.note.setWordWrap(True)
        layout.addWidget(self.note)
        row = QHBoxLayout()
        self.collection = QComboBox()
        self.collection.setMinimumContentsLength(18)
        self.collection.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        self.collection.currentIndexChanged.connect(self._collection_changed)
        row.addWidget(self.collection, 1)
        self.refresh_button = QPushButton('Refresh DMM')
        self.refresh_button.clicked.connect(self.refresh)
        row.addWidget(self.refresh_button)
        self.choose_button = QPushButton('Choose DMM folder…')
        self.choose_button.clicked.connect(self._choose)
        row.addWidget(self.choose_button)
        layout.addLayout(row)
        row = QHBoxLayout()
        self.filter = QLineEdit()
        self.filter.setPlaceholderText('Find an installed model')
        self.filter.textChanged.connect(self._filter)
        row.addWidget(self.filter)
        self.models = QComboBox()
        self.models.setMinimumContentsLength(18)
        self.models.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
        row.addWidget(self.models, 1)
        self.load_button = QPushButton('Load selected model')
        self.load_button.clicked.connect(self._load)
        row.addWidget(self.load_button)
        layout.addLayout(row)
        self.status = QLabel()
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.modules = QLabel()
        self.modules.setWordWrap(True)
        layout.addWidget(self.modules)
        self._timer = QTimer(self)
        self._timer.setInterval(15000)
        self._timer.timeout.connect(self.refresh)
        controller.snapshot_ready.connect(self._snapshot_ready)
        controller.busy_changed.connect(self._enabled)
        controller.template_changed.connect(self._enabled)
        self.models.currentIndexChanged.connect(self._enabled)
        self._enabled()
        # Synchronous controllers belong to headless tests: they request scans
        # explicitly instead of touching the user's installed mods at construction.
        if not controller._synchronous:
            self._timer.start()
            QTimer.singleShot(0, self.refresh)

    def refresh(self, *_args):
        if self.controller._shutdown_requested or self.controller.busy or self._scan.busy:
            return
        saved = self._saved
        self._scan.request(saved, lambda stop: scan_character_library(saved, stop_event=stop))

    def _snapshot_ready(self):
        if not self.controller._synchronous or self.library is not None:
            QTimer.singleShot(0, self.refresh)

    def _choose(self):
        folder = QFileDialog.getExistingDirectory(self, tr('Choose DMM folder…'), self._saved)
        if folder:
            self._saved = folder
            self._scan.request(folder, lambda stop: scan_character_library(folder, stop_event=stop))

    def _scanned(self, saved, library):
        if saved != self._saved:
            return
        changed = self.library is None or library.identity != self.library.identity
        self._settings.setValue(DMM_FOLDER_SETTING, str(library.install))
        if not changed and self._models_snapshot is self.controller.snapshot:
            return
        previous = self.collection.currentData()
        if self.library is not None and changed:
            _, _, owners = self.controller.variant_plan_inputs()
            if any(getattr(source, 'dmm_source_revision', None) is not None for source in owners):
                self.controller.invalidate_plan()
                self.controller.status_message.emit(tr('Installed files changed. Load the model again before building or exporting.'), True)
        self.library = library
        state = lambda selected: tr('Selected in DMM') if selected else tr('Not selected')
        self.modules.setText(tr('DMM selection — Equip All Armor: {armor}; CharacterCreator.asi: {creator}.').format(
            armor=state(library.equip_all_selected), creator=state(library.creator_asi_selected)))
        self.modules.setToolTip('\n'.join(f'{mod.title} {mod.version}' for mod in library.mods))
        with QSignalBlocker(self.collection):
            self.collection.clear()
            for mod in library.mods:
                if mod.kind in {'creator', 'fit', 'module'}:
                    state = tr('Selected in DMM') if mod.selected else tr('Installed only')
                    self.collection.addItem(f'{mod.title} {mod.version} · {state}', mod.identifier)
            index = self.collection.findData(previous)
            if index >= 0:
                self.collection.setCurrentIndex(index)
        self._collection_changed()

    def _collection_changed(self, *_args):
        self._paths = ()
        self._unresolved = ()
        self.models.clear()
        library, identifier, snapshot = self.library, self.collection.currentData(), self.controller.snapshot
        self._models.cancel()
        self._enabled()
        if library is None or identifier is None:
            self.status.setText(tr('No supported character mods are installed in this DMM library.'))
            return
        self.status.setText(tr('Reading installed models…'))
        key = (library.identity, identifier, id(snapshot))
        self._models.request(key, lambda stop: character_model_paths(library, identifier, snapshot, stop_event=stop))

    def _models_ready(self, key, catalogue):
        if self.library is None or key != (self.library.identity, self.collection.currentData(), id(self.controller.snapshot)):
            return
        self._models_snapshot = self.controller.snapshot
        self._paths = catalogue.paths
        self._unresolved = catalogue.unresolved
        self._filter()

    def _filter(self, *_args):
        previous = self.models.currentData()
        words = self.filter.text().casefold().split()
        paths = [path for path in self._paths if all(word in path for word in words)]
        with QSignalBlocker(self.models):
            self.models.clear()
            for path in paths[:80]:
                self.models.addItem(path.removeprefix('character/model/'), path)
            index = self.models.findData(previous)
            if index >= 0:
                self.models.setCurrentIndex(index)
        self.status.setText(tr('{count} models found. Refine the search to see more than the first 80.').format(count=len(paths)))
        if self._unresolved:
            self.status.setText(self.status.text() + '\n' + tr('{count} replacements could not be resolved against the loaded game. They are unavailable.').format(count=len(self._unresolved)))
        self.status.setToolTip('\n'.join(self._unresolved))
        self._enabled()

    def _enabled(self, *_args):
        ready = not self.controller.busy and self.controller.snapshot is not None and self.controller.draft.template_key is not None
        self.load_button.setEnabled(ready and self.models.currentData() is not None)
        self.choose_button.setEnabled(not self.controller.busy)
        self.refresh_button.setEnabled(not self.controller.busy)

    def _failed(self, _key, message):
        self._paths = ()
        self._models_snapshot = object()
        self.models.clear()
        self.status.setText(tr(message))
        self._enabled()

    def _load(self):
        path = self.models.currentData()
        if not self.load_button.isEnabled() or self.library is None or path is None:
            return
        request = InstalledCharacterModel(self.library, self.collection.currentData(), path)
        self.controller.start_model_import(Path(path), installed_model=request)
