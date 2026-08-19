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

from PySide6.QtCore import Qt, Signal
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
        self.controller.busy_changed.connect(lambda busy: self._progress.setVisible(bool(busy) and not self._panels_built))

    # ------------------------------------------------------------------ bootstrap

    def start_snapshot(self) -> None:
        if self.controller.busy or self.controller.ready:
            return
        entries = tuple(self._get_entries() or ())
        package_root: Optional[Path] = None
        if not entries:
            # the shell's catalogue backend shows the browser without filling the legacy
            # entry list; the studio then lists the archives itself from the package root
            root_text = str(self._get_package_root() or "").strip()
            if not root_text or not Path(root_text).is_dir():
                self._status.setText("The archive list is empty and no game folder is set. Set the game folder in the Archive Browser first, then come back.")
                return
            package_root = Path(root_text)
        self._read_button.setEnabled(False)
        self._progress.setVisible(True)
        if entries:
            self._status.setText(f"Reading the tables from {len(entries):,} archive entries...")
        else:
            self._status.setText(f"Listing the archives under {package_root}, then reading the tables...")
        self.controller.log_message.connect(self._status.setText)
        if not self.controller.start_snapshot(entries, package_root=package_root):
            self._read_button.setEnabled(True)
            self._progress.setVisible(False)

    def _snapshot_failed(self, message: str) -> None:
        self._progress.setVisible(False)
        self._read_button.setEnabled(True)
        self._read_button.setText("Try again")
        self._status.setText(f"The archives could not be read for a new item.\n\n{message}")

    def _snapshot_ready(self) -> None:
        try:
            self.controller.log_message.disconnect(self._status.setText)
        except (RuntimeError, TypeError):
            pass
        self._mount_panels()
        if self._pending_template is not None:
            key, self._pending_template = self._pending_template, None
            self.template_panel.prefill(key)

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
        controller.model_import_changed.connect(lambda _source: self.identity_panel.refresh_issues())
        controller.model_import_changed.connect(self._refresh_summary)
        controller.model_placement_changed.connect(self._refresh_summary)
        self.output_panel.install_requested.connect(self._install)
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
            holder = QWidget()
            holder_layout = QVBoxLayout(holder)
            holder_layout.setContentsMargins(0, 0, 0, 0)
            fills = panel in (self.template_panel, self.model_panel, self.output_panel)
            holder_layout.addWidget(panel, 1 if fills else 0)
            if not fills:
                holder_layout.addStretch(1)
            page = QScrollArea()
            page.setWidgetResizable(True)
            page.setFrameShape(QScrollArea.NoFrame)
            page.setWidget(holder)
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
        self.legend = QLabel(f"{green} settled, {amber} wants a decision or an in-game check, {red} blocks the plan, {blue} differs from the template.")
        self.legend.setObjectName("new_item_intro")
        self.legend.setWordWrap(True)
        summary_layout.addWidget(self.legend)
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
        edits = len(draft.grid_values) + len(draft.price_values) + int(draft.extra_levels) + (1 if draft.max_stack_count is not None else 0)
        lines.append(note(f"Stats and prices: {edits} edit(s)", EDIT) if edits else note("Stats and prices: as the template", OK))
        lines.append(note("Perks: chosen here", EDIT) if draft.socket_items is not None else note("Perks: the template's", OK))
        lines.append(note(f"Effect: {draft.effect_stem}", EDIT) if draft.effect_stem else note("Effect: none", OK))
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

    # ------------------------------------------------------------------ lifecycle

    def iter_shutdown_workers(self):
        return self.controller.iter_shutdown_workers()

    def request_shutdown(self) -> None:
        self.controller.request_shutdown()

    def shutdown(self) -> None:
        if self._panels_built:
            self.model_panel.shutdown_preview()
        self.controller.shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        self.shutdown()
        super().closeEvent(event)


__all__ = ["NewItemStudioTab"]
