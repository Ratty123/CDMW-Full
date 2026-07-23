from __future__ import annotations

import json
from pathlib import Path

import pytest
from PySide6.QtGui import QColor, QImage

from cdmw.models import ModelPreviewData, ModelPreviewMesh, PreviewMaterialTextureInput
from cdmw.modding.mesh_parser import ParsedMesh, SubMesh
from cdmw.rendering import material_combiner_images
from cdmw.services import mesh_dotnet_material_package
from cdmw.services.mesh_dotnet_material_bindings import (
    apply_dotnet_native_material_batch_bindings,
    copy_dotnet_preview_material_bindings,
)


def _image(
    path: Path,
    color: tuple[int, int, int, int],
    *,
    size: tuple[int, int] = (4, 4),
) -> Path:
    image = QImage(*size, QImage.Format.Format_RGBA8888)
    image.fill(QColor(*color))
    assert image.save(str(path), "PNG")
    return path


def _submesh(name: str = "part") -> SubMesh:
    return SubMesh(
        name=name,
        material=name,
        vertices=[(0.0, 0.0, 0.0), (1.0, 0.0, 0.0), (0.0, 1.0, 0.0)],
        uvs=[(0.0, 0.0), (1.0, 0.0), (0.0, 1.0)],
        faces=[(0, 1, 2)],
    )


def _write_manifest(
    root: Path,
    submeshes: list[SubMesh],
    *,
    cancelled=None,
) -> dict[str, object]:
    root.mkdir(parents=True, exist_ok=True)
    path = root / "net_materials.json"
    mesh_dotnet_material_package._write_dotnet_material_manifest(
        path,
        mesh=ParsedMesh(path="archive/test.pac", format="pac", submeshes=submeshes),
        sidecar_payload={},
        material_signature="stable-material-signature",
        cancelled=cancelled,
    )
    return json.loads(path.read_text(encoding="utf-8"))


def test_material_image_reader_falls_back_to_valid_file_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image(tmp_path / "transient-reader.png", (24, 48, 96, 255), size=(8, 4))

    class NullImageReader:
        def __init__(self, _source_path: str) -> None:
            pass

        def setAutoTransform(self, _enabled: bool) -> None:
            pass

        def size(self):
            return QImage().size()

        def setScaledSize(self, _size) -> None:
            pass

        def read(self) -> QImage:
            return QImage()

    monkeypatch.setattr(material_combiner_images, "QImageReader", NullImageReader)

    image = material_combiner_images._image_reader(str(source), max_dimension=4)

    assert not image.isNull()
    assert (image.width(), image.height()) == (4, 2)


def test_material_image_reader_retries_transient_byte_decode_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = _image(tmp_path / "transient-byte-decode.png", (24, 48, 96, 255), size=(8, 4))
    real_qimage = material_combiner_images.QImage
    decode_calls = 0

    class NullImageReader:
        def __init__(self, _source_path: str) -> None:
            pass

        def setAutoTransform(self, _enabled: bool) -> None:
            pass

        def size(self):
            return real_qimage().size()

        def setScaledSize(self, _size) -> None:
            pass

        def read(self) -> QImage:
            return real_qimage()

    class FlakyQImage:
        def __new__(cls, *args, **kwargs):
            return real_qimage(*args, **kwargs)

        @staticmethod
        def fromData(payload: bytes) -> QImage:
            nonlocal decode_calls
            decode_calls += 1
            if decode_calls < 3:
                return real_qimage()
            return real_qimage.fromData(payload)

    monkeypatch.setattr(material_combiner_images, "QImageReader", NullImageReader)
    monkeypatch.setattr(material_combiner_images, "QImage", FlakyQImage)
    monkeypatch.setattr(material_combiner_images.time, "sleep", lambda _delay: None)

    image = material_combiner_images._image_reader(str(source), max_dimension=4)

    assert decode_calls == 3
    assert not image.isNull()
    assert (image.width(), image.height()) == (4, 2)


def test_package_preserves_authoritative_base_and_direct_normal_for_ordinary_pbr(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _image(
        tmp_path / "ordinary_base_2048.png",
        (72, 96, 128, 255),
        size=(2048, 1024),
    )
    normal = _image(
        tmp_path / "ordinary_normal_2048.png",
        (128, 160, 255, 255),
        size=(2048, 1024),
    )
    roughness = _image(
        tmp_path / "ordinary_roughness_2048.png",
        (96, 96, 96, 255),
        size=(2048, 1024),
    )
    submesh = _submesh("ordinary_pbr")
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="baseColorTexture",
            preview_texture_path=str(base),
            source_dds_path=str(base),
            semantic_type="color",
            semantic_subtype="albedo",
            confidence="gltf",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="normalTexture",
            preview_texture_path=str(normal),
            source_dds_path=str(normal),
            semantic_type="normal",
            semantic_subtype="normal",
            confidence="gltf",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="roughnessTexture",
            preview_texture_path=str(roughness),
            source_dds_path=str(roughness),
            semantic_type="roughness",
            semantic_subtype="roughness",
            confidence="gltf",
            visualized=True,
        ),
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("ordinary direct PBR inputs must not invoke the combiner")

    monkeypatch.setattr(mesh_dotnet_material_package, "combine_preview_material", forbidden)

    payload = _write_manifest(tmp_path / "package", [submesh])
    binding = payload["submeshes"][0]

    assert binding["material_synthesis"] == {"attempted": False, "succeeded": False}
    assert binding["resolved_channels"] == binding["raw_resolved_channels"]
    assert binding["resolved_channels"]["base"] == str(base)
    assert binding["resolved_channels"]["albedo"] == str(base)
    assert binding["resolved_channels"]["diffuse"] == str(base)
    assert binding["resolved_channels"]["normal"] == str(normal)
    assert binding["resolved_channels"]["roughness"] == str(roughness)
    for channel in ("base", "albedo", "diffuse", "normal", "roughness"):
        resource = next(
            item
            for item in payload["resources"]
            if item["resource_id"] == binding["resource_channels"][channel]
        )
        assert resource["semantic_authority"] != "synthesized_shared_combiner"


