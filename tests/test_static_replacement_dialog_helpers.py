from __future__ import annotations

from types import SimpleNamespace
from pathlib import Path

from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.ui.archive_browser.static_replacement_preview_limits import (
    adaptive_alignment_preview_face_limit,
    alignment_preview_background_source_face_limit_for_total,
    alignment_preview_selected_source_face_limit_for_total,
    alignment_preview_source_face_limit_for_counts,
)
from cdmw.ui.archive_browser.static_replacement_texture_matching import (
    best_source_for_slot,
    binding_matches_target,
    part_specific_tokens,
    source_texture_evidence_by_local_path,
    texture_file_lookup_maps,
)
from cdmw.ui.archive_browser.static_replacement_dialog_helpers import (
    is_gltf_metallic_roughness_path,
    mapping_status_summary_badge,
    mesh_center_for_ui,
    model_bounds_x,
    rough_control_value_from_settings,
    tag_alignment_d3d11_workspace_model,
    texture_set_factor_parameters,
    translated_preview_model,
)


def test_mapping_status_summary_badge_escapes_label_and_value() -> None:
    html = mapping_status_summary_badge("A<B", "x&y", "#123456")

    assert "A&lt;B" in html
    assert "x&amp;y" in html
    assert "border:1px solid #123456" in html
    assert mapping_status_summary_badge("Empty", "", "#abcdef").count("> -</span>") == 1


def test_mesh_center_for_ui_uses_vertex_bounds_midpoint() -> None:
    mesh = SimpleNamespace(
        submeshes=(
            SimpleNamespace(vertices=((-2.0, 1.0, 4.0), (6.0, 3.0, -2.0))),
            SimpleNamespace(vertices=((4.0, -5.0, 10.0),)),
        )
    )

    assert mesh_center_for_ui(mesh) == (2.0, -1.0, 4.0)


def test_mesh_center_for_ui_defaults_when_mesh_has_no_vertices() -> None:
    assert mesh_center_for_ui(SimpleNamespace(submeshes=())) == (0.0, 0.0, 0.0)


def test_model_bounds_x_uses_valid_position_x_values() -> None:
    model = SimpleNamespace(
        meshes=(
            SimpleNamespace(positions=((-3.5, 0.0, 0.0), (2.0, 1.0, 1.0), ("bad", 0.0, 0.0))),
            SimpleNamespace(positions=((7.25, 0.0, 0.0), ())),
        )
    )

    assert model_bounds_x(model) == (-3.5, 7.25)


def test_model_bounds_x_defaults_when_no_positions_exist() -> None:
    assert model_bounds_x(SimpleNamespace(meshes=())) == (-0.5, 0.5)


def test_translated_preview_model_clones_and_offsets_x_positions() -> None:
    model = ModelPreviewData(
        meshes=[
            ModelPreviewMesh(
                positions=[(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)],
                indices=[0, 1, 0],
            )
        ]
    )

    translated = translated_preview_model(
        model,
        2.5,
        clone_model=lambda source: ModelPreviewData(
            meshes=[
                ModelPreviewMesh(
                    positions=list(source.meshes[0].positions),
                    indices=list(source.meshes[0].indices),
                )
            ]
        ),
    )

    assert isinstance(translated, ModelPreviewData)
    assert translated is not model
    assert translated.meshes[0].positions == [(3.5, 2.0, 3.0), (6.5, 5.0, 6.0)]
    assert model.meshes[0].positions == [(1.0, 2.0, 3.0), (4.0, 5.0, 6.0)]


def test_tag_alignment_d3d11_workspace_model_marks_role_and_locks_original() -> None:
    model = ModelPreviewData(
        meshes=[
            ModelPreviewMesh(
                preview_role="old",
                source_vertex_indices=[1, 2],
                source_face_indices=[3],
            )
        ]
    )

    tagged = tag_alignment_d3d11_workspace_model(
        model,
        "original_reference",
        editable=False,
        clone_model=lambda source: ModelPreviewData(
            meshes=[
                ModelPreviewMesh(
                    preview_role=source.meshes[0].preview_role,
                    source_vertex_indices=list(source.meshes[0].source_vertex_indices),
                    source_face_indices=list(source.meshes[0].source_face_indices),
                )
            ]
        ),
    )

    assert isinstance(tagged, ModelPreviewData)
    assert tagged.meshes[0].preview_role == "original_reference"
    assert tagged.meshes[0].source_vertex_indices == []
    assert tagged.meshes[0].source_face_indices == []
    assert model.meshes[0].source_vertex_indices == [1, 2]


