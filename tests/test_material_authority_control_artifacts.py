from __future__ import annotations

import threading
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from cdmw.core.dds_native import inspect_dds_native_path
from cdmw.core.texture_native import find_directxtex_texture_binary
from cdmw.domain.textures.material_authority_state import (
    MATERIAL_AUTHORITY_AUTOMATIC_KEYS,
    MATERIAL_AUTHORITY_EXPERT_KEYS,
    MATERIAL_AUTHORITY_MANUAL_KEYS,
)
from cdmw.domain.textures.material_parameters import (
    evaluate_material_parameters,
    material_parameter_renderer_overrides,
)
from cdmw.modding.material_profiles import (
    apply_true_source_basic_controls_to_profile,
    get_complete_swap_material_profile,
    serialize_complete_swap_manual_material_profile,
)
from cdmw.modding.material_replacer import ReplacementTextureSet, ReplacementTextureSlot
from cdmw.services.material_authority_resource_service import (
    _channel_preset_key,
    _encode_owned_dds,
    _encode_owned_image_dds_batch,
    generate_material_authority_resource_bindings,
)

_ALL_CHANNELS = ("base", "normal", "height", "material_mask", "emissive")


def test_scalar_surface_channels_use_uncompressed_linear_scalar_preset() -> None:
    for channel in ("roughness", "metallic", "metalness", "occlusion"):
        assert _channel_preset_key(channel) == "height_scalar"
    assert _channel_preset_key("specular") == "mask_packed"


def test_scalar_surface_encoder_writes_full_mip_linear_r8(tmp_path: Path) -> None:
    if find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    source = tmp_path / "roughness.png"
    target = tmp_path / "roughness.dds"
    Image.new("RGB", (8, 8), (73, 73, 73)).save(source)

    _encode_owned_dds(
        source,
        target,
        "roughness",
        threading.Event(),
        source_color_policy="ignore_srgb_metadata",
    )

    info = inspect_dds_native_path(target)
    assert info.reason == ""
    assert info.format_name == "R8_UNORM"
    assert info.srgb is False
    assert info.mip_count == 4


@pytest.mark.parametrize(
    ("channel", "expected_format", "expected_srgb", "expected_fast_preview"),
    (
        ("base", "R8G8B8A8_UNORM_SRGB", True, True),
        ("material_mask", "R8G8B8A8_UNORM", False, True),
        ("normal", "BC5_UNORM", False, False),
        ("roughness", "R8_UNORM", False, False),
    ),
)
def test_rust_preview_skips_only_expensive_bc7_compression(
    tmp_path: Path,
    channel: str,
    expected_format: str,
    expected_srgb: bool,
    expected_fast_preview: bool,
) -> None:
    if find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    source = tmp_path / f"{channel}.png"
    target = tmp_path / f"{channel}.dds"
    source_image = Image.new("RGBA", (8, 8), (73, 41, 19, 157))
    source_image.save(source)

    artifact = _encode_owned_dds(
        source,
        target,
        channel,
        threading.Event(),
        source_color_policy=(
            "assume_srgb" if channel == "base" else "ignore_srgb_metadata"
        ),
        preview_uncompressed_max_bytes=1024 * 1024,
    )

    info = inspect_dds_native_path(target)
    assert info.reason == ""
    assert info.format_name == expected_format
    assert info.srgb is expected_srgb
    assert info.mip_count == 4
    assert artifact["preview_uncompressed"] is expected_fast_preview
    if expected_fast_preview:
        payload = target.read_bytes()
        base_level = info.mip_levels[0]
        assert (
            payload[
                base_level.offset : base_level.offset + base_level.byte_count
            ]
            == source_image.tobytes()
        )


def test_rust_preview_keeps_bc7_when_uncompressed_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    if find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    source = tmp_path / "base.png"
    target = tmp_path / "base.dds"
    Image.new("RGBA", (8, 8), (73, 41, 19, 255)).save(source)

    artifact = _encode_owned_dds(
        source,
        target,
        "base",
        threading.Event(),
        source_color_policy="assume_srgb",
        preview_uncompressed_max_bytes=1,
    )

    info = inspect_dds_native_path(target)
    assert info.reason == ""
    assert info.format_name == "BC7_UNORM_SRGB"
    assert artifact["preview_uncompressed"] is False


