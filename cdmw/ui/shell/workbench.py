"""Explicit shell ownership for the workbench."""

from __future__ import annotations

import importlib

from PySide6.QtWidgets import QMainWindow

from cdmw.ui.shell.about_controller import AboutControllerMixin
from cdmw.ui.shell.about_documentation import AboutDocumentationMixin
from cdmw.ui.shell.support_dialog import SupportDialogMixin
from cdmw.ui.shell.menus import ShellMenusMixin
from cdmw.ui.shell.root_layout import ShellRootLayoutMixin
from cdmw.ui.shell.signal_wiring import ShellSignalWiringMixin
from cdmw.ui.shell.startup_restore import ShellStartupRestoreMixin
from cdmw.ui.shell.tool_tabs import ShellToolTabsMixin
from cdmw.ui.shell.window_bootstrap_state import ShellWindowBootstrapStateMixin
from cdmw.ui.shell.window_runtime_state import ShellWindowRuntimeStateMixin
from cdmw.ui.shell.settings_persistence import SettingsPersistenceMixin
from cdmw.ui.shell.settings_autosave import SettingsAutosaveMixin
from cdmw.ui.shell.close_controller import CloseControllerMixin
from cdmw.ui.shell.responsiveness_controller import ResponsivenessControllerMixin
from cdmw.ui.shell.log_controller import LogControllerMixin
from cdmw.ui.shell.theme_controller import ThemeControllerMixin
from cdmw.ui.shell.language_controller import LanguageControllerMixin
from cdmw.ui.shell.startup_controller import StartupPromptMixin
from cdmw.ui.shell.path_controller import PathControllerMixin
from cdmw.ui.shell.utility_controller import UtilityControllerMixin
from cdmw.ui.shell.workspace_controller import WorkspaceControllerMixin
from cdmw.ui.shell.profile_controller import ProfileControllerMixin
from cdmw.ui.shell.navigation_controller import NavigationControllerMixin
from cdmw.ui.shell.dashboard_controller import DashboardControllerMixin
from cdmw.ui.shell.model_library_bridge import ModelLibraryShellBridgeMixin

# Heavy Mesh Editor bridges are loaded on first access and attached dynamically
# onto WorkbenchWindow (preserving every method on the real mixin class,
# including newly added methods, without pulling numpy/scene_importer/mesh
# services during app startup).
_LAZY_BRIDGE_SPECS: tuple[tuple[str, str, tuple[str, ...]], ...] = (
    (
        "cdmw.ui.mesh_editor.shell_bridge",
        "MeshEditorShellBridgeMixin",
        (
            "_export_current_archive_mesh",
            "_open_mesh_editor_for_entry",
            "_mesh_editor_session_request_key",
            "_reset_mesh_editor_d3d11_view_state_for_session",
            "_mesh_editor_entry_key",
            "_mesh_editor_active_builder",
            "_mesh_editor_active_builder_entry_key",
            "_mesh_editor_selected_backend_is_rust",
            "_mesh_editor_package_matches_archive_entry",
            "_mesh_editor_active_textured_package_for_entry",
            "_mesh_editor_retained_textured_package_for_entry",
            "_mesh_editor_active_set_package_for_contexts",
            "_defer_rust_mesh_editor_for_archive_textures",
            "_archive_preview_interim_for",
            "_disconnect_full_archive_preview_wait",
            "_connect_full_archive_preview_signals",
            "_handle_full_archive_preview_signal",
            "_wait_for_full_archive_preview",
            "_check_full_archive_preview_wait",
            "_start_preloaded_mesh_editor_session",
            "_discard_preloaded_session_result",
            "_handle_preloaded_mesh_editor_session_loaded",
            "_handle_preloaded_mesh_editor_session_aborted",
            "_cleanup_preloaded_mesh_editor_session_loader",
            "_cancel_preloaded_mesh_editor_session",
            "_take_preloaded_mesh_editor_session",
            "_finish_pending_rust_mesh_editor_texture_launch",
            "_refresh_active_rust_material_context_from_archive",
            "_relaunch_idle_rust_editor_for_active_session",
            "_prepare_mesh_editor_archive_launch",
            "_mesh_documents",
            "_show_document_editing",
            "_open_in_other_document",
            "_mesh_editor_open_blocked",
            "_take_pending_hidden_parts_for_open",
            "_launch_archive_mesh_editor_for_entry",
            "_continue_archive_mesh_editor_launch",
            "_show_browse_view_first",
            "_take_early_browse_binding",
            "_drop_early_browse_binding",
            "_launch_archive_mesh_editor_after_view",
            "_open_archive_mesh_editor_with_dependencies",
            "_browse_shows_item_set",
            "_browse_edit_binding",
            "_watch_documents_for_browse_edit",
            "_browse_edit_moved_to_tab",
            "_open_current_archive_mesh_editor",
            "_mesh_editor_modify_original_requested",
            "_mesh_editor_import_replacement_requested",
            "_mesh_editor_import_preview_requested",
            "_mesh_editor_rebuilt_asset_setup",
            "_mesh_editor_preview_rebuilt_asset_requested",
            "_mesh_editor_package_rebuilt_asset_requested",
            "_mesh_editor_in_game_swap_requested",
            "_mesh_editor_replace_from_archive_requested",
            "_mesh_editor_show_archive_target_requested",
            "_mesh_editor_route_active_builder_action",
            "_mesh_editor_action_requested",
            "_modify_current_archive_original_mesh",
        ),
    ),
    (
        "cdmw.ui.mesh_editor.saved_work_bridge",
        "MeshEditorSavedWorkBridgeMixin",
        (
            "_mesh_saved_work_root",
            "_mesh_saved_work_resolver",
            "_mesh_saved_work_active_draft",
            "_open_mesh_editor_saved_work",
            "_continue_mesh_saved_work",
            "_continue_item_package_saved_work",
            "_open_item_package_launch",
            "_mesh_saved_work_dependencies",
            "_reveal_mesh_saved_work_source",
            "_cancel_mesh_saved_work_source_wait",
            "_poll_mesh_saved_work_source",
            "_prepare_mesh_saved_work_launch",
            "_open_mesh_saved_work_launch",
        ),
    ),
)

