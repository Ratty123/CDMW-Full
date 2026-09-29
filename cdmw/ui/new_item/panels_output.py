"""New Item Studio, panel 7: choose output, review the plan, and write it."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QElapsedTimer, QEvent, QSettings, QTimer, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QIntValidator
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHeaderView,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTabWidget,
    QToolButton,
    QTreeView,
    QVBoxLayout,
    QWidget,
)

from cdmw.services.new_item_planning import NewItemPlan
from cdmw.domain.packages.layout import sanitize_mod_package_folder_name
from cdmw.services.settings_service import resolve_settings_file_path
from cdmw.services.archive_overlay_install import OVERLAY_DIRECTORY_FIRST, OverlayInstallResult
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.state import MANAGERS
from cdmw.ui.new_item.review_model import FileChangeModel, ReviewTextWriter
from cdmw.ui.new_item.ui_kit import BLOCK, EDIT, OK, WARN, DetailsToggle, NoteLabel
from cdmw.ui.widgets import request_settings_sync

# Both review tabs scroll locally inside the remaining workspace height.
_COMPACT_SUMMARY_HEIGHT = 120
_OPEN_FOLDER_SETTING = "ui/new_item_open_folder_after_creation"

CHECKLIST = (
    "In game: the item shows in the shop you chose (or in the inventory when given by other means).",
    "Its name and description read right in your language.",
    "It equips and displays correctly in every supported state, including sheathed or holstered when the template has one; the imported model, if any, renders.",
    "An imported model's textures read as the source's (albedo, shine and glow); the plain PBR shaders are the first thing to switch off if they do not.",
    "The icon shows (a generated icon at a new path is the first thing to check).",
    "Its stats match the grid; an added level is the least-proven part.",
    "The tooltip lists the perks you chose; a visual effect, if any, appears on each compatible visual prefab the new item owns.",
)


def install_result_report(result: object) -> tuple:
    """Describe overlay installation, migration and removal by their result type."""

    backup = getattr(result, "backup_dir", "") or ""
    directory = getattr(result, "directory", None)
    name = getattr(directory, "name", "") if directory is not None else ""
    if hasattr(result, "retired_inventory"):
        return (
            "Start fresh with overlays",
            f"Retired {len(result.labels)} saved overlay(s). The old files remain in folder {name} for recovery."
            f"\n\nHistory: {result.retired_inventory}\n\nBackup: {backup}"
            "\n\nRebuild the item plan, then install it with Overlay folder set to Auto.",
        )
    if hasattr(result, 'removed_overlay_id'):
        action = {'remove': 'Removed', 'enable': 'Enabled', 'disable': 'Disabled', 'rebuild': 'Rebuilt'}.get(
            getattr(result, 'action', 'remove'), 'Updated')
        return ('Installed overlays', f'{action} {result.label}. {result.remaining} overlay(s) enabled.\n\nBackup: {backup}')

    if hasattr(result, "removed_files"):  # the overlay taken away
        if not getattr(result, "unmounted", False):
            return ("Remove the overlay", "There was no overlay to remove: the mount list names none.")
        put_back = tuple(getattr(result, "restored_meta", ()) or ())
        if put_back:
            return (
                "Remove the overlay",
                f"Removed the overlay {name} and unmounted it, and put {', '.join(put_back)} back to what the game shipped."
                f"\n\nAnything that lived only in the overlay is gone from the game with it; anything installed into the "
                f"shipped archives is untouched.\n\nBackup: {backup}",
            )
        return (
            "Remove the overlay",
            f"Removed the overlay {name} and unmounted it.\n\nAnything that lived only in the overlay is gone from the game "
            f"with it; anything installed into the shipped archives is untouched.\n\nBackup: {backup}",
        )
    if hasattr(result, "moved"):  # items carried out of the shipped archives
        moved = int(getattr(result, "moved", 0) or 0)
        restored = len(getattr(result, "restored", ()) or ())
        size = int(getattr(result, "payload_bytes", 0) or 0)
        return (
            "Move installed items into the overlay",
            f"Moved {moved} file(s) ({size:,} bytes) into the overlay {name} and put {restored} archive file(s) back to their "
            f"oldest backup.\n\nThe game reads the same thing it did; the files it shipped are its own again."
            f"\n\nBackup: {backup}",
        )
    if hasattr(result, "entries") and hasattr(result, "restore"):  # a move that found nothing
        return (
            "Move installed items into the overlay",
            "Nothing to move: no archive file differs from the oldest backup of it, so the shipped archives carry no "
            "installed item.",
        )
    if hasattr(result, "file_count"):  # installed as an overlay
        count = int(getattr(result, "file_count", 0) or 0)
        carried = int(getattr(result, "carried_forward", 0) or 0)
        size = int(getattr(result, "payload_bytes", 0) or 0)
        recovery = ""
        if getattr(result, "recovery_inventory", None) is not None:
            recovery = (
                f"\n\nAutomatically retired {len(result.recovered_overlays)} unmounted old overlay(s) and installed a fresh set. "
                f"The old files remain on disk. Saved history: {result.recovery_inventory}"
            )
        # the two are whole sentences rather than one with a clause slotted into it: a
        # fragment interpolated into a message is a fragment the translator never sees
        if carried:
            return (
                "Install as an overlay",
                f"Installed as the archive directory {name}: {count} file(s), {size:,} bytes, mounted ahead of the shipped "
                f"archives, {carried} of them carried forward from what the overlay already held.\n\nThe archives the game "
                f"shipped were not written to.\n\nBackup: {backup}\n\nStart the game and go through the checklist." + recovery,
            )
        return (
            "Install as an overlay",
            f"Installed as the archive directory {name}: {count} file(s), {size:,} bytes, mounted ahead of the shipped "
            f"archives.\n\nThe archives the game shipped were not written to."
            f"\n\nBackup: {backup}\n\nStart the game and go through the checklist." + recovery,
        )
    return (
        "Install as an overlay",
        "The operation returned an unrecognised result. Check the log before continuing.",
    )


class OutputPanel(QGroupBox):
    #: The overlay route: the same plan as an archive directory of its own.
    install_overlay_requested = Signal()

    def _build_plan_review(self, content):
        heading = QHBoxLayout()
        heading.addWidget(QLabel("Review the plan"))
        heading.addStretch(1)
        heading.addWidget(self.build_button)
        content.addLayout(heading)
        self.review_tabs = QTabWidget()
        self.file_changes = QTreeView()
        self._file_model = FileChangeModel(["File", "Change"], self.file_changes)
        self.file_changes.setModel(self._file_model)
        self.file_changes.header().setStretchLastSection(False)
        self.file_changes.header().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.file_changes.header().setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        self.file_changes.header().setResizeContentsPrecision(32)
        self.file_changes.setUniformRowHeights(True)
        self.file_changes.setRootIsDecorated(False)
        self.file_changes.setMinimumHeight(_COMPACT_SUMMARY_HEIGHT)
        self.review_tabs.addTab(self.file_changes, "File changes")
        self.summary = QPlainTextEdit()
        self._summary_writer = ReviewTextWriter(self.summary)
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("The plan's summary, warnings and touched files appear here.")
        self.summary.setMinimumHeight(_COMPACT_SUMMARY_HEIGHT)
        self.review_tabs.addTab(self.summary, "Details and warnings")
        content.addWidget(self.review_tabs, 1)


    def __init__(self, controller: NewItemStudioController, parent=None, *, settings=None) -> None:
        super().__init__("7. Output", parent)
        self._controller = controller
        self._settings = settings if settings is not None else QSettings(
            str(resolve_settings_file_path()), QSettings.Format.IniFormat)
        self._open_export_folder = False
        self._review_lookup = controller.create_lookup_lane()
        self._review_lookup.completed.connect(self._review_ready)
        self._review_lookup.failed.connect(self._review_failed)
        self._install_error = ""
        outer = QVBoxLayout(self)
        outer.setContentsMargins(8, 6, 8, 6)
        self.workspace_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.workspace_splitter.setChildrenCollapsible(False)
        self.workspace_splitter.setHandleWidth(6)
        outer.addWidget(self.workspace_splitter)
        workflow = QWidget()
        workflow.setMinimumWidth(520)
        layout = QVBoxLayout(workflow)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        self.workspace_splitter.addWidget(workflow)
        self.setToolTip("Build the plan (nothing is written yet), read what it changes, then write a mod folder or install into the game.")

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(6)
        self.busy_bar.setVisible(False)
        layout.addWidget(self.busy_bar)
        self.busy_state = NoteLabel("", None)
        layout.addWidget(self.busy_state)
        self._busy_detail = ""
        self._busy_elapsed = QElapsedTimer()
        self._busy_timer = QTimer(self)
        self._busy_timer.setInterval(1000)
        self._busy_timer.timeout.connect(self._refresh_busy_detail)
        self.build_button = QPushButton("Build plan")
        self.build_button.setProperty("newItemPrimary", True)
        self.build_button.setToolTip("Validate the draft, allocate its key and stem, and compose every table change and file. Nothing is written yet.")
        self.build_button.clicked.connect(self._build)
        self.plan_state = NoteLabel("Plan not built.", WARN)
        self.plan_state.setToolTip("Every change on the other steps clears the plan, so build it last.")

        self.sidebar = QGroupBox("Destination")
        self.sidebar.setMinimumWidth(320)
        sidebar_layout = QVBoxLayout(self.sidebar)
        sidebar_layout.setSpacing(10)
        write = QWidget()
        write_layout = QVBoxLayout(write)
        write_layout.setContentsMargins(0, 0, 0, 0)
        write_layout.setSpacing(8)
        # Keep one mode value for both the visible choices and existing callers.
        self.output_mode = QComboBox(self)
        self.output_mode.addItem("Mod folder", "folder")
        self.output_mode.addItem("Game overlay", "overlay")
        self.output_mode.hide()
        self.mode_buttons = QWidget()
        mode_row = QHBoxLayout(self.mode_buttons)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(4)
        self.folder_mode_button = QToolButton(self.mode_buttons)
        self.overlay_mode_button = QToolButton(self.mode_buttons)
        for index, button in enumerate((self.folder_mode_button, self.overlay_mode_button)):
            button.setText(self.output_mode.itemText(index))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setProperty("newItemOutputMode", True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked, mode=index: self.output_mode.setCurrentIndex(mode))
            mode_row.addWidget(button)
        write_layout.addWidget(self.mode_buttons)
        self.folder_controls = QWidget()
        export = QVBoxLayout(self.folder_controls)
        export.setContentsMargins(0, 0, 0, 0)
        export.setSpacing(6)
        export.addWidget(QLabel("Mod manager"))
        self.manager = QComboBox()
        self.manager.addItems(list(MANAGERS))
        self.manager.setCurrentText(controller.draft.manager if controller.draft.manager in MANAGERS else MANAGERS[0])
        controller.draft.manager = self.manager.currentText()
        self.manager.setToolTip("The mod manager whose folder layout the loose mod is written in.")
        self.manager.currentTextChanged.connect(lambda text: setattr(self._controller.draft, "manager", str(text)))
        export.addWidget(self.manager)
        self.dmm_warning = QLabel(
            "DMM export is temporarily disabled. Use CDUMM or JMM.")
        self.dmm_warning.setWordWrap(True)
        export.addWidget(self.dmm_warning)
        export.addWidget(QLabel("Mod name"))
        self.mod_name = QLineEdit(controller.draft.mod_name)
        self.mod_name.setPlaceholderText(controller.draft.display_names.get("eng", "") or self.tr("Mod name"))
        self.mod_name.setToolTip("The name of the new mod folder and the title shown in the mod manager. Leave blank to use the item's name.")
        self.mod_name.textChanged.connect(lambda text: setattr(self._controller.draft, "mod_name", str(text)))
        export.addWidget(self.mod_name)
        self.export_root_label = QLabel("Output folder")
        export.addWidget(self.export_root_label)
        self.export_root = QLineEdit()
        self.export_root.setPlaceholderText("Choose where to create the mod folder")
        self.export_root.textChanged.connect(lambda text: setattr(self._controller.draft, "export_root", str(text)))
        export.addWidget(self.export_root)
        self.browse_button = QPushButton("Browse...")
        self.browse_button.clicked.connect(self._pick_root)
        export.addWidget(self.browse_button)
        self.destination_note = QLabel("")
        self.destination_note.setWordWrap(True)
        export.addWidget(self.destination_note)
        self.create_zip = QCheckBox("Also create a ZIP file")
        self.create_zip.setToolTip("Save a ZIP copy beside the mod folder, ready to share.")
        export.addWidget(self.create_zip)
        self.open_folder_after_creation = QCheckBox("Open folder after creation")
        self.open_folder_after_creation.setToolTip("Open the finished mod folder. CDMW remembers this choice until you change it.")
        stored = self._settings.value(_OPEN_FOLDER_SETTING, True)
        self.open_folder_after_creation.setChecked(str(stored).lower() in {"true", "1", "yes", "on"})
        self.open_folder_after_creation.toggled.connect(self._remember_open_folder)
        export.addWidget(self.open_folder_after_creation)
        self.export_button = QPushButton("Write mod folder")
        self.export_button.setToolTip("Create the mod folder shown above, with an optional ZIP copy.")
        self.export_button.clicked.connect(self._export)
        self.export_button.setProperty("newItemPrimary", True)
        write_layout.addWidget(self.folder_controls)
        # A loose mod carries whole tables, so two of them cannot both be enabled: the one
        # the manager mounts last owns the table and the other item is not in it. Planned
        # on the folder's own tables instead, the next item joins the ones already there.
        self.add_to_mod = QCheckBox("Add to existing mod")
        self.add_to_mod.setToolTip(
            "Select an existing mod folder to add this item while keeping its current items. "
            "Leave unticked to create a separate mod in a new folder."
        )
        self.add_to_mod.toggled.connect(lambda _checked: self._mod_base_changed())
        write_layout.addWidget(self.add_to_mod)
        self.mod_base_note = QLabel("")
        self.mod_base_note.setWordWrap(True)
        self.mod_base_note.setVisible(False)
        write_layout.addWidget(self.mod_base_note)
        self.export_root.textChanged.connect(lambda _text: self._mod_base_changed())
        self.mod_name.textChanged.connect(lambda _text: self._update_destination())
        self.overlay_controls = QWidget()
        install = QVBoxLayout(self.overlay_controls)
        install.setContentsMargins(0, 0, 0, 0)
        install.addWidget(QLabel("Overlay folder number"))
        self.overlay_directory = QLineEdit()
        self.overlay_directory.setPlaceholderText("Auto")
        self.overlay_directory.setMaxLength(4)
        self.overlay_directory.setMaximumWidth(90)
        self.overlay_directory.setValidator(QIntValidator(OVERLAY_DIRECTORY_FIRST, 9999, self))
        self.overlay_directory.setToolTip(
            "Leave blank for Auto, or enter a folder number from 0036 to 9999. "
            "Auto reuses CDMW's overlay or finds a free number. Game and other mod-manager folders are reserved."
        )
        install.addWidget(self.overlay_directory)
        self.install_overlay_button = QPushButton("Install as an overlay...")
        self.install_overlay_button.setToolTip(
            "Install this item as a separately tracked overlay. CDMW combines shared tables, preserves other "
            "installed overlays, and backs up the files it changes. Use Installed overlays to remove an individual install."
        )
        self.install_overlay_button.clicked.connect(self.install_overlay_requested.emit)
        self.install_overlay_button.setProperty("newItemPrimary", True)
        write_layout.addWidget(self.overlay_controls)
        write.setToolTip(
            "Export a mod folder or install as an overlay. Overlay installation keeps the shipped archive payloads intact."
        )
        self.checklist = DetailsToggle(
            "\n".join(f"- {line}" for line in CHECKLIST),
            title="After installing, check in game",
        )
        write_layout.addStretch(1)
        self.sidebar_scroll = QScrollArea()
        self.sidebar_scroll.setWidgetResizable(True)
        self.sidebar_scroll.setFrameShape(QScrollArea.NoFrame)
        self.sidebar_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.sidebar_scroll.setWidget(write)
        write.installEventFilter(self)
        sidebar_layout.addWidget(self.sidebar_scroll, 1)
        sidebar_layout.addWidget(self.plan_state)

        review = QWidget()
        review_layout = QVBoxLayout(review)
        review_layout.setContentsMargins(0, 0, 0, 0)
        review_layout.setSpacing(6)
        self._build_plan_review(review_layout)
        self.activity = QGroupBox("Activity log")
        self.activity.setMinimumWidth(260)
        activity_layout = QVBoxLayout(self.activity)
        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setProperty("followTail", True)
        self.log.setPlaceholderText("Build progress, exports, installs, and other messages appear here.")
        self.log.setMinimumHeight(_COMPACT_SUMMARY_HEIGHT)
        activity_layout.addWidget(self.log, 1)
        review_layout.addWidget(self.checklist)
        self.workflow_scroll = QScrollArea()
        self.workflow_scroll.setWidgetResizable(True)
        self.workflow_scroll.setFrameShape(QScrollArea.NoFrame)
        self.workflow_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.workflow_scroll.setWidget(review)
        layout.addWidget(self.workflow_scroll, 1)

        self.workspace_splitter.addWidget(self.activity)
        self.workspace_splitter.addWidget(self.sidebar)
        self.workspace_splitter.setStretchFactor(0, 1)
        self.workspace_splitter.setStretchFactor(1, 1)
        self.workspace_splitter.setStretchFactor(2, 0)
        self.workspace_splitter.setSizes((460, 460, 320))
        self.actions = QWidget()
        actions = QVBoxLayout(self.actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.export_button)
        actions.addWidget(self.install_overlay_button)
        sidebar_layout.addWidget(self.actions)
        self.output_mode.currentIndexChanged.connect(self._output_mode_changed)
        self.manager.currentIndexChanged.connect(controller.invalidate_plan)
        self.overlay_directory.textChanged.connect(controller.invalidate_plan)
        self._output_mode_changed()

        controller.log_message.connect(self.append_log)
        controller.plan_ready.connect(self._show_plan)
        controller.plan_failed.connect(self._plan_failed)
        controller.plan_invalidated.connect(self._show_plan)
        controller.export_finished.connect(self._export_finished)
        controller.install_finished.connect(self._install_finished)
        controller.install_failed.connect(self._install_failed)
        controller.busy_changed.connect(self._busy_changed)
        controller.operation_progress.connect(self._operation_progress)
        controller.status_message.connect(self._operation_message)
        controller.template_changed.connect(lambda _key: self._show_plan(None))
        self._busy_changed(False)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.sidebar_scroll.widget() and event.type() == QEvent.Type.LayoutRequest:
            # Honor translated labels and font scaling without a horizontal scroll.
            width = watched.minimumSizeHint().width() + self.sidebar_scroll.verticalScrollBar().sizeHint().width()
            if self.sidebar_scroll.minimumWidth() != width:
                self.sidebar_scroll.setMinimumWidth(width)
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------ actions

    def _output_mode_changed(self) -> None:
        folder = self.output_mode.currentData() == "folder"
        self.folder_mode_button.setChecked(folder)
        self.overlay_mode_button.setChecked(not folder)
        self.folder_controls.setVisible(folder)
        self.overlay_controls.setVisible(not folder)
        self.export_button.setVisible(folder)
        self.install_overlay_button.setVisible(not folder)
        self._mod_base_changed()

    def _build(self) -> None:
        self.summary.setPlainText("Building the plan...")
        self.plan_state.set_note("Building...", None)
        if not self._controller.start_plan():
            self.plan_state.set_note("The plan could not start; see the message above.", BLOCK)
            return

    def _mod_base_changed(self) -> None:
        """Only use the selected folder as a base when the user asks to extend it."""
        folder_mode = self.output_mode.currentData() == "folder"
        self.add_to_mod.setVisible(folder_mode)
        self.mod_base_note.setVisible(folder_mode)
        self._controller.invalidate_plan()
        self._controller.set_mod_base(self._package_root() if folder_mode and self.add_to_mod.isChecked() else None)
        self._update_destination()

    def _package_root(self) -> Optional[Path]:
        text = self.export_root.text().strip()
        if not text:
            return None
        parent = Path(text).expanduser()
        return parent if self.add_to_mod.isChecked() else parent / sanitize_mod_package_folder_name(self._controller.export_title)

    def _update_destination(self) -> None:
        adding = self.add_to_mod.isChecked()
        self.export_root_label.setText(self.tr("Existing mod folder") if adding else self.tr("Output folder"))
        if adding:
            self.mod_base_note.setText("Adds this item to the selected mod folder and keeps its existing items. Select the mod folder itself, then rebuild the plan.")
        else:
            self.mod_base_note.setText("Creates a new folder named after your mod inside the output folder. To add this item to a mod you already made, tick Add to existing mod.")
        root = self._package_root()
        self.destination_note.setText(f"Mod folder: {root}" if root is not None else "")

    def _remember_open_folder(self, checked: bool) -> None:
        self._settings.setValue(_OPEN_FOLDER_SETTING, checked)
        request_settings_sync(self._settings)

    def _pick_root(self) -> None:
        title = self.tr("Choose the existing mod folder") if self.add_to_mod.isChecked() else self.tr("Choose where to create the mod folder")
        path = QFileDialog.getExistingDirectory(self, title, self.export_root.text() or "")
        if path:
            self.export_root.setText(path)

    def _export(self) -> None:
        root = self._package_root()
        if root is None:
            QMessageBox.information(self, "Write loose mod", "Choose an output folder first.")
            return
        if self.add_to_mod.isChecked() and not root.is_dir():
            QMessageBox.information(self, "Write loose mod", "Choose the existing mod folder you want to add this item to.")
            return
        if self._controller.plan is None:
            QMessageBox.information(self, "Write loose mod", "Build the plan first.")
            return
        self._open_export_folder = self.open_folder_after_creation.isChecked()
        self._controller.start_export(root, self.manager.currentText(), create_zip=self.create_zip.isChecked(),
                                      replace_existing=self.add_to_mod.isChecked())

    # ------------------------------------------------------------------ results

    def append_log(self, message: str) -> None:
        self.log.appendPlainText(str(message))
        self.log.verticalScrollBar().setValue(self.log.verticalScrollBar().maximum())

    def _operation_message(self, message: str, error: bool) -> None:
        if error:
            self.append_log(message)

    def _show_plan(self, plan: Optional[NewItemPlan] = None) -> None:
        self.mod_name.setPlaceholderText(self._controller.draft.display_names.get("eng", "") or self.tr("Mod name"))
        self._update_destination()
        self._install_error = ""
        if not self._controller.busy:
            self.busy_state.set_note("", None)
        enabled = plan is not None
        self.build_button.setProperty("newItemPrimary", not enabled)
        self.build_button.style().unpolish(self.build_button)
        self.build_button.style().polish(self.build_button)
        self.export_button.setEnabled(enabled and not self._controller.busy)
        self.install_overlay_button.setEnabled(enabled and not self._controller.busy)
        mode = self.output_mode.currentData()
        if getattr(self, "_displayed_plan", False) == (id(plan), mode):
            return
        self._displayed_plan = (id(plan), mode)
        self._review_lookup.cancel()
        self._file_model.replace_rows(())
        if plan is None:
            self.build_button.setText(self.tr("Build plan"))
            self._summary_writer.set_text("")
            self.plan_state.set_note("Plan not built.", WARN)
            return
        self.build_button.setText(self.tr("Rebuild plan"))
        warnings = len(plan.warnings)
        self.plan_state.set_note(
            f"Ready: item {plan.spec.item_key}, {len(plan.patches)} table file(s) replaced, {len(plan.additions)} new file(s)"
            + (f", {warnings} warning(s) to review" if warnings else ""),
            WARN if warnings else OK,
        )
        from cdmw.services.new_item_review import plan_review_content
        labels = (self.tr("Replace table"), self.tr("Add file"), self.tr("Overlay metadata"))
        self._summary_writer.set_text("Preparing the plan review…")
        self._review_lookup.request((id(plan), mode), lambda stop: plan_review_content(plan, mode, labels, stop))
        self.review_tabs.setCurrentWidget(self.summary if plan.warnings else self.file_changes)

    def _review_failed(self, key, message):
        if key == self._displayed_plan:
            self._summary_writer.set_text(f"The plan review could not be prepared: {message}")

    def _review_ready(self, key, result):
        if key == self._displayed_plan:
            rows, text = result
            self._file_model.replace_rows(rows)
            self._summary_writer.set_text(text)

    def _plan_failed(self, message: str, issues: object) -> None:
        lines = [f"The plan could not be built: {message}"]
        for issue in tuple(issues or ())[:12]:
            lines.append(f"- {issue.field}: {issue.message}")
        self._show_plan(None)
        self.summary.setPlainText("\n".join(lines))
        self.review_tabs.setCurrentWidget(self.summary)
        self.append_log("\n".join(lines))
        self.plan_state.set_note(f"Blocked: {message}", BLOCK)

    def _export_finished(self, result: object) -> None:
        root = getattr(result, "package_root", "")
        count = len(getattr(result, "payload_paths", ()) or ())
        new = len(getattr(result, "new_paths", ()) or ())
        self.append_log(f"Loose mod written to {root}: {count} file(s), {new} new.")
        message = f"Written to {root}\n\n{count} file(s), {new} of them new."
        zip_path = getattr(result, "zip_path", None)
        if zip_path is not None:
            message += f"\n\nZIP: {zip_path}"
            self.append_log(f"ZIP written to {zip_path}")
        if self._open_export_folder and root:
            if not QDesktopServices.openUrl(QUrl.fromLocalFile(str(root))):
                self.append_log(f"The mod was created, but its folder could not be opened: {root}")
        QMessageBox.information(self, "Write loose mod", message)

    def _install_finished(self, result: object) -> None:
        self._install_error = ""
        self.busy_state.set_note("", None)
        title, message = install_result_report(result)
        self.append_log(message.replace("\n\n", " "))
        if isinstance(result, OverlayInstallResult):
            QMessageBox.information(self, title, message)

    def _install_failed(self, message: str) -> None:
        self._install_error = f"Overlay installation failed: {message}"
        self.busy_state.set_note(self._install_error, BLOCK)
        QMessageBox.warning(self, "Overlay installation failed", message)

    def _busy_changed(self, busy: bool) -> None:
        lane = str(getattr(self._controller, "_lane", "") or "")
        if busy and lane == "install":
            self._install_error = ""
        working = bool(busy) and lane in {"plan", "export", "install", "snapshot"}
        self.busy_bar.setVisible(working)
        self.busy_bar.setRange(0, 0)
        self._busy_timer.stop()
        if not working:
            self.busy_state.set_note(self._install_error, BLOCK if self._install_error else None)
        else:
            self._busy_detail = {
                "plan": self.tr("Building the plan."),
                "export": self.tr("Writing the mod folder..."),
                "install": self.tr("Installing the overlay: backing up, validating, writing."),
                "snapshot": self.tr("Reading the archives..."),
            }[lane]
            self._busy_elapsed.start()
            self._busy_timer.start()
            self._refresh_busy_detail()
        self.build_button.setEnabled(not busy)
        has_plan = self._controller.has_current_plan
        self.export_button.setEnabled(has_plan and not busy)
        self.install_overlay_button.setEnabled(has_plan and not busy)
        self.overlay_directory.setEnabled(not busy)
        for control in (self.output_mode, self.mode_buttons, self.folder_controls, self.add_to_mod):
            control.setEnabled(not busy)

    def _operation_progress(self, lane: str, current: int, total: int, detail: str) -> None:
        if (not self._controller.busy or lane != self._controller._lane
                or lane not in {"plan", "export", "install", "snapshot"}):
            return
        # Counts describe the current stage (for example, completed materials),
        # never an estimated percentage of the whole plan or a native encode.
        self.busy_bar.setRange(0, max(0, total))
        if total > 0:
            self.busy_bar.setValue(max(0, min(current, total)))
        self._busy_detail = str(detail)
        self._refresh_busy_detail()

    def _refresh_busy_detail(self) -> None:
        if self._busy_elapsed.isValid():
            seconds = self._busy_elapsed.elapsed() // 1000
            self.busy_state.set_note(f"{self._busy_detail} ({seconds}s)", EDIT)


__all__ = ["CHECKLIST", "OutputPanel", "install_result_report"]