@pytest.mark.parametrize("source_format", ("PNG", "JPEG", "TGA", "WEBP"))
def test_external_preview_images_use_one_native_encode_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    source_format: str,
) -> None:
    if find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    from cdmw.core import texture_native

    base_source = tmp_path / f"base.{source_format.lower()}"
    normal_source = tmp_path / "normal.png"
    base_target = tmp_path / "base.dds"
    normal_target = tmp_path / "normal.dds"
    Image.new("RGB", (64, 32), (73, 41, 19)).save(base_source, format=source_format)
    source_bytes = base_source.read_bytes()
    Image.new("RGBA", (8, 8), (128, 128, 255, 255)).save(normal_source)
    original_batch = texture_native.encode_dds_batch_with_directxtex
    request_counts: list[int] = []
    native_inputs: list[Path] = []

    def recording_batch(jobs: object, **kwargs: object) -> object:
        requests = tuple(jobs)  # type: ignore[arg-type]
        request_counts.append(len(requests))
        native_inputs.extend(request.input_path for request in requests)
        return original_batch(requests, **kwargs)

    monkeypatch.setattr(
        texture_native,
        "encode_dds_batch_with_directxtex",
        recording_batch,
    )
    artifacts = _encode_owned_image_dds_batch(
        (
            (base_source, base_target, "base"),
            (normal_source, normal_target, "normal"),
        ),
        threading.Event(),
        preview_uncompressed_max_bytes=1024 * 1024,
        max_dimension=16,
    )

    assert request_counts == [2]
    assert len(artifacts) == 2
    assert base_target.is_file()
    assert normal_target.is_file()
    base_info = inspect_dds_native_path(base_target)
    normal_info = inspect_dds_native_path(normal_target)
    assert base_info.reason == ""
    assert (base_info.width, base_info.height) == (16, 8)
    assert normal_info.reason == ""
    assert (normal_info.width, normal_info.height) == (8, 8)
    assert (artifacts[0]["width"], artifacts[0]["height"]) == (16, 8)
    assert base_source.read_bytes() == source_bytes
    assert native_inputs[1] == normal_source
    if source_format == "PNG":
        assert native_inputs[0] == base_source
    else:
        assert native_inputs[0] != base_source
        assert not native_inputs[0].exists()


@pytest.mark.parametrize("cancel", (False, True))
def test_external_preview_normalized_images_are_removed_on_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, cancel: bool,
) -> None:
    from cdmw.core import texture_native
    from cdmw.domain.cancellation import RunCancelled

    source = tmp_path / "base.jpg"
    Image.new("RGB", (8, 8), (73, 41, 19)).save(source)
    source_bytes = source.read_bytes()
    native_inputs: list[Path] = []
    failure = RunCancelled if cancel else RuntimeError

    def failed_batch(jobs: object, **kwargs: object) -> object:
        requests = tuple(jobs)  # type: ignore[arg-type]
        native_inputs.extend(request.input_path for request in requests)
        assert native_inputs[0].read_bytes().startswith(b"\x89PNG\r\n\x1a\n")
        raise failure("test encode interrupted")

    monkeypatch.setattr(texture_native, "encode_dds_batch_with_directxtex", failed_batch)
    with pytest.raises(failure, match="test encode interrupted"):
        _encode_owned_image_dds_batch(
            ((source, tmp_path / "base.dds", "base"),), threading.Event(),
        )

    assert native_inputs
    assert not native_inputs[0].parent.exists()
    assert not (tmp_path / "base.dds").exists()
    assert source.read_bytes() == source_bytes


@pytest.mark.parametrize("srgb_metadata", (False, True))
def test_external_preview_batch_preserves_colour_and_data_pixels(
    tmp_path: Path, srgb_metadata: bool,
) -> None:
    if find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    from PIL.PngImagePlugin import PngInfo

    source = tmp_path / "source.png"
    pixels = Image.new("RGBA", (8, 8))
    pixels.putdata([(8, 7, 6, 255), (73, 41, 19, 157), (170, 139, 69, 255), (255, 80, 234, 255)] * 16)
    metadata = PngInfo()
    if srgb_metadata:
        metadata.add(b"sRGB", b"\0")
    pixels.save(source, pnginfo=metadata)
    jobs = tuple((source, tmp_path / f"{role}.dds", role) for role in ("base", "emissive", "material_mask"))

    _encode_owned_image_dds_batch(
        jobs, threading.Event(), preview_uncompressed_max_bytes=1024 * 1024,
    )

    for _source, target, role in jobs:
        info = inspect_dds_native_path(target)
        assert info.srgb is (role != "material_mask")
        level = info.mip_levels[0]
        assert target.read_bytes()[level.offset : level.offset + level.byte_count] == pixels.tobytes()


