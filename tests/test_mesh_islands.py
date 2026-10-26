"""PAC island exclusions follow separated, simplified components at every LOD."""

import struct
import json
from dataclasses import replace
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
        # Separate seam vertices retain a single island. Keep LOD0 at least as
        # detailed as the split LOD so the general PAC parser selects LOD0.
        source.append((island, [(x, 10000, 20000), (x + 3000, 10000, 20000),
                                (x, 13000, 20000), (x + 3000, 10000, 20000),
                                (x + 3000, 13000, 20000), (x, 13000, 20000)],
                       [(0, 1, 2), (3, 4, 5)]))
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


def _record_island_pac(*, count=6, axes=(0, 1, 2), scale=1, mirror=False, disappear=False, vary_masks=False, corner_motion=False):
    """Intersecting component bounds, retained UV/skin, and changing normals."""
    square = [(10000, 10000, 20000), (30000, 10000, 20000),
              (10000, 30000, 20000), (30000, 10000, 20000),
              (30000, 30000, 20000), (10000, 30000, 20000)]
    if corner_motion:
        # A fine corner next to a longer panel, like the reported belt accessory.
        square = [(10000, 10000, 20000), (12000, 10000, 20000),
                  (10000, 12000, 20000), (12000, 10000, 20000),
                  (30000, 30000, 20000), (10000, 12000, 20000)]
    uvs = [(0, 0), (1, 0), (0, 1), (1, 0), (1, 1), (0, 1)]
    lods = []
    for lod in range(4):
        components = []
        for owner in range(count):
            shape = list(square)
            if corner_motion and lod == 3:
                shape[0] = (10000, 13750, 20000)
            points = [tuple(round(((65535 - p[a] if mirror else p[a]) + owner // 2 * 2000
                                   + lod * (300, -200, 100)[a]) * scale) for a in axes)
                      for p in (shape if owner % 2 == 0 else [tuple(p[a] for a in (2, 0, 1)) for p in shape])]
            components.append((owner, points, [(0, 1, 2), (3, 4, 5)]))
        if disappear and lod == 3:
            components = components[:1]
        lods.append(components if lod % 2 == 0 else list(reversed(components)))
    source, owners = _island_pac(lods)
    raw = bytearray(source)
    for lod_index, lod in enumerate(pac_cloth_lods(source)):
        part = lod.submeshes[0]
        for component, (owner, _, _) in enumerate(lods[lod_index]):
            for vertex, uv in enumerate(uvs):
                offset = part.source_vertex_offsets[component * 6 + vertex]
                record = bytearray(raw[offset:offset + 40])
                struct.pack_into('<2e', record, 8, *uv)
                struct.pack_into('<I', record, 16, 0x40000000 + lod_index)
                _skin(record, (3, 4), (255 - owner * 20, owner * 20))
                if vary_masks:
                    record[36] = 40 + lod_index
                raw[offset:offset + 40] = record
    return bytes(raw), owners


@pytest.mark.parametrize('excluded', [(0,), (1,), (0, 2, 5)])
@pytest.mark.parametrize('vary_masks', [False, True], ids=['raw-records', 'resolved-skin'])
@pytest.mark.parametrize('axes,scale,mirror', [((0, 1, 2), 1, False),
                                             ((2, 0, 1), .125, False),
                                             ((1, 2, 0), .5, True)])
def test_retained_records_map_intersecting_bounds_without_touching_other_bytes(excluded, axes, scale, mirror, vary_masks):
    source, owners = _record_island_pac(axes=axes, scale=scale, mirror=mirror, vary_masks=vary_masks)
    expected, masks = _expected_output(source, owners, set(excluded))
    assert pac_island_face_masks(source, {0: masks[0, 0]})[1] == masks
    assert apply_pac_island_exclusions(source, source, {0: masks[0, 0]}) == expected


@pytest.mark.parametrize('excluded', [(0,), (1,)])
@pytest.mark.parametrize('vary_masks', [False, True], ids=['raw-records', 'resolved-skin'])
@pytest.mark.parametrize('axes,scale,mirror', [((0, 1, 2), 1, False),
                                             ((2, 0, 1), .125, False),
                                             ((1, 2, 0), .5, True)])
