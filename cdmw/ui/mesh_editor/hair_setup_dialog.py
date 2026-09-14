"""One cancellable setup surface shared by Finder and the Mesh Editor."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QComboBox, QDialog, QFormLayout, QLabel, QPushButton, QVBoxLayout

from cdmw.domain.hair_characters import HAIR_CHARACTERS, hair_character
from cdmw.ui.mesh_editor.hair_context_preparation import HairContextPreparation
from cdmw.ui.mesh_editor.hair_reference_picker import HairReferencePickerDialog

_CREATE_MODE, _EDIT_MODE = "generated", "existing"

class HairSetupDialog(QDialog):
    def __init__(self, owner, *, character=None, mode="generated", preset="empty", target_path="", reuse_target=None, draft_root=None):
        super().__init__(owner)
        self._owner = owner
        self._service = owner.archive.archive_catalogue_service
        self._generation = 0
        self._closed = False
        self._picker = None
        self.context = self.selected_entry = self.selected_dependencies = None
        self._target_path = target_path.casefold()
        self._reuse_target, self._draft_root = reuse_target, draft_root
        self.prepared_result = None
        import threading
        self._stop = threading.Event()
        self.setWindowTitle("Hair Tools (Experimental)")
        self.resize(1060, 800)
        layout = QVBoxLayout(self)
        notice = QLabel("Not tested in game. Hairstyles may not work correctly.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        form = QFormLayout()
        self.character = QComboBox()
        self.character.addItem("Choose a character", None)
        for profile in HAIR_CHARACTERS:
            self.character.addItem(profile.name, profile.name)
        self.mode = QComboBox()
        self.mode.addItem("Create hairstyle", _CREATE_MODE)
        self.mode.addItem("Edit hairstyle", _EDIT_MODE)
        self.mode.setCurrentIndex(max(0, self.mode.findData(mode)))
        # Retain the compatibility selection for the handoff; new creation is
        # always blank. Optional procedural fills belong inside the editor.
        self.preset = QComboBox(self)
        self.preset.addItem("Empty", "empty")
        self.preset.hide()
        form.addRow("Character", self.character)
        form.addRow("Action", self.mode)
        layout.addLayout(form)
        self.status = QLabel("Choose a character. The current scene stays open until you start its replacement.")
        self.status.setWordWrap(True)
        layout.addWidget(self.status)
        self.waiting_start = QPushButton("Start")
        self.waiting_start.setEnabled(False)
        self.waiting_start.clicked.connect(self._start)
        layout.addWidget(self.waiting_start)
        self.retry = QPushButton("Retry loading choices")
        layout.addWidget(self.retry)
        self.cancel_button = QPushButton("Cancel")
        layout.addWidget(self.cancel_button)
        self._resolver = HairContextPreparation(self._service, self)
        self._resolver.ready.connect(self._context_ready)
        self._resolver.failed.connect(self._failed)
        self._service.session_published.connect(self._session_changed)
        self.character.currentIndexChanged.connect(self._load)
        self.mode.currentIndexChanged.connect(self._load)
        self.retry.clicked.connect(self._load)
        self.cancel_button.clicked.connect(self.reject)
        if character:
            self.character.setCurrentIndex(max(0, self.character.findData(character)))
        else:
            self._load()

    def _start(self):
        if self._picker is not None and self.waiting_start.isEnabled():
            self._picker._choose()

    def _load(self):
        if self._closed:
            return
        self.resize(620, 320) if self.mode.currentData() == "generated" else self.resize(1060, 800)
        self.waiting_start.setEnabled(False)
        for control in (self.character, self.mode, self.preset, self.retry):
            control.setEnabled(True)
        self._generation += 1
        self._stop.set()
        import threading
        self._stop = threading.Event()
        self._resolver.cancel()
        self.context = None
        if self._picker:
            picker = self._picker
            self._picker = None
            self.layout().removeWidget(picker)
            picker.reject()
        self.waiting_start.show()
        character = self.character.currentData()
        if self._service.current_session is None:
            self.status.setText("Load the archive catalogue to choose a hairstyle. Start is unavailable until it is ready.")
        elif not character:
            self.status.setText("Choose Kliff, Damiane, or Oongka to load compatible hairstyles.")
        else:
            self.status.setText("Loading the mounted character and hairstyle catalogue…")
            self._resolver.start(character)

    def _context_ready(self, context):
        if self._closed or context.character != self.character.currentData():
            return
        self.context = context
        profile = hair_character(context.character)
        entry = context.dependencies.entry_for_path(profile.mesh_param_path)
        if entry is None:
            self._failed("The mounted character is missing its barber registration. Refresh the catalogue.")
            return
        generation = self._generation
        def read_choices(_log):
            from cdmw.core.archive_extraction import read_archive_entry_data
            from cdmw.domain.hair_registration import read_hair_choices
            if entry.orig_size > 2 * 1024 * 1024:
                raise ValueError("The barber registration exceeds its supported size.")
            return read_hair_choices(read_archive_entry_data(entry)[0])
        def ready(choices):
            if self._closed or generation != self._generation:
                return
            creating = self.mode.currentData() == "generated"
            picker = HairReferencePickerDialog(self._owner, "hair", character=profile.name,
                styles=tuple((c.index, c.prefab_stem) for c in choices), audit_hair=True,
                preferred_path=self._target_path, base_only=creating)
            self._picker = picker
            picker.setParent(self, Qt.Widget)
            picker.choose.setText("Start")
            picker.finished.connect(lambda result: self._selected(picker, result))
            picker.preparation_failed.connect(self._failed)
            if creating:
                picker.hide()
                def base_ready():
                    if not self._closed and generation == self._generation and picker is self._picker:
                        self.waiting_start.setEnabled(True)
                        self.status.setText("Start opens an empty scalp. Use Draw to create your hair.")
                picker.base_ready.connect(base_ready)
                self.status.setText("Checking character compatibility for an empty hairstyle…")
            else:
                self.waiting_start.hide()
                self.layout().insertWidget(self.layout().indexOf(self.status) + 1, picker, 1)
                picker.show()
                self.status.setText("Choose an existing hairstyle to load and edit.")
        def failed(message):
            if generation == self._generation:
                self._failed(message)
        self._owner._run_utility_task_when_idle(status_message="Loading registered hairstyles…", task=read_choices,
                                              on_complete=ready, on_error=failed)

    def _selected(self, picker, result):
        if self._closed or picker is not self._picker:
            return
        if result == QDialog.Accepted:
            self.selected_entry = picker.selected_entry
            self.selected_dependencies = picker.selected_dependencies
            self._picker = None
            self.layout().removeWidget(picker)
            self.waiting_start.show()
            self.waiting_start.setEnabled(False)
            if (self._reuse_target == (self.context.character, self.selected_entry.identity)
                    and self.mode.currentData() == "generated"):
                self.accept()
                return
            self.status.setText("Preparing the new editor scene. Your current scene remains open…")
            for control in (self.character, self.mode, self.preset, self.retry):
                control.setEnabled(False)
            generation, stop = self._generation, self._stop
            entry, dependencies = self.selected_entry, self.selected_dependencies
            arguments = {**self.context.arguments(), "mode": self.mode.currentData(), "start_preset": self.preset.currentData()}
            def prepare(_log):
                from cdmw.workers.mesh_archive_refit_worker import prepare_hair_editor_session
                return prepare_hair_editor_session(entry, dependencies, arguments, self._draft_root, stop)
            def ready(value):
                if self._closed or generation != self._generation:
                    value.service.close_edit_session(value.view.session_id, force_without_saving=True)
                    return
                self.prepared_result = value
                self.accept()
            self._owner._run_utility_task_when_idle(status_message="Preparing hair editor…", task=prepare,
                on_complete=ready, on_error=lambda message: self._failed(message) if generation == self._generation else None)
        else:
            self.reject()

    def _failed(self, message):
        if not self._closed:
            for control in (self.character, self.mode, self.preset, self.retry):
                control.setEnabled(True)
            self.status.setText(str(message) + " Use Retry loading choices to try again.")

    def _session_changed(self, _session):
        self._load()

    def done(self, result):
        if not self._closed:
            self._closed = True
            self._generation += 1
            self._stop.set()
            self._resolver.cancel()
            self._service.session_published.disconnect(self._session_changed)
            if self._picker and not self._picker._closed:
                self._picker.reject()
        super().done(result)
