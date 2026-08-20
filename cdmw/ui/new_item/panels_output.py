"""New Item Studio, panel 6: build the plan, write a loose mod, or install."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QVBoxLayout,
)

from cdmw.services.new_item_planning import NewItemPlan
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.state import MANAGERS
from cdmw.ui.new_item.ui_kit import BLOCK, EDIT, OK, WARN, DetailsToggle, NoteLabel, intro_label

CHECKLIST = (
    "In game: the item shows in the shop you chose (or in the inventory when given by other means).",
    "Its name and description read right in your language.",
    "It equips, draws and sheathes; the imported model, if any, renders.",
    "An imported model's textures read as the source's (albedo, shine and glow); the plain PBR shaders are the first thing to switch off if they do not.",
    "The icon shows (a generated icon at a new path is the first thing to check).",
    "Its stats match the grid; an added level is the least-proven part.",
    "The tooltip lists the perks you chose; a weapon effect, if any, shows on the drawn blade.",
)


def install_result_report(result: object) -> tuple:
    """What to tell the reader after one of step 7's four buttons finishes.

    All four report through the same signal, and they did not all report the same kind of
    result: an overlay install, a move into the overlay and a removal have no
    `changed_paths` between them, so each of them said "Installed 0 archive entr(ies)",
    which reads like a failure after a button that worked.
    """

    backup = getattr(result, "backup_dir", "") or ""
    directory = getattr(result, "directory", None)
    name = getattr(directory, "name", "") if directory is not None else ""

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
        # the two are whole sentences rather than one with a clause slotted into it: a
        # fragment interpolated into a message is a fragment the translator never sees
        if carried:
            return (
                "Install as an overlay",
                f"Installed as the archive directory {name}: {count} file(s), {size:,} bytes, mounted ahead of the shipped "
                f"archives, {carried} of them carried forward from what the overlay already held.\n\nThe archives the game "
                f"shipped were not written to.\n\nBackup: {backup}\n\nStart the game and go through the checklist.",
            )
        return (
            "Install as an overlay",
            f"Installed as the archive directory {name}: {count} file(s), {size:,} bytes, mounted ahead of the shipped "
            f"archives.\n\nThe archives the game shipped were not written to."
            f"\n\nBackup: {backup}\n\nStart the game and go through the checklist.",
        )
    changed = len(getattr(result, "changed_paths", ()) or ())
    return (
        "Install into the game archives",
        f"Installed {changed} archive entr(ies).\n\nBackup: {backup}\n\nStart the game and go through the checklist.",
    )


class OutputPanel(QGroupBox):
    #: The tab asks the shell for confirmation and the mutation service, then installs.
    install_requested = Signal()
    #: The overlay route: the same plan as an archive directory of its own.
    install_overlay_requested = Signal()
    #: Housekeeping for that directory, neither of which needs a plan.
    overlay_migration_requested = Signal()
    overlay_removal_requested = Signal()

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("7. Output", parent)
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("Build the plan (nothing is written yet), read what it changes, then write a mod folder or install into the game."))

        self.busy_bar = QProgressBar()
        self.busy_bar.setRange(0, 0)
        self.busy_bar.setTextVisible(False)
        self.busy_bar.setFixedHeight(6)
        self.busy_bar.setVisible(False)
        layout.addWidget(self.busy_bar)
        self.busy_state = NoteLabel("", None)
        layout.addWidget(self.busy_state)

        build = QGroupBox("1. Build the plan")
        build_layout = QHBoxLayout(build)
        self.build_button = QPushButton("Build plan")
        self.build_button.setToolTip("Validate the draft, allocate its key and stem, and compose every table change and file. Nothing is written yet.")
        self.build_button.clicked.connect(self._build)
        build_layout.addWidget(self.build_button)
        self.plan_state = NoteLabel("Not built yet. Every change on the other steps clears the plan, so build it last.", WARN)
        build_layout.addWidget(self.plan_state, 1)
        layout.addWidget(build)

        review = QGroupBox("2. What the plan will change")
        review_layout = QVBoxLayout(review)
        self.summary = QPlainTextEdit()
        self.summary.setReadOnly(True)
        self.summary.setPlaceholderText("The plan's summary, warnings and touched files appear here.")
        self.summary.setMinimumHeight(160)
        review_layout.addWidget(self.summary)
        layout.addWidget(review, 1)

        write = QGroupBox("3. Write it")
        write_layout = QVBoxLayout(write)
        export = QHBoxLayout()
        export.addWidget(QLabel("Mod folder for:"))
        self.manager = QComboBox()
        self.manager.addItems(list(MANAGERS))
        self.manager.setToolTip("The mod manager whose folder layout the loose mod is written in.")
        self.manager.currentTextChanged.connect(lambda text: setattr(self._controller.draft, "manager", str(text)))
        export.addWidget(self.manager)
        self.export_root = QLineEdit()
        self.export_root.setPlaceholderText("Folder the mod is written into")
        self.export_root.textChanged.connect(lambda text: setattr(self._controller.draft, "export_root", str(text)))
        export.addWidget(self.export_root, 1)
        self.browse_button = QPushButton("Folder...")
        self.browse_button.clicked.connect(self._pick_root)
        export.addWidget(self.browse_button)
        self.export_button = QPushButton("Write mod folder")
        self.export_button.setToolTip("Write the plan as a loose mod folder for the manager chosen on the left; the game is not touched.")
        self.export_button.clicked.connect(self._export)
        export.addWidget(self.export_button)
        write_layout.addLayout(export)
        # A loose mod carries whole tables, so two of them cannot both be enabled: the one
        # the manager mounts last owns the table and the other item is not in it. Planned
        # on the folder's own tables instead, the next item joins the ones already there.
        self.add_to_mod = QCheckBox("Add to the mod already in this folder")
        self.add_to_mod.setToolTip(
            "A mod folder carries whole tables, so a second mod replaces the first one's rather than adding to it, and only "
            "one of the items survives. On, the next item is planned on the tables in this folder, so the folder ends up "
            "holding both. Off, it is planned on the game's own tables and the folder is overwritten."
        )
        self.add_to_mod.setChecked(True)
        self.add_to_mod.setVisible(False)
        self.add_to_mod.toggled.connect(lambda _checked: self._mod_base_changed())
        write_layout.addWidget(self.add_to_mod)
        self.mod_base_note = QLabel("")
        self.mod_base_note.setWordWrap(True)
        self.mod_base_note.setVisible(False)
        write_layout.addWidget(self.mod_base_note)
        self.export_root.textChanged.connect(lambda _text: self._mod_base_changed())
        install = QHBoxLayout()
        self.install_button = QPushButton("Install into the game archives...")
        self.install_button.setToolTip("Confirmed first, backed up, restorable. Refused while the game is running.")
        self.install_button.clicked.connect(self.install_requested.emit)
        install.addWidget(self.install_button)
        self.install_overlay_button = QPushButton("Install as an overlay...")
        self.install_overlay_button.setToolTip(
            "Write the item into an archive directory of its own and name that directory first in the game's mount "
            "list, which is where the game looks first. The archives the game shipped are not written to at all, so "
            "the backup is the mount list rather than a gigabyte of payload files, and removing the mod is deleting "
            "the directory. New in this build and not yet confirmed in game."
        )
        self.install_overlay_button.clicked.connect(self.install_overlay_requested.emit)
        install.addWidget(self.install_overlay_button)
        install.addStretch(1)
        write_layout.addLayout(install)
        write_layout.addWidget(intro_label(
            "Installing writes into the archives the game shipped, backs them up first, and can be restored. An overlay "
            "writes a directory of its own instead and leaves them alone; it is the faster and more easily undone of the "
            "two, and the newer."
        ))
        overlay_row = QHBoxLayout()
        self.overlay_migration_button = QPushButton("Move installed items into the overlay...")
        self.overlay_migration_button.setToolTip(
            "For items already written into the shipped archives. Every archive entry that differs from the oldest "
            "backup of it is carried into the overlay directory, and the archives themselves go back to that backup, "
            "so the game reads the same thing while the files it shipped are its own again."
        )
        self.overlay_migration_button.clicked.connect(self.overlay_migration_requested.emit)
        overlay_row.addWidget(self.overlay_migration_button)
        self.overlay_removal_button = QPushButton("Remove the overlay...")
        self.overlay_removal_button.setToolTip(
            "Unmount the overlay directory and delete it. Everything it holds leaves the game with it; anything "
            "installed into the shipped archives stays where it is."
        )
        self.overlay_removal_button.clicked.connect(self.overlay_removal_requested.emit)
        overlay_row.addWidget(self.overlay_removal_button)
        overlay_row.addStretch(1)
        write_layout.addLayout(overlay_row)
        self.checklist = DetailsToggle(
            "\n".join(f"- {line}" for line in CHECKLIST),
            title="After installing, check in game",
        )
        write_layout.addWidget(self.checklist)
        layout.addWidget(write)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setPlaceholderText("What happened: exports, installs, messages.")
        self.log.setMaximumHeight(90)
        layout.addWidget(self.log)

        controller.log_message.connect(self.append_log)
        controller.plan_ready.connect(self._show_plan)
        controller.plan_failed.connect(self._plan_failed)
        controller.export_finished.connect(self._export_finished)
        controller.install_finished.connect(self._install_finished)
        controller.busy_changed.connect(self._busy_changed)
        controller.template_changed.connect(lambda _key: self._show_plan(None))
        self._busy_changed(False)

    # ------------------------------------------------------------------ actions

    def _build(self) -> None:
        self.summary.setPlainText("Building the plan...")
        self.plan_state.set_note("Building...", None)
        if not self._controller.start_plan():
            self.plan_state.set_note("The plan could not start; see the message above.", BLOCK)
            return

    def _mod_base_changed(self) -> None:
        """Follow the folder box: say what is already there, and plan on it when asked."""

        from cdmw.services.new_item_mod_base import describe_mod_folder

        text = self.export_root.text().strip()
        found = describe_mod_folder(Path(text)) if text else ""
        self.add_to_mod.setVisible(bool(found))
        self.mod_base_note.setVisible(bool(found))
        if not found:
            self.mod_base_note.setText("")
            self._controller.set_mod_base(None)
            return
        if self.add_to_mod.isChecked():
            self.mod_base_note.setText(f"{found} The next item is planned on its tables, so the folder will hold both.")
            self._controller.set_mod_base(Path(text))
        else:
            self.mod_base_note.setText(f"{found} Writing here will replace it, and only the new item will be in the tables.")
            self._controller.set_mod_base(None)

    def _pick_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose the loose mod output folder", self.export_root.text() or "")
        if path:
            self.export_root.setText(path)

    def _export(self) -> None:
        root = self.export_root.text().strip()
        if not root:
            QMessageBox.information(self, "Write loose mod", "Choose the folder the package is written into.")
            return
        if self._controller.plan is None:
            QMessageBox.information(self, "Write loose mod", "Build the plan first.")
            return
        self._controller.start_export(Path(root), self.manager.currentText())

    # ------------------------------------------------------------------ results

    def append_log(self, message: str) -> None:
        self.log.appendPlainText(str(message))

    def _show_plan(self, plan: Optional[NewItemPlan]) -> None:
        enabled = plan is not None
        self.export_button.setEnabled(enabled and not self._controller.busy)
        self.install_button.setEnabled(enabled and not self._controller.busy)
        if plan is None:
            self.summary.setPlainText("")
            self.plan_state.set_note("Not built yet. Every change on the other steps clears the plan, so build it last.", WARN)
            return
        warnings = len(plan.warnings)
        self.plan_state.set_note(
            f"Ready: item {plan.spec.item_key}, {len(plan.patches)} table file(s) replaced, {len(plan.additions)} new file(s)"
            + (f", {warnings} warning(s) below" if warnings else ""),
            WARN if warnings else OK,
        )
        lines = [f"Item {plan.spec.item_key} {plan.spec.internal_name} from template {plan.spec.template_key}"]
        if plan.spec.stem:
            lines.append(f"Model stem: {plan.spec.stem}")
        lines.append("")
        lines.extend(plan.summary_lines)
        if plan.warnings:
            lines.append("")
            lines.append("Warnings:")
            lines.extend(f"- {warning}" for warning in plan.warnings)
        notes = [issue for issue in plan.issues if not issue.is_error]
        if notes:
            lines.append("")
            lines.extend(f"Note: {issue.message}" for issue in notes)
        lines.append("")
        lines.append(f"{len(plan.patches)} table file(s) replaced, {len(plan.additions)} new file(s):")
        lines.extend(f"- {path}" for path in plan.new_paths)
        self.summary.setPlainText("\n".join(lines))

    def _plan_failed(self, message: str, issues: object) -> None:
        lines = [f"The plan could not be built: {message}"]
        for issue in tuple(issues or ())[:12]:
            lines.append(f"- {issue.field}: {issue.message}")
        self._show_plan(None)
        self.summary.setPlainText("\n".join(lines))
        self.plan_state.set_note(f"Blocked: {message}", BLOCK)

    def _export_finished(self, result: object) -> None:
        root = getattr(result, "package_root", "")
        count = len(getattr(result, "payload_paths", ()) or ())
        new = len(getattr(result, "new_paths", ()) or ())
        self.append_log(f"Loose mod written to {root}: {count} file(s), {new} new.")
        QMessageBox.information(self, "Write loose mod", f"Written to {root}\n\n{count} file(s), {new} of them new.")

    def _install_finished(self, result: object) -> None:
        title, message = install_result_report(result)
        self.append_log(message.replace("\n\n", " "))
        QMessageBox.information(self, title, message)

    def _busy_changed(self, busy: bool) -> None:
        lane = str(getattr(self._controller, "_lane", "") or "")
        working = bool(busy) and lane in {"plan", "export", "install", "snapshot"}
        self.busy_bar.setVisible(working)
        if not working:
            self.busy_state.set_note("", None)
        elif lane == "plan":
            self.busy_state.set_note("Building the plan; the window stays usable while it runs.", EDIT)
        elif lane == "export":
            self.busy_state.set_note("Writing the mod folder...", EDIT)
        elif lane == "install":
            self.busy_state.set_note("Installing into the game archives: backing up, validating, writing.", EDIT)
        elif lane == "snapshot":
            self.busy_state.set_note("Reading the archives...", EDIT)
        else:
            self.busy_state.set_note("Working...", EDIT)
        self.build_button.setEnabled(not busy)
        has_plan = self._controller.plan is not None
        self.export_button.setEnabled(has_plan and not busy)
        self.install_button.setEnabled(has_plan and not busy)


__all__ = ["CHECKLIST", "OutputPanel", "install_result_report"]
