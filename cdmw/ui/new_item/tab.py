"""New Item Studio: the tab that composes the seven panels around one controller.

The tab is thin on purpose. It reads the archive list off the shell window, hands it
to the controller for the one-time snapshot, mounts the panels once that snapshot is
ready, and forwards two requests it cannot fulfil itself: importing a model (the shell
owns Import Mesh) and installing (the shell owns the mutation service and the
confirmation). It never touches the archives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional

from PySide6.QtCore import Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import ArchiveEntry
from cdmw.services.new_item_service import NewItemService
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_identity import IdentityPanel
from cdmw.ui.new_item.panels_model import ModelPanel
from cdmw.ui.new_item.panels_output import OutputPanel
from cdmw.ui.new_item.panels_perks import PerksPanel
from cdmw.ui.new_item.panels_placement import PlacementPanel
from cdmw.ui.new_item.panels_stats import StatsPanel
from cdmw.ui.new_item.panels_template import TemplatePanel
from cdmw.ui.new_item.ui_kit import BLOCK, EDIT, OK, WARN, NoteLabel, note, step_style, tinted


#: the left rail: the step list and the item so far, and how many characters one of its lines holds
RAIL_WIDTH = 300
RAIL_CHARS = 40


def _window_package_root(window: object) -> str:
    """The game folder the shell's Archive Browser points at, if the window has one."""

    edit = getattr(window, "archive_package_root_edit", None)
    text = getattr(edit, "text", None)
    if callable(text):
        try:
            return str(text() or "")
        except Exception:  # noqa: BLE001 - a half-built window is not a reason to raise
            return ""
    return str(getattr(window, "archive_package_root", "") or "")


