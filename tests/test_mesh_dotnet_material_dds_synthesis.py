from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from cdmw.models import PreviewMaterialTextureInput
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.services import mesh_dotnet_material_package
from cdmw.services.mesh_dotnet_material_compiler import _material_compile_blockers
from cdmw.services.mesh_dotnet_material_raw_channels import _native_support_map_channel


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
    assert binding["material_synthesis"]["decode_diagnostics"] == {
        "input_count": 1,
        "dds_candidate_count": 1,
        "decode_job_count": 1,
        "native_channel_deferred_count": 0,
        "raw_channel_mask_decoded_count": 0,
        "missing_dds_input_count": 0,
        "missing_dds_input_sample": [],
        "preview_deferred_by_environment": False,
        "decoded_input_count": 0,
    }
    assert "failure" not in binding["material_synthesis"]
    assert binding["resolved_channels"] == binding["raw_resolved_channels"]
    assert "albedo synthesis failed" in binding["material_synthesis"]["notes"]


def _support_map_submesh(
    normal_dds: Path,
    height_dds: Path,
    layer_dds: Path,
    *,
    material_dds: Path | None = None,
) -> SubMesh:
    submesh = _submesh()
    inputs = [
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
            slot_kind="normal",
            parameter_name="_normalTexture",
            source_dds_path=str(normal_dds),
            preview_texture_path=str(normal_dds),
            semantic_type="normal",
            semantic_subtype="normal",
            shader_family="SkinnedMeshStandard_Ver2",
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
    ]
    if material_dds is not None:
        submesh.preview_material_texture_dds_path = str(material_dds)
        submesh.preview_material_texture_path = str(material_dds)
        inputs.append(
            PreviewMaterialTextureInput(
                slot_kind="material",
                parameter_name="_specularTexture",
                source_dds_path=str(material_dds),
                preview_texture_path=str(material_dds),
                semantic_type="material",
                semantic_subtype="specular",
                shader_family="SkinnedMeshStandard_Ver2",
                visualized=True,
            )
        )
    submesh.preview_material_texture_inputs = tuple(inputs)
    return submesh


