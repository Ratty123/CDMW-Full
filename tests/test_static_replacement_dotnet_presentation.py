from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.modding.static_mesh_types import StaticSourcePartAdjustment
from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    builder_part_highlight_state,
    builder_presentation_state,
    effective_builder_comparison_mode,
    send_resident_presentation_state,
)
from cdmw.ui.archive_browser.static_replacement_dotnet_view_modes import (
    DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES,
    DOTNET_PREVIEW_VIEW_MODES,
)
from cdmw.ui.archive_browser.static_replacement_dialog_sections_mesh_geometry_preview_part_01 import (
    _bind_embedded_mesh_editor_preview,
)
from cdmw.ui.model_preview_settings_visibility import (
    DOTNET_CAMERA_INPUT_SETTING_FIELDS,
    DOTNET_GIZMO_APPEARANCE_SETTING_FIELDS,
    DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS,
)
from cdmw.ui.mesh_editor.tab_dotnet_protocol import MeshEditorDotNetProtocolMixin
from cdmw.ui.mesh_editor.tab_dotnet_presentation import MeshEditorDotNetPresentationMixin
from cdmw.ui.mesh_editor.tab_state import MeshEditorStateMixin


ROOT = Path(__file__).resolve().parents[1]


class _PreviewValueControl:
    def __init__(self, value: object) -> None:
        self.value = value

    def currentData(self) -> object:
        return self.value

    def isChecked(self) -> bool:
        return bool(self.value)


def test_builder_presentation_state_carries_all_outer_control_families() -> None:
    settings = ModelPreviewRenderSettings(
        d3d11_view_mode="normal",
        high_quality_by_default=True,
        d3d11_light_azimuth_degrees=45.0,
        d3d11_normal_y_mode="force_flip",
        d3d11_texture_address_mode="clamp",
        force_nearest_no_mipmaps=True,
        height_effect_max=0.35,
        specular_max=0.44,
        shininess_max=96.0,
    )
    state = builder_presentation_state(
        comparison_mode="side_by_side",
        camera={"yaw": 30.0, "pitch": -10.0, "fit_to_view": True},
        render_settings=settings,
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=True,
        selected_source_indices=(4,),
        selected_target_source_indices=(2,),
        selected_original_indices=(7,),
        hovered_source_index=3,
        source_part_adjustments={
            2: StaticSourcePartAdjustment(
                source_submesh_index=2,
                enabled=False,
                offset_xyz=(1.0, 2.0, 3.0),
                material_role="armor",
            )
        },
        uv_state={"flip_u": True, "flip_v": False, "rotate_degrees": 90.0},
        side_by_side_split_ratio=0.63,
    )

    assert state["active_view"] == "comparison"
    assert state["side_by_side_split_ratio"] == 0.63
    assert state["camera"] == {"yaw": 30.0, "pitch": -10.0, "fit_to_view": True}
    assert state["display"]["mode"] == "untextured_wire"  # type: ignore[index]
    assert state["display"]["material_debug_mode"] == 2  # type: ignore[index]
    assert state["display"]["quality"]["d3d11_normal_y_mode"] == "force_flip"  # type: ignore[index]
    assert state["display"]["quality"]["d3d11_texture_address_mode"] == "clamp"  # type: ignore[index]
    assert state["display"]["quality"]["force_nearest_no_mipmaps"] is True  # type: ignore[index]
    assert state["display"]["quality"]["height_effect_max"] == 0.35  # type: ignore[index]
    assert state["display"]["quality"]["specular_max"] == 0.44  # type: ignore[index]
    assert state["display"]["quality"]["shininess_max"] == 96.0  # type: ignore[index]
    assert state["highlights"]["source_indices"] == [2, 4]  # type: ignore[index]
    assert state["visibility"]["hidden_submesh_indices"] == [2]  # type: ignore[index]
    assert state["part_transforms"]["2"]["offset_xyz"] == [1.0, 2.0, 3.0]  # type: ignore[index]
    assert state["uv"] == {"flip_u": True, "flip_v": False, "rotate_degrees": 90.0}


def test_builder_presentation_state_defaults_mesh_edit_to_wire_vertices() -> None:
    state = builder_presentation_state(
        comparison_mode="replacement_only",
        camera=None,
        render_settings=ModelPreviewRenderSettings(d3d11_view_mode="lit"),
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=False,
        mesh_edit_active=True,
    )

    assert state["display"]["mode"] == "wire_vertices"  # type: ignore[index]
    assert state["display"]["gizmo_visible"] is False  # type: ignore[index]


