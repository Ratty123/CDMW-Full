from __future__ import annotations

import threading
import time
import json
import codecs
from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.models import (
    ArchiveEntry,
    ArchiveModelTextureReference,
    ArchivePreviewResult,
    HkxPhysicsOverlayBone,
    HkxPhysicsOverlayData,
    ModelPreviewData,
    ModelPreviewRenderSettings,
    PreparedModelPreviewData,
    RunCancelled,
)
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


def test_material_sidecar_document_load_reads_complete_original_encoding_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    text = (
        '<?xml version="1.0" encoding="utf-16"?>\r\n'
        + "<!--"
        + ("x" * 250_000)
        + '-->\r\n<MaterialParameterByte4 _name="_channels" _value="7" />'
    )
    payload = codecs.BOM_UTF16_LE + text.encode("utf-16-le")

    monkeypatch.setattr(
        service,
        "read_archive_entry_data",
        lambda _entry, *, stop_event=None: (payload, False, ""),
    )

    document = service.load_material_sidecar_editor_document(_entry())

    assert len(document.original_text) > 240_000
    assert document.original_payload == payload
    assert document.source_format.encoding == "utf-16-le"
    assert document.source_format.bom == codecs.BOM_UTF16_LE
    assert document.source_format.newline == "\r\n"
    assert document.rows[0].kind == "byte4"


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


def test_skeleton_disabled_manifest_clone_omits_bones_without_material_edits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source_package = tmp_path / "source"
    source_package.mkdir()
    (source_package / "vertices.bin").write_bytes(b"vertices")
    (source_package / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": "character/model/test.pac",
                "batches": [
                    {
                        "material_name": "body",
                        "vertex_file": "vertices.bin",
                        "vertex_count": 3,
                    }
                ],
                "skeleton_overlay": {
                    "enabled": True,
                    "status": "ok",
                    "bone_count": 1,
                    "bones": [{"name": "Root", "index": 0}],
                },
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        preview_service,
        "discover_material_sidecar_preview_overrides_for_edits",
        lambda *_args, **_kwargs: (),
    )

    result = preview_service.fast_material_preview_package_from_manifest(
        source_package,
        cache_root=tmp_path / "cache",
        label_normalizer=lambda value: str(value).casefold(),
        preview_sidecar_text="sidecar",
        edited_values={},
        color_edits_active=False,
        include_skeleton_overlay=False,
    )

    assert result is not None
    package_dir, batch_count, vertex_count, notes = result
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    assert batch_count == 1
    assert vertex_count == 3
    assert manifest["skeleton_overlay"]["enabled"] is False
    assert manifest["skeleton_overlay"]["status"] == "disabled"
    assert manifest["skeleton_overlay"]["bone_count"] == 0
    assert manifest["skeleton_overlay"]["bones"] == []
    assert "skeleton overlay omitted for material editing" in notes


