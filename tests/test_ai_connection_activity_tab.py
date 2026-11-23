"""The Workspace Activity drawer's AI Connection tab: fed by the audit log, live, bounded, collapsed."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QVBoxLayout, QWidget

from cdmw.app import app_folder
from cdmw.mcp.activity import ActivityFeed
from cdmw.mcp.app_tools import app_tools
from cdmw.mcp.audit import AuditLog
from cdmw.mcp.errors import REFUSED, ToolError
from cdmw.mcp.jobs import JobRegistry
from cdmw.mcp.names import READ
from cdmw.mcp.server import McpServer
from cdmw.mcp.tools import Tool, ToolTable, object_schema
from cdmw.ui.ai_connections.activity_model import AiActivityModel
from cdmw.ui.shell.compact.activity import ActivityHistory
from cdmw.ui.shell.compact.drawer import CompactActivityDrawer


@pytest.fixture
def app():
    return QApplication.instance() or QApplication([])


def _pump_until(app, condition, timeout: float = 10.0) -> None:
    deadline = time.monotonic() + timeout
    while not condition():
        app.processEvents()
        if time.monotonic() > deadline:
            raise AssertionError("the tab did not update in time")
        time.sleep(0.005)
    app.processEvents()


def _record(log: AuditLog, *, tool="mesh.transform", arguments=None, result="ok", message="", job="",
            duration_s=0.012) -> None:
    log.record(client="pytest-client", tool=tool, effect="edit", arguments=arguments or {"part": 3, "scale": 1.1},
               approval="allowed_once", result=result, duration_s=duration_s, job=job, message=message)


@pytest.fixture
def fed(app, tmp_path):
    feed = ActivityFeed()
    log = AuditLog(tmp_path / "logs" / "ai-calls.log")
    log.feed = feed
    model = AiActivityModel()
    model.attach(feed, log_path=log.path)
    yield feed, log, model
    model.detach(feed)
    model.deleteLater()


def test_a_call_audited_on_a_worker_thread_reaches_the_tab_as_the_file_has_it(app, fed) -> None:
    feed, log, model = fed
    worker = threading.Thread(target=_record, args=(log,),
                              kwargs={"result": REFUSED, "message": "Declined in CDMW."})
    worker.start()
    worker.join(5)
    _pump_until(app, lambda: model.rows)
    (row,) = model.rows
    line = json.loads(log.path.read_text(encoding="utf-8").splitlines()[0])
    assert row.tool == line["tool"] == "mesh.transform"
    assert row.result == line["result"] == REFUSED and row.message == line["message"] == "Declined in CDMW."
    assert json.loads(row.arguments_full) == line["arguments"] == {"part": 3, "scale": 1.1}
    assert row.duration_ms == line["duration_ms"] == 12
    assert row.is_error and row.result_text() == "refused: Declined in CDMW."
    assert row.arguments == "part=3, scale=1.1"


def test_the_same_call_failing_the_same_way_collapses_into_one_row_with_a_count(app, fed) -> None:
    feed, log, model = fed
    for _ in range(12):
        _record(log, result="unavailable", message="Open a mesh first.")
    _record(log, result="unavailable", message="Something else.")
    _record(log, tool="mesh.state", arguments={})
    _record(log, tool="mesh.state", arguments={})
    _record(log, tool="mesh.build", arguments={"out": "x"}, job="job-1")
    _record(log, tool="mesh.build", arguments={"out": "x"}, job="job-2")
    _pump_until(app, lambda: len(model.rows) >= 5)
    counts = [(row.tool, row.message, row.count) for row in model.rows]
    assert counts == [("mesh.transform", "Open a mesh first.", 12), ("mesh.transform", "Something else.", 1),
                      ("mesh.state", "", 2), ("mesh.build", "", 1), ("mesh.build", "", 1)]
    host = QWidget()
    drawer = CompactActivityDrawer(ActivityHistory(parent=host), host, ai_activity=model)
    drawer.ai_connection_view.refresh()
    first = drawer.ai_connection_view.calls_view.topLevelItem(0)
    assert first.text(1) == "mesh.transform ×12"
    host.deleteLater()


def test_the_rows_stay_capped_and_a_slow_interface_never_backs_up_the_calls(app) -> None:
    model = AiActivityModel(cap=20)
    model.apply_events([{"kind": "call", "tool": f"t{index}", "result": "ok"} for index in range(50)])
    assert len(model.rows) == 20 and model.rows[0].tool == "t30" and model.rows[-1].tool == "t49"

    # Nothing drains this feed: it keeps its newest events, counts the rest and the call never waits.
    feed = ActivityFeed(capacity=100)
    wakes = []
    feed.set_waker(lambda: wakes.append(1))
    started = time.monotonic()
    for index in range(1000):
        feed.call({"tool": f"t{index}", "result": "ok"})
    assert time.monotonic() - started < 2.0
    assert len(wakes) == 1  # one wake until the interface drains, not one per event
    events, dropped = feed.drain()
    assert len(events) == 100 and dropped == 900 and events[-1]["tool"] == "t999"
    model.attach(feed)
    feed.call({"tool": "after", "result": "ok"})
    _pump_until(app, lambda: model.rows[-1].tool == "after")
    model.detach(feed)


def test_a_feed_whose_tab_is_gone_stops_waking_it(app) -> None:
    feed = ActivityFeed()
    model = AiActivityModel()
    model.attach(feed)
    model.deleteLater()
    app.processEvents()
    from PySide6.QtCore import QCoreApplication, QEvent

    QCoreApplication.sendPostedEvents(None, QEvent.Type.DeferredDelete)
    feed.call({"tool": "x", "result": "ok"})  # must not raise
    feed.call({"tool": "y", "result": "ok"})


def test_a_job_shows_its_later_completion_even_when_it_ends_before_its_line(app, fed) -> None:
    feed, log, model = fed

    class _Job:
        def __init__(self, job_id, state, error=None):
            self.id, self.tool, self.state, self.error = job_id, "textures.upscale", state, error
            self.started, self.finished = 100.0, 112.5

    _record(log, tool="textures.upscale", job="job-a")
    feed.job_finished(_Job("job-a", "done"))
    feed.job_finished(_Job("job-b", "failed", ToolError("failed", "The model ran out of memory.")))
    _record(log, tool="textures.upscale", arguments={"other": 1}, job="job-b")
    _pump_until(app, lambda: len(model.rows) == 2 and model.rows[1].job_state)
    done, failed = model.rows
    assert done.job_text() == "job-a: done in 12.5 s" and not done.is_error
    assert failed.job_state == "failed" and failed.is_error
    assert failed.job_text() == "job-b: failed after 12.5 s: The model ran out of memory."


def test_nothing_is_shown_while_no_client_connects(app, fed) -> None:
    feed, log, model = fed
    model.set_listening(True)
    host = QWidget()
    QVBoxLayout(host).addWidget(drawer := CompactActivityDrawer(ActivityHistory(parent=host), host,
                                                                ai_activity=model))
    host.resize(800, 260)
    host.show()
    try:
        drawer.tabs.setCurrentWidget(drawer.ai_connection_view)
        app.processEvents()
        view = drawer.ai_connection_view
        assert model.rows == [] and not model.connected
        assert view.calls_view.topLevelItemCount() == 0
        assert view.empty_label.isVisible() and not view.calls_view.isVisible()
        assert view.status_label.text() == "Not connected. Waiting for an AI app to connect."
        assert not drawer.clear_button.isEnabled() and not drawer.copy_button.isEnabled()
        assert not view.open_log_button.isEnabled()  # no call yet, so no log file
        model.set_listening(False)
        app.processEvents()
        assert view.status_label.text().startswith("Not connected. AI connections are off")
    finally:
        host.close()
        host.deleteLater()


def test_the_drawer_builds_the_ai_connection_tab_headless(app, fed) -> None:
    feed, log, model = fed
    host = QWidget()
    QVBoxLayout(host).addWidget(drawer := CompactActivityDrawer(ActivityHistory(parent=host), host,
                                                                ai_activity=model))
    host.resize(800, 260)
    host.show()
    try:
        assert [drawer.tabs.tabText(i) for i in range(drawer.tabs.count())] == [
            "Activity", "Current Tool Log", "AI Connection"]
        feed.connected()
        feed.client_named("Claude Code")
        _record(log, result="refused", message="Declined in CDMW.")
        _record(log, tool="mesh.state", arguments={})
        drawer.tabs.setCurrentWidget(drawer.ai_connection_view)
        _pump_until(app, lambda: len(model.rows) == 3)
        view = drawer.ai_connection_view
        _pump_until(app, lambda: view.calls_view.topLevelItemCount() == 3)
        assert view.status_label.text().startswith("Connected: Claude Code, since ")
        assert view.calls_view.topLevelItem(0).text(1) == "Connected: Claude Code"
        refused = view.calls_view.topLevelItem(1)
        assert refused.text(3) == "refused: Declined in CDMW." and refused.data(3, 0x0100) == "error"
        assert view.calls_view.topLevelItem(2).data(3, 0x0100) == ""
        assert view.open_log_button.isEnabled()
        assert drawer.clear_button.isEnabled() and drawer.copy_button.isEnabled()
        drawer.copy_button.click()
        assert "mesh.state" in QApplication.clipboard().text()

        # Clear on this tab clears only this tab.
        drawer._history.append("Something else happened.")
        drawer.clear_button.click()
        assert model.rows == [] and view.calls_view.topLevelItemCount() == 0
        assert drawer._history.events
        feed.disconnected()
        _pump_until(app, lambda: model.rows and not model.connected)
        _pump_until(app, lambda: view.calls_view.topLevelItemCount() == 1)
        assert view.calls_view.topLevelItem(0).text(1) == "Disconnected: Claude Code"
    finally:
        host.close()
        host.deleteLater()


# ----- through the real pipe and a real ``--mcp-bridge`` process --------------------------
@pytest.fixture
def profile(monkeypatch, tmp_path) -> Path:
    folder = tmp_path / "profile"
    folder.mkdir()
    monkeypatch.setenv(app_folder.PROFILE_DIR_ENV, str(folder))
    app_folder._reset_for_tests()
    yield folder
    app_folder._reset_for_tests()


class _Context:
    def ui_call(self, function, timeout: float = 30.0):
        return function()

    def command_registry(self):
        return None

    def game_folder(self) -> str:
        return ""


def _echo(call):
    if call.arguments.get("fail"):
        raise ToolError("unavailable", "Nothing is open.")
    return {"echo": call.arguments.get("text", "")}


@pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")
def test_a_real_client_shows_its_name_its_calls_and_its_departure(app, profile) -> None:
    from cdmw.mcp.link import AiConnectionLink
    from tests.mcp_helpers import Bridge, initialize

    tools = [Tool(name="search.echo", family="search", description="Echo.", effect=READ, route="test", handler=_echo,
                  input_schema=object_schema({"text": {"type": "string"}, "fail": {"type": "boolean"}})),
             *app_tools()]
    server = McpServer(ToolTable(tools), _Context(), jobs=JobRegistry())
    model = AiActivityModel()
    model.attach(server.activity, log_path=server.audit.path)
    link = AiConnectionLink(server.serve_connection, on_refused=server.activity.refused)
    link.start()
    bridge = Bridge(profile)
    try:
        pump = app.processEvents
        initialize(bridge, pump=pump)
        bridge.send_request("tools/call", {"name": "search_echo", "arguments": {"text": "hello"}})
        bridge.read(pump=pump)
        for _ in range(3):
            bridge.send_request("tools/call", {"name": "search_echo", "arguments": {"fail": True}})
            bridge.read(pump=pump)
        _pump_until(app, lambda: len([r for r in model.rows if r.kind == "call"]) == 2)
        assert model.connected and model.client == "pytest-client"
        kinds = [(row.kind, row.client if row.kind != "call" else row.tool, row.count) for row in model.rows]
        assert kinds == [("connected", "pytest-client", 1), ("call", "search.echo", 1), ("call", "search.echo", 3)]
        assert model.rows[2].result_text() == "unavailable: Nothing is open."
        lines = server.audit.path.read_text(encoding="utf-8").splitlines()
        assert len(lines) == 4  # the file has every call; the tab collapses the repeats
    finally:
        bridge.close()
        _pump_until(app, lambda: not model.connected)
        link.stop()
        model.detach(server.activity)
        model.deleteLater()
    assert model.rows[-1].kind == "disconnected" and model.rows[-1].client == "pytest-client"


def test_dropped_events_still_leave_the_status_line_right(app) -> None:
    feed = ActivityFeed(capacity=3)
    model = AiActivityModel()
    feed.connected()
    feed.client_named("Codex")
    for index in range(10):  # the connect and name events fall out of the buffer
        feed.call({"tool": f"t{index}", "result": "ok"})
    model.attach(feed)
    _pump_until(app, lambda: model.rows)
    assert model.dropped == 9 and model.connected and model.client == "Codex"
    model.detach(feed)
    model.deleteLater()


@pytest.mark.skipif(os.name != "nt", reason="AI connections are Windows-only")
def test_the_app_controller_and_the_drawer_share_one_model(app, profile, tmp_path) -> None:
    from cdmw.mcp import approvals
    from cdmw.services.settings_service import create_settings
    from cdmw.ui.ai_connections import controller as controller_module
    from cdmw.ui.ai_connections.activity_model import ai_activity_model

    settings = create_settings(settings_file_path=tmp_path / "ai.cfg")
    host = QWidget()
    drawer = CompactActivityDrawer(ActivityHistory(parent=host), host)  # made before the controller, as the shell does
    controller = controller_module.install_ai_connections(None, settings)
    try:
        model = ai_activity_model()
        assert drawer.ai_connection_view.model is model is controller.activity
        assert not model.listening
        settings.setValue(approvals.ENABLED_KEY, True)
        controller.apply()
        assert model.listening
        drawer.ai_connection_view.refresh()
        assert drawer.ai_connection_view.status_label.text() == "Not connected. Waiting for an AI app to connect."
        rows_before = len(model.rows)
        controller.server.audit.record(client="c", tool="mesh.state", effect=READ, arguments={}, approval="no_prompt",
                                       result="ok", duration_s=0.0)
        _pump_until(app, lambda: len(model.rows) == rows_before + 1)
        assert model.rows[-1].tool == "mesh.state"
        assert model.log_path == controller.server.audit.path
        settings.setValue(approvals.ENABLED_KEY, False)
        controller.apply()
        assert not model.listening
    finally:
        feed = controller.server.activity
        controller_module.remove_ai_connections()
        app.processEvents()
        host.deleteLater()
    assert feed._waker is None  # detached: the old server no longer wakes the model
