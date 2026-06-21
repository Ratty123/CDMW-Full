from __future__ import annotations

import json
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_preview_mapping import (
    independent_parts,
    mapped_source_indices,
    preview_model_in_original_frame,
    preview_target_mesh_indices,
    selected_part_preview_indices,
    source_preview_geometry_key,
    unmapped_appended_source_indices,
)


def test_preview_target_mesh_indices_uses_fallback_when_unmapped() -> None:
    preview_model = SimpleNamespace(meshes=[object(), object()])

    assert preview_target_mesh_indices(
        preview_model,
        "Body",
        (0, 2, 1),
        mapped_preview=False,
        current_mappings=(),
        preview_submesh_index_map={},
    ) == (0, 1)


def test_preview_target_mesh_indices_uses_preview_map_then_name_tokens() -> None:
    preview_model = SimpleNamespace(
        meshes=[
            SimpleNamespace(name="Helmet", material_name=""),
            SimpleNamespace(name="", material_name="Body Skin"),
            SimpleNamespace(name="Cape", material_name=""),
        ]
    )
    mappings = (
        SimpleNamespace(target_submesh_index=5, target_submesh_name="Body", source_submesh_indices=(2,)),
    )

    assert preview_target_mesh_indices(
        preview_model,
        "Body",
        (2,),
        mapped_preview=True,
        current_mappings=mappings,
        preview_submesh_index_map={5: 1},
    ) == (1,)
    assert preview_target_mesh_indices(
        preview_model,
        "Body",
        (9,),
        mapped_preview=True,
        current_mappings=mappings,
        preview_submesh_index_map={},
    ) == (1,)


def test_mapped_source_indices_collects_mapping_sources() -> None:
    mappings = (
        SimpleNamespace(source_submesh_indices=(0, "2")),
        SimpleNamespace(source_submesh_indices=(2, 3)),
    )

    assert mapped_source_indices(mappings) == {0, 2, 3}


def test_independent_parts_filters_mapped_disabled_marker_and_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(material="Body", name="", marker=False),
            SimpleNamespace(material="Cape", name="", marker=False),
            SimpleNamespace(material="Marker", name="", marker=True),
            SimpleNamespace(material="Disabled", name="", marker=False),
        ]
    )
    mappings = (SimpleNamespace(source_submesh_indices=(0,)),)
    adjustments = {3: SimpleNamespace(enabled=False)}

    parts = independent_parts(
        replacement_mesh=mesh,
        independent_output_source_indices={0, 1, 2, 3, 9},
        preview_only_source_indices={0},
        current_mappings=mappings,
        source_part_adjustments=adjustments,
        default_adjustment=lambda _index: SimpleNamespace(enabled=True),
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
        source_display_name=lambda index: f"{index}: part",
        independent_part_type=SimpleNamespace,
        include_preview_only=True,
    )

    assert [(part.source_submesh_index, part.material_name, part.preview_only) for part in parts] == [
        (0, "Body", True),
        (1, "Cape", False),
    ]


def test_unmapped_appended_source_indices_filters_mapped_disabled_marker_and_bounds() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=False),
            SimpleNamespace(marker=True),
            SimpleNamespace(marker=False),
        ]
    )
    mappings = (SimpleNamespace(source_submesh_indices=(0,)),)
    adjustments = {3: SimpleNamespace(enabled=False)}

    assert unmapped_appended_source_indices(
        replacement_mesh=mesh,
        appended_source_indices={0, 1, 2, 3, 9},
        current_mappings=mappings,
        source_part_adjustments=adjustments,
        default_adjustment=lambda _index: SimpleNamespace(enabled=True),
        is_marker_source=lambda source: bool(getattr(source, "marker", False)),
    ) == (1,)


