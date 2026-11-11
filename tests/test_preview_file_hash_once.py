"""P3 "hash once": a preview file's SHA-256 is computed once per process.

A file verified at least the memo's minimum age after its last write is trusted
again while its volume, file id, size and modification time are unchanged. A
changed file is always caught, and the checks that run on the UI thread never
read file contents.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from pathlib import Path

import pytest

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_rust_preview_files as files
from cdmw.services.mesh_rust_preview_cache import validate_rust_preview_cache_package
from cdmw.services.mesh_rust_preview_package import build_rust_preview_package, validate_rust_preview_package


def _triangle() -> ParsedMesh:
    submesh = SubMesh(
        name="triangle",
        material="test",
        vertices=[(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.0, 0.5, 0.0)],
        normals=[(0.0, 0.0, 1.0)] * 3,
        uvs=[(0.0, 1.0), (1.0, 1.0), (0.5, 0.0)],
        faces=[(0, 1, 2)],
        vertex_count=3,
        face_count=1,
    )
    return ParsedMesh(
        path="procedural://hash-once",
        format="procedural",
        bbox_min=(-0.5, -0.5, 0.0),
        bbox_max=(0.5, 0.5, 0.0),
        submeshes=[submesh],
        total_vertices=3,
        total_faces=1,
        has_uvs=True,
    )


@pytest.fixture(autouse=True)
def _empty_memo():
    files.forget_verified_preview_files()
    yield
    files.forget_verified_preview_files()


@pytest.fixture
def hash_calls(monkeypatch):
    calls: list[str] = []
    original = hashlib.file_digest

    def counting(stream, digest):
        calls.append(Path(getattr(stream, "name", "")).name)
        return original(stream, digest)

    monkeypatch.setattr(files.hashlib, "file_digest", counting)
    return calls


def _age(package_dir: Path, seconds: float = 60.0) -> None:
    """Make every file look like a cache file written a while ago."""

    stamp = time.time_ns() - int(seconds * 1_000_000_000)
    for path in package_dir.rglob("*"):
        if path.is_file():
            os.utime(path, ns=(stamp, stamp))


def _package(tmp_path: Path, name: str = "package") -> Path:
    package = build_rust_preview_package(_triangle(), output_package_dir=tmp_path / name, include_material_resources=False)
    _age(package.package_dir)
    return package.package_dir


def _document(package_dir: Path) -> Path:
    manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))
    return package_dir / manifest["document"]["path"]


def test_an_unchanged_file_is_hashed_once_per_process(tmp_path: Path, hash_calls) -> None:
    package_dir = _package(tmp_path)
    assert validate_rust_preview_package(package_dir) == ()
    first = len(hash_calls)
    assert first >= 2  # document and channels at least
    assert validate_rust_preview_package(package_dir) == ()
    assert validate_rust_preview_cache_package(package_dir) == (True, ())
    assert len(hash_calls) == first


def test_a_fresh_file_is_not_remembered(tmp_path: Path, hash_calls) -> None:
    package = build_rust_preview_package(_triangle(), output_package_dir=tmp_path / "package",
                                         include_material_resources=False)
    assert validate_rust_preview_package(package.package_dir) == ()
    first = len(hash_calls)
    # A same-size rewrite inside one timestamp tick would keep its time, so a
    # file written moments ago is verified again rather than trusted.
    assert validate_rust_preview_package(package.package_dir) == ()
    assert len(hash_calls) == 2 * first


@pytest.mark.parametrize("change", ["content", "size"])
def test_a_changed_file_is_still_caught(tmp_path: Path, change: str) -> None:
    package_dir = _package(tmp_path)
    assert validate_rust_preview_package(package_dir) == ()
    document = _document(package_dir)
    data = bytearray(document.read_bytes())
    if change == "content":
        data[-2] ^= 1
    else:
        data += b" "
    document.write_bytes(bytes(data))
    assert validate_rust_preview_package(package_dir)


def test_a_new_modification_time_is_verified_again(tmp_path: Path, hash_calls) -> None:
    package_dir = _package(tmp_path)
    assert validate_rust_preview_package(package_dir) == ()
    before = len(hash_calls)
    document = _document(package_dir)
    stamp = time.time_ns() - 30_000_000_000
    os.utime(document, ns=(stamp, stamp))
    assert validate_rust_preview_package(package_dir) == ()
    assert hash_calls[before:] == [document.name]


def test_a_hard_link_reuses_the_verification(tmp_path: Path, hash_calls) -> None:
    source = _package(tmp_path, "direct")
    linked = tmp_path / "full"
    linked.mkdir()
    for path in source.iterdir():
        try:
            os.link(path, linked / path.name)
        except OSError:
            pytest.skip("hard links are not available here")
    assert validate_rust_preview_package(source) == ()
    before = len(hash_calls)
    assert validate_rust_preview_package(linked) == ()
    assert len(hash_calls) == before


def test_the_ui_thread_check_never_reads_file_contents(tmp_path: Path, monkeypatch) -> None:
    package_dir = _package(tmp_path)

    def refuse(*_args, **_kwargs):
        raise AssertionError("the UI-thread check hashed a file")

    monkeypatch.setattr(files.hashlib, "file_digest", refuse)
    # Never verified in this process: accepted on structure, sizes and
    # containment; the worker and the helper still verify the contents.
    assert validate_rust_preview_cache_package(package_dir, hash_unverified=False) == (True, ())
    document = _document(package_dir)
    document.write_bytes(document.read_bytes() + b" ")
    valid, missing = validate_rust_preview_cache_package(package_dir, hash_unverified=False)
    assert not valid and "size" in missing[0]
    document.unlink()
    assert validate_rust_preview_cache_package(package_dir, hash_unverified=False)[0] is False


def test_the_ui_thread_check_rejects_a_digest_this_process_disproved(tmp_path: Path) -> None:
    package_dir = _package(tmp_path)
    assert validate_rust_preview_package(package_dir) == ()
    manifest_path = package_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["document"]["sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    valid, missing = validate_rust_preview_cache_package(package_dir, hash_unverified=False)
    assert not valid and "SHA-256" in missing[0]


def test_both_ui_thread_package_checks_skip_hashing(tmp_path: Path, monkeypatch) -> None:
    from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin

    package_dir = _package(tmp_path)

    def refuse(*_args, **_kwargs):
        raise AssertionError("a UI-thread package check hashed a file")

    monkeypatch.setattr(files.hashlib, "file_digest", refuse)
    # Used for every in-memory cache entry on a click (workers.py) and for the
    # published result (preview_result.py).
    assert ArchivePreviewCacheMixin._validate_d3d11_preview_package_paths(package_dir) == (True, ())
    from cdmw.ui.archive_browser import preview_cache, preview_result

    assert preview_result.validate_dotnet_preview_package(package_dir) == (True, ())
    assert preview_cache.validate_dotnet_preview_package(package_dir) == (True, ())
