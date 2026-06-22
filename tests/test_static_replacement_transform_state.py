from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace

import pytest

from cdmw.ui.archive_browser.static_replacement_transform_state import (
    DEFAULT_GLOBAL_TRANSFORM_VALUES,
    active_tab_is,
    alignment_global_fast_preview_state,
    alignment_linked_scale_sync_state,
    alignment_part_delta_refresh_state,
    alignment_part_fast_preview_state,
    alignment_part_transform_preview_queue_indices,
    alignment_global_rotation_origin_state,
    alignment_preview_commit_state,
    alignment_preview_drag_prepare_state,
    alignment_rotation_nudge_value,
    alignment_preview_rotation_context_state,
    alignment_transform_control_text,
    alignment_transform_generation_initial_state,
    alignment_transform_location_original_text,
    alignment_transform_preview_queue_state,
    alignment_transform_reset_state,
    alignment_preview_is_interactive,
    capture_static_preview_baked_transform_state,
    current_alignment_transform_generation,
    mesh_edit_raw_preview_active,
    scale_syncing_initial_state,
    source_part_transform_values,
    spinbox_transform_values,
    static_preview_baked_transform_initial_state,
    static_preview_interactive_until_initial_state,
)
from cdmw.ui.archive_browser.static_replacement_transform_control_state import (
    alignment_global_transform_layout_specs,
    alignment_global_transform_reset_button_specs,
    alignment_global_transform_row_specs,
    alignment_global_transform_spin_commit_state,
    alignment_global_transform_spin_specs,
    alignment_global_transform_slider_specs,
    alignment_global_transform_tilt_button_specs,
    alignment_transform_slider_sync_state,
)


def test_scale_syncing_initial_state_preserves_default() -> None:
    assert scale_syncing_initial_state() == {"active": False}


def test_alignment_global_transform_spin_specs_preserve_ranges() -> None:
    specs = alignment_global_transform_spin_specs()
    assert specs["offset"] == {"value": 0.0, "minimum": -10.0, "maximum": 10.0, "decimals": 5, "step": 0.0005}
    assert specs["rotation"] == {
        "value": 0.0,
        "minimum": -360.0,
        "maximum": 360.0,
        "decimals": 2,
        "step": 0.10,
        "suffix": " deg",
    }
    assert specs["scale"] == {"value": 1.0, "minimum": 0.001, "maximum": 100.0, "decimals": 4, "step": 0.005}
    assert specs["tilt_step"] == {
        "value": 2.0,
        "minimum": 0.1,
        "maximum": 45.0,
        "decimals": 1,
        "step": 0.25,
        "suffix": " deg",
    }


def test_alignment_global_transform_slider_specs_preserve_ranges() -> None:
    assert alignment_global_transform_slider_specs() == {
        "offset": {"slider_scale": 2000.0},
        "rotation": {"slider_scale": 10.0},
        "scale": {"slider_scale": 1000.0, "slider_minimum": 0.1, "slider_maximum": 3.0},
    }


def test_alignment_global_transform_layout_specs_preserve_ui_values() -> None:
    assert alignment_global_transform_layout_specs() == {
        "margins": (5, 3, 5, 3),
        "horizontal_spacing": 5,
        "vertical_spacing": 2,
        "column_stretches": ((0, 0), (1, 0), (2, 1)),
        "column_minimum_widths": ((0, 66), (1, 126)),
        "spin_minimum_width": 76,
        "slider_object_name": "AlignmentTransformSlider",
        "slider_minimum_width": 92,
        "reset_button_minimum_width": 0,
        "tilt_step_minimum_width": 72,
    }


def test_alignment_global_transform_row_specs_preserve_rows() -> None:
    assert alignment_global_transform_row_specs() == (
        {
            "row_index": 1,
            "label_key": "location_label",
            "original_source": "original_center",
            "widget_group": "offset",
            "slider_spec": "offset",
        },
        {
            "row_index": 2,
            "label_key": "rotation_label",
            "original_key": "rotation_original",
            "widget_group": "rotation",
            "slider_spec": "rotation",
        },
        {
            "row_index": 3,
            "label_key": "scale_label",
            "original_key": "scale_original",
            "widget_group": "scale",
            "slider_spec": "scale",
        },
    )


