"""Profile commands through the isolated editor, Finish, drafts and mod output."""

from contextlib import ExitStack
from dataclasses import replace
import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.services.mesh_physics_profiles import resolve_mesh_physics_profiles
from cdmw.services.mesh_replacement_import import archive_location
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from cdmw.services.mesh_rust_authoring import RustMeshAuthoringSession, RustMeshProtocolError, prime_rust_mesh_preview_context
from cdmw.ui.mesh_editor.replacement_flow import prepare_replacement_event
from tests.test_mesh_editor_replacement import editor
from tests.test_mesh_editor_replacement_sequences import open_editor
from tests.test_mesh_physics_profile_output import inputs
from tests.test_mesh_physics_profiles import _prepared
from tests.test_mesh_rust_authoring_exact_output import _request
from tests.test_mesh_rust_replacement import command


@pytest.fixture
def profile_host(editor, tmp_path):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    _, sidecar, catalogue, profile, rule = inputs(snapshot)
    target = _prepared(tmp_path, snapshot.mesh.path, snapshot.original_data, ordinal=10)
    entries = tuple(_prepared(tmp_path, file.path, file.data, package=f"{index + 11:04}", ordinal=index + 20)
                    for index, file in enumerate((sidecar, catalogue, profile)))
    index = {entry.basename.casefold(): (entry,) for entry in entries}
    context = resolve_mesh_physics_profiles(target, index)
    assert not context.problem and context.profiles
    controller = SimpleNamespace(mesh_service=service, active_session_id=sid)
    prime_rust_mesh_preview_context(controller, None, target_entry=target, physics_profile_context=context)
    host = RustMeshAuthoringSession.create(controller, tmp_path / 'session', process_generation=7)
    dependencies = SimpleNamespace(entries_by_basename=index,
                                   entries_by_normalized_path={entry.identity.normalized_path: (entry,) for entry in entries})
    yield SimpleNamespace(host=host, service=service, sid=sid, target=target, context=context,
                          entries=entries, dependencies=dependencies, rule=rule)
    if not host.closed:
        host.cancel()


def profile_state(host):
    return host.state_payload(include_document=False)['physics_profiles']


def arguments(case, variant='0', *, reset=False):
    group = next(group for group in profile_state(case.host)['groups'] if group['variant'] == variant)
    args = {'group_id': group['id'], '_archive_entry': case.target, '_archive_dependencies': case.dependencies}
    args.update({'reset': True} if reset else {'rule': replace(case.rule, variant=variant).to_dict()})
    return args


def output(host):
    return prepare_replacement_output(host.shadow_service.capture_export_snapshot(host.shadow_session_id))


@pytest.mark.parametrize('collision_values', [(), (
    ('IsCloak', 1), ('UseBackStopCollision', 0), ('UseInputPositionCollision', 1),
    ('ShrinkWhenShieldIsInSocket', 1), ('UseLraConstraint', 0),
), (('RestoreAngleStiffness', .025),), (('SkipSelfMeshCollidable', 0),)],
                         ids=['mechanics', 'collision-and-attachments', 'spline-spring-back', 'weapon-self-collision'])
