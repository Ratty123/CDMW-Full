"""Run typed calls against owned page widgets through the production Qt executor."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import threading
import time
from types import SimpleNamespace

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.mcp.approvals import ENABLED_KEY, FULL_ACCESS_KEY
from cdmw.mcp.audit import AuditLog
from cdmw.mcp.catalogue import typed_tools
from cdmw.mcp.server import McpServer, McpSession
from cdmw.mcp.tools import ToolTable
from cdmw.ui.ai_connections.context import AppToolContext
from cdmw.ui.ai_connections.executor import UiExecutor


def wait_for(predicate, timeout=15):
    app = QApplication.instance()
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if app is not None:
            app.processEvents()
        if predicate():
            return
        time.sleep(0.003)
    assert predicate(), "CDMW's page or worker did not finish"


class RailClient:
    def __init__(self, root, *, widgets=None, window=None, settings=None):
        if window is None:
            window = SimpleNamespace(shell=SimpleNamespace(_tool_widgets_by_key=widgets or {}))
        self.settings = settings or QSettings(str(root / "rail.ini"), QSettings.Format.IniFormat)
        self.settings.setValue(ENABLED_KEY, True)
        self.settings.setValue(FULL_ACCESS_KEY, True)
        self.context = AppToolContext(self.settings, UiExecutor(), window=window)
        self.server = McpServer(ToolTable(typed_tools()), self.context, audit=AuditLog(root / "rail-audit.jsonl"))
        self.session = McpSession(self.server, lambda _message: None)

    def call(self, tool_name, **arguments):
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(self.server.call_tool, self.session, {"name": tool_name, "arguments": arguments},
                                     threading.Event())
            wait_for(future.done)
            result = future.result()
        return result["structuredContent"]

    def ok(self, tool_name, **arguments):
        result = self.call(tool_name, **arguments)
        assert "error" not in result, result
        assert "waiting_on" not in result, result
        if "job" in result:
            job = self.server.jobs.get(result["job"])
            wait_for(lambda: job.wait(0))
            assert job.error is None, job.error
            return job.result
        return result
