from __future__ import annotations

from dataclasses import dataclass, field
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_original_parts import (
    appended_original_copy_column_text,
    copy_original_part_payload,
    copied_original_clipboard_status_message,
    copied_original_dds_cell_text,
    copied_original_dds_badge,
    copied_original_part_source,
    copied_original_physics_status_message,
    copied_original_source_indices,
    copied_original_texture_tooltip,
    missing_copied_original_part_message,
    original_part_action_control_text,
    original_part_clipboard_action_text,
    original_part_clipboard_can_paste,
    original_part_tree_control_text,
    original_part_texture_intent_rows,
    original_target_label,
    part_physics_review_reason,
    pasted_original_source_status_message,
    physics_status_tooltip,
    remapped_original_copy_source_text,
    source_physics_status_text,
    target_physics_status_text,
)
from cdmw.ui.archive_browser.static_replacement_dialog_routing_callbacks import (
    create_alignment_original_texture_intent_callbacks,
)


@dataclass
class CopyablePart:
    name: str = "partName"
    material: str = "partMat"
    texture: str = ""
    vertices: list[int] = field(default_factory=lambda: [1, 2])
    normals: list[int] = field(default_factory=lambda: [3])
    uvs: list[int] = field(default_factory=lambda: [4])
    faces: list[int] = field(default_factory=lambda: [5])
    bone_indices: list[int] = field(default_factory=lambda: [6])
    bone_weights: list[float] = field(default_factory=lambda: [0.5])


def test_copied_original_part_source_clones_and_names_copy_without_overwriting_material() -> None:
    source = SimpleNamespace(name="src", material="srcMat", vertices=[1])

    copied = copied_original_part_source(
        source,
        {"label": "Label"},
        original_index=2,
        fallback_label="Fallback",
        pasted=True,
    )

    assert copied is not source
    assert copied.vertices is not source.vertices
    assert copied.name == "Label (pasted copy)"
    assert copied.material == "srcMat"