def test_rough_control_value_from_settings_clamps_shininess_range() -> None:
    assert rough_control_value_from_settings(SimpleNamespace(shininess_max=32.0)) == 0.0
    assert rough_control_value_from_settings(SimpleNamespace(shininess_max=144.0)) == 0.5
    assert rough_control_value_from_settings(SimpleNamespace(shininess_max=999.0)) == 1.0
    assert rough_control_value_from_settings(SimpleNamespace(shininess_max="bad")) == 0.25


def test_is_gltf_metallic_roughness_path_matches_common_export_names() -> None:
    assert is_gltf_metallic_roughness_path(Path("Helmet_MetallicRoughness.png"))
    assert is_gltf_metallic_roughness_path(Path("helmet-metal_rough.dds"))
    assert is_gltf_metallic_roughness_path(Path("helmet_roughness_metallic.tga"))
    assert not is_gltf_metallic_roughness_path(Path("helmet_roughness.png"))


def test_part_specific_tokens_groups_character_parts_and_body_fallback() -> None:
    assert part_specific_tokens("left hand glove") == {"hand"}
    assert part_specific_tokens("face eye mouth") == {"head"}
    assert part_specific_tokens("long hair beard") == {"hair"}
    assert part_specific_tokens("leg boot") == {"foot"}
    assert part_specific_tokens("body skin torso") == {"body"}
    assert part_specific_tokens("hand body") == {"hand"}


def test_binding_matches_target_uses_names_then_important_texture_tokens() -> None:
    assert binding_matches_target(SimpleNamespace(submesh_name="Helmet_A", texture_path=""), "helmet")
    assert binding_matches_target(SimpleNamespace(submesh_name="", texture_path="textures/skin_body_d.dds"), "body")
    assert binding_matches_target(SimpleNamespace(submesh_name="hair_material", texture_path=""), "hair")
    assert not binding_matches_target(SimpleNamespace(submesh_name="helmet", texture_path="helmet.dds"), "boots")


def test_source_texture_evidence_by_local_path_groups_valid_mapping_rows() -> None:
    rows = [
        {"local_path": "Textures/Base.dds", "archive_path": "game/base.dds"},
        {"local_path": "Textures/Base.dds", "archive_path": "game/base_alt.dds"},
        {"local_path": "", "archive_path": "skip.dds"},
        object(),
    ]

    grouped = source_texture_evidence_by_local_path(rows)

    assert len(grouped) == 1
    assert [row["archive_path"] for row in next(iter(grouped.values()))] == ["game/base.dds", "game/base_alt.dds"]


def test_texture_file_lookup_maps_builds_basename_and_evidence_paths() -> None:
    texture_file = Path("Textures/Base.dds")
    evidence = source_texture_evidence_by_local_path(
        [{"local_path": str(texture_file), "archive_path": "Game/Base.dds", "texture_path": "Alt/Base.dds"}]
    )

    by_basename, by_source_path = texture_file_lookup_maps(
        (texture_file,),
        evidence,
        normalize_texture_reference=lambda value: value.replace("\\", "/").lower(),
    )

    assert by_basename == {"base.dds": texture_file}
    assert by_source_path["game/base.dds"] == texture_file
    assert by_source_path["alt/base.dds"] == texture_file


def _texture_classification(slot_kind: str, subtype: str | None = None) -> SimpleNamespace:
    return SimpleNamespace(slot_kind=slot_kind, semantic_subtype=subtype or slot_kind)


def _classify_texture_for_test(parameter_name: str, texture_path: str) -> SimpleNamespace:
    text = f"{parameter_name} {texture_path}".lower()
    if "emissive" in text or "glow" in text:
        return _texture_classification("base", "emissive")
    if "normal" in text or "_n" in text:
        return _texture_classification("normal")
    if "height" in text:
        return _texture_classification("height")
    if "mask" in text or "rough" in text:
        return _texture_classification("material")
    return _texture_classification("base")


def test_best_source_for_slot_prefers_exact_target_texture_path() -> None:
    source_path = Path("loose/body_base.dds")

    assert best_source_for_slot(
        "Body",
        (),
        "base",
        {},
        target_texture_path="game/body_base.dds",
        texture_files_for_mapping=(),
        texture_files_by_basename={"body_base.dds": source_path},
        texture_files_by_normalized_source_path={},
        source_texture_evidence_by_local_path_map={},
        replacement_mesh=None,
        classify_texture_binding=_classify_texture_for_test,
        normalize_texture_reference=lambda value: value.replace("\\", "/").lower(),
        looks_like_standalone_pbr_source=lambda _path: False,
    ) == str(source_path)


def test_best_source_for_slot_picks_emissive_loose_texture() -> None:
    glow_path = Path("body_glow.dds")

    assert best_source_for_slot(
        "Body",
        (),
        "base",
        {},
        parameter_name="Emissive",
        texture_files_for_mapping=(Path("body_base.dds"), glow_path),
        texture_files_by_basename={},
        texture_files_by_normalized_source_path={},
        source_texture_evidence_by_local_path_map={},
        replacement_mesh=None,
        classify_texture_binding=_classify_texture_for_test,
        normalize_texture_reference=lambda value: value.replace("\\", "/").lower(),
        looks_like_standalone_pbr_source=lambda _path: False,
    ) == str(glow_path)