def test_alignment_global_transform_button_specs_preserve_order() -> None:
    assert alignment_global_transform_reset_button_specs() == (
        {"key": "location", "text_key": "reset_location"},
        {"key": "rotation", "text_key": "reset_rotation"},
        {"key": "scale", "text_key": "reset_scale"},
        {"key": "placement", "text_key": "reset_placement"},
    )
    assert alignment_global_transform_tilt_button_specs() == (
        {"key": "x_minus", "text_key": "tilt_x_minus", "tooltip_key": "tilt_x_minus_tooltip", "axis": "x", "direction": -1.0},
        {"key": "x_plus", "text_key": "tilt_x_plus", "tooltip_key": "tilt_x_plus_tooltip", "axis": "x", "direction": 1.0},
        {"key": "y_minus", "text_key": "tilt_y_minus", "tooltip_key": "tilt_y_minus_tooltip", "axis": "y", "direction": -1.0},
        {"key": "y_plus", "text_key": "tilt_y_plus", "tooltip_key": "tilt_y_plus_tooltip", "axis": "y", "direction": 1.0},
        {"key": "z_minus", "text_key": "tilt_z_minus", "tooltip_key": "tilt_z_minus_tooltip", "axis": "z", "direction": -1.0},
        {"key": "z_plus", "text_key": "tilt_z_plus", "tooltip_key": "tilt_z_plus_tooltip", "axis": "z", "direction": 1.0},
    )


@dataclass
class FakeSpinBox:
    raw_value: object

    def value(self) -> object:
        return self.raw_value


class RaisingSpinBox:
    def value(self) -> object:
        raise RuntimeError("deleted widget")


def test_alignment_transform_control_text_preserves_labels_and_tooltips() -> None:
    text = alignment_transform_control_text()

    assert text["export_group_title"] == "Export Values"
    assert text["export_property_header"] == "Property"
    assert text["export_original_header"] == "Original"
    assert text["export_values_header"] == "Export values"
    assert (text["axis_x"], text["axis_y"], text["axis_z"]) == ("X", "Y", "Z")
    assert text["location_label"] == "Location"
    assert text["rotation_label"] == "Rotation"
    assert text["scale_label"] == "Scale"
    assert text["rotation_original"] == "0.00, 0.00, 0.00 deg"
    assert text["scale_original"] == "1.0000, 1.0000, 1.0000"
    assert text["axis_slider_tooltip_template"] == "{label} {axis} slider. Numeric entry remains available above."
    assert text["link_scale_axes"] == "Link scale axes"
    assert text["reset_location"] == "Reset Location"
    assert text["reset_rotation"] == "Reset Rotation"
    assert text["reset_scale"] == "Reset Scale"
    assert text["reset_placement"] == "Reset Placement"
    assert text["tilt_step_label"] == "Tilt step"
    assert text["tilt_step_tooltip"] == "Step used by the tilt/turn/roll buttons."
    assert text["tilt_x_minus"] == "Tilt X-"
    assert text["tilt_x_plus"] == "Tilt X+"
    assert text["tilt_y_minus"] == "Turn Y-"
    assert text["tilt_y_plus"] == "Turn Y+"
    assert text["tilt_z_minus"] == "Roll Z-"
    assert text["tilt_z_plus"] == "Roll Z+"
    assert text["tilt_x_minus_tooltip"] == "Pitch the replacement backward around X."
    assert text["tilt_x_plus_tooltip"] == "Pitch the replacement forward around X."
    assert text["tilt_y_minus_tooltip"] == "Turn the replacement left/right around Y."
    assert text["tilt_y_plus_tooltip"] == "Turn the replacement left/right around Y."
    assert text["tilt_z_minus_tooltip"] == "Roll or side-tilt the replacement around Z."
    assert text["tilt_z_plus_tooltip"] == "Roll or side-tilt the replacement around Z."
    assert "Manual export transform" in text["hint_html"]
    assert text["section_title"] == "Transform"


