"""MCP gap plan item 14: Edit Sound Bank and Import WAV through typed tools."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication, QCheckBox, QLineEdit, QMessageBox, QWidget

from cdmw.core.archive_wwise_hirc import read_hirc_graph
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser import patch_actions
from cdmw.ui.archive_browser.mod_ready_export import ArchiveModReadyExportMixin
from tests.mcp_rail_helpers import RailClient
from tests.test_archive_audio_loose_mod_actions import _tone
from tests.test_archive_wwise_hirc import EMBEDDED_A, EMBEDDED_B, bank, random_container, sound, wem


@pytest.fixture
def sounds(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    loose = wem(b"\x07" * 300, rate=48000)
    files = {
        "sound/windows/media/7000.wem": loose,
        "sound/windows/one.bnk": bank([sound(1, 7000, len(loose))]),
        "sound/windows/two.bnk": bank(
            [sound(101, 9001, len(EMBEDDED_A), properties=[(0x00, -4.0)]), sound(102, 9002, len(EMBEDDED_B)),
             random_container(200, [101, 102])],
            media=[(9001, EMBEDDED_A), (9002, EMBEDDED_B)]),
    }
    entries = tuple(ArchiveEntry(path, tmp_path / "x.pamt", tmp_path / "x.paz", 0, len(data), len(data), 0, 0)
                    for path, data in files.items())
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data",
                        lambda entry, *_a, **_k: (files[entry.path], False, ""))
    exported = []

    def export(requests, *, parent_root, package_info, **_kwargs):
        package = Path(parent_root) / package_info.title
        package.mkdir(parents=True)
        exported.append({"root": package, "info": package_info,
                         "files": [(request.entry.path, request.payload_data) for request in requests]})
        return patch_actions.ArchiveLooseExportResult(package, [])

    monkeypatch.setattr(patch_actions, "export_archive_payloads_to_mod_ready_loose", export)
    monkeypatch.setattr(QMessageBox, "information", lambda *args: None)

    class Shell:
        def __init__(self):
            self.status = []
            self.settings_file_path = tmp_path / "settings" / "cdmw.ini"

        def set_status_message(self, message, error=False):
            self.status.append((message, error))

        def schedule_settings_save(self):
            pass

        def _run_utility_task(self, *, task, on_complete=None, task_accepts_cancel=False, **_kw):
            on_complete(task(lambda _line: None, None) if task_accepts_cancel else task(lambda _line: None))

    class Browser(patch_actions.ArchivePatchActionsMixin, ArchiveModReadyExportMixin, QWidget):
        def __init__(self):
            super().__init__()
            self.shell = Shell()
            self.archive_entries = entries
            self.selected = entries[2]
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
    yield client, browser, entries, exported, mods
    browser.deleteLater()


def test_read_and_write_a_sound_bank_as_a_mod(sounds) -> None:
    client, _browser, _entries, exported, mods = sounds
    read = client.ok("files.sound_bank_read")
    assert read["path"] == "sound/windows/two.bnk"
    volume = next(row for row in read["values"] if (row["object"], row["value"]) == (101, "property:Volume"))
    assert volume["stored"] == -4.0
    container = next(obj for obj in read["objects"] if obj["object"] == 200)
    assert container["random_container"] and container["sounds"] == [101, 102]
    assert client.ok("files.sound_bank_read", query="no-such-value")["values"] == []

    written = client.ok("files.sound_bank_write", folder=str(mods), title="Quieter",
                        values=[{"object": 101, "value": "property:Volume", "new": -2.5}],
                        add=[{"object": 102, "property": "Pitch", "new": 150}])
    assert written["saved"] == [str(mods / "Quieter")]
    assert exported[-1]["info"].title == "Quieter"
    path, data = exported[-1]["files"][0]
    assert path == "sound/windows/two.bnk"
    by_id = read_hirc_graph(data).by_id()
    assert by_id[101].property(0x00).as_float == -2.5


def test_bad_sound_bank_changes_are_refused_before_the_editor(sounds) -> None:
    client, browser, entries, exported, mods = sounds
    assert client.call("files.sound_bank_write", folder=str(mods))["error"]["code"] == "invalid_arguments"
    unknown = client.call("files.sound_bank_write", folder=str(mods),
                          values=[{"object": 999, "value": "property:Volume", "new": 1}])
    assert unknown["error"]["code"] == "not_found"
    word = client.call("files.sound_bank_write", folder=str(mods),
                       values=[{"object": 101, "value": "property:Volume", "new": "loud"}])
    assert word["error"]["code"] == "invalid_arguments"
    cannot = client.call("files.sound_bank_write", folder=str(mods),
                         add=[{"object": 101, "property": "NoSuchProperty", "new": 1}])
    assert cannot["error"]["code"] == "not_found"
    assert exported == []
    browser.selected = entries[0]
    assert client.call("files.sound_bank_read")["error"]["code"] == "unavailable"


def test_import_wav_as_a_loose_mod(sounds, tmp_path) -> None:
    client, browser, entries, exported, mods = sounds
    browser.selected = entries[0]
    tone = _tone(tmp_path / "new.wav")
    written = client.ok("files.audio_import", source=str(tone), folder=str(mods), title="New hit")
    assert written["saved"] == [str(mods / "New hit")]
    assert [path for path, _data in exported[-1]["files"]] == ["sound/windows/media/7000.wem",
                                                              "sound/windows/one.bnk"]
    assert client.call("files.audio_import", source=str(tmp_path / "missing.wav"),
                       folder=str(mods))["error"]["code"] == "not_found"
