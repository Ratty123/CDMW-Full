from __future__ import annotations

import json
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from PySide6.QtCore import QUrl
from PySide6.QtGui import QColor, QImage

from cdmw.models import PreviewMaterialParameterInput, PreviewMaterialTextureInput
from cdmw.rendering.material_combiner import combine_preview_material
from cdmw.rendering.material_combiner_rules import MaterialPreviewCombinerSettings
from cdmw.services.mesh_rust_preview_package import (
    build_rust_preview_package_from_preview_core,
)

ROOT = Path(__file__).resolve().parents[1]
NATIVE_PREVIEW_CORE = (
    ROOT
    / "native"
    / "cdmw_preview_core"
    / "build"
    / "Release"
    / "cdmw-preview-core.exe"
)
RUST_PREVIEW = (
    ROOT
    / "tools"
    / "rust_mesh_lab"
    / "target"
    / "release"
    / "cdmw_mesh_lab.exe"
)

OWNER_WRAPPER_ITEM_ID = "712"
OWNER_WRAPPER_INDEX = 4
BLUE = (22 / 255.0, 47 / 255.0, 1.0, 1.0)
COPPER = (0.76, 0.31, 0.08, 1.0)


def _write_png(path: Path, pixels: tuple[tuple[int, int, int, int], ...]) -> Path:
    image = QImage(len(pixels), 1, QImage.Format.Format_RGBA8888)
    for x, color in enumerate(pixels):
        image.setPixelColor(x, 0, QColor(*color))
    assert image.save(str(path), "PNG")
    return path


def _rgba_pixels(image: QImage) -> bytes:
    rgba = image.convertToFormat(QImage.Format.Format_RGBA8888)
    result = bytearray()
    for y in range(rgba.height()):
        for x in range(rgba.width()):
            color = rgba.pixelColor(x, y)
            result.extend((color.red(), color.green(), color.blue(), color.alpha()))
    return bytes(result)


def _rgba8_dds(image: QImage, *, srgb: bool) -> bytes:
    """Match cdmw_texture::encode_rgba8_dds for a single RGBA8 mip."""

    width, height = image.width(), image.height()
    pixels = _rgba_pixels(image)
    header = bytearray(148)

    def put(offset: int, value: int) -> None:
        header[offset : offset + 4] = int(value).to_bytes(4, "little")

    header[:4] = b"DDS "
    put(4, 124)
    put(8, 0x0000_100F)
    put(12, height)
    put(16, width)
    put(20, width * 4)
    put(28, 1)
    put(76, 32)
    put(80, 0x4)
    header[84:88] = b"DX10"
    put(108, 0x0000_1000)
    put(128, 29 if srgb else 28)  # R8G8B8A8_UNORM[_SRGB]
    put(132, 3)  # D3D10_RESOURCE_DIMENSION_TEXTURE2D
    put(140, 1)
    return bytes(header) + pixels


def _write_dds(path: Path, image: QImage, *, srgb: bool) -> Path:
    path.write_bytes(_rgba8_dds(image, srgb=srgb))
    return path


