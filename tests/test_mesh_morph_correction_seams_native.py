"""Resident seam-cohort correction regression; requires rebuilt native core."""

import pytest

from cdmw.domain.mesh import MeshEditSelection
from tests.test_mesh_morph_authoring_native import resident, _positions, _sculpt, _assert_positions_equal
from tests.test_mesh_morph_service import _author_command


@pytest.mark.parametrize("weight", [0.0, 0.25])
def test_saved_correction_respects_effective_coincident_seam_mask(resident, weight):
    service, open_session = resident
    session_id = open_session()
    assert service.apply_command(session_id, _author_command()).ok
    assert service.set_refit_driver(session_id, (0, 1))[0].ok
    assert service.bind_refit(session_id, (2,))[0].ok
    assert service.set_refit_vertex_influence(
        session_id, selection=MeshEditSelection.from_maps(vertices_by_submesh={2: (0,)}), weight=weight,
    )[0].ok
    # Vertices0 and3 coincide, but vertex3 still has a raw mask of1. Native
    # fitting uses the cohort minimum, which the saved delta must also use.
    assert service.begin_morph_correction(session_id, "volume", (2,))[0].ok
    assert _sculpt(service, session_id, {2: (3,)}, (0.0, 0.0, 0.2)).ok
    target = _positions(service, session_id, 2)
    if weight == 0.0:
        with pytest.raises(ValueError, match="protected"):
            service.save_morph_correction(session_id)
        assert service.cached_morph_state(session_id).correction_definition_id == "volume"
        _assert_positions_equal(_positions(service, session_id, 2), target)
    else:
        assert service.save_morph_correction(session_id)[0].ok
        _assert_positions_equal(_positions(service, session_id, 2), target)
