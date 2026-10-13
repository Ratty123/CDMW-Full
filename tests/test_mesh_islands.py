"""PAC island exclusions follow separated, simplified components at every LOD."""

import struct
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_islands import apply_pac_island_exclusions, pac_island_face_masks
from cdmw.modding.pac_cloth import pac_cloth_lods
from tests.test_mesh_pac_topology_serializer import _skin, _vertex_record


def _island_lods(*, simplified=True, count=6):
    """Six separate ornaments; simplification splits, reorders and removes pieces."""
    source = []
    for island in range(count):
        x = 5000 + island * 8000
        source.append((island, [(x, 10000, 20000), (x + 3000, 10000, 20000),
                                (x, 13000, 20000), (x + 3000, 13000, 20000)],
                       [(0, 1, 2), (1, 3, 2)]))
    if not simplified:
        return [source] * 4
    split, coarse = [], []
    for island in reversed(range(count)):
        x = 5000 + island * 8000
        split.append((island, [(x - 100, 9900, 20020), (x + 3100, 9900, 20020),
                               (x - 100, 11400, 20020)], [(0, 1, 2)]))
        split.append((island, [(x + 3100, 11600, 20020), (x + 3100, 13100, 20020),
                               (x - 100, 13100, 20020)], [(0, 1, 2)]))
        coarse.append((island, [(x - 150, 9900, 20030), (x + 3100, 9900, 20030),
                                (x + 1500, 13100, 20030)], [(0, 1, 2)]))
    return [source, split, coarse, coarse[:max(1, count - 2)]]


