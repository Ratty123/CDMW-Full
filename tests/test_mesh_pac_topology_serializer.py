"""Exact PAC LOD0 topology serializer contract tests."""

from __future__ import annotations

import hashlib
import struct

import pytest

from cdmw.domain.mesh.topology import (
    TOPOLOGY_BOUNDS_EXCEED_SOURCE,
    TOPOLOGY_CONTRACT_UNSUPPORTED,
    TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED,
    TOPOLOGY_PROTECTED_BYTES_DIVERGE,
    TOPOLOGY_PROVENANCE_REQUIRED,
    TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED,
    compose_topology_provenance,
    identity_topology_provenance,
    topology_source_vertex_map,
)
from cdmw.modding.mesh_pac_topology_builder import (
    PacTopologyRebuildBlocked,
    build_pac_topology_rebuild,
    derived_skin_row,
    protected_byte_mask,
    topology_rebuild_blockers,
)
from cdmw.modding.mesh_parser import (
    PAC_SKIN_INFLUENCES,
    PAC_SKIN_SLOT_BITS,
    PAC_SKIN_SLOT_GROUPS,
    PAC_SKIN_WEIGHT_OFFSET,
    ParsedMesh,
    parse_pac,
)


N_LODS = 4
LOD0_VERTEX_COUNT = 4
LOD0_FACES = ((0, 1, 2), (1, 3, 2))
LOWER_VERTEX_COUNT = 3
LOWER_FACES = ((0, 1, 2),)


def _vertex_record(x: int, y: int, z: int, *, tail: int = 0) -> bytearray:
    record = bytearray(40)
    struct.pack_into("<HHH", record, 0, x, y, z)
    # Bytes 6-7 and 12-15 are protected lanes; give them a stable non-zero value
    # so a writer that touches them is caught.
    struct.pack_into("<H", record, 6, 0x1234)
    struct.pack_into("<e", record, 8, 0.25)
    struct.pack_into("<e", record, 10, 0.75)
    struct.pack_into("<I", record, 12, 0xA5A5A5A5)
    struct.pack_into("<I", record, 16, 0x40000000)
    record[34:40] = bytes((0x11, 0x22, 0x33, 0x44, 0x55, tail & 0xFF))
    return record


def _skin(record: bytearray, slots: tuple[int, ...], weights: tuple[int, ...]) -> None:
    padded_slots = list(slots) + [0] * (PAC_SKIN_INFLUENCES - len(slots))
    padded_weights = list(weights) + [0] * (PAC_SKIN_INFLUENCES - len(weights))
    for group, group_offset in enumerate(PAC_SKIN_SLOT_GROUPS):
        packed = struct.unpack_from("<I", record, group_offset)[0] & ~0x3FFFFFFF
        for position in range(3):
            packed |= padded_slots[group * 3 + position] << (PAC_SKIN_SLOT_BITS * position)
        struct.pack_into("<I", record, group_offset, packed)
    record[PAC_SKIN_WEIGHT_OFFSET : PAC_SKIN_WEIGHT_OFFSET + PAC_SKIN_INFLUENCES] = bytes(padded_weights)


