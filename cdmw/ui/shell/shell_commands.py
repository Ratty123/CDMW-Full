"""The shell's commands: the Profile, Settings, Window, Help and About menus (P12 step 2).

Each menu entry is a view of one registry command, and so are the compact
rail's Settings and Report buttons, which reuse the same actions.
"""

from __future__ import annotations

from cdmw.ui.commands.adapters import bind_action
from cdmw.ui.commands.registry import Command, CommandRegistry

#: The shell context, as views refresh it.
SHELL = "shell"
BUSY_REASON = "Wait for the current task to finish."
DETACH_REASON = "This tool cannot be moved to a window of its own."
ATTACH_REASON = "This tool is not in a window of its own."
ATTACH_ALL_REASON = "No tool is in a window of its own."

#: Command id -> the shell action that shows it in the menus.
SHELL_ACTIONS = {
    "shell.export_profile": "export_profile_action",
    "shell.import_profile": "import_profile_action",
    "shell.settings": "open_settings_action",
    "shell.detach_tool": "detach_current_tab_action",
    "shell.attach_tool": "attach_current_tool_action",
    "shell.attach_all_tools": "attach_all_tools_action",
    "shell.documentation": "open_documentation_action",
    "shell.report_problem": "report_problem_action",
    "shell.export_diagnostics": "export_diagnostics_action",
    "shell.copy_problem_summary": "copy_problem_summary_action",
    "shell.open_crash_reports": "open_crash_reports_action",
    "shell.about": "open_about_action",
}


def shell_commands(shell) -> list[Command]:
    def busy() -> str:
        return BUSY_REASON if getattr(shell, "_shell_busy", False) else ""

    def window_state(index: int, reason: str):
        def check() -> str:
            state = getattr(shell, "_window_menu_state", (False, False, False))
            return "" if state[index] else reason
        return check

    def make(command_id: str, label: str, run, reason=busy) -> Command:
        return Command(command_id, label, SHELL, run, reason)

    return [
        make("shell.export_profile", "Export Profile...", lambda: shell.export_profile()),
        make("shell.import_profile", "Import Profile...", lambda: shell.import_profile()),
        make("shell.settings", "Settings", lambda: shell.show_settings()),
        make("shell.detach_tool", "Detach Current Tool", lambda: shell._detach_current_tool_tab(),
             window_state(0, DETACH_REASON)),
        make("shell.attach_tool", "Reattach Current Tool", lambda: shell._attach_current_tool_tab(),
             window_state(1, ATTACH_REASON)),
        make("shell.attach_all_tools", "Reattach All Tools", lambda: shell._attach_all_detached_tools(),
             window_state(2, ATTACH_ALL_REASON)),
        make("shell.documentation", "Documentation", lambda: shell.show_documentation_dialog()),
        # Reporting a problem stays possible while the app is busy, as before.
        make("shell.report_problem", "Report a Problem...", lambda: shell.show_problem_report_dialog(),
             lambda: ""),
        make("shell.export_diagnostics", "Export Diagnostics...", lambda: shell.export_diagnostic_bundle()),
        make("shell.copy_problem_summary", "Copy Latest Problem Summary",
             lambda: shell.copy_latest_problem_summary()),
        make("shell.open_crash_reports", "Open Crash Reports Folder", lambda: shell.open_crash_reports_folder()),
        make("shell.about", "About", lambda: shell.show_about_dialog()),
    ]


def install_shell_commands(shell) -> CommandRegistry:
    """Register the shell's commands in the application's registry and bind its menu actions.

    The application has one registry (``command_registry()``), owned by the
    application, so tools that register before the shell (Browse Archives builds
    first) and the shell share it. The window keeps a reference as
    ``command_registry``.
    """

    from PySide6.QtGui import QAction

    from cdmw.ui.commands.registry import command_registry

    registry = command_registry() or CommandRegistry()
    shell.command_registry = registry
    registry.register_all(shell_commands(shell), replace=True)
    for command_id, attribute in SHELL_ACTIONS.items():
        action = getattr(shell, attribute, None)
        if isinstance(action, QAction):
            bind_action(action, registry, command_id)
    return registry
