from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PIL import Image
import pytest

from cdmw.core.archive_mesh_types import MeshImportPreviewResult, MeshImportSupplementalFileSpec
from cdmw.core.final_package_preview import (
    apply_material_preflight_override,
    build_final_package_preview,
    material_preflight_hard_blockers,
)
from cdmw.domain.mesh.material_export_safety import material_export_safety_blockers
from cdmw.models import ModelPreviewData, ModelPreviewMesh
from cdmw.modding.material_profiles import get_complete_swap_material_profile
from cdmw.modding.material_atlas import resize_atlas_tile
from cdmw.modding.material_rebuilt_payloads import _bake_complete_swap_material_atlas_png
from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot, TextureReplacementReport
from cdmw.modding.mesh_parser import SubMesh
from cdmw.modding.pac_xml_profiles import infer_pac_xml_texture_role, pac_xml_texture_alias_matches_parameter
from cdmw.modding.static_mesh_output_plan import _atlas_uv_transform
from cdmw.modding.static_mesh_runtime_builder import _rewrite_submesh_uvs_for_material_atlas
from cdmw.modding.static_mesh_types import StaticMaterialAtlasRect, StaticOutputDrawSection


def _wrapper(parameters: tuple[dict[str, object], ...]) -> dict[str, object]:
    return {
        "wrapper_name": "Body",
        "shader_name": "SkinnedMeshGlass",
        "parameters": parameters,
        "corpus_proven": True,
    }


def test_material_export_preflight_blocks_unproven_alpha_and_transmission() -> None:
    source = ({"material_name": "Glass", "alpha_mode": "BLEND", "scalar_hints": (("transmission", 0.5),)},)
    routes = ({"source_material_names": ("Glass",), "source_indices": (), "target_wrapper_names": ("Body",)},)

    blockers = material_export_safety_blockers(source, (_wrapper(()),), routes)
    compatible = material_export_safety_blockers(
        source,
        (
            _wrapper(
                (
                    {"name": "_alphaBlend", "type": "Bool", "value": "1"},
                    {"name": "_transmissionFactor", "type": "Float", "value": "0.5"},
                )
            ),
        ),
        routes,
    )

    assert len(blockers) == 1
    assert "BLEND, transmission" in blockers[0]
    assert compatible == ()
    mask_source = ({"material_name": "Leaves", "alpha_mode": "MASK"},)
    mask_routes = ({"source_material_names": ("Leaves",), "source_indices": (), "target_wrapper_names": ("Body",)},)
    assert material_export_safety_blockers(mask_source, (_wrapper(()),), mask_routes)
    assert material_export_safety_blockers(
        mask_source,
        (_wrapper(({"name": "_alphaTest", "type": "Bool", "value": "1"},)),),
        mask_routes,
    ) == ()


def _preview(alpha_mode: str = "") -> MeshImportPreviewResult:
    mesh = ModelPreviewMesh(
        material_name="Glass",
        positions=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        texture_coordinates=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        indices=[0, 1, 2],
        source_submesh_index=0,
        preview_alpha_mode=alpha_mode,
    )
    section = StaticOutputDrawSection(
        output_index=0,
        target_submesh_index=0,
        target_submesh_name="Body",
        source_submesh_indices=[0],
        source_material_name="Glass",
    )
    return MeshImportPreviewResult(
        rebuilt_data=b"",
        parsed_mesh=SimpleNamespace(path="source.glb", submeshes=[]),
        preview_model=ModelPreviewData(path="source.glb", meshes=[mesh]),
        summary_lines=[],
        source_owned_output_draw_sections=(section,),
    )


def _sidecar(*, alpha_blend: bool = False, texture_path: str = "character/texture/body.dds", parameter: str = "_overlayColorTexture") -> bytes:
    alpha = (
        '<MaterialParameterBool StringItemID="_alphaBlend" ItemID="9" _name="_alphaBlend" _value="1" Index="1"/>'
        if alpha_blend
        else ""
    )
    return (
        '<ModelProperty><Vector Name="_subMeshResources">'
        '<SkinnedMeshMaterialWrapper ItemID="1" _subMeshName="Body">'
        '<Material _materialName="SkinnedMeshGlass"><Vector Name="_parameters">'
        f'<MaterialParameterTexture ItemID="8" _name="{parameter}" Index="0">'
        f'<ResourceReferencePath_ITexture _path="{texture_path}"/></MaterialParameterTexture>{alpha}'
        "</Vector></Material></SkinnedMeshMaterialWrapper></Vector></ModelProperty>"
    ).encode("utf-8")


