"""Real Qt worker delivery, cancellation, and export without paid provider calls."""

import json
import threading
import time

import pytest
from PySide6.QtWidgets import QApplication

from tests.test_translation_studio_audit import split_catalogue
from tests.test_translation_studio_loading import panel, until
from tools.translation_studio import ai_job, ai_panel, tab as tab_module
from tools.translation_studio.ai_provider import ProviderConfig
from tools.translation_studio.ai_translate import Line


@pytest.fixture
def configured(monkeypatch, tmp_path):
    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("CDMW_TS_WORK_ROOT", str(tmp_path))
    config = ProviderConfig(preset="ollama", model="test", batch_size=1, parallel=1)
    monkeypatch.setattr(ai_panel, "load_config", lambda: config)
    yield config
    until(lambda: not tab_module._LIVE_THREADS)
    app.processEvents()


def reply(text="Translated"):
    return 200, json.dumps({"choices": [{"message": {"content": json.dumps([{"i": 0, "t": text}])}}]}).encode()


def test_provider_dialog_close_is_nonblocking_and_retains_the_request(panel, configured, monkeypatch):
    tab, _edit, _settings = panel
    started, release = threading.Event(), threading.Event()

    def transport(*_args):
        started.set()
        release.wait(3)
        return reply("Traduction.<br/>{Key:Key_Roll}")

    monkeypatch.setattr(ai_job, "http_transport", transport)
    dialog = ai_panel.ProviderSettingsDialog(tab)
    dialog._on_test()
    until(started.is_set)
    try:
        assert any(label == "translation provider test" for label, *_ in tab.iter_shutdown_workers())
        assert dialog._test_thread.parent() is None
        before = dialog.test_result.text()
        started_close = time.perf_counter()
        dialog.reject()
        assert time.perf_counter() - started_close < 0.2
        release.set()
        until(lambda: not dialog.iter_shutdown_workers())
        assert dialog.test_result.text() == before
    finally:
        release.set()
        until(lambda: not dialog.iter_shutdown_workers())
        dialog.deleteLater()


def test_provider_connection_test_rejects_broken_markup(configured, monkeypatch):
    monkeypatch.setattr(ai_job, "http_transport", lambda *_: reply("Missing all placeholders"))
    worker = ai_panel._TestWorker(configured)
    results = []
    worker.done.connect(lambda ok, message: results.append((ok, message)))
    worker.run()
    assert results[0][0] is False
    assert "markup" in results[0][1]


def test_provider_save_failure_is_reported_without_closing(configured, monkeypatch):
    def fail(_config):
        raise OSError("read-only folder")

    monkeypatch.setattr(ai_panel, "save_config", fail)
    dialog = ai_panel.ProviderSettingsDialog()
    dialog._on_save()
    assert not dialog._closed
    assert "read-only folder" in dialog.test_result.text()
    dialog.reject()
    dialog.deleteLater()


def test_translation_dialog_applies_on_ui_thread_and_can_run_again(panel, configured):
    tab, _edit, _settings = panel
    cat = split_catalogue()
    tab._on_loaded(cat, "")
    applied_threads, request_threads = [], []
    main_thread = threading.get_ident()

    def transport(*_args):
        request_threads.append(threading.get_ident())
        return reply()

    def apply(translations):
        applied_threads.append(threading.get_ident())
        tab.apply_ai_translations(translations)

    dialog = ai_panel.TranslateDialog(scopes=[("Selected", [Line(0, "Bank")])], working_language="eng",
                                      apply_translations=apply, parent=tab, transport=transport)
    for _ in range(2):
        dialog._on_start()
        dialog._on_start()  # A second click must not replace a running thread.
        until(lambda: not dialog.iter_shutdown_workers())
        assert dialog.summary.translated == 1
    assert applied_threads == [main_thread, main_thread]
    assert len(request_threads) == 2 and main_thread not in request_threads
    assert cat.text_at(0) == "Translated"
    assert tab.export_button.isEnabled()
    dialog.reject()
    dialog.deleteLater()


def test_translation_dialog_close_drops_late_results_and_keeps_existing_edits(panel, configured):
    tab, _edit, _settings = panel
    cat = split_catalogue()
    tab._on_loaded(cat, "")
    cat.set_text(0, "Already edited")
    started, release = threading.Event(), threading.Event()

    def transport(*_args):
        started.set()
        release.wait(3)
        return reply("Late response")

    dialog = ai_panel.TranslateDialog(scopes=[("Selected", [Line(0, "Bank")])], working_language="eng",
                                      apply_translations=tab.apply_ai_translations, parent=tab, transport=transport)
    dialog._on_start()
    until(started.is_set)
    try:
        assert any(label == "AI translation" for label, *_ in tab.iter_shutdown_workers())
        assert dialog._thread.parent() is None
        started_close = time.perf_counter()
        dialog.reject()
        assert time.perf_counter() - started_close < 0.2
        release.set()
        until(lambda: not dialog.iter_shutdown_workers())
        assert cat.text_at(0) == "Already edited"
    finally:
        release.set()
        until(lambda: not dialog.iter_shutdown_workers())
        dialog.deleteLater()


def test_export_button_uses_a_worker_and_an_immutable_edit_snapshot(panel, monkeypatch, tmp_path):
    tab, _edit, _settings = panel
    cat = split_catalogue()
    tab._on_loaded(cat, "")
    tab.apply_ai_translations({0: "First edit"})
    started, release = threading.Event(), threading.Event()
    observed = []
    main_thread = threading.get_ident()

    def export(snapshot, **_kwargs):
        started.set()
        release.wait(3)
        observed.append((snapshot.text_at(0), threading.get_ident()))
        return ("one", "two", "three")

    monkeypatch.setattr(tab_module, "export_packages", export)
    monkeypatch.setattr(tab_module.QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path))
    tab.export_button.click()
    until(started.is_set)
    try:
        assert not tab.open_file_button.isEnabled()
        assert not tab.export_button.isEnabled()
        assert not tab.table.isEnabled()
        assert any(label == "translation export" for label, *_ in tab.iter_shutdown_workers())
        cat.set_text(0, "Later edit")
        release.set()
        until(lambda: not tab.iter_shutdown_workers())
        assert observed[0][0] == "First edit"
        assert observed[0][1] != main_thread
        assert "Wrote 3 package(s)" in tab.export_note.text()
        assert tab.table.isEnabled()
    finally:
        release.set()
        until(lambda: not tab.iter_shutdown_workers())


def test_shutdown_cancels_export_and_drops_its_late_status(panel, monkeypatch, tmp_path):
    tab, _edit, _settings = panel
    tab._on_loaded(split_catalogue(), "")
    tab.apply_ai_translations({0: "Edited"})
    started, release = threading.Event(), threading.Event()

    def export(_snapshot, *, is_cancelled, **_kwargs):
        started.set()
        release.wait(3)
        assert is_cancelled()
        return ("late",)

    monkeypatch.setattr(tab_module, "export_packages", export)
    monkeypatch.setattr(tab_module.QFileDialog, "getExistingDirectory", lambda *_: str(tmp_path))
    tab.export_button.click()
    until(started.is_set)
    try:
        status = tab.export_note.text()
        tab.request_shutdown()
        release.set()
        until(lambda: not tab.iter_shutdown_workers())
        assert tab.export_note.text() == status
    finally:
        release.set()
        until(lambda: not tab.iter_shutdown_workers())