def _manual(values: dict[str, object]) -> object:
    return get_complete_swap_material_profile(
        serialize_complete_swap_manual_material_profile(values)
    )


def _automatic(**values: object) -> object:
    return apply_true_source_basic_controls_to_profile(
        get_complete_swap_material_profile("material_authority_detail_mask"),
        **values,
    )


def _write_fixture(root: Path, variant: str) -> ReplacementTextureSet:
    root.mkdir(parents=True, exist_ok=True)
    slot_names = {
        "full": {"base", "normal", "height", "emissive", "roughness", "metallic", "ao"},
        "base_only": {"base"},
        "base_emissive": {"base", "emissive"},
        "missing_roughness": {"base", "normal", "height", "emissive", "metallic", "ao"},
        "missing_metallic": {"base", "normal", "height", "emissive", "roughness", "ao"},
        "missing_ao": {"base", "normal", "height", "emissive", "roughness", "metallic"},
        "factor_base": {"normal", "height"},
        "factor_mask": {"base", "normal", "height"},
    }[variant]
    slots: dict[str, ReplacementTextureSlot] = {}
    for slot_name in sorted(slot_names):
        path = root / f"{slot_name}.png"
        pixels: list[tuple[int, int, int, int]] = []
        for y in range(8):
            for x in range(8):
                value = 24 + x * 21 + y * 8
                if slot_name == "base":
                    pixel = (value, 220 - x * 14, 35 + y * 23, 255)
                elif slot_name == "emissive":
                    pixel = (40 + x * 23, 18 + y * 19, 210 - x * 11, 255)
                elif slot_name == "normal":
                    pixel = (128 + x, 128 - y, 245, 255)
                else:
                    pixel = (value, value, value, 255)
                pixels.append(tuple(max(0, min(255, component)) for component in pixel))
        image = Image.new("RGBA", (8, 8))
        image.putdata(pixels)
        image.save(path)
        slots[slot_name] = ReplacementTextureSlot("Blade", slot_name, path)
    if variant == "factor_base":
        factor_path = root / "blade_base_factor.png"
        Image.new("RGBA", (8, 8), (51, 178, 230, 255)).save(factor_path)
        slots["base"] = ReplacementTextureSlot(
            "Blade",
            "base",
            factor_path,
            source_authority="synthetic",
            base_color_factor=(0.2, 0.7, 0.9),
        )
    return ReplacementTextureSet(
        "Blade",
        slots=slots,
        base_color_factor=(0.2, 0.7, 0.9) if variant == "factor_base" else None,
        roughness_factor=0.25 if variant == "factor_mask" else None,
        metallic_factor=0.8 if variant == "factor_mask" else None,
        occlusion_strength=0.6 if variant == "factor_mask" else None,
    )


def _resource_signature(
    texture_set: ReplacementTextureSet,
    profile: object,
    output_root: Path,
) -> dict[str, tuple[object, ...]]:
    # These assertions are about what the real DirectXTex encoder writes into each
    # canonical channel, so there is nothing to check without it. The texture
    # backend has no Python fallback by design.
    if find_directxtex_texture_binary() is None:
        pytest.skip("cd-texture-dx is not built")
    bindings = generate_material_authority_resource_bindings(
        (("Blade", texture_set),),
        profile,
        _ALL_CHANNELS,
        output_root,
        threading.Event(),
    )
    signature: dict[str, tuple[object, ...]] = {}
    for binding in bindings:
        channel = str(binding.get("channel", "") or "")
        if channel == "material":
            channel = "material_mask"
        signature[channel] = (
            bool(binding.get("remove", False)),
            str(binding.get("content_sha256", "") or ""),
            str(binding.get("dds_format", "") or ""),
            str(binding.get("color_space", "") or ""),
            int(binding.get("mip_count", 0) or 0),
        )
    return signature


