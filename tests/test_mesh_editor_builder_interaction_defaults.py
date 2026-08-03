"""Real Qt Builder coverage for the neutral Mesh Editor opening contract."""

from __future__ import annotations

from functools import partial
from types import SimpleNamespace

import pytest

from tests.mesh_builder_driver import open_mesh_builder


class _ResidentToolStateHost:
    def __init__(self) -> None:
        self.tool_states: list[dict[str, object]] = []
        self.alignment_states: list[dict[str, object]] = []
        self.alignment_transform_count = 0

    def set_mesh_edit_state(self, **payload: object) -> bool:
        self.tool_states.append(dict(payload))
        return True

    def set_alignment_state(self, **payload: object) -> bool:
        self.alignment_states.append(dict(payload))
        return True

    def set_alignment_preview_transform(self) -> bool:
        self.alignment_transform_count += 1
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
        assert host.alignment_states == []
        assert host.alignment_transform_count == 0


def test_real_builder_tool_click_publishes_one_tool_state_without_scene_or_display_replay() -> None:
    with open_mesh_builder(
        modify_original_clone_mode=True,
        dialog_title="Mesh Editor tool publication",
    ) as builder:
        sync = builder.control("_sync_mesh_edit_preview_settings")
        adopt_tool = builder.control("_mesh_editor_dotnet_tool_changed")
        assert isinstance(sync, partial)
        assert isinstance(adopt_tool, partial)
        state, callbacks = sync.args[:2]
        host = _ResidentToolStateHost()
        state.alignment_d3d11_preview_host = host
        state._alignment_d3d11_preview_active = lambda: True
        state._mesh_edit_tab_active = lambda: True
        callbacks._mesh_edit_can_edit_scope = lambda: (True, "")
        state.mesh_edit_enabled_checkbox.blockSignals(True)
        state.mesh_edit_enabled_checkbox.setChecked(True)
        state.mesh_edit_enabled_checkbox.blockSignals(False)
        action_state_updates: list[dict[str, object]] = []
        state.self.mesh_editor_tab = SimpleNamespace(
            update_editor_action_state=lambda **payload: action_state_updates.append(
                dict(payload)
            )
        )

        assert adopt_tool({"tool": "grab"})

        assert state.mesh_edit_tool_combo.currentData() == "grab"
        assert [payload["tool"] for payload in host.tool_states] == ["grab"]
        assert len(action_state_updates) == 1
        assert action_state_updates[0]["publish_native"] is False
        assert host.alignment_states == []
        assert host.alignment_transform_count == 0


def test_real_builder_finish_restores_controls_and_leaves_edit_mesh() -> None:
    with open_mesh_builder(
        modify_original_clone_mode=True,
        dialog_title="Mesh Editor Finish shell restoration",
    ) as builder:
        controls_panel = builder.control("controls_panel")
        edit_checkbox = builder.checkbox("MeshEditModeCheckbox")
        finalize = getattr(
            builder.dialog,
            "_mesh_editor_embedded_finalize_dotnet_import",
            None,
        )
        assert callable(finalize)

        builder.set_mesh_edit(True)
        controls_panel.setVisible(False)
        builder.pump()
        assert edit_checkbox.isChecked()
        assert controls_panel.isHidden()

        assert finalize("dotnet_finish_edit")
        builder.pump()

        assert not edit_checkbox.isChecked()
        assert not controls_panel.isHidden()
        assert controls_panel.isVisible()