def _pac_fixture(
    *,
    skinned: bool = False,
    protected_divergence: bool = False,
    lower_matches_lod0: bool = False,
) -> bytes:
    """A four-vertex, two-face LOD0 over three smaller lower LODs."""
    lower_vertex_count = LOD0_VERTEX_COUNT if lower_matches_lod0 else LOWER_VERTEX_COUNT
    lower_faces = LOD0_FACES if lower_matches_lod0 else LOWER_FACES
    lod0_positions = ((0, 0, 0), (32767, 0, 0), (0, 32767, 0), (32767, 32767, 0))
    lod0_records = bytearray()
    for index, position in enumerate(lod0_positions):
        record = _vertex_record(*position, tail=index if protected_divergence else 0)
        if skinned:
            # Vertices 0 and 1 share slots 3 and 7 so their union stays inside six.
            if index in (0, 1):
                _skin(record, (3, 7), (200, 55))
            else:
                _skin(record, (3,), (255,))
        lod0_records.extend(record)
    lod0_indices = b"".join(struct.pack("<HHH", *face) for face in LOD0_FACES)
    lod0_payload = bytes(lod0_records + lod0_indices)

    lower_records = bytearray()
    for index in range(lower_vertex_count):
        record = _vertex_record(index * 100, index * 50, 0)
        if skinned:
            _skin(record, (3,), (255,))
        lower_records.extend(record)
    lower_indices = b"".join(struct.pack("<HHH", *face) for face in lower_faces)
    lower_payload = bytes(lower_records + lower_indices)

    section_0 = bytearray(5 + N_LODS * 8)
    section_0[4] = N_LODS
    section_0.extend(bytes([6]) + b"target")
    section_0.extend(bytes([6]) + b"target")
    descriptor = bytearray(64)
    descriptor[0] = 0x01
    struct.pack_into("<8f", descriptor, 3, 0.0, 0.0, 0.0, 0.0, 0.0, 1.0, 1.0, 1.0)
    descriptor[35:40] = bytes([0x04, 0x00, 0x01, 0x02, 0x03])
    for lod_index in range(N_LODS):
        vertex_count = LOD0_VERTEX_COUNT if lod_index == 0 else lower_vertex_count
        index_count = len(LOD0_FACES) * 3 if lod_index == 0 else len(lower_faces) * 3
        struct.pack_into("<H", descriptor, 40 + lod_index * 2, vertex_count)
        struct.pack_into("<I", descriptor, 48 + lod_index * 4, index_count)
    section_0.extend(descriptor)

    header = bytearray(0x50)
    header[:4] = b"PAR "
    payloads = [bytes(section_0)] + [lower_payload] * (N_LODS - 1) + [lod0_payload]
    # Section index n_lods holds LOD0; sections 1..n_lods-1 hold the lower LODs.
    for index, payload in enumerate(payloads):
        struct.pack_into("<I", header, 0x10 + index * 8, 0)
        struct.pack_into("<I", header, 0x10 + index * 8 + 4, len(payload))
    offsets: list[int] = []
    cursor = len(header)
    for payload in payloads:
        offsets.append(cursor)
        cursor += len(payload)
    for lod_index in range(N_LODS):
        section_index = N_LODS - lod_index
        split = len(lod0_records) if lod_index == 0 else len(lower_records)
        struct.pack_into("<I", section_0, 5 + lod_index * 4, offsets[section_index])
        struct.pack_into("<I", section_0, 5 + N_LODS * 4 + lod_index * 4, offsets[section_index] + split)
    payloads[0] = bytes(section_0)
    return bytes(header) + b"".join(payloads)


def _deleted_quad(original: ParsedMesh) -> ParsedMesh:
    """Face Delete keeping triangle 0 and its three vertices."""
    import copy

    edited = copy.deepcopy(original)
    submesh = edited.submeshes[0]
    provenance = compose_topology_provenance(
        identity_topology_provenance(len(original.submeshes[0].vertices), len(original.submeshes[0].faces)),
        copy_vertex_indices=(0, 1, 2),
        face_origins=(0,),
    )
    submesh.vertices = list(original.submeshes[0].vertices[:3])
    submesh.uvs = list(original.submeshes[0].uvs[:3]) if original.submeshes[0].uvs else []
    submesh.normals = list(original.submeshes[0].normals[:3]) if original.submeshes[0].normals else []
    submesh.faces = [(0, 1, 2)]
    submesh.bone_indices = list(original.submeshes[0].bone_indices[:3])
    submesh.bone_weights = list(original.submeshes[0].bone_weights[:3])
    submesh.source_vertex_map = list(topology_source_vertex_map(provenance))
    submesh.source_vertex_map_authority = "topology"
    submesh.source_vertex_offsets = list(original.submeshes[0].source_vertex_offsets[:3])
    submesh.vertex_count = 3
    submesh.face_count = 1
    submesh.topology_provenance = provenance
    return edited


