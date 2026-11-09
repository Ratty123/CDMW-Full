"""Create New Item: painted cloth gets guides of its own and a cloth profile."""

from types import SimpleNamespace

import pytest

from cdmw.modding.mesh_deformer import copy_extra_submesh_attrs
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.modding.pac_cloth import pac_cloth_lods
from cdmw.modding.pac_cloth_guides import decode_pac_cloth_guides
from cdmw.modding.scene_geometry_utils import _copy_submesh_with_transform
from cdmw.services.new_item_cloth_guides import (
    apply_import_cloth_guides, assign_cloth_profile, cloth_profile_names, import_cloth_samples, mesh_has_cloth_pins,
)
from tests.test_pac_cloth_painted_guides import grid_pac

IDENTITY = (1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1., 0., 0., 0., 0., 1.)

SIDECAR = b"""<SkinnedMeshPropertyCommon ReflectObjectXMLDataVersion="9"/>
<ModelPropertyList>
\t<ModelProperty Index="0" Version="Reflection">
\t\t<SkinnedMeshProperty ReflectObjectXMLDataVersion="9"%s>
\t\t\t<Vector Name="_subMeshResources">
\t\t\t\t<SkinnedMeshMaterialWrapper ItemID="1" _subMeshName="skirt" _jiggleWindWeight="0"/>
\t\t\t\t<SkinnedMeshMaterialWrapper ItemID="2" _subMeshName="belt" _jiggleWindWeight="0"/>
\t\t\t</Vector>
\t\t</SkinnedMeshProperty>
\t</ModelProperty>
</ModelPropertyList>
"""

CATALOGUE = b"""<PbdConfig>
\t<Material Name="Cloth_Skirt" Filename="material/cloth_skirt.xml"/>
\t<Material Name="wing" Filename="material/wing.xml"/>
</PbdConfig>
"""


def imported_from(data, *, paint_below=.55, pins=None):
    part = pac_cloth_lods(data)[0].submeshes[0]
    mesh_part = SubMesh(name="skirt", material="cloth", vertices=[tuple(v) for v in part.vertices], faces=list(part.faces))
    mesh_part.cloth_paint = [1.0 if v[1] < paint_below else 0.0 for v in part.vertices]
    if pins is not None:
        mesh_part.cloth_pin = [bool(pins(v)) for v in part.vertices]
    return ParsedMesh(format="obj", submeshes=[mesh_part])


def test_pins_follow_copies_transforms_and_samples():
    mesh = imported_from(grid_pac(), pins=lambda v: v[1] > .99)
    assert mesh_has_cloth_pins(mesh)
    target = SubMesh(name="copy")
    copy_extra_submesh_attrs(mesh.submeshes[0], target)
    assert target.cloth_pin == mesh.submeshes[0].cloth_pin
    assert _copy_submesh_with_transform(mesh.submeshes[0], IDENTITY).cloth_pin == mesh.submeshes[0].cloth_pin
    samples = import_cloth_samples(mesh, IDENTITY)
    assert sum(samples.pins) == 13 and len(samples.pins) == len(samples.positions)


def test_service_builds_own_guides_and_records_the_profile_choice():
    data = grid_pac()
    result = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    assert apply_import_cloth_guides(result, imported_from(data), IDENTITY, profile="Cloth_Skirt")
    guides = decode_pac_cloth_guides(result.rebuilt_data)
    assert guides is not None and result.cloth_paint_report.guide_count == len(guides.vertices)
    assert result.cloth_profile_edit == ("Cloth_Skirt", ("skirt",))
    assert "new cloth guides" in result.summary_lines[-1] and "test in game" in result.summary_lines[-1]
    unpainted = imported_from(data, paint_below=-1)
    untouched = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    assert not apply_import_cloth_guides(untouched, unpainted, IDENTITY)
    assert untouched.rebuilt_data == data and not untouched.summary_lines


def test_service_refuses_paint_with_nothing_holding_it():
    data = grid_pac()
    result = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    with pytest.raises(ValueError, match="Nothing holds the painted cloth"):
        apply_import_cloth_guides(result, imported_from(data, paint_below=2.0), IDENTITY)
    assert result.rebuilt_data == data
    pinned = imported_from(data, paint_below=2.0, pins=lambda v: v[1] > .99)
    assert apply_import_cloth_guides(result, pinned, IDENTITY)


