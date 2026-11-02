"""The Archive Browser audio actions write a .wem and the banks that play it as one loose mod."""
from __future__ import annotations

import io
import os
import struct
import wave
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QWidget

from cdmw.core.archive_wwise_bank import read_embedded_media
from cdmw.core.archive_wwise_hirc import read_hirc_graph
from cdmw.models import ArchiveEntry
from cdmw.ui.archive_browser import patch_actions
from tests.test_archive_wwise_hirc import EMBEDDED_A, bank, sound, wem

PCM = 0x00010001


class _Shell:
    settings_file_path = Path("settings.json")

    def __init__(self) -> None:
        self.statuses: list[str] = []

    def set_status_message(self, message: str, error: bool = False) -> None:
        self.statuses.append(message)

    def _run_utility_task(self, *, status_message, task, on_complete, show_archive_progress, task_accepts_cancel=False):
        def log(_message: str) -> None:
            pass

        on_complete(task(log, None) if task_accepts_cancel else task(log))


class _Browser(patch_actions.ArchivePatchActionsMixin, QWidget):
    def __init__(self, entries) -> None:
        super().__init__()
        self.shell = _Shell()
        self.archive_entries = entries

    def _collect_archive_mod_ready_export_target(self, **_kwargs):
        return Path("parent"), object(), False, False, object()


def _tone(path: Path, rate: int = 48000, frames: int = 480) -> Path:
    data = io.BytesIO()
    with wave.open(data, "wb") as audio:
        audio.setparams((1, 2, rate, 0, "NONE", "not compressed"))
        audio.writeframes(b"\x01\x00" * frames)
    path.write_bytes(data.getvalue())
    return path


@pytest.fixture
def archive(tmp_path, monkeypatch):
    QApplication.instance() or QApplication([])
    loose = wem(b"\x07" * 300, rate=48000)
    files = {
        "sound/windows/media/7000.wem": loose,
        "sound/windows/one.bnk": bank([sound(1, 7000, len(loose))]),
        "sound/windows/two.bnk": bank([sound(2, 9001, len(EMBEDDED_A))], media=[(9001, EMBEDDED_A)]),
        "sound/windows/other.bnk": bank([sound(3, 42, 10)]),
    }
    entries = tuple(ArchiveEntry(path, tmp_path / "x.pamt", tmp_path / "x.paz", 0, len(data), len(data), 0, 0) for path, data in files.items())
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", lambda entry, *_a, **_k: (files[entry.path], False, ""))
    exported: list = []

    def fake_export(requests, **kwargs):
        exported.append([(request.entry.path, request.payload_data) for request in requests])
        return patch_actions.ArchiveLooseExportResult(Path("pkg"), [])

    monkeypatch.setattr(patch_actions, "export_archive_payloads_to_mod_ready_loose", fake_export)
    messages: list[str] = []
    monkeypatch.setattr(patch_actions.QMessageBox, "information", lambda _parent, _title, text: messages.append(text))
    return entries, exported, messages


def test_importing_audio_onto_a_numeric_wem_also_writes_the_banks_that_play_it(archive, tmp_path, monkeypatch):
    entries, exported, messages = archive
    replacement = _tone(tmp_path / "new.wav")
    monkeypatch.setattr(patch_actions.QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(replacement), ""))
    browser = _Browser(entries)
    browser._start_archive_audio_patch(entries[0])

    assert [path for path, _data in exported[0]] == ["sound/windows/media/7000.wem", "sound/windows/one.bnk"]
    media = exported[0][0][1]
    source = read_hirc_graph(exported[0][1][1]).by_id()[1].source
    assert (source.plugin_id, source.in_memory_size) == (PCM, len(media))
    assert "switched to Wwise's built-in PCM codec" in messages[-1]


def test_replacing_a_banks_embedded_sound_lists_its_media_off_the_ui_thread(archive, tmp_path, monkeypatch):
    entries, exported, _messages = archive
    replacement = wem(b"\x55" * 90)
    (tmp_path / "new.wem").write_bytes(replacement)
    monkeypatch.setattr(patch_actions.QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(tmp_path / "new.wem"), ""))
    offered: list = []

    def choose(_parent, _title, _label, items, *_args):
        offered.extend(items)
        return items[0], True

    monkeypatch.setattr(patch_actions.QInputDialog, "getItem", choose)
    browser = _Browser(entries)
    browser._start_archive_bank_media_replace(entries[2])

    assert offered == [f"1: 9001 ({len(EMBEDDED_A):,} bytes)"]
    assert [path for path, _data in exported[0]] == ["sound/windows/two.bnk"]
    rebuilt = exported[0][0][1]
    assert read_embedded_media(rebuilt)[0].size == len(replacement)
    assert read_hirc_graph(rebuilt).by_id()[2].source.in_memory_size == len(replacement)