def _final_preview(tmp_path: Path, *, alpha_blend: bool) -> object:
    specs = (
        MeshImportSupplementalFileSpec(
            source_path=tmp_path / "body.dds",
            target_path="character/texture/body.dds",
            kind="texture_generated",
            payload_data=b"DDS payload",
        ),
        MeshImportSupplementalFileSpec(
            source_path=tmp_path / "body.pac_xml",
            target_path="character/modelproperty/body.pac_xml",
            kind="sidecar_generated",
            payload_data=_sidecar(alpha_blend=alpha_blend),
            note="PAC-driven material sidecar patched from original archive entry.",
        ),
    )
    return build_final_package_preview(_preview("BLEND"), supplemental_file_specs=specs, require_source_owned_colors=True)


def test_final_preview_blocks_unproven_blend_and_preserves_unsafe_override_policy(tmp_path: Path) -> None:
    blocked = _final_preview(tmp_path, alpha_blend=False)
    compatible = _final_preview(tmp_path, alpha_blend=True)

    safety = tuple(error for error in blocked.preflight_errors if "Corpus-proven target wrapper support missing" in error)
    hard = material_preflight_hard_blockers(blocked.preflight_errors)
    assert len(safety) == 1
    assert any("Visible color texture is not package-resolved" in error for error in hard)
    assert not any("Corpus-proven target wrapper support missing" in error for error in compatible.preflight_errors)
    assert material_preflight_hard_blockers(safety) == safety
    assert apply_material_preflight_override(blocked) == hard
    assert safety[0] in blocked.preflight_errors
    assert apply_material_preflight_override(blocked, include_hard=True) == ()


def test_pac_xml_semantics_accept_parameter_proven_short_aliases() -> None:
    normal_path = "character/texture/cd_phm_0264_hair_00_f.dds"
    height_path = "character/texture/cd_phm_0264_body_00_h.dds"

    assert infer_pac_xml_texture_role("_normalTexture", normal_path) == "normal"
    assert infer_pac_xml_texture_role("_heightTexture", height_path) == "height"
    assert pac_xml_texture_alias_matches_parameter("_normalTexture", normal_path)
    assert pac_xml_texture_alias_matches_parameter("_heightTexture", height_path)
    assert not pac_xml_texture_alias_matches_parameter("_normalTexture", "character/texture/body_m.dds")


def test_final_preview_does_not_false_warn_for_corpus_normal_f_alias(tmp_path: Path) -> None:
    path = "character/texture/cd_phm_0264_hair_00_f.dds"
    specs = (
        MeshImportSupplementalFileSpec(tmp_path / "hair.dds", path, "texture_generated", payload_data=b"DDS payload"),
        MeshImportSupplementalFileSpec(
            tmp_path / "hair.pac_xml",
            "character/modelproperty/hair.pac_xml",
            "sidecar_generated",
            payload_data=_sidecar(texture_path=path, parameter="_normalTexture"),
        ),
    )

    result = build_final_package_preview(_preview(), supplemental_file_specs=specs)

    assert not any("_normalTexture points at a non-normal-looking DDS path" in warning for warning in result.warnings)


