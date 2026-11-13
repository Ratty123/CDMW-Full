"""New Item Studio, panel 7: choose output, review the plan, and write it."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from cdmw import constants

from PySide6.QtCore import QElapsedTimer, QEvent, QSettings, QTimer, Qt, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHeaderView,
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
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.state import MANAGERS
from cdmw.ui.new_item.review_model import FileChangeModel, ReviewTextWriter
from cdmw.ui.new_item.ui_kit import BLOCK, EDIT, OK, WARN, DetailsToggle, NoteLabel
from cdmw.ui.widgets import request_settings_sync
from cdmw.ui.log_view import LiveLogBinding

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


class OutputPanel(QGroupBox):

    def _build_plan_review(self, content):
        content.addWidget(QLabel("Review the plan"))
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
        self.summary.setPlaceholderText("Build the plan to see its summary, warnings and the files it changes. Nothing is written until you choose the write or install button.")
        self.summary.setMinimumHeight(_COMPACT_SUMMARY_HEIGHT)
        self.review_tabs.addTab(self.summary, "Details and warnings")
        from cdmw.ui.new_item.component_list import ComponentSummary
        self.component_summary = ComponentSummary(self._controller, self.review_tabs)
        self.review_tabs.insertTab(0, self.component_summary, "Components")
        self.review_tabs.setCurrentWidget(self.component_summary)
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
        self._export_error = ""
        self._export_requested = False
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
        self.setToolTip("Build plan is read-only. Review the planned files, warnings and errors before exporting.")

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
        self.plan_state.setToolTip(
            "Changes to the item, or to the mod it builds on, clear the plan. "
            "The output folder, mod manager and mod name keep it."
        )

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
        # DMM and .cdmw are the only outputs; other managers are not updated for the DLC.
        self.output_mode.addItem(self.tr("Mod folder") + " · DMM", "folder")
        self.output_mode.addItem(self.tr("Item package") + " · .cdmw", "independent")
        self.output_mode.hide()
        self.mode_buttons = QWidget()
        mode_row = QVBoxLayout(self.mode_buttons)
        mode_row.setContentsMargins(0, 0, 0, 0)
        mode_row.setSpacing(4)
        self.folder_mode_button = QToolButton(self.mode_buttons)
        self.independent_mode_button = QToolButton(self.mode_buttons)
        for mode, button in (("folder", self.folder_mode_button), ("independent", self.independent_mode_button)):
            index = self.output_mode.findData(mode)
            if index < 0:
                button.hide()
                button.setEnabled(False)
                continue
            button.setText(self.output_mode.itemText(index))
            button.setCheckable(True)
            button.setAutoExclusive(True)
            button.setProperty("newItemOutputMode", True)
            button.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            button.clicked.connect(lambda _checked, mode=index: self.output_mode.setCurrentIndex(mode))
            mode_row.addWidget(button)
        self.folder_mode_button.setToolTip(self.tr("Write a mod folder for DMM (Definitive Mod Manager)."))
        self.independent_mode_button.setToolTip(self.tr("Create a shareable .cdmw package with its own identity. CDMW combines supported shared files when it is installed or prepared."))
        write_layout.addWidget(self.mode_buttons)
        self.folder_controls = QWidget()
        export = QVBoxLayout(self.folder_controls)
        export.setContentsMargins(0, 0, 0, 0)
        export.setSpacing(6)
        # What the plan builds on comes first; it changes what the folder below means.
        self.add_to_mod = QCheckBox("Add to existing mod")
        self.add_to_mod.setToolTip(
            "Select an existing mod folder to add this item while keeping its current items. "
            "Leave unticked to create a separate mod in a new folder."
        )
        self.add_to_mod.toggled.connect(lambda _checked: self._mod_base_changed())
        export.addWidget(self.add_to_mod)
        self.mod_base_note = QLabel("")
        self.mod_base_note.setWordWrap(True)
        self.mod_base_note.setVisible(False)
        export.addWidget(self.mod_base_note)
        # One manager remains, so the choice stays hidden for callers that read it.
        self.manager = QComboBox()
        self.manager.addItems(MANAGERS)
        controller.draft.manager = self.manager.currentText()
        export.addWidget(self.manager)
        self.manager.hide()
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
        self.independent_controls = QWidget()
        independent_layout = QVBoxLayout(self.independent_controls)
        independent_layout.setContentsMargins(0, 0, 0, 0)
        self.independent_note = QLabel(self.tr("Writes a portable .cdmw package. Add it on Mod Management's Mods page and choose Send to DMM; DMM loads it into the game."))
        self.independent_note.setWordWrap(True)
        independent_layout.addWidget(self.independent_note)
        self.continued_package_button = QPushButton(self.tr("Update the continued package"))
        self.continued_package_button.setToolTip(self.tr("Write this item back to the package opened from Drafts & Mods, keeping its identity."))
        self.continued_package_button.clicked.connect(self._write_continued)
        self.continued_package_button.setVisible(False)
        independent_layout.addWidget(self.continued_package_button)
        self.update_package_button = QPushButton("Update an existing item package...")
        self.update_package_button.setToolTip(self.tr("Replace a selected .cdmw package while keeping its identity. Writing a new package creates a separate item."))
        self.update_package_button.clicked.connect(lambda: self._write_independent(update=True))
        independent_layout.addWidget(self.update_package_button)
        write_layout.addWidget(self.independent_controls)
        # A blocked export and its remedy stay above the choices they refer to.
        self.export_problem = NoteLabel("", BLOCK)
        write_layout.insertWidget(0, self.export_problem)
        self.choose_mod_base_button = QPushButton("Choose mod to extend...")
        self.choose_mod_base_button.clicked.connect(self._choose_mod_to_extend)
        self.choose_mod_base_button.hide()
        write_layout.insertWidget(1, self.choose_mod_base_button)
        self.export_root.textChanged.connect(lambda _text: self._mod_base_changed())
        self.mod_name.textChanged.connect(lambda _text: self._update_destination())
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
        self._log_binding = LiveLogBinding(self.log)
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
        # Status, Build plan and the write action read top to bottom in the order
        # they are used. Destination details are applied when writing, so changing
        # them keeps a built plan; only what the plan builds on clears it.
        self.actions = QWidget()
        actions = QVBoxLayout(self.actions)
        actions.setContentsMargins(0, 0, 0, 0)
        actions.addWidget(self.build_button)
        actions.addWidget(self.export_button)
        self.send_dmm_button = QPushButton(self.tr("Send to DMM"))
        self.send_dmm_button.setObjectName("new_item_send_to_dmm")
        self.send_dmm_button.setToolTip(self.tr(
            "Write the mod straight into DMM's mods folder. Then enable it in DMM and click Mount."))
        self.send_dmm_button.clicked.connect(self._send_to_dmm)
        actions.addWidget(self.send_dmm_button)
        sidebar_layout.addWidget(self.actions)
        self._stale_reason = self._pending_stale_reason = self._plan_blocked = ""
        self._plan_was_shown = False
        self.output_mode.currentIndexChanged.connect(self._output_mode_changed)
        self._output_mode_changed()

        controller.log_message.connect(self.append_log)
        controller.plan_ready.connect(self._show_plan)
        controller.plan_failed.connect(self._plan_failed)
        controller.plan_invalidated.connect(self._plan_invalidated)
        controller.export_finished.connect(self._export_finished)
        controller.busy_changed.connect(self._busy_changed)
        controller.operation_progress.connect(self._operation_progress)
        controller.status_message.connect(self._operation_message)
        controller.template_changed.connect(lambda _key: self._show_plan(None))
        controller.template_changed.connect(
            lambda _key: self.continued_package_button.setVisible(controller.continued_package_path is not None))
        self._busy_changed(False)

    def eventFilter(self, watched, event) -> bool:
        if watched is self.sidebar_scroll.widget() and event.type() == QEvent.Type.LayoutRequest:
            # Honor translated labels and font scaling without a horizontal scroll.
            width = (watched.minimumSizeHint().width() + self.sidebar_scroll.verticalScrollBar().sizeHint().width()
                     + 2 * self.sidebar_scroll.frameWidth())
            if self.sidebar_scroll.minimumWidth() != width:
                self.sidebar_scroll.setMinimumWidth(width)
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------ actions

    def _output_mode_changed(self) -> None:
        folder = self.output_mode.currentData() == "folder"
        independent = self.output_mode.currentData() == "independent"
        reason = ""
        if self._controller.independent_mode != independent:
            # Item packages are planned without the mounted game identities.
            self._controller.independent_mode = independent
            reason = self.tr("Item packages and game installs are planned differently.")
        self.folder_mode_button.setChecked(folder)
        self.independent_mode_button.setChecked(independent)
        self.folder_controls.setVisible(folder)
        self.independent_controls.setVisible(independent)
        self.export_button.setVisible(folder or independent)
        self.send_dmm_button.setVisible(folder)
        self.export_button.setText(self.tr("Write item package") + " (.cdmw)" if independent else self.tr("Write mod folder"))
        self.export_button.setToolTip(self.tr("Write a portable .cdmw file for installation through CDMW.") if independent else self.tr("Create the mod folder shown above, with an optional ZIP copy."))
        self._mod_base_changed(reason)

    def show_continued_package(self) -> None:
        """Select item package output and offer to write back to the continued package."""

        path = self._controller.continued_package_path
        index = self.output_mode.findData("independent")
        if index >= 0 and self.output_mode.currentIndex() != index:
            self.output_mode.setCurrentIndex(index)
        self.continued_package_button.setVisible(path is not None)
        self.continued_package_button.setToolTip(
            self.tr("Write this item back to the package opened from Drafts & Mods, keeping its identity.")
            + (f"\n\n{path}" if path is not None else ""))
        self._refresh_export_state()

    def _write_continued(self) -> None:
        path = self._controller.continued_package_path
        if path is not None and self._controller.has_current_plan:
            self._controller.start_independent_export(str(path), update=True)

    def _write_independent(self, *, update=False):
        if not self._controller.has_current_plan:
            return
        if update:
            path, _ = QFileDialog.getOpenFileName(self, self.tr("Select the item package to update"), "", self.tr("Independent item (*.cdmw *.cditem)"))
        else:
            path, _ = QFileDialog.getSaveFileName(self, self.tr("Write item package"), "", self.tr("Independent item (*.cdmw)"))
        if path:
            if not path.lower().endswith(constants.PACKAGE_EXTENSIONS):
                path += constants.PACKAGE_EXTENSION
            self._controller.start_independent_export(path, update=update)

    def _build(self) -> None:
        self.summary.setPlainText("Building the plan...")
        self._plan_blocked = ""
        if not self._controller.start_plan() and not self._plan_blocked:
            self.plan_state.set_note("The plan could not start; see the activity log.", BLOCK)
            return
        # Starting clears the previous plan; show building, ready or blocked instead.
        self._refresh_export_state()

    def _mod_base_changed(self, reason: str = "") -> None:
        """Only use the selected folder as a base when the user asks to extend it."""
        folder_mode = self.output_mode.currentData() == "folder"
        self.add_to_mod.setVisible(folder_mode)
        self.mod_base_note.setVisible(folder_mode)
        base = self._package_root() if folder_mode and self.add_to_mod.isChecked() else None
        base = base if base is not None and base.is_dir() else None
        if base != self._controller.mod_base_folder:
            self._controller.set_mod_base(base)
            reason = reason or self.tr("The plan builds on a different mod now.")
        if reason:
            # The last invalidation names why; set_mod_base's own carries none.
            self._pending_stale_reason = reason
            self._controller.invalidate_plan()
        self._update_destination()
        # The folder, manager and overlay number are only used when writing; a
        # built plan stays ready and its review follows the selected output.
        self._show_plan(self._controller.plan if self._controller.has_current_plan else None)

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

    def _choose_mod_to_extend(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose the existing mod folder", self.export_root.text())
        if path:
            self.add_to_mod.setChecked(True)
            self.export_root.setText(path)

    def _source_export_problem(self) -> str:
        plan = self._controller.plan
        if (plan is None or not plan.unselected_source_items or self.add_to_mod.isChecked()
                or self.output_mode.currentData() != "folder"):
            return ""
        items = ", ".join(plan.unselected_source_items)
        message = self.tr("Source tables already contain other custom items: {value_0}.").format(value_0=items)
        source = plan.manifest.get("tables", {}).get("iteminfo", {}).get("source_archive", "")
        if source:
            message += "\n" + self.tr("Source: {value_0}").format(value_0=source)
        message += "\n\n" + self.tr(
            "To combine items, choose the existing mod folder, then rebuild the plan. "
            "For a separate mod, unmount the item mods, read the archives again, then rebuild."
        )
        return message

    def _refresh_export_state(self) -> None:
        plan = self._controller.plan
        source_problem = self._source_export_problem()
        problem = source_problem or (self._export_error if self.output_mode.currentData() in ("folder", "independent") else "")
        changed = problem != self.export_problem.plain_text()
        self.export_problem.set_lines((line, BLOCK) for line in problem.splitlines())
        if problem and changed:
            self.sidebar_scroll.verticalScrollBar().setValue(0)
        self.choose_mod_base_button.setVisible(bool(source_problem))
        self.choose_mod_base_button.setEnabled(not self._controller.busy)
        self.export_button.setEnabled(self._controller.has_current_plan and not self._controller.busy and not source_problem)
        self.send_dmm_button.setEnabled(self.export_button.isEnabled())
        self.update_package_button.setEnabled(self._controller.has_current_plan and not self._controller.busy)
        self.continued_package_button.setEnabled(self._controller.has_current_plan and not self._controller.busy)
        if problem:
            self.plan_state.set_note("Export blocked", BLOCK)
        elif not self._controller.has_current_plan:
            self._plan_note()
        else:
            plan = self._controller.plan
            warnings = len(plan.warnings)
            self.plan_state.set_note(
                f"Ready: item {plan.spec.item_key}, {len(plan.patches)} table file(s) replaced, {len(plan.additions)} new file(s)"
                + (f", {warnings} warning(s) to review" if warnings else ""),
                WARN if warnings else OK,
            )

    def _export(self) -> None:
        if self.output_mode.currentData() == "independent":
            self._write_independent()
            return
        if self._source_export_problem():
            self._refresh_export_state()
            return
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
        self._export_error = ""
        self._export_requested = True
        try:
            self._controller.start_export(root, self.manager.currentText(), create_zip=self.create_zip.isChecked(),
                                          replace_existing=self.add_to_mod.isChecked())
        finally:
            self._export_requested = False

    # ------------------------------------------------------------------ results

    def append_log(self, message: str) -> None:
        self._log_binding.append_log(str(message))

    def _operation_message(self, message: str, error: bool) -> None:
        if error:
            self.append_log(message)
            if self._export_requested or self._controller._lane == "export":
                self._export_error = str(message)
                self._refresh_export_state()

    def _plan_note(self) -> None:
        """Say what the plan needs next, beside the buttons that do it."""
        if self._controller.busy and self._controller._lane == "plan":
            self.plan_state.set_note(self.tr("Building the plan..."), EDIT)
        elif self._plan_blocked:
            self.plan_state.set_note(f"Blocked: {self._plan_blocked}", BLOCK)
        elif self._plan_was_shown:
            reason = self._stale_reason or self.tr("Something on an earlier step changed.")
            self.plan_state.set_note(
                self.tr("Plan out of date. {value_0} Build it again before writing.").format(value_0=reason), WARN)
        else:
            self.plan_state.set_note(
                self.tr("Next: build the plan. Nothing is written until you choose the button below it."), WARN)

    def _plan_invalidated(self) -> None:
        self._stale_reason, self._pending_stale_reason = self._pending_stale_reason, ""
        self._plan_blocked = ""
        self._show_plan(None)

    def _show_plan(self, plan: Optional[NewItemPlan] = None) -> None:
        self.mod_name.setPlaceholderText(self._controller.draft.display_names.get("eng", "") or self.tr("Mod name"))
        self._update_destination()
        self._install_error = ""
        self._export_error = ""
        if not self._controller.busy:
            self.busy_state.set_note("", None)
        enabled = plan is not None
        if enabled:
            self._plan_was_shown = True
            self._stale_reason = self._plan_blocked = ""
        self.build_button.setProperty("newItemPrimary", not enabled)
        self.build_button.style().unpolish(self.build_button)
        self.build_button.style().polish(self.build_button)
        self.export_button.setEnabled(enabled and not self._controller.busy)
        self.send_dmm_button.setEnabled(enabled and not self._controller.busy)
        self._refresh_export_state()
        mode = self.output_mode.currentData()
        if getattr(self, "_displayed_plan", False) == (id(plan), mode):
            return
        self._displayed_plan = (id(plan), mode)
        self._review_lookup.cancel()
        self._file_model.replace_rows(())
        if plan is None:
            self.build_button.setText(self.tr("Build plan"))
            self._summary_writer.set_text("")
            return
        self.build_button.setText(self.tr("Rebuild plan"))
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
        self._plan_blocked = str(message)
        self._plan_note()

    def _send_to_dmm(self) -> None:
        if self._source_export_problem():
            self._refresh_export_state()
            return
        mods = self._dmm_mods_folder()
        if mods is None:
            return
        # The DMM folder is named after the mod alone, so another item sent under
        # the same name would be replaced without a word.
        from cdmw.services.dmm_send import send_target
        title = self._controller.export_title
        try:
            # With Add to existing mod, the send updates that mod instead of adding a second one.
            folder, replaced, _title = send_target(mods, title, self._controller.mod_base_folder)
            title = folder.name
        except ValueError:
            replaced = False  # The send itself reports a folder CDMW did not write.
        if replaced and QMessageBox.question(
                self, self.tr("Send to DMM"),
                self.tr("Replace the mod named {value_0} that CDMW wrote earlier?").format(value_0=title),
        ) != QMessageBox.StandardButton.Yes:
            return
        self._export_error = ""
        self._export_requested = True
        try:
            self._controller.start_send_to_dmm(mods)
        finally:
            self._export_requested = False

    def _dmm_mods_folder(self):
        from cdmw.ui.new_item.dmm_send_ui import choose_dmm_mods_folder
        return choose_dmm_mods_folder(self, self._settings)

    def _export_finished(self, result: object) -> None:
        from cdmw.domain.new_item.independent import IndependentItemExport
        from cdmw.services.dmm_send import DmmSendResult
        if isinstance(result, IndependentItemExport):
            self._export_error = ""
            self.append_log(f"Item package written: {result.path}")
            QMessageBox.information(self, self.tr("Write item package"), self.tr("Package written. Add it on Mod Management's Mods page and choose Send to DMM.") + "\n\n" + str(result.path))
            return
        if isinstance(result, DmmSendResult):
            self._export_error = ""
            self._refresh_export_state()
            self.append_log(f"Sent to DMM: {result.folder}")
            message = self.tr("Sent to DMM. In DMM, enable the mod and click Mount.")
            if result.replaced:
                message += "\n" + self.tr("It replaced the copy CDMW sent earlier.")
            QMessageBox.information(self, self.tr("Send to DMM"), message + "\n\n" + str(result.folder))
            return
        self._export_error = ""
        self._refresh_export_state()
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

    def _busy_changed(self, busy: bool) -> None:
        lane = str(getattr(self._controller, "_lane", "") or "")
        if busy and lane == "install":
            self._install_error = ""
        if busy and lane == "export":
            self._export_error = ""
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
                "snapshot": self.tr("Reading the archives..."),
            }[lane]
            self._busy_elapsed.start()
            self._busy_timer.start()
            self._refresh_busy_detail()
        self.build_button.setEnabled(not busy)
        has_plan = self._controller.has_current_plan
        self.export_button.setEnabled(has_plan and not busy)
        self.send_dmm_button.setEnabled(has_plan and not busy)
        for control in (self.output_mode, self.mode_buttons, self.folder_controls, self.independent_controls, self.add_to_mod):
            control.setEnabled(not busy)
        self.update_package_button.setEnabled(has_plan and not busy)
        self.continued_package_button.setEnabled(has_plan and not busy)
        self._refresh_export_state()

    def _operation_progress(self, lane: str, current: int, total: int, detail: str) -> None:
        if (not self._controller.busy or lane != self._controller._lane
                or lane not in {"plan", "export", "snapshot"}):
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


__all__ = ["CHECKLIST", "OutputPanel"]