def test_alignment_transform_location_original_text_preserves_format() -> None:
    assert alignment_transform_location_original_text((1, 2.345678, "-3")) == "1.00000, 2.34568, -3.00000"
    assert alignment_transform_location_original_text((1,)) == "1.00000, 0.00000, 0.00000"


def test_spinbox_transform_values_reads_widget_values() -> None:
    assert spinbox_transform_values(
        (FakeSpinBox("1.0"), FakeSpinBox(2.0), FakeSpinBox(3)),
        (FakeSpinBox(4.0), FakeSpinBox("5.0"), FakeSpinBox(6.0)),
        (FakeSpinBox(7.0), FakeSpinBox(8.0), FakeSpinBox("9.0")),
        catch_runtime=True,
    ) == (
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
        (7.0, 8.0, 9.0),
    )


def test_spinbox_transform_values_can_fallback_on_deleted_widget() -> None:
    assert spinbox_transform_values(
        (RaisingSpinBox(), FakeSpinBox(2.0), FakeSpinBox(3.0)),
        (FakeSpinBox(4.0), FakeSpinBox(5.0), FakeSpinBox(6.0)),
        (FakeSpinBox(7.0), FakeSpinBox(8.0), FakeSpinBox(9.0)),
        catch_runtime=True,
    ) == DEFAULT_GLOBAL_TRANSFORM_VALUES


def test_spinbox_transform_values_can_fallback_before_widgets_exist() -> None:
    assert spinbox_transform_values(
        (None, None, None),
        (None, None, None),
        (None, None, None),
        catch_runtime=True,
    ) == DEFAULT_GLOBAL_TRANSFORM_VALUES


def test_spinbox_transform_values_can_raise_deleted_widget() -> None:
    with pytest.raises(RuntimeError):
        spinbox_transform_values(
            (RaisingSpinBox(), FakeSpinBox(2.0), FakeSpinBox(3.0)),
            (FakeSpinBox(4.0), FakeSpinBox(5.0), FakeSpinBox(6.0)),
            (FakeSpinBox(7.0), FakeSpinBox(8.0), FakeSpinBox(9.0)),
            catch_runtime=False,
        )


def test_source_part_transform_values_uses_existing_or_default_adjustment() -> None:
    adjustments = {
        3: SimpleNamespace(
            offset_xyz=(1, 2, 3),
            rotate_xyz_degrees=(4, 5, 6),
            scale_xyz=(7, 8, 9),
            uniform_scale=2.5,
        )
    }

    assert source_part_transform_values(adjustments, 3, SimpleNamespace) == (
        (1.0, 2.0, 3.0),
        (4.0, 5.0, 6.0),
        (7.0, 8.0, 9.0),
        2.5,
    )
    assert source_part_transform_values(adjustments, 4, lambda index: SimpleNamespace(source_index=index)) == (
        (0.0, 0.0, 0.0),
        (0.0, 0.0, 0.0),
        (1.0, 1.0, 1.0),
        1.0,
    )


def test_alignment_part_delta_refresh_state_tracks_selected_and_preview_refresh() -> None:
    assert alignment_part_delta_refresh_state("4", (2, 4)) == {
        "source_indices": (2, 4),
        "reload_selected_controls": True,
        "refresh_source_columns": True,
        "queue_part_preview": True,
    }
    assert alignment_part_delta_refresh_state("bad", ()) == {
        "source_indices": (),
        "reload_selected_controls": False,
        "refresh_source_columns": False,
        "queue_part_preview": False,
    }


