"""MCP gap plan item 13: the Prefab Inspector's path edits through typed tools. Owned fixture prefab."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox, QWidget

from cdmw.core.prefab_binary import decode_prefab_binary
from cdmw.models import ArchiveEntry
from tests.mcp_rail_helpers import RailClient
from tests.test_prefab_inspector_dialog import PATH as MESH, _build

PREFAB = "character/model/test/owned.prefab"


@pytest.fixture
def prefab(tmp_path, monkeypatch):
    from cdmw.ui.archive_browser import prefab_inspector_actions as actions
    from cdmw.ui.archive_browser.mod_ready_export import ArchiveModReadyExportMixin
    from cdmw.ui.archive_browser.prefab_json_actions import ArchivePrefabJsonActionsMixin

    QApplication.instance() or QApplication([])
    data = _build()
    entry = ArchiveEntry(PREFAB, tmp_path / "0.pamt", tmp_path / "0.paz", 0, len(data), len(data), 0, 0)
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

        def _run_utility_task_when_idle(self, *, task, on_complete=None, **_kw):
            on_complete(task(lambda _line: None))

    class Browser(actions.ArchivePrefabInspectorActionsMixin, ArchivePrefabJsonActionsMixin,
                  ArchiveModReadyExportMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = Shell()
            self.selected = entry
            self.archive_preview_showing_loose = False
            self.archive_entries_by_extension = {}
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


def test_read_rows_and_save_a_longer_mesh_path(prefab) -> None:
    client, _browser, exported, mods = prefab
    read = client.ok("files.prefab_read")
    assert "Fully read" in read["banner"]
    mesh = next(row for row in read["rows"] if row["value"] == MESH)
    assert mesh["can_change"] and mesh["field"] == "Mesh file"

    replacement = "character/model/1_pc/weapon/a_much_longer_sword_name.pac"
    saved = client.ok("files.prefab_save", folder=str(mods), title="Longer sword", accept_warnings=True,
                      changes=[{"row": mesh["row"], "new": replacement}])
    assert saved["saved"] == [str(mods / "Longer sword")] and "1 path change" in saved["summary"]
    document = decode_prefab_binary(exported[-1][0])
    assert [item.text for item in document.resource_strings()] == [replacement]


def test_bad_rows_and_unread_warnings_are_refused(prefab) -> None:
    client, browser, exported, mods = prefab
    read = client.ok("files.prefab_read")
    mesh = next(row for row in read["rows"] if row["value"] == MESH)
    assert client.call("files.prefab_save", folder=str(mods),
                       changes=[{"row": "9.9", "new": "x/y.pac"}])["error"]["code"] == "not_found"
    # A path that does not look like a file is a review warning, which blocks without accept_warnings.
    warned = client.call("files.prefab_save", folder=str(mods), changes=[{"row": mesh["row"], "new": "not a path"}])
    assert warned["error"]["code"] == "refused"
    assert exported == [] and not any(mods.iterdir())
    browser.selected = None
    assert client.call("files.prefab_read")["error"]["code"] == "unavailable"