@pytest.mark.parametrize(
    (
        "material_name",
        "shader_family",
        "layer_parameter",
        "layer_role",
        "mask_parameter",
        "authoritative_layer_graph",
    ),
    (
        ("shield_layer", "MultiTextured", "_colorTextureG", "", "_rgbTexture", True),
        (
            "outfit_dye",
            "Standard",
            "_dyeingColorTexture",
            "dye",
            "_dyeingMaskTexture",
            False,
        ),
    ),
)
def test_package_only_replaces_base_for_authoritative_combiner_layer_graphs(
    tmp_path: Path,
    material_name: str,
    shader_family: str,
    layer_parameter: str,
    layer_role: str,
    mask_parameter: str,
    authoritative_layer_graph: bool,
) -> None:
    base = _image(tmp_path / f"{material_name}_base.png", (48, 44, 42, 255))
    layer = _image(tmp_path / f"{material_name}_layer.png", (120, 190, 95, 255))
    mask = _image(tmp_path / f"{material_name}_mask.png", (0, 255, 0, 255))
    submesh = _submesh(material_name)
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_baseColorTexture",
            preview_texture_path=str(base),
            semantic_type="color",
            semantic_subtype="albedo",
            shader_family=shader_family,
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name=layer_parameter,
            preview_texture_path=str(layer),
            semantic_type="color",
            semantic_subtype="detail_diffuse",
            shader_family=shader_family,
            layer_role=layer_role,
            layer_channel="g",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name=mask_parameter,
            preview_texture_path=str(mask),
            semantic_type="mask",
            semantic_subtype="mask",
            shader_family=shader_family,
            layer_role="mask",
            layer_channel="g",
            visualized=True,
        ),
    )

    payload = _write_manifest(tmp_path / "package", [submesh])
    binding = payload["submeshes"][0]

    assert payload["material_signature"] == "stable-material-signature"
    assert binding["raw_material_contract"]["layer_bindings"]
    if not authoritative_layer_graph:
        assert "shader_family_layer_graph" in binding["unsupported_features"]
        assert binding["synthesis_evidence"]["required_graph_compiled"] is False
        assert binding["material_synthesis"]["succeeded"] is False
        assert binding["material_synthesis"]["generated_channels"] == []
        assert binding["resolved_channels"] == binding["raw_resolved_channels"]
        assert binding["resolved_features"] == []
        return
    assert "shader_family_layer_graph" not in binding["unsupported_features"]
    assert binding["synthesis_evidence"]["required_graph_compiled"] is True
    assert binding["material_synthesis"]["succeeded"] is True
    assert "base" in binding["material_synthesis"]["generated_channels"]
    assert "preview_material_graph_baked" in binding["resolved_features"]
    assert binding["resolved_channels"]["base"] != binding["raw_resolved_channels"]["base"]
    assert binding["resource_channels"]["base"] == binding["resource_channels"]["albedo"]
    assert binding["resource_channels"]["base"] == binding["resource_channels"]["diffuse"]
    generated_resource = next(
        resource
        for resource in payload["resources"]
        if resource["resource_id"] == binding["resource_channels"]["base"]
    )
    assert generated_resource["semantic_authority"] == "synthesized_shared_combiner"
    assert (tmp_path / "package" / generated_resource["path"]).is_file()


def test_promoted_base_role_does_not_create_a_layer_graph(tmp_path: Path) -> None:
    base = _image(tmp_path / "hair_base.png", (96, 84, 72, 255))
    submesh = _submesh("hair")
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_baseColorTexture",
            preview_texture_path=str(base),
            semantic_type="color",
            semantic_subtype="albedo",
            shader_family="Hair",
            layer_role="base",
            binding_disposition="promoted",
            visualized=True,
        ),
    )

    payload = _write_manifest(tmp_path / "package", [submesh])
    binding = payload["submeshes"][0]

    assert binding["raw_material_contract"]["layer_bindings"] == []
    assert "shader_family_layer_graph" not in binding["unsupported_features"]
    assert binding["material_synthesis"]["attempted"] is False