def test_retained_corner_motion_maps_within_its_incident_neighbourhood(excluded, vary_masks, axes, scale, mirror):
    source, owners = _record_island_pac(count=2, corner_motion=True, vary_masks=vary_masks,
                                        axes=axes, scale=scale, mirror=mirror)
    expected, masks = _expected_output(source, owners, set(excluded))
    assert pac_island_face_masks(source, {0: masks[0, 0]})[1] == masks
    assert apply_pac_island_exclusions(source, source, {0: masks[0, 0]}) == expected


@pytest.mark.parametrize('position', [(10000, 16000, 20000), (29000, 29000, 20000)])
@pytest.mark.parametrize('vary_masks', [False, True], ids=['raw-records', 'resolved-skin'])
def test_retained_corner_motion_outside_its_incident_neighbourhood_stays_rejected(position, vary_masks):
    source, _ = _record_island_pac(count=2, corner_motion=True, vary_masks=vary_masks)
    raw = bytearray(source)
    part = pac_cloth_lods(source)[3].submeshes[0]
    # LOD3 reverses the components. Move owner 0 beyond its local neighbours,
    # including near a distant vertex in the same connected source component.
    struct.pack_into('<3H', raw, part.source_vertex_offsets[6],
                     *(value + 3 * shift for value, shift in zip(position, (300, -200, 100))))
    with pytest.raises(ValueError, match='ambiguous at LOD 3'):
        pac_island_face_masks(bytes(raw), {0: (0, 1)})


@pytest.mark.parametrize('fault', ['uv', 'nan_uv', 'skin', 'collision', 'merged', 'remote', 'position_conflict'])
@pytest.mark.parametrize('vary_masks', [False, True], ids=['raw-records', 'resolved-skin'])
def test_unproven_retained_records_remain_rejected(fault, vary_masks):
    source, _ = _record_island_pac(count=2, vary_masks=vary_masks)
    raw = bytearray(source)
    lods = pac_cloth_lods(source)
    # LOD1 is reversed; these are its first component's vertex records.
    part = lods[1].submeshes[0]
    offset = part.source_vertex_offsets[0]
    if fault == 'uv':
        struct.pack_into('<e', raw, offset + 8, .125)
    elif fault == 'nan_uv':
        # The general parser displays invalid UVs as zero; that is not lineage.
        struct.pack_into('<H', raw, offset + 8, 0x7e00)
    elif fault == 'skin':
        raw[offset + 28] -= 1
    elif fault == 'collision':
        for lod in lods:
            for offset in lod.submeshes[0].source_vertex_offsets:
                record = bytearray(raw[offset:offset + 40])
                _skin(record, (3, 4), (255, 0))
                raw[offset:offset + 40] = record
    elif fault == 'merged':
        struct.pack_into('<3H', raw, part.source_index_offset, 0, 1, 6)
    elif fault == 'remote':
        for offset in part.source_vertex_offsets[:6]:
            struct.pack_into('<H', raw, offset + 2, 65000)
    else:
        # Its attributes say retained, but its exact source position is excluded.
        source_offset = lods[0].submeshes[0].source_vertex_offsets[0]
        raw[offset:offset + 6] = raw[source_offset:source_offset + 6]
    with pytest.raises(ValueError, match='ambiguous at LOD 1'):
        apply_pac_island_exclusions(bytes(raw), bytes(raw), {0: (0, 1)})


def test_excluding_last_surviving_lower_lod_island_keeps_a_valid_invisible_slot():
    source, owners = _record_island_pac(count=2, disappear=True)
    original = pac_cloth_lods(source)
    exclusions = {0: tuple(i for i, owner in enumerate(owners[0]) if owner == 0)}
    result = apply_pac_island_exclusions(source, source, exclusions)
    decoded = pac_cloth_lods(result)
    assert len(decoded) == 4
    assert all(len(lod.submeshes) == 1 for lod in decoded)
    hidden = decoded[3].submeshes[0]
    assert len(hidden.vertices) == len(original[3].submeshes[0].vertices)
    assert len(hidden.faces) == 1
    vertices = hidden.faces[0]
    assert len(set(vertices)) == 3
    for field in ('bone_indices', 'bone_weights', 'uvs', 'normals'):
        values = getattr(hidden, field)
        assert values[vertices[0]] == values[vertices[1]] == values[vertices[2]]
    assert max(max(hidden.vertices[v][a] for v in vertices) - min(hidden.vertices[v][a] for v in vertices)
               for a in range(3)) < .002
    donor = original[3].submeshes[0].source_vertex_offsets[vertices[0]]
    for vertex in vertices:
        offset = hidden.source_vertex_offsets[vertex]
        assert result[offset + 6:offset + 40] == source[donor + 6:donor + 40]
    for lod, before in zip(decoded[:3], original[:3]):
        part = lod.submeshes[0]
        for a, b in zip(part.source_vertex_offsets, before.submeshes[0].source_vertex_offsets):
            assert result[a:a + 40] == source[b:b + 40]