def test_builder_presentation_state_starts_with_readable_untextured_wire() -> None:
    state = builder_presentation_state(
        comparison_mode="replacement_only",
        camera=None,
        render_settings=ModelPreviewRenderSettings(use_textures_by_default=True),
        grid_visible=True,
        gizmo_visible=False,
        part_pick_enabled=False,
    )

    assert state["display"]["mode"] == "untextured_wire"  # type: ignore[index]


def test_builder_presentation_state_preserves_selected_mesh_view_mode() -> None:
    state = builder_presentation_state(
        comparison_mode="replacement_only",
        display_mode="textured_wire",
        camera=None,
        render_settings=ModelPreviewRenderSettings(),
        grid_visible=True,
        gizmo_visible=False,
        part_pick_enabled=False,
    )

    assert state["display"]["mode"] == "textured_wire"  # type: ignore[index]


def test_builder_mesh_view_selector_uses_the_resident_presentation_lane() -> None:
    shell = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_preview_shell.py"
    ).read_text(encoding="utf-8")
    callbacks = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_callbacks_preview_mode_part_01.py"
    ).read_text(encoding="utf-8")
    prompt_callbacks = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_prompt_state_callbacks.py"
    ).read_text(encoding="utf-8")
    presentation_getter = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_sections_mesh_geometry_preview_part_01.py"
    ).read_text(encoding="utf-8")

    assert 'setObjectName("MeshAlignmentViewportDisplayModeCombo")' in shell
    assert "MESH_PREVIEW_DEFAULT_DISPLAY_MODE" in shell
    assert "StaticReplacementPromptStateControls.from_mapping(context)" in prompt_callbacks
    assert (
        "controls.preview_mesh_view_combo.currentIndexChanged.connect(_set_preview_display_mode)"
        in prompt_callbacks
    )
    assert '"_mesh_editor_embedded_request_viewport_display"' in callbacks
    assert "request_display(mode)" in callbacks
    assert '{"display": {"mode": mode}}' in callbacks
    assert '"set_viewport_display_mode"' in callbacks
    assert "display_mode=_state.preview_mesh_view_combo.currentData()" in presentation_getter


def test_builder_part_highlight_state_uses_logical_scene_indices() -> None:
    state = builder_part_highlight_state(
        selection_active=True,
        highlighted_source_indices=(4, 2, 4),
        highlighted_original_indices=(7, 3, 7),
        hovered_source_index=2,
        hidden_source_indices=(6, 1, 6),
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=True,
        mesh_edit_active=True,
    )

    assert state["highlights"] == {
        "source_indices": [2, 4],
        "original_indices": [3, 7],
        "hovered_source_index": 2,
    }
    assert state["visibility"] == {"hidden_submesh_indices": [1, 6]}
    assert state["display"]["gizmo_visible"] is False  # type: ignore[index]


def test_parts_routing_incremental_highlight_does_not_reuse_legacy_preview_ids() -> None:
    source = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_callbacks_preview_mode_part_01.py"
    ).read_text(encoding="utf-8")
    start = source.index("resident_state = builder_part_highlight_state(")
    end = source.index("if send_resident_presentation_state", start)
    resident_update = source[start:end]

    assert "selection_state['highlighted_source_indices']" in resident_update
    assert "selection_state['highlighted_original_indices']" in resident_update
    assert "selection_state['d3d11_highlighted_indices']" not in resident_update
    assert "selection_state['d3d11_original_highlighted_indices']" not in resident_update
    assert "mesh_edit_active=bool(_state.mesh_edit_enabled_checkbox.isChecked())" in resident_update


def test_builder_presentation_state_carries_every_exposed_dotnet_preview_setting() -> None:
    state = builder_presentation_state(
        comparison_mode="side_by_side",
        camera=None,
        render_settings=ModelPreviewRenderSettings(
            gizmo_x_axis_color="#123456",
            gizmo_line_thickness_pixels=2.5,
        ),
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=True,
    )
    quality = state["display"]["quality"]  # type: ignore[index]
    expected = set(DOTNET_CAMERA_INPUT_SETTING_FIELDS) | set(DOTNET_GIZMO_APPEARANCE_SETTING_FIELDS)
    assert expected == DOTNET_SUPPORTED_PREVIEW_SETTING_FIELDS
    assert expected <= set(quality)
    assert quality["gizmo_x_axis_color"] == "#123456"
    assert quality["gizmo_line_thickness_pixels"] == 2.5
    assert "visible_texture_mode" not in quality