def _oracle_albedo(root: Path) -> QImage:
    base = _write_png(
        root / "grip_base.png",
        ((158, 158, 158, 255),) * 8,
    )
    detail = _write_png(
        root / "shared_detail.png",
        ((128, 128, 128, 255),) * 8,
    )
    selector = _write_png(
        root / "grip_selector.png",
        ((255, 0, 0, 255),) * 4 + ((0, 255, 0, 255),) * 4,
    )
    parameters = (
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_dyeingDetailLayerColorMaskR",
            value="#162fffff",
            color_value=BLUE,
        ),
        PreviewMaterialParameterInput(
            parameter_kind="color",
            parameter_name="_dyeingDetailLayerColorMaskG",
            value="#c24f14ff",
            color_value=COPPER,
        ),
        PreviewMaterialParameterInput(
            parameter_kind="byte4",
            parameter_name="_dyeingGlobalOpacity",
            value="4294967295",
            integer_value=0xFFFF_FFFF,
        ),
        PreviewMaterialParameterInput(
            parameter_kind="bitflag32",
            parameter_name="_colorBlendingFlag",
            value="4095",
            integer_value=4095,
        ),
    )

    def texture_input(
        path: Path,
        *,
        parameter_name: str,
        semantic_type: str,
        semantic_subtype: str,
        role: str,
        channel: str = "",
        source_kind: str,
        disposition: str,
    ) -> PreviewMaterialTextureInput:
        return PreviewMaterialTextureInput(
            slot_kind="base" if semantic_type == "color" else "material",
            parameter_name=parameter_name,
            source_texture_path=f"character/texture/{path.stem}.dds",
            source_dds_path=str(path.with_suffix(".dds")),
            texture_name=f"{path.stem}.dds",
            preview_texture_path=str(path),
            semantic_type=semantic_type,
            semantic_subtype=semantic_subtype,
            material_name="CD_PHM_02_Grip_0009",
            shader_family="SkinnedMeshStandard_Ver2",
            confidence="common_default_overlay" if role == "base" else "sidecar-exact",
            sidecar_kind="pac_xml",
            parameter_declared_by="pac_xml",
            layer_role=role,
            layer_channel=channel,
            owner_slot_index=OWNER_WRAPPER_INDEX,
            owner_wrapper_item_id=OWNER_WRAPPER_ITEM_ID,
            binding_authority="authoritative",
            binding_disposition=disposition,
            source_kind=source_kind,
            material_parameters=parameters,
            visualized=True,
        )

    inputs = (
        texture_input(
            base,
            parameter_name="_overlayColorTexture",
            semantic_type="color",
            semantic_subtype="albedo",
            role="base",
            source_kind="crimson_overlay_color",
            disposition="promoted",
        ),
        texture_input(
            detail,
            parameter_name="_detailDiffuseMaskR",
            semantic_type="color",
            semantic_subtype="detail_diffuse",
            role="detail",
            channel="r",
            source_kind="crimson_layer_color",
            disposition="layer_only",
        ),
        texture_input(
            detail,
            parameter_name="_detailDiffuseMaskG",
            semantic_type="color",
            semantic_subtype="detail_diffuse",
            role="detail",
            channel="g",
            source_kind="crimson_layer_color",
            disposition="layer_only",
        ),
        texture_input(
            selector,
            parameter_name="_colorBlendingMaskTexture",
            semantic_type="mask",
            semantic_subtype="material_mask",
            role="mask",
            source_kind="crimson_color_blending_mask",
            disposition="layer_only",
        ),
    )
    combined = combine_preview_material(
        SimpleNamespace(
            material_name="CD_PHM_02_Grip_0009",
            texture_name="CD_PHM_02_Grip_0009",
            texture_flip_vertical=False,
            tangents_usable=False,
            material_texture_inputs=inputs,
            alpha_mode="opaque",
        ),
        root / "python-oracle",
        0,
        settings=MaterialPreviewCombinerSettings(
            support_map_max_dimension=2048,
            requested_output_channels=frozenset({"base"}),
        ),
    )
    assert "pac_detail_dye_tints_masked" in ";".join(combined.notes)
    result = QImage(QUrl(combined.base_source).toLocalFile())
    assert not result.isNull()
    return result


def _geometry_bytes() -> bytes:
    # Preview Core schema 8 stores one non-indexed record per triangle corner.
    vertices = (
        ((-0.8, -0.4, 0.0), (0.0, 1.0)),
        ((0.8, -0.4, 0.0), (1.0, 1.0)),
        ((0.8, 0.4, 0.0), (1.0, 0.0)),
        ((-0.8, -0.4, 0.0), (0.0, 1.0)),
        ((0.8, 0.4, 0.0), (1.0, 0.0)),
        ((-0.8, 0.4, 0.0), (0.0, 0.0)),
    )
    records = []
    for index, (position, uv) in enumerate(vertices):
        records.append(
            struct.pack(
                "<23f",
                *position,
                0.0,
                0.0,
                1.0,
                0.62,
                0.62,
                0.62,
                *uv,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                0.0,
                0.0,
                0.0,
                1.0,
                float(index % 3 == 0),
                float(index % 3 == 1),
                float(index % 3 == 2),
            )
        )
    return b"".join(records)


