"""Neutral appearance must not turn a bind-frame mismatch into a folded surface."""

import copy
import struct

import pytest

from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.modding.skeleton_variation_parser import (
    PABC_RECORD_OFFSET,
    PABC_RECORD_STRIDE,
    apply_skeleton_variation_to_mesh,
    parse_pabc_skeleton_variation,
)


# A rotated, translated, non-unit bind frame; the fix must work outside world axes.
BIND = (0., .8, 0., 0., -.8, 0., 0., 0., 0., 0., .8, 0., .2, 1.7, .03, 1.)
INVERSE_BIND = (0., -1.25, 0., 0., 1.25, 0., 0., 0., 0., 0., 1.25, 0., -2.125, .25, -.0375, 1.)
IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)


def _pabc_payload(target):
    data = bytearray(PABC_RECORD_OFFSET + PABC_RECORD_STRIDE + 4)
    data[:4] = b"PAR "
    struct.pack_into("<I", data, 0x10, 1)
    # The third block is the raw local SRT and scale data, not another matrix.
    tail = (1., 1., 1., 0., 0., 0., 1., 0., 0., 0.) + (1.,) * 6
    struct.pack_into("<I48f", data, PABC_RECORD_OFFSET, 0x12345678, *(tuple(target) + IDENTITY + tail))
    return bytes(data)


def _variation(skeleton, target):
    return parse_pabc_skeleton_variation(_pabc_payload(target), "owned/neutral.pabc", skeleton=skeleton)


def _fixture(bind=BIND, inverse=INVERSE_BIND):
    skeleton = Skeleton(bones=[
        Bone(index=0, name="JointA", name_hash=0x12345678, bind_matrix=bind, inv_bind_matrix=inverse),
        Bone(index=1, name="JointB", name_hash=0x23456789, bind_matrix=IDENTITY, inv_bind_matrix=IDENTITY),
    ], bone_count=2)
    mesh = ParsedMesh(format="pac", submeshes=[SubMesh(
        vertices=[(.19, 1.71, .04), (.22, 1.69, .06)],
        normals=[(1., 0., 0.), (0., 1., 0.)],
        bone_indices=[(0,), (0, 1)], bone_weights=[(1.,), (.25, .75)], vertex_count=2,
    )], total_vertices=2, has_bones=True)
    return skeleton, mesh


@pytest.mark.parametrize("axes", [(0, 1), (0, 2), (1, 2)])
def test_neutral_pabc_reconciles_paired_bind_axes_without_folding_weighted_vertices(axes):
    skeleton, mesh = _fixture()
    target = list(BIND)
    for axis in axes:
        target[axis * 4:axis * 4 + 3] = [-value for value in target[axis * 4:axis * 4 + 3]]
    before = copy.deepcopy(mesh)

    result = apply_skeleton_variation_to_mesh(mesh, skeleton, (0, 1), _variation(skeleton, target))

    for actual, expected in zip(result.submeshes[0].vertices, mesh.submeshes[0].vertices):
        assert actual == pytest.approx(expected, abs=1e-6)
    for actual, expected in zip(result.submeshes[0].normals, mesh.submeshes[0].normals):
        assert actual == pytest.approx(expected, abs=1e-6)
    assert mesh == before
    restored = result._cdmw_neutral_appearance.to_source(result, mesh)
    for actual, expected in zip(restored.submeshes[0].vertices, mesh.submeshes[0].vertices):
        assert actual == pytest.approx(expected, abs=1e-6)


def test_bind_axis_reconciliation_keeps_small_authored_translation():
    skeleton, mesh = _fixture()
    target = list(BIND)
    target[:8] = [-value if index % 4 != 3 else value for index, value in enumerate(target[:8])]
    target[12] += .00004
    result = apply_skeleton_variation_to_mesh(mesh, skeleton, (0, 1), _variation(skeleton, target))
    for index, weight in enumerate((1., .25)):
        source = mesh.submeshes[0].vertices[index]
        assert result.submeshes[0].vertices[index] == pytest.approx(
            (source[0] + .00004 * weight, source[1], source[2]), abs=1e-6,
        )


@pytest.mark.parametrize("target, expected", [
    ((0., 1., 0., 0., -1., 0., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.), (-2., 1., 3.)),
    ((-1., 0., 0., 0., 0., -1., 0., 0., 0., 0., 1., 0., .1, 0., 0., 1.), (-.9, -2., 3.)),
    ((-2., 0., 0., 0., 0., -1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.), (-2., -2., 3.)),
    ((-1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.), (-1., 2., 3.)),
])
def test_non_neutral_rotations_scales_and_reflections_are_preserved(target, expected):
    skeleton, mesh = _fixture(IDENTITY, IDENTITY)
    mesh.submeshes[0].vertices[0] = (1., 2., 3.)
    result = apply_skeleton_variation_to_mesh(mesh, skeleton, (0, 1), _variation(skeleton, target))
    assert result.submeshes[0].vertices[0] == pytest.approx(expected)
