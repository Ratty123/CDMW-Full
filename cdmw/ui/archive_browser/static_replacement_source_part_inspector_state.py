"""Selected source-part inspector presentation text helpers."""

from __future__ import annotations


def part_inspector_loading_initial_state() -> dict[str, bool]:
    return {"active": False}


def source_parts_action_control_text() -> dict[str, str]:
    return {
        "delete_button": "Delete Selected",
        "apply_button": "Apply",
        "delete_object": "MeshRoutingDeleteSourcePartsButton",
        "apply_object": "MeshRoutingApplySourcePartsButton",
        "delete_tooltip": (
            "Delete selected replacement source part(s) from this alignment session, remove their target assignments, "
            "and re-number later source indices. Original archive files are not modified."
        ),
        "apply_tooltip": (
            "Apply a deferred source-part routing change when the pending label asks for it. Use, delete, and remove "
            "source changes rebuild the preview immediately."
        ),
        "pending_label": "No unapplied source-part changes.",
    }


def source_part_inspector_control_text() -> dict[str, str]:
    return {
        "group_title": "Selected Replacement Part",
        "workflow_hint": "Transforms apply to the selected source part(s).",
        "workflow_hint_tooltip": (
            "Select one or more parts. Use Uniform Scale for equal resizing, or Axis Scale for X/Y/Z-only changes."
        ),
        "source_select_label": "Select part",
        "source_combo_tooltip": "Choose the imported/original-clone part to inspect, remove, resize, or route.",
        "name_placeholder": "Select a replacement source part.",
        "target_placeholder": "-",
        "include_in_output": "Include in output",
        "no_target_selected": "No target selected",
        "role_tooltip": (
            "This role label is for mapping clarity in this dialog. The actual output target is controlled by the "
            "target mapping below."
        ),
        "target_tooltip": "Choose the original draw/material target that this selected source should feed.",
        "replace_target": "Replace Target",
        "add_target": "Add To Target",
        "unmap_part": "Unmap Part",
        "replace_target_tooltip": "Set the chosen target's replacement parts to only this selected source.",
        "add_target_tooltip": "Add this selected source to the chosen target without removing any existing source indexes.",
        "unmap_part_tooltip": "Remove this selected source from every target row it currently feeds.",
        "part_label": "Part",
        "role_label": "Role",
        "map_to_label": "Map to",
        "add_mesh_part": "Add Mesh Part...",
        "add_mesh_part_tooltip": (
            "Import an extra OBJ, DAE, glTF/GLB, PAC, PAM, or PAMLOD source part into this Geometry session."
        ),
        "duplicate_part": "Duplicate Part",
        "duplicate_part_tooltip": "Duplicate the selected source part and copy its current target mapping.",
        "mirror_duplicate_part": "Mirror Duplicate",
        "mirror_duplicate_part_tooltip": (
            "Duplicate the selected source part, bake its current placement, mirror it across the original model X "
            "center, and copy its current target mapping."
        ),
        "texture_status_initial": "Texture: -",
        "use_copied_texture": "Use copied original",
        "use_route_texture": "Use route source",
        "remove_copied_texture": "Remove copied texture",
        "use_copied_texture_tooltip": "Use the DDS refs copied from the original part for this pasted replacement source.",
        "use_route_texture_tooltip": "Ignore copied DDS refs and use the normal replacement material route.",
        "remove_copied_texture_tooltip": "Remove the copied DDS intent from this source. Geometry remains.",
    }


__all__ = [
    "part_inspector_loading_initial_state",
    "source_part_inspector_control_text",
    "source_parts_action_control_text",
]