@pytest.mark.parametrize('extent', [(100, 100, 100), (0, 0, 1)])
def test_empty_lod_refuses_an_unrepresentable_invisible_placeholder(extent):
    from cdmw.modding.mesh_islands import _preserve_empty_island_part

    source, _ = _record_island_pac(count=2, disappear=True)
    part = replace(pac_cloth_lods(source)[3].submeshes[0], source_bbox_extent=extent)
    with pytest.raises(ValueError, match='cannot preserve an invisible part at LOD 3'):
        _preserve_empty_island_part(bytearray(source), part, 3)


def test_retained_record_mapping_cancellation_is_not_an_ambiguous_result():
    from cdmw.domain.cancellation import RunCancelled
    from cdmw.modding.mesh_islands import _island_record_owners, _retained_island_faces

    class StopAfterSixChecks:
        calls = 0

        def is_set(self):
            self.calls += 1
            return self.calls >= 6

    source, _ = _record_island_pac(count=2)
    lods = pac_cloth_lods(source)
    before, current = lods[0].submeshes[0], lods[1].submeshes[0]
    records = _island_record_owners(source, before, {0, 1})
    with pytest.raises(RunCancelled):
        _retained_island_faces(source, before, current, records, {}, stop_event=StopAfterSixChecks())


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


@pytest.mark.parametrize('corner_motion', [False, True], ids=['separated-bounds', 'local-record-motion'])
def test_island_host_command_restores_output_with_history_and_finish(tmp_path, monkeypatch, corner_motion):
    from cdmw.models import ArchiveEntry
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
    from tests.test_mesh_rust_replacement import command

    source, owners = (_record_island_pac(corner_motion=True, vary_masks=True) if corner_motion
                      else _island_pac(_island_lods()))
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


@pytest.fixture
def island_host(tmp_path, monkeypatch, request):
    from cdmw.models import ArchiveEntry
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
    from tests.test_mesh_rust_replacement import command

    scenario = getattr(request, 'param', 6)
    source, owners = (_record_island_pac(vary_masks=scenario == 'decoded-records') if scenario in {'retained-records', 'decoded-records'}
                      else _island_pac(_island_lods(count=scenario)))
    monkeypatch.setattr('tests.test_mesh_rust_authoring_exact_output._pac_fixture', lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / 'session')
    snapshot = service.capture_export_snapshot(host.authoritative_session_id)
    assert snapshot.mesh.submeshes[0].faces == pac_cloth_lods(source)[0].submeshes[0].faces
    original_path = tmp_path / 'source.pac'
    original_path.write_bytes(source)
    target = ArchiveEntry(snapshot.mesh.path, tmp_path / '0009/0.pamt', original_path,
                          0, len(source), len(source), 0, 0)
    command(host, 'select', {'selection': {'source_indices': [0]}, 'operation': 'replace'})
    part_id = host.state_payload()['replacement']['parts'][0]['id']
    arguments = {'part_id': part_id, 'included': False, '_archive_entry': target,
                 '_archive_dependencies': SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})}
    yield source, owners, service, host, target, arguments
    if not host.closed:
        host.cancel()
    service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def test_island_color_metadata_matches_list_and_roundtrips(island_host):
    _, _, _, host, _, _ = island_host
    state = json.loads(json.dumps(host.state_payload()))
    mesh = host.shadow_service._session(host.shadow_session_id).working_mesh
    colors = state['mesh_islands']['color_faces']
    assert len(colors) == len(mesh.submeshes)
    for row in state['mesh_islands']['parts']:
        assert len(colors[row['index']]) == len(mesh.submeshes[row['index']].faces)
        for island in row['islands']:
            assert all(colors[row['index']][face] == min(island['faces']) for face in island['faces'])


