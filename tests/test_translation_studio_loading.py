"""Configured archive paths and loose language files through the real panel workers."""

import os
import threading
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import QSettings, QTimer, Qt
from PySide6.QtWidgets import QApplication, QLineEdit, QMessageBox

from cdmw.core.paloc_format import encode_paloc, parse_paloc
from tests.test_translation_studio import ENGLISH, KOREAN
from tools.translation_studio import tab as module
from tools.translation_studio.catalogue import load_catalogue


def until(predicate):
    app = QApplication.instance()
    deadline = time.monotonic() + 4
    while time.monotonic() < deadline:
        app.processEvents()
        if predicate():
            return
        time.sleep(0.001)
    assert predicate(), "Timed out waiting for Translation Studio"


@pytest.fixture
def panel(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    settings = QSettings(str(tmp_path / "settings.ini"), QSettings.IniFormat)
    # An explicitly empty live field must override this saved value.
    settings.setValue("archive/package_root", "saved-installation")
    edit = QLineEdit()
    window = SimpleNamespace(archive=SimpleNamespace(archive_package_root_edit=edit))
    widget = module.TranslationStudioTab(settings=settings, window=window)
    yield widget, edit, settings
    widget.request_shutdown()
    until(lambda: not widget.iter_shutdown_workers() and not module._LIVE_THREADS)
    widget.close()
    widget.deleteLater()
    edit.deleteLater()
    app.processEvents()


def test_live_and_saved_paths_use_the_current_app_contract(panel, monkeypatch):
    tab, edit, settings = panel
    scans = []
    main_thread = threading.get_ident()

    def languages(root, **kwargs):
        scans.append((str(root), threading.get_ident()))
        return ("eng", "kor")

    monkeypatch.setattr(module, "available_languages", languages)
    assert tab._game_root() == ""
    assert tab.open_file_button.isEnabled()
    assert not tab.load_button.isEnabled()
    assert not tab.iter_shutdown_workers()
    edit.setText(r"D:\SteamLibrary\Crimson Desert")
    until(lambda: tab.language_box.count() == 2 and not tab.iter_shutdown_workers())
    assert scans == [(edit.text(), scans[0][1])]
    assert scans[0][1] != main_thread
    assert edit.text() in tab.archive_label.text()
    # Reloading replaces the list, rather than appending duplicate languages.
    tab.refresh_button.click()
    until(lambda: len(scans) == 2 and not tab.iter_shutdown_workers())
    assert tab.language_box.count() == 2
    tab._window = None
    settings.setValue("archive_package_root", "stale-legacy-installation")
    assert tab._game_root() == "saved-installation"


def test_path_change_cancels_old_scan_and_queues_only_the_latest_root(panel, monkeypatch):
    tab, edit, _settings = panel
    started, release = threading.Event(), threading.Event()
    scans = []

    def languages(root, **kwargs):
        scans.append(str(root))
        if str(root) == "old-installation":
            started.set()
            release.wait(3)
            return ("eng",)
        return ("kor",)

    monkeypatch.setattr(module, "available_languages", languages)
    edit.setText("old-installation")
    until(started.is_set)
    first = tab._language_thread
    try:
        edit.setText("intermediate-installation")
        edit.setText("new-installation")
        until(lambda: not tab._refresh_timer.isActive())
        assert scans == ["old-installation"]
        assert first.isInterruptionRequested()
        assert tab.language_box.count() == 0
    finally:
        release.set()
    until(lambda: tab.language_box.count() == 1 and not tab.iter_shutdown_workers())
    assert scans == ["old-installation", "new-installation"]
    assert tab.language_box.currentText() == "kor"
    assert "new-installation" in tab.archive_label.text()
    edit.clear()
    until(lambda: not tab._refresh_timer.isActive())
    assert tab.language_box.count() == 0
    assert not tab.load_button.isEnabled()
    assert len(scans) == 2


def test_archive_load_uses_the_same_root_and_rejects_results_after_path_changes(panel, monkeypatch):
    tab, edit, _settings = panel
    monkeypatch.setattr(module, "available_languages", lambda root, **kwargs: ("eng",))
    edit.setText("first-installation")
    until(lambda: tab.language_box.count() == 1 and not tab.iter_shutdown_workers())
    original = load_catalogue(KOREAN, "kor")
    tab._on_loaded(original, "")
    started, release = threading.Event(), threading.Event()
    reads = []

    def read(language, root, **kwargs):
        reads.append((language, str(root)))
        started.set()
        release.wait(3)
        return ENGLISH

    monkeypatch.setattr(module, "read_language_tables", read)
    tab.load_button.click()
    until(started.is_set)
    try:
        edit.setText("second-installation")
        assert tab._thread.isInterruptionRequested()
    finally:
        release.set()
    until(lambda: not tab.iter_shutdown_workers() and not tab._refresh_timer.isActive())
    assert reads == [("eng", "first-installation")]
    assert tab._catalogue is original
    assert "second-installation" in tab.archive_label.text()
    assert "Game path changed" in tab.status_label.text()


def test_open_paloc_is_background_and_preserves_mod_text_source_and_export_slot(panel, monkeypatch, tmp_path):
    tab, _edit, _settings = panel
    imported = load_catalogue(ENGLISH, "eng")
    imported.set_text(0, "Existing fan translation")
    payload = encode_paloc(imported.apply())
    source = tmp_path / "localizationstring_eng.paloc"
    source.write_bytes(payload)
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    monkeypatch.setattr(module, "read_language_tables", lambda *args, **kwargs: pytest.fail("Loose files must not read game archives"))
    main_thread = threading.get_ident()
    parsing_threads = []
    original_load = module.load_catalogue
    started, release = threading.Event(), threading.Event()

    def load(data, language):
        parsing_threads.append(threading.get_ident())
        started.set()
        release.wait(3)
        return original_load(data, language)

    monkeypatch.setattr(module, "load_catalogue", load)
    tab.open_file_button.click()
    until(started.is_set)
    beats = []
    timer = QTimer()
    timer.setInterval(5)
    timer.timeout.connect(lambda: beats.append(True))
    timer.start()
    try:
        until(lambda: len(beats) >= 3)
        assert not tab.table.isEnabled()
        assert not tab.open_file_button.isEnabled()
    finally:
        timer.stop()
        release.set()
    until(lambda: tab._catalogue is not None and not tab.iter_shutdown_workers())
    assert parsing_threads and parsing_threads[0] != main_thread
    assert tab._catalogue.text_at(0) == "Existing fan translation"
    assert str(source) in tab.status_label.text()
    assert tab.model.setData(tab.model.index(1, 2), "My correction", Qt.EditRole)
    assert tab.export_button.isEnabled()
    files = tab.mod_files()
    assert list(files) == ["gamedata/stringtable/binary__/localizationstring_eng.paloc"]
    rebuilt = parse_paloc(next(iter(files.values())))
    assert rebuilt.entries[0].text == "Existing fan translation"
    assert rebuilt.entries[1].text == "My correction"
    assert source.read_bytes() == payload
    tab._on_reset()
    assert tab._catalogue.text_at(0) == "Existing fan translation"


def test_invalid_file_preserves_edits_and_cancelled_replacement_does_not_load(panel, monkeypatch, tmp_path):
    tab, _edit, _settings = panel
    original = load_catalogue(ENGLISH, "eng")
    original.set_text(0, "Keep my edit")
    tab._on_loaded(original, "")
    source = tmp_path / "localizationstring_eng.paloc"
    source.write_bytes(b"invalid language file")
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    monkeypatch.setattr(module.QMessageBox, "question", lambda *args: QMessageBox.No)
    tab.open_file_button.click()
    assert tab._thread is None
    assert tab._catalogue is original
    monkeypatch.setattr(module.QMessageBox, "question", lambda *args: QMessageBox.Yes)
    tab.open_file_button.click()
    until(lambda: not tab.iter_shutdown_workers())
    assert tab._catalogue is original
    assert original.text_at(0) == "Keep my edit"
    assert "Load failed" in tab.status_label.text()
    assert tab.table.isEnabled()
    assert tab.export_button.isEnabled()


def test_renamed_file_asks_for_slot_and_close_rejects_pending_result(panel, monkeypatch, tmp_path):
    tab, _edit, _settings = panel
    source = tmp_path / "my-translation.paloc"
    source.write_bytes(ENGLISH)
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *args, **kwargs: ("rus", True))
    original_load = module.load_catalogue
    started, release = threading.Event(), threading.Event()
    loaded = []

    def load(data, language):
        loaded.append(language)
        started.set()
        release.wait(3)
        return original_load(data, language)

    monkeypatch.setattr(module, "load_catalogue", load)
    tab.open_file_button.click()
    until(started.is_set)
    try:
        tab.close()
        assert tab._thread.isInterruptionRequested()
    finally:
        release.set()
    until(lambda: not tab.iter_shutdown_workers())
    assert loaded == ["rus"]
    assert tab._catalogue is None


