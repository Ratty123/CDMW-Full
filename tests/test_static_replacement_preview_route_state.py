from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_static_preview_state import (
    static_preview_refresh_route_state,
)


def test_static_preview_refresh_route_state_keeps_external_materials_and_tracks_original_readiness() -> None:
    route = static_preview_refresh_route_state(
        active_preview_mode="replacement_only",
        mesh_edit_enabled=False,
        mesh_edit_tab_active=False,
        replacement_mesh_available=True,
        interactive_preview=False,
        complete_external_swap_enabled=False,
        needs_original_material_preview=False,
        preview_controls_ready=True,
        original_mesh_available=True,
    )

    assert route.mesh_edit_direct_source_preview is False
    assert route.replacement_only_direct_source_preview is False
    assert route.source_owned_direct_source_preview is True
    assert route.require_original_reference is True
    assert route.can_build_source_geometry is True
    assert route.waits_for_original_reference(ready=False) is False

    mesh_edit_route = static_preview_refresh_route_state(
        active_preview_mode="side_by_side",
        mesh_edit_enabled=True,
        mesh_edit_tab_active=True,
        replacement_mesh_available=True,
        interactive_preview=True,
        complete_external_swap_enabled=True,
        needs_original_material_preview=False,
        preview_controls_ready=False,
        original_mesh_available=True,
    )

    assert mesh_edit_route.mesh_edit_direct_source_preview is False
    assert mesh_edit_route.replacement_only_direct_source_preview is False
    assert mesh_edit_route.source_owned_direct_source_preview is True
    assert mesh_edit_route.require_original_reference is True
    assert mesh_edit_route.can_build_source_geometry is False
    assert mesh_edit_route.waits_for_original_reference(ready=False) is True
    assert mesh_edit_route.waits_for_original_reference(ready=True) is False
