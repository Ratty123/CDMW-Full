"""MCP gap plan item 13: Add Bones through typed tools. The skeleton is an owned fixture."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox, QWidget

from cdmw.modding.skeleton_writer import read_pab_document
from cdmw.models import ArchiveEntry
from tests.mcp_rail_helpers import RailClient
from tests.test_pab_skeleton_writer import pab

PATH = "character/model/test/owned.pab"


@pytest.fixture
def skeleton(tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import pab_json_actions as actions
    from cdmw.ui.archive_browser.mod_ready_export import ArchiveModReadyExportMixin

    QApplication.instance() or QApplication([])
    data = pab()
    entry = ArchiveEntry(PATH, tmp_path / "0.pamt", tmp_path / "0.paz", 0, len(data), len(data), 0, 0)
    monkeypatch.setattr("cdmw.services.archive_read_service.read_archive_entry_data",
                        lambda _entry, *_a, **_k: (data, False, ""))
    exported = []

    def export(requests, *, parent_root, package_info, **_kwargs):
        package = Path(parent_root) / package_info.title
        package.mkdir(parents=True)
        exported.append([request.payload_data for request in requests])
        return actions.ArchiveLooseExportResult(package, [])

    monkeypatch.setattr(actions, "export_archive_payloads_to_mod_ready_loose", export)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

    class Shell:
        settings_file_path = tmp_path / "settings" / "cdmw.ini"

        def set_status_message(self, message, error=False):
            pass

        def schedule_settings_save(self):
            pass

        def _run_utility_task(self, *, task, on_complete=None, **_kw):
            on_complete(task(lambda _line: None))

    class Browser(actions.ArchivePabJsonActionsMixin, ArchiveModReadyExportMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = Shell()
            self.selected = entry
            self.archive_preview_showing_loose = False
            fields = ("export_root", "package_title", "package_version", "package_author", "package_description")
            self.textures = SimpleNamespace(collect_config=lambda: SimpleNamespace(mod_ready_export_root=""),
                                            mod_ready_create_no_encrypt_checkbox=QCheckBox(),
                                            mod_ready_profile_checkboxes={},
                                            **{f"mod_ready_{field}_edit": QLineEdit() for field in fields})

        def _current_archive_entry(self):
            return self.selected

    browser = Browser()
    client = RailClient(tmp_path, window=SimpleNamespace(archive=browser, shell=browser.shell))
    mods = tmp_path / "mods"
    mods.mkdir()
    yield client, browser, exported, mods
    browser.deleteLater()


def test_read_bones_and_add_a_tail(skeleton) -> None:
    client, _browser, exported, mods = skeleton
    read = client.ok("files.skeleton_read")
    assert [bone["name"] for bone in read["bones"]] == ["Bip01", "Bip01 Spine", "Bip01 Head"]
    assert read["bones"][2]["parent"] == "Bip01 Spine"

    written = client.ok("files.skeleton_add_bones", folder=str(mods), title="Tail",
                        bones=[{"parent": "Bip01 Head", "name": "Tail_00", "position": [0, 0.1, 0]},
                               {"parent": "Tail_00", "name": "Tail_01", "angles": [0, 0, 30]}])
    assert written["saved"] == [str(mods / "Tail")] and written["added"] == ["Tail_00", "Tail_01"]
    document = read_pab_document(exported[-1][0])
    assert [bone.name for bone in document.bones][-2:] == ["Tail_00", "Tail_01"]


def test_bad_bones_are_refused_and_nothing_is_written(skeleton) -> None:
    client, browser, exported, mods = skeleton
    missing = client.call("files.skeleton_add_bones", folder=str(mods),
                          bones=[{"parent": "No Such Bone", "name": "Tail_00"}])
    assert missing["error"]["code"] == "refused"
    clash = client.call("files.skeleton_add_bones", folder=str(mods),
                        bones=[{"parent": "Bip01", "name": "Bip01 Head"}])
    assert clash["error"]["code"] == "refused"
    assert exported == [] and not any(mods.iterdir())
    browser.selected = None
    assert client.call("files.skeleton_read")["error"]["code"] == "unavailable"
