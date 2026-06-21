from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_added_part_textures import (
    added_texture_editor_loading_initial_state,
    added_texture_editor_loading_set,
    added_part_detected_missing_message,
    added_part_detected_assignment_state,
    added_part_attached_targets,
    added_part_selected_texture_assignment_state,
    added_part_texture_choose_dialog_state,
    added_part_texture_editor_context_state,
    added_part_texture_editor_state,
    added_part_texture_group_size_state,
    added_part_texture_override_action_state,
    added_part_texture_row_states,
    added_part_texture_tree_visibility_state,
    added_part_texture_control_text,
    added_part_texture_invalid_file_message,
    added_part_target_has_material_conflict,
    added_part_target_summary,
    added_part_texture_display,
    added_part_texture_role_label,
    added_part_texture_status,
    added_texture_source_choices,
    current_added_part_texture_source_index,
    source_material_name_for_index,
    source_material_override_key,
    source_slot_for_added_part,
    selected_added_part_texture_row_initial_state,
)


def test_added_part_texture_initial_states_preserve_defaults() -> None:
    assert selected_added_part_texture_row_initial_state() == {"source_index": -1}
    assert added_texture_editor_loading_initial_state() == {"active": False}


def test_added_texture_editor_loading_and_current_source_index_state() -> None:
    loading_state = added_texture_editor_loading_initial_state()

    assert added_texture_editor_loading_set(loading_state, True) == {"active": True}
    assert loading_state == {"active": True}
    assert added_texture_editor_loading_set(loading_state, False) == {"active": False}
    assert current_added_part_texture_source_index("4", 2) == 4
    assert current_added_part_texture_source_index("bad", "3") == 3
    assert current_added_part_texture_source_index(None, "bad") == -1


def test_added_part_texture_editor_state_uses_placeholder_without_source() -> None:
    state = added_part_texture_editor_state(
        -1,
        source_choices=(("Detected", "detected.dds"),),
        current_source="manual.dds",
    )

    assert state.has_source is False
    assert state.source_choices == (("Select an added part", ""),)
    assert state.current_source == ""


def test_added_part_texture_editor_state_preserves_choices_for_selected_source() -> None:
    state = added_part_texture_editor_state(
        4,
        source_choices=(("Use detected / none", ""), ("Manual", "manual.dds")),
        current_source="manual.dds",
    )

    assert state.has_source is True
    assert state.source_choices == (("Use detected / none", ""), ("Manual", "manual.dds"))
    assert state.current_source == "manual.dds"


def test_added_part_texture_tree_visibility_state_tracks_empty_and_populated_views() -> None:
    empty_state = added_part_texture_tree_visibility_state(0)

    assert empty_state.has_rows is False
    assert empty_state.empty_label_visible is True
    assert empty_state.tree_visible is False
    assert empty_state.editor_visible is False

    populated_state = added_part_texture_tree_visibility_state(3)
    assert populated_state.has_rows is True
    assert populated_state.empty_label_visible is False
    assert populated_state.tree_visible is True
    assert populated_state.editor_visible is True


def test_added_part_texture_group_size_state_tracks_empty_and_populated_layouts() -> None:
    populated_state = added_part_texture_group_size_state(
        True,
        empty_label_height=12,
        font_height=10,
    )

    assert populated_state.max_height == 360
    assert populated_state.fixed_height is False

    compact_empty_state = added_part_texture_group_size_state(
        False,
        empty_label_height=12,
        font_height=10,
    )

    assert compact_empty_state.max_height == 46
    assert compact_empty_state.fixed_height is True

    tall_empty_state = added_part_texture_group_size_state(
        False,
        empty_label_height=70,
        font_height=13,
    )

    assert tall_empty_state.max_height == 105
    assert tall_empty_state.fixed_height is True


