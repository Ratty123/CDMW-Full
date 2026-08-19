"""New Item Studio, panel 6: build the plan, write a loose mod, or install."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
)

from cdmw.services.new_item_planning import NewItemPlan
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.state import MANAGERS
from cdmw.ui.new_item.ui_kit import BLOCK, OK, WARN, DetailsToggle, NoteLabel, intro_label

CHECKLIST = (
    "In game: the item shows in the shop you chose (or in the inventory when given by other means).",
    "Its name and description read right in your language.",
    "It equips, draws and sheathes; the imported model, if any, renders.",
    "An imported model's textures read as the source's (albedo, shine and glow); the plain PBR shaders are the first thing to switch off if they do not.",
    "The icon shows (a generated icon at a new path is the first thing to check).",
    "Its stats match the grid; an added level is the least-proven part.",
    "The tooltip lists the perks you chose; a weapon effect, if any, shows on the drawn blade.",
)


class OutputPanel(QGroupBox):
    #: The tab asks the shell for confirmation and the mutation service, then installs.
    install_requested = Signal()

    def __init__(self, controller: NewItemStudioController, parent=None) -> None:
        super().__init__("7. Output", parent)
        self._controller = controller
        layout = QVBoxLayout(self)
        layout.addWidget(intro_label("Build the plan (nothing is written yet), read what it changes, then write a mod folder or install into the game."))

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
        install = QHBoxLayout()
        self.install_button = QPushButton("Install into the game archives...")
        self.install_button.setToolTip("Confirmed first, backed up, restorable. Refused while the game is running.")
        self.install_button.clicked.connect(self.install_requested.emit)
        install.addWidget(self.install_button)
        install.addWidget(QLabel("or write it straight into the game (asks first, keeps a backup)."))
        install.addStretch(1)
        write_layout.addLayout(install)
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
        backup = getattr(result, "backup_dir", "")
        changed = len(getattr(result, "changed_paths", ()) or ())
        self.append_log(f"Installed: {changed} archive entr(ies) written. Backup: {backup}")
        QMessageBox.information(
            self, "Install into the game archives",
            f"Installed {changed} archive entr(ies).\n\nBackup: {backup}\n\nStart the game and go through the checklist.",
        )

    def _busy_changed(self, busy: bool) -> None:
        self.build_button.setEnabled(not busy)
        has_plan = self._controller.plan is not None
        self.export_button.setEnabled(has_plan and not busy)
        self.install_button.setEnabled(has_plan and not busy)


__all__ = ["CHECKLIST", "OutputPanel"]
