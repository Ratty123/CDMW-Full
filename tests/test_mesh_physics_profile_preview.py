from dataclasses import replace
import hashlib
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.models import PbdProfileBinding, PbdProfileDocument
from cdmw.modding.mesh_parser import parse_pac
from cdmw.services.mesh_rust_physics_profiles import _cloth_geometry, _profile_preview
from tests.test_mesh_physics_profiles import physics_inputs
from tests.test_pac_cloth_guides import guide_fixture


def _document(source, **overrides):
    values = {"SimulationMode": "cloth", "StretchingStiffness": ".3", "BendingStiffness": ".1388",
              "Damping": ".8", "Gravity": "-10", "SolverIterationCount": "3",
              "UseVertexAlphaPositionBlending": "1", "UseRotationCorrection": "0"}
    values.update(overrides)
    xml = '<SimulationParameters>' + ''.join(f'<{key}>{value}</{key}>' for key, value in values.items() if value is not None)
    xml += '<AttachedCloth><Damping>8</Damping><Gravity>-99</Gravity><SimulationMode>spline</SimulationMode></AttachedCloth>'
    xml += '<UnknownFlag magic="keep"/><!-- untouched --></SimulationParameters>'
    data = xml.encode('utf-16')
    return PbdProfileDocument("profile.xml", source.identity, data, hashlib.sha256(data).hexdigest())


def test_authored_coefficients_use_decoded_initial_conversion_and_packing(physics_inputs):
    source, *_ = physics_inputs
    document = _document(source)
    before = document.data
    result = _profile_preview(document)
    assert result["preview"] == {
        "gravity": 10., "damping": .7998046875, "stretch": .359619140625,
        "bend": .05999755859375, "iterations": 4, "use_vertex_alpha": True, "rotate_guides": False,
    }
    assert result["authored"]["solveriterationcount"] == "3"
    assert result["authored"]["damping"] == ".8"
    assert document.data == before and result["sha256"] == hashlib.sha256(before).hexdigest()
    # XML source order matters: a later mode resets the rotation flag.
    reordered = replace(document, data=before.decode('utf-16').replace(
        '<SimulationMode>cloth</SimulationMode>', '').replace(
        '<UseRotationCorrection>0</UseRotationCorrection>',
        '<UseRotationCorrection>0</UseRotationCorrection><SimulationMode>cloth</SimulationMode>',
    ).encode('utf-16'))
    assert _profile_preview(reordered)["preview"]["rotate_guides"] is True
    high_damping = _profile_preview(_document(source, Damping="8.125"))
    assert high_damping["preview"]["damping"] == 8.125  # Not the heuristic parser's clamp.
    disabled = _profile_preview(_document(source, StretchingStiffness="-1", BendingStiffness="0"))
    assert disabled["preview"]["stretch"] == disabled["preview"]["bend"] == 0


@pytest.mark.parametrize("overrides", [
    {"SimulationMode": "spline"}, {"SimulationMode": None}, {"Gravity": None},
    {"Gravity": "100.1"}, {"Gravity": "-100.1"}, {"Gravity": "nan"}, {"Gravity": "inf"},
    {"Damping": "10.1"}, {"SolverIterationCount": "9"},
    {"StretchingStiffness": "nan"}, {"BendingStiffness": "inf"},
    {"UseVertexAlphaPositionBlending": "true"}, {"SolverIterationCount": "3.5"},
])
def test_unresolved_or_unsupported_values_do_not_become_a_preview_preset(physics_inputs, overrides):
    source, *_ = physics_inputs
    result = _profile_preview(_document(source, **overrides))
    assert result["preview"] is None and result["reason"]


@pytest.mark.parametrize("gravity", [-100, -10, 0, 20, 100])
def test_signed_gravity_preserves_authored_value_and_converts_preview_direction(physics_inputs, gravity):
    source, *_ = physics_inputs
    document = _document(source, Gravity=str(gravity))
    before = document.data
    result = _profile_preview(document)
    assert result["preview"]["gravity"] == -gravity
    assert result["authored"]["gravity"] == str(gravity)
    assert document.data == before


def test_guide_diagnostic_distinguishes_absent_unsupported_and_authored_geometry():
    data, _ = guide_fixture()
    assert _cloth_geometry(data) == {"status": "available", "guide_count": 3, "fixed_count": 3}
    absent = bytearray(data)
    absent[81] = 0  # PAC metadata's guide-layout flag.
    assert _cloth_geometry(bytes(absent)) == {"status": "absent", "guide_count": 0}
    unknown = bytearray(data)
    unknown[81] = 1  # Present, but not a decoded layout.
    for unsupported in (bytes(unknown), data[:100], b"unknown header"):
        diagnostic = _cloth_geometry(unsupported)
        assert diagnostic["status"] == "unsupported" and diagnostic["reason"]
        assert "guide_count" not in diagnostic


def test_session_projects_exact_source_assignments_across_rename_and_empty_variant(physics_inputs, tmp_path):
    from cdmw.services.mesh_physics_profiles import resolve_mesh_physics_profiles
    from tests.test_mesh_rust_authoring import RustMeshAuthoringTests

    source, index, *_ = physics_inputs
    context = resolve_mesh_physics_profiles(source, index)
    source_name = parse_pac(source.prepared_path.read_bytes(), source.path).submeshes[0].name
    profile = replace(_document(source), path=context.profiles[0].path)
    context = replace(context, profiles=(profile,), bindings=(
        PbdProfileBinding("Lower_Leather", source_name, "", "0", profile.path),
        PbdProfileBinding("", source_name, "", "1"),
        PbdProfileBinding("Decoy", "renamed", "", "1", "wrong.xml"),
    ))
    service, host = RustMeshAuthoringTests()._create(
        tmp_path / "session", preview_material_model=SimpleNamespace(path=source.path, submeshes=()),
        target_entry=source, physics_profile_context=context,
    )
    try:
        state = host.state_payload(include_document=False)["physics_profiles"]
        part = state["parts"][0]
        assert state["available"] and state["variants"] == ["0", "1"]
        assert [(row["variant"], row["profile"]) for row in part["bindings"]] == [("0", "Lower_Leather"), ("1", "")]
        assert state["profiles"][0]["preview"]["gravity"] == 10
        assert state["sidecar_sha256"] == context.sidecar.sha256
        # The host fixture uses an older PAC header: an unsupported decoder is
        # not evidence that the source model has no guides.
        assert state["cloth_geometry"]["status"] == "unsupported"
        assert "guide_count" not in state["cloth_geometry"]
        session = host.shadow_service._session(host.shadow_session_id)
        session.working_mesh.submeshes[0].name = "renamed"
        with patch('cdmw.services.mesh_rust_physics_profiles.parse_pac', side_effect=AssertionError('not cached')), \
             patch('cdmw.services.mesh_rust_physics_profiles.decode_pac_cloth_guides', side_effect=AssertionError('not cached')):
            renamed = host.state_payload(include_document=False)["physics_profiles"]
        assert renamed["parts"][0]["name"] == "renamed"
        assert renamed["parts"][0]["source_name"] == source_name
        assert renamed["parts"][0]["bindings"] == part["bindings"]
        assert renamed["cloth_geometry"] == state["cloth_geometry"]
        assert profile.data == context.profiles[0].data
        assert "data" not in state["profiles"][0]  # Raw XML is retained only on the host.
    finally:
        host.cancel()
        service.close_edit_session("authoritative-rust-test", force_without_saving=True)
