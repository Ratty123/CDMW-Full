from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.ui.archive_browser.static_replacement_native_manifest import (
    apply_native_preview_core_material_manifest,
    load_native_preview_core_material_manifest_for_alignment,
)
from cdmw.ui.archive_browser.static_replacement_preview_cache import (
    cached_static_preview_geometry,
    model_has_preview_texture_keys,
    restore_static_preview_geometry_cache_payload,
    static_preview_geometry_cache_payload,
    static_preview_prepared_cache_key,
    store_static_preview_cache_entry,
)
from cdmw.ui.archive_browser.static_replacement_static_preview_state import (
    static_preview_prepared_cache_result,
    static_preview_refresh_route_state,
    static_preview_upload_elapsed_ms,
    static_preview_widget_mode_state,
    static_preview_widget_model_action,
)
from cdmw.ui.archive_browser.static_replacement_preview_textures import (
    accent_glow_preview_enabled,
    accent_glow_preview_intensity,
    add_preview_material_input,
    apply_manual_preview_texture_override_specs,
    apply_source_material_preview,
    apply_source_material_preview_for_model,
    apply_source_role_emissive_preview,
    apply_source_role_emissive_preview_for_model,
    clear_replacement_preview_texture_bindings,
    clear_source_role_emissive_preview,
    material_authority_preview_parameters,
    preview_glow_color_from_candidates,
    set_preview_texture_slot_path,
    source_preview_path,
    texture_set_for_mapping,
)


def test_source_preview_path_keeps_dds_path_for_native_loader() -> None:
    assert source_preview_path("C:/tmp/body.dds").endswith("body.dds")
    assert source_preview_path("C:/tmp/body.png").endswith("body.png")


def test_accent_glow_preview_intensity_clamps_profile_values() -> None:
    assert accent_glow_preview_intensity(SimpleNamespace(accent_glow_strength=0, accent_glow_intensity_max=8)) == 1.0
    assert accent_glow_preview_intensity(SimpleNamespace(accent_glow_strength=50, accent_glow_intensity_max=8)) == 4.0
    assert accent_glow_preview_intensity(SimpleNamespace(accent_glow_strength=1000, accent_glow_intensity_max=100)) == 20.0
    assert accent_glow_preview_intensity(SimpleNamespace(accent_glow_strength="bad")) == 1.0
    assert accent_glow_preview_enabled(SimpleNamespace(accent_glow_strength=1))
    assert not accent_glow_preview_enabled(SimpleNamespace(accent_glow_strength=0))


def test_material_authority_preview_parameters_clamps_numeric_values() -> None:
    params = material_authority_preview_parameters(
        SimpleNamespace(
            scratch_roughness=2,
            scratch_metallic=-1,
            shine_scalar=0.25,
            displacement_scale_multiplier="bad",
        ),
        enabled=True,
    )

    assert [(param.parameter_name, param.numeric_value, param.value) for param in params] == [
        ("_scratchRoughness", 1.0, "1.000000"),
        ("_scratchMetallic", 0.0, "0.000000"),
        ("_specularAmount", 0.25, "0.250000"),
    ]
    assert material_authority_preview_parameters(SimpleNamespace(scratch_roughness=1), enabled=False) == ()


def test_static_preview_prepared_cache_key_tracks_texture_and_highlight_state() -> None:
    small_plain_model = SimpleNamespace(face_count=12, summary="small", meshes=[SimpleNamespace()])
    assert not model_has_preview_texture_keys(small_plain_model)
    assert (
        static_preview_prepared_cache_key(
            small_plain_model,
            source_preview_cache_key="source",
            active_preview_mode="side_by_side",
            cache_suffix="static",
            selected_preview_indices=(),
            highlighted_source_indices=(),
            highlighted_original_indices=(),
            texture_override_preview_specs=(),
            material_authority_preview_signature="",
        )
        == ""
    )

    textured_model = SimpleNamespace(
        face_count=12,
        summary="textured",
        meshes=[SimpleNamespace(preview_material_texture_path="C:/tmp/body_mr.dds")],
    )
    assert model_has_preview_texture_keys(textured_model)
    key = static_preview_prepared_cache_key(
        textured_model,
        source_preview_cache_key="source",
        active_preview_mode="overlay",
        cache_suffix="main",
        selected_preview_indices=(2, 1),
        highlighted_source_indices=(7, 3),
        highlighted_original_indices=(4,),
        texture_override_preview_specs=(("Body", "base", "preview/base.dds", "base.dds", (2,), "C:/tmp/base.dds"),),
        material_authority_preview_signature="sig",
    )

    assert '"highlight_sources":[3,7]' in key
    assert '"material_authority_preview_signature":"sig"' in key
    assert '"texture_specs":[["Body","base","preview/base.dds","base.dds",[2]]]' in key

    high_face_model = SimpleNamespace(face_count=40_000, summary="dense", meshes=[SimpleNamespace()])
    assert static_preview_prepared_cache_key(
        high_face_model,
        source_preview_cache_key="source",
        active_preview_mode="side_by_side",
        cache_suffix="dense",
        selected_preview_indices=None,
        highlighted_source_indices=(),
        highlighted_original_indices=(),
        texture_override_preview_specs=(),
        material_authority_preview_signature="",
    )


