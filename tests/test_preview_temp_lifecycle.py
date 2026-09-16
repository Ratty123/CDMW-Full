from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from cdmw.domain.cancellation import RunCancelled
from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.rendering import native_preview_temp
from cdmw.rendering.native_preview_core import NativePreviewCoreAttempt
from cdmw.services import mesh_rust_preview_cache as cache
from cdmw.services.mesh_rust_preview_package import validate_rust_preview_package
from cdmw.ui.archive_browser import reference_preview
from tests.test_native_preview_core import _entry
from tests.test_rust_preview_production_cutover import _write_schema8_preview_core_fixture


@pytest.mark.parametrize("route", ["composed", "native", "model"])
@pytest.mark.parametrize("mode,budget", [("off", 1024), ("balanced", 0)])
@pytest.mark.parametrize("outcome", ["success", "cancelled", "error", "late_cancel"])
def test_transient_build_owns_failure_cleanup(tmp_path, monkeypatch, route, mode, budget, outcome):
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    unrelated = cache_root / "keep.txt"
    unrelated.write_bytes(b"other cache data")
    cancelled = False

    def build(output: Path):
        nonlocal cancelled
        output.mkdir(parents=True)
        (output / "payload.bin").write_bytes(b"partial package")
        if outcome == "cancelled":
            raise RunCancelled("cancelled in builder")
        if outcome == "error":
            raise ValueError("builder failed")
        cancelled = outcome == "late_cancel"
        return SimpleNamespace(package_dir=output)

    kwargs = dict(
        cache_root=cache_root, archive_identity="fixture", cache_mode=mode,
        max_bytes=budget, target_bytes=0, cancelled=lambda: cancelled,
    )
    if route == "composed":
        invoke = lambda: cache.build_or_lookup_rust_preview_package_with_builder(builder=build, **kwargs)
    elif route == "native":
        source = tmp_path / "source"
        source.mkdir()
        (source / "manifest.json").write_text('{"schema_version": 8}', encoding="utf-8")
        monkeypatch.setattr(cache._PreviewCorePackageRequest, "build", lambda self, output, *_: build(output))
        invoke = lambda: cache.build_or_lookup_rust_preview_package(source, **kwargs)
    else:
        monkeypatch.setattr(cache._ModelPreviewPackageRequest, "build", lambda self, output, *_: build(output))
        invoke = lambda: cache.build_or_lookup_rust_preview_package_from_model(object(), **kwargs)
    if outcome == "success":
        result = invoke()
        assert (result.package_dir / "payload.bin").read_bytes() == b"partial package"
        assert len(list(cache_root.glob("cdmw_rust_preview_*"))) == 1
    else:
        with pytest.raises(ValueError if outcome == "error" else RunCancelled):
            invoke()
        assert not list(cache_root.glob("cdmw_rust_preview_*"))
    assert unrelated.read_bytes() == b"other cache data"


@pytest.mark.parametrize("route", ["native", "model"])
@pytest.mark.parametrize("durable", [False, True])
@pytest.mark.parametrize("outcome", ["success", "error", "callback_cancel", "before_delivery_cancel", "after_delivery_cancel"])
def test_fast_package_handoff_releases_only_unaccepted_transients(tmp_path, monkeypatch, route, durable, outcome):
    cache_root = tmp_path / "cache"
    cache_root.mkdir()
    unrelated = cache_root / "keep.txt"
    unrelated.write_bytes(b"other cache data")
    cancelled = False
    direct_packages = []
    received = []
    request_type = cache._PreviewCorePackageRequest if route == "native" else cache._ModelPreviewPackageRequest
    original_build = request_type.build_or_lookup_quality

    def build(self, quality, *args):
        nonlocal cancelled
        package = original_build(self, quality, *args)
        if quality == "direct":
            direct_packages.append(package)
            cancelled = outcome == "before_delivery_cancel"
        return package

    monkeypatch.setattr(request_type, "build_or_lookup_quality", build)

    def receive(package):
        nonlocal cancelled
        received.append(package)
        assert not validate_rust_preview_package(package.package_dir)
        if outcome == "error":
            raise ValueError("receiver failed before accepting the package")
        if outcome == "callback_cancel":
            raise RunCancelled("receiver cancelled before accepting the package")
        cancelled = outcome == "after_delivery_cancel"

    kwargs = dict(
        cache_root=cache_root, archive_identity="handoff-fixture",
        cache_mode="balanced" if durable else "off",
        max_bytes=64 * 1024 * 1024, target_bytes=48 * 1024 * 1024,
        cancelled=lambda: cancelled, fast_package_ready=receive,
    )
    if route == "native":
        source, *_ = _write_schema8_preview_core_fixture(tmp_path)
        invoke = lambda: cache.build_or_lookup_rust_preview_package(source, **kwargs)
    else:
        model = ModelPreviewData(path="fixture.obj", format="obj", meshes=[ModelPreviewMesh(
            material_name="fixture", positions=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)],
            normals=[(0., 0., 1.)] * 3, texture_coordinates=[(0., 0.), (1., 0.), (0., 1.)],
            indices=[0, 1, 2],
        )])
        invoke = lambda: cache.build_or_lookup_rust_preview_package_from_model(model, **kwargs)
    if outcome.endswith("cancel"):
        with pytest.raises(RunCancelled):
            invoke()
    else:
        full = invoke()
        assert not validate_rust_preview_package(full.package_dir)
    assert len(direct_packages) == 1
    direct = direct_packages[0].package_dir
    accepted = outcome in {"success", "after_delivery_cancel"}
    assert direct.exists() is (durable or accepted)
    assert len(received) == (0 if outcome == "before_delivery_cancel" else 1)
    if not durable and not accepted:
        assert not direct.parent.exists()
    assert unrelated.read_bytes() == b"other cache data"


