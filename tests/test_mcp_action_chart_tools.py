"""MCP gap plan item 14: the Action Chart Editor through typed tools.

The chart is the owned fixture from tests/test_action_chart_binary.py; no game file is read.
"""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.core.action_chart_binary import decode_action_chart
from cdmw.models import ArchiveEntry
from tests.mcp_rail_helpers import RailClient
from tests.test_action_chart_binary import CLIPS, chart_bytes

PATH = "actionchart/bin__/upperaction/1_pc/1_phm/sword_upper.paac"


@pytest.fixture
def charts(tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import action_chart_actions as actions
    from cdmw.ui.archive_browser.action_chart_editor_dialog import ActionChartEditorDialog

    QApplication.instance() or QApplication([])
    monkeypatch.setattr(actions.QMessageBox, "information", lambda *args: None)
    entry = ArchiveEntry(PATH, tmp_path / "0.pamt", tmp_path / "0.paz", 0, 1, 1, 0, 0)
    written = []

    class Browser(actions.ArchiveActionChartActionsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = SimpleNamespace(settings_file_path=tmp_path / "settings.ini",
                                         set_status_message=lambda message, error=False: None)
            self._action_chart_editors = []
            self.selected = None

        def _current_archive_action_chart_entry(self):
            return self.selected

        def _open_current_archive_action_chart_editor(self):
            self.show_editor()

        def show_editor(self):
            def write(payload, plan, _log):
                folder = plan.parent / plan.title
                folder.mkdir()
                written.append((plan, payload))
                return folder

            dialog = ActionChartEditorDialog(
                chart_bytes(), virtual_path=PATH, parent=self,
                export_details=lambda payload: self._ask_action_chart_export(entry, payload),
                export_writer=write)
            self._action_chart_editors.append(dialog)
            dialog.show()
            return dialog

    browser = Browser()
    client = RailClient(tmp_path, window=SimpleNamespace(archive=browser, shell=browser.shell))
    yield client, browser, entry, written
    for dialog in browser._action_chart_editors:
        dialog._clear_pending()
        dialog._changes = type(dialog._changes)()
        dialog.close()
    browser.deleteLater()


def test_open_edit_apply_and_export_an_action_chart(charts, tmp_path) -> None:
    client, browser, entry, written = charts
    assert client.ok("files.action_chart_state") == {"open": False}
    assert client.call("files.action_chart_edit", action="open")["error"]["code"] == "unavailable"
    browser.selected = entry
    state = client.ok("files.action_chart_edit", action="open")
    assert state["open"] and state["path"] == PATH and len(state["animations"]) == 2

    detail = client.ok("files.action_chart_state", animation=0, table=6)
    assert any(row["field"] == "speed.rate" for row in detail["values"])
    assert [row["value"] for row in detail["names"]][1] == "RHand_Socket"

    client.ok("files.action_chart_edit", action="set_clip", animation=1, clip=CLIPS[0])
    client.ok("files.action_chart_edit", action="set_value", animation=0, field="speed.rate", value=1.5)
    client.ok("files.action_chart_edit", action="set_rate", value=1.25)
    pending = client.ok("files.action_chart_edit", action="replace", table=6, old="RHand_Socket", new="LHand_Socket")
    assert len(pending["pending"]) == 4 and pending["can_apply"]
    assert client.call("files.action_chart_edit", action="set_value", animation=0, field="nope",
                       value=1)["error"]["code"] == "not_found"

    # LHand_Socket is a name the game does not have; the editor's check refuses unless the AI says go ahead.
    refused = client.call("files.action_chart_edit", action="apply")
    assert refused["error"]["code"] == "refused"
    applied = client.ok("files.action_chart_edit", action="apply", apply_unknown_names=True)
    assert applied["pending"] == [] and applied["can_export"], applied["status"]
    assert any("Chart speed rate: 1 -> 1.25" in line for line in applied["changes"])

    mods = tmp_path / "mods"
    mods.mkdir()
    exported = client.ok("files.action_chart_export", folder=str(mods), title="Sword tweaks", author="Tester")
    assert exported["saved"] == str(mods / "Sword tweaks") and (mods / "Sword tweaks").is_dir()
    plan, payload = written[0]
    assert plan.title == "Sword tweaks" and plan.author == "Tester" and not plan.sent
    chart = decode_action_chart(payload.data, virtual_path=PATH)
    assert chart.clip_name(chart.animations[1]) == CLIPS[0]


def test_export_needs_applied_edits_and_a_name(charts, tmp_path) -> None:
    client, browser, entry, _written = charts
    browser.selected = entry
    client.ok("files.action_chart_edit", action="open")
    mods = tmp_path / "mods"
    mods.mkdir()
    assert client.call("files.action_chart_export", folder=str(mods))["error"]["code"] == "unavailable"
    client.ok("files.action_chart_edit", action="set_rate", value=2.0)
    client.ok("files.action_chart_edit", action="apply")
    assert client.call("files.action_chart_export", folder=str(mods), title="  ")["error"]["code"] in (
        "invalid_arguments", "failed")
    assert not any(mods.iterdir())
    assert client.ok("files.action_chart_edit", action="reset")["changes"] == ["No changes yet."]