class NewItemStudioTab(QWidget):
    """Clone an equipment item into a brand-new one: identity, model, icon, stats, perks, shop, output."""

    status_message_requested = Signal(str, bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        window: object = None,
        service: Optional[NewItemService] = None,
        controller: Optional[NewItemStudioController] = None,
        get_archive_entries: Optional[Callable[[], Iterable[ArchiveEntry]]] = None,
        get_package_root: Optional[Callable[[], str]] = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._get_entries = get_archive_entries or (lambda: getattr(window, "archive_entries", None) or ())
        self._get_package_root = get_package_root or (lambda: _window_package_root(window))
        self.controller = controller or NewItemStudioController(service=service, parent=self)
        cache_root = getattr(window, "archive_cache_root", None)
        if cache_root is not None and self.controller.effect_cache_path is None:
            self.controller.effect_cache_path = Path(cache_root) / "index" / "effect_catalogue_v1.json"
        self._pending_template: Optional[int] = None
        self._pending_model_import: Optional[Path] = None
        self._panels_built = False
        self._refreshing_checks = False

        self._status = QLabel("New Item Studio reads the item, string, store, group and language tables once, then plans a new item against them.")
        self._status.setWordWrap(True)
        self._status.setAlignment(Qt.AlignCenter)
        self._progress = QProgressBar()
        self._progress.setRange(0, 0)
        self._progress.setVisible(False)
        self._read_button = QPushButton("Read the archives")
        self._read_button.clicked.connect(self.start_snapshot)
        self._bootstrap = QWidget()
        boot = QVBoxLayout(self._bootstrap)
        boot.setContentsMargins(24, 24, 24, 24)
        boot.addStretch(1)
        boot.addWidget(self._status)
        boot.addWidget(self._progress)
        boot.addWidget(self._read_button, alignment=Qt.AlignHCenter)
        boot.addStretch(1)

        self._layout = QVBoxLayout(self)
        self._layout.setContentsMargins(0, 0, 0, 0)
        self._layout.addWidget(self._bootstrap, 1)

        self.controller.snapshot_ready.connect(self._snapshot_ready)
        self.controller.snapshot_failed.connect(self._snapshot_failed)
        self.controller.status_message.connect(self.status_message_requested.emit)
        self.controller.busy_changed.connect(self._bootstrap_busy_changed)

    # ------------------------------------------------------------------ bootstrap

    def _bootstrap_busy_changed(self, busy: object) -> None:
        """The bootstrap's own progress bar, while the archives are being read.

        Only until the panels replace the bootstrap, which is deleted then -- and this
        signal goes on firing for every operation after it: an import, a plan, an install.
        A lambda used to do this, and a lambda has no receiver for Qt to disconnect when
        the widget dies, so `setVisible` was still called on a deleted C++ object. It was
        called whatever the flag said, too, because the flag was inside the argument.
        """

        if self._panels_built:
            return
        progress = getattr(self, "_progress", None)
        if progress is None:
            return
        try:
            progress.setVisible(bool(busy))
        except RuntimeError:
            # deleted between the check and the call; there is nothing left to show
            self._progress = None

    def start_snapshot(self) -> None:
        if self.controller.busy:
            return
        entries = tuple(self._get_entries() or ())
        package_root: Optional[Path] = None
        if not entries:
            # the shell's catalogue backend shows the browser without filling the legacy
            # entry list; the studio then lists the archives itself from the package root
            root_text = str(self._get_package_root() or "").strip()
            if not root_text or not Path(root_text).is_dir():
                if self._panels_built:
                    self.status_message_requested.emit("The archive list is empty and no game folder is set. Set the game folder in the Archive Browser first, then come back.", True)
                else:
                    self._status.setText("The archive list is empty and no game folder is set. Set the game folder in the Archive Browser first, then come back.")
                return
            package_root = Path(root_text)
        if self._panels_built:
            self.output_panel.append_log("Reading the archives again so the next item gets its own key and stem...")
        else:
            self._read_button.setEnabled(False)
            self._progress.setVisible(True)
            if entries:
                self._status.setText(f"Reading the tables from {len(entries):,} archive entries...")
            else:
                self._status.setText(f"Listing the archives under {package_root}, then reading the tables...")
            self.controller.log_message.connect(self._status.setText)
        if not self.controller.start_snapshot(entries, package_root=package_root):
            if not self._panels_built:
                self._read_button.setEnabled(True)
                self._progress.setVisible(False)

    def _snapshot_failed(self, message: str) -> None:
        if self._panels_built:
            self.output_panel.append_log(f"The archives could not be read for a new item.\n\n{message}")
            self.status_message_requested.emit(message, True)
            return
        self._progress.setVisible(False)
        self._read_button.setEnabled(True)
        self._read_button.setText("Try again")
        self._status.setText(f"The archives could not be read for a new item.\n\n{message}")

    def _snapshot_ready(self) -> None:
        if self._panels_built:
            self.template_panel._refresh_matches()
            self.stats_panel.rebuild()
            self.perks_panel._refresh_all()
            self.placement_panel._refresh_stores()
            self.placement_panel._refresh_groups()
            self.identity_panel.refresh_issues()
            self._refresh_summary()
            return
        try:
            self.controller.log_message.disconnect(self._status.setText)
        except (RuntimeError, TypeError):
            pass
        self._mount_panels()
        if self._pending_template is not None:
            key, self._pending_template = self._pending_template, None
            self.template_panel.prefill(key)
        if self._pending_model_import is not None:
            model_path, self._pending_model_import = self._pending_model_import, None
            self.open_model_source(model_path)

    def _mount_panels(self) -> None:
        if self._panels_built:
            return
        self._panels_built = True
        self._layout.removeWidget(self._bootstrap)
        self._bootstrap.setParent(None)
        self._bootstrap.deleteLater()

        controller = self.controller
        self.template_panel = TemplatePanel(controller)
        self.identity_panel = IdentityPanel(controller)
        self.model_panel = ModelPanel(controller)
        self.stats_panel = StatsPanel(controller)
        self.perks_panel = PerksPanel(controller)
        self.placement_panel = PlacementPanel(controller)
        self.output_panel = OutputPanel(controller)
        controller.install_finished.connect(lambda _result: QTimer.singleShot(0, self._reread_after_install))
        controller.model_import_changed.connect(lambda _source: self.identity_panel.refresh_issues())
        controller.model_import_changed.connect(self._refresh_summary)
        controller.model_placement_changed.connect(self._refresh_summary)
        self.output_panel.install_requested.connect(self._install)
        self.output_panel.install_overlay_requested.connect(self._install_overlay)
        self.output_panel.overlay_migration_requested.connect(self._migrate_overlay)
        self.output_panel.overlay_removal_requested.connect(self._remove_overlay)
        controller.template_changed.connect(lambda _key: self.identity_panel.refresh_issues())
        controller.model_changed.connect(lambda _result: self.identity_panel.refresh_issues())

        # one step at a time: a step list on the left (as tall as its seven lines), under it
        # the item so far, one tinted line per step; the step's panel fills the right;
        # Back/Next along the bottom
        self.setStyleSheet(step_style(self.palette()))
        self.steps = QListWidget()
        self.steps.setObjectName("new_item_steps")
        self.steps.setFixedWidth(RAIL_WIDTH)
        self.steps.setSpacing(2)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.pages = QStackedWidget()
        self._panels = (self.template_panel, self.identity_panel, self.model_panel, self.stats_panel, self.perks_panel, self.placement_panel, self.output_panel)
        for panel in self._panels:
            item = QListWidgetItem(panel.title())
            item.setToolTip(panel.toolTip())
            self.steps.addItem(item)
            panel.setObjectName("new_item_step")
            # the panel takes the height its content needs and sits at the top; the page
            # below it is plain background, not an empty frame
            # The panel goes into the scroll area itself: with a holder widget in between,
            # the area sized that holder to the viewport and left it shorter than the
            # panel's own minimum, so the widgets under a grown table were drawn over it.
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QScrollArea.NoFrame)
            page.setWidget(panel)
            self.pages.addWidget(page)
        self.steps.currentRowChanged.connect(self._show_step)
        rows_height = sum(self.steps.sizeHintForRow(i) + 2 * self.steps.spacing() for i in range(self.steps.count()))
        self.steps.setFixedHeight(rows_height + 2 * self.steps.frameWidth() + 6)

        self.summary_box = QGroupBox("Your item so far")
        summary_layout = QVBoxLayout(self.summary_box)
        self.summary = NoteLabel("")
        self.summary.setObjectName("new_item_summary")
        summary_layout.addWidget(self.summary)
        green, amber, red, blue = tinted("green", OK), tinted("amber", WARN), tinted("red", BLOCK), tinted("blue", EDIT)
        self.summary_box.setToolTip(f"{green} settled, {amber} wants a decision or an in-game check, {red} blocks the plan, {blue} differs from the template.")
        summary_layout.addStretch(1)
        rail = QVBoxLayout()
        rail.setContentsMargins(0, 0, 0, 0)
        rail.setSpacing(8)
        rail.addWidget(self.steps)
        rail.addWidget(self.summary_box, 1)
        rail_widget = QWidget()
        rail_widget.setLayout(rail)
        rail_widget.setFixedWidth(RAIL_WIDTH)

        columns = QHBoxLayout()
        columns.setContentsMargins(0, 0, 0, 0)
        columns.setSpacing(10)
        columns.addWidget(rail_widget)
        columns.addWidget(self.pages, 1)
        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 8)
        body_layout.setSpacing(8)
        body_layout.addLayout(columns, 1)
        footer = QHBoxLayout()
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(lambda: self._step_by(-1))
        self.next_button = QPushButton("Next")
        self.next_button.clicked.connect(lambda: self._step_by(+1))
        footer.addWidget(self.back_button)
        footer.addWidget(self.next_button)
        self.step_hint = QLabel("")
        self.step_hint.setObjectName("new_item_intro")
        footer.addSpacing(16)
        footer.addWidget(self.step_hint, 1)
        body_layout.addLayout(footer)
        self._layout.addWidget(body, 1)
        controller.template_changed.connect(self._refresh_summary)
        controller.model_changed.connect(self._refresh_summary)
        controller.plan_ready.connect(self._refresh_summary)
        controller.plan_failed.connect(self._refresh_summary)
        controller.plan_invalidated.connect(self._refresh_summary)
        self.identity_panel.internal_name.textChanged.connect(self._refresh_summary)
        self.identity_panel.display_name.textChanged.connect(self._refresh_summary)
        for radio in (self.placement_panel.no_store, self.placement_panel.swap, self.placement_panel.insert):
            radio.toggled.connect(self._refresh_summary)
        self.placement_panel.store.currentIndexChanged.connect(self._refresh_summary)
        self.placement_panel.old_item.currentIndexChanged.connect(self._refresh_summary)
        self.perks_panel.use_effect.toggled.connect(self._refresh_summary)
        self.perks_panel.effect.currentIndexChanged.connect(self._refresh_summary)
        self.perks_panel.own_perks.toggled.connect(self._refresh_summary)
        self.stats_panel.table.itemChanged.connect(self._refresh_summary)
        self.stats_panel.price_table.itemChanged.connect(self._refresh_summary)
        self.steps.setCurrentRow(0)
        self._refresh_summary()
        self.template_panel._refresh_matches()
        self.placement_panel._refresh_stores()

    # ------------------------------------------------------------------ steps

    def _show_step(self, row: int) -> None:
        if row < 0:
            return
        # the template list takes a row once the reader settles on it; leaving the step
        # is settling on it, and the steps after read the template
        if self._panels_built:
            self.template_panel.apply_pending_pick()
        self.pages.setCurrentIndex(row)
        self.back_button.setEnabled(row > 0)
        self.next_button.setEnabled(row < self.pages.count() - 1)
        self.step_hint.setText(f"Step {row + 1} of {self.pages.count()}" + ("" if row < self.pages.count() - 1 else ": build the plan, then write or install it"))

    def _step_by(self, delta: int) -> None:
        row = self.steps.currentRow() + int(delta)
        if 0 <= row < self.pages.count():
            self.steps.setCurrentRow(row)

    def show_step(self, index: int) -> None:
        """Bring step `index` (0-based) to the front; the shell and the panels use it to
        jump the reader to where a message points."""

        if 0 <= int(index) < self.pages.count():
            self.steps.setCurrentRow(int(index))

    def _refresh_summary(self, *_args) -> None:
        """The rail's "item so far": one line per step, tinted by what it still needs; the
        Checks on step 2 read the same draft, so they follow every change too."""

        controller = self.controller
        if self._panels_built and not self._refreshing_checks:
            self._refreshing_checks = True
            try:
                self.identity_panel.refresh_issues()
            finally:
                self._refreshing_checks = False
        draft = controller.draft
        lines = []
        template = controller.template_name()
        lines.append(note(f"Template: {template}", OK) if template else note("Template: choose one", WARN))
        if draft.internal_name:
            english = (draft.display_names or {}).get("eng", "")
            lines.append(note(f"Name: {draft.internal_name} ({english})", OK) if english else note(f"Name: {draft.internal_name}, no English display name yet", WARN))
        else:
            lines.append(note("Name: not set", WARN))
        blocked = [issue for issue in controller.validate() if issue.is_error] if controller.ready else []
        if blocked:
            lines.append(note(f"{len(blocked)} thing(s) block the plan (see step 2)", BLOCK))
        imported = controller.model_import
        if imported is not None and controller.model_result is None:
            lines.append(note(f"Model: {imported.label}, placement not applied", WARN))
        elif imported is not None or controller.model_result is not None:
            lines.append(note(f"Model: {imported.label if imported is not None else 'imported'}, placed", EDIT))
        else:
            lines.append(note("Model: the template's", OK))
        stats_text, stats_changed = self.stats_panel.summary_text()
        lines.append(note(stats_text, EDIT if stats_changed else OK))
        perks_text, perks_changed = self.perks_panel.perks_summary()
        lines.append(note(perks_text, EDIT if perks_changed else OK))
        effect_text, effect_changed = self.perks_panel.effect_summary()
        effect_tone = WARN if self.perks_panel.use_effect.isChecked() and not draft.effect_stem else EDIT if effect_changed else OK
        lines.append(note(effect_text, effect_tone))
        if draft.placement_kind.value != "none" and draft.store_name:
            lines.append(note(f"Shop: {draft.store_name}", OK))
        else:
            lines.append(note("Shop: not sold anywhere (nothing hands the item out)", WARN))
        if controller.plan is not None:
            lines.append(note(f"Plan: ready, item {controller.plan.spec.item_key}", OK))
        else:
            lines.append(note("Plan: not built yet", WARN))
        self.summary.set_lines(lines, line_chars=RAIL_CHARS)

    # ------------------------------------------------------------------ entry points

    def prefill_template(self, template_key: int) -> None:
        """Point the studio at a template (from the Item Finder or the Builder)."""

        if not self.controller.ready:
            self._pending_template = int(template_key)
            self.start_snapshot()
            return
        self.template_panel.prefill(int(template_key))

    def open_model_source(self, path: Path | str) -> None:
        """Open the model step and begin its normal cancellable import."""

        model_path = Path(path).expanduser().resolve()
        if not self.controller.ready or not self._panels_built:
            self._pending_model_import = model_path
            self.start_snapshot()
            return
        self.steps.setCurrentRow(2)
        self.controller.start_model_import(model_path)

    def _reread_after_install(self) -> None:
        """After an install the archives hold the new item: read them again, so the next
        item is allocated its own key and stem instead of the one just written."""

        self.output_panel.append_log("Reading the archives again so the next item gets its own key and stem...")
        self.start_snapshot()

    def receive_imported_model(self, entry: Optional[ArchiveEntry], result: object, scene: object | None = None) -> None:
        """Take a Builder result for the current template's mesh, with the scene import
        it was built from when the hand-off carried it (the plain-PBR material route
        reads the source's own textures through it)."""

        self.controller.set_imported_model(entry, result, scene)
        if self._panels_built:
            self.identity_panel.refresh_issues()

    def _install(self) -> None:
        plan = self.controller.plan
        if plan is None:
            return
        services = getattr(getattr(self._window, "app_context", None), "services", None)
        mutations = getattr(services, "require_archive_mutations", None)
        if not callable(mutations):
            QMessageBox.warning(self, "Install into the game archives", "The archive mutation service is not available in this window.")
            return
        touched = "\n".join(f"- {path}" for path in plan.touched_paths[:14])
        more = f"\n- ... {len(plan.touched_paths) - 14} more" if len(plan.touched_paths) > 14 else ""
        confirmation = QMessageBox.question(
            self,
            "Install into the game archives",
            (
                f"Install {plan.spec.internal_name} (item {plan.spec.item_key}) into the game archives?\n\n"
                f"{len(plan.patches)} table file(s) are replaced and {len(plan.additions)} file(s) are added:\n{touched}{more}\n\n"
                "A backup of the touched archive files is created before anything is written, and the game must not be running."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        self.controller.start_install(mutations())

    def _install_overlay(self) -> None:
        plan = self.controller.plan
        if plan is None:
            return
        services = getattr(getattr(self._window, "app_context", None), "services", None)
        mutations = getattr(services, "require_archive_mutations", None)
        if not callable(mutations):
            QMessageBox.warning(self, "Install as an overlay", "The archive mutation service is not available in this window.")
            return
        touched = "\n".join(f"- {path}" for path in plan.touched_paths[:14])
        more = f"\n- ... {len(plan.touched_paths) - 14} more" if len(plan.touched_paths) > 14 else ""
        confirmation = QMessageBox.question(
            self,
            "Install as an overlay",
            (
                f"Install {plan.spec.internal_name} (item {plan.spec.item_key}) as an archive directory of its own?\n\n"
                f"{len(plan.patches) + len(plan.additions)} file(s) go into the new directory:\n{touched}{more}\n\n"
                "The archives the game shipped are not written to. The mount list and the texture registry are backed "
                "up first, and the game must not be running."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        self.controller.start_install_overlay(mutations())

    def _overlay_services(self, title: str):
        """The mutation service (for the backup) and the package root, or None with a word."""

        services = getattr(getattr(self._window, "app_context", None), "services", None)
        mutations = getattr(services, "require_archive_mutations", None)
        if not callable(mutations):
            QMessageBox.warning(self, title, "The archive mutation service is not available in this window.")
            return None
        root = str(self._get_package_root() or "").strip()
        if not root:
            QMessageBox.warning(self, title, "Point the workbench at the game folder first.")
            return None
        return mutations(), Path(root)

    def _migrate_overlay(self) -> None:
        title = "Move installed items into the overlay"
        found = self._overlay_services(title)
        if found is None:
            return
        mutations, root = found
        from cdmw.services.archive_overlay_migration import plan_migration

        try:
            preview = plan_migration(root)
        except Exception as exc:  # noqa: BLE001 - the message is the answer
            QMessageBox.warning(self, title, f"The archives could not be read: {exc}")
            return
        if preview.is_empty:
            QMessageBox.information(self, title, "Nothing in the shipped archives differs from the oldest backup of it, so there is nothing to move.")
            return
        listed = "\n".join(f"- {item.path}" for item in preview.entries[:12])
        more = f"\n- ... {len(preview.entries) - 12} more" if len(preview.entries) > 12 else ""
        confirmation = QMessageBox.question(
            self,
            title,
            (
                f"Move {len(preview.entries)} archive entrie(s) into the overlay and put the shipped archives back?\n\n"
                f"{listed}{more}\n\n"
                f"{len(preview.restore)} archive file(s) go back to their oldest backup ({len(preview.backups)} backup(s) read). "
                "The game must not be running."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        self.controller.start_overlay_migration(mutations, root)

    def _remove_overlay(self) -> None:
        title = "Remove the overlay"
        found = self._overlay_services(title)
        if found is None:
            return
        mutations, root = found
        confirmation = QMessageBox.question(
            self,
            title,
            (
                "Unmount the overlay directory and delete it?\n\n"
                "Every item that lives only in the overlay leaves the game with it. Items written into the shipped "
                "archives stay where they are. The game must not be running."
            ),
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        self.controller.start_overlay_removal(mutations, root)

    # ------------------------------------------------------------------ lifecycle

    def iter_shutdown_workers(self):
        workers = list(self.controller.iter_shutdown_workers())
        if self._panels_built:
            workers.extend(self.model_panel.iter_shutdown_workers())
            workers.extend(self.perks_panel.iter_shutdown_workers())
        return tuple(workers)

    def request_shutdown(self) -> None:
        self.controller.request_shutdown()
        if self._panels_built:
            self.model_panel.request_shutdown_preview()
            self.perks_panel.request_shutdown()

    def shutdown(self) -> None:
        self.request_shutdown()
        if self._panels_built:
            self.model_panel.shutdown_preview()
        self.controller.shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        self.shutdown()
        super().closeEvent(event)


__all__ = ["NewItemStudioTab"]