def test_raw_support_map_channels_do_not_block_the_material_compile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Skipping a decode is not a read failure, and must not abort the compile.

    Normal and packed material inputs whose raw DDS is packaged verbatim are
    not decoded, so the combiner probes the `.dds` itself and used to leave an
    `unreadable:` note behind. Resident height is removed before combining when
    a resident normal already makes derived-normal synthesis unnecessary.
    `_material_compile_blockers` treats unreadable notes as hard blockers, so
    Solid (Textured) got no textures at all.
    """
    layer_dds = tmp_path / "cd_texturelayer_003_0005.dds"
    layer_dds.write_bytes(b"DDS graph input placeholder")
    normal_dds = tmp_path / "cd_phm_01_blade_0070_n.dds"
    normal_dds.write_bytes(b"DDS normal input placeholder")
    height_dds = tmp_path / "cd_phm_01_blade_0070_disp.dds"
    height_dds.write_bytes(b"DDS height input placeholder")
    material_dds = tmp_path / "cd_texturelayer_damaged_scar_sp.dds"
    material_dds.write_bytes(b"DDS packed material input placeholder")
    layer_png = _image(tmp_path / "cd_texturelayer_003_0005.png", (184, 132, 72, 255))

    def decode(jobs, *, include_job_keys, stop_event):
        from cdmw.core.texture_native import directxtex_preview_result_key

        # The raw-channel normal, height, and packed material maps never reach
        # the decoder.
        assert [job["dds_path"] for job in jobs] == [str(layer_dds.resolve())]
        return {
            directxtex_preview_result_key(
                layer_dds,
                max_dimension=512,
                slot_kind="base",
                srgb="srgb",
                normal_space="auto",
            ): layer_png,
        }

    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        decode,
    )

    payload = _write_manifest(
        tmp_path / "package",
        _support_map_submesh(
            normal_dds,
            height_dds,
            layer_dds,
            material_dds=material_dds,
        ),
    )
    binding = payload["submeshes"][0]
    notes = tuple(binding["material_synthesis"]["notes"])

    assert binding["material_synthesis"]["succeeded"] is True
    assert not [note for note in notes if "unreadable:" in note.casefold()]
    assert "normal not decoded, raw channel packaged:cd_phm_01_blade_0070_n.dds" in notes
    assert not [note for note in notes if "height not decoded" in note.casefold()]
    assert (
        "material not decoded, raw channel packaged:cd_texturelayer_damaged_scar_sp.dds"
        in notes
    )
    assert binding["raw_resolved_channels"]["normal"] == str(normal_dds)
    assert binding["resolved_channels"]["normal"] == str(normal_dds)
    assert binding["raw_resolved_channels"]["height"] == str(height_dds)
    assert binding["resolved_channels"]["height"] == str(height_dds)
    assert binding["raw_resolved_channels"]["material"] == str(material_dds)
    assert binding["resolved_channels"]["material"] == str(material_dds)
    for channel in ("occlusion", "roughness", "metallic"):
        assert binding["raw_resolved_channels"][channel] == str(material_dds)
        assert binding["resolved_channels"][channel] == str(material_dds)
        assert channel in binding["resource_channels"]
    assert binding["channel_components"] == {
        "occlusion": "r",
        "roughness": "g",
        "metallic": "b",
    }
    assert _material_compile_blockers(payload) == []


def test_package_reconstructs_positive_z_when_composing_bc5_normal_layers(
    tmp_path: Path,
) -> None:
    # DirectXTex expands BC5 to RG with blue left at zero. The renderer
    # reconstructs positive Z from XY, so the offline layer compositor must do
    # the same instead of interpreting blue=0 as signed Z=-1.
    base_normal = _image(tmp_path / "base_bc5.png", (128, 128, 0, 255))
    detail_normal = _image(tmp_path / "detail_bc5.png", (200, 128, 0, 255))
    selector = _image(tmp_path / "selector.png", (255, 0, 0, 255))
    submesh = _submesh()
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_normalTexture",
            preview_texture_path=str(base_normal),
            source_dds_path=str(base_normal),
            semantic_type="normal",
            layer_role="normal",
            sidecar_kind="pac_xml",
            binding_authority="authoritative",
            binding_disposition="promoted",
            source_kind="crimson_normal",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_detailNormalMaskR",
            preview_texture_path=str(detail_normal),
            source_dds_path=str(detail_normal),
            semantic_type="normal",
            layer_role="detail",
            layer_channel="r",
            sidecar_kind="pac_xml",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_layer_normal",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="mask",
            parameter_name="_colorBlendingMaskTexture",
            preview_texture_path=str(selector),
            source_dds_path=str(selector),
            semantic_type="mask",
            layer_role="color",
            sidecar_kind="pac_xml",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_color_blending_mask",
            visualized=True,
        ),
    )

    payload = _write_manifest(tmp_path / "package", submesh)
    binding = payload["submeshes"][0]
    normal_resource = next(
        resource
        for resource in payload["resources"]
        if resource["resource_id"] == binding["resource_channels"]["normal"]
    )
    packaged_normal = QImage(str(tmp_path / "package" / normal_resource["path"]))
    pixel = packaged_normal.pixelColor(0, 0)

    assert 150 <= pixel.red() <= 175
    assert 120 <= pixel.green() <= 135
    assert pixel.blue() >= 245


def test_layered_normal_uses_the_native_selected_macro_dds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_dds = tmp_path / "zzz_selected_00_n.dds"
    alternate_dds = tmp_path / "000_alternate_01_n.dds"
    detail_dds = tmp_path / "detail_n.dds"
    for path in (selected_dds, alternate_dds, detail_dds):
        path.write_bytes(b"DDS normal placeholder")
    selected_png = _image(tmp_path / "selected.png", (128, 128, 0, 255))
    alternate_png = _image(tmp_path / "alternate.png", (230, 128, 0, 255))
    detail_png = _image(tmp_path / "detail.png", (160, 128, 0, 255))
    selector = _image(tmp_path / "selector.png", (255, 0, 0, 255))
    decoded_paths: list[str] = []

    def decode(jobs, *, include_job_keys, stop_event):
        from cdmw.core.texture_native import directxtex_preview_result_key

        decoded_paths.extend(str(job["dds_path"]) for job in jobs)
        outputs = {
            selected_dds.resolve(): selected_png,
            alternate_dds.resolve(): alternate_png,
            detail_dds.resolve(): detail_png,
        }
        return {
            directxtex_preview_result_key(
                source,
                max_dimension=256,
                slot_kind="normal",
                srgb="linear",
                normal_space="auto",
            ): preview
            for source, preview in outputs.items()
        }

    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        decode,
    )
    submesh = _submesh()
    submesh.preview_tangents_usable = True
    submesh.preview_normal_texture_path = str(selected_dds)
    submesh.preview_normal_texture_dds_path = str(selected_dds)
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_normalTexture",
            source_dds_path=str(alternate_dds),
            preview_texture_path=str(alternate_dds),
            semantic_type="normal",
            layer_role="normal",
            binding_disposition="promoted",
            source_kind="crimson_normal",
        ),
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_normalTexture",
            source_dds_path=str(selected_dds),
            preview_texture_path=str(selected_dds),
            semantic_type="normal",
            layer_role="normal",
            binding_disposition="promoted",
            source_kind="crimson_normal",
        ),
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_detailNormalMaskR",
            source_dds_path=str(detail_dds),
            preview_texture_path=str(detail_dds),
            semantic_type="normal",
            layer_role="detail",
            layer_channel="r",
            binding_disposition="layer_only",
            source_kind="crimson_layer_normal",
        ),
        PreviewMaterialTextureInput(
            slot_kind="mask",
            parameter_name="_colorBlendingMaskTexture",
            source_dds_path=str(selector),
            preview_texture_path=str(selector),
            semantic_type="mask",
            layer_role="color",
            binding_disposition="layer_only",
            source_kind="crimson_color_blending_mask",
        ),
    )

    payload = _write_manifest(tmp_path / "package", submesh)
    binding = payload["submeshes"][0]
    normal_resource = next(
        resource
        for resource in payload["resources"]
        if resource["resource_id"] == binding["resource_channels"]["normal"]
    )
    packaged_normal = QImage(str(tmp_path / "package" / normal_resource["path"]))
    pixel = packaged_normal.pixelColor(0, 0)

    assert str(selected_dds.resolve()) in decoded_paths
    assert binding["raw_resolved_channels"]["normal"] == str(selected_dds)
    assert binding["resolved_channels"]["normal"] != str(selected_dds)
    assert 125 <= pixel.red() <= 165
    assert pixel.blue() >= 245
    assert not [
        note
        for note in binding["material_synthesis"]["notes"]
        if "normal not decoded" in note.casefold()
    ]


def test_layered_normal_decode_failure_keeps_the_native_selected_dds(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    selected_dds = tmp_path / "selected_00_n.dds"
    detail_dds = tmp_path / "detail_n.dds"
    selected_dds.write_bytes(b"DDS selected normal placeholder")
    detail_dds.write_bytes(b"DDS detail normal placeholder")
    detail_png = _image(tmp_path / "detail.png", (200, 128, 0, 255))
    decoded_paths: list[str] = []

    def decode(jobs, *, include_job_keys, stop_event):
        from cdmw.core.texture_native import directxtex_preview_result_key

        decoded_paths.extend(str(job["dds_path"]) for job in jobs)
        return {
            directxtex_preview_result_key(
                detail_dds.resolve(),
                max_dimension=256,
                slot_kind="normal",
                srgb="linear",
                normal_space="auto",
            ): detail_png
        }

    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        decode,
    )
    submesh = _submesh()
    submesh.preview_tangents_usable = True
    submesh.preview_normal_texture_path = str(selected_dds)
    submesh.preview_normal_texture_dds_path = str(selected_dds)
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_normalTexture",
            source_dds_path=str(selected_dds),
            preview_texture_path=str(selected_dds),
            semantic_type="normal",
            layer_role="normal",
            binding_disposition="promoted",
            source_kind="crimson_normal",
        ),
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="_detailNormalMaskR",
            source_dds_path=str(detail_dds),
            preview_texture_path=str(detail_dds),
            semantic_type="normal",
            layer_role="detail",
            layer_channel="r",
            binding_disposition="layer_only",
            source_kind="crimson_layer_normal",
        ),
    )

    payload = _write_manifest(tmp_path / "package", submesh)
    binding = payload["submeshes"][0]
    notes = [str(note).casefold() for note in binding["material_synthesis"]["notes"]]

    assert str(selected_dds.resolve()) in decoded_paths
    assert binding["raw_resolved_channels"]["normal"] == str(selected_dds)
    assert binding["resolved_channels"]["normal"] == str(selected_dds)
    assert any("normal not decoded, raw channel packaged" in note for note in notes)
    assert not any("normal layers synthesized" in note for note in notes)


def test_selector_mask_that_is_also_the_raw_material_channel_is_decoded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A layer selector mask is decoded even when its DDS is the raw material channel.

    On `cd_phm_01_sword_0039.pac` the grime selector `_colorBlendingMaskTexture`
    is the same `_m.dds` the resident viewport packages verbatim as the material
    channel. The deferral skipped its decode, both layer compositors then probed
    the raw `.dds`, and `normal mask unreadable:` plus `material layer mask
    unreadable:grime:r` blocked the whole compile, so Solid (Textured) fell back
    to Faces (No Textures) on the Original pane every time it was picked.
    """
    from cdmw.core.texture_native import directxtex_preview_result_key

    mask_dds = tmp_path / "cd_texturelayer_0036_m.dds"
    mask_dds.write_bytes(b"DDS selector mask placeholder")
    grime_dds = tmp_path / "cd_texturelayer_0036_grime_sp.dds"
    grime_dds.write_bytes(b"DDS grime material placeholder")
    mask_png = _image(tmp_path / "cd_texturelayer_0036_m.png", (255, 0, 0, 255))
    grime_png = _image(tmp_path / "cd_texturelayer_0036_grime_sp.png", (40, 200, 90, 255))
    decoded_paths: list[str] = []

    def decode(jobs, *, include_job_keys, stop_event):
        decoded_paths.extend(str(job["dds_path"]) for job in jobs)
        outputs = {str(mask_dds.resolve()): mask_png, str(grime_dds.resolve()): grime_png}
        return {
            directxtex_preview_result_key(
                Path(job["dds_path"]),
                max_dimension=job["max_dimension"],
                slot_kind=job["slot_kind"],
                srgb=job["srgb"],
                normal_space=job["normal_space"],
            ): outputs[str(job["dds_path"])]
            for job in jobs
        }

    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        decode,
    )
    submesh = _submesh()
    # The raw material channel the viewport packages verbatim is the mask itself.
    submesh.preview_material_texture_dds_path = str(mask_dds)
    submesh.preview_material_texture_path = str(mask_dds)
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_grimeMaterialTexture",
            source_dds_path=str(grime_dds),
            preview_texture_path=str(grime_dds),
            semantic_type="material",
            semantic_subtype="specular",
            shader_family="SkinnedMeshStandard_Ver2",
            layer_role="grime",
            layer_channel="r",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_colorBlendingMaskTexture",
            source_dds_path=str(mask_dds),
            preview_texture_path=str(mask_dds),
            semantic_type="material",
            semantic_subtype="mask",
            shader_family="SkinnedMeshStandard_Ver2",
            layer_role="color",
            binding_disposition="layer_only",
            source_kind="crimson_color_blending_mask",
            visualized=True,
        ),
    )

    payload = _write_manifest(tmp_path / "package", submesh)
    binding = payload["submeshes"][0]
    synthesis = binding["material_synthesis"]
    notes = tuple(str(note) for note in synthesis["notes"])

    assert str(mask_dds.resolve()) in decoded_paths
    assert synthesis["decode_diagnostics"]["raw_channel_mask_decoded_count"] == 1
    assert synthesis["decode_diagnostics"]["native_channel_deferred_count"] == 0
    assert not [note for note in notes if "unreadable:" in note.casefold()]
    assert "material layer mask applied:grime:r" in notes
    assert binding["raw_resolved_channels"]["material"] == str(mask_dds)
    assert _material_compile_blockers(payload) == []


