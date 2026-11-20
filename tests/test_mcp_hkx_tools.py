"""MCP gap plan item 14: the HKX Physics Editor through typed tools."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.core.archive_hkx_joint_limits import HINGE_CLASS
from cdmw.models import ArchiveEntry
from cdmw.services.hkx_physics_editor_service import load_hkx_physics_session
from tests.hkx_tagfile_fixtures import build_physics_fixture
from tests.mcp_rail_helpers import RailClient


@pytest.fixture
def hkx(tmp_path):
    from cdmw.ui.archive_browser.hkx_physics_editor_actions import ArchiveHkxPhysicsEditorMixin

    QApplication.instance() or QApplication([])
    data = build_physics_fixture()
    entry = ArchiveEntry("character/bin__/havokphysics/x.hkx", tmp_path / "0.pamt", tmp_path / "0.paz", 0,
                         len(data), len(data), 0, 0)

    class Shell:
        def __init__(self):
            self.status = []

        def set_status_message(self, message, error=False):
            self.status.append((message, error))

        def _run_utility_task(self, *, task, on_complete=None, **_kw):
            on_complete(task(lambda _line: None, threading.Event()))

    class Browser(ArchiveHkxPhysicsEditorMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = Shell()
            self.selected = entry

        def _current_archive_hkx_entry(self):
            return self.selected

        def _read_hkx_entry_bytes(self, _entry, _stop_event):
            return data

    browser = Browser()
    client = RailClient(tmp_path, window=SimpleNamespace(archive=browser, shell=browser.shell))
    yield client, browser, data
    dialog = getattr(browser, "_hkx_physics_editor_dialog", None)
    if dialog is not None:
        dialog.close()
    browser.deleteLater()


def test_open_change_and_save_an_hkx_file(hkx, tmp_path) -> None:
    client, browser, data = hkx
    assert client.ok("files.hkx_state") == {"open": False}
    state = client.ok("files.hkx_edit", action="open")
    assert state["open"] and state["changes"] == 0
    session = browser._hkx_physics_editor_dialog.session
    hinge = next(joint for joint in session.joints if joint.class_name == HINGE_CLASS)

    changed = client.ok("files.hkx_edit", action="set_joint", joint=hinge.index, field="bend_max", value=165.0)
    assert changed["changes"] == 1
    row = next(j for j in changed["joints"] if j["joint"] == hinge.index)
    assert next(f for f in row["fields"] if f["field"] == "bend_max")["value"] == 165.0
    assert client.ok("files.hkx_edit", action="scale_stiffness", factor=2.0)["changes"] == 3

    too_far = client.call("files.hkx_edit", action="set_joint", joint=hinge.index, field="bend_max", value=1e6)
    assert too_far["error"]["code"] == "invalid_arguments"
    assert client.call("files.hkx_edit", action="set_joint", joint=999, field="bend_max", value=1.0)["error"][
        "code"] == "not_found"

    target = tmp_path / "out.hkx"
    saved = client.ok("files.hkx_save", save_file=str(target))
    assert saved["saved"] == str(target) and target.read_bytes() != data
    reopened = load_hkx_physics_session(target.read_bytes(), session.path)
    hinge_after = next(joint for joint in reopened.joints if joint.class_name == HINGE_CLASS)
    assert next(f for f in hinge_after.fields if f.key == "bend_max").value == pytest.approx(165.0)

    assert client.ok("files.hkx_edit", action="reset_all")["changes"] == 0


def test_an_inverted_range_is_refused_before_saving(hkx, tmp_path) -> None:
    client, browser, _data = hkx
    client.ok("files.hkx_edit", action="open")
    session = browser._hkx_physics_editor_dialog.session
    hinge = next(joint for joint in session.joints if joint.class_name == HINGE_CLASS)
    low = next(f for f in hinge.fields if f.key == "bend_min")
    high = next(f for f in hinge.fields if f.key == "bend_max")
    client.ok("files.hkx_edit", action="set_joint", joint=hinge.index, field="bend_min",
              value=min(low.maximum, high.value + 5))
    refused = client.call("files.hkx_save", save_file=str(tmp_path / "bad.hkx"))
    assert refused["error"]["code"] == "refused" and not (tmp_path / "bad.hkx").exists()


def test_renames_and_a_missing_selection(hkx) -> None:
    client, browser, _data = hkx
    state = client.ok("files.hkx_edit", action="open")
    name = state["names"][0]
    renamed = client.ok("files.hkx_edit", action="rename", name=name["name"], text="Ragdoll_Bip01 Hips")
    assert renamed["names"][0]["new_text"] == "Ragdoll_Bip01 Hips" and renamed["changes"] == 1
    browser._hkx_physics_editor_dialog.close()
    browser.selected = None
    assert client.call("files.hkx_edit", action="open")["error"]["code"] == "unavailable"