def test_material_atlas_extrudes_gutters_and_insets_uvs(tmp_path: Path) -> None:
    first_path = tmp_path / "first.png"
    second_path = tmp_path / "second.png"
    first = Image.new("RGBA", (16, 16))
    first.putdata([(x * 16, y * 8, 0, 255) for y in range(16) for x in range(16)])
    first.save(first_path)
    Image.new("RGBA", (16, 16), (0, 0, 255, 255)).save(second_path)
    texture_sets = {
        "first": ReplacementTextureSet("First", {"base": ReplacementTextureSlot("First", "base", first_path)}),
        "second": ReplacementTextureSet("Second", {"base": ReplacementTextureSlot("Second", "base", second_path)}),
    }
    rects = (
        StaticMaterialAtlasRect("First", (0,), 0.0, 0.0, 0.5, 1.0),
        StaticMaterialAtlasRect("Second", (1,), 0.5, 0.0, 0.5, 1.0),
    )
    report = TextureReplacementReport()
    atlas_path = _bake_complete_swap_material_atlas_png(
        target_name="Body",
        rects=rects,
        texture_sets=texture_sets,
        slot_kind="base",
        padding=8,
        report=report,
        material_profile=get_complete_swap_material_profile("material_authority_detail_mask"),
    )

    assert atlas_path is not None
    assert report.errors == []
    with Image.open(atlas_path) as atlas:
        middle_y = atlas.height // 2
        cell_width = atlas.width // 2
        assert 8 / cell_width == pytest.approx(1.0 / 64.0)
        assert atlas.getpixel((0, middle_y)) == atlas.getpixel((8, middle_y))
        assert atlas.getpixel((cell_width - 1, middle_y)) == atlas.getpixel((cell_width - 9, middle_y))
        assert atlas.getpixel((cell_width, middle_y)) == (0, 0, 255, 255)

    offset, scale = _atlas_uv_transform(rects[0], padding=8)
    assert offset[0] > rects[0].x
    assert offset[0] + scale[0] < rects[0].x + rects[0].width
    submesh = SubMesh(vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0)], uvs=[(0.0, 0.0), (1.0, 1.0)])
    with patch("cdmw.modding.mesh_native_core.apply_native_mesh_uv_atlas_submesh", return_value=False):
        _rewrite_submesh_uvs_for_material_atlas(
            submesh,
            rects[0],
            target_name="Body",
            source_index=0,
            source_material_name="First",
            padding=8,
        )
    assert submesh.uvs == [offset, (offset[0] + scale[0], offset[1] + scale[1])]


def test_material_atlas_rows_match_bottom_up_uv_rectangles(tmp_path: Path) -> None:
    colors = {
        "first": (255, 0, 0, 255),
        "second": (0, 255, 0, 255),
        "third": (0, 0, 255, 255),
        "fourth": (255, 255, 0, 255),
    }
    texture_sets: dict[str, ReplacementTextureSet] = {}
    for name, color in colors.items():
        path = tmp_path / f"{name}.png"
        Image.new("RGBA", (16, 16), color).save(path)
        texture_sets[name] = ReplacementTextureSet(
            name.title(),
            {"base": ReplacementTextureSlot(name.title(), "base", path)},
        )
    rects = (
        StaticMaterialAtlasRect("First", (0,), 0.0, 0.0, 0.5, 0.5),
        StaticMaterialAtlasRect("Second", (1,), 0.5, 0.0, 0.5, 0.5),
        StaticMaterialAtlasRect("Third", (2,), 0.0, 0.5, 0.5, 0.5),
        StaticMaterialAtlasRect("Fourth", (3,), 0.5, 0.5, 0.5, 0.5),
    )
    report = TextureReplacementReport()

    path = _bake_complete_swap_material_atlas_png(
        target_name="BodyRows",
        rects=rects,
        texture_sets=texture_sets,
        slot_kind="base",
        padding=8,
        report=report,
        material_profile=get_complete_swap_material_profile("material_authority_detail_mask"),
    )

    assert path is not None and report.errors == []
    with Image.open(path) as atlas:
        quarter_x, quarter_y = atlas.width // 4, atlas.height // 4
        assert atlas.getpixel((quarter_x, atlas.height - quarter_y)) == colors["first"]
        assert atlas.getpixel((atlas.width - quarter_x, atlas.height - quarter_y)) == colors["second"]
        assert atlas.getpixel((quarter_x, quarter_y)) == colors["third"]
        assert atlas.getpixel((atlas.width - quarter_x, quarter_y)) == colors["fourth"]


def test_material_atlas_resize_uses_linear_color_and_normalized_vectors() -> None:
    source = Image.new("RGBA", (2, 1))
    source.putdata(((0, 0, 0, 255), (255, 255, 255, 255)))
    color = resize_atlas_tile(source, (1, 1), "base")
    data = resize_atlas_tile(source, (1, 1), "material_mask")
    normal_source = Image.new("RGBA", (2, 1))
    normal_source.putdata(((255, 128, 128, 255), (128, 255, 128, 255)))
    normal = resize_atlas_tile(normal_source, (1, 1), "normal")
    try:
        assert color.getpixel((0, 0))[0] == pytest.approx(188, abs=1)
        assert data.getpixel((0, 0))[0] == pytest.approx(128, abs=1)
        encoded = normal.getpixel((0, 0))
        vector = tuple(channel / 127.5 - 1.0 for channel in encoded[:3])
        assert sum(component * component for component in vector) ** 0.5 == pytest.approx(1.0, abs=0.02)
        assert vector[0] > 0.65 and vector[1] > 0.65
    finally:
        source.close()
        color.close()
        data.close()
        normal_source.close()
        normal.close()
