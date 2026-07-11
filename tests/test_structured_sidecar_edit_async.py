from __future__ import annotations

import struct
import threading
import time
from pathlib import Path

import pytest

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services import structured_sidecar_edit_service as service
from cdmw.services.structured_sidecar_edit_service import StructuredSidecarEditRequest
from cdmw.ui.archive_browser.binary_sidecar_actions import ArchiveBinarySidecarActionsMixin


def _entry(extension: str = ".paseq") -> ArchiveEntry:
    return ArchiveEntry(f"animation/test{extension}", Path("0.pamt"), Path("0.paz"), 1, 16, 16, 0, 0)


def test_structured_sidecar_load_and_write_are_cancellable_and_transactional(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = struct.pack("<I", 8) + b"old.paa\0"
    stop_event = threading.Event()
    seen_stop_events: list[threading.Event | None] = []

    def fake_read(_entry: ArchiveEntry, *, stop_event: threading.Event | None = None):
        seen_stop_events.append(stop_event)
        return payload, False, ""

    monkeypatch.setattr(service, "read_archive_entry_data", fake_read)
    document = service.load_structured_sidecar_document(_entry(), stop_event=stop_event)
    assert document.fields[0].text == "old.paa"
    assert seen_stop_events == [stop_event]

    output = tmp_path / "edited.paseq"
    result = service.write_structured_sidecar_edit(
        StructuredSidecarEditRequest(document, output, 0, replacement_text="new.paa"),
        stop_event=stop_event,
    )
    assert result.output_path == output
    assert output.read_bytes()[4:11] == b"new.paa"
    assert not tuple(tmp_path.glob(".*.tmp"))

    stop_event.set()
    with pytest.raises(RunCancelled):
        service.load_structured_sidecar_document(_entry(), stop_event=stop_event)


def test_structured_sidecar_ui_handler_only_queues_worker() -> None:
    class Owner:
        _edit_archive_structured_binary_sidecar = (
            ArchiveBinarySidecarActionsMixin._edit_archive_structured_binary_sidecar
        )

        def __init__(self) -> None:
            self.dispatched: dict[str, object] | None = None
            self._structured_sidecar_request_id = 0
            self.status: list[tuple[str, bool]] = []

        def _run_utility_task(self, **kwargs: object) -> None:
            self.dispatched = kwargs

        def _prompt_structured_sidecar_edit(self, _request_id: int, _result: object) -> None:
            return

        def set_status_message(self, message: str, *, error: bool = False) -> None:
            self.status.append((message, error))

    owner = Owner()
    started = time.perf_counter()
    owner._edit_archive_structured_binary_sidecar(_entry())
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert owner.dispatched is not None
    assert owner.dispatched["task_accepts_cancel"] is True
    assert callable(owner.dispatched["task"])
