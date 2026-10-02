from dataclasses import replace
import hashlib

import pytest

from cdmw.core.pbd_cloth import _parse_xml
from cdmw.domain.mesh.physics_profile import PacPhysicsProfileRule, validate_profile_values
from cdmw.domain.mesh.replacement import ReplacementFile
from cdmw.modding.pbd_profile_edit import ProfileXml, edit_profile_values
from cdmw.services.mesh_physics_profiles import _xml_text
from cdmw.services.mesh_replacement_draft import save_replacement_state, load_replacement_state
from cdmw.services.mesh_replacement_import import initial_replacement_state, mesh_with_part_ids, commit_replacement
from cdmw.services.mesh_replacement_output import prepare_replacement_output
from tests.test_mesh_editor_replacement import editor


PROFILE = ('<?xml version="1.0" encoding="utf-16"?>\r\n<SimulationParameters unknown="keep">'
           '<!-- <Damping>9</Damping> untouched -->\r\n<SimulationMode>cloth</SimulationMode>'
           '<Damping> 0.8 </Damping><Gravity>-10</Gravity><Unknown value="keep &amp; preserve"/>'
           '<AttachedCloth><Damping>2</Damping></AttachedCloth></SimulationParameters>')

COLLISION_FIELDS = ('IsCloak', 'UseBackStopCollision', 'UseInputPositionCollision',
                    'ShrinkWhenShieldIsInSocket', 'UseLraConstraint', 'SkipSelfMeshCollidable')


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-be'])
def test_collision_profile_overrides_preserve_attached_settings_and_unrelated_xml(encoding):
    parents = ''.join(f'<{key}>0</{key}>' for key in COLLISION_FIELDS)
    children = ''.join(f'<{key}>1</{key}>' for key in COLLISION_FIELDS)
    source = f'<SimulationParameters keep="yes">{parents}<!-- unchanged --><AttachedCloth>{children}</AttachedCloth></SimulationParameters>'
    data = source.encode(encoding)
    changed = edit_profile_values(data, tuple((key, 1) for key in COLLISION_FIELDS))
    assert changed == source.replace(parents, children, 1).encode(encoding)
    assert data == source.encode(encoding)


@pytest.mark.parametrize('key', COLLISION_FIELDS)
@pytest.mark.parametrize('value', [-1, .5, 2, True, float('nan')])
def test_collision_profile_overrides_require_binary_numbers(key, value):
    with pytest.raises(ValueError, match='Invalid physics profile settings'):
        validate_profile_values(((key, value),))


def inputs(snapshot):
    path = 'character/descriptors/pbd/material/armor/lower.xml'
    profile = ReplacementFile(path, PROFILE.encode('utf-16'))
    catalogue = ReplacementFile('character/descriptors/pbd/pbdconfig.xml', (
        '<?xml version="1.0"?><Config>\r\n<!-- <Material Name="Lower" Filename="wrong.xml"/> -->'
        '<Material Name="Lower" PbdPart="Skirt" Mode="cloth" Filename="Material/Armor/Lower.xml" unknown="keep"/>'
        '\r\n</Config>').encode('utf-8-sig'))
    wrappers = ''.join(f'<SkinnedMeshMaterialWrapper _subMeshName="{part.name}"><Material texture="original.dds"/></SkinnedMeshMaterialWrapper>'
                       for part in snapshot.mesh.submeshes)
    sidecar = ReplacementFile(snapshot.mesh.path.replace('/model/', '/modelproperty/') + '_xml', (
        '<?xml version="1.0" encoding="utf-16"?>\r\n<Common keep="yes"/><ModelPropertyList>'
        '<!-- _pbdSimulationMaterialName="Lower" -->'
        f'<ModelProperty Index="0"><SkinnedMeshProperty _pbdSimulationMaterialName="Lower"><Vector>{wrappers}</Vector>'
        '</SkinnedMeshProperty></ModelProperty>'
        f'<ModelProperty Index="1"><SkinnedMeshProperty _pbdSimulationMaterialName=""><Vector>{wrappers}</Vector>'
        '</SkinnedMeshProperty></ModelProperty></ModelPropertyList>').encode('utf-16'))
    rule = PacPhysicsProfileRule('0', 'Lower', path, hashlib.sha256(profile.data).hexdigest(),
                                (('Damping', 1.25), ('UseRotationCorrection', 0)))
    state = initial_replacement_state(snapshot, dependencies=(sidecar, catalogue, profile))
    state = replace(state, parts=tuple(replace(part, physics_profiles=(rule,)) for part in state.parts))
    return state, sidecar, catalogue, profile, rule


