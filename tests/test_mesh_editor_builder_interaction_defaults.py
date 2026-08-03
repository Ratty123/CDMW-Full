"""Real Qt Builder coverage for the neutral Mesh Editor opening contract."""

from __future__ import annotations

from functools import partial

import pytest

from tests.mesh_builder_driver import open_mesh_builder


class _ResidentToolStateHost:
    def __init__(self) -> None:
        self.tool_states: list[dict[str, object]] = []

    def set_mesh_edit_state(self, **payload: object) -> bool:
        self.tool_states.append(dict(payload))
        return True

    def set_alignment_state(self, **_payload: object) -> bool:
        return True

    def set_alignment_preview_transform(self) -> bool:
        return True

    def update_mesh_edit_vertices(self, _groups: object) -> bool:
        return True

    def replace_mesh_edit_triangles(self, _groups: object, **_payload: object) -> bool:
        return True


@pytest.mark.parametrize("modify_original_clone_mode", (False, True))
def test_real_builder_opens_dotnet_in_orbit_with_part_brush_defaults(
    modify_original_clone_mode: bool,
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title="Mesh Editor neutral defaults",
    ) as builder:
        sync = builder.control("_sync_mesh_edit_preview_settings")
        assert isinstance(sync, partial)
        state, callbacks = sync.args[:2]
        host = _ResidentToolStateHost()
        state.alignment_d3d11_preview_host = host
        state._alignment_d3d11_preview_active = lambda: True
        state._mesh_edit_tab_active = lambda: True
        callbacks._mesh_edit_can_edit_scope = lambda: (True, "")
        state.mesh_edit_enabled_checkbox.blockSignals(True)
        state.mesh_edit_enabled_checkbox.setChecked(True)
        state.mesh_edit_enabled_checkbox.blockSignals(False)

        sync()

        assert state.mesh_edit_tool_combo.currentData() == "orbit"
        assert state.mesh_edit_selection_mode_combo.currentData() == "brush"
        assert host.tool_states
        payload = host.tool_states[-1]
        assert payload["enabled"] is False
        assert payload["tool"] == "orbit"
        assert payload["target_mode"] == "source"
        assert payload["selection_mode"] == "brush"
        assert payload["selection_operation"] == "add"
        assert payload["selection_depth_mode"] == "visible"
