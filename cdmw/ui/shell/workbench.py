"""Explicit shell ownership for the workbench."""

from __future__ import annotations

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
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin


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
    MeshEditorShellBridgeMixin,
    QMainWindow,
):
    @property
    def shell(self) -> WorkbenchWindow:
        return self
