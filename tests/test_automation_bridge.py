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


def test_ui_stack_answers_while_the_ui_thread_is_blocked_and_names_the_blocker(env) -> None:
    """The stall probe for defect 2: ``ui_stack`` is read on the listener thread, so it
    answers while a UI-thread command is still running and names what holds the thread."""

    from PySide6.QtWidgets import QApplication

    from cdmw.automation.bridge import AutomationBridge
    from cdmw.automation.client import AutomationClient

    app = QApplication.instance() or QApplication([])
    env.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    env.setenv(policy.PIPE_ENV, f"test-stack-{os.getpid()}-{secrets.token_hex(4)}")
    settings = policy.automation_settings()
    bridge = AutomationBridge(settings)
    release = threading.Event()
    entered = threading.Event()

    def blocking_ui_work_for_the_probe(_args):
        entered.set()
        release.wait(10)
        return "done"

    bridge._ui_commands["block"] = blocking_ui_work_for_the_probe
    window = _Window()
    bridge.attach(window)
    results: dict[str, object] = {}

    def blocker():
        with AutomationClient(settings.address, settings.token) as client:
            results["block"] = client.call("block")

    def sampler():
        try:
            entered.wait(10)
            with AutomationClient(settings.address, settings.token) as client:
                started = time.perf_counter()
                results["stack"] = client.call("ui_stack")
                results["answer_s"] = time.perf_counter() - started
        except Exception as exc:  # surfaced below
            results["error"] = repr(exc)
        finally:
            release.set()

    workers = [threading.Thread(target=blocker), threading.Thread(target=sampler)]
    for worker in workers:
        worker.start()
    deadline = time.time() + 20
    while any(worker.is_alive() for worker in workers) and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    for worker in workers:
        worker.join(1)
    bridge.stop()
    window.widget.deleteLater()
    assert "error" not in results, results
    assert results["block"] == "done"
    assert results["answer_s"] < 2.0
    assert any("blocking_ui_work_for_the_probe" in line for line in results["stack"]), results["stack"]
    assert all(isinstance(line, str) and ":" in line for line in results["stack"])


def test_windows_are_kept_off_screen_even_when_qt_itself_shows_them() -> None:
    """A plain show() must not reach the screen; patching setVisible in Python missed these."""

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication, QSplashScreen, QWidget

    from cdmw.automation.bridge import _WindowPlacement

    app = QApplication.instance() or QApplication([])
    placement = _WindowPlacement(hidden=True)
    app.installEventFilter(placement)
    try:
        for widget in (QWidget(), QSplashScreen()):
            widget.show()
            assert widget.testAttribute(Qt.WidgetAttribute.WA_DontShowOnScreen), type(widget).__name__
            widget.close()
            widget.deleteLater()
    finally:
        app.removeEventFilter(placement)


def test_with_no_secondary_screen_windows_go_off_screen_not_on_the_primary(monkeypatch) -> None:
    """A game or a switched-off monitor can leave one screen: the test window must not
    then be put on the user's main monitor (2026-11-16, a run's window landed at x=8)."""

    from PySide6.QtCore import QRect
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication, QWidget

    from cdmw.automation import bridge

    QApplication.instance() or QApplication([])

    class _Screen:
        def __init__(self, rect):
            self.rect = rect

        def availableGeometry(self):  # noqa: N802 - Qt API
            return self.rect

        def virtualGeometry(self):  # noqa: N802 - Qt API
            return QRect(-1920, 0, 1920 + 2293, 1080)

    primary = _Screen(QRect(0, 0, 2293, 960))
    secondary = _Screen(QRect(-1920, 0, 1920, 1080))
    monkeypatch.setattr(QGuiApplication, "primaryScreen", staticmethod(lambda: primary))
    monkeypatch.delenv(bridge.SCREEN_ENV, raising=False)
    widget = QWidget()
    try:
        monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [primary]))
        assert bridge.automation_screen() is None
        bridge.place_on_automation_screen(widget)
        assert widget.x() > 2293 and widget.y() > 1080
        monkeypatch.setattr(QGuiApplication, "screens", staticmethod(lambda: [primary, secondary]))
        assert bridge.automation_screen() is secondary
        bridge.place_on_automation_screen(widget)
        assert (widget.x(), widget.y()) == (-1880, 40)
    finally:
        widget.deleteLater()


