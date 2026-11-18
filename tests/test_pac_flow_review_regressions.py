"""PAC write/read regressions from the 2026-11-18 flow review.

Each test builds a small synthetic PAC in memory (no game data) and checks a
contract that one writer or reader used to break:

* faces and parts are addressed by where they are stored, not by their
  position in the parser's filtered lists;
* rebuilt parts never get stride-sampled lower LODs, and weight-only rebuilds
  keep the source's own lower LODs;
* part names read back exactly as written, or the writer refuses them;
* PAC files that declare more than four LODs are refused by the writers.
"""

from __future__ import annotations

import copy
import struct
from dataclasses import replace

import pytest

from cdmw.modding.mesh_pac_builder import (
    _build_pac_full_rebuild,
    _build_pac_in_place,
    _length_prefixed_ascii,
    build_pac,
)
from cdmw.modding.mesh_parser import (
    _find_name_strings,
    _find_pac_descriptors,
    _parse_par_sections,
    parse_pac,
)

N_LODS = 4
Q = 32767
QUAD = [(0, 0, 0), (Q, 0, 0), (0, Q, 0), (Q, Q, 0)]
TRI = [(0, 0, 0), (Q, 0, 0), (0, Q, 0)]


def _record(x, y, z):
    record = bytearray(40)
    struct.pack_into("<HHH", record, 0, x, y, z)
    struct.pack_into("<e", record, 8, 0.25)
    struct.pack_into("<e", record, 10, 0.75)
    struct.pack_into("<I", record, 16, (512 << 10) | (512 << 20))
    record[39] = 63
    return record


def make_pac(parts, *, n_lods=N_LODS, names=None):
    """parts: list of dict(name, lods=[(positions, flat_indices)] * n_lods)."""
    section_0 = bytearray(5 + n_lods * 8)
    section_0[4] = n_lods
    for part_index, part in enumerate(parts):
        name_prefix = (names[part_index] if names else
                       bytes([len(part["name"])]) + part["name"].encode() + bytes([len(part["name"])]) + part["name"].encode())
        section_0.extend(name_prefix)
        descriptor = bytearray(64)
        descriptor[0] = 1
        struct.pack_into("<8f", descriptor, 3, 0, 0, 0, 0, 0, 1.0, 1.0, 1.0)
        descriptor[35:40] = bytes([4, 0, 1, 2, 3])
        for lod in range(N_LODS):
            positions, indices = part["lods"][lod]
            struct.pack_into("<H", descriptor, 40 + lod * 2, len(positions))
            struct.pack_into("<I", descriptor, 48 + lod * 4, len(indices))
        section_0.extend(descriptor)
    lod_payloads, splits = [], []
    for lod in range(N_LODS):
        vertices, indices = bytearray(), bytearray()
        for part in parts:
            positions, flat = part["lods"][lod]
            for position in positions:
                vertices.extend(_record(*position))
            indices.extend(struct.pack(f"<{len(flat)}H", *flat))
        lod_payloads.append(bytes(vertices + indices))
        splits.append(len(vertices))
    payloads = [bytes(section_0)] + [lod_payloads[N_LODS - slot] for slot in range(1, N_LODS + 1)]
    header = bytearray(0x50)
    header[:4] = b"PAR "
    offsets, cursor = [], 0x50
    for slot, payload in enumerate(payloads):
        struct.pack_into("<I", header, 0x10 + slot * 8 + 4, len(payload))
        offsets.append(cursor)
        cursor += len(payload)
    for lod in range(N_LODS):
        slot = N_LODS - lod
        struct.pack_into("<I", section_0, 5 + lod * 4, offsets[slot])
        struct.pack_into("<I", section_0, 5 + n_lods * 4 + lod * 4, offsets[slot] + splits[lod])
    payloads[0] = bytes(section_0)
    return bytes(header) + b"".join(payloads)


def _grid(n=5):
    positions = [(int(Q * x / (n - 1)), int(Q * y / (n - 1)), 0) for y in range(n) for x in range(n)]
    indices = []
    for y in range(n - 1):
        for x in range(n - 1):
            a = y * n + x
            indices += [a, a + 1, a + n, a + 1, a + n + 1, a + n]
    return positions, indices