def test_package_resolves_layer_graph_when_every_layer_reuses_its_base_source(
    tmp_path: Path,
) -> None:
    blackoil = _image(tmp_path / "blackoil.png", (0, 0, 0, 255))
    mask = _image(tmp_path / "mask.png", (255, 0, 0, 255))
    submesh = _submesh("identity_graph")
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_baseColorTexture",
            source_texture_path="character/texture/blackoil.dds",
            preview_texture_path=str(blackoil),
            semantic_type="base",
            shader_family="SkinnedMeshStandard",
            layer_role="base",
            binding_disposition="promoted",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_detailDiffuseMaskR",
            source_texture_path="character/texture/blackoil.dds",
            preview_texture_path=str(blackoil),
            semantic_type="base",
            shader_family="SkinnedMeshStandard",
            layer_role="detail",
            layer_channel="r",
            binding_disposition="layer_only",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="detail",
            parameter_name="_maskTexture",
            source_texture_path="character/texture/cd_temp_r_m.dds",
            preview_texture_path=str(mask),
            semantic_type="mask",
            shader_family="SkinnedMeshStandard",
            layer_role="material_response",
            binding_disposition="layer_only",
            visualized=True,
        ),
    )

    binding = _write_manifest(tmp_path / "package", [submesh])["submeshes"][0]

    assert binding["material_synthesis"]["attempted"] is True
    assert binding["material_synthesis"]["succeeded"] is True
    assert binding["material_synthesis"]["identity_noop"] is True
    assert binding["material_synthesis"]["generated_channels"] == []
    assert binding["resolved_channels"] == binding["raw_resolved_channels"]
    assert binding["resolved_features"] == ["preview_material_graph_identity"]
    assert "shader_family_layer_graph" not in binding["unsupported_features"]
    assert binding["synthesis_evidence"]["required_graph_compiled"] is True


def test_package_expands_generic_packed_mask_without_losing_source_v_orientation(
    tmp_path: Path,
) -> None:
    base = _image(tmp_path / "generic_base.png", (52, 64, 78, 255))
    normal = _image(tmp_path / "generic_normal.png", (128, 142, 255, 255))
    height = _image(tmp_path / "generic_height.png", (32, 96, 180, 255))
    packed = _image(tmp_path / "generic_orm.png", (220, 80, 190, 255))
    submesh = _submesh("generic_packed")
    submesh.preview_texture_flip_vertical = True
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="baseColorTexture",
            preview_texture_path=str(base),
            source_dds_path=str(base),
            semantic_type="color",
            semantic_subtype="albedo",
            confidence="gltf",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="normal",
            parameter_name="normalTexture",
            preview_texture_path=str(normal),
            source_dds_path=str(normal),
            semantic_type="normal",
            semantic_subtype="normal",
            confidence="gltf",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="height",
            parameter_name="heightTexture",
            preview_texture_path=str(height),
            source_dds_path=str(height),
            semantic_type="height",
            semantic_subtype="height",
            confidence="gltf",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="metallicRoughnessTexture",
            preview_texture_path=str(packed),
            semantic_type="material",
            semantic_subtype="metallic_roughness",
            packed_channels=("occlusion", "roughness", "metallic"),
            confidence="gltf",
            visualized=True,
        ),
    )

    payload = _write_manifest(tmp_path / "package", [submesh])
    binding = payload["submeshes"][0]

    generated = set(binding["material_synthesis"]["generated_channels"])
    assert {"roughness", "metallic"}.issubset(generated)
    assert generated <= {"occlusion", "roughness", "metallic", "specular"}
    metallic_summary = binding["material_synthesis"]["metallic_summary"]
    assert metallic_summary["sample_count"] > 0
    assert metallic_summary["q50"] > 0.5
    assert metallic_summary["coverage_above_0_25"] == 1.0
    assert binding["resolved_channels"]["base"] == str(base)
    assert binding["resolved_channels"]["normal"] == str(normal)
    assert binding["resolved_channels"]["height"] == str(height)
    changed_channels = {
        channel
        for channel in set(binding["raw_resolved_channels"]) | set(binding["resolved_channels"])
        if binding["raw_resolved_channels"].get(channel)
        != binding["resolved_channels"].get(channel)
    }
    assert changed_channels == generated
    assert binding["texture_flip_vertical"] is True
    assert binding["material_synthesis"]["texture_flip_vertical"] is True
    assert "mirrored-v" not in binding["material_synthesis"].get("base_note", "")
    assert "preview_support_maps_baked" in binding["resolved_features"]
    assert binding["channel_components"]["roughness"] == "r"
    assert binding["channel_components"]["metallic"] == "r"
    for channel in ("roughness", "metallic"):
        resource_id = binding["resource_channels"][channel]
        resource = next(item for item in payload["resources"] if item["resource_id"] == resource_id)
        assert resource["semantic_authority"] == "synthesized_shared_combiner"
        assert (tmp_path / "package" / resource["path"]).is_file()


def test_package_combiner_failure_preserves_raw_channels_and_unsupported_reporting(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base = _image(tmp_path / "base.png", (60, 70, 80, 255))
    layer = _image(tmp_path / "layer.png", (170, 90, 40, 255))
    submesh = _submesh("fallback")
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_baseColorTexture",
            preview_texture_path=str(base),
            semantic_type="color",
            shader_family="MultiTextured",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_colorTextureR",
            preview_texture_path=str(layer),
            semantic_type="color",
            shader_family="MultiTextured",
            layer_role="layer",
            layer_channel="r",
            visualized=True,
        ),
    )

    def fail(*_args, **_kwargs):
        raise RuntimeError("synthetic combiner failure")

    monkeypatch.setattr(mesh_dotnet_material_package, "combine_preview_material", fail)
    payload = _write_manifest(tmp_path / "package", [submesh])
    binding = payload["submeshes"][0]

    assert binding["material_synthesis"]["attempted"] is True
    assert binding["material_synthesis"]["succeeded"] is False
    assert "synthetic combiner failure" in binding["material_synthesis"]["failure"]
    assert binding["resolved_channels"] == binding["raw_resolved_channels"]
    assert binding["resolved_features"] == []
    assert "shader_family_layer_graph" in binding["unsupported_features"]


