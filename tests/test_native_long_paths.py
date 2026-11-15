"""Every native program CDMW ships reads and writes a 300-character path (2026-11-13).

Windows refuses paths over 260 characters unless they carry the extended-length
prefix or the machine has long paths switched on, which CDMW must not change. A
long user or profile name pushes CDMW's own folders past that (a probe journey
lost its texturing that way). The C++ programs now open every file through
native/common/long_path.hpp; Rust's standard library and .NET add the prefix
themselves. Each test hands a program plain paths of 300 characters or more, in
the folder layout CDMW uses, and checks what it wrote.

Every program here is the built one; a test skips when it is not built.
"""

from __future__ import annotations

import ctypes
import json
import os
import struct
import subprocess
from pathlib import Path

import pytest

from tests.long_path_support import LONG_PATH_LENGTH, exists, long_folder, read_bytes, write_bytes

ROOT = Path(__file__).resolve().parents[1]
pytestmark = pytest.mark.skipif(os.name != "nt", reason="the MAX_PATH limit is Windows'")


def _built(relative: str) -> Path:
    path = ROOT / relative
    if not path.is_file():
        pytest.skip(f"{relative} is not built")
    return path


def _run(argv: list[object], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run([str(item) for item in argv], capture_output=True, text=True, timeout=120, **kwargs)


def _report(path: Path) -> dict:
    return json.loads(read_bytes(path).decode("utf-8"))


def _dxt5_dds() -> bytes:
    data = bytearray(144)
    data[:4] = b"DDS "
    struct.pack_into("<7I", data, 4, 124, 0x81007, 4, 4, 16, 0, 1)
    struct.pack_into("<II4s", data, 76, 32, 4, b"DXT5")
    struct.pack_into("<I", data, 108, 0x1000)
    data[128] = 255
    return bytes(data)


def test_cd_texture_dx(tmp_path) -> None:
    helper = _built("native/cd_texture_dx/build/Release/cd-texture-dx.exe")
    folder = long_folder(tmp_path)
    source, output = folder / "source.dds", folder / "out" / "preview.png"
    job, report = folder / "job.json", folder / "report.json"
    write_bytes(source, _dxt5_dds())
    write_bytes(job, json.dumps({"jobs": [{"input": str(source), "output": str(output)}]}).encode())
    run = _run([helper, "batch-preview-json", job, report])
    assert run.returncode == 0, run.stderr
    result = _report(report)
    assert result["status"] == "ok" and result["items"][0]["status"] != "error", result
    assert read_bytes(output)[:8] == b"\x89PNG\r\n\x1a\n"


def _pamlod() -> bytes:
    geometry = 80 + 2 * 536
    data = bytearray(geometry + 6 * 20 + 12)
    struct.pack_into("<II", data, 0, 1, geometry)
    struct.pack_into("<3f", data, 28, 1, 1, 1)
    for index in range(2):
        at = 80 + index * 536
        struct.pack_into("<4I", data, at, 3, 3, index * 3, index * 3)
        data[at + 16:at + 26] = b"owned.dds\0"
        for vertex, xyz in enumerate(((0, 0, 0), (32767, 0, 0), (0, 32767, 0))):
            struct.pack_into("<3H", data, geometry + (index * 3 + vertex) * 20, *xyz)
    struct.pack_into("<6H", data, geometry + 120, 0, 1, 2, 0, 1, 2)
    return bytes(data)


def test_cdmw_preview_core(tmp_path) -> None:
    helper = _built("native/cdmw_preview_core/build/Release/cdmw-preview-core.exe")
    folder = long_folder(tmp_path)
    source, report = folder / "owned.pamlod", folder / "out" / "audit.json"
    write_bytes(source, _pamlod())
    run = _run([helper, "mesh-audit-job", source, report, "owned.pamlod"])
    assert run.returncode == 0, run.stderr
    result = _report(report)
    assert result["status"] == "ok" and result["vertex_count"] == 6, result


def test_cdmw_archive_accelerator(tmp_path) -> None:
    from cdmw.core.archive_format import hashlittle

    helper = _built("native/cdmw_archive_accelerator/build/Release/cdmw-archive-accelerator.exe")
    folder = long_folder(tmp_path)
    job, result = folder / "paths.bin", folder / "out" / "checksums.bin"
    name = b"character/model/body.pac"
    write_bytes(job, b"CDPH\x01\0\0\0" + struct.pack("<I", 1) + struct.pack("<I", len(name)) + name)
    os.makedirs("\\\\?\\" + str(result.parent), exist_ok=True)
    run = _run([helper, "path-checksum-job", job, result])
    assert run.returncode == 0, run.stderr
    data = read_bytes(result)
    assert len(data) == 16 and struct.unpack_from("<I", data, 12)[0] == hashlittle(name, 0x000C5EDE)


def test_cdmw_mesh_core(tmp_path) -> None:
    helper = _built("native/cdmw_mesh_core/build/Release/cdmw-mesh-core.exe")
    # Wide arguments too: a character outside the ANSI code page.
    folder = long_folder(tmp_path / "profile å中")
    job, report = folder / "job.json", folder / "report.json"
    write_bytes(job, json.dumps({"submeshes": [{"index": 0, "vertices": [[-1, 2, 0.5], [4, -3, 2], [0, 1, -2]],
                                                "face_count": 1}]}).encode())
    run = _run([helper, "mesh-metadata-json", job, report])
    assert run.returncode == 0, run.stderr
    result = _report(report)
    assert result["status"] == "ok" and result["total_vertices"] == 3, result
    assert result["bbox_max"] == [4, 2, 2]


def _package(root: Path) -> None:
    names = struct.pack("<I", 0xFFFFFFFF) + bytes([8]) + b"file.txt"
    write_bytes(root / "0000" / "0.paz", b"hello")
    write_bytes(root / "0000" / "0.pamt", struct.pack("<7I", 0, 1, 0, 0, 0, 0, 0) + struct.pack("<I", len(names))
                + names + struct.pack("<II", 0, 1) + struct.pack("<IIIIHH", 0, 0, 5, 5, 0, 0))


def test_cdmw_full_archive_core(tmp_path) -> None:
    library = _built("native/cdmw_full_archive_backend/build/Release/cdmw-full-archive-core.dll")
    folder = long_folder(tmp_path)
    package, index = folder / "game", folder / "cache" / "full.index"
    _package(package)
    build = ctypes.CDLL(str(library)).cdmw_full_archive_build_index_utf8
    build.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.POINTER(ctypes.c_uint64), ctypes.c_char_p,
                      ctypes.c_size_t]
    build.restype = ctypes.c_int
    count, error = ctypes.c_uint64(), ctypes.create_string_buffer(4096)
    status = build(str(package).encode(), str(index).encode(), ctypes.byref(count), error, len(error))
    assert status == 0, error.value.decode()
    data = read_bytes(index)
    assert count.value == 1 and b"file.txt" in data
    assert b"\\?\\" not in data and "\\?\\".encode("utf-16-le") not in data  # paths stay as given
    assert not exists(Path(str(index) + ".tmp"))