def _stored_lod_faces(data):
    """Face sets per LOD of the single descriptor, by (x, y) record position."""
    sections = {section["index"]: section for section in _parse_par_sections(data)}
    descriptor = data.find(bytes([4, 0, 1, 2, 3]), sections[0]["offset"]) - 35
    vertex_counts = struct.unpack_from("<4H", data, descriptor + 40)
    index_counts = struct.unpack_from("<4I", data, descriptor + 48)
    result = []
    for lod in range(4):
        section = sections[4 - lod]
        indices = struct.unpack_from(f"<{index_counts[lod]}H", data, section["offset"] + vertex_counts[lod] * 40)
        positions = [struct.unpack_from("<2H", data, section["offset"] + v * 40) for v in range(vertex_counts[lod])]
        result.append(sorted(tuple(sorted(positions[i] for i in indices[k:k + 3]))
                             for k in range(0, len(indices), 3)))
    return result


def _add_vertex_and_face(part, position, face):
    part.vertices = list(part.vertices) + [position]
    part.uvs = list(part.uvs) + [(0.5, 0.5)]
    part.normals = list(part.normals) + [(0.0, 0.0, 1.0)]
    part.bone_indices = list(part.bone_indices) + [()]
    part.bone_weights = list(part.bone_weights) + [()]
    part.faces = list(part.faces) + [face]
    part.source_vertex_map = list(range(len(part.vertices) - 1)) + [0]


# Chain 2: faces and parts are addressed by where they are stored.

def test_in_place_face_edit_writes_each_face_to_its_own_stored_triple():
    source = make_pac([
        {"name": "partA", "lods": [(QUAD, [0, 1, 2, 1, 1, 1, 1, 3, 2])] + [(TRI, [0, 1, 2])] * 3},
    ])
    original = parse_pac(source, "probe.pac")
    assert original.submeshes[0].faces == [(0, 1, 2), (1, 3, 2)]
    assert original.submeshes[0].source_face_slots == [0, 2]
    edited = copy.deepcopy(original)
    edited.submeshes[0].faces = [edited.submeshes[0].faces[0], (1, 2, 3)]

    output = _build_pac_in_place(original, edited, source)

    offset = original.submeshes[0].source_index_offset
    assert struct.unpack_from("<9H", output, offset) == (0, 1, 2, 1, 1, 1, 1, 2, 3)
    assert parse_pac(output, "probe.pac").submeshes[0].faces == [(0, 1, 2), (1, 2, 3)]


@pytest.mark.parametrize("b_lower_lod", [[0, 1, 2], [0, 0, 0]], ids=["live-lower-lods", "collapsed-everywhere"])
def test_full_rebuild_keeps_a_descriptor_the_parser_could_not_read(b_lower_lod):
    # partB has no live face at LOD0. With live lower LODs, the rebuilt LOD1 ties
    # LOD0 on faces and has more vertices; it must still read back as LOD0.
    source = make_pac([
        {"name": "partA", "lods": [(QUAD, [0, 1, 2, 1, 3, 2])] + [(TRI, [0, 1, 2])] * 3},
        {"name": "partB", "lods": [(TRI, [0, 0, 0])] + [(TRI, b_lower_lod)] * 3},
        {"name": "partC", "lods": [(QUAD, [0, 1, 2, 1, 3, 2])] + [(TRI, [0, 1, 2])] * 3},
    ])
    original = parse_pac(source, "probe.pac")
    assert [part.name for part in original.submeshes] == ["partA", "partC"]
    edited = copy.deepcopy(original)
    _add_vertex_and_face(edited.submeshes[1], (0.5, 0.5, 0.0), (0, 1, 4))

    output = build_pac(edited, source)

    rebuilt = parse_pac(output, "probe.pac")
    assert [(part.name, len(part.vertices), len(part.faces)) for part in rebuilt.submeshes] == [
        ("partA", 4, 2), ("partC", 5, 3)]
    sections = _parse_par_sections(output)
    section0 = next(section for section in sections if section["index"] == 0)
    descriptors = _find_pac_descriptors(output, section0["offset"], section0["size"], N_LODS)
    assert [descriptor.name for descriptor in descriptors] == ["partA", "partB", "partC"]
    # partB's own records are carried over untouched at every LOD.
    assert [descriptor.vertex_counts[:4] for descriptor in descriptors][1] == [3, 3, 3, 3]
    assert [descriptor.index_counts[:4] for descriptor in descriptors][1] == [3, 3, 3, 3]


# Chain 1: lower LODs are never stride-sampled.

