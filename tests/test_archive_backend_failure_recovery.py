import os
from types import SimpleNamespace
import pytest
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLineEdit, QWidget
from cdmw.domain.archives.catalogue_operations import ArchiveBackendError
from cdmw.domain.archives.discovery import ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, suggested_archive_exclusion
from cdmw.services.settings_service import add_ignored_archive_folder, create_settings
from cdmw.services.archive_failure_report import ArchiveOperationFailure
from cdmw.ui.archive_browser.failure_report import ArchiveFailureDialog, ArchiveFailurePanel
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin

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


@pytest.mark.parametrize("relative,expected", [
    ("bin64/.CrimsonModsCache/main/hash/0009/0.pamt", "bin64/.CrimsonModsCache"),
    ("BIN64/.cRIMSONmODSCache/main/0.pamt", "bin64/.CrimsonModsCache"),
    ("backups/0009/0.pamt", "backups"),
    ("0009/0.pamt", None), ("dlc/dlc_01/0009/0.pamt", None),
    ("bin64/.CrimsonModsCache2/0.pamt", None), ("unknown/mod/0.pamt", None),
    ("../bin64/.CrimsonModsCache/0.pamt", None),
    ("bin64/.CrimsonModsCache/../0009/0.pamt", None),
])
def test_exclusion_suggestions_only_cover_known_in_root_subtrees(tmp_path, relative, expected):
    assert suggested_archive_exclusion(str(tmp_path), str(tmp_path / relative)) == expected


@pytest.mark.parametrize("source,operation,offer", [
    ("bin64/.CrimsonModsCache/main/0009/0.pamt", "open", True),
    ("0009/0.pamt", "open", False), (None, "open", False),
    ("bin64/.CrimsonModsCache/main/0009/0.pamt", "build_name_index", False),
])
def test_failure_panel_offers_exclusion_only_for_confirmed_open_failures(tmp_path, source, operation, offer):
    panel = ArchiveFailurePanel()
    error = ArchiveBackendError("invalid_archive", "Invalid extension table", source_path=str(tmp_path / source) if source else None)
    panel.show_failure("Archive opening failed", error, operation=operation, package_root=str(tmp_path))
    assert panel.exclude_button.isHidden() is not offer
    if source:
        assert source in panel.source_label.text().replace("\\", "/")
    if offer:
        requested = []
        panel.excludeFolderRequested.connect(requested.append)
        panel.exclude_button.click()
        panel.exclude_button.click()
        assert requested == ["bin64/.CrimsonModsCache"]
    elif operation == "open":
        assert "verify the installation" in panel.guidance_label.text()
    panel.deleteLater()
    _APP.processEvents()


def test_equivalent_root_spelling_keeps_the_confirmed_exclusion(tmp_path):
    panel = ArchiveFailurePanel()
    failure = ArchiveOperationFailure("invalid_archive", "Bad table", None, "report", "request",
        str(tmp_path / "bin64/.CrimsonModsCache/0.pamt"), str(tmp_path))
    panel.show_failure("Failed", failure, operation="open", package_root=tmp_path.as_posix() + "/")
    assert panel.excluded_folder == "bin64/.CrimsonModsCache"
    panel.show_failure("Failed", failure, operation="open", package_root=str(tmp_path / "other"))
    assert panel.exclude_button.isHidden()
    panel.deleteLater()
    _APP.processEvents()


def test_failed_settings_save_does_not_keep_an_unsaved_exclusion(tmp_path):
    settings_path = tmp_path / "directory-not-a-settings-file"
    settings_path.mkdir()
    settings = create_settings(settings_file_path=settings_path)
    with pytest.raises(OSError, match="Settings could not be saved"):
        add_ignored_archive_folder(settings, "bin64/.CrimsonModsCache")
    assert settings.value(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, None) is None


class _FailureWorkspace(QWidget, ArchiveScanLifecycleMixin):
    def __init__(self, tmp_path):
        super().__init__()
        self.shell = SimpleNamespace(_shutting_down=False, settings=create_settings(settings_file_path=tmp_path / "settings.cfg"),
            _release_startup_splash=lambda: None)
        self.archive_open_generation = 1
        self.archive_package_root_edit = QLineEdit(str(tmp_path), self)
        self.archive_remote_bridge = None
        self.archive_remote_query_pending = False
        self.scans = []

    def scan_archives(self, *args, **kwargs):
        self.scans.append(kwargs)


@pytest.mark.parametrize("stale", ["generation", "root", "shutdown", "closed", "pending"])
def test_stale_popup_cannot_save_an_exclusion_or_refresh(tmp_path, stale):
    workspace = _FailureWorkspace(tmp_path)
    source = str(tmp_path / "bin64/.CrimsonModsCache/main/0009/0.pamt")
    workspace._handle_archive_backend_failure("open", ArchiveBackendError("invalid_archive", "Bad table", source_path=source))
    dialog = workspace.archive_backend_failure_dialog
    if stale == "generation": workspace.archive_open_generation += 1
    if stale == "root": workspace.archive_package_root_edit.setText(str(tmp_path / "other"))
    if stale == "shutdown": workspace.shell._shutting_down = True
    if stale == "closed": dialog.close()
    if stale == "pending": workspace.archive_remote_query_pending = True
    dialog.panel.exclude_button.click()
    assert not workspace.scans
    assert workspace.shell.settings.value(ARCHIVE_IGNORED_FOLDERS_OVERRIDE_SETTING, None) is None
    dialog.close()
    workspace.deleteLater()
    _APP.processEvents()
