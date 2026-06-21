"""Selected source-part transform control presentation text helpers."""

from __future__ import annotations


def source_part_transform_control_text() -> dict[str, str]:
    return {
        "uniform_prefix": "All ",
        "translate_spin_tooltip": "Move selected part(s) on this local axis.",
        "rotate_spin_tooltip": "Rotate selected part(s) around this axis in degrees.",
        "axis_spin_tooltip": "Non-uniform axis scale. 1.0 leaves this axis unchanged.",
        "uniform_spin_tooltip": "Uniform scale. Multiplies all axes equally; 1.0 leaves size unchanged.",
        "translate_label": "Translate",
        "translate_x_tooltip": "Selected part X translate slider.",
        "translate_y_tooltip": "Selected part Y translate slider.",
        "translate_z_tooltip": "Selected part Z translate slider.",
        "nudge_step_prefix": "Step ",
        "nudge_step_tooltip": "Distance used by the selected-part nudge buttons and keyboard shortcuts.",
        "nudge_x_minus": "-X",
        "nudge_x_plus": "+X",
        "nudge_y_minus": "-Y",
        "nudge_y_plus": "+Y",
        "nudge_z_minus": "-Z",
        "nudge_z_plus": "+Z",
        "nudge_tooltip": "Nudge the selected part by the configured step.",
        "center_part": "Center To Target",
        "center_part_tooltip": "Move the selected part center to the chosen target center without changing rotation or scale.",
        "rotate_label": "Rotate",
        "rotate_x_tooltip": "Selected part X rotation slider.",
        "rotate_y_tooltip": "Selected part Y rotation slider.",
        "rotate_z_tooltip": "Selected part Z rotation slider.",
        "axis_scale_label": "Axis Scale",
        "axis_scale_tooltip": "Non-uniform scale: change X, Y, and Z independently.",
        "scale_x_tooltip": "Selected part X fine scale slider. Type larger values above.",
        "scale_y_tooltip": "Selected part Y fine scale slider. Type larger values above.",
        "scale_z_tooltip": "Selected part Z fine scale slider. Type larger values above.",
        "uniform_scale_label": "Uniform Scale",
        "uniform_scale_tooltip": "Equal scale applied to all axes.",
        "uniform_scale_slider_tooltip": "Selected part uniform fine scale slider. Type larger values above.",
        "reset_part": "Reset Part",
        "remove_part": "Disable Part Output",
        "fit_part": "Fit Size",
        "undo_geometry": "Undo Geometry",
        "reset_geometry": "Reset Geometry",
        "remove_part_tooltip": (
            "Exclude this replacement source from final output. This is not a preview-only hide; mapped targets with "
            "no enabled source export as removed placeholders."
        ),
        "reset_part_tooltip": "Reset the selected source part transform and include state.",
        "fit_part_tooltip": "Match selected part size to the selected target slot. Use Translate for exact placement.",
        "undo_geometry_tooltip": "Undo the last Geometry action, including routing and texture state touched by that action.",
        "reset_geometry_tooltip": (
            "Reset all Geometry-session changes back to the initial alignment state, including routing and "
            "texture-affecting assignments."
        ),
    }


__all__ = [
    "source_part_transform_control_text",
]
