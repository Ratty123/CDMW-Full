from __future__ import annotations

from dataclasses import dataclass

from cdmw.domain.archives.backend_mode import ArchiveBackendMode, ArchiveBackendSelection
from cdmw.ui.archive_browser import scan_lifecycle
from cdmw.ui.archive_browser.scan_lifecycle import ArchiveScanLifecycleMixin


@dataclass
class _Button:
    label: str


class _MessageBox:
    Critical = 3
    AcceptRole = 0
    ActionRole = 3
    RejectRole = 1
    choice = "cancel"

    def __init__(self, _parent: object) -> None:
        self.buttons: dict[str, _Button] = {}
        self._clicked: _Button | None = None

    def setIcon(self, _icon: object) -> None:
        pass

    def setWindowTitle(self, _title: str) -> None:
        pass

    def setText(self, _text: str) -> None:
        pass

    def setInformativeText(self, _text: str) -> None:
        pass

    def addButton(self, label: str, _role: object) -> _Button:
        button = _Button(label)
        self.buttons[label] = button
        return button

    def setDefaultButton(self, _button: _Button) -> None:
        pass

    def exec(self) -> None:
        labels = {
            "retry": "Retry v2",
            "legacy": "Use Legacy This Session",
            "cancel": "Cancel",
        }
        self._clicked = self.buttons[labels[self.choice]]

    def clickedButton(self) -> _Button | None:
        return self._clicked


class _Timer:
    @staticmethod
    def singleShot(_delay: int, callback) -> None:
        callback()


class _Bridge:
    displays_v2 = True
    last_force_refresh = True
    last_activate_tab = False

    def __init__(self) -> None:
        self.retry_count = 0
        self.deactivate_count = 0

    def retry_last_open(self) -> bool:
        self.retry_count += 1
        return True

    def deactivate(self) -> None:
        self.deactivate_count += 1


class _Tree:
    def __init__(self) -> None:
        self.legacy_count = 0
        self.root_decorated: bool | None = None
        self.enabled: bool | None = None

    def use_legacy_model(self) -> None:
        self.legacy_count += 1

    def setRootIsDecorated(self, value: bool) -> None:
        self.root_decorated = value

    def setEnabled(self, value: bool) -> None:
        self.enabled = value


class _Service:
    def __init__(self) -> None:
        self.shutdown_count = 0

    def request_shutdown(self) -> None:
        self.shutdown_count += 1


class _Window(ArchiveScanLifecycleMixin):
    def __init__(self) -> None:
        self.archive_remote_bridge = _Bridge()
        self.archive_backend_selection = ArchiveBackendSelection(ArchiveBackendMode.V2, "", True)
        self.archive_backend_mode = ArchiveBackendMode.V2
        self.archive_backend_failure_dialog_open = False
        self.archive_remote_actions_safe = False
        self.archive_remote_query_pending = True
        self.archive_remote_total_matches = 42
        self.archive_tree = _Tree()
        self.archive_catalogue_service = _Service()
        self.logs: list[str] = []
        self.scans: list[tuple[bool, bool]] = []
        self.events: list[tuple[str, dict[str, object]]] = []

    def append_archive_log(self, message: str) -> None:
        self.logs.append(message)

    def scan_archives(self, force_refresh: bool = False, *, activate_archive_tab: bool = True) -> None:
        self.scans.append((force_refresh, activate_archive_tab))

    def _record_runtime_event(self, event: str, **fields: object) -> None:
        self.events.append((event, fields))


def test_backend_failure_retry_keeps_v2_and_retries_last_request(monkeypatch) -> None:
    monkeypatch.setattr(scan_lifecycle, "QMessageBox", _MessageBox)
    monkeypatch.setattr(_MessageBox, "choice", "retry")
    window = _Window()
    bridge = window.archive_remote_bridge

    window._handle_archive_backend_v2_failure("open", "worker unavailable")

    assert bridge.retry_count == 1
    assert bridge.deactivate_count == 0
    assert window.archive_backend_mode is ArchiveBackendMode.V2
    assert window.scans == []


def test_backend_failure_legacy_choice_is_session_only_and_explicit(monkeypatch) -> None:
    monkeypatch.setattr(scan_lifecycle, "QMessageBox", _MessageBox)
    monkeypatch.setattr(scan_lifecycle, "QTimer", _Timer)
    monkeypatch.setattr(_MessageBox, "choice", "legacy")
    window = _Window()
    bridge = window.archive_remote_bridge

    window._handle_archive_backend_v2_failure("open", "worker unavailable")

    assert bridge.deactivate_count == 1
    assert window.archive_remote_bridge is None
    assert window.archive_backend_selection == ArchiveBackendSelection(
        ArchiveBackendMode.LEGACY,
        "session_failure_recovery",
        True,
    )
    assert window.archive_backend_mode is ArchiveBackendMode.LEGACY
    assert window.archive_remote_actions_safe
    assert not window.archive_remote_query_pending
    assert window.archive_remote_total_matches == 0
    assert window.archive_tree.legacy_count == 1
    assert window.archive_tree.root_decorated
    assert window.archive_tree.enabled
    assert window.archive_catalogue_service.shutdown_count == 1
    assert window.scans == [(True, False)]
    assert window.events == [
        (
            "archive_backend_session_legacy_selected",
            {"failed_operation": "open", "error": "worker unavailable"},
        )
    ]