def test_preview_settings_dotnet_target_covers_the_whole_embedded_mesh_editor() -> None:
    source = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_callbacks_remaining_preview_render_settings_part_01.py"
    ).read_text(encoding="utf-8")
    start = source.index("preview_target = (")
    end = source.index("_state.self._open_modal_model_preview_settings_dialog(", start)
    target_selection = source[start:end]

    assert "_mesh_editor_embedded_dotnet_active" in target_selection
    assert "mesh_edit_enabled_checkbox" not in target_selection
    assert "mesh_edit_active" not in target_selection
    assert "'dotnet_vortice'" in target_selection
    assert "'archive_dotnet_vortice'" in target_selection
    assert "'native_d3d11'" not in target_selection


def test_builder_presentation_state_maps_every_preview_mode_to_its_resident_view() -> None:
    expected = {
        "side_by_side": "comparison",
        "overlay": "comparison",
        "replacement_only": "editable",
        "original_only": "reference",
    }

    for mode, active_view in expected.items():
        state = builder_presentation_state(
            comparison_mode=mode,
            camera=None,
            render_settings=ModelPreviewRenderSettings(),
            grid_visible=True,
            gizmo_visible=True,
            part_pick_enabled=True,
        )
        assert state["comparison_mode"] == mode
        assert state["active_view"] == active_view


def test_edit_mesh_effective_mode_is_always_replacement_only() -> None:
    for mode in ("side_by_side", "overlay", "replacement_only", "original_only"):
        assert effective_builder_comparison_mode(mode, mesh_edit_active=True) == "replacement_only"
        assert effective_builder_comparison_mode(mode, mesh_edit_active=False) == mode


def test_embedded_builder_presentation_getter_reads_current_render_settings() -> None:
    initial = ModelPreviewRenderSettings(disable_lighting=False, d3d11_tone_exposure=1.0)
    current = {"settings": initial}
    dialog = SimpleNamespace()
    callbacks = SimpleNamespace(
        _mesh_editor_action_bar_action_requested=lambda *_args, **_kwargs: None,
        _mesh_editor_embedded_controller=lambda: None,
        _mesh_editor_embedded_placement_state=lambda: {},
        _mesh_editor_embedded_apply_native_update=lambda *_args, **_kwargs: False,
        _mesh_editor_embedded_finalize_dotnet_import=lambda *_args, **_kwargs: False,
        _mesh_editor_embedded_run_part_action=lambda *_args, **_kwargs: False,
        _mesh_editor_embedded_set_skeleton_bone=lambda *_args, **_kwargs: False,
    )
    state = SimpleNamespace(
        dialog=dialog,
        _alignment_current_camera_state=lambda: {},
        _current_alignment_preview_render_settings=None,
        _current_preview_render_settings=lambda: current["settings"],
        preview_render_settings=initial,
        hovered_source_part={},
        alignment_d3d11_preview_host=SimpleNamespace(
            remember_side_by_side_split_ratio=lambda *_args: 0.5,
        ),
        self=SimpleNamespace(settings=SimpleNamespace(setValue=lambda *_args: None)),
        preview_mode_combo=_PreviewValueControl("replacement_only"),
        preview_mesh_view_combo=_PreviewValueControl("untextured_wire"),
        preview_gizmo_checkbox=_PreviewValueControl(True),
        preview_part_pick_checkbox=_PreviewValueControl(True),
        mesh_edit_enabled_checkbox=_PreviewValueControl(False),
        selected_source_highlight_indices=set(),
        selected_target_source_highlight_indices=set(),
        selected_original_highlight_indices=set(),
        selected_target_original_highlight_indices=set(),
        source_part_adjustments={},
        texture_uv_global_transform_state={},
        alignment_mesh_edit_callbacks=callbacks,
        _current_static_alignment_transform=lambda: {},
        original_mesh_for_mapping=None,
        _current_original_reference_preview_model=lambda: None,
    )
    _bind_embedded_mesh_editor_preview(state)

    current["settings"] = ModelPreviewRenderSettings(
        disable_lighting=True,
        d3d11_tone_exposure=0.35,
    )
    payload = dialog._mesh_editor_embedded_presentation_state()
    quality = payload["display"]["quality"]

    assert quality["disable_lighting"] is True
    assert quality["d3d11_tone_exposure"] == 0.35

    state.preview_mode_combo.value = "original_only"
    state.mesh_edit_enabled_checkbox.value = True
    edit_payload = dialog._mesh_editor_embedded_presentation_state()

    assert edit_payload["comparison_mode"] == "replacement_only"
    assert edit_payload["active_view"] == "editable"
    assert dialog._mesh_editor_embedded_comparison_mode() == "replacement_only"
    assert dialog._mesh_editor_embedded_placement_comparison_mode() == "original_only"