def test_cancelled_package_skips_new_synthesis_work_and_keeps_raw_fallback(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packed = _image(tmp_path / "packed.png", (10, 120, 240, 255))
    submesh = _submesh("cancelled")
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="material",
            preview_texture_path=str(packed),
            semantic_type="material",
            semantic_subtype="metallic_roughness",
            packed_channels=("roughness", "metallic"),
            visualized=True,
        ),
    )

    def forbidden(*_args, **_kwargs):
        raise AssertionError("cancelled package must not start material synthesis")

    monkeypatch.setattr(mesh_dotnet_material_package, "combine_preview_material", forbidden)
    raw_channels = mesh_dotnet_material_package._dotnet_resolved_texture_channels(submesh)
    raw_contract = mesh_dotnet_material_package._dotnet_material_semantic_contract(
        submesh,
        raw_channels,
        source_asset_path="archive/test.pac",
    )
    resolved, synthesis, generated = (
        mesh_dotnet_material_package._synthesize_dotnet_material_channels(
            submesh,
            raw_channels,
            raw_contract,
            output_dir=tmp_path / "cancelled-synthesis",
            batch_index=0,
            cancelled=lambda: True,
        )
    )

    assert synthesis == {
        "attempted": False,
        "succeeded": False,
        "skipped": "cancelled",
    }
    assert resolved == raw_channels
    assert generated == ()


def test_native_only_manifest_packed_inputs_are_typed_and_synthesized(
    tmp_path: Path,
) -> None:
    packed = _image(tmp_path / "native_only_orm.png", (210, 72, 184, 255))
    mesh = ParsedMesh(
        path="archive/native-only.pac",
        format="pac",
        submeshes=[_submesh("native_only")],
    )

    assert apply_dotnet_native_material_batch_bindings(
        mesh,
        (
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "dds_textures": {
                    "material_inputs": [
                        {
                            "slot": "material",
                            "source_path": str(packed),
                            "semantic_type": "material",
                            "semantic_subtype": "metallic_roughness",
                            "packed_channels": ["occlusion", "roughness", "metallic"],
                            "confidence": "native_manifest",
                        }
                    ]
                },
            },
        ),
    ) == 1
    typed_inputs = mesh.submeshes[0].preview_material_texture_inputs
    assert typed_inputs
    assert all(isinstance(item, PreviewMaterialTextureInput) for item in typed_inputs)

    payload = _write_manifest(tmp_path / "native-only-package", mesh.submeshes)
    binding = payload["submeshes"][0]
    assert binding["material_synthesis"]["succeeded"] is True
    assert "failure" not in binding["material_synthesis"]
    assert {"roughness", "metallic"}.issubset(
        binding["material_synthesis"]["generated_channels"]
    )


def test_native_only_manifest_layer_inputs_are_typed_and_synthesized(
    tmp_path: Path,
) -> None:
    base = _image(tmp_path / "native_layer_base.png", (42, 48, 54, 255))
    layer = _image(tmp_path / "native_layer_color.png", (180, 110, 62, 255))
    mask = _image(tmp_path / "native_layer_mask.png", (0, 255, 0, 255))
    mesh = ParsedMesh(
        path="archive/native-layer.pac",
        format="pac",
        submeshes=[_submesh("native_layer")],
    )

    assert apply_dotnet_native_material_batch_bindings(
        mesh,
        (
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "dds_textures": {
                    "material_inputs": [
                        {
                            "slot": "base",
                            "source_path": str(base),
                            "parameter_name": "_baseColorTexture",
                            "semantic_type": "color",
                            "semantic_subtype": "albedo",
                            "shader_family": "MultiTextured",
                        },
                        {
                            "slot": "material",
                            "source_path": str(layer),
                            "parameter_name": "_colorTextureG",
                            "semantic_type": "color",
                            "semantic_subtype": "detail_diffuse",
                            "shader_family": "MultiTextured",
                            "layer_role": "layer",
                            "layer_channel": "g",
                        },
                        {
                            "slot": "material",
                            "source_path": str(mask),
                            "parameter_name": "_rgbTexture",
                            "semantic_type": "mask",
                            "semantic_subtype": "mask",
                            "shader_family": "MultiTextured",
                            "layer_role": "mask",
                            "layer_channel": "g",
                        },
                    ]
                },
            },
        ),
    ) == 1
    assert all(
        isinstance(item, PreviewMaterialTextureInput)
        for item in mesh.submeshes[0].preview_material_texture_inputs
    )

    payload = _write_manifest(tmp_path / "native-layer-package", mesh.submeshes)
    binding = payload["submeshes"][0]
    assert binding["material_synthesis"]["succeeded"] is True
    assert "base" in binding["material_synthesis"]["generated_channels"]