def test_profile_assignment_writes_the_owner_and_keeps_everything_else():
    sidecar = SIDECAR % b""
    result = assign_cloth_profile(sidecar, "Cloth_Skirt", ("skirt",), catalogue=CATALOGUE)
    assert b'<SkinnedMeshProperty ReflectObjectXMLDataVersion="9" _pbdSimulationMaterialName="Cloth_Skirt">' in result
    assert result.replace(b' _pbdSimulationMaterialName="Cloth_Skirt"', b"") == sidecar
    assert assign_cloth_profile(result, "Cloth_Skirt", ("skirt",), catalogue=CATALOGUE) == result
    assert cloth_profile_names(CATALOGUE) == ("Cloth_Skirt", "wing")


def test_template_profile_is_kept_only_when_it_exists():
    named = SIDECAR % b' _pbdSimulationMaterialName="wing"'
    assert assign_cloth_profile(named, "", ("SKIRT",)) == named
    with pytest.raises(ValueError, match="no cloth profile"):
        assign_cloth_profile(SIDECAR % b"", "", ("skirt",))
    with pytest.raises(ValueError, match="not in the game's profile catalogue"):
        assign_cloth_profile(named, "Made_Up", ("skirt",), catalogue=CATALOGUE)
    with pytest.raises(ValueError, match="no entry for cloth part"):
        assign_cloth_profile(named, "wing", ("cape",))


def test_model_files_carry_the_profile_into_the_sidecar(tmp_path):
    from cdmw.services.new_item_planning import NewItemPlanError, model_files_from_import

    path = "character/modelproperty/1_pc/1_phm/armor/skirt.pac_xml"
    family = SimpleNamespace(files_for=lambda role: (SimpleNamespace(path=path),) if role == "pac_xml" else ())
    spec = SimpleNamespace(target_path=path, payload_data=SIDECAR % b"", source_path=None)
    result = SimpleNamespace(rebuilt_data=b"pac", supplemental_file_specs=(spec,), summary_lines=[],
                             cloth_paint_report=object(), cloth_profile_edit=("wing", ("skirt",)))
    files = model_files_from_import(result, family=family)
    assert files.cloth_painted and files.cloth_profile == ("wing", ("skirt",))
    assert b'_pbdSimulationMaterialName="wing"' in files.side_files[path]
    keep = SimpleNamespace(**{**vars(result), "cloth_profile_edit": ("", ("skirt",))})
    with pytest.raises(NewItemPlanError, match="no cloth profile"):
        model_files_from_import(keep, family=family)
    bare = SimpleNamespace(**{**vars(result), "supplemental_file_specs": ()})
    with pytest.raises(NewItemPlanError, match="no material file"):
        model_files_from_import(bare, family=family)


def test_editor_pins_the_sent_selection_with_undo_and_publishes_pinned_rows():
    from cdmw.services.mesh_rust_authoring import RustMeshValidationError
    from cdmw.services.mesh_rust_cloth_paint import cloth_paint_state, run_cloth_pin_command
    from cdmw.services.mesh_rust_state_cache import RustMeshStateCache
    from tests.test_new_item_cloth_paint import _authoring_for, _selection, imported

    authoring = _authoring_for(imported(((0., 0., 0.), (1., 0., 0.), (0., 1., 0.), (1., 1., 0.)), ()))
    service, sid = authoring.shadow_service, authoring.shadow_session_id
    try:
        session = service._session(sid)
        assert run_cloth_pin_command(authoring, {"selection": _selection((2, 3)), "value": True}) == {
            "changed_vertex_count": 2}
        state = cloth_paint_state(session, RustMeshStateCache())
        assert state["pins_supported"] and state["pinned_vertex_count"] == 2
        assert state["pin_parts"] == [{"submesh_index": 0, "vertices": [2, 3]}]
        service.undo(sid)
        assert not any(getattr(service._session(sid).working_mesh.submeshes[0], "cloth_pin", ()) or ())
        service.redo(sid)
        assert service._session(sid).working_mesh.submeshes[0].cloth_pin == [False, False, True, True]
        assert run_cloth_pin_command(authoring, {"selection": _selection(()), "value": False, "whole_model": True}) == {
            "changed_vertex_count": 2}
        with pytest.raises(RustMeshValidationError, match="Pin a selection"):
            run_cloth_pin_command(authoring, {"selection": _selection(()), "value": True, "whole_model": True})
        with pytest.raises(RustMeshValidationError, match="true or false"):
            run_cloth_pin_command(authoring, {"selection": _selection((1,)), "value": 1})
    finally:
        service.close_edit_session(sid)


