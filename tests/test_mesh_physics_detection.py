"""Physics classification requires vertex bindings, guides and exact profile evidence."""

import copy
import struct

import pytest

from cdmw.domain.mesh.cloth import PacClothRule
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.services.mesh_physics_profiles import resolve_mesh_physics_profiles
from cdmw.services.mesh_rust_cloth import physics_detection_ui_state
from tests.test_mesh_cloth_influence import apply_rule, shadow_output
from tests.test_mesh_physics_profiles import _prepared
from tests.test_mesh_rust_authoring_exact_output import _open_exact_session
from tests.test_mesh_rust_replacement import command
from tests.test_pac_cloth_guides import guide_fixture


def detection_fixture(*, spline=True, bound=True, bad_lod=None):
    source, offsets = guide_fixture()
    data = bytearray(source)
    flags = struct.unpack_from("<I", data, 80)[0]
    struct.pack_into("<I", data, 80, flags | 0x8000 if spline else flags)
    data[offsets["channel_b"]:offsets["channel_b"] + 3] = bytes((255, 0, 0))
    for lod, mesh in enumerate(pac_cloth_lods(data)):
        for part in mesh.submeshes:
            for vertex, offset in enumerate(part.source_vertex_offsets):
                data[offset + 28] = 255
                data[offset + 38:offset + 40] = bytes((255, 63))
                if bound and vertex > 0:
                    struct.pack_into("<2e", data, offset + 12, 2., 2.)
                    struct.pack_into("<I", data, offset + 24, 1 << 20)
                    data[offset + 32] = 255
                    data[offset + 39] = 0
                    if lod == bad_lod:
                        struct.pack_into("<e", data, offset + 12, 9.)
    return bytes(data)


@pytest.fixture
def detection_host(tmp_path, monkeypatch):
    source = detection_fixture()
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **_: source)
    _, service, host = _open_exact_session(tmp_path / "session")
    yield source, host
    if not host.closed:
        host.cancel()
    service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def detect(host):
    return host.state_payload(include_document=False)["physics"]["parts"][0]


def exact_profiles(tmp_path, source, mode):
    target = _prepared(tmp_path, "owned-rust-exact.pac", source)
    sidecar = _prepared(tmp_path, "owned-rust-exact.pac_xml", (
        '<ModelPropertyList><ModelProperty Index="0">'
        '<SkinnedMeshMaterialWrapper _subMeshName="MESH" _pbdSimulationMaterialName="WeaponProfile"/>'
        '</ModelProperty><ModelProperty Index="1">'
        '<SkinnedMeshMaterialWrapper _subMeshName="mesh" _pbdSimulationMaterialName=""/>'
        '</ModelProperty></ModelPropertyList>'
    ).encode())
    catalogue = _prepared(tmp_path, "character/descriptors/pbd/pbdconfig.xml",
        b'<Config><Material Name="WeaponProfile" Filename="Material/weapon/profile.xml"/></Config>')
    profile = _prepared(tmp_path, "character/descriptors/pbd/material/weapon/profile.xml",
        f'<Profile><SimulationMode>{mode}</SimulationMode></Profile>'.encode())
    entries = {entry.basename.casefold(): [entry] for entry in (sidecar, catalogue, profile)}
    context = resolve_mesh_physics_profiles(target, entries)
    assert not context.problem and context.profiles
    return context


def test_raw_spline_detection_works_without_a_preview_rig_or_name_hint(detection_host):
    source, host = detection_host
    row = detect(host)
    assert row["name"] == "mesh"  # Names do not classify the physics.
    assert row["kind"] == "spline" and row["mode_source"] == "pac_default"
    assert row["guide_counts"] == [2] * 4 and row["vertex_counts"] == [3] * 4
    assert row["guides"]["guide_count"] == 3 and row["guides"]["fixed_count"] == 1
    assert row["jiggle_counts"] == [0] * 4
    assert not host.state_payload(include_document=False)["jiggle"]["decoded"]["available"]
    assert row["preview_reason"] == "spline_preview_approximate"
    assert shadow_output(host) == source


@pytest.mark.parametrize("mode", ["cloth", "spline"])
def test_exact_assignments_override_pac_default_and_keep_empty_variants(detection_host, tmp_path, mode):
    source, host = detection_host
    host.physics_profile_context = exact_profiles(tmp_path, source, mode)
    row = detect(host)
    assert row["kind"] == mode and row["mode_source"] == "profile"
    assert [(profile["variant"], profile["profile"], profile["mode"]) for profile in row["profiles"]] == [
        ("0", "WeaponProfile", mode), ("1", "", "")]
    assert shadow_output(host) == source


def test_disabled_edit_and_undo_keep_the_retained_spline_identity(detection_host, tmp_path):
    source, host = detection_host
    assert detect(host)["current_guide_count"] == 2
    apply_rule(host, tmp_path, PacClothRule(0))
    row = detect(host)
    assert row["kind"] == "spline" and row["guide_counts"] == [2] * 4
    assert row["current_guide_count"] == 0
    command(host, "undo")
    assert detect(host)["current_guide_count"] == 2
    assert shadow_output(host) == source