def test_apply_restore_history_finish_draft_reopen_without_archive_and_build_mod(profile_host, tmp_path, collision_values):
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    case, host = profile_host, profile_host.host
    case.rule = replace(case.rule, values=tuple(sorted(case.rule.values + collision_values)))
    before = case.service.capture_export_snapshot(case.sid)
    args = arguments(case)
    command(host, 'replacement_physics_profile', args)
    current = output(host)
    assert current.data == before.original_data
    state = host.shadow_service._session(host.shadow_session_id).replacement_state
    assert all(part.physics_profiles == (case.rule,) for part in state.parts)
    assert state.target_location == archive_location(case.target)
    for entry in case.entries:
        file = next(file for file in state.dependencies if file.path == entry.path)
        assert file.data == entry.prepared_path.read_bytes()
        assert file.archive_location == archive_location(entry)
    assert case.service.session_view(case.sid).revision == before.mesh_revision
    assert case.service._session(case.sid).replacement_state is None
    edited = profile_state(host)
    assert all(part['bindings'][0]['profile'].startswith('CDMW_') for part in edited['parts'])
    assert all(part['bindings'][1]['profile'] == '' for part in edited['parts'])
    assert next(row for row in edited['profiles'] if row.get('edited'))['authored']['damping'] == '1.25'
    edited_values = next(row for row in edited['profiles'] if row.get('edited'))['authored']
    assert all(edited_values[key.casefold()] == str(value) for key, value in collision_values)

    command(host, 'undo')
    assert host.shadow_service._session(host.shadow_session_id).replacement_state is None
    command(host, 'redo')
    assert output(host).companion_files == current.companion_files
    command(host, 'replacement_physics_profile', arguments(case, reset=True))
    assert not output(host).companion_files and output(host).data == before.original_data
    assert all(part['bindings'][0]['profile'] == 'Lower' for part in profile_state(host)['parts'])
    command(host, 'undo')
    assert output(host).companion_files == current.companion_files

    # A second variant is independent, including an explicit empty assignment.
    command(host, 'replacement_physics_profile', arguments(case, '1'))
    two_variants = output(host)
    assert len(two_variants.companion_files) == 4
    command(host, 'replacement_physics_profile', arguments(case, reset=True))
    assert all(part['bindings'][0]['profile'] == 'Lower' and part['bindings'][1]['profile'].startswith('CDMW_')
               for part in profile_state(host)['parts'])
    command(host, 'undo')
    host.finish(_request(host, 'finish_request', 22))
    final = case.service.capture_export_snapshot(case.sid)
    assert case.service.rebuild_result_from_snapshot(final)[0].data == before.original_data
    assert all(len(part.physics_profiles) == 2 for part in final.replacement_state.parts)
    draft = tmp_path / 'draft' / 'mesh_layers.json'
    case.service._session(case.sid).mesh_layer_project_path = draft
    case.service.retry_mesh_layer_autosave(case.sid)
    descriptor = json.loads(draft.read_text())
    assert descriptor['format'] == 'mesh_layer_project_v2'
    generation = json.loads((draft.parent / descriptor['current_generation'] / 'generation.json').read_text())
    assert generation['replacement']['version'] == 7

    with ExitStack() as stack:
        reopened, sid = open_editor(stack, before.original_data, final.mesh.path, draft)
        recovered = RustMeshAuthoringSession.create(SimpleNamespace(mesh_service=reopened, active_session_id=sid),
                                                   tmp_path / 'recovered', process_generation=8)
        stack.callback(recovered.cancel)
        assert recovered.physics_profile_context is None
        assert output(recovered).companion_files == two_variants.companion_files
        tab = SimpleNamespace(standalone_rust_authoring_session=recovered, standalone_rust_closing=False)
        group = next(row for row in profile_state(recovered)['groups'] if row['variant'] == '0')
        # No current target, archive index, or source files are needed after recovery.
        for entry in case.entries:
            entry.prepared_path.unlink()
        event = prepare_replacement_event(tab, recovered, {
            **_request(recovered, 'command_request', 23), 'command': 'replacement_physics_profile',
            'arguments': {'group_id': group['id'], 'reset': True},
        })
        with patch('cdmw.services.mesh_physics_profiles.read_archive_entry_data', side_effect=AssertionError('live read')):
            recovered.run_command(event)
            command(recovered, 'replacement_physics_profile', {'group_id': group['id'], 'rule': case.rule.to_dict()})
            assert output(recovered).companion_files == two_variants.companion_files
        recovered.finish(_request(recovered, 'finish_request', 24))
        errors, completed = [], []
        worker = MeshDirectOutputWorker(1, reopened, sid, case.target, kind='loose_mod', output_path=tmp_path / 'mod')
        worker.error.connect(lambda _id, message: errors.append(message))
        worker.completed.connect(lambda _id, result: completed.append(result))
        worker.run()
        assert not errors and completed
        assert (tmp_path / 'mod' / case.target.path).read_bytes() == before.original_data
        for file in two_variants.companion_files:
            assert (tmp_path / 'mod' / file.path).read_bytes() == file.data
        assert len(list((tmp_path / 'mod' / 'character/descriptors/pbd/material/cdmw').glob('*.xml'))) == 2


@pytest.mark.parametrize('fault', ['group', 'hash', 'symbol', 'variant', 'target', 'source_location', 'source_bytes', 'nonfinite', 'duplicate_dependency'])
def test_rejected_profile_commands_leave_shadow_authoritative_and_history_unchanged(profile_host, fault):
    case, host = profile_host, profile_host.host
    args = arguments(case)
    if fault == 'group':
        args['group_id'] += '-stale'
    elif fault in {'hash', 'symbol', 'variant'}:
        args['rule'][{'hash': 'source_sha256', 'symbol': 'source_profile', 'variant': 'variant'}[fault]] = {
            'hash': '0' * 64, 'symbol': 'Missing', 'variant': '1'}[fault]
    elif fault == 'target':
        args['_archive_entry'] = replace(case.target, offset=case.target.offset + 1)
    elif fault in {'source_location', 'source_bytes'}:
        document = case.context.profiles[0]
        document = (replace(document, archive_location=case.context.sidecar.archive_location)
                    if fault == 'source_location' else replace(document, data=document.data + b' '))
        host.physics_profile_context = replace(case.context, profiles=(document,))
    elif fault == 'nonfinite':
        args['rule']['values']['Damping'] = float('nan')
    before = host.shadow_service.session_view(host.shadow_session_id)
    if fault == 'duplicate_dependency':
        from cdmw.domain.mesh.replacement import ReplacementFile
        document = case.context.sidecar
        dependency = ReplacementFile(document.path, document.data, document.archive_location)
        with patch('cdmw.services.mesh_replacement_materials.capture_replacement_dependencies',
                   return_value=(dependency, replace(dependency, data=b'<Changed/>'))):
            with pytest.raises(ValueError):
                command(host, 'replacement_physics_profile', args)
    else:
        with pytest.raises(ValueError):
            command(host, 'replacement_physics_profile', args)
    after = host.shadow_service.session_view(host.shadow_session_id)
    assert (after.revision, after.undo_count, after.redo_count) == (before.revision, before.undo_count, before.redo_count)
    assert host.shadow_service._session(host.shadow_session_id).replacement_state is None
    assert case.service._session(case.sid).replacement_state is None