def test_every_dotnet_view_mode_routes_to_a_supported_shader_output() -> None:
    expected_debug_modes = {
        "lit": 0,
        "game_outdoor": 0,
        "base_direct": 1,
        "normal": 2,
        "uv_checker": 8,
        "base_alpha": 9,
        "part_id": 10,
        "material_response": 11,
        "layer_mask": 12,
    }
    assert tuple(expected_debug_modes) == DOTNET_PREVIEW_VIEW_MODES
    assert expected_debug_modes == DOTNET_PREVIEW_VIEW_MODE_DEBUG_MODES

    for view_mode, debug_mode in expected_debug_modes.items():
        state = builder_presentation_state(
            comparison_mode="side_by_side",
            camera=None,
            render_settings=ModelPreviewRenderSettings(d3d11_view_mode=view_mode),
            grid_visible=True,
            gizmo_visible=True,
            part_pick_enabled=True,
        )
        assert state["display"]["material_debug_mode"] == debug_mode  # type: ignore[index]
        assert state["display"]["quality"]["dotnet_view_mode"] == view_mode  # type: ignore[index]


def test_resident_visible_texture_mode_change_reloads_reference_materials_before_return() -> None:
    source = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_callbacks_remaining_preview_render_settings_part_01.py"
    ).read_text(encoding="utf-8")

    assert "visible_texture_mode_changed" in source
    assert "_stop_original_reference_texture_worker()" in source
    assert "_load_original_reference_texture_preview()" in source
    assert source.index("if visible_texture_mode_changed") < source.index("if presentation_sent:")
    assert "preview_target=preview_target" in source
    assert "'_mesh_editor_embedded_dotnet_active'" in source
    assert "'dotnet_vortice'" in source
    assert "'archive_dotnet_vortice'" in source


def test_builder_presentation_state_clamps_role_pane_split_ratio() -> None:
    settings = ModelPreviewRenderSettings()
    low = builder_presentation_state(
        comparison_mode="side_by_side",
        camera=None,
        render_settings=settings,
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=True,
        side_by_side_split_ratio=-4.0,
    )
    high = builder_presentation_state(
        comparison_mode="side_by_side",
        camera=None,
        render_settings=settings,
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=True,
        side_by_side_split_ratio=9.0,
    )

    assert low["side_by_side_split_ratio"] == 0.18
    assert high["side_by_side_split_ratio"] == 0.82


def test_role_pane_split_event_routes_to_active_builder_persistence_callback() -> None:
    events: list[dict[str, object]] = []
    ratios: list[float] = []
    state = SimpleNamespace(
        _append_dotnet_protocol_event=lambda payload: events.append(dict(payload)),
        active_builder=lambda: SimpleNamespace(
            _mesh_editor_embedded_split_ratio_changed=lambda ratio: ratios.append(ratio) or True
        ),
    )
    payload = {"event": "presentation_split_changed", "ratio": 0.61}

    assert MeshEditorDotNetProtocolMixin._handle_dotnet_protocol_event(state, payload)
    assert events == [payload]
    assert ratios == [0.61]


def test_builder_role_pane_split_uses_shared_persisted_ratio() -> None:
    host_source = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(
        encoding="utf-8"
    )
    builder_source = (
        ROOT
        / "cdmw"
        / "ui"
        / "archive_browser"
        / "static_replacement_dialog_sections_mesh_geometry_preview_part_01.py"
    ).read_text(encoding="utf-8")

    assert "def remember_side_by_side_split_ratio(self, ratio: Optional[float] = None) -> float:" in host_source
    assert "_mesh_editor_embedded_split_ratio_changed" in builder_source
    assert "remember_side_by_side_split_ratio" in builder_source
    assert "ui/mesh_alignment/d3d11_side_by_side_split_ratio" in builder_source


def test_resident_presentation_bridge_never_calls_inactive_or_missing_sender() -> None:
    calls: list[dict[str, object]] = []
    dialog = SimpleNamespace(
        _mesh_editor_embedded_dotnet_active=False,
        _mesh_editor_embedded_set_presentation_state=lambda state: calls.append(state) or True,
    )
    assert not send_resident_presentation_state(dialog, {"camera": {"preset": "front"}})
    assert calls == []

    dialog._mesh_editor_embedded_dotnet_active = True
    assert send_resident_presentation_state(dialog, {"camera": {"preset": "front"}})
    assert calls == [{"camera": {"preset": "front"}}]


