"""The native mesh-core lookup the Mesh Editor's panel state makes on the UI thread.

Each system call there gives up the GIL and waits to take it back; behind a busy worker
that wait is a switch interval, so a lookup that resolved five paths every time took
about 60 to 80 ms (20 ms at a 1 ms interval). The paths are worked out once; only the
existence checks remain, and they stop at the first binary found.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from cdmw.modding import mesh_native_availability as availability


@pytest.fixture(autouse=True)
def _fresh_cache(monkeypatch):
    availability._candidate_paths.cache_clear()
    yield
    availability._candidate_paths.cache_clear()


def _count(monkeypatch, name):
    calls = []
    original = getattr(Path, name)

    def counted(self, *args, **kwargs):
        calls.append(str(self))
        return original(self, *args, **kwargs)

    monkeypatch.setattr(Path, name, counted)
    return calls


def test_a_repeated_lookup_resolves_no_path_and_checks_only_the_binary_found(monkeypatch, tmp_path):
    binary = tmp_path / "cdmw-mesh-core.exe"
    binary.write_bytes(b"MZ")
    monkeypatch.setenv("CDMW_MESH_CORE_BIN", str(binary))
    assert availability.find_native_mesh_core_binary() == binary

    resolved = _count(monkeypatch, "resolve")
    checked = _count(monkeypatch, "is_file")
    for _ in range(5):
        assert availability.native_mesh_core_available()
    assert resolved == []
    assert checked == [str(binary)] * 5


def test_a_binary_removed_or_another_one_set_is_still_noticed(monkeypatch, tmp_path):
    first = tmp_path / "first.exe"
    second = tmp_path / "second.exe"
    first.write_bytes(b"MZ")
    second.write_bytes(b"MZ")
    monkeypatch.setenv("CDMW_MESH_CORE_BIN", str(first))
    assert availability.find_native_mesh_core_binary() == first
    monkeypatch.setenv("CDMW_MESH_CORE_BIN", str(second))
    assert availability.find_native_mesh_core_binary() == second
    second.unlink()
    # The variable's binary is gone: the lookup falls through to the build folders.
    found = availability.find_native_mesh_core_binary()
    assert found != second
    assert found is None or found.is_file()