@pytest.mark.parametrize('encoding', ['utf-8', 'utf-8-sig', 'utf-16', 'utf-16-be'])
def test_profile_scalar_changes_preserve_unknown_bytes_comments_and_attached_owner(encoding):
    declaration = 'utf-16' if '16' in encoding else 'utf-8'
    source = PROFILE.replace('encoding="utf-16"', f'encoding="{declaration}"')
    data = source.encode(encoding)
    changed = edit_profile_values(data, (('Damping', 1.25),))
    assert changed == source.replace('<Damping> 0.8 </Damping>', '<Damping> 1.25 </Damping>').encode(encoding)
    inserted = edit_profile_values(data, (('UseRotationCorrection', 0),))
    assert inserted == source.replace('</SimulationParameters>', '\n\t<UseRotationCorrection>0</UseRotationCorrection></SimulationParameters>').encode(encoding)


def test_spline_spring_back_override_preserves_mode_comments_and_unknown_values():
    source = b'<SimulationParameters><SimulationMode>spline</SimulationMode><!-- keep --><RestoreAngleStiffness>0.025</RestoreAngleStiffness><FutureFlag>7</FutureFlag></SimulationParameters>'
    edited = edit_profile_values(source, (('RestoreAngleStiffness', .4),))
    assert edited == source.replace(b'>0.025<', b'>0.4<')
    for value in (-.1, 1.1, float('nan'), True):
        with pytest.raises(ValueError):
            validate_profile_values((('RestoreAngleStiffness', value),))


def test_rotation_override_follows_mode_reset_without_rewriting_existing_order():
    data = b'<SimulationParameters><UseRotationCorrection>1</UseRotationCorrection><SimulationMode>cloth</SimulationMode></SimulationParameters>'
    edited = edit_profile_values(data, (('UseRotationCorrection', 0),))
    assert edited == data.replace(b'</SimulationParameters>', b'\n\t<UseRotationCorrection>0</UseRotationCorrection></SimulationParameters>')


@pytest.mark.parametrize('data', [
    b'<!DOCTYPE X [<!ENTITY n "1">]><SimulationParameters><Damping>&n;</Damping></SimulationParameters>',
    b'<SimulationParameters><Damping><!-- preserve -->.8</Damping></SimulationParameters>',
    b'<SimulationParameters><Damping><Value>.8</Value></Damping></SimulationParameters>',
    b'<SimulationParameters><Setting Name="Damping" Value=".8"/></SimulationParameters>',
    b'<SimulationParameters><Damping>.8</SimulationParameters>',
])
def test_unestablished_xml_layouts_are_rejected_before_rewriting(data):
    with pytest.raises(ValueError, match='structure'):
        edit_profile_values(data, (('Damping', 1.25),))