def _subdivided_quad(original: ParsedMesh) -> ParsedMesh:
    """One midpoint on the edge between original vertices 0 and 1."""
    import copy

    edited = copy.deepcopy(original)
    source = original.submeshes[0]
    submesh = edited.submeshes[0]
    provenance = compose_topology_provenance(
        identity_topology_provenance(len(source.vertices), len(source.faces)),
        copy_vertex_indices=(0, 1, 2, 3, -1),
        vertex_blends=({"index": 4, "left": 0, "right": 1, "factor": 0.5},),
        face_origins=(0, 0, 1),
    )
    midpoint = tuple(
        (source.vertices[0][axis] + source.vertices[1][axis]) * 0.5 for axis in range(3)
    )
    submesh.vertices = list(source.vertices) + [midpoint]
    submesh.uvs = list(source.uvs) + [source.uvs[0]] if source.uvs else []
    submesh.normals = list(source.normals) + [source.normals[0]] if source.normals else []
    submesh.faces = [(0, 4, 2), (4, 1, 2), (1, 3, 2)]
    if source.bone_indices:
        submesh.bone_indices = list(source.bone_indices) + [source.bone_indices[0]]
        submesh.bone_weights = list(source.bone_weights) + [source.bone_weights[0]]
    submesh.source_vertex_map = list(topology_source_vertex_map(provenance))
    submesh.source_vertex_map_authority = "topology"
    submesh.source_vertex_offsets = list(source.source_vertex_offsets) + [-1]
    submesh.vertex_count = 5
    submesh.face_count = 3
    submesh.topology_provenance = provenance
    return edited


def _lower_lod_payloads(data: bytes) -> list[bytes]:
    from cdmw.modding.mesh_parser import _parse_par_sections

    return [
        bytes(data[section["offset"] : section["offset"] + section["size"]])
        for section in _parse_par_sections(data)
        if 1 <= section["index"] < N_LODS
    ]


# ── ownership mask ───────────────────────────────────────────────────


def test_protected_mask_owns_only_the_proven_lanes() -> None:
    static_mask = protected_byte_mask(skinned=False)
    skinned_mask = protected_byte_mask(skinned=True)

    assert all(static_mask[offset] == 0x00 for offset in range(0, 6))
    assert all(static_mask[offset] == 0x00 for offset in range(8, 12))
    assert static_mask[16:19] == b"\x00\x00\x00"
    # The top two bits of the normal u32 stay protected.
    assert static_mask[19] == 0xC0
    assert static_mask[6] == 0xFF and static_mask[7] == 0xFF
    assert all(static_mask[offset] == 0xFF for offset in range(12, 16))
    assert all(static_mask[offset] == 0xFF for offset in range(20, 34))
    assert all(static_mask[offset] == 0xFF for offset in range(34, 40))
    # Skinned records additionally own the palette groups and weight bytes.
    assert skinned_mask[20:23] == b"\x00\x00\x00" and skinned_mask[23] == 0xC0
    assert skinned_mask[24:27] == b"\x00\x00\x00" and skinned_mask[27] == 0xC0
    assert all(skinned_mask[offset] == 0x00 for offset in range(28, 34))
    assert all(skinned_mask[offset] == 0xFF for offset in range(34, 40))


# ── admission ────────────────────────────────────────────────────────


def test_a_mesh_without_any_contract_is_not_admitted() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")

    assert topology_rebuild_blockers(original, original, data) == (TOPOLOGY_PROVENANCE_REQUIRED,)


def test_an_empty_output_submesh_is_blocked() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    edited = _deleted_quad(original)
    edited.submeshes[0].vertices = []
    edited.submeshes[0].faces = []

    assert TOPOLOGY_EMPTY_SUBMESH_UNSUPPORTED in topology_rebuild_blockers(original, edited, data)


def test_a_position_outside_the_original_bounds_is_blocked() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    edited = _deleted_quad(original)
    edited.submeshes[0].vertices[0] = (5.0, 0.0, 0.0)

    assert TOPOLOGY_BOUNDS_EXCEED_SOURCE in topology_rebuild_blockers(original, edited, data)


def test_parents_that_disagree_on_a_protected_byte_block_the_rebuild() -> None:
    data = _pac_fixture(protected_divergence=True)
    original = parse_pac(data, "target.pac")
    edited = _subdivided_quad(original)

    assert TOPOLOGY_PROTECTED_BYTES_DIVERGE in topology_rebuild_blockers(original, edited, data)