_ARTIFACT_CASES = (
    ("global_gloss_reduction", "full", {"material_mask"}, _automatic(), _automatic(gloss_reduction=100)),
    ("auto_brightness", "full", {"base"}, _automatic(), _automatic(auto_brightness_balance=100)),
    ("source_brightness", "full", {"base"}, _automatic(), _automatic(dark_detail_lift=100)),
    ("tone_contrast", "full", {"base"}, _automatic(), _automatic(tone_contrast=100)),
    ("edge_relief", "base_only", {"normal", "height", "material_mask"}, _automatic(), _automatic(edge_relief_strength=100, edge_relief_source="generate_source")),
    ("edge_relief_source", "base_only", {"normal", "height", "material_mask"}, _automatic(edge_relief_strength=100, edge_relief_source="preserve_target"), _automatic(edge_relief_strength=100, edge_relief_source="generate_source")),
    ("base_binding_mode", "full", {"base"}, _manual({"base_binding_mode": "overlay_texture"}), _manual({"base_binding_mode": "disabled"})),
    ("mask_binding_mode", "full", {"material_mask"}, _manual({"mask_binding_mode": "detail_mask_material"}), _manual({"mask_binding_mode": "disabled"})),
    ("support_policy", "base_only", {"normal", "height", "material_mask"}, _manual({"support_policy": "source_only"}), _manual({"support_policy": "generated_or_neutral"})),
    ("emissive_mode", "full", {"emissive"}, _manual({"emissive_mode": "intensity"}), _manual({"emissive_mode": "disabled"})),
    ("base_color_lift", "full", {"base"}, _manual({"base_color_lift": 0}), _manual({"base_color_lift": 110})),
    ("base_color_gamma", "full", {"base"}, _manual({"base_color_gamma": 1.0}), _manual({"base_color_gamma": 0.35})),
    ("base_color_saturation", "full", {"base"}, _manual({"base_color_saturation": 1.0}), _manual({"base_color_saturation": 0.0})),
    ("base_color_value_max", "full", {"base"}, _manual({"base_color_value_max": 255}), _manual({"base_color_value_max": 96})),
    ("base_color_scale", "full", {"base"}, _manual({"base_color_scale": 1.0}), _manual({"base_color_scale": 0.25})),
    ("emissive_color_scale", "full", {"emissive"}, _manual({"emissive_color_scale": 1.0}), _manual({"emissive_color_scale": 0.2})),
    ("emissive_color_saturation", "full", {"emissive"}, _manual({"emissive_color_saturation": 1.0}), _manual({"emissive_color_saturation": 0.0})),
    ("emissive_color_value_max", "full", {"emissive"}, _manual({"emissive_color_value_max": 255}), _manual({"emissive_color_value_max": 72})),
    ("roughness_default", "missing_roughness", {"material_mask"}, _manual({"roughness_default": 255}), _manual({"roughness_default": 32})),
    ("roughness_min", "full", {"material_mask"}, _manual({"roughness_min": 0}), _manual({"roughness_min": 200})),
    ("roughness_scale", "full", {"material_mask"}, _manual({"roughness_min": 0, "roughness_scale": 0.5}), _manual({"roughness_min": 0, "roughness_scale": 1.5})),
    ("roughness_max", "full", {"material_mask"}, _manual({"roughness_min": 0, "roughness_max": 255}), _manual({"roughness_min": 0, "roughness_max": 80})),
    ("metallic_default", "missing_metallic", {"material_mask"}, _manual({"metallic_default": 0}), _manual({"metallic_default": 220})),
    ("metallic_min", "full", {"material_mask"}, _manual({"metallic_min": 0}), _manual({"metallic_min": 180})),
    ("metallic_scale", "full", {"material_mask"}, _manual({"metallic_scale": 0.4}), _manual({"metallic_scale": 1.6})),
    ("metallic_max", "full", {"material_mask"}, _manual({"metallic_max": 255}), _manual({"metallic_max": 80})),
    ("ao_default", "missing_ao", {"material_mask"}, _manual({"ao_default": 255}), _manual({"ao_default": 32})),
    ("force_nonmetal", "full", {"material_mask"}, _manual({"force_nonmetal": False}), _manual({"force_nonmetal": True})),
    ("roughness_inverted", "full", {"material_mask"}, _manual({"roughness_min": 0, "roughness_inverted": False}), _manual({"roughness_min": 0, "roughness_inverted": True})),
    ("metallic_inverted", "full", {"material_mask"}, _manual({"metallic_inverted": False}), _manual({"metallic_inverted": True})),
    ("allow_factor_only_authority", "factor_base", {"base"}, _manual({"allow_factor_only_authority": False}), _manual({"allow_factor_only_authority": True})),
    ("factor_only_material_mask", "factor_mask", {"material_mask"}, _manual({"factor_only_material_mask": False}), _manual({"factor_only_material_mask": True})),
    ("force_neutral_layer_support", "base_only", {"normal", "height", "material_mask"}, _manual({"support_policy": "source_only", "force_neutral_layer_support": False}), _manual({"support_policy": "source_only", "force_neutral_layer_support": True})),
)


