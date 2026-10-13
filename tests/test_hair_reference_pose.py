"""Hair's face, skull, neck and eyes must share one authored character pose."""

import copy
from dataclasses import replace
from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_rust_hair import prepare_hair_setup, _reference_with_pose, _shared_reference_pose
from tests.test_mesh_hair_authoring import editor


IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def translated(x=0., y=0., z=0.):
    return (*IDENTITY[:12], x, y, z, 1.)


def skeleton():
    bones = [Bone(index=i, name=name, parent_index=parent, bind_matrix=IDENTITY, inv_bind_matrix=IDENTITY)
             for i, (name, parent) in enumerate((('Neck', -1), ('Bip01 Head', 0), ('Chin', 1), ('Temple', 1), ('Eye', 1)))]
    bones[1] = replace(bones[1], bind_matrix=translated(y=1.5), inv_bind_matrix=translated(y=-1.5))
    return Skeleton(bones=bones, bone_count=len(bones))


def appearances():
    # Temple is explicitly reset to bind by the head PABC. An identity-matrix
    # heuristic would leave the body's conflicting temple adjustment active.
    head = NeutralMeshAppearance('head.pabc', (2, 0, 1, 3, 4),
        (IDENTITY, IDENTITY, translated(y=.025), IDENTITY, translated(z=.01)), (2, 3, 4))
    body = NeutralMeshAppearance('body.pabc', (3, 2, 1, 0, 4),
        (translated(y=-.02), translated(y=.01), translated(x=.015), translated(x=-.02), IDENTITY), (0, 1, 2, 3))
    return head, body


@pytest.mark.parametrize('scale', [.92, 1.02])
@pytest.mark.parametrize('fitted_caps', [False, True])
def test_setup_aligns_shared_edges_with_authored_pose_and_independent_palettes(editor, scale, fitted_caps):
    _, authoring = editor
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    rig = skeleton()
    head_pose, body_pose = appearances()
    face = SubMesh(name='face', vertices=[(-.1, 1.6, 0.), (.1, 1.6, 0.), (0., 1.8, 0.)], faces=[(0, 1, 2)],
                   bone_indices=[(0,), (0, 1), (3,)], bone_weights=[(1.,), (.6, .4), (1.,)])
    eye = SubMesh(name='eyecover', vertices=[(-.02, 1.7, -.01), (.02, 1.7, -.01), (0., 1.72, -.01)],
                  faces=[(0, 1, 2)], bone_indices=[(4,)] * 3, bone_weights=[(1.,)] * 3)
    head = ParsedMesh(format='pac', submeshes=[face, eye] if fitted_caps else [face])
    shoulders = [(-.2, 1.52, 0.), (.2, 1.52, 0.), (0., 1.5, .1)]
    body = ParsedMesh(format='pac', submeshes=[SubMesh(name='skull and neck',
        vertices=face.vertices + [(0., 1.9, .1)] + shoulders,
        faces=[(1, 0, 3), (2, 1, 3), (0, 2, 3), (4, 5, 6)],
        bone_indices=[(1,), (1, 3), (0,), (2,), (3,), (3,), (3,)],
        bone_weights=[(1.,), (.6, .4), (1.,), (1.,), (1.,), (1.,), (1.,)])])
    data = service._session(sid).original_data
    args = dict(character='Damiane', _head_scale=scale,
        _archive_snapshot=SimpleNamespace(mesh=head, original_data=data),
        _archive_entry=SimpleNamespace(path='character/model/1_pc/2_phw/head/head/test.pac'),
        _archive_skeleton=rig, _archive_neutral_appearance=head_pose,
        _body_snapshot=SimpleNamespace(mesh=body, original_data=data),
        _body_archive_entry=SimpleNamespace(path='character/model/1_pc/2_phw/nude/cd_phw_00_nude_test.pac'),
        _body_skeleton=rig, _body_neutral_appearance=body_pose)
    if not fitted_caps:
        # Separate eye PAC has a different palette again.
        eye = replace(eye, bone_indices=[(0,)] * 3)
        args['_prepared_head_details'] = [dict(_archive_snapshot=SimpleNamespace(
            mesh=ParsedMesh(format='pac', submeshes=[eye]), original_data=data),
            _archive_neutral_appearance=replace(head_pose, bone_palette=(4, 1, 0, 2, 3)), _scale=scale)]
    before = copy.deepcopy((head, body, service.working_mesh(sid)))
    prepare_hair_setup(service, sid, args, None)
    state = service._session(sid).hair_state.payload
    scalp = state['scalp']
    # The common edge welds: four source vertices and four source triangles,
    # with no wide strip of artificial face-to-skull bridge triangles.
    assert len(scalp['positions']) == 4
    assert len(scalp['triangles']) == 4
    expected = [(-.1 * scale, 1.51 + (1.625 - 1.51) * scale, 0.),
                (.1 * (1. + (scale - 1.) * .6), 1.51 + (1.607 - 1.51) * (1. + (scale - 1.) * .6), 0.),
                (0., 1.51 + (1.8 - 1.51) * scale, 0.)]
    for point in expected:
        assert any(actual == pytest.approx(point) for actual in scalp['positions'])
    bust = next(r for r in state['references'] if not r['identity'].startswith(('head:', 'collision:')))
    assert bust['positions'] == [list((x, y - .02, z)) for x, y, z in shoulders]
    eyes = next(r for r in state['references'] if r['identity'].startswith('head:'))
    for actual, (x, y, z) in zip(eyes['positions'], eye.vertices):
        assert actual == pytest.approx((x * scale, 1.51 + (y - 1.51) * scale, (z + .01) * scale))
    assert (head, body, service.working_mesh(sid)) == before


@pytest.mark.parametrize('missing', ['head', 'body'])
def test_shared_pose_uses_the_available_authored_context(missing):
    head, body = appearances()
    args = dict(_body_snapshot=object(), _archive_skeleton=skeleton(), _body_skeleton=skeleton(),
                _archive_neutral_appearance=head, _body_neutral_appearance=body)
    args['_archive_neutral_appearance' if missing == 'head' else '_body_neutral_appearance'] = None
    assert _shared_reference_pose(args).skin_matrices == (body if missing == 'head' else head).skin_matrices


def test_reference_without_own_pabc_resolves_its_own_palette(monkeypatch):
    from cdmw.modding import mesh_parser
    head, _ = appearances()
    rig = skeleton()
    calls = []
    monkeypatch.setattr(mesh_parser, 'resolve_pac_bone_palette',
                        lambda data, skeleton: calls.append((data, skeleton)) or (4, 0, 1, 2, 3))
    context = _reference_with_pose(None, SimpleNamespace(original_data=b'eye PAC'), rig, head)
    assert calls == [(b'eye PAC', rig)]
    mesh = ParsedMesh(format='pac', submeshes=[SubMesh(
        vertices=[(0., 1.7, 0.)], bone_indices=[(0,)], bone_weights=[(1.,)])])
    assert context.to_neutral(mesh).submeshes[0].vertices[0] == pytest.approx((0., 1.7, .01))


def test_shared_pose_refuses_different_bind_skeletons():
    head, body = appearances()
    wrong = skeleton()
    wrong.bones[2] = replace(wrong.bones[2], bind_matrix=translated(x=.1))
    with pytest.raises(ValueError, match='same skeleton'):
        _shared_reference_pose(dict(_body_snapshot=object(), _archive_skeleton=skeleton(), _body_skeleton=wrong,
                                   _archive_neutral_appearance=head, _body_neutral_appearance=body))