def test_cancellation_during_material_pixel_synthesis_cleans_partial_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    packed = _image(
        tmp_path / "cancel_during_orm.png",
        (210, 72, 184, 255),
        size=(64, 64),
    )
    submesh = _submesh("cancel_during")
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="material",
            preview_texture_path=str(packed),
            source_dds_path=str(packed),
            semantic_type="material",
            semantic_subtype="metallic_roughness",
            packed_channels=("occlusion", "roughness", "metallic"),
            visualized=True,
        ),
    )
    entered_pixel_loop = False
    original_decode = material_combiner_images.decode_material_sample

    def tracked_decode(*args, **kwargs):
        nonlocal entered_pixel_loop
        entered_pixel_loop = True
        return original_decode(*args, **kwargs)

    monkeypatch.setattr(material_combiner_images, "decode_material_sample", tracked_decode)
    raw_channels = mesh_dotnet_material_package._dotnet_resolved_texture_channels(submesh)
    raw_contract = mesh_dotnet_material_package._dotnet_material_semantic_contract(
        submesh,
        raw_channels,
        source_asset_path="archive/test.pac",
    )
    output_dir = tmp_path / "cancelled-during-synthesis"

    resolved, synthesis, generated = (
        mesh_dotnet_material_package._synthesize_dotnet_material_channels(
            submesh,
            raw_channels,
            raw_contract,
            output_dir=output_dir,
            batch_index=0,
            cancelled=lambda: entered_pixel_loop,
        )
    )

    assert entered_pixel_loop is True
    assert resolved == raw_channels
    assert synthesis == {
        "attempted": True,
        "succeeded": False,
        "skipped": "cancelled_during_synthesis",
    }
    assert generated == ()
    assert not output_dir.exists()


def test_package_carries_archive_base_tint_and_texture_tint_separately(tmp_path: Path) -> None:
    base = _image(tmp_path / "shield_base.png", (92, 104, 116, 255))
    submesh = _submesh("shield")
    submesh.preview_texture_path = str(base)
    submesh.preview_color = (0.57, 0.39, 0.29)
    submesh.preview_texture_tint = (0.73, 0.44, 0.24)
    submesh.preview_native_material_overrides = {
        "base_tint_strength": 0.42,
        "material_category": "metal",
    }

    payload = _write_manifest(tmp_path / "package", [submesh])
    parameters = payload["submeshes"][0]["parameters"]

    assert parameters["base_tint_color"] == [0.57, 0.39, 0.29]
    assert parameters["base_tint_strength"] == 0.42
    assert parameters["base_tint_metallic"] is True
    assert parameters["texture_tint"] == [0.73, 0.44, 0.24]
    assert "tint_color" not in parameters


@pytest.mark.parametrize("shader_family", ["standard", "standard_v2"])
@pytest.mark.parametrize(
    "family_reason",
    [
        "metal:armor_family_material_response",
        "metal:equipment_family_material_response",
        "metal:weapon_family_material_response",
    ],
)
def test_synthesized_contract_requires_dominant_decoded_metal_for_equipment(
    shader_family: str,
    family_reason: str,
) -> None:
    source_contract = {
        "shader_family": shader_family,
        "material_category": "metal",
        "material_category_confidence": 0.9,
        "material_category_reason": family_reason,
        "material_response_promoted": True,
        "alpha_mode": "opaque",
        "alpha_authority": "guess",
    }

    soft = mesh_dotnet_material_package._refine_synthesized_material_contract(
        source_contract,
        {"generated_channels": ["roughness", "specular"]},
    )
    metal = mesh_dotnet_material_package._refine_synthesized_material_contract(
        source_contract,
        {
            "generated_channels": ["metallic", "roughness", "specular"],
            "metallic_summary": {
                "q50": 0.72,
                "q90": 0.86,
                "coverage_above_0_25": 0.91,
            },
        },
    )
    mixed = mesh_dotnet_material_package._refine_synthesized_material_contract(
        source_contract,
        {
            "generated_channels": ["metallic", "roughness", "specular"],
            "metallic_summary": {
                "q50": 0.03,
                "q90": 0.28,
                "coverage_above_0_25": 0.18,
            },
        },
    )

    assert soft["material_category"] == "generic"
    assert soft["material_response_promoted"] is False
    assert soft["material_category_reason"] == (
        "generic:equipment_material_response_without_decoded_metal_channel"
    )
    assert mixed["material_category"] == "generic"
    assert mixed["material_response_promoted"] is False
    assert mixed["material_category_reason"] == (
        "generic:equipment_material_response_without_dominant_decoded_metal_channel"
    )
    assert metal["material_category"] == "metal"
    assert metal["material_response_promoted"] is True
    assert metal["material_category_reason"] == (
        "metal:dominant_decoded_equipment_metal_channel"
    )
    assert metal["material_category_pre_synthesis_reason"] == family_reason


def test_dense_standard_v2_equipment_metal_response_survives_refinement() -> None:
    refined = mesh_dotnet_material_package._refine_synthesized_material_contract(
        {
            "shader_family": "standard_v2",
            "material_category": "metal",
            "material_category_confidence": 0.9,
            "material_category_reason": "metal:weapon_family_material_response",
            "material_response_promoted": True,
        },
        {
            "generated_channels": ["metallic", "roughness", "specular"],
            "metallic_summary": {
                "q50": 0.353,
                "q90": 0.408,
                "coverage_above_0_25": 0.964,
            },
        },
    )

    assert refined["material_category"] == "metal"
    assert refined["material_response_promoted"] is True
    assert refined["material_category_reason"] == (
        "metal:dominant_decoded_equipment_metal_channel"
    )