def _island_pac(lods):
    metadata = bytearray(5 + 4 * 8)
    metadata[4] = 4
    metadata.extend(b'\x06target\x06target')
    descriptor = bytearray(64)
    descriptor[0] = 1
    struct.pack_into('<8f', descriptor, 3, 0, 0, 0, 0, 0, 1, 1, 1)
    descriptor[35:40] = bytes((4, 0, 1, 2, 3))
    payloads, splits, owners = [], [], []
    for lod_index, components in enumerate(lods):
        records, indices, labels = bytearray(), bytearray(), []
        for island, positions, faces in components:
            base = len(records) // 40
            for position in positions:
                record = _vertex_record(*position)
                _skin(record, (3,), (255,))
                records.extend(record)
            for face in faces:
                indices.extend(struct.pack('<3H', *(v + base for v in face)))
                labels.append(island)
        struct.pack_into('<H', descriptor, 40 + lod_index * 2, len(records) // 40)
        struct.pack_into('<I', descriptor, 48 + lod_index * 4, len(indices) // 2)
        splits.append(len(records))
        payloads.append(bytes(records + indices))
        owners.append(labels)
    metadata.extend(descriptor)
    header = bytearray(0x50)
    header[:4] = b'PAR '
    offset = len(header) + len(metadata)
    struct.pack_into('<I', header, 0x14, len(metadata))
    for section in range(1, 5):
        lod_index = 4 - section
        struct.pack_into('<I', header, 0x14 + section * 8, len(payloads[lod_index]))
        struct.pack_into('<I', metadata, 5 + lod_index * 4, offset)
        struct.pack_into('<I', metadata, 21 + lod_index * 4, offset + splits[lod_index])
        offset += len(payloads[lod_index])
    return bytes(header + metadata) + b''.join(reversed(payloads)), owners


def _expected_output(source, owners, excluded):
    expected = bytearray(source)
    masks = {}
    for lod_index, lod in enumerate(pac_cloth_lods(source)):
        part = lod.submeshes[0]
        masks[lod_index, 0] = tuple(i for i, owner in enumerate(owners[lod_index]) if owner in excluded)
        for face_index in masks[lod_index, 0]:
            vertex = part.faces[face_index][0]
            struct.pack_into('<3H', expected, part.source_index_offset + face_index * 6,
                             vertex, vertex, vertex)
    return bytes(expected), masks


@pytest.mark.parametrize('excluded', [(i,) for i in range(6)] + [(0, 2, 5), tuple(range(5))])
@pytest.mark.parametrize('simplified', [False, True])
def test_island_exclusion_preserves_every_other_byte_across_lods(excluded, simplified):
    source, owners = _island_pac(_island_lods(simplified=simplified))
    expected, masks = _expected_output(source, owners, excluded)
    exclusions = {0: masks[0, 0]}
    assert pac_island_face_masks(source, exclusions)[1] == masks
    assert apply_pac_island_exclusions(source, source, exclusions) == expected
    assert apply_pac_island_exclusions(source, source, {}) == source


@pytest.mark.parametrize('count', [2, 3, 7])
@pytest.mark.parametrize('axes,scale,mirror', [((0, 1, 2), 1, False),
                                             ((2, 0, 1), .125, False),
                                             ((1, 2, 0), .5, True)])
def test_simplified_mapping_is_independent_of_count_scale_and_orientation(count, axes, scale, mirror):
    lods = [[(owner, [tuple(round((65535 - p[a] if mirror else p[a]) * scale)
                           for a in axes) for p in points], faces)
             for owner, points, faces in lod] for lod in _island_lods(count=count)]
    source, owners = _island_pac(lods)
    expected, masks = _expected_output(source, owners, {0})
    assert pac_island_face_masks(source, {0: masks[0, 0]})[1] == masks
    assert apply_pac_island_exclusions(source, source, {0: masks[0, 0]}) == expected


@pytest.mark.parametrize('fault', ['between', 'remote', 'merged', 'overlapping'])
def test_unproven_simplified_components_are_rejected(fault):
    lods = _island_lods()
    if fault == 'between':
        lods[1][0] = (0, [(10000, 10000, 20000), (11000, 10000, 20000),
                         (10500, 13000, 20000)], [(0, 1, 2)])
    elif fault == 'remote':
        lods[1][0] = (0, [(5000, 40000, 20000), (8000, 40000, 20000),
                         (5000, 43000, 20000)], [(0, 1, 2)])
    elif fault == 'merged':
        # Exact anchors on both sides cannot authorize deleting a bridge.
        lods[1][0] = (0, [lods[0][0][1][0], lods[0][1][1][0], (6000, 13000, 20020)],
                     [(0, 1, 2)])
    else:
        # No shared vertices, but overlapping source bounds cannot prove ownership.
        lods[0][1] = (1, [(5500, 10500, 20000), (7500, 10500, 20000),
                         (5500, 12500, 20000)], [(0, 1, 2)])
    source, _ = _island_pac(lods)
    with pytest.raises(ValueError, match='ambiguous at LOD 1'):
        apply_pac_island_exclusions(source, source, {0: (0, 1)})


@pytest.mark.parametrize('hidden', [(0,), tuple(range(12))])
def test_partial_and_whole_part_exclusions_remain_rejected(hidden):
    source, _ = _island_pac(_island_lods())
    with pytest.raises(ValueError, match='boundaries share|Keep one island'):
        pac_island_face_masks(source, {0: hidden})


def test_failed_island_mapping_leaves_session_and_history_unchanged(tmp_path, monkeypatch):
    from cdmw.services.mesh_island_authoring import set_island_inclusion
    from cdmw.services.mesh_replacement_import import initial_replacement_state
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session

    lods = _island_lods()
    lods[1][0] = (0, [lods[0][0][1][0], lods[0][1][1][0], (6000, 13000, 20020)], [(0, 1, 2)])
    source, _ = _island_pac(lods)
    monkeypatch.setattr('tests.test_mesh_rust_authoring_exact_output._pac_fixture', lambda **kw: source)
    _, service, session = _open_exact_session(tmp_path / 'session')
    try:
        shadow = session.shadow_service
        before = shadow.capture_export_snapshot(session.shadow_session_id)
        view = shadow.session_view(session.shadow_session_id)
        part_id = initial_replacement_state(before).parts[0].part_id
        with pytest.raises(ValueError, match='ambiguous at LOD 1'):
            set_island_inclusion(session, before, {'part_id': part_id, 'faces': [0, 1], 'included': False})
        after = shadow.capture_export_snapshot(session.shadow_session_id)
        assert after.mesh_revision == before.mesh_revision
        assert after.replacement_state is None
        assert shadow.session_view(session.shadow_session_id).undo_count == view.undo_count
        assert list(after.mesh.submeshes[0].vertices) == list(before.mesh.submeshes[0].vertices)
        assert after.mesh.submeshes[0].faces == before.mesh.submeshes[0].faces
    finally:
        session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)


def test_island_host_command_restores_output_with_history_and_finish(tmp_path, monkeypatch):
    from cdmw.models import ArchiveEntry
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
    from tests.test_mesh_rust_replacement import command

    source, owners = _island_pac(_island_lods())
    monkeypatch.setattr('tests.test_mesh_rust_authoring_exact_output._pac_fixture', lambda **kw: source)
    _, service, session = _open_exact_session(tmp_path / 'session')
    try:
        part_id = session.state_payload()['replacement']['parts'][0]['id']
        arguments = {'part_id': part_id, 'faces': [0, 1], 'included': False,
                     '_archive_entry': ArchiveEntry('owned-rust-exact.pac', tmp_path / '0009/0.pamt',
                                                    tmp_path / '0009/0.paz', 0, 0, 0, 0, 0),
                     '_archive_dependencies': SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})}
        before = service.capture_export_snapshot(session.authoritative_session_id)
        command(session, 'replacement_islands', arguments)
        shadow = session.shadow_service
        snapshot = shadow.capture_export_snapshot(session.shadow_session_id)
        expected = _expected_output(source, owners, {0})[0]
        assert prepare_replacement_output(snapshot).data == expected
        assert snapshot.mesh.submeshes[0].faces == before.mesh.submeshes[0].faces
        assert list(snapshot.mesh.submeshes[0].vertices) == list(before.mesh.submeshes[0].vertices)
        command(session, 'undo')
        assert shadow.capture_export_snapshot(session.shadow_session_id).replacement_state is None
        command(session, 'redo')
        assert prepare_replacement_output(shadow.capture_export_snapshot(session.shadow_session_id)).data == expected
        command(session, 'replacement_islands', {**arguments, 'included': True})
        assert prepare_replacement_output(shadow.capture_export_snapshot(session.shadow_session_id)).data == source
        command(session, 'replacement_islands', arguments)
        assert service.session_view(session.authoritative_session_id).revision == before.mesh_revision
        session.finish(_request(session, 'finish_request', 22))
        result, _ = service.rebuild_result_from_snapshot(service.capture_export_snapshot(session.authoritative_session_id))
        assert result.data == expected
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id, force_without_saving=True)