def test_best_source_for_slot_rejects_single_candidate_from_wrong_character_part() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(material="Skin", name="")])
    texture_sets = {"skin": SimpleNamespace(slots={"base": SimpleNamespace(source_path=Path("hand_base.dds"))})}

    assert (
        best_source_for_slot(
            "Body",
            (0,),
            "base",
            texture_sets,
            target_texture_path="body_base.dds",
            texture_files_for_mapping=(),
            texture_files_by_basename={},
            texture_files_by_normalized_source_path={},
            source_texture_evidence_by_local_path_map={},
            replacement_mesh=mesh,
            classify_texture_binding=_classify_texture_for_test,
            normalize_texture_reference=lambda value: value.replace("\\", "/").lower(),
            looks_like_standalone_pbr_source=lambda _path: False,
        )
        == ""
    )


def test_texture_set_factor_parameters_clamps_and_formats_numeric_inputs() -> None:
    params = texture_set_factor_parameters(
        SimpleNamespace(
            roughness_factor=0.5,
            metallic_factor=2.0,
            specular_factor=-1.0,
            glossiness_factor="bad",
            occlusion_strength=None,
        )
    )

    assert [(param.parameter_name, param.value, param.numeric_value) for param in params] == [
        ("_roughnessFactor", "0.500000", 0.5),
        ("_metallicFactor", "1.000000", 1.0),
        ("_specularFactor", "0.000000", 0.0),
    ]


def test_adaptive_alignment_preview_face_limit_clamps_per_submesh_budget() -> None:
    assert adaptive_alignment_preview_face_limit(4, target_total_faces=40_000, minimum=2_000, maximum=20_000) == 10_000
    assert adaptive_alignment_preview_face_limit(100, target_total_faces=40_000, minimum=2_000, maximum=20_000) == 2_000
    assert adaptive_alignment_preview_face_limit(1, target_total_faces=80_000, minimum=2_000, maximum=20_000) == 20_000


def test_alignment_preview_source_face_limit_for_counts_tracks_interactive_and_clone_modes() -> None:
    assert alignment_preview_source_face_limit_for_counts((30_000, 30_000), modify_original_clone_mode=False, appended_geometry=0, d3d11_normal_active=False, interactive=False) == 0
    assert alignment_preview_source_face_limit_for_counts((60_000, 60_000), modify_original_clone_mode=False, appended_geometry=0, d3d11_normal_active=True, interactive=False) == 10_000
    assert alignment_preview_source_face_limit_for_counts((100_000, 100_000), modify_original_clone_mode=False, appended_geometry=0, d3d11_normal_active=False, interactive=True) == 12_000
    assert alignment_preview_source_face_limit_for_counts((90_000,), modify_original_clone_mode=True, appended_geometry=0, d3d11_normal_active=False, interactive=False) == 10_000
    assert alignment_preview_source_face_limit_for_counts((90_000,), modify_original_clone_mode=True, appended_geometry=1, d3d11_normal_active=False, interactive=False) == 5_000


def test_alignment_preview_selected_source_face_limit_for_total_preserves_thresholds() -> None:
    assert alignment_preview_selected_source_face_limit_for_total(130_000, selected_requested=True, interactive=True, fallback_limit=99) == 18_000
    assert alignment_preview_selected_source_face_limit_for_total(130_000, selected_requested=False, interactive=True, fallback_limit=99) == 8_000
    assert alignment_preview_selected_source_face_limit_for_total(90_000, selected_requested=True, interactive=False, fallback_limit=99) == 55_000
    assert alignment_preview_selected_source_face_limit_for_total(120_000, selected_requested=False, interactive=False, fallback_limit=99) == 12_000
    assert alignment_preview_selected_source_face_limit_for_total(20_000, selected_requested=False, interactive=False, fallback_limit=99) == 99


def test_alignment_preview_background_source_face_limit_for_total_preserves_thresholds() -> None:
    assert alignment_preview_background_source_face_limit_for_total(130_000, interactive=True, fallback_limit=99) == 2_000
    assert alignment_preview_background_source_face_limit_for_total(260_000, interactive=False, fallback_limit=99) == 2_500
    assert alignment_preview_background_source_face_limit_for_total(110_000, interactive=False, fallback_limit=99) == 3_500
    assert alignment_preview_background_source_face_limit_for_total(50_000, interactive=False, fallback_limit=99) == 5_000
    assert alignment_preview_background_source_face_limit_for_total(10_000, interactive=False, fallback_limit=99) == 99
