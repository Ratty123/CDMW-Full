from __future__ import annotations

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.static_replacement_d3d11_state import (
    alignment_d3d11_mark_loaded_package,
    alignment_d3d11_package_quality,
)


def test_alignment_d3d11_package_quality_keeps_loaded_material_frame_during_geometry_rebuild() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True)

    result_settings, high_quality, material_combiner, package_quality = alignment_d3d11_package_quality(
        settings,
        {
            "fast_geometry_loaded": False,
            "archive_parity_ready": False,
            "material_complete_preview_seen": True,
        },
        reason="geometry",
        mesh_edit_raw_preview_active=False,
    )

    assert result_settings.use_textures_by_default is False
    assert high_quality is False
    assert material_combiner is False
    assert package_quality == "archive_parity"


def test_material_complete_frame_authority_survives_active_package_handoff() -> None:
    settings = ModelPreviewRenderSettings(use_textures_by_default=True, high_quality_by_default=True)
    state: dict[str, object] = {}
    alignment_d3d11_mark_loaded_package(state, package_quality="archive_parity")
    state.update(
        preview_loaded=False,
        active_package_quality="",
        fast_geometry_loaded=False,
        archive_parity_ready=False,
    )

    _result_settings, _high_quality, _combiner, quality = alignment_d3d11_package_quality(
        settings,
        state,
        reason="geometry",
        mesh_edit_raw_preview_active=False,
    )

    assert state["material_complete_preview_seen"] is True
    assert quality == "archive_parity"
