"""New Item Studio: the tab that composes the six panels around one controller.

The tab is thin on purpose. It reads the archive list off the shell window, hands it
to the controller for the one-time snapshot, mounts the panels once that snapshot is
ready, and forwards two requests it cannot fulfil itself: importing a model (the shell
owns Import Mesh) and installing (the shell owns the mutation service and the
confirmation). It never touches the archives.
"""

from __future__ import annotations

from typing import Callable, Iterable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QLabel,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import ArchiveEntry
from cdmw.services.new_item_service import NewItemService
from cdmw.ui.new_item.controller import NewItemStudioController
from cdmw.ui.new_item.panels_identity import IdentityPanel
from cdmw.ui.new_item.panels_model import ModelPanel
from cdmw.ui.new_item.panels_output import OutputPanel
from cdmw.ui.new_item.panels_placement import PlacementPanel
from cdmw.ui.new_item.panels_stats import StatsPanel
from cdmw.ui.new_item.panels_template import TemplatePanel


class NewItemStudioTab(QWidget):
    """Clone an equipment item into a brand-new one: identity, model, icon, stats, shop, output."""

    status_message_requested = Signal(str, bool)

    def __init__(
        self,
        parent: Optional[QWidget] = None,
        *,
        window: object = None,
        service: Optional[NewItemService] = None,
        controller: Optional[NewItemStudioController] = None,
        get_archive_entries: Optional[Callable[[], Iterable[ArchiveEntry]]] = None,
    ) -> None:
        super().__init__(parent)
        self._window = window
        self._get_entries = get_archive_entries or (lambda: getattr(window, "archive_entries", None) or ())
        self.controller = controller or NewItemStudioController(service=service, parent=self)
        self._pending_template: Optional[int] = None
        self._panels_built = False

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
        if not entries:
            self._status.setText("The archive list is empty. Scan the archives in the Archive Browser first, then come back.")
            return
        self._read_button.setEnabled(False)
        self._progress.setVisible(True)
        self._status.setText(f"Reading the tables from {len(entries):,} archive entries...")
        self.controller.log_message.connect(self._status.setText)
        if not self.controller.start_snapshot(entries):
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
        self.placement_panel = PlacementPanel(controller)
        self.output_panel = OutputPanel(controller)
        self.model_panel.import_requested.connect(self._start_model_import)
        self.output_panel.install_requested.connect(self._install)
        controller.template_changed.connect(lambda _key: self.identity_panel.refresh_issues())
        controller.model_changed.connect(lambda _result: self.identity_panel.refresh_issues())

        body = QWidget()
        body_layout = QVBoxLayout(body)
        body_layout.setContentsMargins(12, 12, 12, 12)
        body_layout.setSpacing(10)
        for panel in (self.template_panel, self.identity_panel, self.model_panel, self.stats_panel, self.placement_panel, self.output_panel):
            body_layout.addWidget(panel)
        body_layout.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(body)
        self._layout.addWidget(scroll, 1)
        self.template_panel._refresh_matches()
        self.placement_panel._refresh_stores()

    # ------------------------------------------------------------------ entry points

    def prefill_template(self, template_key: int) -> None:
        """Point the studio at a template (from the Item Finder or the Builder)."""

        if not self.controller.ready:
            self._pending_template = int(template_key)
            self.start_snapshot()
            return
        self.template_panel.prefill(int(template_key))

    def receive_imported_model(self, entry: Optional[ArchiveEntry], result: object) -> None:
        """Take a Builder result for the current template's mesh."""

        self.controller.set_imported_model(entry, result)
        if self._panels_built:
            self.identity_panel.refresh_issues()

    def _start_model_import(self) -> None:
        entries = self.controller.template_entries()
        if not entries:
            QMessageBox.information(self, "Import through the Builder", "Choose a template whose model files are in the archives first.")
            return
        starter = getattr(self._window, "start_new_item_model_import", None)
        if not callable(starter):
            QMessageBox.information(
                self, "Import through the Builder",
                "Import Mesh is not reachable from here in this window. Build the model through Archive Browser's Import Mesh, "
                "then use Build as new item... in the Builder.",
            )
            return
        starter(entries[0], self.receive_imported_model)

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
        self.controller.shutdown()

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt virtual
        self.shutdown()
        super().closeEvent(event)


__all__ = ["NewItemStudioTab"]
