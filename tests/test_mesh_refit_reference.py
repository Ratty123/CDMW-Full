"""Reference-body retarget for Fit to body: bind-to-bind skinning on the body's own weights."""
from dataclasses import replace
import math

import numpy as np
import pytest

from cdmw.modding.mesh_neutral_appearance import NeutralMeshAppearance
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.mesh_refit_reference import (
    retarget_reference_body,
    retarget_transforms,
    skin_retarget,
)
from cdmw.modding.skeleton_parser import Bone, Skeleton


def _matrix(translation=(0., 0., 0.), turn=0.):
    """Row-major, row-vector bind: rotation about +z by `turn` radians, then translation."""
    c, s = math.cos(turn), math.sin(turn)
    return (c, s, 0., 0., -s, c, 0., 0., 0., 0., 1., 0., *translation, 1.)


def _skeleton(*bones):
    return Skeleton(path="test.pab", bones=[
        Bone(index=index, name=name, parent_index=parent, bind_matrix=matrix)
        for index, (name, parent, matrix) in enumerate(bones)
    ])


SOURCE = _skeleton(("root", -1, _matrix()), ("arm", 0, _matrix((0., 1., 0.))),
                   ("twist", 1, _matrix((0., 1.5, 0.))), ("prop", -1, _matrix((5., 0., 0.))))
TARGET = _skeleton(("root", -1, _matrix()), ("arm", 0, _matrix((0., 1.2, 0.), math.pi / 2)))


def _part(vertices, indices, weights, faces=((0, 1, 2),)):
    return SubMesh(name="body", material="skin", texture="", vertices=list(vertices), faces=list(faces),
                   bone_indices=list(indices), bone_weights=list(weights))


def test_vertex_follows_its_bone_from_source_bind_into_target_bind():
    transforms, target_palette, substituted = retarget_transforms((0, 1), SOURCE, TARGET)
    assert substituted == () and target_palette.tolist() == [0, 1]
    moved = skin_retarget([(0., 1.5, 0.), (2., 0., 0.)], [(1,), (0,)], [(1.,), (1.,)], transforms)
    # 0.5 along the arm in its source frame, then turned a quarter about +z at the target joint.
    assert moved[0] == pytest.approx((-.5, 1.2, 0.))
    assert moved[1] == pytest.approx((2., 0., 0.))


def test_missing_bones_use_the_nearest_shared_ancestor_or_stay_put():
    transforms, target_palette, substituted = retarget_transforms((2, 3), SOURCE, TARGET)
    assert substituted == ("twist->arm", "prop->identity")
    assert target_palette.tolist() == [1, -1]
    arm, _, _ = retarget_transforms((1,), SOURCE, TARGET)
    assert transforms[0] == pytest.approx(arm[0])
    assert transforms[1] == pytest.approx(np.eye(4))


def test_blended_rows_are_padded_and_invalid_influences_renormalised():
    transforms, _, _ = retarget_transforms((0, 1), SOURCE, TARGET)
    points = [(0., 1.5, 0.), (0., 1.5, 0.), (0., 1.5, 0.), (3., 3., 3.)]
    moved = skin_retarget(points, [(0, 1), (1, 9), (1,), ()], [(.5, .5), (.25, .75), (0.,), ()], transforms)
    root, arm = np.array([0., 1.5, 0.]), np.array([-.5, 1.2, 0.])
    assert moved[0] == pytest.approx(.5 * root + .5 * arm)
    # Slot 9 is outside the palette: the remaining influence carries the whole vertex.
    assert moved[1] == pytest.approx(arm)
    # No weight at all, or no influences: the authored position is kept.
    assert moved[2] == pytest.approx(points[2])
    assert moved[3] == pytest.approx(points[3])


def test_body_parts_are_concatenated_and_payload_is_flat():
    first = _part([(0., 1.5, 0.), (0., 2., 0.), (1., 2., 0.)], [(1,)] * 3, [(1.,)] * 3)
    second = _part([(0., 0., 0.), (1., 0., 0.), (0., 0., 1.), (1., 0., 1.)], [(0,)] * 4, [(1.,)] * 4,
                   faces=((0, 1, 2), (1, 3, 2)))
    empty = _part([], [], [], faces=())
    reference = retarget_reference_body([first, empty, second], (0, 1), SOURCE, TARGET, label="nude.pac")
    assert reference.source_positions.shape == (7, 3) and reference.faces.tolist() == [[0, 1, 2], [3, 4, 5], [4, 6, 5]]
    assert reference.fitted_positions[0] == pytest.approx((-.5, 1.2, 0.))
    assert reference.fitted_positions[3:] == pytest.approx(reference.source_positions[3:])
    payload = reference.payload()
    assert payload["label"] == "nude.pac"
    assert len(payload["source_positions"]) == len(payload["fitted_positions"]) == 21
    assert payload["faces"] == [0, 1, 2, 3, 4, 5, 4, 6, 5]
    with pytest.raises(ValueError):
        retarget_reference_body([empty], (0, 1), SOURCE, TARGET)


def test_appearance_poses_the_reference_like_the_session_poses_its_parts():
    vertices = [(0., 1.5, 0.), (.2, 1.1, 0.), (0., .5, .3)]
    indices, weights = [(0, 1), (1,), (0,)], [(.3, .7), (1.,), (1.,)]
    body = _part(vertices, indices, weights)
    source_look = (_matrix((0., .1, 0.), .2), _matrix((.05, 0., 0.), -.3), _matrix(), _matrix())
    target_look = (_matrix((.02, 0., 0.)), _matrix((0., -.04, .01), .1))
    reference = retarget_reference_body([body], (0, 1), SOURCE, TARGET,
                                        source_appearance=source_look, target_appearance=target_look)
    mesh = ParsedMesh(path="body.pac", format="pac", submeshes=[body])
    expected = NeutralMeshAppearance("source", (0, 1), source_look).to_neutral(mesh).submeshes[0].vertices
    assert reference.source_positions == pytest.approx(np.asarray(expected), abs=1e-12)
    # The retargeted body then takes the driver's appearance through the bones it now follows.
    plain = retarget_reference_body([body], (0, 1), SOURCE, TARGET)
    moved = replace(body, vertices=[tuple(p) for p in plain.fitted_positions])
    expected = NeutralMeshAppearance("target", (0, 1), target_look).to_neutral(
        ParsedMesh(path="moved.pac", format="pac", submeshes=[moved])).submeshes[0].vertices
    assert reference.fitted_positions == pytest.approx(np.asarray(expected), abs=1e-12)
