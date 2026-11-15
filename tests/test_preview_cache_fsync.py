"""P3 decision 6: preview cache files are not flushed to disk one by one.

They are verified on read and rebuilt when damaged. Build output and other
files that may be the only copy keep the flush.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from cdmw.core import atomic_file
from cdmw.services import mesh_rust_preview_files
from tests.test_preview_file_hash_once import _triangle


@pytest.fixture
def fsyncs(monkeypatch):
    calls: list[int] = []
    original = os.fsync

    def counting(descriptor):
        calls.append(descriptor)
        return original(descriptor)

    monkeypatch.setattr(os, "fsync", counting)
    return calls


def test_atomic_writes_still_flush_by_default(tmp_path: Path, fsyncs) -> None:
    atomic_file.atomic_write_text(tmp_path / "settings.json", "{}")
    atomic_file.atomic_write_bytes(tmp_path / "draft.bin", b"draft")
    assert len(fsyncs) == 2
    atomic_file.atomic_write_text(tmp_path / "cache.json", "{}", durable=False)
    atomic_file.atomic_write_bytes(tmp_path / "cache.bin", b"cache", durable=False)
    assert len(fsyncs) == 2
    assert (tmp_path / "cache.json").read_text() == "{}"


def test_a_preview_cache_package_is_not_flushed_file_by_file(tmp_path: Path, fsyncs) -> None:
    from cdmw.services.mesh_rust_preview_package import build_rust_preview_package, validate_rust_preview_package

    package = build_rust_preview_package(_triangle(), output_package_dir=tmp_path / "package",
                                         include_material_resources=False)
    assert validate_rust_preview_package(package.package_dir) == ()
    assert fsyncs == []


def test_the_choice_lives_in_one_constant(tmp_path: Path, fsyncs, monkeypatch) -> None:
    from cdmw.services.mesh_rust_preview_package import build_rust_preview_package

    monkeypatch.setattr(mesh_rust_preview_files, "PREVIEW_CACHE_FSYNC", True)
    build_rust_preview_package(_triangle(), output_package_dir=tmp_path / "package", include_material_resources=False)
    assert fsyncs