def test_more_than_six_merged_influences_block_before_encoding() -> None:
    records = [bytearray(40) for _ in range(2)]
    _skin(records[0], (1, 2, 3, 4), (64, 64, 64, 63))
    _skin(records[1], (5, 6, 7, 8), (64, 64, 64, 63))

    with pytest.raises(PacTopologyRebuildBlocked) as blocked:
        derived_skin_row([bytes(records[0]), bytes(records[1])], (0.5, 0.5))

    assert TOPOLOGY_SKIN_INFLUENCE_CAPACITY_EXCEEDED in blocked.value.blockers


def test_a_derived_row_normalizes_source_totals_that_are_not_exactly_255() -> None:
    left = bytearray(40)
    right = bytearray(40)
    # Observed source rows total 255 +/- 2.
    _skin(left, (3, 7), (200, 57))
    _skin(right, (3, 7), (150, 103))

    slots, weights = derived_skin_row([bytes(left), bytes(right)], (0.5, 0.5))

    assert set(slots) == {3, 7}
    assert sum(weights) == pytest.approx(1.0, abs=1e-12)


# ── exact rebuild ────────────────────────────────────────────────────


def test_face_delete_shrinks_lod0_and_leaves_everything_else_byte_identical() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    edited = _deleted_quad(original)
    report: dict[str, object] = {}

    rebuilt = build_pac_topology_rebuild(original, edited, data, report=report)
    reparsed = parse_pac(rebuilt, "target.pac")

    assert len(reparsed.submeshes[0].vertices) == 3
    assert len(reparsed.submeshes[0].faces) == 1
    assert tuple(reparsed.submeshes[0].faces[0]) == (0, 1, 2)
    assert report["fallback_used"] is False
    assert report["serializer"] == "pac_lod0_topology_exact_v1"
    assert report["direct_vertex_count"] == 3
    assert report["blended_vertex_count"] == 0
    assert report["removed_vertex_count"] == 1
    assert report["removed_face_count"] == 1
    assert _lower_lod_payloads(rebuilt) == _lower_lod_payloads(data)


def test_direct_vertices_keep_their_original_record_bytes_exactly() -> None:
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    edited = _deleted_quad(original)

    rebuilt = build_pac_topology_rebuild(original, edited, data)
    reparsed = parse_pac(rebuilt, "target.pac")

    for index, offset in enumerate(reparsed.submeshes[0].source_vertex_offsets):
        rebuilt_record = rebuilt[offset : offset + 40]
        source_offset = original.submeshes[0].source_vertex_offsets[index]
        assert rebuilt_record == data[source_offset : source_offset + 40]


def test_midpoint_subdivide_grows_lod0_and_derives_its_record_from_the_parents() -> None:
    data = _pac_fixture(skinned=True)
    original = parse_pac(data, "target.pac")
    edited = _subdivided_quad(original)
    report: dict[str, object] = {}

    rebuilt = build_pac_topology_rebuild(original, edited, data, report=report)
    reparsed = parse_pac(rebuilt, "target.pac")

    assert len(reparsed.submeshes[0].vertices) == 5
    assert len(reparsed.submeshes[0].faces) == 3
    assert report["blended_vertex_count"] == 1
    assert report["lost_influence_mass"] == 0.0
    assert report["influence_union_width"] == 2
    assert _lower_lod_payloads(rebuilt) == _lower_lod_payloads(data)

    derived_offset = reparsed.submeshes[0].source_vertex_offsets[4]
    derived_record = rebuilt[derived_offset : derived_offset + 40]
    parent_offset = original.submeshes[0].source_vertex_offsets[0]
    parent_record = data[parent_offset : parent_offset + 40]
    mask = protected_byte_mask(skinned=True)
    assert bytes(a & m for a, m in zip(derived_record, mask)) == bytes(
        a & m for a, m in zip(parent_record, mask)
    )
    assert sum(derived_record[PAC_SKIN_WEIGHT_OFFSET : PAC_SKIN_WEIGHT_OFFSET + PAC_SKIN_INFLUENCES]) == 255
    assert set(reparsed.submeshes[0].bone_indices[4]) == {3, 7}