def test_game_models_offer_pins_but_not_paint():
    from cdmw.services.mesh_rust_cloth_paint import cloth_paint_state

    part = SubMesh(name="cape", vertices=[(0., 0., 0.), (1., 0., 0.)], faces=[])
    part.cloth_pin = [True, False]
    state = cloth_paint_state(SimpleNamespace(mesh_format="pac", working_mesh=ParsedMesh(format="pac", submeshes=[part])))
    assert not state["supported"] and state["pins_supported"] and state["pinned_vertex_count"] == 1


def test_subdivided_edge_is_pinned_only_between_two_pins():
    from cdmw.modding.mesh_deformer import _subdivide_interchange_vertex_channels

    part = SubMesh(name="cape", vertices=[(0., 0., 0.), (1., 0., 0.), (0., 1., 0.)], faces=[(0, 1, 2)])
    part.cloth_pin = [True, True, False]
    _subdivide_interchange_vertex_channels(part, {(0, 1): 3, (1, 2): 4}, 3, None)
    assert part.cloth_pin == [True, True, False, True, False]


def test_real_static_build_with_a_placement_gets_its_own_guides_on_the_painted_area():
    from cdmw.modding.mesh_parser import parse_pac
    from cdmw.modding.static_mesh_build import build_static_mesh_replacement
    from cdmw.modding.static_mesh_types import StaticMeshReplacementOptions, StaticSubmeshMapping
    from cdmw.ui.new_item.model_import import ModelPlacement
    from tests.test_new_item_cloth_paint import _inverse_rows, _row

    raw = grid_pac()
    original = parse_pac(raw, "skirt.pac")
    template = pac_cloth_lods(raw)[0].submeshes[0]
    origin = (0., 0., 0.)
    placement = ModelPlacement(offset=(.25, 0., .5), rotation=(0., 0., 90.))
    inverse = _inverse_rows(placement.matrix(origin=origin))
    part = SubMesh(name="skirt", material="cloth", vertices=[_row(p, inverse) for p in template.vertices],
                   faces=list(template.faces))
    part.uvs = [(0., 0.)] * len(part.vertices)
    part.cloth_paint = [1.0 if p[1] < .55 else 0.0 for p in template.vertices]
    mesh = ParsedMesh(format="obj", submeshes=[part])
    options = StaticMeshReplacementOptions(
        complete_external_swap=True, transform=placement.build_transform(origin=origin),
        submesh_mappings=[StaticSubmeshMapping(0, "skirt", [0], 0)])
    output, report = build_static_mesh_replacement(raw, original, mesh, options)
    assert not report.errors
    result = SimpleNamespace(rebuilt_data=output, summary_lines=[])
    assert apply_import_cloth_guides(result, mesh, placement.matrix(origin=origin), profile="wing")
    guides = decode_pac_cloth_guides(result.rebuilt_data)
    assert guides is not None and all(p[1] < .55 for p in guides.vertices)
    assert {round(guides.vertices[i][1], 3) for i, b in enumerate(guides.channel_b) if b == 255} == {0.5}


def test_following_a_template_without_cloth_points_to_guides_of_its_own():
    from cdmw.services.new_item_cloth_paint import apply_import_cloth_paint, mesh_has_cloth_paint
    data = grid_pac()
    result = SimpleNamespace(rebuilt_data=data, summary_lines=[])
    with pytest.raises(ValueError, match="Gets cloth guides of its own"):
        apply_import_cloth_paint(result, imported_from(data), IDENTITY)
    assert result.rebuilt_data == data and not result.summary_lines
    mesh = imported_from(data, paint_below=-1.)
    assert not mesh_has_cloth_paint(mesh)
    mesh.submeshes[0].cloth_paint[-1] = float("nan")
    assert not mesh_has_cloth_paint(mesh)
    mesh.submeshes[0].cloth_paint[-1] = .25
    assert mesh_has_cloth_paint(mesh)