def test_static_preview_geometry_cache_payload_copies_preview_index_maps() -> None:
    source_model = object()
    direct = {1: 10}
    overlay = {2: 20}
    submesh = {3: 30}

    payload = static_preview_geometry_cache_payload(
        source_model,
        mapped_preview=True,
        direct_source_preview_index_map=direct,
        source_overlay_preview_index_map=overlay,
        preview_submesh_index_map=submesh,
    )
    direct[1] = 99
    overlay[2] = 99
    submesh[3] = 99

    assert payload == (source_model, True, {1: 10}, {2: 20}, {3: 30})


def test_restore_static_preview_geometry_cache_payload_replaces_target_maps() -> None:
    direct = {9: 9}
    overlay = {8: 8}
    submesh = {7: 7}

    source_model, mapped_preview = restore_static_preview_geometry_cache_payload(
        ("model", False, {1: 10}, {2: 20}, {3: 30}),
        direct_source_preview_index_map=direct,
        source_overlay_preview_index_map=overlay,
        preview_submesh_index_map=submesh,
    )

    assert source_model == "model"
    assert mapped_preview is False
    assert direct == {1: 10}
    assert overlay == {2: 20}
    assert submesh == {3: 30}


def test_static_preview_cache_lookup_and_store_respect_live_edit_and_limit() -> None:
    geometry_cache = {"cached": "value"}
    assert cached_static_preview_geometry(geometry_cache, "cached", live_mesh_edit=True) is None
    assert cached_static_preview_geometry(geometry_cache, "cached", live_mesh_edit=False) == "value"

    paired_cache = {"prepared": "value"}
    limited_cache = {str(index): index for index in range(8)}
    stored = store_static_preview_cache_entry(
        limited_cache,
        "new",
        "payload",
        paired_cache_to_clear=paired_cache,
    )

    assert stored == "payload"
    assert limited_cache == {"new": "payload"}
    assert paired_cache == {}


def test_static_preview_refresh_route_state_tracks_direct_source_and_original_readiness() -> None:
    route = static_preview_refresh_route_state(
        active_preview_mode="replacement_only",
        mesh_edit_enabled=False,
        mesh_edit_tab_active=False,
        replacement_mesh_available=True,
        interactive_preview=False,
        complete_external_swap_enabled=True,
        needs_original_material_preview=False,
        preview_controls_ready=True,
        original_mesh_available=True,
    )

    assert route.mesh_edit_direct_source_preview is False
    assert route.replacement_only_direct_source_preview is True
    assert route.source_owned_direct_source_preview is True
    assert route.require_original_reference is True
    assert route.can_build_source_geometry is True

    mesh_edit_route = static_preview_refresh_route_state(
        active_preview_mode="side_by_side",
        mesh_edit_enabled=True,
        mesh_edit_tab_active=True,
        replacement_mesh_available=True,
        interactive_preview=True,
        complete_external_swap_enabled=True,
        needs_original_material_preview=False,
        preview_controls_ready=False,
        original_mesh_available=True,
    )

    assert mesh_edit_route.mesh_edit_direct_source_preview is True
    assert mesh_edit_route.replacement_only_direct_source_preview is False
    assert mesh_edit_route.source_owned_direct_source_preview is False
    assert mesh_edit_route.require_original_reference is False
    assert mesh_edit_route.can_build_source_geometry is False


def test_static_preview_widget_mode_and_model_actions_route_qt_work() -> None:
    assert static_preview_widget_mode_state("side_by_side").update_side_by_side is True
    assert static_preview_widget_mode_state("replacement_only").update_replacement_only is True
    assert static_preview_widget_mode_state("overlay").update_overlay is True

    live_action = static_preview_widget_model_action(live_mesh_edit=True, prepared_key="key")
    assert live_action.preserve_mesh_edit_cache is True
    assert live_action.use_prepared_cache is False
    assert live_action.cache_lookup_allowed is False

    cached_action = static_preview_widget_model_action(live_mesh_edit=False, prepared_key="key")
    assert cached_action.preserve_mesh_edit_cache is False
    assert cached_action.use_prepared_cache is True
    assert cached_action.cache_lookup_allowed is True
    assert cached_action.prepared_key == "key"

    plain_action = static_preview_widget_model_action(live_mesh_edit=False, prepared_key="")
    assert plain_action.use_prepared_cache is False


