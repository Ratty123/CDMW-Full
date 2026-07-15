from __future__ import annotations

from pathlib import Path

from tests.native_source_text import d3d11_preview_source


def test_native_preview_material_authority_protocol_source_contract() -> None:
    d3d11_text = d3d11_preview_source()
    host_text = Path("cdmw/ui/native_d3d11_preview_host.py").read_text(encoding="utf-8")

    for fragment in (
        'json_has_field(payload, "roughness_hint_present")',
        'json_has_field(payload, "emissive_color_authoritative")',
        'json_has_field(payload, "emissive_scalar_mask")',
        "batch.roughness_hint_present = json_bool_field",
        "batch.emissive_color_authoritative = json_bool_field",
        "uint material_hint_presence = (uint)round(material_value_params.w);",
        "bool has_material_roughness_hint = (material_hint_presence & 1u) != 0u;",
        "bool emissive_color_authoritative = material_params.z > 0.5;",
        "bool emissive_scalar_mask = material_params.w > 0.5;",
        "max(emissive_color, emissive_sample.rgb)",
    ):
        assert fragment in d3d11_text

    for fragment in (
        '("roughness_hint_present", roughness_hint_present)',
        'payload["emissive_color_authoritative"] = bool(emissive_color_authoritative)',
        '("emissive_scalar_mask", emissive_scalar_mask)',
    ):
        assert fragment in host_text
