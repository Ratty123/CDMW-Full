"""Transform control state helpers for static replacement."""

from __future__ import annotations


def alignment_transform_control_text() -> dict[str, str]:
    return {
        "export_group_title": "Export Values",
        "export_property_header": "Property",
        "export_original_header": "Original",
        "export_values_header": "Export values",
        "axis_x": "X",
        "axis_y": "Y",
        "axis_z": "Z",
        "location_label": "Location",
        "rotation_label": "Rotation",
        "scale_label": "Scale",
        "rotation_original": "0.00, 0.00, 0.00 deg",
        "scale_original": "1.0000, 1.0000, 1.0000",
        "axis_slider_tooltip_template": "{label} {axis} slider. Numeric entry remains available above.",
        "link_scale_axes": "Link scale axes",
        "reset_location": "Reset Location",
        "reset_rotation": "Reset Rotation",
        "reset_scale": "Reset Scale",
        "reset_placement": "Reset Placement",
        "tilt_step_label": "Tilt step",
        "tilt_step_tooltip": "Step used by the tilt/turn/roll buttons.",
        "tilt_x_minus": "Tilt X-",
        "tilt_x_plus": "Tilt X+",
        "tilt_y_minus": "Turn Y-",
        "tilt_y_plus": "Turn Y+",
        "tilt_z_minus": "Roll Z-",
        "tilt_z_plus": "Roll Z+",
        "tilt_x_minus_tooltip": "Pitch the replacement backward around X.",
        "tilt_x_plus_tooltip": "Pitch the replacement forward around X.",
        "tilt_y_minus_tooltip": "Turn the replacement left/right around Y.",
        "tilt_y_plus_tooltip": "Turn the replacement left/right around Y.",
        "tilt_z_minus_tooltip": "Roll or side-tilt the replacement around Z.",
        "tilt_z_plus_tooltip": "Roll or side-tilt the replacement around Z.",
        "hint_html": (
            "<span style='color:#8b949e;'>Manual export transform. Drag axes to move; "
            "Alt+drag rotates X/Y; Alt+Shift+drag rolls Z.</span>"
        ),
        "section_title": "Transform",
    }


def alignment_global_transform_spin_specs() -> dict[str, dict[str, object]]:
    return {
        "offset": {"value": 0.0, "minimum": -10.0, "maximum": 10.0, "decimals": 5, "step": 0.0005},
        "rotation": {
            "value": 0.0,
            "minimum": -360.0,
            "maximum": 360.0,
            "decimals": 2,
            "step": 0.10,
            "suffix": " deg",
        },
        "scale": {"value": 1.0, "minimum": 0.001, "maximum": 100.0, "decimals": 4, "step": 0.005},
        "tilt_step": {
            "value": 2.0,
            "minimum": 0.1,
            "maximum": 45.0,
            "decimals": 1,
            "step": 0.25,
            "suffix": " deg",
        },
    }


def alignment_global_transform_slider_specs() -> dict[str, dict[str, float]]:
    return {
        "offset": {"slider_scale": 2000.0},
        "rotation": {"slider_scale": 10.0},
        "scale": {"slider_scale": 1000.0, "slider_minimum": 0.1, "slider_maximum": 3.0},
    }


def alignment_global_transform_layout_specs() -> dict[str, object]:
    return {
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


def alignment_global_transform_row_specs() -> tuple[dict[str, object], ...]:
    return (
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


def alignment_global_transform_reset_button_specs() -> tuple[dict[str, str], ...]:
    return (
        {"key": "location", "text_key": "reset_location"},
        {"key": "rotation", "text_key": "reset_rotation"},
        {"key": "scale", "text_key": "reset_scale"},
        {"key": "placement", "text_key": "reset_placement"},
    )


def alignment_global_transform_tilt_button_specs() -> tuple[dict[str, object], ...]:
    return (
        {"key": "x_minus", "text_key": "tilt_x_minus", "tooltip_key": "tilt_x_minus_tooltip", "axis": "x", "direction": -1.0},
        {"key": "x_plus", "text_key": "tilt_x_plus", "tooltip_key": "tilt_x_plus_tooltip", "axis": "x", "direction": 1.0},
        {"key": "y_minus", "text_key": "tilt_y_minus", "tooltip_key": "tilt_y_minus_tooltip", "axis": "y", "direction": -1.0},
        {"key": "y_plus", "text_key": "tilt_y_plus", "tooltip_key": "tilt_y_plus_tooltip", "axis": "y", "direction": 1.0},
        {"key": "z_minus", "text_key": "tilt_z_minus", "tooltip_key": "tilt_z_minus_tooltip", "axis": "z", "direction": -1.0},
        {"key": "z_plus", "text_key": "tilt_z_plus", "tooltip_key": "tilt_z_plus_tooltip", "axis": "z", "direction": 1.0},
    )


def alignment_transform_reset_state(
    reset_kind: str,
    *,
    modify_original_clone_mode: bool = False,
) -> dict[str, object]:
    kind = str(reset_kind or "").strip().lower()
    state: dict[str, object] = {
        "alignment_mode": None,
        "scale_to_length": None,
        "flip_direction": None,
        "scale_link": None,
        "offset": None,
        "rotation": None,
        "scale": None,
        "queue_rebuild": True,
    }
    if kind == "location":
        state["offset"] = (0.0, 0.0, 0.0)
    elif kind == "rotation":
        state["flip_direction"] = False
        state["rotation"] = (0.0, 0.0, 0.0)
    elif kind == "scale":
        state["scale_link"] = True
        state["scale"] = (1.0, 1.0, 1.0)
    elif kind == "placement":
        state["alignment_mode"] = "grid_flat"
        state["scale_to_length"] = not bool(modify_original_clone_mode)
        state["flip_direction"] = False
        state["offset"] = (0.0, 0.0, 0.0)
        state["rotation"] = (0.0, 0.0, 0.0)
        state["scale"] = (1.0, 1.0, 1.0)
    else:
        state["queue_rebuild"] = False
    return state


def scale_syncing_initial_state() -> dict[str, bool]:
    return {"active": False}


def alignment_linked_scale_sync_state(
    *,
    syncing_active: object,
    link_enabled: object,
    value: object,
    source_index: object,
    scale_count: object = 3,
) -> dict[str, object]:
    if bool(syncing_active) or not bool(link_enabled):
        return {"apply": False, "target_indices": (), "value": None}
    try:
        source = int(source_index)
    except (TypeError, ValueError, OverflowError):
        source = -1
    count = max(0, int(scale_count))
    targets = tuple(index for index in range(count) if index != source)
    return {"apply": bool(targets), "target_indices": targets, "value": float(value)}


def alignment_transform_slider_sync_state(
    *,
    value: object,
    slider_value: object,
    scale: object,
) -> dict[str, object]:
    target_value = int(round(float(value) * float(scale)))
    return {"apply": int(slider_value) != target_value, "slider_value": target_value}


def alignment_global_transform_spin_commit_state(
    *,
    scale_spin: object,
    d3d11_preview_active: object,
) -> dict[str, bool]:
    preview_active = bool(d3d11_preview_active)
    return {
        "sync_linked_scale": bool(scale_spin),
        "queue_preview_update": preview_active,
        "queue_static_rebuild": not preview_active,
    }
