"""P13 stage C, item 4: Allow AI connections, approvals per class, Full access and the prompt."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
import time
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication, QMainWindow

from cdmw.app import app_folder
from cdmw.mcp import approvals, tools as tool_module
from cdmw.mcp.approvals import ALLOW_ONCE, ALLOW_SESSION, DENY, ApprovalPolicy, ApprovalRequest
from cdmw.mcp.errors import DECLINED_MESSAGE, REFUSED, ToolError
from cdmw.mcp.names import DESTRUCTIVE, EDIT, EFFECT_CLASSES, OUTPUT, READ
from cdmw.mcp.tools import Tool, ToolTable, object_schema
from cdmw.services.settings_service import create_settings
from tests.mcp_helpers import Bridge, initialize

pytestmark = pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


@pytest.fixture
def profile(monkeypatch, tmp_path) -> Path:
    folder = tmp_path / "profile"
    folder.mkdir()
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(folder))
    app_folder._reset_for_tests()
    yield folder
    app_folder._reset_for_tests()


@pytest.fixture
def settings(tmp_path):
    return create_settings(settings_file_path=tmp_path / "ai.cfg")


@pytest.fixture
def every_class_built(monkeypatch):
    """This part builds read tools only; the approval path is the same for every class."""
    monkeypatch.setattr(tool_module, "BUILT_EFFECTS", frozenset(EFFECT_CLASSES))


def _pump(app):
    return lambda: app.processEvents()


# ----- the policy ------------------------------------------------------------------
def test_defaults_read_runs_and_every_other_class_asks(settings) -> None:
    assert not approvals.connections_enabled(settings), "off by default"
    assert approvals.approval_mode(settings, READ) == approvals.ALLOW
    for effect in (EDIT, DESTRUCTIVE, OUTPUT):
        assert approvals.approval_mode(settings, effect) == approvals.ASK
    asked: list[ApprovalRequest] = []
    policy = ApprovalPolicy(settings, ask=lambda request: (asked.append(request), request.decide(ALLOW_ONCE)))
    assert policy.approve(client="c", tool="search.x", title="x", effect=READ, arguments={},
                          session_allowed=set()) == "no_prompt"
    assert asked == []
    assert policy.approve(client="c", tool="mesh.x", title="x", effect=EDIT, arguments={"a": 1},
                          session_allowed=set()) == ALLOW_ONCE
    assert [r.tool for r in asked] == ["mesh.x"] and asked[0].change


def test_a_class_set_to_allow_and_full_access_stop_the_questions(settings) -> None:
    asked = []
    policy = ApprovalPolicy(settings, ask=asked.append)
    settings.setValue(approvals.APPROVAL_KEY.format(effect=EDIT), approvals.ALLOW)
    assert policy.approve(client="c", tool="mesh.x", title="x", effect=EDIT, arguments={},
                          session_allowed=set()) == "no_prompt"
    settings.setValue(approvals.FULL_ACCESS_KEY, True)
    for effect in (DESTRUCTIVE, OUTPUT):
        assert policy.approve(client="c", tool="saved.x", title="x", effect=effect, arguments={},
                              session_allowed=set()) == "no_prompt"
    assert asked == []


def test_deny_and_no_answer_refuse_and_allow_for_the_session_sticks(settings) -> None:
    answers = iter([DENY, ALLOW_SESSION])
    policy = ApprovalPolicy(settings, ask=lambda request: request.decide(next(answers)))
    allowed: set[str] = set()
    with pytest.raises(ToolError) as declined:
        policy.approve(client="c", tool="mesh.x", title="x", effect=EDIT, arguments={}, session_allowed=allowed)
    assert declined.value.code == REFUSED and declined.value.message == DECLINED_MESSAGE == "Declined in CDMW."
    assert policy.approve(client="c", tool="mesh.x", title="x", effect=EDIT, arguments={},
                          session_allowed=allowed) == ALLOW_SESSION
    assert policy.approve(client="c", tool="mesh.x", title="x", effect=EDIT, arguments={},
                          session_allowed=allowed) == "session"
    silent = ApprovalPolicy(settings, ask=lambda request: None, timeout=0.2)
    started = time.monotonic()
    with pytest.raises(ToolError, match="Declined"):
        silent.approve(client="c", tool="mesh.y", title="y", effect=EDIT, arguments={}, session_allowed=set())
    assert time.monotonic() - started < 5
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(ToolError, match="Declined"):
        ApprovalPolicy(settings, ask=lambda request: None).approve(
            client="c", tool="mesh.z", title="z", effect=EDIT, arguments={}, session_allowed=set(), cancel=cancel)


def test_full_access_ends_with_the_session_unless_kept(settings) -> None:
    settings.setValue(approvals.FULL_ACCESS_KEY, True)
    assert approvals.end_full_access_unless_kept(settings) and not approvals.full_access(settings)
    settings.setValue(approvals.FULL_ACCESS_KEY, True)
    settings.setValue(approvals.FULL_ACCESS_KEEP_KEY, True)
    assert not approvals.end_full_access_unless_kept(settings) and approvals.full_access(settings)


@pytest.mark.parametrize("key", [approvals.ENABLED_KEY, approvals.FULL_ACCESS_KEY, approvals.FULL_ACCESS_KEEP_KEY,
                                 approvals.APPROVAL_KEY.format(effect=OUTPUT), approvals.GAME_FOLDER_KEY,
                                 "AI_Connections\\Enabled", "/archive/package_root"])
def test_no_tool_can_change_the_connection_approvals_full_access_or_game_folder(key) -> None:
    with pytest.raises(ToolError) as refused:
        approvals.refuse_protected_setting(key)
    assert refused.value.code == REFUSED and "Only you" in refused.value.message
    approvals.refuse_protected_setting("appearance/theme")


# ----- through a real bridge, the real server and the real prompt --------------------
def _tools(output_folder_check=None) -> list[Tool]:
    ran: list[str] = []

    def handler(call):
        ran.append(call.tool.name)
        return {"ran": call.tool.name, "approval": call.approval}

    tools = [
        Tool(name="search.look", family="search", description="Look.", input_schema=object_schema(),
             effect=READ, route="test", handler=handler),
        Tool(name="mesh.change", family="mesh", description="Change.",
             input_schema=object_schema({"amount": {"type": "number"}}), effect=EDIT, route="test", handler=handler),
        Tool(name="saved.delete", family="saved", description="Delete.", input_schema=object_schema(),
             effect=DESTRUCTIVE, route="test", handler=handler),
        Tool(name="files.export", family="files", description="Export.",
             input_schema=object_schema({"path": {"type": "string"}}, ["path"]), effect=OUTPUT, route="test",
             handler=handler, output_paths=("path",)),
    ]
    return tools, ran


@pytest.fixture
def controller(app, profile, settings, every_class_built):
    from cdmw.ui.ai_connections.controller import AiConnectionsController

    tools, ran = _tools()
    window = QMainWindow()
    window.setWindowTitle("Crimson Desert Mod Workbench")
    controller = AiConnectionsController(settings, table=ToolTable(tools), window=None)
    controller.attach(window)
    controller.ran = ran
    controller.test_window = window
    yield controller
    controller.stop()
    for prompt in list(controller.prompts):
        try:
            prompt.deleteLater()
        except RuntimeError:
            pass
    window.deleteLater()
    app.processEvents()


def _wait_for_prompt(app, controller, timeout=20.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        app.processEvents()
        open_prompts = [p for p in controller.prompts if not p.request.decided]
        if open_prompts:
            return open_prompts[-1]
        time.sleep(0.01)
    raise AssertionError("no approval prompt appeared")


def test_off_by_default_nothing_listens_and_the_title_says_when_it_is_on(app, controller, settings, profile) -> None:
    controller.apply()
    assert not controller.link.listening and not controller.link.token_file.exists()
    assert controller.test_window.windowTitle() == "Crimson Desert Mod Workbench"
    settings.setValue(approvals.ENABLED_KEY, True)
    controller.apply()
    assert controller.link.listening and controller.link.token_file.exists()
    assert controller.test_window.windowTitle().endswith("[AI connections on]")
    settings.setValue(approvals.FULL_ACCESS_KEY, True)
    controller.apply()
    assert controller.test_window.windowTitle().endswith("[AI connections on, Full access]")
    settings.setValue(approvals.ENABLED_KEY, False)
    controller.apply()
    assert not controller.link.listening and not controller.link.token_file.exists()
    assert controller.test_window.windowTitle() == "Crimson Desert Mod Workbench"


def test_each_class_asks_in_the_app_as_configured(app, controller, settings, profile, tmp_path) -> None:
    settings.setValue(approvals.ENABLED_KEY, True)
    controller.apply()
    bridge = Bridge(profile)
    pump = _pump(app)
    try:
        initialize(bridge, pump)
        # Read runs without a question.
        bridge.send_request("tools/call", {"name": "search_look", "arguments": {}})
        assert bridge.read(pump=pump)["result"]["structuredContent"] == {"ran": "search.look",
                                                                          "approval": "no_prompt"}
        # Edit asks; the prompt names the client, the tool and its arguments; Allow once runs it.
        bridge.send_request("tools/call", {"name": "mesh_change", "arguments": {"amount": 2.5}})
        prompt = _wait_for_prompt(app, controller)
        assert "pytest-client" in prompt.summary_label.text() and "mesh.change" in prompt.summary_label.text()
        assert '"amount": 2.5' in prompt.arguments_view.toPlainText()
        assert prompt.deny_button.isDefault() and not prompt.isModal()
        prompt.allow_once_button.click()
        assert bridge.read(pump=pump)["result"]["structuredContent"]["approval"] == ALLOW_ONCE
        # Deny refuses with the stable code; Escape is the same as Deny.
        bridge.send_request("tools/call", {"name": "saved_delete", "arguments": {}})
        _wait_for_prompt(app, controller).deny_button.click()
        denied = bridge.read(pump=pump)["result"]
        assert denied["isError"] and denied["structuredContent"]["error"] == {"code": "refused",
                                                                              "message": "Declined in CDMW."}
        bridge.send_request("tools/call", {"name": "saved_delete", "arguments": {}})
        _wait_for_prompt(app, controller).reject()
        assert bridge.read(pump=pump)["result"]["structuredContent"]["error"]["code"] == "refused"
        # Allow this tool for this session: asked once, then not again on this connection.
        bridge.send_request("tools/call", {"name": "mesh_change", "arguments": {}})
        _wait_for_prompt(app, controller).allow_session_button.click()
        assert bridge.read(pump=pump)["result"]["structuredContent"]["approval"] == ALLOW_SESSION
        bridge.send_request("tools/call", {"name": "mesh_change", "arguments": {}})
        assert bridge.read(pump=pump)["result"]["structuredContent"]["approval"] == "session"
        # A class set to allow stops its questions.
        settings.setValue(approvals.APPROVAL_KEY.format(effect=DESTRUCTIVE), approvals.ALLOW)
        bridge.send_request("tools/call", {"name": "saved_delete", "arguments": {}})
        assert bridge.read(pump=pump)["result"]["structuredContent"]["approval"] == "no_prompt"
        # Full access stops all of them.
        settings.setValue(approvals.FULL_ACCESS_KEY, True)
        out = tmp_path / "exports"
        out.mkdir()
        bridge.send_request("tools/call", {"name": "files_export", "arguments": {"path": str(out / "a.dds")}})
        assert bridge.read(pump=pump)["result"]["structuredContent"]["approval"] == "no_prompt"
    finally:
        code, stderr = bridge.close()
    assert code == 0, stderr
    assert controller.ran.count("saved.delete") == 1, "denied calls never ran"


def test_an_output_path_in_the_game_is_refused_also_under_full_access(app, controller, settings, profile,
                                                                     tmp_path) -> None:
    game = tmp_path / "Crimson Desert"
    (game / "meta").mkdir(parents=True)
    (game / "meta" / "0.papgt").write_bytes(b"\0")
    settings.setValue(approvals.GAME_FOLDER_KEY, str(game))
    settings.setValue(approvals.ENABLED_KEY, True)
    settings.setValue(approvals.FULL_ACCESS_KEY, True)
    for effect in (EDIT, DESTRUCTIVE, OUTPUT):
        settings.setValue(approvals.APPROVAL_KEY.format(effect=effect), approvals.ALLOW)
    controller.apply()
    bridge = Bridge(profile)
    pump = _pump(app)
    try:
        initialize(bridge, pump)
        for target in (game / "mod.dds", game / "meta" / "1.papgt", "relative\\mod.dds"):
            bridge.send_request("tools/call", {"name": "files_export", "arguments": {"path": str(target)}})
            result = bridge.read(pump=pump)["result"]
            assert result["isError"] and result["structuredContent"]["error"]["code"] == "refused", result
        assert controller.prompts == [] and "files.export" not in controller.ran
    finally:
        bridge.close()


def test_a_call_while_the_setting_is_off_is_refused(app, controller, settings, profile) -> None:
    settings.setValue(approvals.ENABLED_KEY, True)
    controller.apply()
    bridge = Bridge(profile)
    pump = _pump(app)
    try:
        initialize(bridge, pump)
        # The setting is read for every call: off in the file means refused, even before the link stops.
        settings.setValue(approvals.ENABLED_KEY, False)
        bridge.send_request("tools/call", {"name": "search_look", "arguments": {}})
        result = bridge.read(pump=pump)["result"]
        assert result["structuredContent"]["error"] == {"code": "refused",
                                                        "message": "CDMW is not running or AI connections are off."}
    finally:
        bridge.close()


# ----- Settings ------------------------------------------------------------------------
def test_the_settings_section_writes_the_setting_and_starts_and_stops_the_link(app, controller, settings,
                                                                              profile) -> None:
    from cdmw.ui.ai_connections.settings_section import AiConnectionsSettingsSection

    section = AiConnectionsSettingsSection(settings, controller_lookup=lambda: controller)
    try:
        assert not section.enabled_checkbox.isChecked()
        assert [c.currentData() for c in section.approval_combos.values()] == ["ask", "ask", "ask"]
        assert not section.keep_full_access_checkbox.isEnabled()
        assert "Off" in section.status_label.text()
        section.enabled_checkbox.setChecked(True)
        assert approvals.connections_enabled(settings) and controller.link.listening
        assert "On" in section.status_label.text()
        section.approval_combos[OUTPUT].setCurrentIndex(section.approval_combos[OUTPUT].findData("allow"))
        assert approvals.approval_mode(settings, OUTPUT) == "allow"
        section.full_access_checkbox.setChecked(True)
        assert approvals.full_access(settings) and section.keep_full_access_checkbox.isEnabled()
        assert "Full access" in section.status_label.text()
        section.keep_full_access_checkbox.setChecked(True)
        section.full_access_checkbox.setChecked(False)
        assert not approvals._bool(settings.value(approvals.FULL_ACCESS_KEEP_KEY)), "keep goes with Full access"
        section.enabled_checkbox.setChecked(False)
        assert not controller.link.listening and not controller.link.token_file.exists()
        assert "--mcp-bridge" in section.setup_text.toPlainText()
        assert "claude mcp add cdmw" in section.setup_text.toPlainText()
    finally:
        section.deleteLater()


def test_settings_has_an_ai_connections_page(app, tmp_path) -> None:
    from cdmw.ui.settings_tab import SettingsTab

    tab = SettingsTab(settings=create_settings(settings_file_path=tmp_path / "tab.cfg"), theme_key="graphite")
    try:
        tab.show_settings_section("ai_connections")
        page = tab.section_stack.currentWidget()
        assert page.isAncestorOf(tab.ai_connections_section)
        assert not tab.ai_connections_section.enabled_checkbox.isChecked()
    finally:
        tab.deleteLater()