def test_added_part_texture_control_text_preserves_panel_copy() -> None:
    text = added_part_texture_control_text()

    assert text["group_title"] == "Added Part Textures"
    assert "Attached parts can export" in text["group_tooltip"]
    assert text["headers"] == ["Part", "Target", "Material", "Base", "Normal", "Mask", "Height", "Status"]
    assert text["empty_label"] == "No added mesh parts in this session."
    assert text["slot_options"] == (
        ("base", "Base"),
        ("normal", "Normal"),
        ("material", "Mask"),
        ("height", "Height"),
    )
    assert text["assign_button"] == "Assign"
    assert text["assign_detected_button"] == "Assign Detected"
    assert text["clear_button"] == "Clear"
    assert text["choose_base_button"] == "Choose Base"
    assert text["role_label"] == "Role"
    assert text["source_label"] == "Source"
    assert added_part_detected_missing_message() == (
        "Assign Detected",
        "No detected texture files were found for the selected added part.",
    )
    assert added_part_texture_invalid_file_message() == (
        "Choose Texture",
        "The selected file is not a supported texture image.",
    )


def test_added_part_texture_role_label_preserves_selection_context_copy() -> None:
    assert added_part_texture_role_label("base") == "Base / Color"
    assert added_part_texture_role_label("normal") == "Normal"
    assert added_part_texture_role_label("material") == "Material / Mask"
    assert added_part_texture_role_label("height") == "Height"
    assert added_part_texture_role_label("emissive") == "Emissive"
    assert added_part_texture_role_label("") == "Texture"


def test_source_material_name_for_index_prefers_texture_set_then_source_label() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin", texture=""),
            SimpleNamespace(name="Cape", material="", texture=""),
        ]
    )
    texture_sets = {"skin": SimpleNamespace(material_name="SkinMat", slots={})}

    assert source_material_name_for_index(0, mesh, texture_sets) == "SkinMat"
    assert source_material_name_for_index(1, mesh, texture_sets) == "Cape"
    assert source_material_name_for_index(9, mesh, texture_sets) == "source_9"


def test_source_slot_for_added_part_uses_override_and_material_slot_fallbacks() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="", material="Skin", texture="")])
    texture_sets = {
        "skin": SimpleNamespace(
            material_name="SkinMat",
            slots={
                "material_mask": SimpleNamespace(source_path=Path("mask.dds")),
                "base": SimpleNamespace(source_path=Path("base.dds")),
            },
        )
    }

    assert source_material_override_key(" SkinMat ", " BASE ") == ("SkinMat", "base")
    assert source_slot_for_added_part(0, "base", mesh, texture_sets, {}) == Path("base.dds")
    assert source_slot_for_added_part(0, "material", mesh, texture_sets, {}) == Path("mask.dds")
    assert source_slot_for_added_part(
        0,
        "base",
        mesh,
        texture_sets,
        {("SkinMat", "base"): "manual.dds"},
    ) == Path("manual.dds")


def test_added_part_targets_summary_and_conflicts() -> None:
    mappings = (
        SimpleNamespace(target_submesh_index=3, source_submesh_indices=(1, 2)),
        SimpleNamespace(target_submesh_index=4, source_submesh_indices=(1,)),
        SimpleNamespace(target_submesh_index="bad", source_submesh_indices=(1,)),
    )

    assert added_part_attached_targets(1, mappings) == (3, 4)
    assert (
        added_part_target_summary(1, (3, 4), set(), target_display_name=lambda index: f"target {index}")
        == "target 3, target 4"
    )
    assert added_part_target_summary(7, (), {7}, target_display_name=lambda index: f"target {index}") == "Preview only"
    assert added_part_target_summary(8, (), set(), target_display_name=lambda index: f"target {index}") == "Attach required"
    assert added_part_target_has_material_conflict(
        1,
        mappings,
        source_material_name_for_index=lambda index: "Skin" if index == 1 else "Cloth",
    )
    assert not added_part_target_has_material_conflict(
        1,
        mappings,
        source_material_name_for_index=lambda _index: "Skin",
    )