def test_preview_model_in_original_frame_normalizes_meshes_and_records_maps() -> None:
    parsed_mesh = SimpleNamespace(
        path="mesh.pac",
        format="pac",
        submeshes=[
            SimpleNamespace(
                material="Body",
                texture="body.dds",
                vertices=[(2.0, 4.0, 6.0), (4.0, 6.0, 8.0), (6.0, 8.0, 10.0)],
                faces=[(0, 1, 2)],
                uvs=[(0.0, 0.0), (1.0, 0.0), (1.0, 1.0)],
                normals=[(0.0, 0.0, 1.0)] * 3,
                preview_double_sided=True,
            ),
            SimpleNamespace(material="Empty", vertices=[], faces=[]),
        ],
    )
    source_index_map: dict[int, int] = {}
    parsed_submesh_index_map: dict[int, int] = {}

    preview = preview_model_in_original_frame(
        parsed_mesh,
        normalization_center=(1.0, 2.0, 3.0),
        normalization_scale=2.0,
        source_indices=(7,),
        source_index_map=source_index_map,
        parsed_submesh_index_map=parsed_submesh_index_map,
    )

    assert preview.path == "mesh.pac"
    assert preview.mesh_count == 1
    assert preview.vertex_count == 3
    assert preview.face_count == 1
    assert preview.normalization_center == (1.0, 2.0, 3.0)
    assert preview.meshes[0].material_name == "Body"
    assert preview.meshes[0].texture_name == "body.dds"
    assert preview.meshes[0].positions == [(2.0, 4.0, 6.0), (6.0, 8.0, 10.0), (10.0, 12.0, 14.0)]
    assert preview.meshes[0].indices == [0, 1, 2]
    assert preview.meshes[0].source_submesh_index == 7
    assert preview.meshes[0].preview_double_sided is True
    assert source_index_map == {7: 0}
    assert parsed_submesh_index_map == {0: 0}


def test_source_preview_geometry_key_serializes_stable_geometry_payload() -> None:
    key = source_preview_geometry_key(
        (SimpleNamespace(target_submesh_index=2, source_submesh_indices=("5", 6)),),
        (
            SimpleNamespace(
                source_submesh_index=5,
                enabled=True,
                offset_xyz=(1, 2, 3),
                rotate_xyz_degrees=(4, 5, 6),
                scale_xyz=(1.0, 1.5, 2.0),
                uniform_scale=0.75,
                material_role="emissive",
                emissive_color_rgb=(1, 2, 3),
            ),
        ),
        (SimpleNamespace(original_submesh_index=1, label="copy", keep_original_placement=True),),
        alignment_mode="grid_flat",
        scale_to_length=True,
        flip=False,
        rotate_xyz=(10, 20, 30),
        scale_xyz=(1, 2, 3),
        offset_xyz=(4, 5, 6),
        texture_uv_payload={"Body": {"u": 1}},
        mesh_edit_revision=7,
        source_geometry_revision=8,
        independent_output_source_indices={9, 3},
        preview_only_source_indices={4},
    )

    payload = json.loads(key)

    assert payload["mode"] == "grid_flat"
    assert payload["mappings"] == [[2, [5, 6]]]
    assert payload["adjustments"][0][0] == 5
    assert payload["copies"] == [[1, "copy", True]]
    assert payload["texture_uv"] == {"Body": {"u": 1}}
    assert payload["mesh_edit_revision"] == 7
    assert payload["source_geometry_revision"] == 8
    assert payload["independent_sources"] == [3, 9]
    assert payload["preview_only_sources"] == [4]
    assert "source_material_textures" not in payload
    assert "donor_material_plans" not in payload


def test_selected_part_preview_indices_uses_direct_map_or_source_indices() -> None:
    preview_model = SimpleNamespace(meshes=[object(), object(), object()])

    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices={0, 2},
        mapped_preview=False,
        current_mappings=(),
        direct_source_preview_index_map={0: 1, 2: 9},
        source_overlay_preview_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    ) == (1,)
    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices={0, 2},
        mapped_preview=False,
        current_mappings=(),
        direct_source_preview_index_map={},
        source_overlay_preview_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    ) == (0, 2)
    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices=set(),
        mapped_preview=False,
        current_mappings=(),
        direct_source_preview_index_map={},
        source_overlay_preview_index_map={},
        preview_target_mesh_indices=lambda *_args: (),
    ) is None


def test_selected_part_preview_indices_uses_overlay_then_mapping_targets() -> None:
    preview_model = SimpleNamespace(meshes=[object(), object(), object(), object()])
    mappings = (SimpleNamespace(target_submesh_name="Body", source_submesh_indices=(1,)),)

    assert selected_part_preview_indices(
        preview_model,
        source_index=-1,
        highlighted_source_indices={1, 3},
        mapped_preview=True,
        current_mappings=mappings,
        direct_source_preview_index_map={},
        source_overlay_preview_index_map={3: 2},
        preview_target_mesh_indices=lambda _model, _target, _fallback, _mapped, _mappings: (1,),
    ) == (1, 2)