def test_alignment_preview_commit_state_routes_part_or_global_delta() -> None:
    assert alignment_preview_commit_state(
        ("2", 4),
        current_values=(10, 20, 30),
        delta_xyz=(1, 2, 3),
    ) == {
        "scope": "parts",
        "part_source_indices": (2, 4),
        "global_values": None,
    }
    assert alignment_preview_commit_state(
        (),
        current_values=(10, 20),
        delta_xyz=(1,),
    ) == {
        "scope": "global",
        "part_source_indices": (),
        "global_values": (11.0, 20.0, 0.0),
    }


def test_alignment_preview_rotation_context_state_selects_part_or_global_context() -> None:
    assert alignment_preview_rotation_context_state(
        "4",
        part_rotation=(1, 2),
        global_rotation=(10, 20, 30),
        global_origin=(3, 4, 5),
    ) == {
        "scope": "part",
        "base_rotation": (1.0, 2.0, 0.0),
        "origin_override": None,
    }
    assert alignment_preview_rotation_context_state(
        -1,
        global_rotation=(10, 20, 30),
        global_origin=(3, 4),
    ) == {
        "scope": "global",
        "base_rotation": (10.0, 20.0, 30.0),
        "origin_override": (3.0, 4.0, 0.0),
    }


def test_alignment_preview_drag_prepare_state_tracks_part_undo() -> None:
    assert alignment_preview_drag_prepare_state(("2", 4), undo_label="Preview part drag") == {
        "part_source_indices": (2, 4),
        "push_undo": True,
        "undo_label": "Preview part drag",
    }
    assert alignment_preview_drag_prepare_state((), undo_label="Preview part drag") == {
        "part_source_indices": (),
        "push_undo": False,
        "undo_label": "Preview part drag",
    }


def test_alignment_global_fast_preview_state_builds_delta_and_d3d11_queue_flag() -> None:
    assert alignment_global_fast_preview_state(
        (
            (1.0, 2.0, 3.0),
            (4.0, 5.0, 6.0),
            (2.0, 4.0, 8.0),
        ),
        (
            (3.0, 6.0, 9.0),
            (5.0, 7.0, 9.0),
            (4.0, 2.0, 16.0),
        ),
        preview_scale=0.5,
        d3d11_active=True,
        drag_active=False,
    ) == {
        "apply": True,
        "queue_d3d11": True,
        "base_rotation": (4.0, 5.0, 6.0),
        "origin_override": "global",
        "source_submesh_indices": (),
        "translation": (1.0, 2.0, 3.0),
        "rotation_degrees": (1.0, 2.0, 3.0),
        "scale_xyz": (2.0, 0.5, 2.0),
    }
    assert alignment_global_fast_preview_state(
        None,
        DEFAULT_GLOBAL_TRANSFORM_VALUES,
        preview_scale=1.0,
        d3d11_active=True,
        drag_active=False,
    ) == {"apply": False, "queue_d3d11": False}


def test_alignment_part_fast_preview_state_builds_delta_and_d3d11_queue_flag() -> None:
    assert alignment_part_fast_preview_state(
        7,
        (
            (1.0, 2.0, 3.0),
            (4.0, 5.0, 6.0),
            (2.0, 4.0, 8.0),
            2.0,
        ),
        (
            (3.0, 6.0, 9.0),
            (5.0, 7.0, 9.0),
            (4.0, 2.0, 16.0),
            0.5,
        ),
        preview_scale=0.5,
        d3d11_active=True,
        drag_active=True,
    ) == {
        "apply": True,
        "queue_d3d11": False,
        "base_rotation": (4.0, 5.0, 6.0),
        "origin_override": None,
        "source_submesh_indices": (7,),
        "translation": (1.0, 2.0, 3.0),
        "rotation_degrees": (1.0, 2.0, 3.0),
        "scale_xyz": (0.5, 0.125, 0.5),
    }
    assert alignment_part_fast_preview_state(
        7,
        None,
        ((0.0, 0.0, 0.0), (0.0, 0.0, 0.0), (1.0, 1.0, 1.0), 1.0),
        preview_scale=1.0,
        d3d11_active=True,
        drag_active=False,
    ) == {"apply": False, "queue_d3d11": False}


