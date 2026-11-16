"""Finding the native mesh core resolves the program's folders once per process.

The review measured 152 ms (148 ms cold) on the UI thread in Open in Mesh
Editor inside find_native_mesh_core_binary: four or five realpaths per call,
asked whenever a Mesh Editor tab is built or a selection is pruned.
"""

from __future__ import annotations

from pathlib import Path

from cdmw.modding import mesh_native_availability as availability


def test_repeated_lookups_resolve_nothing(monkeypatch):
    availability.find_native_mesh_core_binary()  # the first lookup may resolve
    calls = []
    real_resolve = Path.resolve

    def counting(self, *args, **kwargs):
        calls.append(str(self))
        return real_resolve(self, *args, **kwargs)

    monkeypatch.setattr(Path, "resolve", counting)
    for _ in range(5):
        availability.find_native_mesh_core_binary()
        availability.native_mesh_core_available()
    assert calls == []


def test_the_lookup_still_sees_a_binary_named_by_the_environment(tmp_path, monkeypatch):
    binary = tmp_path / "core.exe"
    monkeypatch.setenv("CDMW_MESH_CORE_BIN", str(binary))
    first = availability.find_native_mesh_core_binary()
    assert first != binary
    binary.write_bytes(b"MZ")
    assert availability.find_native_mesh_core_binary() == binary
