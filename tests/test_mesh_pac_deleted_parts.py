"""Exact whole-part deletion keeps descriptor slots and unrelated LOD records."""

import copy
import math
import struct

import pytest

from cdmw.domain.mesh import validate_mesh_export
from cdmw.domain.mesh.topology import compose_topology_provenance, identity_topology_provenance
from cdmw.modding.mesh_pac_topology_builder import (
    PacTopologyRebuildBlocked, build_pac_topology_rebuild,
)
from cdmw.modding.mesh_parser import parse_pac
from cdmw.modding.pac_cloth import pac_cloth_lods
from tests.test_mesh_pac_topology_serializer import _skin, _vertex_record


def _parts_pac(*, skinned=True, disappearing=False):
    metadata = bytearray(37)
    metadata[4] = 4
    buffers = [[bytearray(), bytearray()] for _ in range(4)]
    for part in range(3):
        name = f"part{part}".encode()
        metadata.extend(bytes([len(name)]) + name + bytes([len(name)]) + name)
        descriptor = bytearray(64)
        descriptor[0] = 1
        struct.pack_into("<8f", descriptor, 3, 0, 0, 0, 0, 0, 1, 1, 1)
        descriptor[35:40] = bytes((4, 0, 1, 2, 3))
        for lod, (records, indices) in enumerate(buffers):
            positions = [(0, 0, 0), (32767, 0, 0), (0, 32767, 0)]
            faces = [(0, 1, 2)]
            if lod == 0:
                positions.append((32767, 32767, 0))
                faces.append((1, 3, 2))
            if disappearing and part == 1 and lod == 3:
                positions, faces = [], []
            for position in positions:
                record = _vertex_record(*position, tail=part)
                record[36:39] = bytes((part + 20, lod + 30, 40))
                if skinned:
                    _skin(record, (3,), (255,))
                records.extend(record)
            for face in faces:
                indices.extend(struct.pack("<3H", *face))
            struct.pack_into("<H", descriptor, 40 + lod * 2, len(positions))
            struct.pack_into("<I", descriptor, 48 + lod * 4, len(faces) * 3)
        metadata.extend(descriptor)
    payloads = [metadata] + [records + indices for records, indices in reversed(buffers)]
    payloads.append(b"unknown-section-must-survive")
    header = bytearray(0x50)
    header[:4] = b"PAR "
    offset = 0x50
    for section, payload in enumerate(payloads):
        struct.pack_into("<I", header, 0x14 + section * 8, len(payload))
        if 1 <= section <= 4:
            lod = 4 - section
            struct.pack_into("<I", metadata, 5 + lod * 4, offset)
            struct.pack_into("<I", metadata, 21 + lod * 4, offset + len(buffers[lod][0]))
        offset += len(payload)
    return bytes(header) + b"".join(payloads)


def _empty_parts(original, indices):
    edited = copy.deepcopy(original)
    for index in indices:
        part = edited.submeshes[index]
        part.topology_provenance = compose_topology_provenance(
            identity_topology_provenance(len(part.vertices), len(part.faces)),
            copy_vertex_indices=(), face_origins=(),
        )
        for attr in ("vertices", "faces", "uvs", "normals", "tangents", "shader_masks",
                     "bone_indices", "bone_weights", "source_vertex_map", "source_vertex_offsets"):
            setattr(part, attr, [])
        part.vertex_count = part.face_count = 0
        part.source_vertex_map_authority = "topology"
    return edited


