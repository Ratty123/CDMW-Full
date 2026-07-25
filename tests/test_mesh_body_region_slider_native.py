"""Region sliders through the real service and native core, not just Python.

Everything upstream of this is validated headlessly against pure-Python maths.
This drives a generated profile the way the app does — save it, activate it,
move a slider, read the geometry back out of the native session — because the
failures that matter here are integration ones. The fingerprint mismatch that
made every region-scoped profile fail to activate was invisible until a profile
actually reached ``activate_morph_profile``.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from cdmw.domain.mesh.body_region_falloff import smooth_body_region_weights
from cdmw.domain.mesh.body_region_sliders import build_region_slider_profile
from cdmw.domain.mesh.body_regions import build_body_region_map
from cdmw.domain.mesh.morph import generate_procedural_morph_fields
from cdmw.modding import mesh_native_core
from cdmw.services.mesh_morph_profiles import mesh_morph_profile_root, save_mesh_morph_profile
from cdmw.services.mesh_service import MeshService

from tests.test_mesh_body_region_sliders import _limb_mesh, _limb_skeleton


class _Settings:
    def __init__(self, path: Path) -> None:
        self._path = path

    def fileName(self) -> str:
        return str(self._path)


def _require_native() -> None:
    if not mesh_native_core.native_mesh_core_available():
        pytest.skip("native mesh core binary not available")


def _region_profile(mesh, *, region_ids: tuple[str, ...] = ()):
    region_map = smooth_body_region_weights(
        mesh, build_body_region_map(mesh, _limb_skeleton()), band=0.15
    )
    return build_region_slider_profile(mesh, region_map, region_ids=region_ids)


def _positions(mesh) -> list[tuple[float, float, float]]:
    return [tuple(vertex) for submesh in mesh.submeshes for vertex in submesh.vertices]


def _expected_offsets(mesh, profile, definition_id: str, percent: float) -> dict[int, tuple[float, float, float]]:
    definition = next(item for item in profile.definitions if item.definition_id == definition_id)
    scale = percent / 100.0
    offsets: dict[int, tuple[float, float, float]] = {}
    for field in generate_procedural_morph_fields(mesh, definition):
        for vertex_index, delta in zip(field.vertex_indices, field.deltas):
            offsets[vertex_index] = tuple(component * scale for component in delta)
    return offsets


@pytest.mark.parametrize("region_ids", ((), ("thigh_l",)))
def test_generated_region_profile_activates_and_drives_native_geometry(tmp_path, region_ids) -> None:
    """A whole-body profile and a region-scoped one must both activate.

    The scoped case is the regression: its fingerprint covers only the
    submeshes its definitions touch, and carrying the region map's own
    fingerprint instead made activation raise.
    """

    _require_native()
    mesh = _limb_mesh()
    profile = _region_profile(mesh, region_ids=region_ids)
    assert profile.definitions, "the generated profile has no sliders"

    settings = _Settings(tmp_path / "settings.ini")
    service = MeshService(settings=settings)
    save_mesh_morph_profile(mesh_morph_profile_root(settings), profile)
    view = service.open_edit_session(mesh, mode="edit")
    session_id = view.session_id
    try:
        _result, state = service.activate_morph_profile(session_id, profile.profile_id)
        assert state.profile_id == profile.profile_id
        assert {item.definition_id for item in state.definitions} == {
            item.definition_id for item in profile.definitions
        }

        target = "thigh_l_size"
        baseline = _positions(service.working_mesh(session_id, clone=True))
        _result, state = service.set_morph_value(session_id, target, 100.0)
        assert dict(state.values)[target] == pytest.approx(100.0)

        moved = _positions(service.working_mesh(session_id, clone=True))
        expected = _expected_offsets(mesh, profile, target, 100.0)
        assert expected, "the slider generated no displacement to check"

        for index, (before, after) in enumerate(zip(baseline, moved)):
            offset = expected.get(index, (0.0, 0.0, 0.0))
            for axis in range(3):
                assert after[axis] == pytest.approx(before[axis] + offset[axis], abs=1e-6), (
                    f"vertex {index} axis {axis} diverged from the Python field"
                )
    finally:
        service.close_edit_session(session_id)


def test_region_slider_round_trips_through_reset_and_bake(tmp_path) -> None:
    _require_native()
    mesh = _limb_mesh()
    profile = _region_profile(mesh)
    settings = _Settings(tmp_path / "settings.ini")
    service = MeshService(settings=settings)
    save_mesh_morph_profile(mesh_morph_profile_root(settings), profile)
    view = service.open_edit_session(mesh, mode="edit")
    session_id = view.session_id
    try:
        service.activate_morph_profile(session_id, profile.profile_id)
        baseline = _positions(service.working_mesh(session_id, clone=True))

        service.set_morph_value(session_id, "thigh_l_size", 100.0)
        lifted = _positions(service.working_mesh(session_id, clone=True))
        assert any(
            not all(math.isclose(a, b, abs_tol=1e-9) for a, b in zip(first, second))
            for first, second in zip(baseline, lifted)
        ), "the slider moved nothing"

        # Reset returns the surface exactly, so a slider is non-destructive.
        _result, state = service.reset_morph(session_id)
        assert all(value == pytest.approx(0.0) for _definition_id, value in state.values)
        restored = _positions(service.working_mesh(session_id, clone=True))
        for first, second in zip(baseline, restored):
            for axis in range(3):
                assert second[axis] == pytest.approx(first[axis], abs=1e-6)

        # Baking keeps the shaped surface and clears the unbaked flag.
        service.set_morph_value(session_id, "thigh_l_size", 100.0)
        shaped = _positions(service.working_mesh(session_id, clone=True))
        _result, state = service.bake_morph(session_id)
        assert not state.unbaked
        baked = _positions(service.working_mesh(session_id, clone=True))
        for first, second in zip(shaped, baked):
            for axis in range(3):
                assert second[axis] == pytest.approx(first[axis], abs=1e-6)
    finally:
        service.close_edit_session(session_id)
