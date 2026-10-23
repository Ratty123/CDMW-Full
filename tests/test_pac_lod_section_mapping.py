"""Declared PAC LOD counts govern geometry and protected record ownership."""

import copy
import struct

import pytest

from cdmw.modding.mesh_importer import build_mesh
from cdmw.modding.mesh_parser import (
    _build_pac_preview_mesh,
    _find_pac_descriptors,
    _parse_par_sections,
    _validated_pac_descriptor_prefix,
    parse_pac,
)
from cdmw.modding.pac_cloth import pac_cloth_lods
from tests.test_pac_cloth_guide_builder import guide_free_pac


def _different_lods(lod_count, *, fixed_slots=False):
    """Two owned parts: four vertices at LOD0 and three at each lower LOD."""
    original = guide_free_pac(lods=lod_count, parts=2, flags=0x2004)
    sections = {section["index"]: section for section in _parse_par_sections(original)}
    section0 = sections[0]
    metadata = bytearray(original[section0["offset"]:section0["offset"] + section0["size"]])
    descriptors = _find_pac_descriptors(original, section0["offset"], section0["size"], lod_count)
    geometry = []
    for lod in range(lod_count):
        vertices = 4 if lod == 0 else 3
        faces = (0, 1, 2, 1, 3, 2) if lod == 0 else (0, 1, 2)
        section = sections[lod_count - lod]
        records = b"".join(
            original[section["offset"] + part * 160:section["offset"] + part * 160 + vertices * 40]
            for part in range(2)
        )
        geometry.append(records + struct.pack("<" + "H" * len(faces), *faces) * 2)
        for descriptor in descriptors:
            start = descriptor.descriptor_offset - section0["offset"]
            struct.pack_into("<H", metadata, start + 40 + 2 * lod, vertices)
            struct.pack_into("<I", metadata, start + 40 + 2 * lod_count + 4 * lod, len(faces))
    cursor = 80 + len(metadata)
    for lod in reversed(range(lod_count)):
        struct.pack_into("<I", metadata, 5 + 4 * lod, cursor)
        vertex_bytes = (4 if lod == 0 else 3) * 40 * 2
        struct.pack_into("<I", metadata, 5 + 4 * lod_count + 4 * lod, cursor + vertex_bytes)
        cursor += len(geometry[lod])
    header = bytearray(original[:80])
    payloads = [metadata, *reversed(geometry)]
    for index, payload in enumerate(payloads):
        struct.pack_into("<II", header, 16 + 8 * index, 0, len(payload))
    if fixed_slots:
        # Shipped two/three-LOD PACs leave the lowest reserved slots empty;
        # their LOD0 still occupies slot 4. Physical payload order is unchanged.
        slots = [bytes(header[16 + 8 * index:24 + 8 * index]) for index in range(1, lod_count + 1)]
        header[24:56] = bytes(32)
        for index, slot in enumerate(slots, 5 - lod_count):
            header[16 + 8 * index:24 + 8 * index] = slot
    return bytes(header) + b"".join(payloads)


LAYOUTS = [(2, False), (3, False), (4, False), (2, True), (3, True)]


@pytest.mark.parametrize("lod_count,fixed_slots", LAYOUTS)
def test_main_and_fast_pac_readers_keep_the_declared_lod0(lod_count, fixed_slots):
    source = _different_lods(lod_count, fixed_slots=fixed_slots)
    expected = pac_cloth_lods(source)[0]
    parsed = parse_pac(source, "owned.pac")
    assert parsed.total_vertices == 8
    assert parsed.total_faces == 4
    assert len(parsed.submeshes) == 2
    for actual, reference in zip(parsed.submeshes, expected.submeshes, strict=True):
        assert actual.vertices == reference.vertices
        assert actual.faces == reference.faces
        assert actual.source_vertex_offsets == reference.source_vertex_offsets
        assert actual.bone_indices == reference.bone_indices
        assert actual.bone_weights == reference.bone_weights
        assert actual.source_lod_count == lod_count
    preview = _build_pac_preview_mesh(source, "owned.pac")
    assert preview.vertices == [vertex for part in expected.submeshes for vertex in part.vertices]
    assert len(preview.faces) == 4
    assert build_mesh(parsed, source) == source