def test_alignment_transform_preview_queue_state_sets_interactive_time_and_timer_flag() -> None:
    assert alignment_transform_preview_queue_state(now=10.5, applied=True) == {
        "interactive_until": 11.3,
        "start_timer": False,
    }
    assert alignment_transform_preview_queue_state(now=10.5, applied=False, interactive_seconds=1.25) == {
        "interactive_until": 11.75,
        "start_timer": True,
    }


def test_alignment_part_transform_preview_queue_indices_normalizes_source_input() -> None:
    assert alignment_part_transform_preview_queue_indices((3, "2", -1, "bad", 3, None)) == (2, 3)
    assert alignment_part_transform_preview_queue_indices("4") == (4,)
    assert alignment_part_transform_preview_queue_indices(object()) == ()


def test_alignment_transform_reset_state_routes_reset_values() -> None:
    assert alignment_transform_reset_state("location") == {
        "alignment_mode": None,
        "scale_to_length": None,
        "flip_direction": None,
        "scale_link": None,
        "offset": (0.0, 0.0, 0.0),
        "rotation": None,
        "scale": None,
        "queue_rebuild": True,
    }
    assert alignment_transform_reset_state("rotation")["rotation"] == (0.0, 0.0, 0.0)
    assert alignment_transform_reset_state("rotation")["flip_direction"] is False
    assert alignment_transform_reset_state("scale")["scale_link"] is True
    assert alignment_transform_reset_state("scale")["scale"] == (1.0, 1.0, 1.0)
    assert alignment_transform_reset_state("bad")["queue_rebuild"] is False


def test_alignment_transform_reset_state_routes_placement_mode() -> None:
    assert alignment_transform_reset_state("placement", modify_original_clone_mode=False) == {
        "alignment_mode": "grid_flat",
        "scale_to_length": True,
        "flip_direction": False,
        "scale_link": None,
        "offset": (0.0, 0.0, 0.0),
        "rotation": (0.0, 0.0, 0.0),
        "scale": (1.0, 1.0, 1.0),
        "queue_rebuild": True,
    }
    assert alignment_transform_reset_state("placement", modify_original_clone_mode=True)["alignment_mode"] == "manual"
    assert alignment_transform_reset_state("placement", modify_original_clone_mode=True)["scale_to_length"] is False


def test_alignment_rotation_nudge_value_applies_direction_and_step() -> None:
    assert alignment_rotation_nudge_value("10.5", -1, "2.25") == 8.25
    assert alignment_rotation_nudge_value(10.5, 1, 2.25) == 12.75


def test_alignment_global_rotation_origin_state_uses_anchor_offset_center_and_scale() -> None:
    assert alignment_global_rotation_origin_state(
        {"target_anchor": (10.0, 20.0)},
        offset_xyz=(1.0, 2.0, 3.0),
        normalization_center=(4.0, 5.0, 6.0),
        normalization_scale=2.0,
    ) == (14.0, 34.0, -6.0)
    assert alignment_global_rotation_origin_state(
        {},
        offset_xyz=(),
        normalization_center=(),
        normalization_scale=None,
    ) == (0.0, 0.0, 0.0)


def test_alignment_linked_scale_sync_state_routes_targets() -> None:
    assert alignment_linked_scale_sync_state(
        syncing_active=False,
        link_enabled=True,
        value="1.25",
        source_index=1,
        scale_count=3,
    ) == {"apply": True, "target_indices": (0, 2), "value": 1.25}
    assert alignment_linked_scale_sync_state(
        syncing_active=False,
        link_enabled=True,
        value=2.0,
        source_index="bad",
        scale_count=3,
    ) == {"apply": True, "target_indices": (0, 1, 2), "value": 2.0}
    assert alignment_linked_scale_sync_state(
        syncing_active=True,
        link_enabled=True,
        value=2.0,
        source_index=0,
    )["apply"] is False
    assert alignment_linked_scale_sync_state(
        syncing_active=False,
        link_enabled=False,
        value=2.0,
        source_index=0,
    )["apply"] is False