def test_rebuilt_part_writes_its_whole_lod0_at_every_lower_lod():
    grid, indices = _grid()
    source = make_pac([{"name": "grid", "lods": [
        (grid, indices), (grid, indices[:len(indices) // 2]),
        (grid, indices[:len(indices) // 4]), (grid, indices[:len(indices) // 8])]}])
    original = parse_pac(source, "probe.pac")
    edited = copy.deepcopy(original)
    _add_vertex_and_face(edited.submeshes[0], (0.5, 0.5, 0.1), (0, 1, 25))

    output = build_pac(edited, source)

    lods = _stored_lod_faces(output)
    assert all(len(level) == 33 for level in lods)
    assert lods[1] == lods[2] == lods[3] == lods[0]


def test_weight_only_rebuild_keeps_the_source_lower_lods():
    grid, indices = _grid()
    source = make_pac([{"name": "armour", "lods": [
        (grid, indices), (grid, indices[:48]), (grid, indices[:24]), (grid, indices[:12])]}])
    original = parse_pac(source, "probe.pac")
    working = replace(original, submeshes=[replace(part, source_vertex_map=[]) for part in original.submeshes])

    output = _build_pac_full_rebuild(original, working, source, preserve_runtime_abi=True)

    assert _stored_lod_faces(output) == _stored_lod_faces(source)


def test_weight_transfer_rebuild_keeps_lower_lod_faces_and_reskins_them():
    grid, indices = _grid()
    source = make_pac([{"name": "armour", "lods": [
        (grid, indices), (grid, indices[:48]), (grid, indices[:24]), (grid, indices[:12])]}])
    original = parse_pac(source, "probe.pac")
    part = original.submeshes[0]
    skinned = replace(
        part,
        bone_indices=[(1,)] * len(part.vertices),
        bone_weights=[(1.0,)] * len(part.vertices),
        source_vertex_map=[],
    )
    working = replace(original, submeshes=[skinned])

    output = _build_pac_full_rebuild(original, working, source, preserve_runtime_abi=True)

    assert _stored_lod_faces(output) == _stored_lod_faces(source)
    from cdmw.modding.pac_cloth import pac_cloth_lods
    for level in pac_cloth_lods(output):
        rows = {tuple(bones) for bones in level.submeshes[0].bone_indices}
        assert rows == {tuple(skinned_row) for skinned_row in pac_cloth_lods(output)[0].submeshes[0].bone_indices}


# Chain 4: names read back exactly as written, or the writer refuses them.

@pytest.mark.parametrize("name", ["cd_" + chr(40) + "x" * 40, "p" * 116, "cd_phm_01_" + chr(60) * 3 + "y" * 70])
def test_part_names_round_trip_through_the_writer_and_the_descriptor_reader(name):
    prefix = _length_prefixed_ascii(name, "fallback") + _length_prefixed_ascii(name + "_mtl", "fallback")
    source = make_pac([{"name": "x", "lods": [(TRI, [0, 1, 2])] * 4}], names=[prefix])
    section0 = next(section for section in _parse_par_sections(source) if section["index"] == 0)

    descriptor, = _find_pac_descriptors(source, section0["offset"], section0["size"], N_LODS)

    assert (descriptor.name, descriptor.material) == (name, name + "_mtl")
    region = source[section0["offset"]:section0["offset"] + section0["size"]]
    start = descriptor.descriptor_offset - section0["offset"]
    assert _find_name_strings(region, start, 5 + N_LODS * 8) == (name, name + "_mtl")


@pytest.mark.parametrize("name", ["Ärmel_überwurf", "p" * 121, "bad\tname"])
def test_name_writer_refuses_names_it_cannot_store_exactly(name):
    with pytest.raises(ValueError, match="PAC part name"):
        _length_prefixed_ascii(name, "fallback")


# Chain 5: more than four declared LODs is refused, not mis-sliced.

def test_writers_refuse_a_pac_that_declares_more_than_four_lods():
    source = bytearray(make_pac([{"name": "part", "lods": [(QUAD, [0, 1, 2, 1, 3, 2])] + [(TRI, [0, 1, 2])] * 3}]))
    original = parse_pac(bytes(source), "probe.pac")
    section0 = next(section for section in _parse_par_sections(bytes(source)) if section["index"] == 0)
    source[section0["offset"] + 4] = 5
    edited = copy.deepcopy(original)
    _add_vertex_and_face(edited.submeshes[0], (0.5, 0.5, 0.0), (0, 1, 4))

    with pytest.raises(ValueError, match="at most 4"):
        _build_pac_full_rebuild(original, edited, bytes(source))