@pytest.mark.parametrize('island_host', [1, 6], indirect=True, ids=['single-island', 'last-island'])
def test_last_island_uses_whole_part_output_and_can_be_restored(island_host):
    from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from tests.test_mesh_rust_authoring_exact_output import _request
    from tests.test_mesh_rust_replacement import command

    _, _, service, host, target, arguments = island_host
    shadow = host.shadow_service
    original = shadow.capture_export_snapshot(host.shadow_session_id)
    replacement = initial_replacement_state(original, target)
    removed = replace(replacement, parts=tuple(replace(part, included=False) for part in replacement.parts))
    expected = prepare_replacement_output(replace(original, mesh=mesh_with_part_ids(original, replacement),
                                                replacement_state=removed)).data
    groups = host.state_payload()['mesh_islands']['parts'][0]['islands']
    for group in groups[:-1]:
        command(host, 'replacement_islands', {**arguments, 'faces': group['faces']})
    before = shadow.capture_export_snapshot(host.shadow_session_id)
    before_data = shadow.rebuild_result_from_snapshot(before)[0].data
    last = {**arguments, 'faces': groups[-1]['faces']}
    state = command(host, 'replacement_islands', last)['state']
    assert state['replacement']['parts'][0]['included']
    assert state['mesh_islands']['parts'][0]['available']
    assert all(not island['included'] for island in state['mesh_islands']['parts'][0]['islands'])
    snapshot = shadow.capture_export_snapshot(host.shadow_session_id)
    assert snapshot.mesh.submeshes[0].faces == original.mesh.submeshes[0].faces
    assert list(snapshot.mesh.submeshes[0].vertices) == list(original.mesh.submeshes[0].vertices)
    assert prepare_replacement_output(snapshot).data == expected
    command(host, 'undo')
    assert shadow.rebuild_result_from_snapshot(shadow.capture_export_snapshot(host.shadow_session_id))[0].data == before_data
    command(host, 'redo')
    assert prepare_replacement_output(shadow.capture_export_snapshot(host.shadow_session_id)).data == expected
    command(host, 'replacement_islands', {**last, 'included': True})
    assert shadow.rebuild_result_from_snapshot(shadow.capture_export_snapshot(host.shadow_session_id))[0].data == before_data
    command(host, 'replacement_islands', last)
    for included in (False, True):
        command(host, 'replacement_include', {'part_ids': [arguments['part_id']], 'included': included})
        assert prepare_replacement_output(shadow.capture_export_snapshot(host.shadow_session_id)).data == expected
    host.finish(_request(host, 'finish_request', 22))
    assert service.rebuild_result_from_snapshot(service.capture_export_snapshot(host.authoritative_session_id))[0].data == expected


@pytest.mark.parametrize('part_index', [0, 1])
def test_last_island_preserves_other_part_records_at_every_lod(tmp_path, monkeypatch, part_index):
    from cdmw.models import ArchiveEntry
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from tests.test_mesh_editor_replacement_regressions import _distinct_lods, _lod_part_records
    from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
    from tests.test_mesh_rust_replacement import command

    source = _distinct_lods()
    monkeypatch.setattr('tests.test_mesh_rust_authoring_exact_output._pac_fixture', lambda **kw: source)
    _, service, host = _open_exact_session(tmp_path / 'session')
    try:
        command(host, 'select', {'selection': {'source_indices': [part_index]}, 'operation': 'replace'})
        part = host.state_payload()['replacement']['parts'][part_index]
        before = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        command(host, 'replacement_islands', {
            'part_id': part['id'], 'faces': list(range(len(before.mesh.submeshes[part_index].faces))),
            'included': False,
            '_archive_entry': ArchiveEntry(before.mesh.path, tmp_path / '0009/0.pamt',
                                          tmp_path / '0009/0.paz', 0, 0, 0, 0, 0),
            '_archive_dependencies': SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})})
        snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
        output = prepare_replacement_output(snapshot).data
        for lod_index, lod in enumerate(pac_cloth_lods(output)):
            assert len(lod.submeshes) == 2
            assert _lod_part_records(output, lod_index, 1 - part_index) == _lod_part_records(source, lod_index, 1 - part_index)
            hidden = lod.submeshes[part_index]
            assert len(hidden.faces) == 1
            assert max(max(v[axis] for v in hidden.vertices) - min(v[axis] for v in hidden.vertices)
                       for axis in range(3)) < .002
        assert snapshot.original_data == source
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize('island_host', [6, 'retained-records', 'decoded-records'], indirect=True, ids=['bounds', 'raw-records', 'resolved-skin'])
@pytest.mark.parametrize('excluded', [(0, 2), tuple(range(6))], ids=['some-islands', 'all-islands'])
@pytest.mark.parametrize('manager,folder', [('dmm', ''), ('jmm', ''),
                                           ('cdumm', 'files'), ('crimson_sharp', 'files')])