@pytest.mark.parametrize("lod_count,fixed_slots", LAYOUTS)
def test_position_edit_preserves_lower_lods_and_skin_records(lod_count, fixed_slots):
    source = _different_lods(lod_count, fixed_slots=fixed_slots)
    before = pac_cloth_lods(source)
    edited = parse_pac(source, "owned.pac")
    assert edited.total_vertices == 8
    edited.submeshes[0].vertices[0] = (2., 0., 0.)
    output = build_mesh(edited, source)
    after = pac_cloth_lods(output)
    assert len(after) == lod_count
    assert after[0].submeshes[0].vertices[0] == pytest.approx((2., 0., 0.), abs=1e-4)
    for lod, (old, new) in enumerate(zip(before, after, strict=True)):
        for old_part, new_part in zip(old.submeshes, new.submeshes, strict=True):
            assert new_part.faces == old_part.faces
            assert new_part.bone_indices == old_part.bone_indices
            assert new_part.bone_weights == old_part.bone_weights
            if lod:
                for old_vertex, new_vertex in zip(old_part.vertices, new_part.vertices, strict=True):
                    assert new_vertex == pytest.approx(old_vertex, abs=1e-4)
            for old_offset, new_offset in zip(old_part.source_vertex_offsets, new_part.source_vertex_offsets, strict=True):
                assert output[new_offset + 6:new_offset + 40] == source[old_offset + 6:old_offset + 40]


@pytest.mark.parametrize("lod_count,fixed_slots", LAYOUTS)
def test_descriptor_prefix_requires_exact_sizes_for_the_declared_lods(lod_count, fixed_slots):
    source = _different_lods(lod_count, fixed_slots=fixed_slots)
    sections = _parse_par_sections(source)
    metadata = sections[0]
    descriptors = _find_pac_descriptors(source, metadata["offset"], metadata["size"], lod_count)
    false_match = copy.deepcopy(descriptors[0])
    false_match.name = "not_a_part"
    false_match.vertex_counts[0] = 1000
    candidates = [*descriptors, false_match]
    assert _validated_pac_descriptor_prefix(candidates, sections, lod_count=lod_count) == descriptors
    bad_sections = [dict(section) for section in sections]
    bad_sections[-1]["size"] += 1
    assert _validated_pac_descriptor_prefix(candidates, bad_sections, lod_count=lod_count) == candidates


def _assert_lod_stream_pointers(source, lod_count):
    sections = _parse_par_sections(source)
    metadata = sections[0]["offset"]
    by_offset = {section["offset"]: section for section in sections}
    for lod, mesh in enumerate(pac_cloth_lods(source)):
        start, = struct.unpack_from("<I", source, metadata + 5 + 4 * lod)
        split, = struct.unpack_from("<I", source, metadata + 5 + 4 * lod_count + 4 * lod)
        assert by_offset[start]["index"] > 0
        assert split == start + sum(len(part.vertices) * 40 for part in mesh.submeshes)


@pytest.mark.parametrize("lod_count,fixed_slots", LAYOUTS)
def test_full_rebuild_retains_source_geometry_slots(lod_count, fixed_slots):
    from cdmw.modding.mesh_pac_builder import _build_pac_full_rebuild

    source = _different_lods(lod_count, fixed_slots=fixed_slots)
    original = parse_pac(source, "owned.pac")
    edited = copy.deepcopy(original)
    edited.submeshes[0].vertices[0] = (.5, 0., 0.)
    output = _build_pac_full_rebuild(
        original, edited, source, preserve_original_submesh_indices=(1,),
    )
    assert [section["index"] for section in _parse_par_sections(output)] == [
        section["index"] for section in _parse_par_sections(source)
    ]
    assert parse_pac(output, "owned.pac").submeshes[0].vertices[0] == pytest.approx((.5, 0., 0.), abs=1e-4)
    _assert_lod_stream_pointers(output, lod_count)


@pytest.mark.parametrize("lod_count,fixed_slots", LAYOUTS)
def test_exact_topology_rebuild_keeps_distinct_lower_lods(lod_count, fixed_slots):
    from cdmw.modding.mesh_pac_topology_builder import build_pac_topology_rebuild
    from tests.test_mesh_pac_topology_serializer import _deleted_quad

    source = _different_lods(lod_count, fixed_slots=fixed_slots)
    original = parse_pac(source, "owned.pac")
    output = build_pac_topology_rebuild(original, _deleted_quad(original), source)
    assert len(parse_pac(output, "owned.pac").submeshes[0].faces) == 1
    old_levels, new_levels = pac_cloth_lods(source), pac_cloth_lods(output)
    for old, new in zip(old_levels[1:], new_levels[1:], strict=True):
        for a, b in zip(old.submeshes, new.submeshes, strict=True):
            assert b.vertices == a.vertices
            assert b.faces == a.faces
            assert b.bone_indices == a.bone_indices
            assert b.bone_weights == a.bone_weights
    _assert_lod_stream_pointers(output, lod_count)