def test_static_preview_prepared_cache_result_reuses_or_prepares_model() -> None:
    calls: list[object] = []

    def prepare(model: object) -> tuple[object, object]:
        calls.append(model)
        return f"prepared:{model}", f"preview:{model}"

    cache: dict[str, object] = {}
    first = static_preview_prepared_cache_result(
        cache,
        "model",
        prepared_key="key",
        prepare_model_preview=prepare,
    )
    assert first.prepared_model == "prepared:model"
    assert first.prepared_preview == "preview:model"
    assert first.cache_hit is False
    assert first.prepare_elapsed_ms >= 0.0
    assert cache == {"key": ("prepared:model", "preview:model")}
    assert calls == ["model"]

    second = static_preview_prepared_cache_result(
        cache,
        "model",
        prepared_key="key",
        prepare_model_preview=prepare,
    )
    assert second.cache_hit is True
    assert second.prepare_elapsed_ms == 0.0
    assert calls == ["model"]


def test_static_preview_upload_elapsed_ms_reads_widget_last_uploads() -> None:
    assert static_preview_upload_elapsed_ms(()) == 0.0
    assert static_preview_upload_elapsed_ms(
        (
            SimpleNamespace(_last_gl_upload_ms=2.5),
            SimpleNamespace(_last_gl_upload_ms="bad"),
            SimpleNamespace(_last_gl_upload_ms=4),
        )
    ) == 4.0


def test_texture_set_for_mapping_matches_single_material_only() -> None:
    body_set = SimpleNamespace(material_name="Body")
    cape_set = SimpleNamespace(material_name="Cape")
    mesh = SimpleNamespace(submeshes=[object(), object()])
    texture_sets = {"body": body_set, "cape": cape_set}
    lookup = lambda index, _sets: body_set if index == 0 else cape_set

    assert texture_set_for_mapping(
        SimpleNamespace(source_submesh_indices=(0,)),
        texture_sets=texture_sets,
        replacement_mesh=mesh,
        texture_set_for_source_index=lookup,
    ) is body_set
    assert texture_set_for_mapping(
        SimpleNamespace(source_submesh_indices=(0, 1)),
        texture_sets=texture_sets,
        replacement_mesh=mesh,
        texture_set_for_source_index=lookup,
    ) is None


def test_clear_and_set_preview_texture_slot_path_updates_mesh_fields() -> None:
    mesh = SimpleNamespace(
        preview_texture_path="old",
        preview_texture_dds_path="old.dds",
        texture_name="old.dds",
        preview_material_texture_inputs=("input",),
        preview_material_texture_packed_channels=("r",),
    )

    clear_replacement_preview_texture_bindings(mesh)

    assert mesh.preview_texture_path == ""
    assert mesh.preview_texture_dds_path == ""
    assert mesh.texture_name == ""
    assert mesh.preview_material_texture_inputs == ()
    assert mesh.preview_material_texture_packed_channels == ()

    dds = Path("C:/tmp/body.dds")
    assert set_preview_texture_slot_path(
        mesh,
        path_attr="preview_texture_path",
        dds_attr="preview_texture_dds_path",
        name_attr="texture_name",
        source_path=dds,
    ) == str(dds)
    assert mesh.preview_texture_path == str(dds)
    assert mesh.preview_texture_dds_path == str(dds)
    assert mesh.texture_name == "body.dds"

    png = Path("C:/tmp/body.png")
    set_preview_texture_slot_path(
        mesh,
        path_attr="preview_texture_path",
        dds_attr="preview_texture_dds_path",
        name_attr="texture_name",
        source_path=png,
    )
    assert mesh.preview_texture_path == str(png)
    assert mesh.preview_texture_dds_path == ""
    assert mesh.texture_name == "body.png"


def test_add_preview_material_input_dedupes_and_prefers_pbr_over_legacy_orm() -> None:
    mesh = SimpleNamespace(material_name="Body", preview_material_texture_inputs=())
    pbr = Path("C:/tmp/body_mr.dds")

    add_preview_material_input(
        mesh,
        slot_kind="ao",
        source_path=pbr,
        semantic_type="material",
        semantic_subtype="orm",
        packed_channels=("ao", "roughness", "metallic"),
        material_name="Body",
    )
    add_preview_material_input(
        mesh,
        slot_kind="material",
        source_path=pbr,
        semantic_type="material",
        semantic_subtype="metallic_roughness",
        packed_channels=("roughness", "metallic"),
        parameter_name="_metallicRoughnessTexture",
        material_name="Body",
    )
    add_preview_material_input(
        mesh,
        slot_kind="material",
        source_path=pbr,
        semantic_type="material",
        semantic_subtype="metallic_roughness",
        packed_channels=("roughness", "metallic"),
        parameter_name="_metallicRoughnessTexture",
        material_name="Body",
    )

    inputs = tuple(mesh.preview_material_texture_inputs)
    assert len(inputs) == 1
    assert inputs[0].semantic_subtype == "metallic_roughness"
    assert inputs[0].source_dds_path == str(pbr)