def test_cd_hkx(tmp_path) -> None:
    helper = _built("native/cd_hkx/target/release/cd-hkx.exe")
    fixture = (ROOT / "tests/fixtures/new_item_golden/character/bin__/meshphysics/1_pc/1_phm/weapon/"
               "1_onehandweapon/cd_phm_01_sword_0109.hkx")
    if not fixture.is_file():
        pytest.skip("the HKX fixture is not present")
    folder = long_folder(tmp_path)
    source, output = folder / "sword.hkx", folder / "out" / "sword.hkx"
    write_bytes(source, fixture.read_bytes())
    os.makedirs("\\\\?\\" + str(output.parent), exist_ok=True)
    run = _run([helper, "roundtrip-noedit", source, output])
    assert run.returncode == 0, run.stderr
    assert read_bytes(output) == fixture.read_bytes()


def test_cdmw_mesh_lab(tmp_path) -> None:
    helper = _built("native/rust_mesh_editor/build/Release/cdmw_mesh_lab.exe")
    folder = long_folder(tmp_path)
    source, output = folder / "texture.dds", folder / "out" / "texture.png"
    write_bytes(source, _dxt5_dds())
    os.makedirs("\\\\?\\" + str(output.parent), exist_ok=True)
    run = _run([helper, "--capture-dds-texture", source, output], cwd=str(helper.parent))
    if run.returncode != 0 and "adapter" in (run.stderr + run.stdout).lower():
        pytest.skip("no graphics adapter for the texture viewer")
    assert run.returncode == 0, run.stderr + run.stdout
    assert read_bytes(output)[:8] == b"\x89PNG\r\n\x1a\n"


def test_cdmw_full_archive_worker(tmp_path) -> None:
    from cdmw.domain.archives.catalogue import ArchiveQuery
    from cdmw.domain.archives.catalogue_operations import FetchPageRequest, OpenArchiveRequest
    from cdmw.services.archive_catalogue_service import ArchiveCatalogueService
    from cdmw.ui.shell.archive_backend_client import ArchiveBackendClient
    import shiboken6
    from PySide6.QtWidgets import QApplication
    from tools.dotnet_archive_backend.probe_full_archive_backend import _Awaiter

    worker = _built("native/cdmw_full_archive_backend/build/Release/cdmw-full-archive-worker.exe")
    QApplication.instance() or QApplication([])
    folder = long_folder(tmp_path)
    package = folder / "game"
    _package(package)
    client = ArchiveBackendClient(cache_root=folder / "cache", worker_executable=worker)
    service = ArchiveCatalogueService(client)
    awaiter = _Awaiter(service)
    try:
        session = awaiter.wait(service.open_archive(OpenArchiveRequest(str(package)), ui_generation=1))
        query = awaiter.wait(service.create_query(ArchiveQuery(session.session_id), ui_generation=1))
        page = awaiter.wait(service.fetch_page(FetchPageRequest(query.query_id, 0, 16), ui_generation=1))
        assert [row.path for row in page.rows] == ["file.txt"]
        assert len(str(folder / "cache")) >= LONG_PATH_LENGTH
    finally:
        client.shutdown()
        assert _Awaiter._wait_until(lambda: client.process_id == 0, timeout_ms=5000)
        shiboken6.delete(service)
