"""What tools reach in the app: settings, the registry, the game folder and the services.

One object per app, given to every tool call as ``call.context``. Each
accessor is safe from a tool's thread: interface state is read through
``ui_call``, which runs on the UI thread.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.mcp.approvals import GAME_FOLDER_KEY


class AppToolContext:
    def __init__(self, settings, executor, *, window=None, services=None) -> None:
        self.settings = settings
        self.executor = executor
        self.window = window
        self._services = services

    def ui_call(self, function, timeout: float | None = None):
        if timeout is None:
            return self.executor.call(function)
        return self.executor.call(function, timeout)

    def command_registry(self):
        from cdmw.ui.commands.registry import command_registry

        return command_registry()

    def game_folder(self) -> str:
        value = self.settings.value(GAME_FOLDER_KEY, "") if self.settings is not None else ""
        return str(value or "").strip()

    def services(self):
        """The window's service container (``app_context.services``), or the one given."""

        if self._services is not None:
            return self._services
        app_context = getattr(self.window, "app_context", None)
        return getattr(app_context, "services", None)

    def workspace_root(self) -> Path:
        from cdmw.app.app_folder import workspace_folder

        return workspace_folder()
