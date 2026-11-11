"""Grime follows the preview-wide decision in the Python combiner too."""
from __future__ import annotations

from cdmw.models import PreviewMaterialTextureInput
from cdmw.rendering.material_combiner_rules import _select_visible_layer_inputs


def _layer(role: str, parameter: str, path: str) -> PreviewMaterialTextureInput:
    return PreviewMaterialTextureInput(
        slot_kind="base",
        parameter_name=parameter,
        source_texture_path=f"character/texture/{path}",
        source_dds_path=f"C:/cache/{path}",
        semantic_type="base",
        layer_role=role,
        layer_channel="r",
        binding_authority="authoritative",
        source_kind="crimson_material_sidecar",
    )


def _selected(monkeypatch, value: str | None) -> set[str]:
    if value is None:
        monkeypatch.delenv("CDMW_PREVIEW_DRAW_GRIME", raising=False)
    else:
        monkeypatch.setenv("CDMW_PREVIEW_DRAW_GRIME", value)
    inputs = (
        _layer("detail", "_detailDiffuseMaskR", "detail.dds"),
        _layer("grime", "_grimeDiffuseTextureR", "grime.dds"),
    )
    return {item.parameter_name for item in _select_visible_layer_inputs(inputs, selected_base=None)}


def test_grime_is_left_out_of_synthesised_albedo_by_default(monkeypatch) -> None:
    assert _selected(monkeypatch, None) == {"_detailDiffuseMaskR"}


def test_grime_returns_with_the_shared_preview_switch(monkeypatch) -> None:
    assert _selected(monkeypatch, "1") == {"_detailDiffuseMaskR", "_grimeDiffuseTextureR"}
