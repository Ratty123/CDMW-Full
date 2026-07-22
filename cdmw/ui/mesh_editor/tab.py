from __future__ import annotations

from importlib import import_module as _import_module
from typing import Callable, Mapping, Optional, Sequence

from PySide6.QtCore import QSettings, Signal
from PySide6.QtWidgets import QFrame, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget

from cdmw.ui.mesh_editor.action_bar import MeshEditorActionBar

_STANDALONE_NATIVE_TOOL_STATE: dict[str, tuple[str, str, str]] = {
    "transform_move": ("move", "selection", "edit"),
    "brush_grab": ("grab", "selection", "sculpt"),
    "brush_smooth": ("smooth", "selection", "sculpt"),
    "brush_inflate": ("inflate", "selection", "sculpt"),
    "brush_pinch": ("pinch", "selection", "sculpt"),
}
_LEGACY_SCREEN_CAMERA_FIELDS = frozenset(
    {"camera_world", "yaw_degrees", "pitch_degrees", "distance", "vertical_fov_degrees", "pan"}
)

from cdmw.ui.mesh_editor.tab_shell import MeshEditorTabShellMixin
from cdmw.ui.mesh_editor.tab_native_preview import MeshEditorNativePreviewMixin
from cdmw.ui.mesh_editor.tab_packages import MeshEditorPackageMixin
from cdmw.ui.mesh_editor.tab_dotnet_launch import MeshEditorDotNetLaunchMixin
from cdmw.ui.mesh_editor.tab_dotnet_protocol import MeshEditorDotNetProtocolMixin
from cdmw.ui.mesh_editor.tab_dotnet_commands import MeshEditorDotNetCommandMixin
from cdmw.ui.mesh_editor.tab_dotnet_process import MeshEditorDotNetProcessMixin
from cdmw.ui.mesh_editor.tab_reports import MeshEditorReportsMixin
from cdmw.ui.mesh_editor.tab_session_runtime import MeshEditorSessionMixin
from cdmw.ui.mesh_editor.tab_state import MeshEditorStateMixin
from cdmw.ui.mesh_editor.tab_interaction import MeshEditorInteractionMixin
from cdmw.ui.mesh_editor.tab_actions import MeshEditorActionsMixin


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
    (
        "cdmw.services.mesh_dotnet_experiment",
        (
            "MeshDotNetExperimentPackage",
            "find_mesh_dotnet_experiment_editor",
            "mesh_dotnet_experiment_command",
            "mesh_dotnet_experiment_output_obj_path",
            "mesh_dotnet_helper_provenance_blockers",
            "mesh_dotnet_material_input_signature",
            "mesh_dotnet_material_state_payload",
            "mesh_dotnet_material_parity_warnings",
            "mesh_dotnet_renderer_blockers",
            "resolve_mesh_dotnet_experiment_editor",
            "write_mesh_dotnet_experiment_evaluation",
            "write_mesh_dotnet_launch_diagnostics",
            "write_mesh_dotnet_launch_manifest",
        ),
    ),
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
        ("MeshLiveStrokeDispatcher", "MeshLiveStrokeFailure", "MeshLiveStrokeOutcome"),
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
            "MeshEditablePackageExportWorker",
            "MeshEditablePackageImportWorker",
            "MeshDotNetExperimentOutputImportWorker",
            "MeshDotNetExperimentPackageWorker",
            "MeshDotNetMaterialUpdateWorker",
            "MeshDotNetSceneFrameWorker",
            "MeshExportValidationWorker",
            "MeshFileSessionLoadWorker",
            "MeshRebuildReportWorker",
            "MeshReportWriteWorker",
            "MeshTextureSourceResolveWorker",
        ),
    ),
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


class MeshEditorTab(MeshEditorTabShellMixin, MeshEditorNativePreviewMixin, MeshEditorPackageMixin, MeshEditorDotNetLaunchMixin, MeshEditorDotNetProtocolMixin, MeshEditorDotNetCommandMixin, MeshEditorDotNetProcessMixin, MeshEditorReportsMixin, MeshEditorSessionMixin, MeshEditorStateMixin, MeshEditorInteractionMixin, MeshEditorActionsMixin, QWidget):
    """Main mesh replacement/editing workspace host.

    The full Mesh Replacement Builder is mounted here for active sessions so the
    D3D11 preview, tabs, build preflight, and archive safety gates stay shared.
    """

    status_message_requested = Signal(str, bool)
    runtime_event_requested = Signal(str, dict)
    modify_original_requested = Signal(object)
    import_replacement_requested = Signal(object)
    import_preview_requested = Signal(object)
    preview_rebuilt_asset_requested = Signal(object, object)
    package_rebuilt_asset_requested = Signal(object, object)
    in_game_swap_requested = Signal(object)
    open_archive_target_requested = Signal(object)
    mesh_action_requested = Signal(object)
    open_texture_source_requested = Signal(str, object)

    def __init__(
        self,
        *,
        settings: QSettings,
        theme_key: str = "graphite",
        get_archive_texture_entries_by_normalized_path: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        get_archive_texture_entries_by_basename: Callable[[], Mapping[str, Sequence[ArchiveEntry]]] | None = None,
        parent: Optional[QWidget] = None,
    ) -> None:
        super().__init__(parent)
        self.settings = settings
        self.theme_key = str(theme_key or "graphite")
        self._initialize_runtime_state(
            get_archive_texture_entries_by_normalized_path=get_archive_texture_entries_by_normalized_path,
            get_archive_texture_entries_by_basename=get_archive_texture_entries_by_basename,
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        self.action_bar = MeshEditorActionBar(parent=self)
        self.action_bar.action_requested.connect(self._handle_action_requested)
        root.addWidget(self.action_bar)

        self.workspace_stack = QStackedWidget(self)
        self.workspace_stack.setObjectName("MeshEditorWorkspaceStack")
        self.empty_state = self._build_empty_state()
        self.standalone_workspace = self._build_standalone_workspace()
        self.embedded_builder_host = QFrame(self)
        self.embedded_builder_host.setObjectName("MeshEditorEmbeddedBuilderHost")
        self.embedded_builder_host.setFrameShape(QFrame.Shape.NoFrame)
        self.embedded_builder_host.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.embedded_builder_host_layout = QVBoxLayout(self.embedded_builder_host)
        self.embedded_builder_host_layout.setContentsMargins(0, 0, 0, 0)
        self.embedded_builder_host_layout.setSpacing(0)

        self.workspace_stack.addWidget(self.empty_state)
        self.workspace_stack.addWidget(self.standalone_workspace)
        self.workspace_stack.addWidget(self.embedded_builder_host)
        root.addWidget(self.workspace_stack, 1)

        self._sync_state()


__all__ = sorted(name for name in (*globals(), *_LAZY_EXPORTS) if not name.startswith("_"))
