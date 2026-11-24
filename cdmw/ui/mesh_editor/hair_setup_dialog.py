"""One cancellable setup surface shared by Finder and the Mesh Editor."""
from typing import NamedTuple

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QPushButton,
    QSizePolicy, QVBoxLayout, QWidget,
)

from cdmw.domain.hair_characters import HAIR_CHARACTERS, hair_character
from cdmw.ui.mesh_editor.hair_context_preparation import HairContextPreparation
from cdmw.ui.mesh_editor.hair_reference_picker import HairReferencePickerDialog

_CREATE_MODE, _EDIT_MODE = "generated", "existing"

class HairSetupDialog(QDialog):
    def __init__(self, owner, *, character=None, mode="generated", preset="empty", target_path="", reuse_target=None, reuse_scalp_cap=None, draft_root=None):
        super().__init__(owner)
        self._owner = owner
        self._service = owner.archive.archive_catalogue_service
        self._generation = 0
        self._closed = False
        self._picker = None
        self.context = self.selected_entry = self.selected_dependencies = None
        self._target_path = target_path.casefold()
        self._reuse_target, self._reuse_scalp_cap, self._draft_root = reuse_target, reuse_scalp_cap, draft_root
        self.prepared_result = None
        self._last_failure, self._retrying, self._retry_requested = "", False, False
        import threading
        self._stop = threading.Event()
        self.setWindowTitle("Hair Tools (Experimental)")
        # Dynamically switches between compact setup/loading (620x220) and the
        # embedded hairstyle picker (1060x800); persisting one shared geometry
        # shrinks the picker after a compact run or inflates Create hairstyle.
        self.setProperty("cdmwSkipGeometryPersistence", True)
        self.resize(620, 220)
        layout = QVBoxLayout(self)
        notice = QLabel("Not tested in game. Hairstyles may not work correctly.")
        notice.setWordWrap(True)
        notice.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
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
        self.status.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)
        layout.addWidget(self.status)
        self._create_options_row = QWidget(self)
        create_options = QHBoxLayout(self._create_options_row)
        create_options.setContentsMargins(0, 0, 0, 0)
        self.choose_donor_material = QCheckBox("Choose donor material & textures...", self._create_options_row)
        self.choose_donor_material.setObjectName("hair_choose_donor_material")
        self.choose_donor_material.setToolTip(
            "Open the hairstyle chooser in Create mode so you can select which donor material and textures to use."
        )
        self.keep_scalp_cap = QCheckBox("Keep donor scalp cap", self._create_options_row)
        self.keep_scalp_cap.setObjectName("hair_keep_scalp_cap")
        self.keep_scalp_cap.setChecked(True)
        self.keep_scalp_cap.setToolTip(
            "Retain the donor's fitted scalp base cap under drawn hair locks when the donor has one."
        )
        create_options.addWidget(self.choose_donor_material)
        create_options.addWidget(self.keep_scalp_cap)
        create_options.addStretch(1)
        layout.addWidget(self._create_options_row)
        choices = QWidget(self)
        self._choices_layout = QVBoxLayout(choices)
        self._choices_layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(choices, 1)
        self._buttons_row = QWidget(self)
        buttons = QHBoxLayout(self._buttons_row)
        buttons.setContentsMargins(0, 0, 0, 0)
        self.retry = QPushButton("Retry loading choices")
        buttons.addWidget(self.retry)
        buttons.addStretch(1)
        self.waiting_start = QPushButton("Start")
        self.waiting_start.setEnabled(False)
        self.waiting_start.clicked.connect(self._start)
        buttons.addWidget(self.waiting_start)
        self.cancel_button = QPushButton("Cancel")
        buttons.addWidget(self.cancel_button)
        layout.addWidget(self._buttons_row)
        self._resolver = HairContextPreparation(self._service, self)
        self._resolver.ready.connect(self._context_ready)
        self._resolver.failed.connect(self._failed)
        self._service.session_published.connect(self._session_changed)
        self.character.currentIndexChanged.connect(self._load)
        self.mode.currentIndexChanged.connect(self._load)
        self.choose_donor_material.toggled.connect(self._on_choose_donor_toggled)
        self.retry.clicked.connect(self._retry)
        self.cancel_button.clicked.connect(self.reject)
        if character:
            self.character.setCurrentIndex(max(0, self.character.findData(character)))
        else:
            self._load()

    def _on_choose_donor_toggled(self) -> None:
        if self._closed or self.mode.currentData() != _CREATE_MODE:
            return
        if self._service.current_session is not None and self.character.currentData():
            self._load()

    def _start(self):
        if self._picker is not None and self.waiting_start.isEnabled():
            self._picker._choose()

    def _retry(self):
        """Ask the catalogue again; a plain reload would hand back the remembered character."""
        if self._closed:
            return
        self._resolver.forget()
        self._retry_requested = True
        self._load()

    def _load(self):
        if self._closed:
            return
        self._retrying, self._retry_requested = self._retry_requested, False
        self.waiting_start.setEnabled(False)
        for control in (self.character, self.mode, self.preset, self.retry, self.choose_donor_material, self.keep_scalp_cap):
            control.setEnabled(True)
        is_create = self.mode.currentData() == _CREATE_MODE
        self._create_options_row.setVisible(is_create)
        self.choose_donor_material.setVisible(is_create)
        self.keep_scalp_cap.setVisible(is_create)
        self._generation += 1
        self._stop.set()
        import threading
        self._stop = threading.Event()
        self._resolver.cancel()
        self.context = None
        if self._picker:
            picker = self._picker
            self._picker = None
            self._choices_layout.removeWidget(picker)
            picker.reject()
        self._buttons_row.show()
        self.retry.show()
        self.waiting_start.show()
        self.cancel_button.show()
        self.layout().activate()
        self.resize(620, 220)
        character = self.character.currentData()
        if self._service.current_session is None:
            self.status.setText("Load the archive catalogue to choose a hairstyle. Start is unavailable until it is ready.")
        elif not character:
            self.status.setText("Choose Kliff, Damiane, or Oongka to load compatible hairstyles.")
        else:
            self.status.setText("Loading the character and its hairstyles again…" if self._retrying
                                else "Loading the mounted character and hairstyle catalogue…")
            self._resolver.start(character)

    def _context_ready(self, context):
        if self._closed or context.character != self.character.currentData():
            return
        self.context = context
        profile = hair_character(context.character)
        entry = context.dependencies.entry_for_path(profile.mesh_param_path)
        if entry is None:
            self._failed(f"{profile.name}'s barber list ({profile.mesh_param_path}) is not in the loaded archives. "
                         "Refresh the archive catalogue, then use Retry loading choices.", hint=False)
            return
        generation = self._generation
        def read_choices(_log):
            from cdmw.core.archive_extraction import read_archive_entry_data
            from cdmw.domain.hair_registration import HairRegistrationError, read_hair_choices
            if entry.orig_size > 2 * 1024 * 1024:
                raise ValueError("The barber registration exceeds its supported size.")
            data = read_archive_entry_data(entry)[0]
            try:
                choices = read_hair_choices(data)
            except HairRegistrationError as error:
                return error  # Not a failed read: the table itself is one this tool does not understand.
            return BarberChoices(choices, _mod_added_stems(entry, choices))
        def ready(result):
            if self._closed or generation != self._generation:
                return
            choices, mod_added = ((result.choices, result.mod_added) if isinstance(result, BarberChoices)
                                  else (result, frozenset()))
            if isinstance(choices, Exception):
                self._failed(f"CDMW cannot read {profile.name}'s barber list ({profile.mesh_param_path}): {choices} "
                             "A game update or another mod may have changed it. Loading again will not change this; "
                             "choose another character, or turn off mods that change this file.", hint=False)
                return
            listed = len(choices)
            choices = tuple(choice for choice in choices if choice.usable)
            if not choices:
                self._failed(f"None of {profile.name}'s {listed} barber hairstyles can be opened in Hair Tools. "
                             "Choose another character.", hint=False)
                return
            self._last_failure, self._retrying = "", False
            creating = self.mode.currentData() == "generated"
            custom_donor = creating and self.choose_donor_material.isChecked()
            picker = HairReferencePickerDialog(self._owner, "hair", character=profile.name,
                styles=tuple((c.index, c.prefab_stem) for c in choices), audit_hair=True,
                preferred_path=self._target_path, base_only=creating and not custom_donor,
                icons={c.prefab_stem: c.icon_path for c in reversed(choices) if c.icon_path},
                hidden=tuple(c.index for c in choices if not c.shown_in_game))
            self._picker = picker
            picker.setParent(self, Qt.Widget)
            picker.choose.setText("Start")
            picker.finished.connect(lambda result: self._selected(picker, result))
            picker.preparation_failed.connect(self._failed)
            if creating and not custom_donor:
                picker.hide()
                def base_ready():
                    if not self._closed and generation == self._generation and picker is self._picker:
                        self.waiting_start.setEnabled(True)
                        self.status.setText("Start opens an empty scalp. Use Draw to create your hair.")
                picker.base_ready.connect(base_ready)
                self.status.setText("Checking character compatibility for an empty hairstyle…")
            else:
                if picker.layout() is not None:
                    picker.layout().setContentsMargins(0, 0, 0, 0)
                self.waiting_start.hide()
                self.cancel_button.hide()  # The embedded chooser has its own Cancel.
                self.retry.hide()
                self._buttons_row.hide()
                self._choices_layout.addWidget(picker)
                picker.show()
                self.status.setText(
                    "Choose a donor hairstyle material to start from."
                    if custom_donor
                    else "Choose an existing hairstyle to load and edit."
                )
                added = sorted(c.prefab_stem for c in choices if c.prefab_stem in mod_added)
                if added:
                    # The barber list was read through DMM. Add New Barber Hairstyle copies a
                    # slot of the game's own list, so a mod's hairstyle cannot be its donor.
                    shown = ", ".join(added[:3]) + (", …" if len(added) > 3 else "")
                    self.status.setText(
                        f"Some hairstyles here come from another DMM mod ({shown}). Edit them only with "
                        "Replace Existing Hairstyle; Add New Barber Hairstyle needs one of the game's own hairstyles.")
                self.resize(1060, 800)
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
            self._choices_layout.removeWidget(picker)
            self._buttons_row.show()
            self.retry.show()
            self.waiting_start.show()
            self.cancel_button.show()
            self.waiting_start.setEnabled(False)
            self.layout().activate()
            self.resize(620, 220)
            if (not self.choose_donor_material.isChecked()
                    and (self._reuse_scalp_cap is None or self.keep_scalp_cap.isChecked() == self._reuse_scalp_cap)
                    and self._reuse_target == (self.context.character, self.selected_entry.identity)
                    and self.mode.currentData() == "generated"):
                self.accept()
                return
            self.status.setText("Preparing the new editor scene. Your current scene remains open…")
            for control in (self.character, self.mode, self.preset, self.retry, self.choose_donor_material, self.keep_scalp_cap):
                control.setEnabled(False)
            generation, stop = self._generation, self._stop
            entry, dependencies = self.selected_entry, self.selected_dependencies
            arguments = {
                **self.context.arguments(),
                "mode": self.mode.currentData(),
                "start_preset": self.preset.currentData(),
                "keep_scalp_cap": self.keep_scalp_cap.isChecked() if self.mode.currentData() == _CREATE_MODE else False,
            }
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

    def _failed(self, message, hint=True):
        """Say what failed. ``hint`` is off for messages that already name their own way forward."""
        if self._closed:
            return
        self._buttons_row.show()
        self.retry.show()
        for control in (self.character, self.mode, self.preset, self.retry, self.choose_donor_material, self.keep_scalp_cap):
            control.setEnabled(True)
        text = str(message).strip()
        if hint:
            text = f"{text} Use Retry loading choices to try again."
        # Without this a second identical failure looks as if Retry did nothing.
        repeated = self._retrying and text == self._last_failure
        self._last_failure, self._retrying = text, False
        self.status.setText(f"{text} Retrying gave the same result." if repeated else text)

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


class BarberChoices(NamedTuple):
    """A character's barber list, and the hairstyles in it that a DMM mod adds."""
    choices: tuple
    mod_added: frozenset


def _mod_added_stems(entry, choices) -> frozenset[str]:
    """Hairstyles in a DMM-served barber list that the game's own list lacks.

    Runs on the utility worker. Returns nothing when the list is not served by
    DMM or the game's own copy cannot be read.
    """
    from dataclasses import replace
    from cdmw.core.archive_extraction import read_archive_entry_data
    from cdmw.domain.hair_registration import HairRegistrationError, read_hair_choices
    from cdmw.services.dmm_runtime_mount import is_dmm_note
    if getattr(entry, "prepared_path", None) is None or not is_dmm_note(getattr(entry, "prepared_note", "")):
        return frozenset()
    try:
        game = replace(entry, prepared_path=None, prepared_sha256="", prepared_size=None, prepared_note="")
        vanilla = {choice.prefab_stem for choice in read_hair_choices(read_archive_entry_data(game)[0])}
    except (HairRegistrationError, OSError, ValueError, TypeError):
        return frozenset()
    return frozenset(choice.prefab_stem for choice in choices if choice.prefab_stem not in vanilla)
