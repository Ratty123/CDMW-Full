from __future__ import annotations

import threading
from pathlib import Path

import pytest

from tests.hkx_editor_dialog_source_support import hkx_editor_dialog_source

from cdmw.models import (
    ArchiveEntry,
    ArchiveEntryIdentity,
    ArchivePreviewResult,
    ModelPreviewData,
    RunCancelled,
)
from cdmw.services import hkx_embedded_preview_service as service


def _entry() -> ArchiveEntry:
    return ArchiveEntry("character/test.pac", Path("0.pamt"), Path("0.paz"), 4, 8, 8, 0, 0)


def _request(tmp_path: Path) -> service.HkxEmbeddedPreviewRequest:
    return service.HkxEmbeddedPreviewRequest(
        ArchiveEntryIdentity("character/test.pac", "0.pamt", 0, 4),
        _entry(),
        None,
        {},
        {},
        {},
        {},
        "mesh_base_first",
        ("normal",),
    )


def test_hkx_embedded_preview_passes_cancellation_to_build_and_prepare(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    seen: list[tuple[str, object]] = []
    model = ModelPreviewData(path="character/test.pac")

    def fake_build(_entry: ArchiveEntry, **kwargs: object) -> ArchivePreviewResult:
        seen.append(("build", kwargs["stop_event"]))
        return ArchivePreviewResult(status="ok", preview_model=model)

    def fake_prepare(preview_model: object, **kwargs: object) -> tuple[object, None]:
        seen.append(("prepare", kwargs["stop_event"]))
        return preview_model, None

    monkeypatch.setattr(service, "build_archive_preview_result", fake_build)
    monkeypatch.setattr(service, "prepare_model_preview", fake_prepare)
    _entry_key, _path, result = service.build_hkx_embedded_preview(
        _request(tmp_path),
        stop_event=stop_event,
    )

    assert result.preview_model is model
    assert seen == [("build", stop_event), ("prepare", stop_event)]


def test_hkx_embedded_preview_honors_pre_cancel(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    stop_event = threading.Event()
    stop_event.set()
    build_called = False

    def fake_build(*_args: object, **_kwargs: object) -> ArchivePreviewResult:
        nonlocal build_called
        build_called = True
        return ArchivePreviewResult(status="ok")

    monkeypatch.setattr(service, "build_archive_preview_result", fake_build)
    with pytest.raises(RunCancelled, match="stopped by user"):
        service.build_hkx_embedded_preview(_request(tmp_path), stop_event=stop_event)

    assert build_called is False


def test_hkx_embedded_preview_dialog_dispatch_is_cancellable() -> None:
    source = hkx_editor_dialog_source(Path.cwd())
    start = source.index("def _load_hkx_embedded_preview_model")
    body = source[start : source.index("def _choose_and_load_hkx_embedded_preview_model", start)]

    assert "build_hkx_embedded_preview(preview_request, stop_event=stop_event)" in body
    assert "task_accepts_cancel=True" in body
    assert ".is_file()" not in body