def test_resident_presentation_merge_does_not_mutate_caller_nested_state() -> None:
    baseline = {"display": {"quality": {"disable_lighting": False}}}
    desired: dict[str, object] = {}

    MeshEditorDotNetPresentationMixin._merge_dotnet_presentation_state(desired, baseline)
    MeshEditorDotNetPresentationMixin._merge_dotnet_presentation_state(
        desired,
        {"display": {"quality": {"disable_lighting": True}}},
    )

    assert baseline == {"display": {"quality": {"disable_lighting": False}}}
    assert desired == {"display": {"quality": {"disable_lighting": True}}}


def test_resident_presentation_queue_has_one_active_and_one_merged_pending_state() -> None:
    sent: list[dict[str, object]] = []
    state = MeshEditorStateMixin()
    state.standalone_dotnet_presentation_request_id = 0
    state.standalone_dotnet_presentation_generation = 0
    state.standalone_dotnet_presentation_pending = None
    state.standalone_dotnet_presentation_queued = False
    state.standalone_dotnet_presentation_desired = {}
    state.standalone_dotnet_presentation_acknowledged = None
    state.standalone_dotnet_protocol_events = []
    state.standalone_dotnet_process_generation = 8
    state._standalone_dotnet_editor_process_running = lambda: True
    state._dotnet_target_controller = lambda: SimpleNamespace(
        session_view=lambda: SimpleNamespace(session_id="session-a", revision=12)
    )
    state._send_dotnet_protocol_message = lambda payload: sent.append(dict(payload)) or True
    state._flush_dotnet_protocol_messages = lambda: True
    state._dotnet_session_matches = lambda _payload: True
    state._set_dotnet_status = lambda *_args, **_kwargs: None
    state._append_dotnet_protocol_event = lambda payload: (
        MeshEditorDotNetProtocolMixin._append_dotnet_protocol_event(state, payload)
    )

    assert state._send_dotnet_presentation_state({"camera": {"preset": "front"}})
    assert len(sent) == 1
    assert state._send_dotnet_presentation_state({"display": {"mode": "wire"}})
    assert len(sent) == 1
    assert state.standalone_dotnet_presentation_queued is True

    ack = {
        "event": "presentation_state_update_ack",
        "status": "applied",
        "session_id": "session-a",
        "request_id": 1,
        "process_generation": 8,
    }
    assert MeshEditorDotNetProtocolMixin._handle_dotnet_presentation_state_ack(state, ack)
    assert state.standalone_dotnet_protocol_events == [ack]
    assert len(sent) == 2
    assert sent[1]["camera"]["preset"] == "front"
    assert sent[1]["camera"]["command_generation"] == 1
    assert sent[1]["display"] == {"mode": "wire"}
    assert sent[1]["request_id"] == 2

    ack["request_id"] = 2
    assert MeshEditorDotNetProtocolMixin._handle_dotnet_presentation_state_ack(state, ack)
    assert state._send_dotnet_presentation_state(
        {"camera": {"preset": "front"}, "display": {"mode": "solid"}}
    )
    assert sent[2]["camera"]["command_generation"] == 1

    ack["request_id"] = 3
    assert MeshEditorDotNetProtocolMixin._handle_dotnet_presentation_state_ack(state, ack)
    assert state._send_dotnet_presentation_state({"camera": {"preset": "front"}})
    assert sent[3]["camera"]["command_generation"] == 2


def test_legacy_diagnostic_mode_does_not_override_the_selected_dotnet_view() -> None:
    lit = builder_presentation_state(
        comparison_mode="replacement_only",
        camera=None,
        render_settings=ModelPreviewRenderSettings(
            d3d11_view_mode="lit",
            render_diagnostic_mode="wireframe",
        ),
        grid_visible=False,
        gizmo_visible=False,
        part_pick_enabled=False,
    )
    assert lit["display"]["mode"] == "untextured_wire"  # type: ignore[index]
    assert lit["display"]["material_debug_mode"] == 0  # type: ignore[index]
    assert "render_diagnostic_mode" not in lit["display"]["quality"]  # type: ignore[index]

    uv = builder_presentation_state(
        comparison_mode="replacement_only",
        camera=None,
        render_settings=ModelPreviewRenderSettings(d3d11_view_mode="uv_checker"),
        grid_visible=False,
        gizmo_visible=False,
        part_pick_enabled=False,
    )
    assert uv["display"]["material_debug_mode"] == 8  # type: ignore[index]
