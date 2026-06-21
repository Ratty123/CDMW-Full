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


def test_original_part_action_control_text_preserves_copy() -> None:
    text = original_part_action_control_text()

    assert text["copy"] == "Copy Original As Source"
    assert text["copy_assign"] == "Copy + Assign To Target"
    assert text["clear_selection"] == "Clear Original"
    assert "Replacement sources" in text["copy_tooltip"]
    assert "selected target row" in text["copy_assign_tooltip"]
    assert text["clear_selection_tooltip"] == "Clear only the original reference part selection and preview highlight."


def test_original_part_tree_control_text_preserves_headers() -> None:
    text = original_part_tree_control_text()

    assert text["headers"] == ["#", "Original part", "Role", "Geometry", "Copied as"]


def test_original_part_clipboard_action_text_preserves_copy_paste_labels() -> None:
    text = original_part_clipboard_action_text()

    assert text["copy_part_with_textures"] == "Copy Part With Textures"
    assert text["copy_select_title"] == "Copy Part With Textures"
    assert text["copy_select_message"] == "Select an original reference part to copy first."
    assert text["paste_replacement_source"] == "Paste As Replacement Source"
    assert text["paste_select_title"] == "Paste Replacement Source"
    assert text["paste_select_message"] == "Copy an original reference part first."
    assert text["select_original_title"] == "Select Original Part"
    assert text["select_original_message"] == "Select an original reference part to copy first."
    assert text["paste_undo_label"] == "Paste original part as source"
    assert text["copy_undo_label"] == "Copy original as source"


def test_original_part_clipboard_status_messages_preserve_copy_paste_text() -> None:
    assert "Target physics is preserved" in copied_original_physics_status_message()
    assert "HKX/HKT physics files were auto-copied" in copied_original_physics_status_message()
    assert copied_original_clipboard_status_message(4, 1234) == (
        "Copied original part 4 with 1,234 DDS reference(s)."
    )
    assert pasted_original_source_status_message(7) == (
        "Pasted original part as preview-only replacement source 7."
    )
    assert missing_copied_original_part_message() == (
        "Paste Replacement Source",
        "The copied original part is no longer available in this alignment window.",
    )
    assert copied_original_dds_cell_text("Ready", disabled=False, copied_badge="Copied Orig 2") == (
        "Ready | Copied Orig 2"
    )
    assert copied_original_dds_cell_text("Ready", disabled=True, copied_badge="Copied Orig 2") == "Ready | Route DDS"
    assert appended_original_copy_column_text("", 3) == "3"
    assert appended_original_copy_column_text("1, 2", 3) == "1, 2, 3"


def test_original_target_label_prefers_material_then_name_and_handles_invalid() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="partName", material="partMat"),
            SimpleNamespace(name="nameOnly", material=""),
        ]
    )

    assert original_target_label(0, mesh) == "partMat"
    assert original_target_label(1, mesh) == "nameOnly"
    assert original_target_label(3, mesh) == "original 3"
    assert original_target_label(0, None) == "original 0"


def test_part_physics_review_reason_matches_physics_tokens() -> None:
    reason = part_physics_review_reason(
        "Cape Cloth",
        SimpleNamespace(name="ragdoll shape", material="silk", path="part.hkx"),
    )

    assert "Likely physics/collision-sensitive part" in reason
    assert "(cloth, ragdoll, shape)" in reason
    assert part_physics_review_reason("helmet", SimpleNamespace(name="plain", material="", path="")) == ""


def test_target_physics_status_text_flags_review_only_when_sensitive() -> None:
    target = SimpleNamespace(name="cape cloth", material="", path="")

    assert target_physics_status_text("target", target) == "Review"
    assert target_physics_status_text("target", SimpleNamespace(name="armor", material="", path="")) == "-"


def test_source_physics_status_text_handles_copied_sensitive_source_and_preserved_target() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="plain", material="", path=""),
            SimpleNamespace(name="ragdoll", material="", path=""),
        ]
    )

    kwargs = {
        "source_role_label": lambda index: f"role {index}",
        "source_display_name": lambda index: f"name {index}",
    }
    assert source_physics_status_text("bad", 0, mesh, set(), **kwargs) == "-"
    assert source_physics_status_text(0, 0, mesh, {0}, **kwargs) == "Review"
    assert source_physics_status_text(1, -1, mesh, set(), **kwargs) == "Review"
    assert source_physics_status_text(0, 0, mesh, set(), **kwargs) == "Preserved"
    assert source_physics_status_text(0, -1, mesh, set(), **kwargs) == "-"
    assert source_physics_status_text(3, 0, mesh, set(), **kwargs) == "-"


def test_physics_status_tooltip_matches_status_labels() -> None:
    assert "HKX/HKT" in physics_status_tooltip("Review")
    assert "remains unchanged" in physics_status_tooltip("Preserved")
    assert "No physics/collision warning" in physics_status_tooltip("-")