def test_dense_standard_v2_generic_weapon_part_promotes_only_in_equipment_path() -> None:
    contract = {
        "shader_family": "standard_v2",
        "material_category": "generic",
        "material_category_confidence": 0.35,
        "material_category_reason": "generic:no_strong_material_token",
        "material_response_promoted": False,
    }
    synthesis = {
        "generated_channels": ["metallic", "roughness", "specular"],
        "metallic_summary": {
            "q50": 0.494,
            "q90": 0.494,
            "coverage_above_0_25": 1.0,
        },
    }

    weapon = mesh_dotnet_material_package._refine_synthesized_material_contract(
        contract,
        synthesis,
        source_asset_path=(
            "character/model/1_pc/1_phm/weapon/2_twohandweapon/"
            "cd_phm_02_sword_0036.pac"
        ),
    )
    unrelated = mesh_dotnet_material_package._refine_synthesized_material_contract(
        contract,
        synthesis,
        source_asset_path="character/model/monster/example.pac",
    )

    assert weapon["material_category"] == "metal"
    assert weapon["material_response_promoted"] is True
    assert weapon["material_category_pre_synthesis_reason"] == (
        "generic:no_strong_material_token"
    )
    assert unrelated["material_category"] == "generic"
    assert unrelated["material_response_promoted"] is False


def test_dense_standard_v2_conserved_pac_metal_promotes_outside_equipment_path() -> None:
    contract = {
        "shader_family": "standard_v2",
        "material_category": "generic",
        "material_category_confidence": 0.35,
        "material_category_reason": "",
        "material_response_promoted": False,
        "source_contract": {
            "source_kind": "pac_xml",
            "binding_conservation": {
                "conserved": True,
            },
        },
    }
    synthesis = {
        "generated_channels": ["metallic", "roughness", "specular"],
        "metallic_summary": {
            "q50": 0.492,
            "q90": 0.494,
            "coverage_above_0_25": 1.0,
        },
    }

    refined = mesh_dotnet_material_package._refine_synthesized_material_contract(
        contract,
        synthesis,
        source_asset_path=(
            "character/model/monster/m0001/"
            "cd_m0001_00_sir_catfish_ub_00_0001.pac"
        ),
    )

    assert refined["material_category"] == "metal"
    assert refined["material_category_confidence"] == 0.88
    assert refined["material_response_promoted"] is True
    assert refined["material_category_reason"] == (
        "metal:dominant_decoded_pac_metal_channel"
    )


def test_dense_standard_v2_nonconserved_pac_metal_stays_generic() -> None:
    refined = mesh_dotnet_material_package._refine_synthesized_material_contract(
        {
            "shader_family": "standard_v2",
            "material_category": "generic",
            "material_category_confidence": 0.35,
            "material_category_reason": "",
            "material_response_promoted": False,
            "source_contract": {
                "source_kind": "pac_xml",
                "binding_conservation": {
                    "conserved": False,
                },
            },
        },
        {
            "generated_channels": ["metallic", "roughness", "specular"],
            "metallic_summary": {
                "q50": 0.492,
                "q90": 0.494,
                "coverage_above_0_25": 1.0,
            },
        },
        source_asset_path=(
            "character/model/monster/example/example_nonconserved.pac"
        ),
    )

    assert refined["material_category"] == "generic"
    assert refined["material_response_promoted"] is False


def test_sparse_inferred_hair_alpha_uses_opaque_card_fallback(tmp_path: Path) -> None:
    base = tmp_path / "sparse_inferred_hair.png"
    material = _image(tmp_path / "sparse_inferred_hair_sp.png", (255, 180, 0, 255))
    image = QImage(10, 10, QImage.Format.Format_RGBA8888)
    image.fill(QColor(86, 58, 42, 15))
    for x in range(9):
        image.setPixelColor(x, 0, QColor(86, 58, 42, 255))
    assert image.save(str(base), "PNG")
    submesh = _submesh("beard_card")
    submesh.preview_texture_path = str(base)
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_baseColorTexture",
            source_texture_path=str(base),
            preview_texture_path=str(base),
            semantic_type="color",
            semantic_subtype="albedo",
            shader_family="SkinnedMeshHairStandard",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_materialTexture",
            source_texture_path=str(material),
            preview_texture_path=str(material),
            semantic_type="material",
            semantic_subtype="specular",
            shader_family="SkinnedMeshHairStandard",
            visualized=True,
        ),
    )

    payload = _write_manifest(tmp_path / "sparse-hair-package", [submesh])
    binding = payload["submeshes"][0]

    assert binding["raw_material_contract"]["alpha_mode"] == "cutout"
    assert binding["raw_material_contract"]["alpha_authority"] == "inferred"
    assert binding["material_synthesis"]["base_alpha_summary"]["coverage_at_cutoff"] == 0.09
    assert binding["alpha_mode"] == "opaque"
    assert binding["alpha_authority"] == "inferred_fallback"
    assert "discard at least 90%" in binding["alpha_reason"]


