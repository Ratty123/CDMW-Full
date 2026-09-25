"""Exercise PAC descriptor recovery through the built Preview Core helper."""

from dataclasses import replace
import hashlib
import json
from pathlib import Path
import struct

import pytest

from tests.test_native_preview_long_paths import _grid_pac, _prepared_entry, _run, native_helper


def _grid_with_extra_descriptor(*, real_lods: tuple[int, ...]) -> bytes:
    data = _grid_pac()
    metadata_size = struct.unpack_from("<I", data, 0x14)[0]
    metadata = bytearray(data[0x50:0x50 + metadata_size])
    extra = bytearray(metadata[-64:])
    if real_lods:
        for lod in range(4):
            struct.pack_into("<H", extra, 40 + lod * 2, 9 if lod in real_lods else 0)
            struct.pack_into("<I", extra, 48 + lod * 4, 24 if lod in real_lods else 0)
    metadata.extend(b"\x06second\x06second" + extra)
    grid = data[0x50 + metadata_size:0x50 + metadata_size + 408]
    sections = []
    cursor = 0x50 + len(metadata)
    for lod in (3, 2, 1, 0):
        copies = 2 if lod in real_lods else 1
        geometry = grid[:360] * copies + grid[360:] * copies
        struct.pack_into("<I", metadata, 5 + lod * 4, cursor)
        struct.pack_into("<I", metadata, 21 + lod * 4, cursor + 360 * copies)
        sections.append(geometry)
        cursor += len(geometry)
    header = bytearray(data[:0x50])
    for index, section in enumerate([metadata, *sections]):
        struct.pack_into("<II", header, 0x10 + index * 8, 0, len(section))
    return bytes(header + metadata) + b"".join(sections)


@pytest.mark.parametrize("real_lods,expected_parts", [((), 1), ((0, 1, 2, 3), 2), ((1,), 2)])
def test_native_pac_descriptors_require_exact_fit_in_every_lod(
    native_helper, tmp_path: Path, real_lods, expected_parts,
):
    entry = _prepared_entry(tmp_path / "grid.pac")
    data = _grid_with_extra_descriptor(real_lods=real_lods)
    entry.prepared_path.write_bytes(data)
    entry = replace(entry, orig_size=len(data), comp_size=len(data), prepared_size=len(data),
                    prepared_sha256=hashlib.sha256(data).hexdigest())
    result = _run(entry, tmp_path)
    assert result.succeeded, result.fallback_reason
    package = Path(result.package_path)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["mesh_count"] == expected_parts
    assert manifest["source_vertex_count"] == 9 * expected_parts
    assert manifest["face_count"] == 8 * expected_parts
    expected_indices = [v for face in struct.iter_unpack("<3H", _grid_pac()[-48:]) for v in face]
    for part, batch in enumerate(manifest["batches"]):
        identities = list(struct.iter_unpack("<2i", (package / batch["editor_identity"]["identity_file"]).read_bytes()))
        assert identities == [(part, vertex) for vertex in expected_indices]
    assert entry.prepared_path.read_bytes() == data


@pytest.mark.parametrize("damage", [None, "normals", "indices", "layout"])
def test_coarse_pac_long_edges_require_exact_layout_and_authored_normals(native_helper, tmp_path, damage):
    data = bytearray(_grid_pac())
    metadata_size = struct.unpack_from("<I", data, 0x14)[0]
    start = 0x50 + metadata_size
    sections = []
    for lod in range(4):
        section = bytearray(data[start + lod * 408:start + (lod + 1) * 408])
        for vertex in range(9):
            # Wide triangles are intentional, and every authored normal is +Z.
            struct.pack_into("<H", section, vertex * 40, (0, 327, 32767)[vertex % 3])
            if damage == "normals":
                struct.pack_into("<I", section, vertex * 40 + 16, 0x40000000 | (512 << 10) | (512 << 20))
        if damage == "indices":
            struct.pack_into("<H", section, 360, 65535)
        if damage == "layout":
            section.extend(b"\0\0")
        struct.pack_into("<I", data, 0x14 + (lod + 1) * 8, len(section))
        sections.append(section)
    data = bytes(data[:start]) + b"".join(sections)
    entry = _prepared_entry(tmp_path / "coarse.pac")
    entry.prepared_path.write_bytes(data)
    entry = replace(entry, orig_size=len(data), comp_size=len(data), prepared_size=len(data),
                    prepared_sha256=hashlib.sha256(data).hexdigest())
    result = _run(entry, tmp_path)
    if damage is None:
        assert result.succeeded, result.fallback_reason
        assert result.diagnostics["face_count"] == 8
    else:
        assert not result.succeeded
        assert "unsafe" in result.fallback_reason
