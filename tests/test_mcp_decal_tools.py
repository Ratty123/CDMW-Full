"""MCP gap plan item 13: Edit Skinned Decal through typed tools."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import threading
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.core.skinned_decal import read_skinned_decal
from cdmw.models import ArchiveEntry
from cdmw.services.skinned_decal_service import DecalEditSource
from tests.mcp_rail_helpers import RailClient
from tests.test_skinned_decal import sequence_fixture


@pytest.fixture
def decal(tmp_path, monkeypatch):
    import cdmw.services.skinned_decal_service as service
    import cdmw.ui.archive_browser.workflow_dependencies as dependencies
    from cdmw.ui.archive_browser import skinned_decal_actions as wiring

    QApplication.instance() or QApplication([])
    entry = ArchiveEntry("character/decal.paseq", tmp_path / "0.pamt", tmp_path / "0.paz", 0, 64, 64, 0, 0)
    document = read_skinned_decal(sequence_fixture())
    monkeypatch.setattr(service, "load_decal_source", lambda e, **_kw: DecalEditSource(e, document))
    monkeypatch.setattr(dependencies, "archive_workflow_dependency_context",
                        lambda _owner, e: SimpleNamespace(selected_entry=e))

    class Browser(wiring.SkinnedDecalActionsMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = self
            self.settings_file_path = tmp_path / "settings.ini"
            self.status = []
            self.selected = entry

        def _current_archive_entry(self):
            return self.selected

        def _run_utility_task(self, *, task, on_complete=None, **_kw):
            on_complete(task(lambda _line: None, threading.Event()))

        _run_utility_task_when_idle = _run_utility_task

        def set_status_message(self, message, error=False):
            self.status.append((message, error))

    browser = Browser()
    client = RailClient(tmp_path, window=SimpleNamespace(archive=browser, shell=browser))
    yield client, browser, document
    browser.deleteLater()


def test_read_and_save_a_decal_through_the_dialog(decal, tmp_path) -> None:
    client, browser, document = decal
    settings = client.ok("files.decal_read")["settings"]
    opacity = next(row for row in settings if row["setting"].endswith("_opacity"))
    assert len(settings) == len(document.fields)

    target = tmp_path / "out" / "decal.paseq"
    target.parent.mkdir()
    saved = client.ok("files.decal_save", changes={opacity["setting"]: "0.25"}, save_file=str(target))
    assert saved["saved"] == str(target) and target.is_file()
    assert saved["changed"] == [opacity["setting"]]
    reread = read_skinned_decal(target.read_bytes())
    assert next(f for f in reread.fields if f.path == opacity["setting"]).text() == "0.25"
    assert browser.status[-1][0].startswith("Saved decal sequence copy")


def test_bad_values_unknown_settings_and_wrong_files_are_refused(decal, tmp_path) -> None:
    client, browser, _document = decal
    opacity = next(row for row in client.ok("files.decal_read")["settings"] if row["setting"].endswith("_opacity"))
    target = tmp_path / "decal.paseq"
    bad = client.call("files.decal_save", changes={opacity["setting"]: "NaN"}, save_file=str(target))
    assert bad["error"]["code"] == "invalid_arguments" and not target.exists()
    unknown = client.call("files.decal_save", changes={"[0].nothing": "1"}, save_file=str(target))
    assert unknown["error"]["code"] == "not_found"
    wrong = client.call("files.decal_save", changes={opacity["setting"]: "0.5"}, save_file=str(tmp_path / "d.bin"))
    assert wrong["error"]["code"] == "invalid_arguments"
    browser.selected = None
    assert client.call("files.decal_read")["error"]["code"] == "unavailable"