def test_the_descriptor_bounds_are_never_moved() -> None:
    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    edited = _deleted_quad(original)

    rebuilt = build_pac_topology_rebuild(original, edited, data)
    reparsed = parse_pac(rebuilt, "target.pac")

    assert reparsed.submeshes[0].source_bbox_min == original.submeshes[0].source_bbox_min
    assert reparsed.submeshes[0].source_bbox_extent == original.submeshes[0].source_bbox_extent


def test_lower_lod_counts_survive_a_lod0_rebuild() -> None:
    from cdmw.modding.mesh_parser import _find_pac_descriptors, _parse_par_sections

    data = _pac_fixture()
    original = parse_pac(data, "target.pac")
    edited = _deleted_quad(original)

    rebuilt = build_pac_topology_rebuild(original, edited, data)

    def counts(payload: bytes) -> tuple[list[int], list[int]]:
        sections = {section["index"]: section for section in _parse_par_sections(payload)}
        descriptors = _find_pac_descriptors(
            payload, sections[0]["offset"], sections[0]["size"], N_LODS
        )
        return list(descriptors[0].vertex_counts), list(descriptors[0].index_counts)

    original_vertices, original_indices = counts(data)
    rebuilt_vertices, rebuilt_indices = counts(rebuilt)

    assert rebuilt_vertices[0] == 3 and rebuilt_indices[0] == 3
    assert rebuilt_vertices[1:] == original_vertices[1:]
    assert rebuilt_indices[1:] == original_indices[1:]


def test_the_serializer_never_reaches_for_a_donor_or_a_fallback() -> None:
    import cdmw.modding.mesh_pac_topology_builder as builder

    source = (builder.__file__ or "")
    with open(source, "r", encoding="utf-8") as handle:
        text = handle.read()

    # A source check is not proof of behaviour on its own, but importing the
    # donor chooser here would make the exact contract unenforceable, so the
    # absence of the import is worth pinning.
    assert "_choose_pac_donor_indices" not in text
    assert "transfer_native_mesh_skin_weights_from_source" not in text
    assert "_build_pac_full_rebuild" not in text


def test_a_lod0_that_would_stop_outranking_a_lower_lod_is_blocked() -> None:
    # parse_pac chooses the geometry section with the most faces, so a LOD0 that
    # shrinks past a stored lower LOD would be read as the wrong section.
    data = _pac_fixture(lower_matches_lod0=True)
    original = parse_pac(data, "target.pac")
    edited = _deleted_quad(original)

    assert TOPOLOGY_CONTRACT_UNSUPPORTED in topology_rebuild_blockers(original, edited, data)


def test_growing_lod0_over_an_equal_lower_lod_is_still_admitted() -> None:
    data = _pac_fixture(lower_matches_lod0=True)
    original = parse_pac(data, "target.pac")
    edited = _subdivided_quad(original)

    assert topology_rebuild_blockers(original, edited, data) == ()


def test_a_blocked_rebuild_produces_no_output_at_all() -> None:
    data = _pac_fixture(protected_divergence=True)
    original = parse_pac(data, "target.pac")
    edited = _subdivided_quad(original)
    digest_before = hashlib.sha256(data).hexdigest()

    with pytest.raises(PacTopologyRebuildBlocked) as blocked:
        build_pac_topology_rebuild(original, edited, data)

    assert TOPOLOGY_PROTECTED_BYTES_DIVERGE in blocked.value.blockers
    assert hashlib.sha256(data).hexdigest() == digest_before


def test_a_static_mesh_rebuilds_without_touching_the_skin_lanes() -> None:
    data = _pac_fixture(skinned=False)
    original = parse_pac(data, "target.pac")
    edited = _subdivided_quad(original)

    rebuilt = build_pac_topology_rebuild(original, edited, data)
    reparsed = parse_pac(rebuilt, "target.pac")

    derived_offset = reparsed.submeshes[0].source_vertex_offsets[4]
    parent_offset = original.submeshes[0].source_vertex_offsets[0]
    assert rebuilt[derived_offset + 20 : derived_offset + 40] == data[parent_offset + 20 : parent_offset + 40]
