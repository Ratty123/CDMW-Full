"""A transient DDS decoder failure must retain its cause and allow a retry."""

from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import struct
import threading

import pytest
from PySide6.QtGui import QImage

from cdmw.core import texture_native
from cdmw.core.texture_pipeline.preview import ensure_dds_display_preview_png
from cdmw.models import ArchiveEntry, ArchivePreviewResult, RunCancelled
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin
from cdmw.workers.archive_preview_workers import ArchivePreviewWorker


def _dds_bytes():
    header = bytearray(128)
    header[:4] = b"DDS "
    struct.pack_into("<7I", header, 4, 124, 0x81007, 4, 4, 8, 0, 1)
    struct.pack_into("<II4s", header, 76, 32, 4, b"DXT1")
    struct.pack_into("<I", header, 108, 0x1000)
    return bytes(header) + b"\0" * 8


class _Cache(ArchivePreviewCacheMixin):
    def __init__(self):
        self.archive_preview_cache = OrderedDict()

    def _trim_archive_preview_cache(self):
        pass


@pytest.fixture
def decode_attempt(tmp_path, monkeypatch):
    raw = _dds_bytes()
    paz = tmp_path / "0.paz"
    paz.write_bytes(raw)
    entry = ArchiveEntry("texture/owned.dds", tmp_path / "0.pamt", paz, 0, len(raw), len(raw), 0, 0)
    binary = tmp_path / "cd-texture-dx.exe"
    binary.write_bytes(b"owned helper placeholder")
    monkeypatch.setattr(texture_native, "find_directxtex_texture_binary", lambda: binary)
    state = {"error": "LoadFromDDSFile failed: 0x8007000d", "calls": 0}

    def run(command, **_kwargs):
        state["calls"] += 1
        request = json.loads(Path(command[2]).read_text(encoding="utf-8"))["jobs"][0]
        result = {"output_path": request["output"], "source_path": request["input"]}
        if state["error"]:
            result.update(status="error", message=state["error"])
        else:
            image = QImage(4, 4, QImage.Format_RGBA8888)
            image.fill(0xFF00FF00)
            assert image.save(request["output"], "PNG")
            result.update(status="decoded", width=4, height=4)
        Path(command[3]).write_text(json.dumps({"status": "ok", "items": [result]}), encoding="utf-8")
        return (2 if state["error"] else 0), "", ""

    monkeypatch.setattr(texture_native, "run_process_with_cancellation", run)

    def preview(snapshot=None):
        worker = ArchivePreviewWorker(
            1, entry, None, {}, {}, None, None, (),
            full_preview_cache_key="owned", preview_cache_snapshot=snapshot,
        )
        emitted = []
        worker.completed.connect(lambda _request, result: emitted.append(result))
        worker.run()
        assert len(emitted) == 1
        return emitted[0]

    return state, preview


def test_archive_dds_failure_preserves_native_decoder_reason(decode_attempt):
    state, preview = decode_attempt
    result = preview()
    assert result.warning_badge == "Raw bytes"
    assert "Decoded preview failed:" in result.detail_text
    assert state["error"] in result.detail_text


def test_raw_fallback_is_not_cached_and_reselection_recovers(decode_attempt):
    state, preview = decode_attempt
    cache = _Cache()
    failed = preview()
    cache._store_cached_archive_preview_result("owned", failed)
    assert "owned" not in cache.archive_preview_cache

    state["error"] = ""
    recovered = preview(cache.archive_preview_cache)
    assert state["calls"] == 2
    assert recovered.preferred_view == "image"
    assert not recovered.warning_badge
    assert not recovered.preview_image.isNull()
    cache._store_cached_archive_preview_result("owned", recovered)
    assert "owned" in cache.archive_preview_cache


def test_worker_retries_an_existing_raw_fallback_snapshot(decode_attempt):
    state, preview = decode_attempt
    failed = preview()
    state["error"] = ""
    recovered = preview({"owned": failed})
    assert state["calls"] == 2
    assert recovered.preferred_view == "image"
    assert not recovered.warning_badge


def test_repeated_decoder_failure_stays_an_explicit_failure(decode_attempt):
    state, preview = decode_attempt
    first = preview()
    second = preview({"owned": first})
    assert state["calls"] == 2
    assert second.warning_badge == "Raw bytes"
    assert state["error"] in second.detail_text
    assert not second.preview_image_path
    assert second.preview_image is None


def test_ui_cache_discards_a_raw_fallback_but_keeps_normal_binary_previews():
    cache = _Cache()
    cache.archive_preview_cache["failed"] = ArchivePreviewResult(status="ok", warning_badge="Raw bytes")
    assert cache._get_cached_archive_preview_result("failed") is None
    assert "failed" not in cache.archive_preview_cache
    assert cache._archive_preview_result_cacheable(ArchivePreviewResult(status="ok", preferred_view="text"))


def test_parallel_dds_failures_keep_their_own_diagnostics(tmp_path, monkeypatch):
    paths = [tmp_path / name for name in ("first.dds", "second.dds")]
    for path in paths:
        path.write_bytes(_dds_bytes())
    barrier = threading.Barrier(2)

    def fail(path, **_kwargs):
        texture_native._record_directxtex_failure(
            binary=None, operation="batch-preview-json", returncode=2,
            source_path=path, stderr=f"decode failure for {path.name}", reason="native_decode_failed",
        )
        barrier.wait(timeout=5)
        return None

    monkeypatch.setattr(texture_native, "ensure_directxtex_dds_preview_png", fail)

    def preview(path):
        with pytest.raises(ValueError) as error:
            ensure_dds_display_preview_png(path)
        return str(error.value)

    with ThreadPoolExecutor(max_workers=2) as pool:
        errors = list(pool.map(preview, paths))
    for index, error in enumerate(errors):
        assert f"decode failure for {paths[index].name}" in error
        assert paths[1 - index].name not in error


def test_dds_preview_cancellation_stays_cancellation(tmp_path, monkeypatch):
    path = tmp_path / "cancelled.dds"
    path.write_bytes(_dds_bytes())

    def cancel(*_args, **_kwargs):
        raise RunCancelled("cancelled")

    monkeypatch.setattr(texture_native, "ensure_directxtex_dds_preview_png", cancel)
    with pytest.raises(RunCancelled):
        ensure_dds_display_preview_png(path)


def test_optional_native_preview_keeps_none_and_does_not_reuse_old_errors(tmp_path, monkeypatch):
    path = tmp_path / "optional.dds"
    path.write_bytes(_dds_bytes())
    texture_native._record_directxtex_failure(
        binary=None, operation="batch-preview-json", returncode=2,
        source_path=path, stderr="old failure from another request",
    )
    monkeypatch.setattr(texture_native, "ensure_directxtex_dds_preview_png", lambda *_args, **_kwargs: None)
    assert texture_native.ensure_native_dds_preview_png(path, max_dimension=64) is None
    with pytest.raises(ValueError) as error:
        ensure_dds_display_preview_png(path)
    assert "old failure" not in str(error.value)