def test_apply_source_material_preview_updates_slots_and_material_inputs() -> None:
    mesh = SimpleNamespace(
        material_name="Body",
        preview_texture_path="old",
        preview_material_texture_inputs=("stale",),
    )
    slots = {
        "base": SimpleNamespace(source_path=Path("C:/tmp/body_bc.dds")),
        "normal": SimpleNamespace(source_path=Path("C:/tmp/body_n.png")),
        "material": SimpleNamespace(source_path=Path("C:/tmp/body_mr.png")),
        "emissive": SimpleNamespace(source_path=Path("C:/tmp/body_e.dds")),
    }
    factor_param = PreviewMaterialParameterInput(
        parameter_kind="float",
        parameter_name="_baseFactor",
        value="0.500000",
        numeric_value=0.5,
    )

    apply_source_material_preview(
        mesh,
        SimpleNamespace(slots=slots),
        "Body",
        complete_external_swap_enabled=True,
        basic_controls_profile_enabled=True,
        material_authority_profile=SimpleNamespace(scratch_roughness=0.25, accent_glow_strength=50),
        texture_set_factor_parameters=lambda _texture_set: (factor_param,),
        material_authority_preview_texture_slots=lambda texture_set, *_args, **_kwargs: texture_set.slots,
        replacement_texture_slot_preview_semantics=lambda _slot, *, source_path: ("", "", (), ""),
        resolve_model_texture_semantic_details=lambda _path: ("material", "orm", "auto", ("ao", "roughness", "metallic")),
        is_gltf_metallic_roughness_path=lambda path: path.name == "body_mr.png",
        infer_model_preview_normal_strength=lambda **_kwargs: 0.8,
        accent_glow_preview_intensity=4.0,
    )

    assert mesh.preview_texture_path == str(Path("C:/tmp/body_bc.dds"))
    assert mesh.preview_texture_dds_path == str(Path("C:/tmp/body_bc.dds"))
    assert mesh.preview_normal_texture_path == str(Path("C:/tmp/body_n.png"))
    assert mesh.preview_normal_texture_dds_path == ""
    assert mesh.preview_normal_texture_strength == 0.8
    assert mesh.preview_material_texture_subtype == "metallic_roughness"
    assert mesh.preview_material_texture_packed_channels == ("roughness", "metallic")
    assert mesh.preview_sidecar_shader_family == "SkinnedMeshEmissive_Ver2"

    inputs = tuple(mesh.preview_material_texture_inputs)
    assert [item.slot_kind for item in inputs] == ["base", "normal", "material", "emissive"]
    assert inputs[2].parameter_name == "_metallicRoughnessTexture"
    assert inputs[2].material_parameters == (
        factor_param,
        PreviewMaterialParameterInput(
            parameter_kind="float",
            parameter_name="_scratchRoughness",
            value="0.250000",
            numeric_value=0.25,
        ),
    )
    assert inputs[3].material_parameters[0].numeric_value == 4.0


def test_apply_source_material_preview_for_model_uses_direct_source_map() -> None:
    preview_model = SimpleNamespace(meshes=[SimpleNamespace(material_name="A"), SimpleNamespace(material_name="B")])
    texture_set = SimpleNamespace(slots={"base": SimpleNamespace(source_path=Path("C:/tmp/source4.dds"))})

    apply_source_material_preview_for_model(
        preview_model,
        use_direct_source_preview=True,
        direct_source_preview_index_map={4: 1},
        mapped_preview=False,
        source_overlay_preview_index_map={},
        current_mappings=(),
        texture_sets={"source4": texture_set},
        material_authority_profile=None,
        complete_external_swap_enabled=False,
        basic_controls_profile_enabled=False,
        texture_set_for_source_index=lambda _index, _sets: texture_set,
        texture_set_for_mapping=lambda _mapping: None,
        source_display_name=lambda index: f"source {index}",
        preview_target_mesh_indices=lambda *_args: (),
        texture_set_factor_parameters=lambda _texture_set: (),
        material_authority_preview_texture_slots=lambda texture_set_obj, **_kwargs: texture_set_obj.slots,
        replacement_texture_slot_preview_semantics=lambda _slot, *, source_path: ("", "", (), ""),
        resolve_model_texture_semantic_details=lambda _path: ("material", "orm", "auto", ()),
        is_gltf_metallic_roughness_path=lambda _path: False,
        infer_model_preview_normal_strength=lambda **_kwargs: 1.0,
        accent_glow_preview_intensity=1.0,
    )

    assert not hasattr(preview_model.meshes[0], "preview_texture_path")
    assert preview_model.meshes[1].preview_texture_path == str(Path("C:/tmp/source4.dds"))
    assert preview_model.meshes[1].preview_material_texture_inputs[0].material_name == "source 4"


