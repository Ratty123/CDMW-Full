import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication
from cdmw.domain.archives.catalogue_operations import ArchiveBackendError
from cdmw.ui.archive_browser.failure_report import ArchiveFailureDialog, ArchiveFailurePanel

_APP = QApplication.instance() or QApplication([])


def test_archive_failure_has_retry_copy_details_and_close_controls(monkeypatch):
    monkeypatch.setenv("USERPROFILE", "C:/Users/Owner")
    dialog = ArchiveFailureDialog()
    retries = []
    dialog.retryRequested.connect(lambda: retries.append(True))
    panel = dialog.panel
    panel.show_failure("Archive opening failed", ArchiveBackendError("worker_missing", "Helper missing", "C:/Users/Owner/game/worker.exe"), package_root="C:/Users/Owner/game")
    assert [button.text() for button in (panel.retry_button, panel.copy_button, panel.details_button, panel.close_button)] == ["Retry", "Copy error report", "Details", "Close"]
    panel.copy_button.click()
    assert "<game>/worker.exe" in _APP.clipboard().text()
    panel.details_button.click()
    assert not panel.details.isHidden()
    panel.retry_button.click()
    assert retries == [True]
    dialog.deleteLater()
    _APP.processEvents()


def test_background_failure_remains_until_success_and_is_clearable():
    panel = ArchiveFailurePanel()
    panel.show_failure("Item names unavailable", ArchiveBackendError("operation_timeout", "Indexer timed out"))
    assert "Item names unavailable" in panel.message.text() and not panel.isHidden()
    panel.clear()
    assert panel.isHidden() and panel.report == ""
    panel.deleteLater()
    _APP.processEvents()