@pytest.mark.parametrize(
    ("control_key", "fixture", "affected_channels", "baseline", "changed"),
    _ARTIFACT_CASES,
    ids=[case[0] for case in _ARTIFACT_CASES],
)
def test_every_artifact_control_changes_only_its_declared_canonical_channels(
    tmp_path: Path,
    control_key: str,
    fixture: str,
    affected_channels: set[str],
    baseline: object,
    changed: object,
) -> None:
    texture_set = _write_fixture(tmp_path / "source", fixture)
    before = _resource_signature(texture_set, baseline, tmp_path / "before")
    after = _resource_signature(texture_set, changed, tmp_path / "after")
    changed_channels = {
        channel for channel in _ALL_CHANNELS if before.get(channel) != after.get(channel)
    }

    assert changed_channels, f"{control_key} produced no canonical DDS/binding delta"
    assert changed_channels <= affected_channels


def test_selected_part_glow_color_changes_only_emissive_dds(tmp_path: Path) -> None:
    texture_set = _write_fixture(tmp_path / "source", "full")
    texture_set.source_role_tags = ("glow",)
    profile = _manual({"emissive_mode": "intensity"})
    texture_set.accent_glow_color_rgb = (1.0, 0.0, 0.0)
    before = _resource_signature(texture_set, profile, tmp_path / "red")
    texture_set.accent_glow_color_rgb = (0.0, 0.0, 1.0)
    after = _resource_signature(texture_set, profile, tmp_path / "blue")

    assert before["emissive"] != after["emissive"]
    assert all(before[channel] == after[channel] for channel in _ALL_CHANNELS if channel != "emissive")


@pytest.mark.parametrize(
    ("control_key", "baseline", "changed", "parameter"),
    (
        (
            "accent_glow",
            evaluate_material_parameters(_automatic(), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=1.0, emissive_color_rgb=())),
            evaluate_material_parameters(_automatic(accent_glow_strength=100), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=1.0, emissive_color_rgb=())),
            "emissive_intensity",
        ),
        (
            "part_glow_strength",
            evaluate_material_parameters(_automatic(), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=1.0, emissive_color_rgb=())),
            evaluate_material_parameters(_automatic(), part_adjustment=SimpleNamespace(material_role="glow", emissive_strength=3.0, emissive_color_rgb=())),
            "emissive_intensity",
        ),
        (
            "displacement_scale_multiplier",
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 0.2, "displacement_scale_max": 1.0})),
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 0.8, "displacement_scale_max": 1.0})),
            "height_scale",
        ),
        (
            "displacement_scale_max",
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 1.0, "displacement_scale_max": 0.2})),
            evaluate_material_parameters(_manual({"displacement_scale_multiplier": 1.0, "displacement_scale_max": 0.8})),
            "height_scale",
        ),
    ),
)
def test_parameter_backed_controls_change_the_canonical_parameter(
    control_key: str,
    baseline: object,
    changed: object,
    parameter: str,
) -> None:
    before = material_parameter_renderer_overrides(baseline)
    after = material_parameter_renderer_overrides(changed)

    assert before.get(parameter) != after.get(parameter), control_key


def test_effect_matrix_covers_every_normal_control_exactly_once() -> None:
    # Per-part controls are authored on the source-part adjustment rather than
    # the material profile, so they have no profile-driven generation case
    # above; they are still artifact controls that rewrite the baked channel.
    artifact_keys = {case[0] for case in _ARTIFACT_CASES} | {
        "part_glow_color",
        "part_colourise_color",
        "part_colourise_strength",
    }
    parameter_keys = {
        "accent_glow",
        "part_glow_strength",
        "displacement_scale_multiplier",
        "displacement_scale_max",
    }
    normal_keys = (MATERIAL_AUTHORITY_AUTOMATIC_KEYS | MATERIAL_AUTHORITY_MANUAL_KEYS) - MATERIAL_AUTHORITY_EXPERT_KEYS

    assert artifact_keys | parameter_keys == normal_keys
    assert not artifact_keys & parameter_keys