def test_identical_apply_is_inert_and_stale_revision_is_rejected(profile_host):
    case, host = profile_host, profile_host.host
    stale = {**_request(host, 'command_request', 9), 'command': 'replacement_physics_profile', 'arguments': arguments(case)}
    command(host, 'replacement_physics_profile', arguments(case))
    before = host.shadow_service.session_view(host.shadow_session_id)
    command(host, 'replacement_physics_profile', arguments(case))
    after = host.shadow_service.session_view(host.shadow_session_id)
    assert after.revision == before.revision and after.undo_count == before.undo_count
    with pytest.raises(RustMeshProtocolError, match='revision'):
        host.run_command(stale)
    assert output(host).data == case.target.prepared_path.read_bytes()


def test_pac_names_match_sidecar_case_without_renaming_or_ambiguous_aliases(profile_host):
    from cdmw.services.mesh_physics_profiles import _xml_text
    from cdmw.services.mesh_rust_physics_profiles import _assignment_groups
    import hashlib

    case, host = profile_host, profile_host.host
    sidecar = case.context.sidecar
    names = tuple(part['source_name'] for part in profile_state(host)['parts'])
    text = _xml_text(sidecar.data)
    for name in names:
        text = text.replace(f'_subMeshName="{name}"', f'_subMeshName="{name.swapcase()}"')
    data = text.encode('utf-16')
    sidecar = replace(sidecar, data=data, sha256=hashlib.sha256(data).hexdigest())
    host.physics_profile_context = replace(case.context, sidecar=sidecar, bindings=tuple(
        replace(binding, submesh_name=binding.submesh_name.swapcase()) for binding in case.context.bindings))
    ui = profile_state(host)
    assert all(group['available'] and len(group['part_ids']) == len(names) for group in ui['groups'])
    assert all(part['bindings'] for part in ui['parts'])
    args = arguments(case)
    # Capture the same mixed-case source used by this independent host context.
    with patch('cdmw.services.mesh_replacement_materials.capture_replacement_dependencies', return_value=()):
        command(host, 'replacement_physics_profile', args)
    result = output(host)
    assert result.data == case.target.prepared_path.read_bytes()
    changed = next(file.data for file in result.companion_files if file.path == sidecar.path)
    assert all(f'_subMeshName="{name.swapcase()}"' in _xml_text(changed) for name in names)
    ambiguous = _assignment_groups(host.physics_profile_context, names + (names[0].swapcase(),))
    assert all(group['reason'] for group in ambiguous)


def test_profile_commands_use_real_qt_preparation_and_worker(profile_host, monkeypatch):
    import time
    from PySide6.QtWidgets import QApplication
    from tests.test_mesh_rejection_logging import _Editor

    case, host = profile_host, profile_host.host
    app = QApplication.instance() or QApplication([])
    ui = _Editor()
    ui._initialize_rust_editor_runtime_state()
    ui.standalone_rust_authoring_session = host
    ui._current_target_entry = lambda: case.target
    ui.window = lambda: ui
    monkeypatch.setattr('cdmw.ui.mesh_editor.replacement_flow.archive_workflow_dependency_context',
                        lambda owner, target: case.dependencies)
    try:
        for reset in (False, True):
            args = arguments(case, reset=reset)
            del args['_archive_entry'], args['_archive_dependencies']
            ui.standalone_rust_protocol_queue.append({**_request(host, 'command_request', 10 + reset),
                                                     'command': 'replacement_physics_profile', 'arguments': args})
            ui._start_next_rust_protocol_worker()
            deadline = time.monotonic() + 15
            while ui.standalone_rust_protocol_thread is not None and time.monotonic() < deadline:
                app.processEvents()
                time.sleep(.001)
            assert ui.standalone_rust_protocol_thread is None, 'profile worker did not shut down'
            response = ui.responses[-1]
            assert isinstance(response, dict) and response['ok'], response
            assert bool(output(host).companion_files) is not reset
        assert case.service._session(case.sid).replacement_state is None
    finally:
        if ui.standalone_rust_protocol_thread is not None:
            host.request_cancel()
            ui.standalone_rust_protocol_thread.quit()
            assert ui.standalone_rust_protocol_thread.wait(5000)
        ui.standalone_status_label.deleteLater()
        ui.deleteLater()
        app.processEvents()
