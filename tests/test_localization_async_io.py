from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QApplication, QDialog

from cdmw.models import RunCancelled
from cdmw.services.localization_file_service import write_language_file
from cdmw.ui.localization import UiLocalizer, bundled_translatable_source_strings
from cdmw.ui.shell.request_task_controller import RequestTaskController
from cdmw.ui.shell.utility_controller import UtilityControllerMixin
from cdmw.workers.localization_workers import (
    LanguageExportRequest,
    LanguageExportResult,
    LanguageImportRequest,
    run_language_export,
    run_language_import,
)


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _wait_for(app: QApplication, predicate: object, timeout: float = 5.0) -> bool:
    deadline = time.perf_counter() + timeout
    while time.perf_counter() < deadline:
        app.processEvents()
        if predicate():
            return True
        time.sleep(0.005)
    return bool(predicate())


class _UtilityOwner(UtilityControllerMixin, QObject):
    def __init__(self) -> None:
        QObject.__init__(self)
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None
        self._utility_updates_archive_progress = False

    def _background_task_active(self) -> bool:
        return self.worker_thread is not None

    def set_status_message(self, *_args: object, **_kwargs: object) -> None:
        pass

    def append_log(self, *_args: object, **_kwargs: object) -> None:
        pass

    def set_busy(self, *_args: object, **_kwargs: object) -> None:
        pass

    def _handle_utility_log_message(self, _message: str) -> None:
        pass

    def _handle_utility_progress_changed(self, _current: int, _total: int, _detail: str) -> None:
        pass

    def _handle_worker_error(self, message: str) -> None:
        if self._utility_error_handler is not None:
            self._utility_error_handler(message)

    def _cleanup_worker_refs(self) -> None:
        self.worker_thread = None
        self.utility_worker = None
        self._utility_completion_handler = None
        self._utility_error_handler = None


def test_language_workers_validate_and_publish_atomically(tmp_path: Path) -> None:
    output_path = tmp_path / "export.json"
    translations = bundled_translatable_source_strings()
    translations["Live string"] = "Cadena activa"
    export = run_language_export(
        LanguageExportRequest(
            output_path,
            "es",
            "Español",
            tuple(sorted(translations.items())),
        )
    )
    assert export.output_path == output_path
    payload = json.loads(output_path.read_text(encoding="utf-8"))
    assert "Open DirectXTex / texconv Page" in payload["translations"]
    assert payload["translations"]["Live string"] == "Cadena activa"
    assert not tuple(tmp_path.glob(".*.tmp"))

    import_source = tmp_path / "source.json"
    import_source.write_text(
        json.dumps(
            {
                "language_code": "Custom Language!",
                "language_name": "Custom",
                "translations": {"Hello": "Hej"},
            }
        ),
        encoding="utf-8",
    )
    imported = run_language_import(LanguageImportRequest(import_source, tmp_path / "languages"))
    assert imported.language_code == "customlanguage"
    assert dict(imported.translations) == {"Hello": "Hej"}
    assert imported.target_path.is_file()


def test_cancelled_language_write_preserves_existing_file(tmp_path: Path) -> None:
    output_path = tmp_path / "language.json"
    output_path.write_bytes(b"original")
    stop_event = threading.Event()
    stop_event.set()
    try:
        run_language_export(
            LanguageExportRequest(output_path, "en", "English", (("Hello", "Hello"),)),
            stop_event=stop_event,
        )
    except RunCancelled:
        pass
    else:
        raise AssertionError("pre-cancelled language export must stop")
    assert output_path.read_bytes() == b"original"
    assert not tuple(tmp_path.glob(".*.tmp"))


def test_available_language_metadata_and_payloads_are_cached(tmp_path: Path) -> None:
    language_dir = tmp_path / "languages"
    write_language_file(
        language_dir / "sv.json",
        language_code="sv",
        language_name="Svenska",
        translations={"Hello": "Hej"},
    )
    localizer = UiLocalizer(language_dir=language_dir, language_code="sv")
    assert localizer.translate("Hello") == "Hej"

    with patch("cdmw.ui.localization.load_language_file", side_effect=AssertionError("language file reread")):
        assert ("sv", "Svenska") in localizer.available_languages()
        localizer.install_imported_language("no", "Norsk", {"Hello": "Hei"}, language_dir / "no.json")
        assert localizer.translate("Hello") == "Hei"
        assert ("no", "Norsk") in localizer.available_languages()


def test_language_controller_cancels_without_delivering_stale_result(tmp_path: Path) -> None:
    app = _app()
    owner = _UtilityOwner()
    dialog = QDialog()
    controller = RequestTaskController(owner, dialog, worker_label="language_io")
    started = threading.Event()
    cancelled = threading.Event()
    completed: list[object] = []

    def slow_export(
        request: LanguageExportRequest,
        *,
        stop_event: threading.Event,
    ) -> LanguageExportResult:
        started.set()
        if stop_event.wait(2.0):
            cancelled.set()
            raise RunCancelled("Language export cancelled.")
        return LanguageExportResult(request.request_id, request.output_path, request.language_code, 0)

    before = time.perf_counter()
    assert controller.start(
        LanguageExportRequest(tmp_path / "out.json", "en", "English", ()),
        slow_export,
        status_message="Exporting...",
        on_complete=completed.append,
        on_error=lambda _message: None,
    )
    assert (time.perf_counter() - before) * 1000.0 < 50.0
    assert started.wait(1.0)
    controller.request_shutdown()
    assert cancelled.wait(1.0)
    assert _wait_for(app, lambda: owner.worker_thread is None)
    assert completed == []
    assert controller.iter_shutdown_workers() == ()
    dialog.deleteLater()
    app.processEvents()


def test_language_handlers_only_snapshot_ui_and_dispatch_workers() -> None:
    source = Path("cdmw/ui/shell/language_controller.py").read_text(encoding="utf-8")
    assert "LanguageExportRequest(" in source
    assert "LanguageImportRequest(" in source
    assert "run_language_export" in source
    assert "run_language_import" in source
    assert "write_language_file(" not in source
    assert "self.ui_localizer.import_language_file(" not in source