@pytest.mark.real_game
def test_installed_game_populates_and_loads_split_tables_through_the_panel(panel):
    from tools.placement_studio import corpus

    tab, edit, _settings = panel
    root = corpus.game_root()
    if not root.is_dir():
        pytest.skip("needs the installed game")
    edit.setText(str(root))
    until(lambda: tab.language_box.count() > 0 and not tab.iter_shutdown_workers())
    count = tab.language_box.count()
    tab.language_box.setCurrentText("eng")
    tab.reference_box.setCurrentText("kor")
    tab.load_button.click()
    until(lambda: not tab.iter_shutdown_workers())
    assert tab._catalogue is not None, tab.status_label.text()
    assert tab._catalogue.language == "eng"
    assert tab._catalogue.reference_language == "kor"
    assert len(tab._catalogue) > 100_000
    assert len(tab._catalogue.source_ranges) > 1
    assert any(tab._catalogue.row_references.values())
    print(f"Installed-game panel: {count} languages, {len(tab._catalogue)} English rows, "
          f"{len(tab._catalogue.source_ranges)} source tables, Korean reference loaded.")


def test_opening_an_extracted_split_table_preserves_its_language_and_filename(panel, monkeypatch, tmp_path):
    tab, _edit, _settings = panel
    source = tmp_path / "kor" / "aidialog.paloc"
    source.parent.mkdir()
    source.write_bytes(KOREAN)
    monkeypatch.setattr(module.QFileDialog, "getOpenFileName", lambda *args: (str(source), ""))
    monkeypatch.setattr(module.QInputDialog, "getText", lambda *args, **kwargs: pytest.fail("The language folder identifies the slot"))
    tab.open_file_button.click()
    until(lambda: tab._catalogue is not None and not tab.iter_shutdown_workers())
    assert tab._catalogue.language == "kor"
    assert tab.model.setData(tab.model.index(0, 2), "A correction", Qt.EditRole)
    assert list(tab.mod_files()) == ["gamedata/stringtable/binary__/kor/aidialog.paloc"]