def test_native_batch_tint_preserves_prepared_typed_inputs_for_package_synthesis(
    tmp_path: Path,
) -> None:
    base = _image(tmp_path / "shield_base.png", (48, 44, 42, 255))
    layer = _image(tmp_path / "shield_layer.png", (120, 190, 95, 255))
    mask = _image(tmp_path / "shield_mask.png", (0, 255, 0, 255))
    prepared_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            parameter_name="_baseColorTexture",
            preview_texture_path=str(base),
            semantic_type="color",
            semantic_subtype="albedo",
            shader_family="MultiTextured",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_colorTextureG",
            preview_texture_path=str(layer),
            semantic_type="color",
            semantic_subtype="detail_diffuse",
            shader_family="MultiTextured",
            layer_channel="g",
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_rgbTexture",
            preview_texture_path=str(mask),
            semantic_type="mask",
            semantic_subtype="mask",
            shader_family="MultiTextured",
            layer_role="mask",
            layer_channel="g",
            visualized=True,
        ),
    )
    mesh = ParsedMesh(
        path="archive/shield.pac",
        format="pac",
        submeshes=[_submesh("shield")],
    )
    preview_model = ModelPreviewData(
        path="archive/shield.pac",
        meshes=[
            ModelPreviewMesh(
                source_submesh_index=0,
                preview_color=(0.57, 0.39, 0.29),
                preview_texture_path=str(base),
                preview_material_texture_inputs=prepared_inputs,
            )
        ],
    )
    assert copy_dotnet_preview_material_bindings(mesh, preview_model) == 1
    copied_inputs = mesh.submeshes[0].preview_material_texture_inputs

    assert apply_dotnet_native_material_batch_bindings(
        mesh,
        (
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "base_color": [0.57, 0.39, 0.29],
                "base_tint_strength": 0.42,
                "texture_tint": [0.73, 0.44, 0.24],
                "material_category": "leather",
                "material_shader_family": "MultiTextured",
                "dds_textures": {
                    "base": {"slot": "base", "source_path": str(base)},
                    "material_inputs": [
                        {"slot": "base", "source_path": str(base)},
                        {"slot": "material", "source_path": str(layer)},
                        {"slot": "material", "source_path": str(mask)},
                    ],
                },
            },
        ),
    ) == 1
    assert mesh.submeshes[0].preview_material_texture_inputs is copied_inputs
    assert all(isinstance(item, PreviewMaterialTextureInput) for item in copied_inputs)

    payload = _write_manifest(tmp_path / "package", mesh.submeshes)
    binding = payload["submeshes"][0]
    assert binding["material_synthesis"]["attempted"] is True
    assert binding["material_synthesis"]["succeeded"] is True
    assert binding["parameters"]["base_tint_strength"] == 0.42
    assert binding["parameters"]["base_tint_metallic"] is False
    assert binding["parameters"]["texture_tint"] == [0.73, 0.44, 0.24]


def test_native_batch_rebases_matching_prepared_graph_inputs_to_durable_paths(
    tmp_path: Path,
) -> None:
    stale = tmp_path / "expired-cache" / "layer.dds"
    durable = tmp_path / "package" / "textures" / "layer.dds"
    durable.parent.mkdir(parents=True)
    durable.write_bytes(b"durable-dds")
    prepared = PreviewMaterialTextureInput(
        slot_kind="material",
        parameter_name="_detailMaterialMaskG",
        source_texture_path="character/texture/layer.dds",
        source_dds_path=str(stale),
        preview_texture_path=str(stale.with_suffix(".png")),
        semantic_type="material",
        semantic_subtype="specular",
        material_name="gauntlet_17",
        shader_family="SkinnedMeshStandard_Ver2",
        confidence="pac_exact",
        visualized=True,
        layer_role="detail",
        layer_channel="g",
        owner_slot_index=13,
        owner_wrapper_item_id="3825",
        binding_authority="authoritative",
        binding_disposition="layer_only",
        source_kind="crimson_layer_material",
    )
    submesh = _submesh("gauntlet_17")
    submesh.preview_material_texture_inputs = (prepared,)
    mesh = ParsedMesh(path="archive/gauntlet.pac", format="pac", submeshes=[submesh])

    assert apply_dotnet_native_material_batch_bindings(
        mesh,
        (
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "dds_textures": {
                    "material_inputs": [
                        {
                            "slot": "material",
                            "source_path": str(durable),
                            "parameter_name": "_detailMaterialMaskG",
                            "semantic_type": "material",
                            "semantic_subtype": "specular",
                            "material_name": "gauntlet_17",
                            "shader_family": "SkinnedMeshStandard_Ver2",
                            "layer_role": "detail",
                            "layer_channel": "g",
                            "owner_slot_index": 13,
                            "owner_wrapper_item_id": "3825",
                            "binding_authority": "authoritative",
                            "binding_disposition": "layer_only",
                            "source_kind": "crimson_layer_material",
                        }
                    ]
                },
            },
        ),
    ) == 1

    (rebased,) = submesh.preview_material_texture_inputs
    assert rebased is not prepared
    assert rebased.source_dds_path == str(durable)
    assert rebased.source_texture_path == "character/texture/layer.dds"
    assert rebased.preview_texture_path == str(durable)
    assert rebased.owner_slot_index == 13
    assert rebased.owner_wrapper_item_id == "3825"
    assert rebased.parameter_name == "_detailMaterialMaskG"
    assert rebased.confidence == "pac_exact"
    assert rebased.visualized is True


