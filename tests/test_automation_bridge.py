"""P13 stage A: the automation bridge is off by default and hardened when on."""
from __future__ import annotations

import os
import secrets
import subprocess
import sys
import threading
import time
from multiprocessing import AuthenticationError, connection
from pathlib import Path

import pytest

from cdmw.app import app_folder
from cdmw.automation import policy

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="the automation pipe is Windows-only")


@pytest.fixture
def env(monkeypatch, tmp_path):
    for name in (policy.AUTOMATION_ENV, policy.TOKEN_ENV, policy.PIPE_ENV, policy.HIDDEN_ENV):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path / "profile"))
    app_folder._reset_for_tests()
    yield monkeypatch
    app_folder._reset_for_tests()


def test_the_bridge_is_off_by_default(env) -> None:
    from cdmw.automation.bridge import start_automation_if_requested

    assert not policy.automation_requested()
    assert start_automation_if_requested() is None


def test_each_rule_refuses_with_its_reason(env, tmp_path) -> None:
    env.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    env.delenv(app_folder.PROFILE_DIR_ENV)
    with pytest.raises(policy.AutomationRefused, match="CDMW_PROFILE_DIR"):
        policy.automation_settings()
    env.setenv(app_folder.PROFILE_DIR_ENV, str(app_folder.default_app_folder()))
    with pytest.raises(policy.AutomationRefused, match="own folder"):
        policy.automation_settings()
    env.setenv(app_folder.PROFILE_DIR_ENV, str(tmp_path / "profile"))
    for token in ("", "not-hex", secrets.token_hex(8)):
        env.setenv(policy.TOKEN_ENV, token)
        with pytest.raises(policy.AutomationRefused, match="token"):
            policy.automation_settings()
    env.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    settings = policy.automation_settings()
    assert settings.address.startswith(policy.PIPE_PREFIX) and not settings.hidden


@pytest.mark.parametrize("missing", ["profile", "token"])
def test_a_refused_start_says_why_before_any_window(tmp_path, missing) -> None:
    run_env = {k: v for k, v in os.environ.items()
               if k not in (app_folder.PROFILE_DIR_ENV, policy.TOKEN_ENV, app_folder.SYSTEM_TEMP_ENV)}
    if missing == "token":
        run_env[app_folder.PROFILE_DIR_ENV] = str(tmp_path / "profile")
    run_env["CDMW_NO_DIALOGS"] = "1"
    result = subprocess.run([sys.executable, str(ROOT / "cdmw_app.py"), "--gui", "--automation"], cwd=ROOT,
                            env=run_env, capture_output=True, text=True, timeout=120)
    assert result.returncode == 4, result.stderr[-2000:]
    assert "Automation refused:" in result.stderr
    assert ("CDMW_PROFILE_DIR" if missing == "profile" else "token") in result.stderr


def _server(handler):
    from cdmw.automation.pipe import LocalPipeServer

    token = secrets.token_bytes(32)
    address = policy.pipe_address(f"test-{os.getpid()}-{secrets.token_hex(4)}")
    refused: list[str] = []
    server = LocalPipeServer(address, token, handler, refused=refused.append)
    server.start()
    return server, address, token, refused


def test_a_client_without_the_token_is_refused_before_any_command() -> None:
    from cdmw.automation.pipe import recv_json, send_json

    served = []

    def handler(conn):
        message = recv_json(conn)
        served.append(message)
        send_json(conn, {"echo": message})

    server, address, token, refused = _server(handler)
    try:
        with pytest.raises((AuthenticationError, EOFError, OSError)):
            connection.Client(address, family="AF_PIPE", authkey=secrets.token_bytes(32))
        deadline = time.time() + 5
        while not refused and time.time() < deadline:
            time.sleep(0.02)
        assert refused and "handshake" in refused[0]
        assert served == []
        good = connection.Client(address, family="AF_PIPE", authkey=token)
        send_json(good, {"command": "ping"})
        assert recv_json(good) == {"echo": {"command": "ping"}}
        good.close()
    finally:
        server.stop()


def test_this_users_client_is_recognised_and_remote_clients_are_rejected() -> None:
    from cdmw.automation import pipe

    seen = []
    server, address, token, _refused = _server(lambda conn: seen.append(pipe.client_runs_as_this_user(conn)))
    try:
        connection.Client(address, family="AF_PIPE", authkey=token).close()
        deadline = time.time() + 5
        while not seen and time.time() < deadline:
            time.sleep(0.02)
        assert seen == [True]
        # Every instance of the pipe is created with PIPE_REJECT_REMOTE_CLIENTS.
        import inspect

        assert "PIPE_REJECT_REMOTE_CLIENTS" in inspect.getsource(pipe._LocalPipeListener._new_handle)
    finally:
        server.stop()


class _Window:
    """Just enough of the main window for the bridge's own commands."""

    def __init__(self) -> None:
        from PySide6.QtWidgets import QMainWindow

        self.widget = QMainWindow()
        self.widget.setWindowTitle("Crimson Desert Mod Workbench")
        self.archive = None
        self.windowTitleChanged = self.widget.windowTitleChanged

    def windowTitle(self):  # noqa: N802 - Qt API
        return self.widget.windowTitle()

    def setWindowTitle(self, title):  # noqa: N802 - Qt API
        self.widget.setWindowTitle(title)


def test_commands_run_on_the_ui_thread_and_waits_do_not_block_it(env, tmp_path) -> None:
    from PySide6.QtWidgets import QApplication

    from cdmw.automation.bridge import TITLE_MARK, AutomationBridge
    from cdmw.automation.client import AutomationClient, AutomationError

    app = QApplication.instance() or QApplication([])
    env.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    env.setenv(policy.PIPE_ENV, f"test-ui-{os.getpid()}-{secrets.token_hex(4)}")
    settings = policy.automation_settings()
    bridge = AutomationBridge(settings)
    threads = []
    bridge._ui_commands["probe"] = lambda _args: threads.append(threading.current_thread()) or "ran"
    window = _Window()
    bridge.attach(window)
    results: dict[str, object] = {}

    def client_side():
        try:
            with AutomationClient(settings.address, settings.token) as client:
                results["probe"] = client.call("probe")
                since = len(client.call("events"))
                bridge._push("test_event", {"value": 7})
                results["waited"] = client.call("wait_event", event="test_event", since=since, timeout=5)
                try:
                    client.call("not_a_command")
                except AutomationError as exc:
                    results["refused"] = str(exc)
                try:
                    client.call("capture", path=str(tmp_path / "outside" / "x.png"))
                except AutomationError as exc:
                    results["capture"] = str(exc)
        except Exception as exc:  # surfaced below
            results["error"] = repr(exc)

    worker = threading.Thread(target=client_side)
    worker.start()
    deadline = time.time() + 20
    while worker.is_alive() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    worker.join(1)
    bridge.stop()
    assert "error" not in results, results
    assert results["probe"] == "ran" and threads == [threading.main_thread()]
    assert results["waited"]["value"] == 7
    assert "Unknown automation command: not_a_command" in results["refused"]
    assert "inside the run's own profile folder" in results["capture"]
    assert window.windowTitle().endswith(TITLE_MARK)
    window.setWindowTitle("Another title")
    app.processEvents()
    assert window.windowTitle().endswith(TITLE_MARK)
    window.widget.deleteLater()