@pytest.mark.parametrize("outcome", ["success", "conversion_error", "conversion_cancel", "native_error"])
def test_reference_preview_releases_native_job_after_conversion(tmp_path, monkeypatch, outcome):
    monkeypatch.setattr(native_preview_temp.tempfile, "tempdir", str(tmp_path))
    monkeypatch.setattr(native_preview_temp, "_swept", True)
    job_root = native_preview_temp.create_preview_job_root()
    source, geometry, _identities, texture = _write_schema8_preview_core_fixture(job_root)
    attempt = NativePreviewCoreAttempt(
        status="error" if outcome == "native_error" else "ok",
        package_path=str(source), job_root_path=str(job_root),
    )
    monkeypatch.setattr(reference_preview, "run_native_preview_core_preview_job", lambda *a, **kw: attempt)
    if outcome.startswith("conversion_"):
        def fail_conversion(*args, **kwargs):
            assert source.exists(), "native input must survive until conversion finishes"
            if outcome == "conversion_cancel":
                raise RunCancelled("cancelled conversion")
            raise ValueError("failed conversion")
        monkeypatch.setattr(reference_preview, "build_or_lookup_dotnet_preview_package", fail_conversion)

    results = []
    def run_task(*, task, on_complete, **kwargs):
        on_complete(task(lambda message: None))

    owner = SimpleNamespace(
        _current_archive_preview_result_for_reference_entry=lambda entry: None,
        _find_archive_preview_companion_entry=lambda *args, **kwargs: None,
        _current_model_preview_render_settings=lambda: SimpleNamespace(),
        _native_preview_core_cache_root=lambda: tmp_path / "native-cache",
        _native_preview_package_cache_root=lambda: tmp_path / "rust-cache",
        _native_preview_package_cache_mode=lambda: "balanced",
        _native_preview_package_cache_budget=lambda: (64 * 1024 * 1024, 48 * 1024 * 1024),
        _archive_model_renderer_backend=lambda: reference_preview.ARCHIVE_MODEL_RENDERER_D3D11,
        archive_package_root_edit=SimpleNamespace(text=lambda: ""),
        archive_sidecar_generation=0,
        shell=SimpleNamespace(_run_utility_task=run_task, set_status_message=lambda *a, **kw: None),
        _show_archive_reference_preview_dialog=lambda entry, result: results.append(result),
    )
    try:
        if outcome.startswith("conversion_"):
            with pytest.raises(RunCancelled if outcome == "conversion_cancel" else ValueError):
                reference_preview.ArchiveReferencePreviewMixin._open_archive_reference_preview_entry(owner, _entry())
        else:
            reference_preview.ArchiveReferencePreviewMixin._open_archive_reference_preview_entry(owner, _entry())
            assert results[0].status == ("error" if outcome == "native_error" else "ok")
            if outcome == "success":
                package = Path(results[0].dotnet_preview_package_path)
                assert not validate_rust_preview_package(package)
                payloads = [path.read_bytes() for path in package.iterdir() if path.is_file()]
                assert geometry in payloads
                assert texture in payloads
        assert not job_root.exists()
        assert job_root not in native_preview_temp._owners
    finally:
        native_preview_temp.remove_preview_job_root(job_root)


@pytest.mark.parametrize("job_root_path", ["", "unowned"])
def test_releasing_attempt_preserves_caller_owned_output(tmp_path, job_root_path):
    payload = tmp_path / "keep.bin"
    payload.write_bytes(b"caller output")
    NativePreviewCoreAttempt(
        status="ok", package_path=str(tmp_path),
        job_root_path=str(tmp_path) if job_root_path else "",
    ).release_temporary_files()
    assert payload.read_bytes() == b"caller output"
