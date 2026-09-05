from __future__ import annotations

from importlib import import_module as _import_module
from pathlib import Path
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QSettings, Signal, Qt
from PySide6.QtWidgets import (
    QFrame,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from cdmw.ui.mesh_editor.action_bar import MeshEditorActionBar
from cdmw.services.workspace_layout import workspace_paths
from cdmw.ui.mesh_editor.tab_support import (
    STANDALONE_NATIVE_TOOL_STATE as _STANDALONE_NATIVE_TOOL_STATE,
)
from cdmw.ui.mesh_editor.tab_lifetime import install_mesh_editor_destroyed_worker_guard

_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)

from cdmw.ui.mesh_editor.tab_shell import MeshEditorTabShellMixin
from cdmw.ui.mesh_editor.tab_native_preview import MeshEditorNativePreviewMixin
from cdmw.ui.mesh_editor.tab_packages import MeshEditorPackageMixin
from cdmw.ui.mesh_editor.tab_rust_editor import MeshEditorRustEditorMixin
from cdmw.ui.mesh_editor.tab_dotnet_launch import MeshEditorDotNetLaunchMixin
from cdmw.ui.mesh_editor.tab_dotnet_protocol import MeshEditorDotNetProtocolMixin
from cdmw.ui.mesh_editor.tab_dotnet_commands import MeshEditorDotNetCommandMixin
from cdmw.ui.mesh_editor.tab_dotnet_process import MeshEditorDotNetProcessMixin
from cdmw.ui.mesh_editor.tab_reports import MeshEditorReportsMixin
from cdmw.ui.mesh_editor.tab_session_runtime import MeshEditorSessionMixin
from cdmw.ui.mesh_editor.tab_state import MeshEditorStateMixin
from cdmw.ui.mesh_editor.tab_ui_state import MeshEditorUiStateMixin
from cdmw.ui.mesh_editor.tab_interaction import MeshEditorInteractionMixin
from cdmw.ui.mesh_editor.tab_actions import MeshEditorActionsMixin
from cdmw.ui.mesh_editor.tab_output_policy import MeshEditorOutputPolicyMixin
from cdmw.ui.mesh_editor.character_context import MeshEditorCharacterContextMixin
from cdmw.ui.character_context_panel import CharacterContextPanel


_LAZY_EXPORT_GROUPS = (
    ("dataclasses", ("asdict", "is_dataclass", "replace")),
    ("pathlib", ("Path",)),
    ("types", ("SimpleNamespace",)),
    ("PySide6.QtCore", ("QPoint", "QProcess", "QThread", "Qt", "QTimer", "QUrl")),
    ("PySide6.QtGui", ("QDesktopServices", "QFont")),
    (
        "PySide6.QtWidgets",
        (
            "QApplication",
            "QFileDialog",
            "QGridLayout",
            "QHBoxLayout",
            "QLabel",
            "QMessageBox",
            "QProgressDialog",
            "QPushButton",
            "QTabWidget",
        ),
    ),
    ("cdmw.services.atomic_file_service", ("atomic_write_text",)),
    (
        "cdmw.domain.mesh",
        (
            "DEVELOPER_OVERRIDABLE_REBUILD_BLOCKERS",
            "MeshEditCommand",
            "MeshEditResult",
            "MeshEditSelection",
            "MeshEditSessionView",
        ),
    ),
    ("cdmw.models", ("ArchiveEntry", "ModelPreviewData", "ModelPreviewRenderSettings", "TextureEditorSourceBinding")),
    ("cdmw.services.mesh_workflow_service", ("ParsedMesh", "SceneImportResult")),
    ("cdmw.modding.mesh_native_availability", ("native_mesh_core_available",)),
    ("cdmw.services.mesh_dotnet_material_state", ("mesh_dotnet_material_input_signature", "mesh_dotnet_material_state_payload")),
    ("cdmw.services.mesh_service", ("MeshService",)),
    ("cdmw.ui.shell.settings_bridge", ("read_bool_setting",)),
    ("cdmw.ui.mesh_editor.actions", ("NATIVE_EDITOR_SESSION_COMMANDS", "mesh_editor_actions_by_key")),
    (
        "cdmw.ui.mesh_editor.controller",
        ("MeshEditorActionExecution", "MeshEditorController", "MeshEditorNativeUpdate", "apply_native_update_to_host"),
    ),
    ("cdmw.ui.mesh_editor.native_preview_payloads", ("mesh_pose_to_native_preview",)),
    (
        "cdmw.ui.mesh_editor.live_stroke_dispatcher",
        (
            "MeshLiveStrokeCoalesced",
            "MeshLiveStrokeDispatcher",
            "MeshLiveStrokeFailure",
            "MeshLiveStrokeOutcome",
        ),
    ),
    ("cdmw.ui.mesh_editor.dotnet_update_queue", ("DotNetRevisionUpdateQueue",)),
    (
        "cdmw.ui.mesh_editor.process_io",
        (
            "DOTNET_PROTOCOL_BUFFER_LIMIT",
            "DOTNET_PROTOCOL_EVENT_LIMIT",
            "DOTNET_PROTOCOL_LINE_LIMIT",
            "append_bounded_text",
            "stop_qprocess_async",
        ),
    ),
    ("cdmw.ui.mesh_editor.session", ("MeshEditorSessionRequest",)),
    ("cdmw.ui.mesh_editor.workspace", ("MeshEditorWorkspace",)),
    (
        "cdmw.workers.mesh_editor_workers",
        (
            "MeshEditCommandWorker",
            "MeshDirectOutputResult",
            "MeshDirectOutputWorker",
            "MeshEditablePackageExportWorker",
            "MeshEditablePackageImportWorker",
            "MeshDotNetExperimentPackageWorker",
            "MeshDotNetMaterialUpdateWorker",
            "MeshDotNetSceneFrameWorker",
            "MeshExportValidationWorker",
            "MeshArchiveMaterialContextWorker",
            "MeshArchiveSessionLoadResult",
            "MeshArchiveSessionLoadWorker",
            "MeshFileSessionLoadWorker",
            "MeshRebuildReportWorker",
            "MeshOverlayApplyWorker",
            "MeshOverlayRestoreWorker",
            "MeshReportWriteWorker",
            "MeshTextureSourceResolveWorker",
        ),
    ),
    ("cdmw.workers.mesh_free_edit_output_worker", ("MeshFreeEditOutputWorker",)),
    (
        "cdmw.ui.mesh_editor.tab_support",
        (
            "_json_safe_report_value",
            "_mesh_edit_result_with_metric",
            "_mesh_editor_tab_index",
            "_mesh_editor_texture_binding_target",
            "_native_update_has_payload",
            "_public_validation_severity",
            "_rebuild_report_json_payload",
            "_validation_report_json_payload",
        ),
    ),
)
_LAZY_EXPORTS = {
    name: (module_name, name)
    for module_name, names in _LAZY_EXPORT_GROUPS
    for name in names
}
_LAZY_EXPORTS.update({name: (name, None) for name in ("json", "os", "shutil", "sys", "time")})


