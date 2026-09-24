"""Island editing preserves source geometry and masks only proven PAC triangles."""
from types import SimpleNamespace
import struct
from unittest.mock import patch

import pytest
from cdmw.models import ArchiveEntry

from cdmw.modding.mesh_islands import mesh_islands, apply_pac_island_exclusions
from cdmw.modding.pac_cloth import pac_cloth_lods
from tests.test_pac_skin_extra_influences import _record
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session, _request
from tests.test_mesh_rust_replacement import command


def island_pac():
    metadata = bytearray(37)
    metadata[4] = 4
    name = b'islands'
    metadata.extend(bytes([len(name)]) + name + bytes([len(name)]) + name)
    descriptor = bytearray(64)
    descriptor[0] = 1
    struct.pack_into('<8f', descriptor, 3, 0, 0, 0, 0, 0, 1, 1, 1)
    descriptor[35:40] = bytes([4, 0, 1, 2, 3])
    vertices = bytearray()
    for x, y in ((0, 0), (8000, 0), (0, 8000), (20000, 20000), (30000, 20000), (20000, 30000)):
        row = bytearray(_record(palette=(1, 2, 3, 4, 5, 6), weights=(255, 0, 0, 0, 0, 0, 0, 0), extra=(0., 1.), gate=63))
        struct.pack_into('<3H', row, 0, x, y, 0)
        vertices.extend(row)
    for lod in range(4):
        struct.pack_into('<H', descriptor, 40 + lod * 2, 6)
        struct.pack_into('<I', descriptor, 48 + lod * 4, 6)
    metadata.extend(descriptor)
    payload = vertices + struct.pack('<6H', 0, 1, 2, 3, 4, 5)
    header = bytearray(80)
    header[:4] = b'PAR '
    cursor = 80
    for section, data in enumerate([metadata, payload, payload, payload, payload]):
        struct.pack_into('<II', header, 16 + section * 8, 0, len(data))
        if section:
            lod = 4 - section
            struct.pack_into('<I', metadata, 5 + lod * 4, cursor)
            struct.pack_into('<I', metadata, 21 + lod * 4, cursor + len(vertices))
        cursor += len(data)
    return bytes(header + metadata + payload * 4)


def test_seams_join_without_welding_or_crossing_spatial_gaps():
    part = SimpleNamespace(vertices=[(0,0,0), (1,0,0), (0,1,0), (0,0,0), (0,1,0), (-1,0,0), (3,0,0), (4,0,0), (3,1,0)],
                           faces=[(0,1,2), (3,4,5), (6,7,8)])
    before = repr(part)
    assert mesh_islands(part) == ((0, 1), (2,))
    assert mesh_islands(part, join_seams=False) == ((0,), (1,), (2,))
    assert repr(part) == before


def test_pac_exclusion_changes_only_target_indices_across_every_lod():
    source = island_pac()
    output = apply_pac_island_exclusions(source, source, {0: (1,)})
    expected = bytearray(source)
    for lod in pac_cloth_lods(source):
        assert mesh_islands(lod.submeshes[0]) == ((0,), (1,))
        struct.pack_into('<3H', expected, lod.submeshes[0].source_index_offset + 6, 3, 3, 3)
    assert output == expected
    assert apply_pac_island_exclusions(source, source, {}) == source


def test_ambiguous_lower_lod_is_rejected():
    source = bytearray(island_pac())
    vertex = pac_cloth_lods(source)[2].submeshes[0].source_vertex_offsets[3]
    struct.pack_into('<H', source, vertex, 23456)
    with pytest.raises(ValueError, match='ambiguous at LOD 2'):
        apply_pac_island_exclusions(bytes(source), bytes(source), {0: (1,)})


def test_host_island_exclusion_undo_restore_and_finish(tmp_path):
    source = island_pac()
    with patch('tests.test_mesh_rust_authoring_exact_output._pac_fixture', return_value=source):
        _, service, session = _open_exact_session(tmp_path / 'session')
    try:
        state = command(session, 'select', {'selection': {'source_indices': [0]}, 'operation': 'replace'})['state']
        row = state['mesh_islands']['parts'][0]
        assert row['available'] and [r['faces'] for r in row['islands']] == [[0], [1]]
        args = {'part_id': row['part_id'], 'faces': [1], 'included': False,
                '_archive_entry': ArchiveEntry('owned-rust-exact.pac', tmp_path / '0.pamt', tmp_path / '0.paz', 0, 0, 0, 0, 0),
                '_archive_dependencies': SimpleNamespace(entries_by_basename={}, entries_by_normalized_path={})}
        before = session.shadow_service.session_view(session.shadow_session_id)
        for invalid in ({'faces': [99]}, {'faces': [0, 1]}, {'included': 'false'}, {'faces': [True]}):
            with pytest.raises(ValueError):
                command(session, 'replacement_islands', {**args, **invalid})
            after = session.shadow_service.session_view(session.shadow_session_id)
            assert (after.revision, after.undo_count) == (before.revision, before.undo_count)
        result = command(session, 'replacement_islands', args)
        assert not result['state']['mesh_islands']['parts'][0]['islands'][1]['included']
        snapshot = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        assert snapshot.mesh.submeshes[0].faces == [(0,1,2), (3,4,5)]
        expected = apply_pac_island_exclusions(source, source, {0: (1,)})
        assert session.shadow_service._replacement_output_for_snapshot(snapshot).data == expected
        command(session, 'replacement_islands', {**args, 'included': True})
        restored = session.shadow_service.capture_export_snapshot(session.shadow_session_id)
        assert session.shadow_service._replacement_output_for_snapshot(restored).data == source
        command(session, 'undo')
        command(session, 'undo')
        assert session.shadow_service.capture_export_snapshot(session.shadow_session_id).replacement_state is None
        command(session, 'redo')
        session.finish(_request(session, 'finish_request', 20))
        final = service.capture_export_snapshot(session.authoritative_session_id)
        assert service.rebuild_result_from_snapshot(final)[0].data == expected
        from cdmw.services.mesh_service import MeshService
        from cdmw.modding.mesh_parser import parse_pac
        draft = tmp_path / 'draft' / 'mesh_layers.json'
        service._session(session.authoritative_session_id).mesh_layer_project_path = draft
        service.retry_mesh_layer_autosave(session.authoritative_session_id)
        seed = parse_pac(source, 'owned-rust-exact.pac')
        seed._cdmw_original_data = source
        seed._cdmw_mesh_layer_project_path = str(draft)
        reopened = MeshService()
        view = reopened.open_edit_session(seed)
        try:
            loaded_snapshot = reopened.capture_export_snapshot(view.session_id)
            assert loaded_snapshot.replacement_state == final.replacement_state
            assert reopened.rebuild_result_from_snapshot(loaded_snapshot)[0].data == expected
        finally:
            reopened.close_edit_session(view.session_id)
        from cdmw.services.mesh_replacement_draft import save_replacement_state, load_replacement_state
        generation = tmp_path / 'generation'
        generation.mkdir()
        saved = save_replacement_state(final.replacement_state, tmp_path, generation)
        assert saved['version'] == 13
        loaded = load_replacement_state(saved, tmp_path)
        assert loaded == final.replacement_state
        for invalid in ([True], [-1], [1, 1], [2, 1]):
            saved['parts'][0]['excluded_island_faces'] = invalid
            with pytest.raises(ValueError, match='island'):
                load_replacement_state(saved, tmp_path)
    finally:
        if not session.closed:
            session.cancel()
        service.close_edit_session(session.authoritative_session_id)