def _layer(
    *,
    role: str,
    channel: str = "",
    source_parameter: str = "",
    diffuse_source: str = "",
    mask_source: str = "",
    tint: tuple[float, float, float, float] = (1.0, 1.0, 1.0, 1.0),
) -> dict[str, object]:
    return {
        "owner_wrapper_item_id": OWNER_WRAPPER_ITEM_ID,
        "material_wrapper_index": OWNER_WRAPPER_INDEX,
        "layer_role": role,
        "mask_channel": channel,
        "shader_family": "SkinnedMeshStandard_Ver2",
        "shader_rule": "standard_v2",
        "evidence_grade": "exact",
        "source_parameter": source_parameter,
        "mask_parameter": "_colorBlendingMaskTexture" if mask_source else "",
        "weight": 1.0,
        "detail_scale": 0.0,
        "roughness_hint": 0.0,
        "metalness_hint": 0.0,
        "specular_hint": 0.0,
        "height_scale_hint": 0.0,
        "tint": list(tint),
        "diffuse_source": diffuse_source,
        "diffuse_archive_path": (
            f"character/texture/{Path(diffuse_source).name}" if diffuse_source else ""
        ),
        "mask_source": mask_source,
        "mask_archive_path": (
            f"character/texture/{Path(mask_source).name}" if mask_source else ""
        ),
    }


def _write_preview_core_package(
    root: Path,
    *,
    layers: list[dict[str, object]],
) -> Path:
    geometry = root / "geometry"
    geometry.mkdir(parents=True)
    (geometry / "batch_000.bin").write_bytes(_geometry_bytes())
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 8,
                "material_semantics_version": 10,
                "material_graph_version": 4,
                "material_conservation": {
                    "schema_version": 1,
                    "declared_parameter_count": 4,
                    "transported_parameter_count": 4,
                    "resolved_texture_count": 4,
                    "unresolved_texture_count": 0,
                    "conserved": True,
                    "findings": [],
                    "parameters": [],
                },
                "source_path": "character/model/weapon/cd_phm_02_sword_0009.pac",
                "format": "pac",
                "normalization_center": [0.0, 0.0, 0.0],
                "normalization_scale": 1.0,
                "batches": [
                    {
                        "index": 0,
                        "material_name": "CD_PHM_02_Grip_0009",
                        "vertex_file": "geometry/batch_000.bin",
                        "vertex_count": 6,
                        "material_category": "metal",
                        "shader_family": "SkinnedMeshStandard_Ver2",
                        "normal_y_policy": "preserve",
                        "alpha_mode": "opaque",
                        "roughness": 0.35,
                        "metalness": 0.75,
                        "base_color": [0.62, 0.62, 0.62],
                        "material_layers": layers,
                    }
                ],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return root


