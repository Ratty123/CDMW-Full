from __future__ import annotations

import base64
import json
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

import pytest

from cdmw.core import texture_native
from cdmw.core.texture_decode_cache import (
    preview_cache_lock_registry_size,
    preview_png_is_valid,
    preview_sidecar_path,
    publish_preview_pair,
)
from cdmw.core.texture_pipeline import preview

_MINIMAL_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk+A8AAQUBAScY42YAAAAASUVORK5CYII="
)


def _minimal_dds() -> bytes:
    header = bytearray(124)
    header[0:4] = (124).to_bytes(4, "little")
    header[4:8] = (0x0002100F).to_bytes(4, "little")
    header[8:12] = (4).to_bytes(4, "little")
    header[12:16] = (4).to_bytes(4, "little")
    header[24:28] = (1).to_bytes(4, "little")
    header[72:76] = (32).to_bytes(4, "little")
    header[76:80] = (0x4).to_bytes(4, "little")
    header[80:84] = b"DXT1"
    return b"DDS " + bytes(header) + (b"\0" * 8)


def _cache_path(root: Path, category: str, key: str) -> Path:
    return root / "cache" / category / key


def test_directxtex_same_key_concurrency_invokes_helper_once(tmp_path: Path) -> None:
    binary = tmp_path / "cd-texture-dx.exe"
    source = tmp_path / "shared.dds"
    binary.write_bytes(b"stub")
    source.write_bytes(_minimal_dds())
    calls = 0
    calls_lock = threading.Lock()

    def fake_run(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
        nonlocal calls
        with calls_lock:
            calls += 1
        time.sleep(0.05)
        job_path = Path(command[2])
        report_path = Path(command[3])
        jobs = json.loads(job_path.read_text(encoding="utf-8"))["jobs"]
        items = []
        for job in jobs:
            output = Path(job["output"])
            output.write_bytes(_MINIMAL_PNG)
            items.append({"status": "decoded", "source_path": job["input"], "output_path": job["output"]})
        report_path.write_text(json.dumps({"status": "ok", "items": items}), encoding="utf-8")
        return 0, "", ""

    with (
        patch.object(texture_native, "find_directxtex_texture_binary", return_value=binary),
        patch.object(texture_native, "run_process_with_cancellation", side_effect=fake_run),
        patch.object(texture_native, "app_temp_cache_path", side_effect=lambda category, key: _cache_path(tmp_path, category, key)),
        patch.object(texture_native, "request_app_temp_cache_prune"),
        ThreadPoolExecutor(max_workers=8) as pool,
    ):
        results = list(
            pool.map(
                lambda _index: texture_native.ensure_directxtex_dds_preview_png(source, max_dimension=512),
                range(8),
            )
        )
        warm_hit = texture_native.ensure_directxtex_dds_preview_png(source, max_dimension=512)

    assert calls == 1
    assert all(path == results[0] for path in results)
    assert warm_hit == results[0]
    assert results[0] is not None and texture_native._cached_preview_is_valid(results[0])


def test_obsolete_preview_argument_warns_and_uses_native_backend(tmp_path: Path) -> None:
    obsolete_backend = tmp_path / "texconv.exe"
    source = tmp_path / "shared.dds"
    native_preview = tmp_path / "shared.png"
    obsolete_backend.write_bytes(b"stub")
    source.write_bytes(_minimal_dds())
    native_preview.write_bytes(_MINIMAL_PNG)

    with patch.object(texture_native, "ensure_native_dds_preview_png", return_value=native_preview) as native_decode:
        with pytest.warns(DeprecationWarning, match="obsolete and ignored"):
            result = preview.ensure_dds_preview_png(obsolete_backend, source)

    assert result == native_preview
    native_decode.assert_called_once_with(
        source.resolve(),
        max_dimension=4096,
        slot_kind="base",
        normal_space="auto",
        stop_event=None,
    )


def test_failed_atomic_preview_publication_exposes_no_partial_pair(tmp_path: Path) -> None:
    staged = tmp_path / "staged.png"
    final = tmp_path / "cache" / "final.png"
    staged.write_bytes(_MINIMAL_PNG)
    real_replace = os.replace

    def fail_png_publish(source: str | Path, target: str | Path) -> None:
        if Path(target) == final:
            raise OSError("forced PNG publication failure")
        real_replace(source, target)

    with patch("cdmw.core.texture_decode_cache.os.replace", side_effect=fail_png_publish):
        with pytest.raises(OSError, match="forced PNG publication failure"):
            publish_preview_pair(staged, final, {"status": "decoded"})

    assert not final.exists()
    assert not preview_sidecar_path(final).exists()


def test_corrupt_helper_png_is_not_published(tmp_path: Path) -> None:
    binary = tmp_path / "cd-texture-dx.exe"
    source = tmp_path / "broken.dds"
    binary.write_bytes(b"stub")
    source.write_bytes(_minimal_dds())

    def fake_run(command: list[str], **_kwargs: object) -> tuple[int, str, str]:
        job_path = Path(command[2])
        report_path = Path(command[3])
        job = json.loads(job_path.read_text(encoding="utf-8"))["jobs"][0]
        Path(job["output"]).write_bytes(b"not-a-png")
        report_path.write_text(
            json.dumps({"status": "ok", "items": [{"status": "decoded", "output_path": job["output"]}]}),
            encoding="utf-8",
        )
        return 0, "", ""

    with (
        patch.object(texture_native, "find_directxtex_texture_binary", return_value=binary),
        patch.object(texture_native, "run_process_with_cancellation", side_effect=fake_run),
        patch.object(texture_native, "app_temp_cache_path", side_effect=lambda category, key: _cache_path(tmp_path, category, key)),
    ):
        result = texture_native.ensure_directxtex_dds_preview_png(source, max_dimension=512)

    assert result is None
    assert not tuple((tmp_path / "cache").rglob("*.png"))


def test_preview_png_validation_rejects_late_chunk_corruption(
    tmp_path: Path,
) -> None:
    valid = tmp_path / "valid.png"
    corrupt = tmp_path / "corrupt.png"
    valid.write_bytes(_MINIMAL_PNG)
    corrupt_bytes = bytearray(_MINIMAL_PNG)
    corrupt_bytes[-20] ^= 0xFF
    corrupt.write_bytes(corrupt_bytes)

    assert preview_png_is_valid(valid) is True
    assert preview_png_is_valid(corrupt) is False


def test_failure_diagnostics_and_lock_registry_are_bounded() -> None:
    texture_native.directxtex_texture_failure_reports(clear=True)
    for index in range(256):
        texture_native._record_directxtex_failure(
            binary=None,
            operation=f"failure-{index}",
            returncode=index,
        )
    reports = texture_native.directxtex_texture_failure_reports(clear=True)

    assert len(reports) == 128
    assert reports[0]["operation"] == "failure-128"
    assert preview_cache_lock_registry_size() == 64