def test_added_part_texture_status_and_display() -> None:
    assert added_part_texture_status(
        1,
        attached_targets=(),
        has_material_conflict=False,
        base_source_path=None,
        preview_only_source_indices={1},
    ) == ("Preview only", "#79c0ff")
    assert added_part_texture_status(
        1,
        attached_targets=(),
        has_material_conflict=False,
        base_source_path=None,
        preview_only_source_indices=set(),
    ) == ("Attach required", "#f85149")
    assert added_part_texture_status(
        1,
        attached_targets=(3,),
        has_material_conflict=True,
        base_source_path=Path("base.dds"),
        preview_only_source_indices=set(),
    ) == ("Target conflict", "#f85149")
    assert added_part_texture_status(
        1,
        attached_targets=(3,),
        has_material_conflict=False,
        base_source_path=None,
        preview_only_source_indices=set(),
    ) == ("Missing base", "#f85149")
    assert added_part_texture_status(
        1,
        attached_targets=(3,),
        has_material_conflict=False,
        base_source_path=Path("base.dds"),
        preview_only_source_indices=set(),
    ) == ("Ready", "#3fb950")

    assert added_part_texture_display("SkinMat", "base", {("SkinMat", "base"): "manual.dds"}, None) == "manual.dds"
    assert added_part_texture_display("SkinMat", "base", {}, Path("base.dds")) == "base.dds"
    assert added_part_texture_display("SkinMat", "base", {}, None) == "-"


def test_added_part_texture_assignment_action_states_normalize_routes() -> None:
    assert added_part_selected_texture_assignment_state(
        loading_active=True,
        source_index=2,
        slot_kind="base",
        source_path="manual.dds",
    ) == {"apply": False, "source_index": -1, "slot_kind": "", "source_path": ""}
    assert added_part_selected_texture_assignment_state(
        loading_active=False,
        source_index="3",
        slot_kind=" MATERIAL ",
        source_path=" manual.dds ",
    ) == {"apply": True, "source_index": 3, "slot_kind": "material", "source_path": "manual.dds"}

    assert added_part_texture_override_action_state(
        source_index=-1,
        material_name="Skin",
        slot_kind="base",
        source_path="manual.dds",
    ) == {"apply": False, "source_index": -1}
    assert added_part_texture_override_action_state(
        source_index=4,
        material_name=" Skin ",
        slot_kind=" BASE ",
        source_path=" manual.dds ",
    ) == {
        "apply": True,
        "source_index": 4,
        "assignment_key": ("Skin", "base"),
        "source_path": "manual.dds",
        "clear": False,
        "enable_rebuild_sidecar": True,
        "enable_inject_base_color": True,
        "mark_dirty": True,
    }
    assert added_part_texture_override_action_state(
        source_index=4,
        material_name="Skin",
        slot_kind="normal",
        source_path="",
    ) == {
        "apply": True,
        "source_index": 4,
        "assignment_key": ("Skin", "normal"),
        "source_path": "",
        "clear": True,
        "enable_rebuild_sidecar": False,
        "enable_inject_base_color": False,
        "mark_dirty": True,
    }


def test_added_part_texture_editor_context_state_loads_override_and_detected_choices() -> None:
    mesh = SimpleNamespace(submeshes=[SimpleNamespace(name="", material="Skin", texture="")])
    texture_sets = {
        "skin": SimpleNamespace(
            material_name="SkinMat",
            slots={
                "base": SimpleNamespace(source_path=Path("detected.dds")),
                "normal": SimpleNamespace(source_path=Path("normal.dds")),
            },
        )
    }
    overrides = {("SkinMat", "base"): "manual.dds"}

    missing = added_part_texture_editor_context_state(
        -1,
        "base",
        replacement_mesh=mesh,
        texture_sets_by_key=texture_sets,
        override_assignments=overrides,
        texture_files_for_mapping=(Path("manual.dds"),),
    )

    assert missing.has_source is False
    assert missing.source_choices == (("Select an added part", ""),)
    assert missing.current_source == ""

    state = added_part_texture_editor_context_state(
        0,
        " BASE ",
        replacement_mesh=mesh,
        texture_sets_by_key=texture_sets,
        override_assignments=overrides,
        texture_files_for_mapping=(Path("manual.dds"), Path("other.dds")),
    )

    assert state.has_source is True
    assert state.current_source == "manual.dds"
    assert state.source_choices == (
        ("Use detected / none", ""),
        ("Detected: manual.dds", "manual.dds"),
        ("other.dds", "other.dds"),
    )