def test_profile_export_clones_registration_and_existing_owner_without_changing_pac(editor):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    state, sidecar, catalogue, profile, rule = inputs(snapshot)
    candidate = mesh_with_part_ids(snapshot, state)
    output = prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=state))
    assert output.data == snapshot.original_data
    files = {file.path: file for file in output.companion_files}
    assert len(files) == 3 and profile.path not in files
    new = next(file for path, file in files.items() if '/material/cdmw/' in path)
    expected = PROFILE.replace('<Damping> 0.8 </Damping>', '<Damping> 1.25 </Damping>').replace(
        '</SimulationParameters>', '\n\t<UseRotationCorrection>0</UseRotationCorrection></SimulationParameters>')
    assert new.data == expected.encode('utf-16')
    config = _parse_xml(_xml_text(files[catalogue.path].data))
    entries = list(config.iter('Material'))
    assert len(entries) == 2 and entries[0].get('Name') == 'Lower'
    generated = entries[1]
    assert generated.get('Name').startswith('CDMW_')
    assert generated.get('Mode') == 'cloth' and generated.get('PbdPart') == 'Skirt' and generated.get('unknown') == 'keep'
    assert 'character/descriptors/pbd/' + generated.get('Filename') == new.path
    old_text = _xml_text(sidecar.data)
    expected_sidecar = old_text.replace('<SkinnedMeshProperty _pbdSimulationMaterialName="Lower">',
                                      f'<SkinnedMeshProperty _pbdSimulationMaterialName="{generated.get("Name")}">')
    assert files[sidecar.path].data == expected_sidecar.encode('utf-16')
    assert b'\xef\xbb\xbf' == files[catalogue.path].data[:3]
    assert profile.data == PROFILE.encode('utf-16')


def test_shared_owner_requires_the_complete_group_and_rejects_stale_sources(editor):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    state, sidecar, catalogue, profile, rule = inputs(snapshot)
    candidate = mesh_with_part_ids(snapshot, state)
    partial = replace(state, parts=(state.parts[0], replace(state.parts[1], physics_profiles=())))
    with pytest.raises(ValueError, match='every part'):
        prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=partial))
    changed = replace(state, dependencies=(sidecar, catalogue, replace(profile, data=profile.data + b' ')))
    with pytest.raises(ValueError, match='source is missing or has changed'):
        prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=changed))


def test_assignment_inherited_above_variants_cannot_be_changed_for_just_one_variant():
    document = ProfileXml(b'<Root _pbdSimulationMaterialName="Shared">'
        b'<ModelProperty Index="0"><SkinnedMeshProperty><Part _subMeshName="body"/></SkinnedMeshProperty></ModelProperty>'
        b'<ModelProperty Index="1"><SkinnedMeshProperty><Part _subMeshName="body"/></SkinnedMeshProperty></ModelProperty></Root>')
    with pytest.raises(ValueError, match='ambiguous'):
        document.assignment('0', ['body'])


def test_assignment_rejects_sidecar_names_differing_only_by_case():
    document = ProfileXml(b'<Root _pbdSimulationMaterialName="Shared"><Part _subMeshName="body"/><Part _subMeshName="BODY"/></Root>')
    with pytest.raises(ValueError, match='ambiguous'):
        document.assignment('', ['body'])


def test_profile_export_composes_with_material_changes_and_can_bind_an_empty_variant(editor):
    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    state, sidecar, catalogue, _, rule = inputs(snapshot)
    current = replace(sidecar, data=_xml_text(sidecar.data).replace('original.dds', 'edited.dds').encode('utf-16'))
    existing_entry = '<Material Name="OtherMod" Filename="material/other.xml" custom="preserve"/>'
    composed_catalogue = replace(catalogue, data=_xml_text(catalogue.data).replace(
        '</Config>', existing_entry + '</Config>').encode('utf-8-sig'))
    rule = replace(rule, variant='1')
    state = replace(state, parts=tuple(replace(part, physics_profiles=(rule,)) for part in state.parts),
                    companion_files=(current, composed_catalogue))
    candidate = mesh_with_part_ids(snapshot, state)
    output = prepare_replacement_output(replace(snapshot, mesh=candidate, replacement_state=state))
    text = _xml_text(next(file.data for file in output.companion_files if file.path == sidecar.path))
    assert text.count('edited.dds') == _xml_text(current.data).count('edited.dds')
    assert '<SkinnedMeshProperty _pbdSimulationMaterialName="Lower">' in text
    assert '<SkinnedMeshProperty _pbdSimulationMaterialName="CDMW_' in text
    config = next(file.data for file in output.companion_files if file.path == catalogue.path)
    assert existing_entry in _xml_text(config)
    assert len(list(_parse_xml(_xml_text(config)).iter('Material'))) == 3


