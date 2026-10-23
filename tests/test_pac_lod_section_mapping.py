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


def _different_lods(lod_count):
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
    return bytes(header) + b"".join(payloads)


@pytest.mark.parametrize("lod_count", [2, 3, 4])
def test_main_and_fast_pac_readers_keep_the_declared_lod0(lod_count):
    source = _different_lods(lod_count)
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


@pytest.mark.parametrize("lod_count", [2, 3, 4])
def test_position_edit_preserves_lower_lods_and_skin_records(lod_count):
    source = _different_lods(lod_count)
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


@pytest.mark.parametrize("lod_count", [2, 3, 4])
def test_descriptor_prefix_requires_exact_sizes_for_the_declared_lods(lod_count):
    source = _different_lods(lod_count)
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