def test_alignment_transform_slider_sync_state_routes_changes() -> None:
    assert alignment_transform_slider_sync_state(value=1.234, slider_value=1233, scale=1000.0) == {
        "apply": True,
        "slider_value": 1234,
    }
    assert alignment_transform_slider_sync_state(value=1.234, slider_value=1234, scale=1000.0)["apply"] is False


def test_alignment_global_transform_spin_commit_state_routes_preview_and_scale() -> None:
    assert alignment_global_transform_spin_commit_state(
        scale_spin=True,
        d3d11_preview_active=True,
    ) == {
        "sync_linked_scale": True,
        "queue_preview_update": True,
        "queue_static_rebuild": False,
    }
    assert alignment_global_transform_spin_commit_state(
        scale_spin=False,
        d3d11_preview_active=False,
    ) == {
        "sync_linked_scale": False,
        "queue_preview_update": False,
        "queue_static_rebuild": True,
    }


def test_current_alignment_transform_generation_defaults_to_zero() -> None:
    assert current_alignment_transform_generation({"value": "12"}) == 12
    assert current_alignment_transform_generation({}) == 0
    assert current_alignment_transform_generation({"value": None}) == 0


def test_transform_initial_states_preserve_defaults() -> None:
    assert alignment_transform_generation_initial_state() == {"value": 0, "committed": 0}
    assert static_preview_baked_transform_initial_state() == {
        "global": None,
        "parts": {},
        "transform_generation": 0,
    }
    assert static_preview_interactive_until_initial_state() == {"time": 0.0}


def test_capture_static_preview_baked_transform_state_records_snapshot() -> None:
    state = static_preview_baked_transform_initial_state()

    result = capture_static_preview_baked_transform_state(
        state,
        global_values=((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
        part_values={2: ("part", 2), 4: ("part", 4)},
        selected_preview_indices=("3", 5),
        transform_generation="12",
    )

    assert result is state
    assert state == {
        "global": ((1.0, 2.0, 3.0), (4.0, 5.0, 6.0), (7.0, 8.0, 9.0)),
        "parts": {2: ("part", 2), 4: ("part", 4)},
        "selected_preview_indices": (3, 5),
        "transform_generation": 12,
    }


def test_alignment_preview_is_interactive_handles_bad_state() -> None:
    assert alignment_preview_is_interactive({"time": 11.0}, monotonic=lambda: 10.0) is True
    assert alignment_preview_is_interactive({"time": 9.0}, monotonic=lambda: 10.0) is False
    assert alignment_preview_is_interactive({"time": object()}, monotonic=lambda: 10.0) is False


class FakeTabs:
    def __init__(self, active: object) -> None:
        self.active = active

    def currentIndex(self) -> int:
        return 0

    def widget(self, index: int) -> object:
        assert index == 0
        return self.active


def test_active_tab_is_handles_match_and_widget_errors() -> None:
    active = object()
    assert active_tab_is(FakeTabs(active), active) is True
    assert active_tab_is(FakeTabs(object()), active) is False
    assert active_tab_is(object(), active) is False


class FakeCheckbox:
    def __init__(self, checked: bool) -> None:
        self.checked = checked

    def isChecked(self) -> bool:
        return self.checked


def test_mesh_edit_raw_preview_active_requires_checkbox_and_tab() -> None:
    assert mesh_edit_raw_preview_active(FakeCheckbox(True), lambda: True) is True
    assert mesh_edit_raw_preview_active(FakeCheckbox(False), lambda: True) is False
    assert mesh_edit_raw_preview_active(FakeCheckbox(True), lambda: False) is False
    assert mesh_edit_raw_preview_active(object(), lambda: True) is False
