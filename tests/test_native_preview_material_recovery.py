from __future__ import annotations

import copy
import json
import shutil
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtWidgets import QApplication

from cdmw.models import ArchiveEntry, ArchivePreviewResult, ModelPreviewRenderSettings, RunCancelled
from cdmw.rendering.native_preview_core import NativePreviewCoreAttempt
from cdmw.services.mesh_rust_preview_package import validate_rust_preview_package
from cdmw.services.preview_material_status import with_preview_material_warning
from cdmw.ui.archive_browser.preview_result import ArchivePreviewResultMixin
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker
from tests.test_rust_preview_production_cutover import _write_schema8_preview_core_fixture


def _worker(root: Path, source_format: str = "pam") -> ArchivePreviewWorker:
    return ArchivePreviewWorker(
        request_id=7,
        entry=ArchiveEntry(
            path=f"fixture/model.{source_format}", pamt_path=root / "0.pamt",
            paz_file=root / "0.paz", offset=0, comp_size=1, orig_size=1, flags=0, paz_index=0,
        ),
        companion_entry=None, texture_entries_by_normalized_path={},
        texture_entries_by_basename={}, sidecar_entries_by_texture_path=None,
        sidecar_entries_by_texture_basename=None, loose_search_roots=(),
        render_settings=ModelPreviewRenderSettings(use_textures_by_default=True),
        native_preview_core_enabled=True, native_preview_core_cache_root=root / "native-cache",
        native_preview_package_cache_root=root / "model-cache",
        native_preview_package_cache_key="material-recovery", native_preview_package_cache_mode="balanced",
        native_preview_package_cache_max_bytes=16 * 1024 * 1024,
        native_preview_package_cache_target_bytes=8 * 1024 * 1024,
        progressive_material_preview=True,
    )


@pytest.mark.parametrize(
    ("resolution", "dds_count", "base_missing", "warn"),
    [("none", 0, 1, True), ("disabled", 0, 1, False), ("none", 0, 0, False), ("resolved", 1, 0, False)],
)
def test_unresolved_standalone_texture_status_preserves_disabled_and_authored_color_modes(
    resolution: str, dds_count: int, base_missing: int, warn: bool,
) -> None:
    original = ArchivePreviewResult(status="ok", title="leaf.pam", native_preview_diagnostics={
        "native_texture_resolution": resolution, "dds_extracted": dds_count,
        "batch_count": 1, "base_missing_count": base_missing,
    })
    result = with_preview_material_warning(original)
    assert bool(result.warning_badge) is warn
    assert bool(result.native_preview_diagnostics.get("texture_preparation_error")) is warn
    assert "texture_preparation_error" not in original.native_preview_diagnostics


def _install_native_job(monkeypatch, root: Path, worker: ArchivePreviewWorker, damage: str = "") -> list[bool]:
    source, *_ = _write_schema8_preview_core_fixture(root)
    geometry = json.loads((source / "manifest.json").read_text(encoding="utf-8"))
    geometry["format"] = worker.entry.extension[1:]
    geometry["source_path"] = worker.entry.path
    geometry["batches"][0]["dds_textures"] = {}
    geometry["batches"][0]["material_layers"] = [{
        "owner_wrapper_item_id": "", "material_wrapper_index": -1, "layer_role": "base",
        "mask_channel": "r", "source_parameter": "", "mask_parameter": "",
    }]
    textured = copy.deepcopy(geometry)
    textured["material_conservation"].update({
        "declared_parameter_count": 1, "transported_parameter_count": 1,
        "unresolved_texture_count": 1, "conserved": False,
        "findings": ["source_dds_unavailable:fixture:model:0:_baseColorTexture:texture/missing.dds"],
    })
    if damage == "cross_owner":
        textured["material_conservation"]["findings"].append("cross_owner_binding:fixture")
    elif damage == "lost_parameter":
        textured["material_conservation"]["transported_parameter_count"] = 0
    calls: list[bool] = []

    def job(_entry, **kwargs):
        use_textures = kwargs["render_settings"].use_textures_by_default
        calls.append(use_textures)
        output = Path(kwargs["output_root"])
        if not use_textures and damage == "geometry_error":
            return NativePreviewCoreAttempt(status="error", fallback_reason="geometry decode failed")
        shutil.copytree(source, output, dirs_exist_ok=True)
        (output / "manifest.json").write_text(
            json.dumps(textured if use_textures else geometry), encoding="utf-8",
        )
        if damage == "cancel":
            worker.stop()
        return NativePreviewCoreAttempt(status="ok", package_path=str(output), elapsed_ms=5.0)

    monkeypatch.setattr("cdmw.workers.archive_preview_native.run_native_preview_core_preview_job", job)
    return calls


