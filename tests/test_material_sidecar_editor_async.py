from __future__ import annotations

import threading
import time
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.models import ArchiveEntry, RunCancelled
from cdmw.services import material_sidecar_document_service as service
from cdmw.services import material_sidecar_preview_service as preview_service
from cdmw.ui.archive_browser.material_sidecar_editor_dialog import (
    ArchiveMaterialSidecarEditorMixin,
)


def _entry() -> ArchiveEntry:
    return ArchiveEntry("character/model/test.pac_xml", Path("0.pamt"), Path("0.paz"), 1, 64, 64, 0, 0)


def test_material_sidecar_document_load_is_cancellable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    payload = b'<SkinnedMeshMaterialWrapper _subMeshName="body"><MaterialParameterFloat _name="_brightness" Value="1.2" /></SkinnedMeshMaterialWrapper>'
    stop_event = threading.Event()
    seen: list[threading.Event | None] = []

    def fake_read(_entry: ArchiveEntry, *, stop_event: threading.Event | None = None):
        seen.append(stop_event)
        return payload, False, ""

    monkeypatch.setattr(service, "read_archive_entry_data", fake_read)
    document = service.load_material_sidecar_editor_document(_entry(), stop_event=stop_event)
    assert document.rows[0].parameter_name == "_brightness"
    assert seen == [stop_event]

    stop_event.set()
    with pytest.raises(RunCancelled):
        service.load_material_sidecar_editor_document(_entry(), stop_event=stop_event)


def test_material_sidecar_open_handler_only_dispatches() -> None:
    class Owner:
        _open_material_sidecar_editor = ArchiveMaterialSidecarEditorMixin._open_material_sidecar_editor

        def __init__(self) -> None:
            self.dispatched: dict[str, object] | None = None
            self._material_sidecar_document_request_id = 0

        def _run_utility_task(self, **kwargs: object) -> None:
            self.dispatched = kwargs

        def _handle_material_sidecar_document_loaded(self, _request_id: int, _result: object) -> None:
            return

    owner = Owner()
    started = time.perf_counter()
    owner._open_material_sidecar_editor(_entry())
    elapsed = time.perf_counter() - started

    assert elapsed < 0.05
    assert owner.dispatched is not None
    assert owner.dispatched["task_accepts_cancel"] is True


def test_material_sidecar_export_analysis_runs_in_worker_owner() -> None:
    source = Path(
        "cdmw/ui/archive_browser/material_sidecar_editor_dialog.py"
    ).read_text(encoding="utf-8")
    export_start = source.index("def _export()")
    export_body = source[export_start : source.index("pick_color_button.clicked.connect", export_start)]

    assert "prepare_material_sidecar_export(" in export_body
    assert "_run_utility_task_when_idle(" in export_body
    assert "task_accepts_cancel=True" in export_body
    assert "stop_event=stop_event" in export_body
    assert "apply_material_sidecar_edits(" not in export_body
    assert "detect_material_sidecar_related_files(" not in export_body


def test_material_live_preview_manifest_work_only_runs_inside_cancellable_task() -> None:
    source = Path("cdmw/ui/archive_browser/material_sidecar_editor_dialog.py").read_text(encoding="utf-8")
    service_source = Path("cdmw/services/material_sidecar_preview_service.py").read_text(encoding="utf-8")
    start = source.index("def _start_material_preview_refresh(")
    task_start = source.index("def _task(", start)
    prefix = source[start:task_start]
    body = source[task_start : source.index("def _handle_complete(", task_start)]

    assert "material_preview_package_matches_entry(" not in prefix
    assert "fast_material_preview_package_from_manifest(" not in prefix
    assert ".is_file()" not in prefix
    assert "build_material_sidecar_preview(preview_request, log, stop_event)" in body
    assert "material_preview_package_matches_entry(" in service_source
    assert "fast_material_preview_package_from_manifest(" in service_source
    assert "stop_event=stop_event" in service_source
    assert "prepare_model_preview(" in service_source
    assert "write_isolated_d3d11_preview_package(" in service_source
    assert "task_accepts_cancel=True" in source[start : source.index("def _schedule_live_preview_for_item", start)]
    shutdown_start = source.index("def _shutdown_material_preview()")
    shutdown_body = source[shutdown_start : source.index("def _apply_material_preview_status_payload", shutdown_start)]
    assert 'preview_generation["value"] += 1' in shutdown_body
    assert 'preview_generation.pop("worker", None)' in shutdown_body
    assert "worker.stop()" in shutdown_body


def test_cancelled_fast_material_preview_removes_staging_package(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_package = tmp_path / "source"
    source_package.mkdir()
    (source_package / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": "character/model/test.pac",
                "batches": [
                    {
                        "material_name": "body",
                        "texture_name": "body",
                        "vertex_file": "vertices.bin",
                        "vertex_count": 3,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    stop_event = threading.Event()
    monkeypatch.setattr(
        preview_service,
        "discover_material_sidecar_preview_overrides_for_edits",
        lambda *_args, **_kwargs: (
            SimpleNamespace(
                group_label="body",
                tint_color=(1.0, 0.0, 0.0),
                brightness=1.0,
                uv_scale=1.0,
                reason="test",
            ),
        ),
    )
    real_write = preview_service.atomic_write_text

    def cancel_after_write(path: Path, text: str) -> None:
        real_write(path, text)
        stop_event.set()

    monkeypatch.setattr(preview_service, "atomic_write_text", cancel_after_write)

    with pytest.raises(RunCancelled):
        preview_service.fast_material_preview_package_from_manifest(
            source_package,
            cache_root=tmp_path / "cache",
            label_normalizer=lambda value: str(value).casefold(),
            preview_sidecar_text="sidecar",
            edited_values={"row": "value"},
            color_edits_active=True,
            stop_event=stop_event,
        )

    assert not tuple((tmp_path / "cache" / "packages").glob("_staging_*"))