@pytest.mark.parametrize("bound", [False, True])
def test_jiggle_contribution_is_detected_separately_and_can_coexist_with_guides(tmp_path, monkeypatch, bound):
    data = bytearray(detection_fixture(bound=bound))
    for level in pac_cloth_lods(data):
        data[level.submeshes[0].source_vertex_offsets[1] + 38] = 0xF2
    source = bytes(data)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **_: source)
    _, service, host = _open_exact_session(tmp_path / "session")
    try:
        row = detect(host)
        assert row["kind"] == ("spline" if bound else "jiggle")
        assert row["jiggle_counts"] == [1] * 4 and row["current_jiggle_count"] == 1
        assert shadow_output(host) == source
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


@pytest.mark.parametrize("bound,bad_lod,expected", [(False, None, "none"), (True, 3, "guide")])
def test_guide_resource_alone_and_invalid_lower_lod_references_do_not_prove_spline(
    tmp_path, monkeypatch, bound, bad_lod, expected,
):
    source = detection_fixture(bound=bound, bad_lod=bad_lod)
    monkeypatch.setattr("tests.test_mesh_rust_authoring_exact_output._pac_fixture", lambda **_: source)
    _, service, host = _open_exact_session(tmp_path / "session")
    try:
        row = detect(host)
        assert row["kind"] == expected
        if bad_lod is not None:
            assert row["reason"] == "guide_indices_out_of_range"
        assert shadow_output(host) == source
    finally:
        host.cancel()
        service.close_edit_session(host.authoritative_session_id, force_without_saving=True)


def inputs(host):
    state = host.state_payload(include_document=False)
    return [copy.deepcopy(state[key]) for key in ("replacement", "cloth", "jiggle", "physics_profiles")]


def test_shared_spline_profile_does_not_classify_rigid_parts_or_follow_their_names(detection_host, tmp_path):
    source, host = detection_host
    host.physics_profile_context = exact_profiles(tmp_path, source, "spline")
    replacement, cloth, jiggle, profiles = inputs(host)
    for index, name in enumerate(("Cloth_Guard", "Tail_Handle", "Sword", "Cloth_Acc"), 1):
        part = {**replacement["parts"][0], "id": f"rigid:{index}", "index": index, "name": name}
        replacement["parts"].append(part)
        cloth["inspected_parts"].append({**cloth["inspected_parts"][0], **part, "lod_counts": [0] * 4})
        profiles["parts"].append({**profiles["parts"][0], **part})
    rows = physics_detection_ui_state(replacement, cloth, jiggle, profiles)["parts"]
    assert [row["kind"] for row in rows] == ["spline", "none", "none", "none", "none"]


@pytest.mark.parametrize("status", ["absent", "unsupported"])
def test_missing_or_undecoded_guides_are_reported_independently_of_bindings(detection_host, status):
    _, host = detection_host
    replacement, cloth, jiggle, profiles = inputs(host)
    cloth["guides"] = {"status": status, "reason": "Unknown guide layout" if status == "unsupported" else ""}
    row = physics_detection_ui_state(replacement, cloth, jiggle, profiles)["parts"][0]
    assert row["kind"] == "guide" and row["guide_counts"] == [2] * 4
    assert row["reason"]


@pytest.mark.parametrize("failure", ["missing_profile", "mixed_modes", "ambiguous_variant", "disabled_profile"])
def test_unresolved_mixed_or_disabled_profiles_never_fall_back_to_pac_spline(detection_host, tmp_path, failure):
    source, host = detection_host
    host.physics_profile_context = exact_profiles(tmp_path, source, "spline")
    replacement, cloth, jiggle, profiles = inputs(host)
    bindings = profiles["parts"][0]["bindings"]
    if failure == "missing_profile":
        profiles["profiles"] = []
    elif failure == "mixed_modes":
        other = {**profiles["profiles"][0], "path": "cloth.xml", "authored": {"simulationmode": "cloth"}}
        profiles["profiles"].append(other)
        bindings[1].update(profile="Other", path=other["path"])
    elif failure == "ambiguous_variant":
        bindings.append(dict(bindings[0]))
    else:
        profiles["profiles"][0]["authored"]["simulationmode"] = "NoSimulation"
    row = physics_detection_ui_state(replacement, cloth, jiggle, profiles)["parts"][0]
    assert row["kind"] == "guide" and row["mode_source"] != "pac_default"
    assert row["reason"]


def test_unreadable_bindings_are_unknown_and_never_reported_as_rigid(detection_host):
    _, host = detection_host
    replacement, cloth, jiggle, profiles = inputs(host)
    cloth.update(inspected_parts=[], inspection_reason="Unsupported PAC records")
    row = physics_detection_ui_state(replacement, cloth, jiggle, profiles)["parts"][0]
    assert row["kind"] == "unknown" and row["reason"] == "Unsupported PAC records"