def test_sound_bank_editor_collects_value_property_and_variation_changes(monkeypatch, tmp_path):
    QApplication.instance() or QApplication([])
    from cdmw.core.archive_wwise_bank_plan import build_sound_bank_editor_model
    from cdmw.ui.archive_browser import sound_bank_editor
    from tests.test_archive_wwise_hirc import EMBEDDED_B, random_container

    data = bank(
        [sound(101, 9001, len(EMBEDDED_A), properties=[(0x00, -4.0)]), sound(102, 9002, len(EMBEDDED_B)), random_container(200, [101, 102])],
        media=[(9001, EMBEDDED_A), (9002, EMBEDDED_B)],
    )
    dialog = sound_bank_editor.SoundBankEditorDialog(None, "x.bnk", build_sound_bank_editor_model(data))
    row = next(i for i, item in enumerate(dialog.model.rows) if (item.object_id, item.target) == (101, "property:Volume"))
    dialog.table.item(row, 4).setText("-2.5")
    dialog.object_combo.setCurrentIndex(dialog.object_combo.findData(102))
    dialog.property_combo.setCurrentIndex(dialog.property_combo.findData("property:Pitch"))
    dialog.value_edit.setText("150")
    dialog._add_property()
    dialog.object_combo.setCurrentIndex(dialog.object_combo.findData(200))
    assert dialog.add_variation_button.isEnabled() and dialog.remove_variation_button.isEnabled()
    monkeypatch.setattr(sound_bank_editor.QInputDialog, "getItem", lambda *_a, **_k: ("102", True))
    monkeypatch.setattr(sound_bank_editor.QFileDialog, "getOpenFileName", lambda *_a, **_k: (str(tmp_path / "a.wav"), ""))
    dialog._add_variation()
    dialog._remove_variation()
    plan = dialog.plan()
    assert [(edit.object_id, edit.target, edit.value) for edit in plan.values] == [(101, "property:Volume", -2.5)]
    assert [(c.object_id, c.target, c.value) for c in plan.properties] == [(102, "property:Pitch", 150)]
    assert plan.removed_variations == ((200, 102),)
    assert [(r.container_id, r.template_sound_id, r.audio_path.name) for r in plan.added_variations] == [(200, 102, "a.wav")]
    assert dialog.pending_list.count() == 3


def test_editing_a_sound_bank_writes_the_edited_bank_as_a_loose_mod(archive, monkeypatch):
    from cdmw.services.archive_workflow_service import HircPropertyChange, SoundBankEditPlan

    entries, exported, messages = archive
    seen_models = []

    class _Dialog:
        DialogCode = type("DialogCode", (), {"Accepted": 1})

        def __init__(self, _parent, _title, model):
            seen_models.append(model)

        def exec(self):
            return self.DialogCode.Accepted

        def plan(self):
            return SoundBankEditPlan(properties=(HircPropertyChange(1, "property:Volume", -6.0),))

    monkeypatch.setattr(patch_actions, "SoundBankEditorDialog", _Dialog)
    _Browser(entries)._start_archive_sound_bank_edit(entries[1])
    assert [obj.object_id for obj in seen_models[0].objects] == [1]
    assert [path for path, _data in exported[0]] == ["sound/windows/one.bnk"]
    assert read_hirc_graph(exported[0][0][1]).by_id()[1].property(0x00).as_float == -6.0
    assert "1 change(s) written to one.bnk" in messages[-1]


def test_audio_payload_paths_keep_their_folders():
    from cdmw.domain.packages.layout import normalize_mod_package_payload_path

    assert normalize_mod_package_payload_path("sound/windows/1355168291.bnk").as_posix() == "sound/windows/1355168291.bnk"
    assert normalize_mod_package_payload_path("soundcommon/windows/1355168291.bnk").as_posix() == "soundcommon/windows/1355168291.bnk"
    assert normalize_mod_package_payload_path("0012/sound/windows/media/1.wem").as_posix() == "sound/windows/media/1.wem"
    assert normalize_mod_package_payload_path("MyMod/files/sequencer/a.paseq").as_posix() == "sequencer/a.paseq"



def _vorbis(seconds: float, rate: int = 48000) -> bytes:
    fmt = bytearray(struct.pack("<HHIIHH", 0xFFFF, 1, rate, 0, 0, 0) + b"\x00" * 0x32)
    struct.pack_into("<I", fmt, 0x18, int(seconds * rate))
    struct.pack_into("<II", fmt, 0x28, 0, 8)
    data = b"\x00" * 8 + b"".join(struct.pack("<H", 20) + b"\x05" * 20 for _ in range(10))
    body = b"WAVE" + b"fmt " + struct.pack("<I", len(fmt)) + bytes(fmt) + b"data" + struct.pack("<I", len(data)) + data
    return b"RIFF" + struct.pack("<I", len(body)) + body


