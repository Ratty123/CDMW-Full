"""Run real Preview Core packages through Windows path and error boundaries."""

from __future__ import annotations

from dataclasses import replace
import hashlib
import json
import os
from pathlib import Path
import struct

import pytest

from cdmw.rendering import native_preview_core as core
from tests.test_native_preview_core import _entry


def _grid_pac() -> bytes:
    """Four identical LODs of a tessellated square with valid UVs/normals."""
    vertices = bytearray(9 * 40)
    for y in range(3):
        for x in range(3):
            offset = (y * 3 + x) * 40
            struct.pack_into("<HHH", vertices, offset, x * 16383, y * 16383, 0)
            struct.pack_into("<ee", vertices, offset + 8, x / 2, y / 2)
            struct.pack_into("<I", vertices, offset + 16, (512 << 10) | (512 << 20))
    faces = [(y * 3 + x, y * 3 + x + 1, (y + 1) * 3 + x) for y in range(2) for x in range(2)]
    faces += [(y * 3 + x + 1, (y + 1) * 3 + x + 1, (y + 1) * 3 + x) for y in range(2) for x in range(2)]
    geometry = bytes(vertices) + b"".join(struct.pack("<HHH", *face) for face in faces)
    metadata = bytearray(37)
    metadata[4] = 4
    metadata.extend(b"\x04grid\x04grid")
    descriptor = bytearray(64)
    descriptor[0] = 1
    struct.pack_into("<8f", descriptor, 3, 0, 0, 0, 0, 0, 1, 1, 1)
    descriptor[35:40] = bytes((4, 0, 1, 2, 3))
    for lod in range(4):
        struct.pack_into("<H", descriptor, 40 + lod * 2, 9)
        struct.pack_into("<I", descriptor, 48 + lod * 4, 24)
        vertex_offset = 0x50 + len(metadata) + len(descriptor) + (3 - lod) * len(geometry)
        struct.pack_into("<I", metadata, 5 + lod * 4, vertex_offset)
        struct.pack_into("<I", metadata, 21 + lod * 4, vertex_offset + len(vertices))
    metadata.extend(descriptor)
    header = bytearray(0x50)
    header[:4] = b"PAR "
    for index, size in enumerate([len(metadata)] + [len(geometry)] * 4):
        struct.pack_into("<II", header, 0x10 + index * 8, 0, size)
    return bytes(header + metadata) + geometry * 4


@pytest.fixture
def native_helper(monkeypatch):
    binary = core.default_native_preview_core_path()
    if os.name != "nt" or not binary.is_file():
        pytest.skip("built Windows Preview Core helper is required")
    core.shutdown_native_preview_core_service()
    monkeypatch.setattr(core, "find_native_preview_core_binary", lambda: binary)
    yield binary
    core.shutdown_native_preview_core_service()


def _prepared_entry(source: Path):
    data = _grid_pac()
    source.parent.mkdir(parents=True, exist_ok=True)
    source.write_bytes(data)
    return replace(
        _entry(), path="fixture/grid.pac", flags=0, orig_size=len(data), comp_size=len(data),
        prepared_path=source, prepared_size=len(data), prepared_sha256=hashlib.sha256(data).hexdigest(),
    )


def _run(entry, root: Path, *, service=False):
    return core.run_native_preview_core_preview_job(
        entry, cache_root=root / "cache", output_root=root / "package",
        dependency_entries=(entry,), dependency_entries_complete=True, use_service=service,
    )


@pytest.mark.parametrize("length,unicode_name,service", [(0, False, False), (279, False, False), (440, True, False), (440, True, True)])
def test_native_package_from_deep_prepared_path(native_helper, tmp_path: Path, length, unicode_name, service):
    root = tmp_path / ("space \u00e5\u4e2d\U0001f680" if unicode_name else "space folder")
    while length and len(str(root / "model.pac")) < length:
        remaining = length - len(str(root / "model.pac"))
        root = root.with_name(root.name + "d") if remaining == 1 else root / ("d" * min(80, remaining - 1))
    source = root / "model.pac"
    assert not length or len(str(source)) == length
    entry = _prepared_entry(source)
    before = source.read_bytes()
    result = _run(entry, root, service=service)
    assert result.succeeded, result.fallback_reason
    assert result.diagnostics["vertex_count"] == 24  # Canonical batches expand triangle vertices.
    assert result.diagnostics["face_count"] == 8
    package = Path(result.package_path)
    manifest = (package / "manifest.json").read_text(encoding="utf-8")
    assert json.loads(manifest)["schema_version"] >= 8
    assert "\\\\\\\\?\\\\" not in manifest
    assert any(path.is_file() for path in (package / "geometry").iterdir())
    assert source.read_bytes() == before


def test_missing_prepared_file_reports_os_cause_and_stops_retry(native_helper, tmp_path: Path):
    entry = _prepared_entry(tmp_path / "missing.pac")
    entry.prepared_path.unlink()
    result = _run(entry, tmp_path)
    assert not result.succeeded
    assert result.diagnostics["file_error"]["kind"] == "missing"
    assert result.diagnostics["file_error"]["os_error"] in (2, 3)
    assert result.diagnostics["file_error"]["path_length"] == len(str(entry.prepared_path))
    assert result.diagnostics["retryable"] is False
    assert "path length" in result.fallback_reason
    assert "preparation failed" in result.diagnostic_line()
    from types import SimpleNamespace
    from cdmw.workers.archive_preview_native import ArchivePreviewNativeMixin
    owner = SimpleNamespace(entry=entry, sidecar_generation=1)
    failure = ArchivePreviewNativeMixin._native_preview_core_failure_result(owner, result, {})
    assert "Refresh the archive catalogue" in failure.detail_text
    assert "will retry" not in failure.detail_text
    assert failure.native_preview_diagnostics["retryable"] is False


@pytest.mark.parametrize("kind", ["access_denied", "invalid_path", "locked"])
def test_native_file_error_categories(native_helper, tmp_path: Path, kind):
    import ctypes
    from ctypes import wintypes

    entry = _prepared_entry(tmp_path / "model.pac")
    handle = None
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    if kind == "access_denied":
        entry.prepared_path.unlink()
        entry.prepared_path.mkdir()
    elif kind == "invalid_path":
        entry = replace(entry, prepared_path=tmp_path / ("x" * 256 + ".pac"))
    else:
        kernel.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p,
                                       wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        kernel.CreateFileW.restype = wintypes.HANDLE
        kernel.CloseHandle.argtypes = [wintypes.HANDLE]
        handle = kernel.CreateFileW(str(entry.prepared_path), 0x80000000, 0, None, 3, 0, None)
        assert handle != ctypes.c_void_p(-1).value, ctypes.get_last_error()
    try:
        result = _run(entry, tmp_path)
        assert not result.succeeded
        assert result.diagnostics["file_error"]["kind"] == kind
        assert result.diagnostics["retryable"] is (kind == "locked")
    finally:
        if handle is not None:
            kernel.CloseHandle(handle)
