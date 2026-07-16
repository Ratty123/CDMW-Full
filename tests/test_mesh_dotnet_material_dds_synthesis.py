from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from cdmw.models import PreviewMaterialTextureInput
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_dotnet_material_package


def _image(path: Path, color: tuple[int, int, int, int]) -> Path:
    image = QImage(4, 4, QImage.Format.Format_RGBA8888)
    image.fill(QColor(*color))
    assert image.save(str(path), "PNG")
    return path


def _submesh() -> SubMesh:
    return SubMesh(
        name="CD_PHM_01_Blade_0070",
        material="CD_PHM_01_Blade_0070",
        texture="CD_PHM_01_Sword_0070",
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        faces=[(0, 1, 2)],
    )


def _write_manifest(root: Path, submesh: SubMesh) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "net_materials.json"
    mesh_dotnet_material_package._write_dotnet_material_manifest(
        path,
        mesh=ParsedMesh(path="archive/test.pac", format="pac", submeshes=[submesh]),
        sidecar_payload={},
        material_signature="stable-material-signature",
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_package_decodes_dds_graph_inputs_and_preserves_native_support_maps(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layer_dds = tmp_path / "cd_texturelayer_003_0005.dds"
    layer_dds.write_bytes(b"DDS graph input placeholder")
    height_dds = tmp_path / "cd_phm_01_blade_0070_disp.dds"
    height_dds.write_bytes(b"DDS height input placeholder")
    detail_height_dds = tmp_path / "cd_texturelayer_003_0005_disp.dds"
    detail_height_dds.write_bytes(b"DDS detail-height input placeholder")
    detail_mask_dds = tmp_path / "cd_phm_01_blade_0070_mg.dds"
    detail_mask_dds.write_bytes(b"DDS detail-mask input placeholder")
    layer_png = _image(
        tmp_path / "cd_texturelayer_003_0005.png",
        (184, 132, 72, 255),
    )
    detail_mask_png = _image(
        tmp_path / "cd_phm_01_blade_0070_mg.png",
        (0, 0, 255, 255),
    )
    submesh = _submesh()
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_detailDiffuseMaskR",
            source_dds_path=str(layer_dds),
            preview_texture_path=str(layer_dds),
            semantic_type="color",
            semantic_subtype="detail_diffuse",
            shader_family="SkinnedMeshStandard_Ver2",
            layer_role="detail",
            layer_channel="r",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="height",
            parameter_name="_heightMap",
            source_dds_path=str(height_dds),
            preview_texture_path=str(height_dds),
            semantic_type="height",
            semantic_subtype="height",
            shader_family="SkinnedMeshStandard_Ver2",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="height",
            parameter_name="_detailHeightMaskR",
            source_dds_path=str(detail_height_dds),
            preview_texture_path=str(detail_height_dds),
            semantic_type="height",
            semantic_subtype="height",
            layer_role="detail",
            layer_channel="r",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="detail",
            parameter_name="_detailMaskTexture",
            source_dds_path=str(detail_mask_dds),
            preview_texture_path=str(detail_mask_dds),
            semantic_type="detail_mask",
            semantic_subtype="detail_mask",
            srgb_mode="linear",
            layer_role="detail",
            layer_channel="b",
            visualized=True,
        ),
    )

    def decode(jobs, *, include_job_keys, stop_event):
        assert include_job_keys is True
        assert stop_event.is_set() is False
        assert jobs == [
            {
                "dds_path": str(layer_dds.resolve()),
                "max_dimension": 512,
                "slot_kind": "base",
                "srgb": "srgb",
                "normal_space": "auto",
            },
            {
                "dds_path": str(detail_mask_dds.resolve()),
                "max_dimension": 512,
                "slot_kind": "material",
                "srgb": "linear",
                "normal_space": "auto",
            },
        ]
        from cdmw.core.texture_native import directxtex_preview_result_key

        return {
            directxtex_preview_result_key(
                layer_dds,
                max_dimension=512,
                slot_kind="base",
                srgb="srgb",
                normal_space="auto",
            ): layer_png,
            directxtex_preview_result_key(
                detail_mask_dds,
                max_dimension=512,
                slot_kind="material",
                srgb="linear",
                normal_space="auto",
            ): detail_mask_png,
        }

    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        decode,
    )

    payload = _write_manifest(tmp_path / "package", submesh)
    binding = payload["submeshes"][0]

    assert binding["material_synthesis"]["succeeded"] is True
    assert binding["material_synthesis"]["decoded_preview_input_count"] == 2
    assert "failure" not in binding["material_synthesis"]
    assert "base" in binding["material_synthesis"]["generated_channels"]
    assert "height" not in binding["material_synthesis"]["generated_channels"]
    assert binding["resolved_channels"]["height"] == str(height_dds)
    assert "preview_material_graph_baked" in binding["resolved_features"]
    generated_resource = next(
        resource
        for resource in payload["resources"]
        if resource["resource_id"] == binding["resource_channels"]["base"]
    )
    generated_image = QImage(str(tmp_path / "package" / generated_resource["path"]))
    assert not generated_image.isNull()
    assert generated_image.pixelColor(0, 0).red() < 245


def test_unreadable_neutral_metal_graph_fails_closed_without_index_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    layer_dds = tmp_path / "cd_texturelayer_003_0005.dds"
    layer_dds.write_bytes(b"DDS graph input placeholder")
    submesh = _submesh()
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_detailDiffuseMaskR",
            source_dds_path=str(layer_dds),
            preview_texture_path=str(layer_dds),
            semantic_type="color",
            semantic_subtype="detail_diffuse",
            shader_family="SkinnedMeshStandard_Ver2",
            layer_role="detail",
            layer_channel="r",
            visualized=True,
        ),
    )
    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        lambda *_args, **_kwargs: {},
    )

    binding = _write_manifest(tmp_path / "package", submesh)["submeshes"][0]

    assert binding["material_synthesis"]["attempted"] is True
    assert binding["material_synthesis"]["succeeded"] is False
    assert binding["material_synthesis"]["decoded_preview_input_count"] == 0
    assert "failure" not in binding["material_synthesis"]
    assert binding["resolved_channels"] == binding["raw_resolved_channels"]
    assert "albedo synthesis failed" in binding["material_synthesis"]["notes"]


def test_missing_raw_height_dds_uses_valid_generated_height(
    tmp_path: Path,
) -> None:
    height_png = tmp_path / "height.png"
    height_image = QImage(4, 4, QImage.Format.Format_RGBA8888)
    for y in range(height_image.height()):
        for x in range(height_image.width()):
            value = (x + y) * 42
            height_image.setPixelColor(x, y, QColor(value, value, value, 255))
    assert height_image.save(str(height_png), "PNG")
    missing_height_dds = tmp_path / "missing_height.dds"
    submesh = _submesh()
    submesh.preview_height_texture_dds_path = str(missing_height_dds)
    submesh.preview_height_texture_path = str(height_png)
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="height",
            parameter_name="_heightTexture",
            source_dds_path=str(missing_height_dds),
            preview_texture_path=str(height_png),
            semantic_type="height",
            semantic_subtype="height",
            layer_role="height",
            layer_channel="r",
            visualized=True,
        ),
    )

    binding = _write_manifest(tmp_path / "package", submesh)["submeshes"][0]

    assert binding["raw_resolved_channels"]["height"] == str(missing_height_dds)
    assert binding["resolved_channels"]["height"] != str(missing_height_dds)
    assert "height" in binding["material_synthesis"]["generated_channels"]
    assert "height" in binding["packaged_channels"]
