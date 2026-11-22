from __future__ import annotations

from collections.abc import Sequence
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_source_part_append_state import (
    source_part_append_rollback_snapshot,
)
from cdmw.ui.archive_browser.static_replacement_source_part_properties_state import (
    source_part_properties_inspector_state,
)


def _properties_state(selection: dict[str, object], **overrides: object):
    kwargs = {
        "output_counts": (2, 3, 1, 4, "prune removed"),
        "target_source_indices": lambda target_index: (0, 2) if target_index == 5 else (),
        "target_outliner_state": lambda target_index, source_indices: (
            ("Removed", "#fb923c") if not tuple(source_indices) else ("Mapped", "#3fb950")
        ),
        "format_source_indices": lambda indices: ", ".join(f"src {index}" for index in indices) or "-",
        "format_target_indices": lambda indices: ", ".join(f"target {index}" for index in indices) or "-",
        "target_dds_label": lambda target_index: f"TargetMat{target_index}" if target_index >= 0 else "",
        "target_texture_status_text": lambda target_name: f"Tex {target_name}",
        "source_assigned_target_indices": lambda source_index: (5,) if source_index == 2 else (),
        "source_outliner_state": lambda source_index, mapped_targets: (
            ("Assigned", "#3fb950") if tuple(mapped_targets) else ("Unassigned", "#d29922")
        ),
        "source_material_name": lambda source_index: f"Material{source_index}",
    }
    kwargs.update(overrides)
    return source_part_properties_inspector_state(selection, **kwargs)


def test_source_part_append_rollback_snapshot_normalizes_mutable_state() -> None:
    adjustments = {1: SimpleNamespace(value=["keep"])}
    redo_adjustments = [SimpleNamespace(value=["redo"])]

    snapshot = source_part_append_rollback_snapshot(
        replacement_mesh="mesh",
        replacement_base_mesh="base",
        appended_source_indices=(2, "bad", 2),
        independent_output_source_indices=(3,),
        preview_only_source_indices=(4,),
        source_role_overrides={2: "role"},
        source_display_overrides={2: "display"},
        source_part_adjustments=adjustments,
        dialog_added_supplemental_files=["sidecar"],
        texture_files_for_mapping=["tex"],
        source_material_texture_override_assignments={"slot": "path"},
        mesh_edit_redo_stack=["redo"],
        mesh_edit_redo_adjustment_stack=redo_adjustments,
        source_geometry_revision="12",
        selected_source_index="2",
        selected_source_indices=(2, 3),
        selected_target_index="4",
        selected_original_index="5",
        selected_source_highlights=(2,),
        selected_target_source_highlights=(4,),
        transform_source_indices=(2, 3),
        selected_original_highlights=(5,),
        selected_target_original_highlights=(6,),
    )

    adjustments[1].value.append("changed")
    redo_adjustments[0].value.append("changed")

    assert snapshot.appended_source_indices == (2,)
    assert snapshot.source_geometry_revision == 12
    assert snapshot.selected_source_index == 2
    assert snapshot.selected_source_indices == (2, 3)
    assert snapshot.source_part_adjustments[1].value == ["keep"]
    assert snapshot.mesh_edit_redo_adjustment_stack[0].value == ["redo"]
