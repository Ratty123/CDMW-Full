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


def test_batched_neutral_deformation_matches_scalar_for_ragged_and_invalid_weights(monkeypatch):
    from cdmw.modding import mesh_parser, skeleton_variation_parser as variation
    assert mesh_parser._np_module() is not None
    _, mesh = _fixture()
    submesh = mesh.submeshes[0]
    submesh.vertices = [(1., 2., 3.)] * 7
    submesh.normals = [(0.2, 0.4, 0.8)] * 7
    submesh.bone_indices = [(0,), (0, 1), (0, 1, 99), (-1,), (), (0, 1), (1,)]
    submesh.bone_weights = [(1.,), (.25, .75), (.5, float('nan'), .5), (1.,), (), (.4,), (0.,)]
    matrices = (BIND, IDENTITY)
    fast_positions = variation._deform_positions(submesh, (1, 0), matrices)
    fast_normals = variation._deform_normals(submesh, (1, 0), matrices)
    monkeypatch.setattr(mesh_parser, "_np_module", lambda: None)
    scalar_positions = variation._deform_positions(submesh, (1, 0), matrices)
    scalar_normals = variation._deform_normals(submesh, (1, 0), matrices)
    for observed, expected in zip(fast_positions + fast_normals, scalar_positions + scalar_normals):
        assert observed == pytest.approx(expected, abs=1e-12)