def test_original_part_texture_intent_rows_collects_sidecar_and_mesh_dds_sorted_unique(tmp_path) -> None:
    preview = tmp_path / "base.dds"
    preview.write_bytes(b"dds")
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="body", material="bodyMat", texture="mesh.dds"),
        ]
    )
    bindings = [
        SimpleNamespace(submesh_name="bodyMat", texture_path="normal.dds", parameter_name="Normal"),
        SimpleNamespace(submesh_name="bodyMat", texture_path="base.dds", parameter_name="Base"),
        SimpleNamespace(submesh_name="bodyMat", texture_path="base.dds", parameter_name="Base"),
        SimpleNamespace(submesh_name="other", texture_path="other.dds", parameter_name="Other"),
        SimpleNamespace(submesh_name="bodyMat", texture_path="not_png.png", parameter_name="Other"),
    ]

    rows = original_part_texture_intent_rows(
        0,
        mesh,
        bindings,
        target_label=lambda _index: "bodyMat",
        preview_source_for_path=lambda texture_path: preview if texture_path == "base.dds" else None,
        binding_matches_target=lambda binding, target: getattr(binding, "submesh_name", "") == target,
        classify_texture_binding=lambda parameter, _path: SimpleNamespace(
            slot_kind="normal" if parameter == "Normal" else "base"
        ),
    )

    assert rows == [
        {
            "parameter_name": "Base",
            "texture_path": "base.dds",
            "slot_kind": "base",
            "source_path": str(preview),
        },
        {
            "parameter_name": "mesh texture",
            "texture_path": "mesh.dds",
            "slot_kind": "base",
            "source_path": "",
        },
        {
            "parameter_name": "Normal",
            "texture_path": "normal.dds",
            "slot_kind": "normal",
            "source_path": "",
        },
    ]
    assert original_part_texture_intent_rows(
        -1,
        mesh,
        bindings,
        target_label=lambda _index: "",
        preview_source_for_path=lambda _texture_path: None,
        binding_matches_target=lambda _binding, _target: True,
        classify_texture_binding=lambda _parameter, _path: SimpleNamespace(slot_kind="base"),
    ) == []


def test_copied_original_texture_tooltip_limits_rows_and_marks_visible_only() -> None:
    rows = [
        {"slot_kind": "base", "parameter_name": "Base", "texture_path": "a.dds", "source_path": "C:/tmp/a.dds"},
        {"slot_kind": "normal", "parameter_name": "Normal", "texture_path": "b.dds", "source_path": ""},
    ]

    assert copied_original_texture_tooltip([]) == ""
    assert copied_original_texture_tooltip(rows) == (
        "Copied original DDS refs:\n"
        "base | Base: a.dds -> a.dds\n"
        "normal | Normal: b.dds (visible only)"
    )


def test_copy_original_part_payload_clones_mutable_submesh_fields_and_metadata() -> None:
    original_part = CopyablePart()
    mesh = SimpleNamespace(submeshes=[original_part])

    payload = copy_original_part_payload(
        0,
        mesh,
        target_label=lambda index: f"label {index}",
        role_hint=lambda text: f"role:{text}",
        texture_intent_rows=lambda index: [{"row": str(index)}],
        physics_review_reason=lambda label, _part: f"physics:{label}",
    )

    assert payload is not None
    assert payload["kind"] == "original_part"
    assert payload["original_submesh_index"] == 0
    assert payload["label"] == "label 0"
    assert payload["role"] == "role:partName partMat label 0"
    assert payload["texture_rows"] == [{"row": "0"}]
    assert payload["physics_review_reason"] == "physics:label 0"
    copied_part = payload["submesh"]
    assert copied_part is not original_part
    assert copied_part.vertices == original_part.vertices
    assert copied_part.vertices is not original_part.vertices
    assert copied_part.bone_indices is not original_part.bone_indices
    assert copy_original_part_payload(-1, mesh, target_label=lambda _index: "", role_hint=lambda _text: "", texture_intent_rows=lambda _index: [], physics_review_reason=lambda _label, _part: "") is None


def test_copied_original_dds_badge_handles_empty_disabled_and_copied_counts() -> None:
    rows = [{"texture_path": "a.dds"}, {"texture_path": "b.dds"}]

    assert copied_original_dds_badge(1, [], set()) == ""
    assert copied_original_dds_badge(1, rows, {1}) == "Route DDS"
    assert copied_original_dds_badge(1, rows, set()) == "Copied Orig 2"


def test_copied_original_source_indices_filters_to_current_replacement_mesh_bounds() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(), SimpleNamespace(), SimpleNamespace()])

    assert copied_original_source_indices(mesh, {-1, 0, 2, 4}) == {0, 2}
    assert copied_original_source_indices(None, {0}) == set()


def test_original_part_clipboard_can_paste_requires_kind_bounds_and_submesh_payload() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(), SimpleNamespace()])

    assert original_part_clipboard_can_paste(
        {"kind": "original_part", "original_submesh_index": 1, "submesh": object()},
        mesh,
    ) is True
    assert original_part_clipboard_can_paste(
        {"kind": "other", "original_submesh_index": 1, "submesh": object()},
        mesh,
    ) is False
    assert original_part_clipboard_can_paste(
        {"kind": "original_part", "original_submesh_index": 2, "submesh": object()},
        mesh,
    ) is False
    assert original_part_clipboard_can_paste(
        {"kind": "original_part", "original_submesh_index": 1, "submesh": None},
        mesh,
    ) is False


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


def test_copied_original_part_source_fills_blank_material_from_original_fallback() -> None:
    copied = copied_original_part_source(
        SimpleNamespace(name="src", material=""),
        {"label": "  "},
        original_index=3,
        fallback_label="Fallback",
        pasted=False,
    )

    assert copied.name == "original 3 (original copy)"
    assert copied.material == "original 3"


def test_remapped_original_copy_source_text_keeps_mapped_unique_indices() -> None:
    assert remapped_original_copy_source_text("0, 2; bad 2\n3", {0: 4, 2: 5}) == "4, 5"
    assert remapped_original_copy_source_text("", {0: 1}) == ""