def test_native_batch_explicit_no_base_suppresses_stale_color_fallbacks(
    tmp_path: Path,
) -> None:
    stale_base = _image(tmp_path / "inferred_belt_base.png", (224, 206, 170, 255))
    material = _image(tmp_path / "belt_detail_mask.png", (90, 150, 210, 255))
    submesh = _submesh("collar")
    submesh.texture = str(stale_base)
    submesh.preview_texture_path = str(stale_base)
    submesh.preview_texture_dds_path = str(stale_base)
    submesh.preview_base_texture_default_path = str(stale_base)
    submesh.preview_base_texture_default_name = stale_base.name
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="base",
            semantic_type="color",
            semantic_subtype="albedo",
            source_dds_path=str(stale_base),
            preview_texture_path=str(stale_base),
            visualized=True,
        ),
        PreviewMaterialTextureInput(
            slot_kind="material",
            semantic_type="mask",
            semantic_subtype="detail_mask",
            source_dds_path=str(material),
            preview_texture_path=str(material),
            layer_role="detail",
            visualized=True,
        ),
    )
    mesh = ParsedMesh(
        path="archive/collar.pac",
        format="pac",
        submeshes=[submesh],
    )

    assert apply_dotnet_native_material_batch_bindings(
        mesh,
        (
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "base_color": [0.58, 0.44, 0.65],
                "textures": {
                    "base": "",
                    "material": "textures/detail_mask.png",
                },
                "dds_textures": {
                    "material": {
                        "slot": "material",
                        "source_path": str(material),
                    },
                    "material_inputs": [
                        {
                            "slot": "material",
                            "semantic_type": "mask",
                            "semantic_subtype": "detail_mask",
                            "source_path": str(material),
                            "layer_role": "detail",
                        },
                    ],
                },
            },
        ),
    ) == 1

    assert submesh.texture == ""
    assert submesh.preview_texture_path == ""
    assert submesh.preview_texture_dds_path == ""
    assert submesh.preview_base_texture_default_path == ""
    assert submesh.preview_base_texture_default_name == ""
    assert submesh.preview_native_material_overrides["base_tint_only_fallback"] is True
    assert len(submesh.preview_material_texture_inputs) == 1
    assert submesh.preview_material_texture_inputs[0].slot_kind == "material"

    payload = _write_manifest(tmp_path / "no-base-package", mesh.submeshes)
    binding = payload["submeshes"][0]
    for channels in (
        binding["raw_resolved_channels"],
        binding["resolved_channels"],
        binding["packaged_channels"],
    ):
        assert not {"albedo", "base", "diffuse"}.intersection(channels)
    assert binding["parameters"]["base_tint_color"] == [0.58, 0.44, 0.65]
    assert "material" in binding["raw_resolved_channels"]


def test_native_batch_rejects_layer_mask_mislabeled_as_base_descriptor(
    tmp_path: Path,
) -> None:
    mask = _image(tmp_path / "color_blending_mask.png", (255, 0, 0, 255))
    submesh = _submesh("guard")
    submesh.texture = str(mask)
    submesh.preview_texture_path = str(mask)
    submesh.preview_texture_dds_path = str(mask)
    submesh.preview_base_texture_default_path = str(mask)
    submesh.preview_base_texture_default_name = mask.name
    submesh.preview_material_texture_inputs = (
        PreviewMaterialTextureInput(
            slot_kind="material",
            parameter_name="_colorBlendingMaskTexture",
            source_texture_path="character/texture/guard_ma.dds",
            source_dds_path=str(mask),
            preview_texture_path=str(mask),
            semantic_type="material",
            layer_role="mask",
            owner_slot_index=0,
            owner_wrapper_item_id="2001",
            binding_authority="authoritative",
            binding_disposition="layer_only",
            source_kind="crimson_color_blending_mask",
        ),
    )
    mesh = ParsedMesh(path="archive/guard.pac", format="pac", submeshes=[submesh])

    assert apply_dotnet_native_material_batch_bindings(
        mesh,
        (
            {
                "editor_identity": {"source_local_submesh_index": 0},
                "textures": {"base": "textures/combined/guard_albedo.png"},
                "dds_textures": {
                    "base": {"slot": "base", "source_path": str(mask)},
                    "material_inputs": [
                        {
                            "slot": "material",
                            "source_path": str(mask),
                            "parameter_name": "_colorBlendingMaskTexture",
                            "semantic_type": "material",
                            "layer_role": "mask",
                            "owner_slot_index": 0,
                            "owner_wrapper_item_id": "2001",
                            "binding_authority": "authoritative",
                            "binding_disposition": "layer_only",
                            "source_kind": "crimson_color_blending_mask",
                        }
                    ],
                },
            },
        ),
    ) == 1

    assert submesh.texture == ""
    assert submesh.preview_texture_path == ""
    assert submesh.preview_texture_dds_path == ""
    assert submesh.preview_base_texture_default_path == ""
    assert submesh.preview_base_texture_default_name == ""
    assert submesh.preview_native_material_overrides["base_tint_only_fallback"] is True
    assert len(submesh.preview_material_texture_inputs) == 1
    assert submesh.preview_material_texture_inputs[0].parameter_name == (
        "_colorBlendingMaskTexture"
    )
