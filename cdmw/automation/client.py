"""Client side of the automation bridge: tests and timing harnesses."""

from __future__ import annotations

import os
import secrets
import subprocess
import sys
import time
from multiprocessing import connection
from pathlib import Path
from typing import Mapping

from cdmw.automation.pipe import recv_json, send_json
from cdmw.automation.policy import AUTOMATION_ENV, HIDDEN_ENV, PIPE_ENV, TOKEN_ENV, pipe_address

ROOT = Path(__file__).resolve().parents[2]


class AutomationError(RuntimeError):
    """The app refused or failed a command; the message is its reason."""


class AutomationClient:
    def __init__(self, address: str, token: bytes) -> None:
        self._conn = connection.Client(address, family="AF_PIPE", authkey=bytes(token))
        self._next = 0

    def call(self, command: str, **args: object) -> object:
        self._next += 1
        send_json(self._conn, {"id": self._next, "command": command, "args": args})
        reply = recv_json(self._conn)
        if not isinstance(reply, dict) or reply.get("id") != self._next:
            raise AutomationError("The app sent an unexpected reply.")
        if not reply.get("ok"):
            raise AutomationError(str(reply.get("error") or "The command failed."))
        return reply.get("result")

    def close(self) -> None:
        self._conn.close()

    def __enter__(self) -> "AutomationClient":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()


class AutomatedApp:
    """The real app in a child process, under a profile of its own."""

    def __init__(self, profile: Path, *, hidden: bool = True, extra_env: Mapping[str, str] | None = None,
                 python: str | None = None, log_path: Path | None = None) -> None:
        self.profile = Path(profile).resolve()
        self.token = secrets.token_bytes(32)
        self.name = f"run-{os.getpid()}-{secrets.token_hex(4)}"
        self.address = pipe_address(self.name)
        env = dict(os.environ)
        # A fresh run: nothing inherited from a parent CDMW process.
        for key in ("CDMW_SYSTEM_TEMP", "CDMW_SINGLE_INSTANCE_SCOPE", "CDMW_TEMP_CACHE_ROOT"):
            env.pop(key, None)
        env.update({
            "CDMW_PROFILE_DIR": str(self.profile),
            AUTOMATION_ENV: "1",
            TOKEN_ENV: self.token.hex(),
            PIPE_ENV: self.name,
            HIDDEN_ENV: "1" if hidden else "0",
            "QT_QPA_PLATFORM": env.get("QT_QPA_PLATFORM", "windows"),
        })
        env.update(dict(extra_env or {}))
        self.log_path = Path(log_path) if log_path else self.profile / "automation-run.log"
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        self._log = self.log_path.open("w", encoding="utf-8")
        command = [python or sys.executable, str(ROOT / "cdmw_app.py"), "--gui", "--automation"]
        self.process = subprocess.Popen(command, cwd=ROOT, env=env, stdout=self._log, stderr=subprocess.STDOUT)
        self.client: AutomationClient | None = None

    def connect(self, timeout: float = 120.0) -> AutomationClient:
        deadline = time.monotonic() + timeout
        last = None
        while time.monotonic() < deadline:
            if self.process.poll() is not None:
                raise AutomationError(f"The app exited with {self.process.returncode} before listening.")
            try:
                self.client = AutomationClient(self.address, self.token)
                return self.client
            except (FileNotFoundError, OSError) as exc:
                last = exc
                time.sleep(0.05)
        raise AutomationError(f"The app did not start listening: {last}")

    def close(self, timeout: float = 60.0) -> int:
        if self.client is not None:
            try:
                self.client.call("quit")
            except Exception:
                pass
            try:
                self.client.close()
            except Exception:
                pass
            try:
                self.process.wait(timeout)
            except subprocess.TimeoutExpired:
                pass
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(10)
        self._log.close()
        return int(self.process.returncode or 0)