def test_island_mod_preview_draft_and_manager_exports(island_host, tmp_path, manager, folder, excluded):
    from cdmw.modding.mesh_parser import parse_mesh
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from cdmw.services.mesh_rust_authoring import read_owned_payload_reference
    from cdmw.services.mesh_service import MeshService
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker
    from tests.test_mesh_rust_authoring_exact_output import _request
    from tests.test_mesh_rust_replacement import command

    source, owners, service, host, target, arguments = island_host
    excluded = set(excluded)
    for island in sorted(excluded):
        faces = [i for i, owner in enumerate(owners[0]) if owner == island]
        state = command(host, 'replacement_islands', {**arguments, 'faces': faces})['state']
        assert not state['mesh_islands']['parts'][0]['islands'][island]['included']
        assert state['replacement']['parts'][0]['included']
    snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
    if excluded == set(owners[0]):
        removed = replace(snapshot.replacement_state, parts=tuple(
            replace(part, included=False) for part in snapshot.replacement_state.parts))
        expected = prepare_replacement_output(replace(snapshot, replacement_state=removed)).data
    else:
        expected = _expected_output(source, owners, excluded)[0]
    source_faces = pac_cloth_lods(source)[0].submeshes[0].faces
    output_faces = parse_mesh(expected, snapshot.mesh.path).submeshes[0].faces
    for mode in ('output', 'original', 'edit'):
        state = command(host, 'replacement_compare', {'mode': mode})['state']
        document = read_owned_payload_reference(host.root, state['document'])
        indices = document['lods'][0]['submeshes'][0]['indices']
        drawn = [tuple(indices[i:i + 3]) for i in range(0, len(indices), 3)
                 if len(set(indices[i:i + 3])) == 3]
        wanted = output_faces if mode == 'output' else source_faces
        assert drawn == wanted
    host.finish(_request(host, 'finish_request', 22))
    sid = host.authoritative_session_id
    snapshot = service.capture_export_snapshot(sid)
    draft = tmp_path / 'draft/mesh_layers.json'
    service._session(sid).mesh_layer_project_path = draft
    service.retry_mesh_layer_autosave(sid)
    assert json.loads(draft.read_text())['format'] == 'mesh_layer_project_v2'
    seed = parse_mesh(source, snapshot.mesh.path)
    seed._cdmw_original_data = source
    seed._cdmw_mesh_layer_project_path = str(draft)
    reopened = MeshService()
    view = reopened.open_edit_session(seed)
    try:
        loaded = reopened.capture_export_snapshot(view.session_id)
        assert loaded.replacement_state == snapshot.replacement_state
        assert reopened.rebuild_result_from_snapshot(loaded)[0].data == expected
        output_path = tmp_path / 'package'
        worker = MeshDirectOutputWorker(1, reopened, view.session_id, target, kind='loose_mod',
                                        output_path=output_path, manager_profile=manager)
        errors, completed = [], []
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors and len(completed) == 1, errors
        assert completed[0].rebuild_report.validation_status == 'passed'
        assert (output_path / folder / target.path).read_bytes() == expected
        assert target.paz_file.read_bytes() == source
    finally:
        reopened.close_edit_session(view.session_id, force_without_saving=True)


