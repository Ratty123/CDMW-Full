from __future__ import annotations

from pathlib import Path
from typing import Optional

from PySide6.QtCore import QSettings, Qt, Signal
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

try:  # pragma: no cover - import guard keeps source tests light.
    from cdmw.models import ArchiveEntry
except Exception:  # pragma: no cover
    ArchiveEntry = object  # type: ignore[assignment]

try:  # pragma: no cover
    from cdmw.modding.scene_importer import SceneImportResult
except Exception:  # pragma: no cover
    SceneImportResult = object  # type: ignore[assignment]


from cdmw.ui.mesh_editor.session import MeshEditorSessionRequest


class MeshEditorTab(QWidget):
    """Main mesh replacement/editing workspace host.

    The full Mesh Replacement Builder is mounted here for active sessions so the
    D3D11 preview, tabs, build preflight, and archive safety gates stay shared.
    """

    status_message_requested = Signal(str, bool)
    modify_original_requested = Signal(object)
    import_replacement_requested = Signal(object)
    import_preview_requested = Signal(object)
    in_game_swap_requested = Signal(object)
    open_archive_target_requested = Signal(object)

    def __init__(
        self,
        *,
        settings: QSettings,
        theme_key: str = "graphite",
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.theme_key = str(theme_key or "graphite")
        self.current_request: Optional[MeshEditorSessionRequest] = None
        self.current_archive_selection: Optional[ArchiveEntry] = None

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.workspace_stack = QStackedWidget(self)
        self.workspace_stack.setObjectName("MeshEditorWorkspaceStack")
        self.empty_state = self._build_empty_state()
        self.embedded_builder_host = QFrame(self)
        self.embedded_builder_host.setObjectName("MeshEditorEmbeddedBuilderHost")
        self.embedded_builder_host.setFrameShape(QFrame.Shape.NoFrame)
        self.embedded_builder_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.embedded_builder_host_layout = QVBoxLayout(self.embedded_builder_host)
        self.embedded_builder_host_layout.setContentsMargins(0, 0, 0, 0)
        self.embedded_builder_host_layout.setSpacing(0)

        self.workspace_stack.addWidget(self.empty_state)
        self.workspace_stack.addWidget(self.embedded_builder_host)
        root.addWidget(self.workspace_stack, 1)

        self._sync_state()

    def _build_empty_state(self) -> QWidget:
        page = QFrame(self)
        page.setObjectName("MeshEditorEmptyState")
        layout = QVBoxLayout(page)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        header = QFrame(page)
        header.setObjectName("MeshEditorEmptyHeader")
        header_layout = QGridLayout(header)
        header_layout.setContentsMargins(8, 6, 8, 6)
        header_layout.setHorizontalSpacing(8)
        header_layout.setVerticalSpacing(3)

        title = QLabel("Mesh Editor")
        title.setObjectName("SectionTitle")
        self.target_label = QLabel("Target: none")
        self.target_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.target_label.setWordWrap(True)
        self.session_label = QLabel("Mode: no active session")
        self.session_label.setObjectName("HintLabel")
        self.session_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        self.open_archive_button = QPushButton("Show Target In Archive")
        self.open_archive_button.setObjectName("MeshEditorShowTargetArchiveButton")
        self.open_archive_button.clicked.connect(self._emit_open_archive_target)

        header_layout.addWidget(title, 0, 0)
        header_layout.addWidget(self.target_label, 1, 0)
        header_layout.addWidget(self.session_label, 2, 0)
        header_layout.addWidget(self.open_archive_button, 0, 1, 3, 1)
        header_layout.setColumnStretch(0, 1)
        layout.addWidget(header)

        self.empty_status_label = QLabel("Select a supported archive mesh, then choose a workflow.")
        self.empty_status_label.setObjectName("MeshEditorEmptyStatus")
        self.empty_status_label.setWordWrap(True)
        layout.addWidget(self.empty_status_label)

        workflow_row = QHBoxLayout()
        workflow_row.setSpacing(8)
        self.modify_original_button = QPushButton("Modify Original")
        self.modify_original_button.setObjectName("MeshEditorModifyOriginalButton")
        self.import_replacement_button = QPushButton("Import Replacement")
        self.import_replacement_button.setObjectName("MeshEditorImportReplacementButton")
        self.import_preview_button = QPushButton("Import Preview")
        self.import_preview_button.setObjectName("MeshEditorImportPreviewButton")
        self.in_game_swap_button = QPushButton("In-Game Swap")
        self.in_game_swap_button.setObjectName("MeshEditorInGameSwapButton")
        self.modify_original_button.setToolTip("Create or reopen an editable clone workspace for the selected archive mesh.")
        self.import_replacement_button.setToolTip("Import OBJ, DAE, glTF, GLB, PAC, PAM, or PAMLOD as the replacement source.")
        self.import_preview_button.setToolTip("Run the same import path as preview-only, without writing output.")
        self.in_game_swap_button.setToolTip("Use another loaded archive mesh as the source for this target.")
        for button in (
            self.modify_original_button,
            self.import_replacement_button,
            self.import_preview_button,
            self.in_game_swap_button,
        ):
            button.setMinimumHeight(30)
            workflow_row.addWidget(button)
        workflow_row.addStretch(1)
        layout.addLayout(workflow_row)
        layout.addStretch(1)

        self.modify_original_button.clicked.connect(lambda _checked=False: self._emit_target(self.modify_original_requested))
        self.import_replacement_button.clicked.connect(lambda _checked=False: self._emit_target(self.import_replacement_requested))
        self.import_preview_button.clicked.connect(lambda _checked=False: self._emit_target(self.import_preview_requested))
        self.in_game_swap_button.clicked.connect(lambda _checked=False: self._emit_target(self.in_game_swap_requested))
        return page

    def builder_host(self) -> QWidget:
        return self.embedded_builder_host

    def active_builder(self) -> Optional[QWidget]:
        item = self.embedded_builder_host_layout.itemAt(0)
        return item.widget() if item is not None else None

    def has_active_builder(self) -> bool:
        return self.active_builder() is not None

    def mount_embedded_builder(self, builder: QWidget) -> None:
        while self.embedded_builder_host_layout.count():
            item = self.embedded_builder_host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None and widget is not builder:
                widget.setParent(None)
                widget.deleteLater()
        self.embedded_builder_host_layout.addWidget(builder)
        self.workspace_stack.setCurrentWidget(self.embedded_builder_host)

    def show_empty_state(self, message: str = "") -> None:
        while self.embedded_builder_host_layout.count():
            item = self.embedded_builder_host_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.setParent(None)
        if message:
            self.empty_status_label.setText(message)
        self.workspace_stack.setCurrentWidget(self.empty_state)

    def _entry_path(self, entry: object) -> str:
        return str(getattr(entry, "path", "") or getattr(entry, "name", "") or "").strip()

    def _entry_label(self, entry: object) -> str:
        return str(getattr(entry, "basename", "") or Path(self._entry_path(entry)).name or self._entry_path(entry) or "mesh").strip()

    def set_archive_selection(self, entry: Optional[ArchiveEntry]) -> None:
        self.current_archive_selection = entry
        if self.has_active_builder():
            self._sync_state()
            return
        if (
            entry is not None
            and (
                self.current_request is None
                or (
                    self.current_request.source_path is None
                    and self.current_request.source_entry is None
                )
            )
        ):
            self.current_request = MeshEditorSessionRequest(target_entry=entry, mode="modify_original")
        self._sync_state()

    def open_session(self, request: MeshEditorSessionRequest) -> None:
        self.current_request = request
        self.current_archive_selection = request.target_entry
        self._sync_state()
        self.status_message_requested.emit(f"Mesh Editor loaded target: {self._entry_label(request.target_entry)}", False)

    def _current_target_entry(self) -> Optional[ArchiveEntry]:
        if self.current_request is not None:
            return self.current_request.target_entry
        return self.current_archive_selection

    def _sync_state(self) -> None:
        target = self._current_target_entry()
        has_target = target is not None
        mode = str(getattr(self.current_request, "mode", "") or "modify_original")
        path_text = self._entry_path(target) if target is not None else ""
        label_text = self._entry_label(target) if target is not None else "none"
        self.target_label.setText(f"Target: {path_text or label_text}")
        self.session_label.setText(f"Mode: {mode.replace('_', ' ')}" if has_target else "Mode: no active session")
        self.empty_status_label.setText(
            "Ready: choose Modify Original, Import Replacement, Import Preview, or In-Game Swap. "
            "The full Mesh Replacement Builder opens here; archive writes still require explicit build/export confirmation."
            if has_target
            else "No mesh target loaded. Select a .pac, .pam, or .pamlod in Archive Browser, then Open in Mesh Editor."
        )
        for button in (
            self.open_archive_button,
            self.modify_original_button,
            self.import_replacement_button,
            self.import_preview_button,
            self.in_game_swap_button,
        ):
            button.setEnabled(has_target)

    def _emit_target(self, signal: Signal) -> None:
        target = self._current_target_entry()
        if target is None:
            self.status_message_requested.emit("Select a supported archive mesh first.", True)
            return
        signal.emit(target)

    def _emit_open_archive_target(self) -> None:
        target = self._current_target_entry()
        if target is None:
            return
        self.open_archive_target_requested.emit(target)