def _run_capture(manifest: Path, output: Path) -> QImage:
    report = output.with_suffix(".json")
    completed = subprocess.run(
        [
            str(RUST_PREVIEW),
            "--capture-cdmw-preview-session",
            str(manifest),
            "--capture-output",
            str(output),
            "--capture-report-json",
            str(report),
            "--capture-yaw-degrees",
            "0",
            "--capture-pitch-degrees",
            "0",
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr or completed.stdout
    payload = json.loads(report.read_text(encoding="utf-8"))
    assert payload["renderer"] == "wgpu_d3d12_rust"
    assert payload["dds_textures_uploaded"] >= 1
    base_color = output.with_name(f"{output.stem}-base-color.bmp")
    image = QImage(str(base_color))
    assert not image.isNull()
    return image


def test_native_graph_full_rust_pixels_match_python_material_oracle(
    tmp_path: Path,
) -> None:
    if not NATIVE_PREVIEW_CORE.is_file():
        pytest.skip("Release Native Preview Core helper is unavailable")
    if not RUST_PREVIEW.is_file():
        pytest.skip("Release Preview helper is unavailable")

    # The compiled native owner/parameter/channel self-test is the source-side
    # guard; the pixel comparison below is the independent composition guard.
    native = subprocess.run(
        [str(NATIVE_PREVIEW_CORE), "self-test"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert native.returncode == 0, native.stderr or native.stdout

    oracle = _oracle_albedo(tmp_path)
    source_textures = tmp_path / "source-textures"
    source_textures.mkdir()
    base_image = QImage(str(tmp_path / "grip_base.png"))
    detail_image = QImage(str(tmp_path / "shared_detail.png"))
    selector_image = QImage(str(tmp_path / "grip_selector.png"))
    _write_dds(source_textures / "grip_base.dds", base_image, srgb=True)
    _write_dds(source_textures / "shared_detail.dds", detail_image, srgb=True)
    _write_dds(source_textures / "grip_selector.dds", selector_image, srgb=False)
    _write_dds(source_textures / "python_oracle.dds", oracle, srgb=True)

    production_source = _write_preview_core_package(
        tmp_path / "native-production-source",
        layers=[
            _layer(
                role="base",
                source_parameter="_baseColorTexture",
                diffuse_source="textures/grip_base.dds",
            ),
            _layer(
                role="detail",
                channel="r",
                source_parameter="_detailDiffuseMaskR",
                diffuse_source="textures/shared_detail.dds",
                mask_source="textures/grip_selector.dds",
                tint=BLUE,
            ),
            _layer(
                role="detail",
                channel="g",
                source_parameter="_detailDiffuseMaskG",
                diffuse_source="textures/shared_detail.dds",
                mask_source="textures/grip_selector.dds",
                tint=COPPER,
            ),
        ],
    )
    oracle_source = _write_preview_core_package(
        tmp_path / "python-oracle-source",
        layers=[
            _layer(
                role="base",
                source_parameter="_baseColorTexture",
                diffuse_source="textures/python_oracle.dds",
            )
        ],
    )
    for package in (production_source, oracle_source):
        package_textures = package / "textures"
        package_textures.mkdir()
        for texture in source_textures.iterdir():
            (package_textures / texture.name).write_bytes(texture.read_bytes())

    production = build_rust_preview_package_from_preview_core(
        production_source,
        output_package_dir=tmp_path / "production-rust-package",
        material_quality="full",
    )
    expected = build_rust_preview_package_from_preview_core(
        oracle_source,
        output_package_dir=tmp_path / "oracle-rust-package",
        material_quality="full",
    )
    production_manifest = json.loads(
        production.manifest_path.read_text(encoding="utf-8")
    )
    graph = production_manifest["preview_core_material_graph"]
    assert graph["quality"] == "full"
    assert graph["source_edge_count"] == 5
    assert graph["unique_resource_count"] == 3
    assert {
        layer["owner_wrapper_item_id"] for layer in graph["materials"][0]["layers"]
    } == {OWNER_WRAPPER_ITEM_ID}
    assert [
        layer["mask_channel"] for layer in graph["materials"][0]["layers"]
    ] == ["", "r", "g"]

    production_pixels = _run_capture(
        production.manifest_path,
        tmp_path / "production.bmp",
    )
    oracle_pixels = _run_capture(
        expected.manifest_path,
        tmp_path / "oracle.bmp",
    )
    assert production_pixels.size() == oracle_pixels.size()

    production_rgba = _rgba_pixels(production_pixels)
    oracle_rgba = _rgba_pixels(oracle_pixels)
    channel_deltas = [
        abs(actual - wanted)
        for offset, (actual, wanted) in enumerate(zip(production_rgba, oracle_rgba))
        if offset % 4 != 3
    ]
    assert max(channel_deltas, default=0) <= 2
    assert sum(channel_deltas) / max(1, len(channel_deltas)) <= 0.02