def test_apply_source_material_preview_for_model_routes_mapped_targets() -> None:
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(material_name="A"),
            SimpleNamespace(material_name="B"),
            SimpleNamespace(material_name="C"),
        ]
    )
    overlay_set = SimpleNamespace(slots={"base": SimpleNamespace(source_path=Path("C:/tmp/overlay.dds"))})
    mapped_set = SimpleNamespace(slots={"base": SimpleNamespace(source_path=Path("C:/tmp/mapped.dds"))})
    mapping = SimpleNamespace(target_submesh_name="TargetBody", source_submesh_indices=(2,))

    apply_source_material_preview_for_model(
        preview_model,
        use_direct_source_preview=False,
        direct_source_preview_index_map={},
        mapped_preview=True,
        source_overlay_preview_index_map={1: 0},
        current_mappings=(mapping,),
        texture_sets={"overlay": overlay_set, "mapped": mapped_set},
        material_authority_profile=None,
        complete_external_swap_enabled=False,
        basic_controls_profile_enabled=False,
        texture_set_for_source_index=lambda _index, _sets: overlay_set,
        texture_set_for_mapping=lambda _mapping: mapped_set,
        source_display_name=lambda index: f"source {index}",
        preview_target_mesh_indices=lambda _model, _target, _sources, _mapped, _mappings: (2,),
        texture_set_factor_parameters=lambda _texture_set: (),
        material_authority_preview_texture_slots=lambda texture_set_obj, **_kwargs: texture_set_obj.slots,
        replacement_texture_slot_preview_semantics=lambda _slot, *, source_path: ("", "", (), ""),
        resolve_model_texture_semantic_details=lambda _path: ("material", "orm", "auto", ()),
        is_gltf_metallic_roughness_path=lambda _path: False,
        infer_model_preview_normal_strength=lambda **_kwargs: 1.0,
        accent_glow_preview_intensity=1.0,
    )

    assert preview_model.meshes[0].preview_texture_path == str(Path("C:/tmp/overlay.dds"))
    assert not hasattr(preview_model.meshes[1], "preview_texture_path")
    assert preview_model.meshes[2].preview_texture_path == str(Path("C:/tmp/mapped.dds"))
    assert preview_model.meshes[2].preview_material_texture_inputs[0].material_name == "TargetBody"


def test_preview_glow_color_from_candidates_normalizes_rgb_candidates() -> None:
    assert preview_glow_color_from_candidates(((), (0, 128, 255), ())) == (
        "#0080FFFF",
        (0.0, 128.0 / 255.0, 1.0),
    )
    assert preview_glow_color_from_candidates(((), (0, 0, 0), ())) == (
        "#FFFFFFFF",
        (1.0, 1.0, 1.0),
    )


def test_source_role_emissive_preview_clears_and_applies_role_override() -> None:
    stale = PreviewMaterialTextureInput(
        slot_kind="emissive",
        confidence="source-role-preview",
    )
    mesh = SimpleNamespace(
        material_name="Body",
        preview_color=(0.25, 0.5, 1.0),
        preview_material_texture_inputs=(stale,),
        preview_native_material_overrides={
            "_source_role_emissive_preview": True,
            "emissive_intensity": 4.0,
            "emissive_color": "#FFFFFFFF",
            "keep": True,
        },
    )

    clear_source_role_emissive_preview(mesh)

    assert mesh.preview_material_texture_inputs == ()
    assert mesh.preview_native_material_overrides == {"keep": True}

    apply_source_role_emissive_preview(
        mesh,
        source_index=2,
        target_name="Body",
        texture_set=SimpleNamespace(accent_glow_color_rgb=(0, 128, 255)),
        adjustment=SimpleNamespace(enabled=True, material_role="glow", emissive_color_rgb=()),
        profile=SimpleNamespace(accent_glow_strength=50, accent_glow_intensity_max=8),
        source_label="2: Glow",
    )

    role_input = mesh.preview_material_texture_inputs[0]
    assert role_input.confidence == "source-role-preview"
    assert role_input.part_name == "2: Glow"
    assert mesh.preview_sidecar_shader_family == "SkinnedMeshEmissive_Ver2"
    assert mesh.preview_native_material_overrides["_source_role_emissive_preview"] is True
    assert mesh.preview_native_material_overrides["emissive_intensity"] == 4.0
    assert mesh.preview_native_material_overrides["emissive_color"] == "#0080FFFF"


