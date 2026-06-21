from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser import static_replacement_donor_material_state as donor_state_module
from cdmw.ui.archive_browser.static_replacement_donor_material_state import (
    donor_anchor_texture_paths,
    donor_bindings_from_sidecar_profiles,
    donor_material_plan_build_state,
    donor_material_plan_tree_size_state,
    donor_material_status_text,
    donor_mesh_picker_candidates,
    donor_part_rows,
    donor_texture_binding_display_state,
    selected_donor_bindings_for_plan,
)


class _Entry:
    def __init__(self, path: str, extension: str) -> None:
        self.path = path
        self.extension = extension


def test_donor_material_plan_tree_size_state_preserves_compact_and_expanded_heights() -> None:
    empty = donor_material_plan_tree_size_state(0)
    assert empty.has_rows is False
    assert empty.group_max_height == 126
    assert empty.tree_max_height == 92

    populated = donor_material_plan_tree_size_state("2")
    assert populated.has_rows is True
    assert populated.group_max_height == 190
    assert populated.tree_max_height == 140


def test_donor_mesh_picker_candidates_filters_current_entry_and_non_mesh_entries() -> None:
    current = _Entry("current.pac", ".pac")
    donor = _Entry("donor.pac", ".pac")
    sidecar = _Entry("donor.pac_xml", ".pac_xml")
    foreign = object()

    assert donor_mesh_picker_candidates(
        (current, donor, sidecar, foreign),
        current,
        same_entry=lambda candidate, entry: candidate is entry,
        mesh_extensions={".pac"},
        archive_entry_type=_Entry,
    ) == (donor,)


def test_donor_bindings_from_sidecar_profiles_builds_fallback_texture_and_empty_bindings() -> None:
    original_parser = donor_state_module.parse_material_sidecar_profile

    def fake_parser(_text: str, *, sidecar_path: str = "") -> object:
        return SimpleNamespace(
            sidecar_kind="pac_xml",
            linked_mesh_path="character/model/donor.pac",
            materials=(
                SimpleNamespace(
                    part_name="Body",
                    material_name="BodyMat",
                    shader_family="Uber",
                    texture_parameters=(
                        SimpleNamespace(parameter_name="_base", texture_path="character\\texture\\body.dds"),
                    ),
                ),
                SimpleNamespace(
                    part_name="Glow",
                    material_name="GlowMat",
                    shader_family="Emissive",
                    texture_parameters=(),
                ),
            ),
        )

    donor_state_module.parse_material_sidecar_profile = fake_parser
    try:
        bindings = donor_bindings_from_sidecar_profiles({"donor.pac_xml": "<xml />"})
    finally:
        donor_state_module.parse_material_sidecar_profile = original_parser

    assert len(bindings) == 2
    assert bindings[0].sidecar_path == "donor.pac_xml"
    assert bindings[0].texture_path == "character/texture/body.dds"
    assert bindings[1].part_name == "Glow"
    assert bindings[1].texture_path == ""


def test_donor_part_rows_group_by_part_and_mark_emissive_sources() -> None:
    base = SimpleNamespace(part_name="Body", shader_family="Uber", parameter_name="_base", texture_path="body.dds")
    glow = SimpleNamespace(part_name="Body", shader_family="Uber", parameter_name="_emissive", texture_path="glow.dds")
    cape = SimpleNamespace(submesh_name="Cape", material_name="CapeMat", shader_family="", parameter_name="", texture_path="")

    rows = donor_part_rows((base, glow, cape))

    assert rows[0]["part_name"] == "Body"
    assert rows[0]["bindings"] == [base, glow]
    assert rows[0]["emissive"] is True
    assert rows[1]["part_name"] == "Cape"
    assert rows[1]["bindings"] == [cape]


def test_donor_texture_binding_display_state_normalizes_texture_and_emissive_status() -> None:
    binding = SimpleNamespace(
        shader_family="",
        parameter_name="_emissiveTexture",
        texture_path="character\\texture\\eye_emit.dds",
    )

    state = donor_texture_binding_display_state(binding)

    assert state.texture_path == "character/texture/eye_emit.dds"
    assert state.parameter_name == "_emissiveTexture"
    assert state.slot_label
    assert state.state == "emissive/glow"


def test_selected_donor_bindings_for_plan_prefers_selected_texture_bindings() -> None:
    part_binding = SimpleNamespace(name="part")
    texture_binding = SimpleNamespace(name="texture")

    assert selected_donor_bindings_for_plan((texture_binding,), (part_binding,)) == (texture_binding,)
    assert selected_donor_bindings_for_plan((), (part_binding,)) == (part_binding,)


def test_donor_anchor_texture_paths_match_target_material() -> None:
    body = SimpleNamespace(part_name="Body", texture_path="body.dds")
    cape = SimpleNamespace(submesh_name="Cape", texture_path="cape.dds")

    assert donor_anchor_texture_paths((body, cape), "body") == ("body.dds",)


def test_donor_material_plan_build_state_routes_empty_unreadable_and_ready_plan() -> None:
    binding = SimpleNamespace(
        sidecar_path="character\\model\\donor.pac_xml",
        sidecar_kind="pac_xml",
        part_name="Body",
        submesh_name="BodySubmesh",
        material_name="BodyMat",
        shader_family="Uber",
        parameter_name="_base",
        texture_path="character\\texture\\body.dds",
    )
    anchor = SimpleNamespace(part_name="Target", texture_path="target.dds")

    empty = donor_material_plan_build_state(
        (),
        {},
        target_material_name="Target",
        patch_mode="donor_textures",
        sidecar_bindings_for_advanced=(),
    )
    assert empty.message_key == "select_binding"
    assert empty.plan is None

    unreadable = donor_material_plan_build_state(
        (binding,),
        {},
        target_material_name="Target",
        patch_mode="donor_textures",
        sidecar_bindings_for_advanced=(),
    )
    assert unreadable.message_key == "unreadable_sidecar"
    assert unreadable.plan is None
    assert unreadable.donor_part_name == "Body"

    ready = donor_material_plan_build_state(
        (binding,),
        {"character/model/donor.pac_xml": "<sidecar />"},
        target_material_name="Target",
        patch_mode="authoritative_recipe",
        sidecar_bindings_for_advanced=(anchor,),
    )

    assert ready.message_key == ""
    assert ready.plan is not None
    assert ready.plan.target_material_name == "Target"
    assert ready.plan.donor_sidecar_path == "character/model/donor.pac_xml"
    assert ready.plan.donor_material_name == "Body"
    assert ready.plan.donor_submesh_name == "BodySubmesh"
    assert ready.plan.patch_mode == "authoritative_recipe"
    assert ready.plan.target_anchor_texture_paths == ("target.dds",)
    assert ready.plan.donor_anchor_texture_paths == ["character/texture/body.dds"]
    assert ready.plan.texture_bindings[0].texture_path == "character/texture/body.dds"


def test_donor_material_status_text_preserves_profile_fallback_copy() -> None:
    control_text = {
        "profile_fallback_status": "profile fallback",
        "default_status": "default route",
    }

    assert donor_material_status_text(control_text, donor_bindings_from_profile=True) == "profile fallback"
    assert donor_material_status_text(control_text, donor_bindings_from_profile=False) == "default route"