def test_island_and_whole_part_mod_controls_keep_separate_state(island_host):
    from cdmw.services.mesh_replacement_output import prepare_replacement_output
    from tests.test_mesh_rust_replacement import command

    source, owners, _, host, _, arguments = island_host
    command(host, 'replacement_islands', {**arguments, 'faces': [0, 1]})
    state = command(host, 'replacement_include', {'part_ids': [arguments['part_id']], 'included': False})['state']
    assert not state['replacement']['parts'][0]['included']
    assert not state['mesh_islands']['parts'][0]['available']
    state = command(host, 'replacement_include', {'part_ids': [arguments['part_id']], 'included': True})['state']
    islands = state['mesh_islands']['parts'][0]
    assert islands['available']
    assert [row['included'] for row in islands['islands']] == [False, True, True, True, True, True]
    snapshot = host.shadow_service.capture_export_snapshot(host.shadow_session_id)
    assert prepare_replacement_output(snapshot).data == _expected_output(source, owners, {0})[0]


def test_island_mod_topology_restriction_tracks_delete_and_undo(island_host):
    from cdmw.domain.mesh import MeshEditCommand, MeshEditSelection
    from tests.test_mesh_rust_replacement import command

    _, _, _, host, _, arguments = island_host
    assert host.state_payload()['mesh_islands']['parts'][0]['available']
    deleted = host.shadow_service.apply_command(host.shadow_session_id, MeshEditCommand(
        'delete', selection=MeshEditSelection.from_maps(faces_by_submesh={0: (0,)}),
        params={'_include_preview_deltas': False}, mode='edit'))
    assert deleted.ok
    row = host.state_payload()['mesh_islands']['parts'][0]
    assert not row['available']
    assert 'Start next edit pass' in row['reason']
    with pytest.raises(ValueError, match='Start next edit pass'):
        command(host, 'replacement_islands', {**arguments, 'faces': row['islands'][0]['faces']})
    restored = command(host, 'undo')['state']['mesh_islands']['parts'][0]
    assert restored['available']
    assert not restored['reason']
    changed = command(host, 'replacement_islands', {**arguments, 'faces': [0, 1]})['state']
    assert not changed['mesh_islands']['parts'][0]['islands'][0]['included']


def test_island_mod_free_edit_reason_explains_obj_output(island_host, tmp_path):
    from tests.test_mesh_rust_replacement import command

    _, _, _, host, _, _ = island_host
    state = command(host, 'configure_output_policy', {
        'policy': 'free_edit_rebuild', 'destination': str(tmp_path / 'output')})['state']
    row = state['mesh_islands']['parts'][0]
    assert not row['available']
    assert 'Free Edit' in row['reason'] and 'OBJ' in row['reason']
    assert row['islands']


@pytest.mark.parametrize('refit_kind', ['archive', 'profile'])
def test_island_mod_refit_reason_preserves_fit_and_advises_continuation(island_host, monkeypatch, refit_kind):
    from cdmw.services.mesh_island_authoring import island_ui_state
    from cdmw.services.mesh_rust_replacement import replacement_ui_state, run_replacement_command

    _, _, _, host, _, _ = island_host
    shadow = host.shadow_service._session(host.shadow_session_id)
    with monkeypatch.context() as scoped:
        if refit_kind == 'archive':
            scoped.setattr(shadow, 'archive_refit_context', object())
        else:
            scoped.setitem(host.shadow_service._morph_sessions, host.shadow_session_id,
                           SimpleNamespace(profile=object()))
        replacement = replacement_ui_state(host)
        assert not replacement['available']
        assert 'Start next edit pass' in replacement['reason']
        with pytest.raises(ValueError, match='Start next edit pass'):
            run_replacement_command(host, 'replacement_include', {}, None)
        row = island_ui_state(host, replacement)['parts'][0]
        assert not row['available']
        assert 'Finish Morph & Refit' in row['reason']
        assert 'Start next edit pass' in row['reason']
        assert 'Undo' not in row['reason']


def test_island_mod_import_reason_uses_new_finished_mesh(island_host, tmp_path):
    from tests.test_mesh_rust_replacement import command, prepare_source

    _, _, _, host, _, arguments = island_host
    prepared = prepare_source(host, tmp_path)
    target_id = prepared['state']['replacement']['pending']['targets'][0]['id']
    state = command(host, 'replacement_apply', {'targets': [target_id]})['state']
    row = state['mesh_islands']['parts'][0]
    assert not row['available']
    assert 'Start next edit pass' in row['reason']
    with pytest.raises(ValueError, match='Start next edit pass'):
        command(host, 'replacement_islands', {**arguments, 'faces': row['islands'][0]['faces']})