def test_apply_source_role_emissive_preview_for_model_uses_direct_source_map() -> None:
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(material_name="A", preview_color=(1.0, 1.0, 1.0), preview_material_texture_inputs=()),
            SimpleNamespace(material_name="B", preview_color=(0.0, 1.0, 0.0), preview_material_texture_inputs=()),
        ]
    )
    texture_set = SimpleNamespace(accent_glow_color_rgb=(255, 0, 0))

    apply_source_role_emissive_preview_for_model(
        preview_model,
        use_direct_source_preview=True,
        direct_source_preview_index_map={4: 1},
        mapped_preview=False,
        source_overlay_preview_index_map={},
        current_mappings=(),
        texture_sets={"body": texture_set},
        source_part_adjustments={4: SimpleNamespace(enabled=True, material_role="glow", emissive_color_rgb=())},
        profile=SimpleNamespace(accent_glow_strength=50, accent_glow_intensity_max=6),
        texture_set_for_source_index=lambda _index, _sets: texture_set,
        source_display_name=lambda index: f"source {index}",
        preview_target_mesh_indices=lambda *_args: (),
    )

    assert tuple(preview_model.meshes[0].preview_material_texture_inputs) == ()
    role_input = preview_model.meshes[1].preview_material_texture_inputs[0]
    assert role_input.part_name == "source 4"
    assert role_input.material_name == "source 4"
    assert preview_model.meshes[1].preview_native_material_overrides["emissive_color"] == "#FF0000FF"


def test_apply_source_role_emissive_preview_for_model_routes_mapped_glow_sources() -> None:
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(material_name="A", preview_color=(1.0, 1.0, 1.0), preview_material_texture_inputs=()),
            SimpleNamespace(material_name="B", preview_color=(1.0, 1.0, 1.0), preview_material_texture_inputs=()),
            SimpleNamespace(material_name="C", preview_color=(1.0, 1.0, 1.0), preview_material_texture_inputs=()),
        ]
    )
    mapping = SimpleNamespace(target_submesh_name="TargetGlow", source_submesh_indices=(2, 5))
    texture_set = SimpleNamespace(base_color_factor=(0, 64, 255))

    apply_source_role_emissive_preview_for_model(
        preview_model,
        use_direct_source_preview=False,
        direct_source_preview_index_map={},
        mapped_preview=True,
        source_overlay_preview_index_map={1: 0},
        current_mappings=(mapping,),
        texture_sets={"body": texture_set},
        source_part_adjustments={
            1: SimpleNamespace(enabled=True, material_role="glow", emissive_color_rgb=(0, 255, 0)),
            5: SimpleNamespace(enabled=True, material_role="glow", emissive_color_rgb=()),
        },
        profile=SimpleNamespace(accent_glow_strength=100, accent_glow_intensity_max=3),
        texture_set_for_source_index=lambda _index, _sets: texture_set,
        source_display_name=lambda index: f"source {index}",
        preview_target_mesh_indices=lambda _model, _target, _sources, _mapped, _mappings: (2,),
    )

    assert preview_model.meshes[0].preview_material_texture_inputs[0].part_name == "source 1"
    assert preview_model.meshes[0].preview_native_material_overrides["emissive_color"] == "#00FF00FF"
    assert tuple(preview_model.meshes[1].preview_material_texture_inputs) == ()
    assert preview_model.meshes[2].preview_material_texture_inputs[0].material_name == "TargetGlow"
    assert preview_model.meshes[2].preview_material_texture_inputs[0].part_name == "source 5"
    assert preview_model.meshes[2].preview_native_material_overrides["emissive_color"] == "#0040FFFF"


def test_apply_manual_preview_texture_override_specs_updates_slots_and_inputs() -> None:
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
            SimpleNamespace(),
        ]
    )
    material_param = material_authority_preview_parameters(
        SimpleNamespace(scratch_roughness=0.5),
        enabled=True,
    )[0]

    apply_manual_preview_texture_override_specs(
        preview_model,
        (
            ("Body", "base", "preview/base.dds", "base.dds", (0,), "C:/tmp/base.dds"),
            ("Body", "normal", "preview/normal.png", "normal.png", (1,), "C:/tmp/normal.png"),
            ("Body", "material", "preview/body_mr.png", "body_mr.png", (2,), "C:/tmp/body_mr.png"),
            ("Glow", "emissive", "preview/glow.dds", "glow.dds", (3,), "C:/tmp/glow.dds"),
        ),
        mapped_preview=False,
        current_mappings=(),
        preview_target_mesh_indices=lambda _model, _target, sources, _mapped, _mappings: tuple(sources),
        resolve_model_texture_semantic_details=lambda _path: ("material", "orm", "auto", ("ao", "roughness", "metallic")),
        replacement_texture_slot_preview_semantics=lambda _slot, *, source_path: ("", "", (), ""),
        is_gltf_metallic_roughness_path=lambda path: path.name == "body_mr.png",
        infer_model_preview_normal_strength=lambda **_kwargs: 0.75,
        material_authority_preview_parameters=(material_param,),
        accent_glow_preview_intensity=6.0,
    )

    base_mesh, normal_mesh, material_mesh, emissive_mesh = preview_model.meshes
    assert base_mesh.preview_texture_path == "preview/base.dds"
    assert base_mesh.preview_texture_dds_path == str(Path("C:/tmp/base.dds"))
    assert base_mesh.texture_name == "base.dds"
    assert base_mesh.preview_texture_flip_vertical is False
    assert normal_mesh.preview_normal_texture_path == "preview/normal.png"
    assert normal_mesh.preview_normal_texture_dds_path == ""
    assert normal_mesh.preview_normal_texture_strength == 0.75
    assert material_mesh.preview_material_texture_subtype == "metallic_roughness"
    assert material_mesh.preview_material_texture_packed_channels == ("roughness", "metallic")
    assert material_mesh.preview_material_texture_inputs[0].parameter_name == "_metallicRoughnessTexture"
    assert material_mesh.preview_material_texture_inputs[0].material_parameters == (material_param,)
    assert emissive_mesh.preview_sidecar_shader_family == "SkinnedMeshEmissive_Ver2"
    assert emissive_mesh.preview_material_texture_inputs[0].semantic_type == "emissive"
    assert emissive_mesh.preview_material_texture_inputs[0].material_parameters[0].numeric_value == 6.0