_LAZY_BRIDGE_ATTRS: dict[str, tuple[str, str]] = {
    attr: (module_name, class_name)
    for module_name, class_name, attrs in _LAZY_BRIDGE_SPECS
    for attr in attrs
}

_LAZY_BRIDGE_PREFIXES: tuple[tuple[str, str, str], ...] = (
    ("_mesh_saved_work", "cdmw.ui.mesh_editor.saved_work_bridge", "MeshEditorSavedWorkBridgeMixin"),
    ("_open_mesh_editor_saved_work", "cdmw.ui.mesh_editor.saved_work_bridge", "MeshEditorSavedWorkBridgeMixin"),
    ("_continue_mesh_saved_work", "cdmw.ui.mesh_editor.saved_work_bridge", "MeshEditorSavedWorkBridgeMixin"),
    ("_mesh_editor_", "cdmw.ui.mesh_editor.shell_bridge", "MeshEditorShellBridgeMixin"),
    ("_open_mesh_editor", "cdmw.ui.mesh_editor.shell_bridge", "MeshEditorShellBridgeMixin"),
    ("_launch_archive_mesh_editor", "cdmw.ui.mesh_editor.shell_bridge", "MeshEditorShellBridgeMixin"),
    ("_prepare_mesh_editor", "cdmw.ui.mesh_editor.shell_bridge", "MeshEditorShellBridgeMixin"),
    ("_browse_edit", "cdmw.ui.mesh_editor.shell_bridge", "MeshEditorShellBridgeMixin"),
)

_ATTACHED_LAZY_BRIDGES: set[tuple[str, str]] = set()


def _attach_lazy_bridge(target_cls: type, module_name: str, class_name: str) -> None:
    key = (module_name, class_name)
    if key in _ATTACHED_LAZY_BRIDGES:
        return
    mixin_cls = getattr(importlib.import_module(module_name), class_name)
    for base in mixin_cls.__mro__:
        if not base.__module__.startswith("cdmw."):
            continue
        for attr_name, raw_value in base.__dict__.items():
            if attr_name.startswith("__") and attr_name.endswith("__"):
                continue
            if attr_name not in target_cls.__dict__:
                setattr(target_cls, attr_name, raw_value)
    _ATTACHED_LAZY_BRIDGES.add(key)


class WorkbenchWindow(
    AboutControllerMixin,
    AboutDocumentationMixin,
    SupportDialogMixin,
    ShellMenusMixin,
    ShellRootLayoutMixin,
    ShellSignalWiringMixin,
    ShellStartupRestoreMixin,
    ShellToolTabsMixin,
    ShellWindowBootstrapStateMixin,
    ShellWindowRuntimeStateMixin,
    SettingsPersistenceMixin,
    SettingsAutosaveMixin,
    CloseControllerMixin,
    ResponsivenessControllerMixin,
    LogControllerMixin,
    ThemeControllerMixin,
    LanguageControllerMixin,
    StartupPromptMixin,
    PathControllerMixin,
    UtilityControllerMixin,
    WorkspaceControllerMixin,
    ProfileControllerMixin,
    NavigationControllerMixin,
    DashboardControllerMixin,
    ModelLibraryShellBridgeMixin,
    QMainWindow,
):
    def __getattr__(self, name: str):
        target = _LAZY_BRIDGE_ATTRS.get(name)
        if target is None:
            for prefix, module_name, class_name in _LAZY_BRIDGE_PREFIXES:
                if name.startswith(prefix):
                    target = (module_name, class_name)
                    break
        if target is None:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        module_name, class_name = target
        _attach_lazy_bridge(WorkbenchWindow, module_name, class_name)
        if name not in WorkbenchWindow.__dict__:
            raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")
        return getattr(self, name)

    @property
    def shell(self) -> WorkbenchWindow:
        return self
