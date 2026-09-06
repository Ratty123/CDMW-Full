from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.domain.mesh.skeleton import summarize_skeleton_bones
from cdmw.modding.skeleton_parser import Bone, Skeleton
from cdmw.services.mesh_rust_rig import selected_bone_influence


@pytest.mark.parametrize("row_major", [False, True])
def test_rig_overlay_uses_mesh_space_bind_positions_without_accumulating_parents(row_major):
    def matrix(x, y):
        values = [1., 0., 0., x, 0., 1., 0., y, 0., 0., 1., 0., 0., 0., 0., 1.]
        if row_major:
            values = [values[column * 4 + row] for row in range(4) for column in range(4)]
        return tuple(values)

    skeleton = Skeleton(bones=[
        Bone(index=0, name="Hip", bind_matrix=matrix(0., 100.), position=(0., 0., 0.)),
        Bone(index=1, name="Thigh", parent_index=0, bind_matrix=matrix(10., 90.), position=(10., -10., 0.)),
        Bone(index=2, name="Knee", parent_index=1, bind_matrix=matrix(10., 50.), position=(0., -40., 0.)),
    ])
    assert [bone.position for bone in summarize_skeleton_bones(skeleton)] == [
        (0., 100., 0.), (10., 90., 0.), (10., 50., 0.),
    ]
    assert skeleton.bones[2].position == (0., -40., 0.)
    assert summarize_skeleton_bones(Skeleton(bones=[Bone(position=(1., 2., 3.))]))[0].position == (1., 2., 3.)


def rig_session():
    return SimpleNamespace(
        skeleton=Skeleton(bones=[Bone(index=101), Bone(index=107)]),
        working_mesh=SimpleNamespace(submeshes=[
            SimpleNamespace(vertices=[(0., 0., 0.)] * 3,
                            bone_indices=[(0, 1, 2), (1,), (0,)],
                            bone_weights=[(.2, .3, .5), (1.,), (1.,)]),
            SimpleNamespace(vertices=[(0., 0., 0.)], bone_indices=[(1,)], bone_weights=[(.5,)]),
        ]),
    )


def test_rig_influence_maps_palette_slots_and_sums_repeated_bone_slots():
    session = rig_session()
    result = selected_bone_influence(session, 107, (0, 1, 1))
    assert result == {
        "bone_index": 107, "available": True, "reason": "", "vertex_count": 3,
        "parts": [{"submesh_index": 0, "weights": [[0, .8], [1, 1.]]},
                  {"submesh_index": 1, "weights": [[0, .5]]}],
    }
    assert session.working_mesh.submeshes[0].bone_weights[0] == (.2, .3, .5)


def test_rig_influence_distinguishes_unresolved_unweighted_and_invalid_data():
    session = rig_session()
    assert not selected_bone_influence(session, 107, ())["available"]
    assert not selected_bone_influence(session, -1, (0, 1, 1))["available"]
    empty = selected_bone_influence(session, 999, (0, 1, 1))
    assert empty["available"] and empty["vertex_count"] == 0 and not empty["parts"]
    session.working_mesh.submeshes[1].bone_weights = [(float("nan"),)]
    invalid = selected_bone_influence(session, 107, (0, 1, 1))
    assert not invalid["available"] and not invalid["parts"]


def test_rig_influence_never_publishes_a_partial_region_at_the_bound():
    with patch("cdmw.services.mesh_rust_rig.MAX_INFLUENCE_VERTICES", 2):
        result = selected_bone_influence(rig_session(), 107, (0, 1, 1))
    assert not result["available"] and result["parts"] == []


def test_rig_influence_rejects_incomplete_rows_instead_of_showing_partial_weights():
    session = rig_session()
    session.working_mesh.submeshes[1].bone_weights = []
    result = selected_bone_influence(session, 107, (0, 1, 1))
    assert not result["available"] and result["parts"] == []