@pytest.mark.parametrize("source_format", ("pac", "pam", "pamlod"))
def test_missing_materials_publish_geometry_with_warning_and_preserve_warm_cache(
    tmp_path: Path, monkeypatch, source_format: str,
) -> None:
    worker = _worker(tmp_path, source_format)
    calls = _install_native_job(monkeypatch, tmp_path, worker)
    emitted = []
    worker.completed.connect(lambda _request, result: emitted.append(result))

    attempt = worker._try_native_preview_core()
    assert attempt.succeeded
    assert attempt.elapsed_ms == 10.0
    result = worker._native_preview_core_result(attempt, {})

    assert calls == [True, False]
    assert worker.render_settings.use_textures_by_default is True
    assert result.status == "ok"
    assert result.preferred_view == "model"
    assert result.warning_badge == "Textures unavailable"
    assert "texture/missing.dds" in result.warning_text
    assert result.native_preview_diagnostics["rust_preview_material_quality"] == "geometry"
    assert validate_rust_preview_package(Path(result.dotnet_preview_package_path)) == ()
    assert emitted == []  # No misleading intermediate textured result.
    cached = worker._durable_native_preview_cache_payload()
    assert cached is not None
    assert cached.result.warning_text == result.warning_text
    assert cached.result.dotnet_preview_package_path == result.dotnet_preview_package_path


@pytest.mark.parametrize("damage", ("cross_owner", "lost_parameter", "geometry_error", "cancel"))
def test_geometry_recovery_preserves_validation_failures_and_cancellation(
    tmp_path: Path, monkeypatch, damage: str,
) -> None:
    worker = _worker(tmp_path)
    calls = _install_native_job(monkeypatch, tmp_path, worker, damage)

    if damage == "cancel":
        with pytest.raises(RunCancelled):
            worker._try_native_preview_core()
    else:
        attempt = worker._try_native_preview_core()
        assert not attempt.succeeded
        if damage == "geometry_error":
            assert attempt.fallback_reason == "geometry decode failed"
    assert calls == ([True, False] if damage == "geometry_error" else [True])
    assert not tuple((tmp_path / "model-cache" / "packages").glob("_staging_*"))


@pytest.mark.parametrize("source_failure", (False, True, "unresolved"))
def test_geometry_recovery_does_not_automatically_retry_unavailable_textures(source_failure: bool | str) -> None:
    app = QApplication.instance() or QApplication([])
    requested = []
    applied = []
    host = SimpleNamespace(
        archive_preview_request_id=7, archive_preview_requested_loose=False,
        _show_archive_preview_result=lambda *args, **kwargs: 0.0,
        _archive_preview_timing_summary=lambda *args: "",
        _refresh_archive_preview_details_text=lambda: None,
        _current_model_preview_render_settings=lambda: ModelPreviewRenderSettings(use_textures_by_default=True),
        _archive_active_package_has_textures=lambda: False,
        _request_archive_preview_textures=lambda *, automatic: requested.append(automatic),
        _log_archive_preview_timing_if_needed=lambda *args: applied.append(args),
    )
    result = ArchivePreviewResult(
        status="ok", title="fixture", preferred_view="model", dotnet_preview_package_path="fixture-package",
        native_preview_diagnostics={"texture_preparation_error": "missing.dds"} if source_failure else {},
    )
    if source_failure == "unresolved":
        result.native_preview_diagnostics = {
            "native_texture_resolution": "none", "dds_extracted": 0,
            "batch_count": 1, "base_missing_count": 1,
        }
        result = with_preview_material_warning(result)

    ArchivePreviewResultMixin._apply_archive_preview_result(host, result, request_id=7)
    app.processEvents()

    assert len(applied) == 1
    assert requested == ([] if source_failure else [True])
    assert host.current_archive_preview_result.preferred_view == "model"