def test_apply_native_preview_core_material_manifest_applies_slots_inputs_and_overrides(tmp_path: Path) -> None:
    mesh = ModelPreviewMesh(
        material_name="Original",
        preview_texture_image=object(),
        preview_normal_texture_image=object(),
        preview_material_texture_image=object(),
        preview_height_texture_image=object(),
    )
    preview_model = ModelPreviewData(meshes=[mesh])
    base_path = str(tmp_path / "base.dds")
    normal_path = str(tmp_path / "normal.dds")
    material_path = str(tmp_path / "material.dds")
    height_path = str(tmp_path / "height.dds")
    manifest = {
        "batches": [
            {"editor_identity": {"prefab_component": True, "source_submesh_index": 0}},
            {"editor_identity": {"source_component_index": 1, "source_submesh_index": 0}},
            {
                "editor_identity": {"source_component_index": 0, "source_submesh_index": 0},
                "material_name": "Body",
                "dds_textures": {
                    "base": {"source_path": base_path},
                    "normal": {"source_path": normal_path, "archive_path": "textures/body_n.dds"},
                    "material": {
                        "source_path": material_path,
                        "texture_name": "body_mr.dds",
                    },
                    "height": {"source_path": height_path},
                    "material_inputs": [
                        {
                            "slot_kind": "material",
                            "source_path": material_path,
                            "texture_name": "body_mr.dds",
                        }
                    ],
                },
                "roughness": 0.42,
                "material_layers": [{"name": "paint"}],
            },
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def convert_descriptor(descriptor: object, **kwargs: object) -> PreviewMaterialTextureInput | None:
        if not isinstance(descriptor, dict):
            return None
        return PreviewMaterialTextureInput(
            slot_kind=str(descriptor.get("slot_kind") or kwargs.get("fallback_slot") or ""),
            source_texture_path=str(descriptor.get("source_path", "")),
            texture_name=str(descriptor.get("texture_name", "")),
            material_name=str(kwargs.get("part_name", "")),
        )

    applied = apply_native_preview_core_material_manifest(
        preview_model,
        tmp_path,
        native_manifest_input_from_descriptor=convert_descriptor,
    )

    assert applied == 1
    assert mesh.preview_texture_path == base_path
    assert mesh.preview_texture_dds_path == base_path
    assert mesh.preview_normal_texture_path == normal_path
    assert mesh.preview_normal_texture_dds_path == normal_path
    assert mesh.preview_normal_texture_name == "body_n.dds"
    assert mesh.preview_material_texture_path == material_path
    assert mesh.preview_material_texture_dds_path == material_path
    assert mesh.preview_material_texture_name == "body_mr.dds"
    assert mesh.preview_height_texture_path == height_path
    assert mesh.preview_height_texture_dds_path == height_path
    assert mesh.preview_height_texture_name == "height.dds"
    assert mesh.preview_material_texture_inputs == (
        PreviewMaterialTextureInput(
            slot_kind="material",
            source_texture_path=material_path,
            texture_name="body_mr.dds",
            material_name="Body",
        ),
    )
    assert mesh.preview_native_material_overrides == {
        "material_layers": [{"name": "paint"}],
        "roughness": 0.42,
    }
    assert mesh.preview_texture_approximation_note == "Material preview uses native C++ Archive Preview material manifest."
    assert mesh.preview_texture_image is None
    assert mesh.preview_normal_texture_image is None
    assert mesh.preview_material_texture_image is None
    assert mesh.preview_height_texture_image is None


def test_apply_native_preview_core_material_manifest_falls_back_to_slot_inputs(tmp_path: Path) -> None:
    mesh = ModelPreviewMesh(material_name="Body")
    preview_model = ModelPreviewData(meshes=[mesh])
    base_path = str(tmp_path / "base.dds")
    manifest = {
        "batches": [
            {
                "index": 0,
                "dds_textures": {"base": {"source_path": base_path}},
            }
        ]
    }
    (tmp_path / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")

    def convert_descriptor(descriptor: object, **kwargs: object) -> PreviewMaterialTextureInput | None:
        if not isinstance(descriptor, dict):
            return None
        return PreviewMaterialTextureInput(
            slot_kind=str(kwargs.get("fallback_slot") or ""),
            source_texture_path=str(descriptor.get("source_path", "")),
            material_name=str(kwargs.get("part_name", "")),
        )

    assert (
        apply_native_preview_core_material_manifest(
            preview_model,
            tmp_path,
            native_manifest_input_from_descriptor=convert_descriptor,
        )
        == 1
    )
    assert mesh.preview_material_texture_inputs == (
        PreviewMaterialTextureInput(slot_kind="base", source_texture_path=base_path, material_name="Body"),
    )


def test_apply_native_preview_core_material_manifest_ignores_invalid_manifest(tmp_path: Path) -> None:
    assert (
        apply_native_preview_core_material_manifest(
            object(),
            tmp_path,
            native_manifest_input_from_descriptor=lambda *_args, **_kwargs: None,
        )
        == 0
    )
    preview_model = ModelPreviewData(meshes=[ModelPreviewMesh()])
    (tmp_path / "manifest.json").write_text("{not-json", encoding="utf-8")

    assert (
        apply_native_preview_core_material_manifest(
            preview_model,
            tmp_path,
            native_manifest_input_from_descriptor=lambda *_args, **_kwargs: None,
        )
        == 0
    )


def test_load_native_preview_core_material_manifest_records_success(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    packages: list[object] = []

    def run_job(entry: object, **kwargs: object) -> object:
        assert kwargs["cache_root"] == tmp_path / "cache"
        assert kwargs["package_root"] == tmp_path / "package-root"
        return SimpleNamespace(succeeded=True, package_path=tmp_path / "package")

    applied = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".pam", path="models/body.pam"),
        package_root_text=str(tmp_path / "package-root"),
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path / "cache",
        render_settings=SimpleNamespace(),
        companion_entry=SimpleNamespace(path="companion"),
        run_preview_job=run_job,
        clear_native_package_path=lambda: packages.append("cleared"),
        set_native_package_path=packages.append,
        apply_manifest=lambda _model, package_path: 2 if package_path == tmp_path / "package" else 0,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )

    assert applied == 2
    assert packages == [tmp_path / "package"]
    assert events == [
        (
            "mesh_alignment_native_material_manifest_applied",
            {
                "path": "models/body.pam",
                "dialog_title": "Dialog",
                "batch_count": 2,
                "package_path": tmp_path / "package",
            },
        )
    ]


def test_load_native_preview_core_material_manifest_records_unavailable_and_failures(tmp_path: Path) -> None:
    events: list[tuple[str, dict[str, object]]] = []
    clears: list[str] = []

    skipped = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".txt", path="notes.txt"),
        package_root_text="",
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path,
        render_settings=SimpleNamespace(),
        companion_entry=None,
        run_preview_job=lambda *_args, **_kwargs: None,
        clear_native_package_path=lambda: clears.append("cleared"),
        set_native_package_path=lambda _path: None,
        apply_manifest=lambda *_args: 1,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )
    assert skipped == 0
    assert events == []

    unavailable = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".pam", path="models/body.pam"),
        package_root_text="",
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path,
        render_settings=SimpleNamespace(),
        companion_entry=None,
        run_preview_job=lambda *_args, **_kwargs: SimpleNamespace(
            succeeded=False,
            status="fallback",
            fallback_reason="unsupported",
        ),
        clear_native_package_path=lambda: clears.append("cleared"),
        set_native_package_path=lambda _path: None,
        apply_manifest=lambda *_args: 1,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )
    assert unavailable == 0
    assert clears == ["cleared"]
    assert events[-1][0] == "mesh_alignment_native_material_manifest_unavailable"
    assert events[-1][1]["reason"] == "unsupported"

    failed = load_native_preview_core_material_manifest_for_alignment(
        SimpleNamespace(),
        entry=SimpleNamespace(extension=".pam", path="models/body.pam"),
        package_root_text="",
        active=True,
        model_extensions=(".pam",),
        cache_root=tmp_path,
        render_settings=SimpleNamespace(),
        companion_entry=None,
        run_preview_job=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("boom")),
        clear_native_package_path=lambda: None,
        set_native_package_path=lambda _path: None,
        apply_manifest=lambda *_args: 1,
        record_runtime_event=lambda event, **fields: events.append((event, fields)),
        dialog_title="Dialog",
    )
    assert failed == 0
    assert events[-1][0] == "mesh_alignment_native_material_manifest_failed"
    assert events[-1][1]["message"] == "boom"