def test_shadowed_bank_copies_use_the_one_the_game_loads(tmp_path, monkeypatch):
    from cdmw.core.archive_audio import plan_wwise_media_replacement

    base = ArchiveEntry("sound/windows/one.bnk", tmp_path / "0004" / "0.pamt", tmp_path / "a.paz", 0, 1, 1, 0, 0)
    newer = ArchiveEntry("sound/windows/one.bnk", tmp_path / "0036" / "0.pamt", tmp_path / "b.paz", 0, 1, 1, 0, 0)
    target = ArchiveEntry("sound/windows/media/7000.wem", tmp_path / "0004" / "0.pamt", tmp_path / "a.paz", 0, 1, 1, 0, 0)
    original = wem(b"\x07" * 300)
    stale = bank([sound(1, 7000, len(original))])
    current = bank([sound(1, 7000, len(original), properties=[(0x00, -2.0)])])
    contents = {id(base): stale, id(newer): current, id(target): original}
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", lambda entry, *_a, **_k: (contents[id(entry)], False, ""))
    replacement = tmp_path / "new.wem"
    replacement.write_bytes(wem(b"\x09" * 50))
    plan = plan_wwise_media_replacement(target, replacement, 7000, [base, newer, target])
    banks = [(entry, data) for entry, data in plan.payloads if entry.extension == ".bnk"]
    assert [entry.pamt_path.parent.name for entry, _data in banks] == ["0036"]
    assert read_hirc_graph(banks[0][1]).by_id()[1].property(0x00).as_float == -2.0


def test_music_tracks_warn_when_the_replacement_changes_length():
    from cdmw.core.archive_audio import build_wwise_media_replacement
    from tests.test_archive_wwise_hirc import music_track

    original = _vorbis(10.0)
    data = bank([music_track(5, 7000, len(original))])
    entry = ArchiveEntry("sound/windows/music.bnk", None, None, 0, 1, 1, 0, 0)
    for seconds, wording in ((4.0, "followed by silence"), (25.0, "is cut off")):
        result = build_wwise_media_replacement(7000, _vorbis(seconds), original_media=original, wem_entries=[],
                                               bank_entries=[entry], read_entry=lambda _entry: data)
        assert any("music track" in note and wording in note and "10.00 s" in note for note in result.notes)
    same = build_wwise_media_replacement(7000, _vorbis(10.0), original_media=original, wem_entries=[],
                                         bank_entries=[entry], read_entry=lambda _entry: data)
    assert not any("music track" in note for note in same.notes)


def test_named_voice_lines_need_a_wem_in_the_original_codec(tmp_path, monkeypatch):
    from cdmw.core.archive_audio import build_archive_audio_patch_payload

    line = ArchiveEntry("sound/windows/english(us)/unique_line_00001.wem", tmp_path / "0.pamt", tmp_path / "a.paz", 0, 1, 1, 0, 0)
    original = wem(b"\x01" * 40)
    monkeypatch.setattr("cdmw.core.archive_extraction.read_archive_entry_data", lambda *_a, **_k: (original, False, ""))
    with pytest.raises(ValueError, match="chosen by name"):
        build_archive_audio_patch_payload(line, _tone(tmp_path / "new.wav"))
    pcm = tmp_path / "pcm.wem"
    pcm.write_bytes(wem(b"\x02" * 40, tag=0x0001))
    with pytest.raises(ValueError, match="different codec"):
        build_archive_audio_patch_payload(line, pcm)
    vorbis = tmp_path / "vorbis.wem"
    vorbis.write_bytes(wem(b"\x03" * 40))
    assert build_archive_audio_patch_payload(line, vorbis) == vorbis.read_bytes()


def test_a_bank_whose_undecoded_object_names_the_media_refuses_instead_of_being_skipped():
    from cdmw.core.archive_audio import build_wwise_media_replacement
    from cdmw.core.archive_wwise_bank_edit import WwiseBankEditError
    from tests.test_archive_wwise_hirc import hirc_object

    data = bank([hirc_object(23, 600, struct.pack("<I", 7000))])
    entry = ArchiveEntry("sound/windows/odd.bnk", None, None, 0, 1, 1, 0, 0)
    with pytest.raises(WwiseBankEditError, match=r"odd\.bnk: 1 object\(s\) this reader does not decode"):
        build_wwise_media_replacement(7000, wem(b"\x00" * 8), original_media=wem(b"\x00" * 8), wem_entries=[],
                                      bank_entries=[entry], read_entry=lambda _entry: data)


def test_sound_bank_editor_filter_hides_rows_without_rebuilding_the_table():
    QApplication.instance() or QApplication([])
    from cdmw.core.archive_wwise_bank_plan import build_sound_bank_editor_model
    from cdmw.ui.archive_browser import sound_bank_editor

    data = bank([sound(101, 9001, len(EMBEDDED_A), properties=[(0x00, -4.0)]), sound(102, 9002, 10, properties=[(0x01, 5.0)])],
                media=[(9001, EMBEDDED_A)])
    dialog = sound_bank_editor.SoundBankEditorDialog(None, "x.bnk", build_sound_bank_editor_model(data))
    dialog._apply_filter("pitch")
    visible = [dialog.table.item(row, 2).text() for row in range(dialog.table.rowCount()) if not dialog.table.isRowHidden(row)]
    assert visible == ["property:Pitch"]
    dialog._apply_filter("")
    assert not any(dialog.table.isRowHidden(row) for row in range(dialog.table.rowCount()))