def test_profile_edit_undo_redo_draft_reopen_and_loose_mod_keep_exact_sources(editor, tmp_path):
    from cdmw.models import ArchiveEntry
    from cdmw.workers.mesh_editor_workers import MeshDirectOutputWorker

    service, sid = editor
    before = service.capture_export_snapshot(sid)
    state, sidecar, catalogue, profile, rule = inputs(before)
    commit_replacement(service, before, mesh_with_part_ids(before, state), state, label='Edit physics profile')
    snapshot = service.capture_export_snapshot(sid)
    output = prepare_replacement_output(snapshot)
    assert output.data == before.original_data
    service.undo(sid)
    assert service._session(sid).replacement_state is None
    service.redo(sid)
    assert service._session(sid).replacement_state == state
    directory = tmp_path / 'draft' / 'generation'
    directory.mkdir(parents=True)
    payload = save_replacement_state(state, directory.parent, directory)
    assert payload['version'] == 7
    reopened = load_replacement_state(payload, directory.parent)
    assert reopened == state
    assert prepare_replacement_output(replace(snapshot, replacement_state=reopened)).companion_files == output.companion_files
    old = dict(payload, version=6)
    with pytest.raises(ValueError, match='physics profile settings'):
        load_replacement_state(old, directory.parent)
    target = ArchiveEntry(before.mesh.path, tmp_path / '0010/0.pamt', tmp_path / '0010/0.paz',
                          0, len(before.original_data), len(before.original_data), 0, 0)
    worker = MeshDirectOutputWorker(1, service, sid, target, kind='loose_mod', output_path=tmp_path / 'mod')
    errors, completed = [], []
    worker.error.connect(lambda _id, message: errors.append(message))
    worker.completed.connect(lambda _id, result: completed.append(result))
    worker.run()
    assert not errors and completed
    assert (tmp_path / 'mod' / target.path).read_bytes() == before.original_data
    for file in output.companion_files:
        assert (tmp_path / 'mod' / file.path).read_bytes() == file.data
    assert state.dependencies == (sidecar, catalogue, profile)


@pytest.mark.parametrize('value', [float('nan'), float('inf'), 2**2000, True, -1, 10.01])
def test_profile_rule_rejects_invalid_authored_damping_before_any_output(value):
    with pytest.raises(ValueError, match='profile settings'):
        PacPhysicsProfileRule('0', 'Lower', 'character/descriptors/pbd/material/lower.xml', '0'*64,
                              (('Damping', value),))


@pytest.mark.parametrize('fault', ['stripped', 'duplicate', 'missing_source', 'relative_jiggle'])
def test_profile_draft_rejects_lost_rules_ambiguous_variants_and_unverified_sources(editor, tmp_path, fault):
    import copy
    from cdmw.domain.mesh.jiggle import PacJiggleRule

    service, sid = editor
    snapshot = service.capture_export_snapshot(sid)
    state, *_ = inputs(snapshot)
    state = replace(state, parts=tuple(replace(part, jiggle=PacJiggleRule(retained=.5)) for part in state.parts))
    generation = tmp_path / 'generation'
    generation.mkdir()
    payload = save_replacement_state(state, tmp_path, generation)
    assert load_replacement_state(payload, tmp_path) == state
    payload = copy.deepcopy(payload)
    if fault == 'stripped':
        for part in payload['parts']:
            del part['physics_profiles']
    elif fault == 'duplicate':
        payload['parts'][0]['physics_profiles'] *= 2
    elif fault == 'relative_jiggle':
        del payload['parts'][0]['jiggle']['retained']
    else:
        payload['dependencies'] = []
    if fault != 'missing_source':
        with pytest.raises(ValueError):
            load_replacement_state(payload, tmp_path)
    else:
        reopened = load_replacement_state(payload, tmp_path)
        with pytest.raises(ValueError, match='source sidecar and catalogue'):
            prepare_replacement_output(replace(snapshot, mesh=mesh_with_part_ids(snapshot, state), replacement_state=reopened))
