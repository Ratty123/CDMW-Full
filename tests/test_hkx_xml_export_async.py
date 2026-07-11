from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from tests.hkx_editor_dialog_source_support import hkx_editor_dialog_source

from cdmw.models import RunCancelled
from cdmw.services.hkx_xml_export_service import (
    HkxXmlExportRequest,
    HkxXmlExportResult,
    export_hkx_xml,
)
from cdmw.ui.archive_browser.hkx_xml_export_controller import start_hkx_editor_xml_export


class _Owner:
    def __init__(self) -> None:
        self._hkx_editor_xml_export_request_id = 0
        self._shutting_down = False
        self.dispatched: list[dict[str, object]] = []
        self.statuses: list[tuple[str, bool]] = []

    def _run_utility_task_when_idle(self, **kwargs: object) -> None:
        self.dispatched.append(kwargs)

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.statuses.append((message, error))


def test_hkx_xml_export_dispatch_returns_within_handler_budget(tmp_path: Path) -> None:
    owner = _Owner()
    document = "<hkx>" + ("0" * (8 * 1024 * 1024)) + "</hkx>"

    started = time.perf_counter()
    start_hkx_editor_xml_export(
        owner,
        tmp_path / "edited.geometry.xml",
        document,
        message_parent=None,  # type: ignore[arg-type]
    )
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert len(owner.dispatched) == 1
    assert owner.dispatched[0]["task_accepts_cancel"] is True
    assert not (tmp_path / "edited.geometry.xml").exists()


def test_hkx_xml_export_rejects_stale_completion(tmp_path: Path) -> None:
    owner = _Owner()
    first_path = tmp_path / "first.xml"
    second_path = tmp_path / "second.xml"
    start_hkx_editor_xml_export(owner, first_path, "first", message_parent=None)  # type: ignore[arg-type]
    start_hkx_editor_xml_export(owner, second_path, "second", message_parent=None)  # type: ignore[arg-type]

    first_complete = owner.dispatched[0]["on_complete"]
    second_complete = owner.dispatched[1]["on_complete"]
    assert callable(first_complete)
    assert callable(second_complete)
    first_complete(HkxXmlExportResult(1, first_path))
    assert owner.statuses == []

    second_complete(HkxXmlExportResult(2, second_path))
    assert owner.statuses == [(f"Exported edited HKX XML to {second_path}.", False)]


def test_hkx_xml_export_is_atomic_and_cancellable(tmp_path: Path) -> None:
    target = tmp_path / "edited.xml"
    target.write_text("existing", encoding="utf-8")
    request = HkxXmlExportRequest(7, target, "x" * (1024 * 1024))

    class _StopDuringWrite:
        calls = 0

        def is_set(self) -> bool:
            self.calls += 1
            return self.calls >= 3

    with pytest.raises(RunCancelled, match="stopped by user"):
        export_hkx_xml(request, stop_event=_StopDuringWrite())  # type: ignore[arg-type]

    assert target.read_text(encoding="utf-8") == "existing"
    assert list(tmp_path.glob(".edited.xml.*.tmp")) == []


def test_hkx_xml_export_publishes_exact_unicode(tmp_path: Path) -> None:
    target = tmp_path / "edited.xml"
    document = "<hkx>Crimson Öken U0001f40d</hkx>"
    result = export_hkx_xml(HkxXmlExportRequest(9, target, document), stop_event=threading.Event())

    assert result == HkxXmlExportResult(9, target)
    assert target.read_text(encoding="utf-8") == document


def test_disabled_placement_page_returns_before_archive_read() -> None:
    source = hkx_editor_dialog_source(Path.cwd())
    start = source.index("def _refresh_inline_socket_details()")
    body = source[start : source.index("def _refresh_inline_swap_summary", start)]

    guard = body.index("if not _state.placement_page.isEnabled():")
    early_return = body.index("return", guard)
    archive_read = body.index("read_archive_entry_data(socket_entry)")
    assert guard < early_return < archive_read
