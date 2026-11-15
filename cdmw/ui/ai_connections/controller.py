"""The app's one AI connections controller (P13 stage C).

It owns the link (pipe and token), the MCP server and the tool context,
starts and stops the link with "Allow AI connections", shows the approval
prompt on the UI thread, and marks the main window's title while
connections are on, so the user can always see it.
"""

from __future__ import annotations

from PySide6.QtCore import QCoreApplication, QObject, Qt, QTimer, Signal

from cdmw.mcp import approvals
from cdmw.mcp.link import AiConnectionLink

TITLE_MARK = " [AI connections on]"
TITLE_MARK_FULL = " [AI connections on, Full access]"
_ATTRIBUTE = "_cdmw_ai_connections"
_POLL_MS = 1000


class AiConnectionsController(QObject):
    #: Something the Settings section or a status area shows changed.
    state_changed = Signal()
    _ask = Signal(object)

    def __init__(self, settings, *, window=None, table=None, services=None, prompt_factory=None,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        from cdmw.mcp.catalogue import typed_tools
        from cdmw.mcp.server import McpServer
        from cdmw.mcp.tools import ToolTable
        from cdmw.ui.ai_connections.context import AppToolContext
        from cdmw.ui.ai_connections.executor import UiExecutor
        from cdmw.ui.commands.registry import command_registry

        self.settings = settings
        self.window = window
        self.executor = UiExecutor(self)
        self.context = AppToolContext(settings, self.executor, window=window, services=services)
        self.table = table or ToolTable(typed_tools(), registry=command_registry)
        self.policy = approvals.ApprovalPolicy(settings, ask=self._ask.emit)
        self.server = McpServer(self.table, self.context, policy=self.policy)
        self.link = AiConnectionLink(self.server.serve_connection)
        self.error = ""
        self.prompts: list = []
        self._prompt_factory = prompt_factory
        self._was_connected = False
        self._ask.connect(self._show_prompt, Qt.ConnectionType.QueuedConnection)
        self._poll = QTimer(self)
        self._poll.setInterval(_POLL_MS)
        self._poll.timeout.connect(self._check_connected)

    # ----- the setting ---------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return approvals.connections_enabled(self.settings)

    def apply(self) -> None:
        """Start or stop the link to match the setting; turning it off ends any connection."""

        self.error = ""
        if self.enabled:
            try:
                self.link.start()
            except Exception as exc:  # another CDMW window, a locked workspace ...
                self.link.stop()
                self.error = f"AI connections could not start: {exc}"
            else:
                self._poll.start()
        else:
            self._poll.stop()
            self.link.stop()
        self._mark_title()
        self.state_changed.emit()

    def stop(self) -> None:
        self._poll.stop()
        self.link.stop()
        self._mark_title()

    def _check_connected(self) -> None:
        connected = self.link.connected
        if connected != self._was_connected:
            self._was_connected = connected
            self.state_changed.emit()

    def status_text(self) -> str:
        if self.error:
            return self.error
        if not self.link.listening:
            return "Off. Nothing listens and no AI app can reach CDMW."
        full = approvals.full_access(self.settings)
        if self.link.connected:
            return ("On, with Full access: an AI app is connected and its tools run without asking." if full
                    else "On. An AI app is connected.")
        return ("On, with Full access: waiting for an AI app to connect. Its tools will run without asking." if full
                else "On. Waiting for an AI app to connect.")

    # ----- the prompt ------------------------------------------------------------
    def _show_prompt(self, request) -> None:
        if request.decided:
            return
        if self._prompt_factory is not None:
            prompt = self._prompt_factory(request)
        else:
            from cdmw.ui.ai_connections.approval_prompt import ApprovalPrompt

            prompt = ApprovalPrompt(request, parent=self.window)
        self.prompts = [p for p in self.prompts if not getattr(p.request, "decided", True)] + [prompt]
        presented = getattr(prompt, "present", None)
        if callable(presented):
            presented()

    # ----- the window ----------------------------------------------------------
    def attach(self, window) -> None:
        self.window = window
        self.context.window = window
        window.windowTitleChanged.connect(lambda _title: self._mark_title())
        self._mark_title()

    def _mark_title(self) -> None:
        window = self.window
        if window is None:
            return
        try:
            title = window.windowTitle()
        except RuntimeError:
            return
        base = title.replace(TITLE_MARK_FULL, "").replace(TITLE_MARK, "")
        mark = ""
        if self.link.listening:
            mark = TITLE_MARK_FULL if approvals.full_access(self.settings) else TITLE_MARK
        if base + mark != title:
            window.setWindowTitle(base + mark)


def ai_connections_controller() -> AiConnectionsController | None:
    app = QCoreApplication.instance()
    return getattr(app, _ATTRIBUTE, None) if app is not None else None


def install_ai_connections(window, settings, **options) -> AiConnectionsController:
    """Create the app's controller once, end Full access unless kept, and apply the setting.

    The shell calls this after the main window exists (see the report's hook
    lines); Settings calls it too, so turning the setting on works even
    before that hook is in.
    """

    app = QCoreApplication.instance()
    controller = getattr(app, _ATTRIBUTE, None)
    if controller is None:
        approvals.end_full_access_unless_kept(settings)
        controller = AiConnectionsController(settings, window=window, parent=app, **options)
        setattr(app, _ATTRIBUTE, controller)
        app.aboutToQuit.connect(controller.stop)
    if window is not None and controller.window is not window:
        controller.attach(window)
    controller.apply()
    return controller


def remove_ai_connections() -> None:
    """Stop and forget the controller (application shutdown and tests)."""

    app = QCoreApplication.instance()
    controller = getattr(app, _ATTRIBUTE, None)
    if controller is not None:
        controller.stop()
        setattr(app, _ATTRIBUTE, None)
        controller.deleteLater()
