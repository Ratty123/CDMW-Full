"""Create New Item: the tab that composes the seven panels around one controller.

The tab is thin on purpose. It reads the archive list off the shell window, hands it
to the controller for the one-time snapshot, mounts the panels once that snapshot is
ready, and forwards two requests it cannot fulfil itself: importing a model (the shell
owns Import Mesh) and installing (the shell owns the mutation service and the
confirmation). It never touches the archives.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable, Iterable, Optional

from PySide6.QtCore import QEvent, Qt, Signal, QTimer
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import (
    ArchiveEntry,
    ModelPreviewRenderSettings,
    clamp_archive_performance_settings,
    clamp_model_preview_render_settings,
)
from cdmw.services.cache_layout import runtime_cache_layout
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
from cdmw.ui.new_item.workflow_header import WorkflowHeader, WorkflowStepState


#: the left rail: the step list and the item so far, and how many characters one of its lines holds
RAIL_WIDTH = 300
RAIL_CHARS = 40
_GAME_COMPATIBILITY_FEATURE = "new_item_archive_snapshot"
_PAPPT_LAYOUT_ERROR_PREFIX = "unsupported part-prefab table layout"


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
        effect_dirty_prompt: Optional[Callable[[], str]] = None,
    ) -> None:
        super().__init__(parent)
        self._applying_step_style = False
        self._window = window
        self._get_entries = get_archive_entries or (lambda: getattr(window, "archive_entries", None) or ())
        self._get_package_root = get_package_root or (lambda: _window_package_root(window))
        self._effect_dirty_prompt = effect_dirty_prompt or self._prompt_for_staged_effect
        self.controller = controller or NewItemStudioController(service=service, parent=self)
        cache_root = getattr(window, "archive_cache_root", None)
        if cache_root is not None and self.controller.effect_cache_path is None:
            self.controller.effect_cache_path = Path(cache_root) / "index" / "effect_catalogue_v1.json"
        self._pending_template: Optional[int] = None
        self._pending_model_import: Optional[Path] = None
        self._panels_built = False
        preview_settings_provider = getattr(window, "_current_model_preview_render_settings", None)
        self._preview_render_settings: ModelPreviewRenderSettings = clamp_model_preview_render_settings(
            preview_settings_provider() if callable(preview_settings_provider) else None
        )
        archive_settings_provider = getattr(window, "_current_archive_performance_settings", None)
        self._preview_cache_mode = clamp_archive_performance_settings(
            archive_settings_provider() if callable(archive_settings_provider) else None
        ).native_preview_cache_mode
        self._refreshing_checks = False
        self._effect_staged_dirty = False
        self._model_part_editor_source: object | None = None
        self._model_part_editor_widget: object | None = None
        self._model_part_editor_controller: object | None = None
        self._model_part_editor_session_id = ""
        self._current_step = 0
        self._syncing_step = False

        self._status = QLabel("Create New Item reads the item, string, store, group and language tables once, then plans a new item against them.")
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
        preview_settings_signal = getattr(
            getattr(window, "settings_tab", None),
            "model_preview_settings_changed",
            None,
        )
        if preview_settings_signal is not None:
            preview_settings_signal.connect(self.set_preview_render_settings)
        archive_settings_signal = getattr(
            getattr(window, "settings_tab", None),
            "archive_performance_settings_changed",
            None,
        )
        if archive_settings_signal is not None:
            archive_settings_signal.connect(self.set_archive_performance_settings)

    # ------------------------------------------------------------------ bootstrap

    def changeEvent(self, event: QEvent) -> None:  # noqa: N802 - QWidget API
        super().changeEvent(event)
        if event.type() in {
            QEvent.Type.ApplicationPaletteChange,
            QEvent.Type.PaletteChange,
        }:
            self._apply_step_style()

    def _apply_step_style(self) -> None:
        if getattr(self, "_applying_step_style", False):
            return
        stylesheet = step_style(self.palette())
        if self.styleSheet() == stylesheet:
            return
        self._applying_step_style = True
        try:
            self.setStyleSheet(stylesheet)
        finally:
            self._applying_step_style = False

    def set_preview_render_settings(self, settings: object | None) -> None:
        self._preview_render_settings = clamp_model_preview_render_settings(settings)
        model_panel = getattr(self, "model_panel", None)
        if model_panel is not None:
            model_panel.preview.set_render_settings(self._preview_render_settings)

    def set_archive_performance_settings(self, settings: object | None) -> None:
        self._preview_cache_mode = clamp_archive_performance_settings(settings).native_preview_cache_mode
        model_panel = getattr(self, "model_panel", None)
        if model_panel is not None:
            model_panel.preview.set_cache_mode(self._preview_cache_mode)

    def _game_package_root(self) -> Optional[Path]:
        root_text = str(self._get_package_root() or "").strip()
        return Path(root_text) if root_text else None

    def _record_snapshot_game_compatibility(self) -> None:
        recorder = getattr(self._window, "_record_game_feature_compatibility", None)
        package_root = self._game_package_root()
        if callable(recorder) and package_root is not None:
            recorder(package_root, _GAME_COMPATIBILITY_FEATURE)

    def _snapshot_game_update_note(self, message: str) -> str:
        if not str(message or "").casefold().startswith(_PAPPT_LAYOUT_ERROR_PREFIX):
            return ""
        evidence_provider = getattr(self._window, "_game_update_feature_error_evidence", None)
        package_root = self._game_package_root()
        if not callable(evidence_provider) or package_root is None:
            return ""
        if not evidence_provider(package_root, _GAME_COMPATIBILITY_FEATURE):
            return ""
        return self.tr("Game update detected via CrimsonDesert.exe hash.")

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
        entries_by_normalized_path = getattr(self._window, "archive_entries_by_normalized_path", None)
        entries_by_basename = getattr(self._window, "archive_entries_by_basename", None)
        entries_by_extension = getattr(self._window, "archive_entries_by_extension", None)
        if not self.controller.start_snapshot(
            entries,
            package_root=package_root,
            entries_by_normalized_path=entries_by_normalized_path,
            entries_by_basename=entries_by_basename,
            entries_by_extension=entries_by_extension,
        ):
            if not self._panels_built:
                self._read_button.setEnabled(True)
                self._progress.setVisible(False)

    def _snapshot_failed(self, message: str) -> None:
        update_note = self._snapshot_game_update_note(message)
        if update_note:
            message = f"{message}\n\n{update_note}"
        if self._panels_built:
            self.output_panel.append_log(f"The archives could not be read for a new item.\n\n{message}")
            self.status_message_requested.emit(message, True)
            return
        self._progress.setVisible(False)
        self._read_button.setEnabled(True)
        self._read_button.setText("Try again")
        self._status.setText(f"The archives could not be read for a new item.\n\n{message}")

    def _snapshot_ready(self) -> None:
        self._record_snapshot_game_compatibility()
        if self._panels_built:
            self.template_panel._refresh_matches()
            self.stats_panel.rebuild()
            self.perks_panel._refresh_all()
            self.placement_panel._refresh_stores()
            # The install changes group membership, not the catalogue; keep its Qt item wrappers.
            self.identity_panel.refresh_issues()
            self._refresh_summary()
            self.controller.start_effect_index()
            return
        try:
            self.controller.log_message.disconnect(self._status.setText)
        except (RuntimeError, TypeError):
            pass
        self._mount_panels()
        self.controller.start_effect_index()
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
        archive_cache_root = getattr(self._window, "archive_cache_root", None)
        native_preview_core_cache_root = (
            runtime_cache_layout(archive_cache_root).native_preview_root
            if archive_cache_root is not None
            else None
        )
        self.model_panel = ModelPanel(
            controller,
            native_preview_core_cache_root=native_preview_core_cache_root,
        )
        self.model_panel.preview.set_render_settings(self._preview_render_settings)
        self.model_panel.preview.set_cache_mode(self._preview_cache_mode)
        self.template_panel.mount_preview(self.model_panel.preview)
        self.stats_panel = StatsPanel(controller)
        self.perks_panel = PerksPanel(controller)
        self.placement_panel = PlacementPanel(controller)
        self.placement_panel.set_copper_price_requested.connect(self.stats_panel.set_copper_price)
        self.stats_panel.price_state_changed.connect(self.placement_panel.refresh_price_state)
        self.output_panel = OutputPanel(controller)
        controller.install_finished.connect(lambda _result: QTimer.singleShot(0, self._reread_after_install))
        controller.model_import_changed.connect(lambda _source: self.identity_panel.refresh_issues())
        controller.model_import_changed.connect(self._refresh_summary)
        controller.model_import_changed.connect(self._model_part_editor_source_changed)
        controller.model_placement_changed.connect(self._refresh_summary)
        controller.model_part_edit_finished.connect(self._model_part_edit_finished)
        controller.model_part_edit_failed.connect(self._model_part_edit_failed)
        self.model_panel.part_editor_open_requested.connect(self._open_model_part_editor)
        self.model_panel.part_editor_apply_requested.connect(self._use_model_part_editor_changes)
        self.output_panel.install_requested.connect(self._install)
        self.output_panel.install_overlay_requested.connect(self._install_overlay)
        self.output_panel.overlay_migration_requested.connect(self._migrate_overlay)
        self.output_panel.overlay_removal_requested.connect(self._remove_overlay)
        controller.model_changed.connect(lambda _result: self.identity_panel.refresh_issues())

        # One guided workspace: the clickable header owns navigation, the current page
        # owns the whole width, and the footer keeps Back / progress / Continue stable.
        self._apply_step_style()
        self.steps = WorkflowHeader()
        self.steps.setObjectName("new_item_steps")
        self.pages = QStackedWidget()
        self._panels = (self.template_panel, self.identity_panel, self.model_panel, self.stats_panel, self.perks_panel, self.placement_panel, self.output_panel)
        for index, panel in enumerate(self._panels):
            item = self.steps.item(index)
            if item is not None:
                item.setToolTip(panel.toolTip())
            panel.setObjectName("new_item_step")
            panel.setTitle("")
            panel.setProperty("guidedPage", True)
            if index in {2, 4}:
                panel.setProperty("guidedFullHeight", True)
                # The Model and Effects workspaces own their local inspector scrollers.
                # Wrapping either page here would make its resident viewport move when a
                # side panel scrolls and can introduce a horizontal bar at 1280 px.
                page = panel
            else:
                page = QScrollArea()
                page.setWidgetResizable(True)
                page.setFrameShape(QScrollArea.NoFrame)
                page.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
                page.setWidget(panel)
            self.pages.addWidget(page)
        self.steps.currentRowChanged.connect(self._show_step)

        # The old rail summary remains computed authority. It is hidden and projected
        # onto each header step's tooltip and accessible text instead of taking a column.
        self.summary_box = QGroupBox("Workflow state")
        summary_layout = QVBoxLayout(self.summary_box)
        summary_layout.setContentsMargins(0, 0, 0, 0)
        self.summary = NoteLabel("", parent=self.summary_box)
        self.summary.setObjectName("new_item_summary")
        summary_layout.addWidget(self.summary)
        settled, review, blocked, edited = "OK", tinted("amber"), "Blocked", "Edited"
        self.summary_box.setToolTip(
            f"{settled} settled, {review} wants a decision or an in-game check, "
            f"{blocked} blocks the plan, {edited} differs from the template."
        )
        self.summary_box.setVisible(False)

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(8, 8, 8, 8)
        body_layout.setSpacing(0)
        body_layout.addWidget(self.steps)
        body_layout.addWidget(self.pages, 1)
        footer = QHBoxLayout()
        footer.setContentsMargins(8, 6, 8, 2)
        self.back_button = QPushButton("Back")
        self.back_button.clicked.connect(lambda: self._step_by(-1))
        self.continue_button = QPushButton("Continue")
        self.continue_button.clicked.connect(lambda: self._step_by(+1))
        self.next_button = self.continue_button  # compatibility alias
        footer.addWidget(self.back_button)
        self.step_hint = QLabel("")
        self.step_hint.setObjectName("new_item_step_counter")
        self.step_hint.setAlignment(Qt.AlignCenter)
        footer.addWidget(self.step_hint, 1)
        footer.addWidget(self.continue_button)
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
        self.perks_panel.effects_workspace.staged_changed.connect(self._effect_staged_changed)
        # The stats tables are deliberately not wired here: every edit on that step
        # invalidates the plan, which refreshes the rail once, after the draft changed.
        # A table's itemChanged fires once per cell it is given, so listening to it ran
        # the summary, and two full validations, once per cell of every rebuild.
        self._show_step(0)
        self.template_panel._refresh_matches()
        self.placement_panel._refresh_stores()

    # ------------------------------------------------------------------ steps

    def _show_step(self, row: int) -> None:
        if self._syncing_step or not 0 <= int(row) < self.pages.count():
            return
        row = int(row)
        previous = int(self._current_step)
        if self._panels_built and previous == 4 and row != 4 and self.perks_panel.has_staged_effect_changes():
            action = str(self._effect_dirty_prompt() or "stay").casefold()
            if action == "apply":
                if not self.perks_panel.apply_staged_effect():
                    action = "stay"
            elif action == "discard":
                self.perks_panel.discard_staged_effect()
            if action not in {"apply", "discard"}:
                self._syncing_step = True
                try:
                    self.steps.setCurrentRow(previous)
                finally:
                    self._syncing_step = False
                self._refresh_summary()
                return
        # the template list takes a row once the reader settles on it; leaving the step
        # is settling on it, and the steps after read the template
        if self._panels_built:
            self.template_panel.apply_pending_pick()
        self._current_step = row
        if row == 0:
            self.template_panel.mount_preview(self.model_panel.preview)
        elif row == 2:
            self.model_panel.mount_preview()
        self.pages.setCurrentIndex(row)
        self.back_button.setEnabled(row > 0)
        self.continue_button.setEnabled(
            row < self.pages.count() - 1
            and not (row == 4 and self.perks_panel.has_staged_effect_changes())
        )
        self.step_hint.setText(f"Step {row + 1} of {self.pages.count()}")
        self._refresh_summary()

    def _prompt_for_staged_effect(self) -> str:
        prompt = QMessageBox(self)
        prompt.setIcon(QMessageBox.Icon.Warning)
        prompt.setWindowTitle("Apply placement changes?")
        prompt.setText("The Effects workspace has placement or look changes that have not been applied.")
        apply_button = prompt.addButton("Apply", QMessageBox.ButtonRole.AcceptRole)
        discard_button = prompt.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        stay_button = prompt.addButton("Stay", QMessageBox.ButtonRole.RejectRole)
        prompt.setDefaultButton(apply_button)
        prompt.exec()
        clicked = prompt.clickedButton()
        if clicked is apply_button:
            return "apply"
        if clicked is discard_button:
            return "discard"
        if clicked is stay_button:
            return "stay"
        return "stay"

    def _effect_staged_changed(self, dirty: object) -> None:
        staged_dirty = bool(dirty)
        if staged_dirty == self._effect_staged_dirty:
            return
        self._effect_staged_dirty = staged_dirty
        if self._current_step == 4:
            self.continue_button.setEnabled(not staged_dirty)
        self._refresh_summary()

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
        issues = None
        if self._panels_built and not self._refreshing_checks:
            self._refreshing_checks = True
            try:
                issues = self.identity_panel.refresh_issues()
            finally:
                self._refreshing_checks = False
        if issues is None:
            issues = controller.validate() if controller.ready else ()
        draft = controller.draft
        lines = []
        template = controller.template_name()
        lines.append(note(f"Template: {template}", OK) if template else note("Template: choose one", WARN))
        english = (draft.display_names or {}).get("eng", "")
        if draft.internal_name:
            lines.append(note(f"Name: {draft.internal_name} ({english})", OK) if english else note(f"Name: {draft.internal_name}, no English display name yet", WARN))
        else:
            lines.append(note("Name: not set", WARN))
        blocked = [issue for issue in issues if issue.is_error]
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
        effect_tone = WARN if self.perks_panel.has_staged_effect_changes() else EDIT if effect_changed else OK
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

        name_context = f"Name: {draft.internal_name or 'not set'}"
        if blocked:
            name_context += f"; {len(blocked)} issue(s) block the plan"
        if imported is not None and controller.model_result is None:
            model_context = f"Model: {imported.label}; placement not applied"
        elif imported is not None or controller.model_result is not None:
            model_context = f"Model: {imported.label if imported is not None else 'imported'}; placed"
        else:
            model_context = "Model: template"
        distribution_context = (
            f"Distribution: {draft.store_name}"
            if draft.placement_kind.value != "none" and draft.store_name
            else "Distribution: not sold anywhere"
        )
        output_context = (
            f"Output: plan ready for item {controller.plan.spec.item_key}"
            if controller.plan is not None
            else "Output: plan not built"
        )
        step_contexts = (
            f"Template: {template or 'choose one'}",
            name_context,
            model_context,
            stats_text,
            f"{perks_text}; {effect_text}"
            + ("; staged placement must be applied or discarded" if self.perks_panel.has_staged_effect_changes() else ""),
            distribution_context,
            output_context,
        )
        step_states = (
            WorkflowStepState.COMPLETED if template else WorkflowStepState.BLOCKED,
            WorkflowStepState.BLOCKED
            if blocked
            else WorkflowStepState.COMPLETED
            if draft.internal_name and english
            else WorkflowStepState.PENDING,
            WorkflowStepState.PENDING
            if imported is not None and controller.model_result is None
            else WorkflowStepState.COMPLETED,
            WorkflowStepState.COMPLETED,
            WorkflowStepState.PENDING
            if self.perks_panel.has_staged_effect_changes()
            else WorkflowStepState.COMPLETED,
            WorkflowStepState.COMPLETED
            if draft.placement_kind.value != "none" and draft.store_name
            else WorkflowStepState.PENDING,
            WorkflowStepState.COMPLETED if controller.plan is not None else WorkflowStepState.PENDING,
        )
        for index, context in enumerate(step_contexts):
            item = self.steps.item(index)
            if item is None:
                continue
            item.setState(step_states[index])
            item.setToolTip(context)
            item.setAccessibleText(f"Step {index + 1}, {item.text()}. {context}")

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

    # ------------------------------------------------------------------ imported-model part editing

    def _activate_model_part_editor(self) -> bool:
        window = self._window
        container = getattr(window, "mesh_editor_tab", None)
        activate = getattr(window, "_activate_tool_widget", None)
        if container is None or not callable(activate):
            self.model_panel.set_part_editor_state(False, "Mesh Editor is not available.")
            return False
        activate(container)
        return True

    def _open_model_part_editor(self) -> None:
        source = self.controller.model_import
        if source is None:
            self.model_panel.set_part_editor_state(False, "Import a model before opening Mesh Editor.")
            return
        if self.controller.busy:
            self.model_panel.set_part_editor_state(
                bool(self._model_part_editor_session_id),
                "Another background task is still running. Wait for it to finish before starting this action.",
            )
            return
        if (
            source is self._model_part_editor_source
            and self._model_part_editor_controller is not None
            and str(getattr(self._model_part_editor_controller, "active_session_id", "") or "")
            == self._model_part_editor_session_id
        ):
            self._activate_model_part_editor()
            return
        window = self._window
        container = getattr(window, "mesh_editor_tab", None)
        ensure = getattr(container, "ensure_widget", None)
        try:
            editor = ensure() if callable(ensure) else container
        except (RuntimeError, TypeError) as exc:
            self.model_panel.set_part_editor_state(False, f"Mesh Editor could not open this imported model: {exc}")
            return
        if editor is None:
            self.model_panel.set_part_editor_state(False, "Mesh Editor is not available.")
            return
        active_controller = getattr(editor, "standalone_controller", None)
        if active_controller is not None and bool(getattr(active_controller, "active_session_id", "")):
            self.model_panel.set_part_editor_state(
                False,
                "Mesh Editor already has an active mesh. Finish or close it before opening this imported model.",
            )
            return
        mesh = getattr(getattr(source, "scene", None), "mesh", None)
        session_id = f"new-item-model:{id(source):x}:{int(getattr(source, 'mesh_generation', 0) or 0)}"
        try:
            view = editor.open_mesh_session(
                mesh,
                session_id=session_id,
                mode="edit",
                initial_element_type="face",
            )
            mesh_controller = editor.standalone_controller
        except (AttributeError, RuntimeError, TypeError, ValueError) as exc:
            self.model_panel.set_part_editor_state(False, f"Mesh Editor could not open this imported model: {exc}")
            return
        self._model_part_editor_source = source
        self._model_part_editor_widget = editor
        self._model_part_editor_controller = mesh_controller
        self._model_part_editor_session_id = str(getattr(view, "session_id", "") or session_id)
        self.model_panel.set_part_editor_state(
            True,
            "Brush or select faces, then choose Create Part from Selection. Return here to use the edited parts.",
        )
        self._activate_model_part_editor()

    def _use_model_part_editor_changes(self) -> None:
        source = self.controller.model_import
        editor = self._model_part_editor_widget
        mesh_controller = self._model_part_editor_controller
        session_id = self._model_part_editor_session_id
        if source is None or source is not self._model_part_editor_source or mesh_controller is None or not session_id:
            self.model_panel.set_part_editor_state(False, "Open this imported model in Mesh Editor first.")
            return
        if str(getattr(mesh_controller, "active_session_id", "") or "") != session_id:
            self._clear_model_part_editor_link()
            self.model_panel.set_part_editor_state(False, "Open this imported model in Mesh Editor first.")
            return
        active_worker = getattr(editor, "_standalone_action_worker_active", None)
        if (
            (callable(active_worker) and active_worker())
            or getattr(editor, "standalone_pending_dotnet_topology_request", None) is not None
        ):
            self.model_panel.set_part_editor_state(True, "Wait for the current Mesh Editor task to finish.")
            return
        started = self.controller.start_model_part_edit_apply(
            source,
            mesh_controller,
            expected_session_id=session_id,
            wait_for_updates=getattr(editor, "_wait_for_dotnet_export_updates", None),
        )
        if started and self.controller.busy:
            self.model_panel.set_part_editor_state(True, "Preparing the Mesh Editor changes...")

    def _model_part_edit_finished(self, source: object) -> None:
        if source is not self._model_part_editor_source:
            return
        mesh = getattr(getattr(source, "scene", None), "mesh", None)
        part_count = len(tuple(getattr(mesh, "submeshes", ()) or ()))
        self.model_panel.set_part_editor_state(
            True,
            f"Using Mesh Editor revision with {part_count} part(s). Apply the placement again before building the item.",
        )

    def _model_part_edit_failed(self, message: str) -> None:
        if self._model_part_editor_session_id:
            self.model_panel.set_part_editor_state(True, str(message))

    def _model_part_editor_source_changed(self, source: object) -> None:
        if self._model_part_editor_source is not None and source is not self._model_part_editor_source:
            self._clear_model_part_editor_link()
            self.model_panel.set_part_editor_state(False)

    def _clear_model_part_editor_link(self) -> None:
        self._model_part_editor_source = None
        self._model_part_editor_widget = None
        self._model_part_editor_controller = None
        self._model_part_editor_session_id = ""

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
