"""Shared harness for the AI connection's tool tests: the real server, link and bridge.

``McpApp`` is the app side as CDMW runs it (the controller with every typed tool, the
pipe, the approval prompt) around a window the test gives it, and a real
``--mcp-bridge`` child process as the client. ``call`` sends ``tools/call`` and pumps
the Qt event loop until the answer comes, so UI-thread tools run as they do in the app.
"""
from __future__ import annotations

import time
from pathlib import Path

from cdmw.mcp import approvals
from tests.mcp_helpers import Bridge, initialize


class McpApp:
    def __init__(self, app, profile: Path, settings, window, *, full_access: bool = True) -> None:
        from cdmw.ui.ai_connections.controller import AiConnectionsController

        self.app = app
        self._client_thread = False
        self.settings = settings
        self.window = window
        settings.setValue(approvals.ENABLED_KEY, True)
        settings.setValue(approvals.FULL_ACCESS_KEY, bool(full_access))
        self.controller = AiConnectionsController(settings, window=None)
        if hasattr(window, "windowTitleChanged"):
            self.controller.attach(window)
        else:
            # A stand-in for the main window: the tools reach it, the title mark does not.
            self.controller.context.window = window
        self.controller.apply()
        self.bridge = Bridge(profile)
        self.hello = initialize(self.bridge, self.pump)

    def pump(self) -> None:
        if not self._client_thread:
            self.app.processEvents()

    def as_client(self, script, timeout: float = 120.0):
        """Run ``script()`` (which calls the tools) on a thread of its own while this
        thread runs the event loop, as in the app: needed when a tool opens a dialog
        whose own event loop would otherwise hold the thread that reads the answers."""

        import threading

        box: dict[str, object] = {}

        def run() -> None:
            try:
                box["value"] = script()
            except BaseException as exc:
                box["error"] = exc

        thread = threading.Thread(target=run, daemon=True)
        self._client_thread = True
        try:
            thread.start()
            deadline = time.monotonic() + timeout
            while thread.is_alive():
                self.app.processEvents()
                time.sleep(0.005)
                assert time.monotonic() < deadline, "the client script did not finish"
        finally:
            self._client_thread = False
        if "error" in box:
            raise box["error"]
        return box.get("value")

    def request(self, method: str, params: dict | None = None, timeout: float = 60.0) -> dict:
        self.bridge.send_request(method, params or {})
        return self.bridge.read(timeout, pump=self.pump)

    def send(self, tool: str, arguments: dict | None = None) -> None:
        self.bridge.send_request("tools/call", {"name": tool, "arguments": arguments or {}})

    def read(self, timeout: float = 60.0) -> dict:
        return self.bridge.read(timeout, pump=self.pump)["result"]

    def call(self, tool: str, arguments: dict | None = None, timeout: float = 60.0) -> dict:
        """The tool's result: ``structuredContent``, with ``isError`` and ``content`` beside it."""

        self.send(tool, arguments)
        return self.read(timeout)

    def ok(self, tool: str, arguments: dict | None = None, timeout: float = 60.0) -> dict:
        result = self.call(tool, arguments, timeout)
        assert not result["isError"], result["structuredContent"]
        return result["structuredContent"]

    def error(self, tool: str, arguments: dict | None = None, timeout: float = 60.0) -> dict:
        result = self.call(tool, arguments, timeout)
        assert result["isError"], result["structuredContent"]
        return result["structuredContent"]["error"]

    def wait_for_prompt(self, timeout: float = 20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            waiting = [p for p in self.controller.prompts if not p.request.decided]
            if waiting:
                return waiting[-1]
            time.sleep(0.01)
        raise AssertionError("no approval prompt appeared")

    def wait_until(self, check, timeout: float = 20.0):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.pump()
            value = check()
            if value:
                return value
            time.sleep(0.01)
        raise AssertionError("the condition did not come true in time")

    def close(self) -> None:
        code, stderr = self.bridge.close()
        self.controller.stop()
        for prompt in list(self.controller.prompts):
            try:
                prompt.deleteLater()
            except RuntimeError:
                pass
        self.controller.deleteLater()
        self.pump()
        assert code == 0, stderr
