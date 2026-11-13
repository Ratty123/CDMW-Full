"""Shared helpers for the AI connection tests: a real ``--mcp-bridge`` child process."""
from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

from cdmw.app import app_folder

ROOT = Path(__file__).resolve().parents[1]


class Bridge:
    """``cdmw_app.py --mcp-bridge`` as an MCP client starts it: pipes for stdin and stdout, no window."""

    def __init__(self, profile: Path) -> None:
        env = {k: v for k, v in os.environ.items() if k not in (app_folder.SYSTEM_TEMP_ENV,)}
        env[app_folder.PROFILE_DIR_ENV] = str(profile)
        env["CDMW_NO_DIALOGS"] = "1"
        self.process = subprocess.Popen([sys.executable, str(ROOT / "cdmw_app.py"), "--mcp-bridge"], cwd=ROOT,
                                        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE)
        self._next = 0
        self._lines: queue.Queue[bytes] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        for line in iter(self.process.stdout.readline, b""):
            self._lines.put(line)
        self._lines.put(b"")

    def send(self, message: dict) -> None:
        self.process.stdin.write(json.dumps(message).encode("utf-8") + b"\n")
        self.process.stdin.flush()

    def send_request(self, method: str, params: dict | None = None) -> int:
        self._next += 1
        self.send({"jsonrpc": "2.0", "id": self._next, "method": method, "params": params or {}})
        return self._next

    def request(self, method: str, params: dict | None = None, timeout: float = 30.0) -> dict:
        self.send_request(method, params)
        return self.read(timeout)

    def call(self, tool: str, arguments: dict | None = None, timeout: float = 30.0) -> dict:
        return self.request("tools/call", {"name": tool, "arguments": arguments or {}}, timeout)["result"]

    def read(self, timeout: float = 30.0, pump=None) -> dict:
        """The next line; ``pump()`` runs meanwhile (the Qt event loop, when the app side needs it)."""

        deadline = time.monotonic() + timeout
        while True:
            try:
                line = self._lines.get(timeout=0.01)
                break
            except queue.Empty:
                if pump is not None:
                    pump()
                if time.monotonic() > deadline:
                    raise AssertionError("the bridge sent nothing in time")
        assert line, "the bridge closed its output"
        return json.loads(line)

    def close(self, timeout: float = 30.0) -> tuple[int, str]:
        try:
            self.process.stdin.close()
        except OSError:
            pass
        try:
            self.process.wait(timeout)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait(10)
        return self.process.returncode, self.process.stderr.read().decode("utf-8", "replace")


def initialize(bridge: Bridge, pump=None) -> dict:
    bridge.send_request("initialize", {"protocolVersion": "2025-06-18", "clientInfo": {"name": "pytest-client"},
                                       "capabilities": {}})
    reply = bridge.read(pump=pump)
    bridge.send({"jsonrpc": "2.0", "method": "notifications/initialized"})
    return reply