def test_added_part_detected_assignment_state_collects_slot_paths() -> None:
    assert added_part_detected_assignment_state(
        source_index=4,
        slot_sources={
            "base": Path("base.dds"),
            "normal": None,
            "material": Path("mask.dds"),
            "height": "height.dds",
        },
    ) == {
        "apply": True,
        "assignments": (("base", "base.dds"), ("material", "mask.dds")),
        "show_missing": False,
    }
    assert added_part_detected_assignment_state(source_index=4, slot_sources={}) == {
        "apply": True,
        "assignments": (),
        "show_missing": True,
    }
    assert added_part_detected_assignment_state(source_index=-1, slot_sources={"base": Path("base.dds")}) == {
        "apply": False,
        "assignments": (),
        "show_missing": False,
    }


def test_added_texture_source_choices_includes_detected_and_dedupes_mapping_files() -> None:
    detected_path = Path("Textures/Base.dds")
    other_path = Path("other.dds")

    assert added_texture_source_choices(
        detected_path,
        (Path("textures/base.dds"), other_path),
    ) == (
        ("Use detected / none", ""),
        ("Detected: Base.dds", str(detected_path)),
        ("other.dds", str(other_path)),
    )


def test_added_part_texture_choose_dialog_state_routes_valid_source_only(tmp_path: Path) -> None:
    skipped = added_part_texture_choose_dialog_state(
        -1,
        "base",
        obj_parent=tmp_path,
    )

    assert skipped.should_open is False
    assert skipped.title == ""
    assert skipped.directory == ""
    assert skipped.file_filter == ""

    state = added_part_texture_choose_dialog_state(
        "3",
        "material_mask",
        obj_parent=tmp_path,
    )

    assert state.should_open is True
    assert state.title == "Choose Material Mask Texture"
    assert state.directory == str(tmp_path)
    assert "*.dds" in state.file_filter
    assert "All files" in state.file_filter


def test_added_part_texture_row_states_build_rows_from_added_sources() -> None:
    mesh = SimpleNamespace(
        submeshes=[
            SimpleNamespace(name="", material="Skin", texture=""),
            SimpleNamespace(name="Cape", material="", texture=""),
            SimpleNamespace(name="Loose", material="", texture=""),
        ]
    )
    texture_sets = {
        "skin": SimpleNamespace(
            material_name="SkinMat",
            slots={
                "base": SimpleNamespace(source_path=Path("base.dds")),
                "normal": SimpleNamespace(source_path=Path("normal.dds")),
            },
        ),
        "cape": SimpleNamespace(
            material_name="CapeMat",
            slots={"base": SimpleNamespace(source_path=Path("cape.dds"))},
        ),
    }
    mappings = (
        SimpleNamespace(target_submesh_index=0, source_submesh_indices=(0,)),
        SimpleNamespace(target_submesh_index=1, source_submesh_indices=(1, 2)),
    )

    rows = added_part_texture_row_states(
        (9, 2, 0, 1),
        replacement_mesh=mesh,
        mappings=mappings,
        texture_sets_by_key=texture_sets,
        override_assignments={("SkinMat", "base"): "manual.dds"},
        preview_only_source_indices={2},
        preserve_source_index=1,
        source_display_name=lambda index: f"source {index}",
        target_display_name=lambda index: f"target {index}",
    )

    assert [row.source_index for row in rows] == [0, 1, 2]
    assert rows[0].source_display_name == "source 0"
    assert rows[0].target_summary == "target 0"
    assert rows[0].material_name == "SkinMat"
    assert rows[0].base_display == "manual.dds"
    assert rows[0].normal_display == "normal.dds"
    assert rows[0].material_display == "-"
    assert rows[0].height_display == "-"
    assert rows[0].status_label == "Ready"
    assert rows[0].status_color == "#3fb950"
    assert rows[0].selected is False

    assert rows[1].target_summary == "target 1"
    assert rows[1].selected is True
    assert rows[1].status_label == "Target conflict"
    assert rows[1].status_color == "#f85149"

    assert rows[2].target_summary == "target 1"
    assert rows[2].status_label == "Target conflict"