def test_raw_support_map_skip_requires_the_same_dds_path(tmp_path: Path) -> None:
    packaged_material_dds = tmp_path / "packaged_sp.dds"
    packaged_material_dds.write_bytes(b"DDS packaged material placeholder")
    unrelated_material_dds = tmp_path / "unrelated_sp.dds"
    unrelated_material_dds.write_bytes(b"DDS unrelated material placeholder")
    item = PreviewMaterialTextureInput(
        slot_kind="material",
        parameter_name="_specularTexture",
        source_dds_path=str(unrelated_material_dds),
        preview_texture_path=str(unrelated_material_dds),
        semantic_type="material",
        semantic_subtype="specular",
        shader_family="SkinnedMeshStandard_Ver2",
        visualized=True,
    )

    assert (
        _native_support_map_channel(
            item,
            {"material": str(packaged_material_dds)},
        )
        == ""
    )


def test_unreadable_input_without_a_raw_channel_still_blocks_the_compile(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The relabelling only covers deliberate skips, never a real decode failure."""
    layer_dds = tmp_path / "cd_texturelayer_003_0005.dds"
    layer_dds.write_bytes(b"DDS graph input placeholder")
    # No file on disk, so nothing packages this channel verbatim and the
    # combiner's failure to read it is a genuine one.
    missing_normal_dds = tmp_path / "cd_phm_01_blade_0070_n.dds"
    height_dds = tmp_path / "cd_phm_01_blade_0070_disp.dds"
    height_dds.write_bytes(b"DDS height input placeholder")
    layer_png = _image(tmp_path / "cd_texturelayer_003_0005.png", (184, 132, 72, 255))

    def decode(jobs, *, include_job_keys, stop_event):
        from cdmw.core.texture_native import directxtex_preview_result_key

        return {
            directxtex_preview_result_key(
                layer_dds,
                max_dimension=512,
                slot_kind="base",
                srgb="srgb",
                normal_space="auto",
            ): layer_png,
        }

    monkeypatch.setattr(
        "cdmw.core.texture_native.ensure_directxtex_dds_preview_pngs",
        decode,
    )

    payload = _write_manifest(
        tmp_path / "package",
        _support_map_submesh(missing_normal_dds, height_dds, layer_dds),
    )
    blockers = _material_compile_blockers(payload)
    unreadable = [
        blocker for blocker in blockers if blocker["kind"] == "unreadable_material_inputs"
    ]

    assert unreadable
    assert unreadable[0]["notes"] == ["normal unreadable:cd_phm_01_blade_0070_n.dds"]
    assert unreadable[0]["decode_diagnostics"]["missing_dds_input_count"] == 1
    assert unreadable[0]["decode_diagnostics"]["missing_dds_input_sample"][0][
        "candidate_paths"
    ]["source_dds_path"] == str(missing_normal_dds)


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