def __getattr__(name: str) -> object:
    try:
        module_name, attribute_name = _LAZY_EXPORTS[name]
    except KeyError as exc:
        raise AttributeError(name) from exc
    module = _import_module(module_name)
    value = module if attribute_name is None else getattr(module, attribute_name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted((*globals(), *_LAZY_EXPORTS))


class MeshEditorTab(MeshEditorCharacterContextMixin, MeshEditorTabShellMixin, MeshEditorNativePreviewMixin, MeshEditorPackageMixin, MeshEditorRustEditorMixin, MeshEditorDotNetLaunchMixin, MeshEditorDotNetProtocolMixin, MeshEditorDotNetCommandMixin, MeshEditorDotNetProcessMixin, MeshEditorOutputPolicyMixin, MeshEditorReportsMixin, MeshEditorSessionMixin, MeshEditorUiStateMixin, MeshEditorStateMixin, MeshEditorInteractionMixin, MeshEditorActionsMixin, QWidget):
    """Direct resident mesh-authoring workspace host."""

    status_message_requested = Signal(str, bool)
    runtime_event_requested = Signal(str, dict)
    open_archive_session_requested = Signal(object)
    open_archive_target_requested = Signal(object)
    replace_from_archive_requested = Signal(object)
    mesh_action_requested = Signal(object)

    def __init__(
        self,
        *,
        settings: QSettings,
        theme_key: str = "graphite",
        get_archive_texture_entries_by_normalized_path: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        get_archive_texture_entries_by_basename: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        get_archive_sidecar_entries_by_texture_path: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        get_archive_sidecar_entries_by_texture_basename: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        ensure_archive_texture_indexes: Callable[[], bool] | None = None,
        get_archive_mutation_service: Callable[[], object | None] | None = None,
        get_archive_material_preview_model: Callable[[], object | None] | None = None,
        character_context_service: object | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        character_context_service = None
        self.settings = settings
        self.get_archive_mutation_service = get_archive_mutation_service
        self.get_archive_material_preview_model = get_archive_material_preview_model
        self.character_context_service = character_context_service
        self.character_context_repackage_generation = 0
        self.character_context_loaded_source_indices: tuple[int, ...] = ()
        self.character_context_next_source_indices: tuple[int, ...] = ()
        self.character_context_visibility_restore_pending = False
        self.character_context_resident_swap_pending = False
        settings_path = Path(str(settings.fileName() or "settings.ini")).expanduser()
        self.mesh_editor_draft_root = workspace_paths(settings_path.parent)[
            "modify_original_sessions_root"
        ]
        self.theme_key = str(theme_key or "graphite")
        self._initialize_runtime_state(
            get_archive_texture_entries_by_normalized_path=get_archive_texture_entries_by_normalized_path,
            get_archive_texture_entries_by_basename=get_archive_texture_entries_by_basename,
            get_archive_sidecar_entries_by_texture_path=get_archive_sidecar_entries_by_texture_path,
            get_archive_sidecar_entries_by_texture_basename=get_archive_sidecar_entries_by_texture_basename,
            ensure_archive_texture_indexes=ensure_archive_texture_indexes,
        )
        self._initialize_rust_editor_runtime_state()

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.action_bar = MeshEditorActionBar(parent=self)
        self.action_bar.action_requested.connect(self._handle_action_requested)
        root.addWidget(self.action_bar)

        self.character_context_toolbar = QFrame(self)
        self.character_context_toolbar.setObjectName("MeshEditorCharacterContextToolbar")
        character_context_toolbar_layout = QHBoxLayout(self.character_context_toolbar)
        character_context_toolbar_layout.setContentsMargins(8, 3, 8, 3)
        character_context_toolbar_layout.addStretch(1)
        self.character_context_toggle_button = QPushButton("Character Context")
        self.character_context_toggle_button.setCheckable(True)
        self.character_context_toggle_button.setToolTip(
            "Show preview-only authored face pieces and optional compatible hair/body context."
        )
        self.character_context_toggle_button.setVisible(False)
        self.character_context_toggle_button.setEnabled(False)
        character_context_toolbar_layout.addWidget(self.character_context_toggle_button)
        self.character_context_toolbar.setVisible(character_context_service is not None)
        root.addWidget(self.character_context_toolbar)

        self.draft_banner = QFrame(self)
        self.draft_banner.setObjectName("MeshEditorDraftRecoveryBanner")
        draft_layout = QHBoxLayout(self.draft_banner)
        draft_layout.setContentsMargins(8, 5, 8, 5)
        self.draft_banner_label = QLabel("", self.draft_banner)
        self.draft_banner_label.setWordWrap(True)
        draft_layout.addWidget(self.draft_banner_label, 1)
        self.draft_resume_button = QPushButton("Resume", self.draft_banner)
        self.draft_start_fresh_button = QPushButton("Start Fresh", self.draft_banner)
        draft_layout.addWidget(self.draft_resume_button)
        draft_layout.addWidget(self.draft_start_fresh_button)
        self.draft_resume_button.clicked.connect(self._resume_latest_archive_draft)
        self.draft_start_fresh_button.clicked.connect(self._dismiss_archive_draft_banner)
        self.draft_banner.setVisible(False)
        self.mesh_editor_matching_drafts: tuple[object, ...] = ()
        root.addWidget(self.draft_banner)

        self.empty_state = self._build_empty_state()
        root.addWidget(self.empty_state)

        self.workspace_stack = QStackedWidget(self)
        self.workspace_stack.setObjectName("MeshEditorWorkspaceStack")
        self.standalone_workspace = self._build_standalone_workspace()
        self.embedded_builder_host = QFrame(self)
        self.embedded_builder_host.setObjectName("MeshEditorEmbeddedBuilderHost")
        self.embedded_builder_host.setFrameShape(QFrame.Shape.NoFrame)
        self.embedded_builder_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.embedded_builder_host_layout = QVBoxLayout(self.embedded_builder_host)
        self.embedded_builder_host_layout.setContentsMargins(0, 0, 0, 0)
        self.embedded_builder_host_layout.setSpacing(0)

        self.workspace_stack.addWidget(self.standalone_workspace)
        self.workspace_stack.addWidget(self.embedded_builder_host)
        self.workspace_stack.setCurrentWidget(self.standalone_workspace)
        self.character_context_splitter = QSplitter(Qt.Orientation.Horizontal, self)
        self.character_context_splitter.setChildrenCollapsible(True)
        self.character_context_splitter.setHandleWidth(8)
        self.character_context_splitter.addWidget(self.workspace_stack)
        self.character_context_panel = (
            CharacterContextPanel(
                character_context_service,
                surface_label="Mesh Editor",
                parent=self.character_context_splitter,
            )
            if character_context_service is not None
            else QFrame(self.character_context_splitter)
        )
        self.character_context_panel.setVisible(False)
        self.character_context_splitter.addWidget(self.character_context_panel)
        self.character_context_splitter.setCollapsible(0, False)
        self.character_context_splitter.setCollapsible(1, True)
        self.character_context_splitter.setStretchFactor(0, 1)
        self.character_context_splitter.setStretchFactor(1, 0)
        self.character_context_splitter.setSizes([920, 0])
        root.addWidget(self.character_context_splitter, 1)
        self.character_context_toggle_button.toggled.connect(
            self._toggle_mesh_editor_character_context
        )
        if character_context_service is not None:
            self.character_context_panel.panel_hidden.connect(
                lambda: self.character_context_toggle_button.setChecked(False)
            )
            character_context_service.selection_changed.connect(
                self._handle_mesh_character_context_selection
            )
            character_context_service.package_started.connect(
                self._handle_mesh_character_context_package_started
            )
            character_context_service.package_ready.connect(
                self._handle_mesh_character_context_package_ready
            )
            character_context_service.package_failed.connect(
                self._handle_mesh_character_context_package_failed
            )

        self._sync_state()
        install_mesh_editor_destroyed_worker_guard(self)


__all__ = sorted(name for name in (*globals(), *_LAZY_EXPORTS) if not name.startswith("_"))