@pytest.mark.parametrize("deleted", [(0,), (1,), (2,), (0, 2), (0, 1, 2)])
@pytest.mark.parametrize("skinned", [False, True])
@pytest.mark.parametrize("disappearing", [False, True])
def test_exact_deleted_parts_preserve_all_other_bytes_and_lods(deleted, skinned, disappearing):
    source = _parts_pac(skinned=skinned, disappearing=disappearing)
    original = parse_pac(source, "parts.pac")
    edited = _empty_parts(original, deleted)
    validation = validate_mesh_export(edited, original_mesh=original, skeleton_bone_count=8)
    assert validation.ok, validation.blockers
    report = {}
    rebuilt = build_pac_topology_rebuild(original, edited, source, report=report)
    assert len(rebuilt) == len(source)
    changed = set()
    for before, after in zip(pac_cloth_lods(source), pac_cloth_lods(rebuilt), strict=True):
        for index, (old, new) in enumerate(zip(before.submeshes, after.submeshes, strict=True)):
            assert new.name == old.name
            assert new.source_descriptor_offset == old.source_descriptor_offset
            assert new.source_vertex_offsets == old.source_vertex_offsets
            if index not in deleted or not old.vertices:
                assert new.vertices == old.vertices
                assert new.faces == old.faces
                continue
            assert new.faces == old.faces[:1]
            face = new.faces[0]
            # All live corners keep identical skin, guide and protected bytes.
            records = [rebuilt[offset:offset + 40] for vertex in face
                       for offset in [new.source_vertex_offsets[vertex]]]
            assert records[0][6:] == records[1][6:] == records[2][6:]
            points = [new.vertices[vertex] for vertex in face]
            assert 0 < max(math.dist(a, b) for a in points for b in points) < .003
            for vertex in old.faces[0]:
                offset = old.source_vertex_offsets[vertex]
                changed.update(range(offset, offset + 40))
            changed.update(range(old.source_index_offset, old.source_index_offset + old.source_index_count * 2))
    assert all(a == b or offset in changed for offset, (a, b) in enumerate(zip(source, rebuilt)))
    reparsed = parse_pac(rebuilt, "parts.pac")
    assert len(reparsed.submeshes) == 3
    assert [len(part.faces) for part in reparsed.submeshes] == [1 if i in deleted else 2 for i in range(3)]
    assert report["fallback_used"] is False
    assert report["deleted_submesh_indices"] == deleted
    assert report["lower_lods_preserved"] is False
    assert report["unmodified_parts_preserved"] is True
    assert report["unknown_sections_preserved"] is True
    assert not any(edited.submeshes[i].vertices for i in deleted)


def test_deleted_part_can_coexist_with_a_partial_topology_edit():
    source = _parts_pac()
    original = parse_pac(source, "parts.pac")
    edited = _empty_parts(original, (2,))
    part = edited.submeshes[0]
    part.topology_provenance = compose_topology_provenance(
        identity_topology_provenance(4, 2), copy_vertex_indices=(0, 1, 2), face_origins=(0,),
    )
    for attr in ("vertices", "uvs", "normals", "shader_masks", "bone_indices", "bone_weights",
                 "source_vertex_offsets", "source_vertex_map"):
        setattr(part, attr, getattr(part, attr)[:3])
    part.faces = [(0, 1, 2)]
    part.source_vertex_map_authority = "topology"
    rebuilt = build_pac_topology_rebuild(original, edited, source)
    levels = pac_cloth_lods(rebuilt)
    assert len(levels[0].submeshes[0].vertices) == 3
    assert levels[0].submeshes[0].faces == [(0, 1, 2)]
    assert all(len(lod.submeshes[2].faces) == 1 for lod in levels)
    for before, after in zip(pac_cloth_lods(source)[1:], levels[1:], strict=True):
        for index in (0, 1):
            old, new = before.submeshes[index], after.submeshes[index]
            assert old.vertices == new.vertices and old.faces == new.faces
            assert b"".join(source[o:o + 40] for o in old.source_vertex_offsets) == b"".join(
                rebuilt[o:o + 40] for o in new.source_vertex_offsets)


@pytest.mark.parametrize("fault", ["no_contract", "stale_contract", "stale_channels", "bounds", "shared_lower_lod"])
def test_unproven_empty_parts_are_refused(fault):
    source = _parts_pac()
    if fault in {"bounds", "shared_lower_lod"}:
        raw = bytearray(source)
        original = parse_pac(source, "parts.pac")
        if fault == "bounds":
            struct.pack_into("<3f", raw, original.submeshes[0].source_descriptor_offset + 23, 1000, 1000, 1000)
        else:
            # LOD1 part 1 now claims part 0's records. Deleting part 0 must
            # refuse the entire export rather than hide part 1 along with it.
            struct.pack_into("<H", raw, original.submeshes[1].source_descriptor_offset + 42, 0)
        source = bytes(raw)
    original = parse_pac(source, "parts.pac")
    edited = _empty_parts(original, (0,))
    if fault == "no_contract":
        edited.submeshes[0].topology_provenance = None
    elif fault == "stale_contract":
        edited.submeshes[0].topology_provenance = identity_topology_provenance(4, 2)
    elif fault == "stale_channels":
        edited.submeshes[0].uvs = [(0, 0)]
    with pytest.raises(PacTopologyRebuildBlocked):
        build_pac_topology_rebuild(original, edited, source)