def test_material_preview_build_does_not_publish_cached_skeleton_when_disabled(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    model_entry = ArchiveEntry(
        "character/model/test.pac",
        Path("0.pamt"),
        Path("0.paz"),
        1,
        64,
        64,
        0,
        0,
    )
    preview_model = ModelPreviewData(
        path=model_entry.path,
        format="pac",
        physics_overlay=HkxPhysicsOverlayData(
            bones=(HkxPhysicsOverlayBone(name="Root", index=0),),
        ),
    )
    captured: dict[str, object] = {}

    def fake_build_archive_preview_result(*_args: object, **kwargs: object) -> ArchivePreviewResult:
        captured.update(kwargs)
        return ArchivePreviewResult(status="ok", preview_model=preview_model)

    def fake_prepare(model: ModelPreviewData, **_kwargs: object):
        assert model.physics_overlay is None
        return model, PreparedModelPreviewData(source_path=model.path)

    package_dir = tmp_path / "package"
    package_dir.mkdir()
    monkeypatch.setattr(preview_service, "build_archive_preview_result", fake_build_archive_preview_result)
    monkeypatch.setattr(preview_service, "prepare_model_preview", fake_prepare)
    monkeypatch.setattr(
        preview_service,
        "create_native_preview_package_staging_dir",
        lambda _root: package_dir,
    )
    monkeypatch.setattr(preview_service, "write_isolated_d3d11_preview_package", lambda *_args, **_kwargs: None)
    request = preview_service.MaterialSidecarPreviewBuildRequest(
        generation=1,
        preview_model_entry=model_entry,
        sidecar_entry=_entry(),
        companion_entry=None,
        preview_sidecar_text="sidecar",
        material_preview_edits={},
        include_texture_edits=False,
        live=False,
        material_effects_active=False,
        color_edits_active=False,
        include_skeleton_overlay=False,
        preview_settings=ModelPreviewRenderSettings(),
        base_cache_key="base|skeleton=0",
        reusable_package_dir=None,
        fast_source_package_dir=None,
        current_archive_result=None,
        cached_base_result=None,
        cache_root=tmp_path / "cache",
        texture_entries_by_normalized_path={},
        texture_entries_by_basename={},
        sidecar_entries_by_texture_path={},
        sidecar_entries_by_texture_basename={},
        clone_preview_model=lambda model, **_kwargs: model,
        apply_preview_overrides=lambda *_args, **_kwargs: (),
        texture_resolution_warnings=lambda *_args, **_kwargs: (),
        label_normalizer=lambda value: str(value).casefold(),
        cached_geometry_log="cached",
        cached_geometry_note="cached",
        building_model_log="building",
        prepare_failed_message="failed",
    )

    result = preview_service.build_material_sidecar_preview(request, lambda _message: None)

    assert captured["enable_hkx_visual_preview"] is False
    assert result.base_result_for_cache is not None
    assert result.base_result_for_cache.preview_model.physics_overlay is None


def test_archive_model_preview_respects_disabled_related_skeleton_overlay(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from cdmw.core import archive_preview_result_builder as preview_builder

    model_entry = ArchiveEntry(
        "character/model/test.pac",
        tmp_path / "0.pamt",
        tmp_path / "0.paz",
        0,
        4,
        4,
        0,
        0,
    )
    preview_model = ModelPreviewData(path=model_entry.path, format="pac")
    parsed_mesh = SimpleNamespace(
        has_bones=False,
        has_uvs=False,
        submeshes=(),
    )
    reference = ArchiveModelTextureReference(
        reference_name="character/bin__/meshphysics/test.hkx",
        reference_kind="physics",
    )
    overlay_calls: list[object] = []
    monkeypatch.setattr(
        preview_builder,
        "read_archive_entry_data",
        lambda *_args, **_kwargs: (b"PAR ", False, ""),
    )
    monkeypatch.setattr(
        preview_builder,
        "_build_pac_model_preview_with_fallback",
        lambda *_args, **_kwargs: (preview_model, parsed_mesh, []),
    )
    monkeypatch.setattr(
        preview_builder,
        "build_archive_model_texture_references",
        lambda *_args, **_kwargs: (reference,),
    )
    monkeypatch.setattr(
        preview_builder,
        "build_archive_relationship_references",
        lambda *_args, **_kwargs: (),
    )
    monkeypatch.setattr(
        preview_builder,
        "_attach_hkx_physics_overlay_to_model_preview",
        lambda model, *_args, **_kwargs: overlay_calls.append(model) or [],
    )

    without_skeleton = preview_builder.build_archive_preview_result(
        model_entry,
        texture_entries_by_normalized_path={},
        texture_entries_by_basename={},
        enable_hkx_visual_preview=False,
    )
    assert without_skeleton.model_texture_references
    assert overlay_calls == []

    preview_builder.build_archive_preview_result(
        model_entry,
        texture_entries_by_normalized_path={},
        texture_entries_by_basename={},
        enable_hkx_visual_preview=True,
    )
    assert overlay_calls == [preview_model]