def test_switch_piece_answers_the_prompt_and_restores_it(env, monkeypatch) -> None:
    """The set commands call what the menu and the editor call; the end-edit prompt
    is answered only while the switch runs."""
    from types import SimpleNamespace

    from cdmw.automation.bridge import AutomationBridge
    from cdmw.ui.mesh_editor import item_set_preparation
    from cdmw.ui.mesh_editor.live_edit import end_edit_prompt

    env.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    bridge = AutomationBridge(policy.automation_settings())
    assert {"open_set", "switch_piece"} <= set(bridge._ui_commands)
    seen = []

    def switch(shell, index):
        seen.append((shell, index, end_edit_prompt.prompt_override(None, "file")))

    monkeypatch.setattr(item_set_preparation, "switch_item_piece", switch)
    shell = object()
    bridge.window = SimpleNamespace(shell=shell)
    assert bridge._switch_piece({"index": 1, "answer": "discard"})
    assert seen == [(shell, 1, end_edit_prompt.DISCARD)]
    assert end_edit_prompt.prompt_override is None


def test_build_mod_writes_inside_the_run_profile_only(env, tmp_path) -> None:
    from cdmw.automation.bridge import AutomationBridge

    env.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    bridge = AutomationBridge(policy.automation_settings())
    assert "build_mod" in bridge._ui_commands
    with pytest.raises(ValueError, match="inside the run's own profile"):
        bridge._build_mod({"output_dir": str(tmp_path / "elsewhere")})


def test_thread_stacks_name_a_busy_worker_while_the_ui_thread_waits(env) -> None:
    """A stall whose ``ui_stack`` is only the event loop can be the window thread waiting
    for the GIL; ``thread_stacks`` names the worker holding it, read on the listener thread."""

    from PySide6.QtWidgets import QApplication

    from cdmw.automation.bridge import AutomationBridge
    from cdmw.automation.client import AutomationClient

    app = QApplication.instance() or QApplication([])
    env.setenv(policy.TOKEN_ENV, secrets.token_hex(32))
    env.setenv(policy.PIPE_ENV, f"test-threads-{os.getpid()}-{secrets.token_hex(4)}")
    settings = policy.automation_settings()
    bridge = AutomationBridge(settings)
    window = _Window()
    bridge.attach(window)
    stop = threading.Event()
    running = threading.Event()

    def busy_python_worker_for_the_probe():
        running.set()
        total = 0
        while not stop.is_set():
            for value in range(5000):
                total += value * value

    worker = threading.Thread(target=busy_python_worker_for_the_probe, name="busy-probe-worker")
    worker.start()
    results: dict[str, object] = {}

    def sampler():
        try:
            running.wait(10)
            with AutomationClient(settings.address, settings.token) as client:
                results["threads"] = client.call("thread_stacks")
        except Exception as exc:  # surfaced below
            results["error"] = repr(exc)

    probe = threading.Thread(target=sampler)
    probe.start()
    deadline = time.time() + 20
    while probe.is_alive() and time.time() < deadline:
        app.processEvents()
        time.sleep(0.005)
    probe.join(1)
    stop.set()
    worker.join(5)
    bridge.stop()
    window.widget.deleteLater()
    assert "error" not in results, results
    rows = results["threads"]
    busy = [row for row in rows if row["name"] == "busy-probe-worker"]
    assert busy and not busy[0]["main"], rows
    assert any("busy_python_worker_for_the_probe" in line for line in busy[0]["frames"]), busy
    assert sum(1 for row in rows if row["main"]) == 1
    assert all(isinstance(line, str) and ":" in line for row in rows for line in row["frames"])
