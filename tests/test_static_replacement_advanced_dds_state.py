from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_advanced_dds_state import (
    advanced_dds_apply_guidance_state,
    advanced_dds_control_text,
    advanced_dds_loading_busy_text,
    advanced_dds_loading_start_text,
    advanced_dds_override_row_scan_state,
    advanced_dds_overrides_clear_loading,
    advanced_dds_overrides_initial_state,
    advanced_dds_overrides_loaded,
    advanced_dds_overrides_loading,
    advanced_dds_overrides_mark_loaded,
    advanced_dds_overrides_mark_loading,
    advanced_dds_preparing_rows_text,
    advanced_dds_scanning_candidates_text,
    advanced_dds_suggested_source_counts,
)


def test_advanced_dds_overrides_state_tracks_loading_request_and_loaded() -> None:
    state = advanced_dds_overrides_initial_state()

    assert not advanced_dds_overrides_loaded(state)
    assert not advanced_dds_overrides_loading(state)
    assert state["load_requested"] is False

    advanced_dds_overrides_mark_loading(state)
    assert advanced_dds_overrides_loading(state)
    assert state["load_requested"] is True

    advanced_dds_overrides_mark_loaded(state)
    assert advanced_dds_overrides_loaded(state)

    advanced_dds_overrides_clear_loading(state)
    assert not advanced_dds_overrides_loading(state)


def test_advanced_dds_control_text_preserves_panel_copy() -> None:
    text = advanced_dds_control_text()

    assert text["section_title"] == "Advanced Original DDS Overrides"
    assert text["group_title"] == "Advanced DDS Overrides"
    assert "explicit slot repair" in str(text["group_tooltip"])
    assert text["hint_label"] == "Manual DDS slot repair."
    assert "Use route source" in str(text["hint_html"])
    assert "original material sidecar" in str(text["hint_tooltip"])
    assert text["no_sources_hint"] == "No replacement texture files supplied."
    assert text["lazy_label"] == "Advanced DDS Overrides can be expanded after the material contract loads."
    assert "Loading it lazily" in str(text["lazy_tooltip"])
    assert text["load_button"] == "Load Advanced DDS Overrides"
    assert text["apply_all_button"] == "Apply all Suggested for Override Source"
    assert text["apply_all_short"] == "Apply Suggested"
    assert text["clear_target_button"] == "Clear Target"
    assert text["keep_original_button"] == "Keep Original"
    assert text["do_not_emit_button"] == "Do Not Emit"
    assert text["add_textures_button"] == "Add textures..."
    assert text["add_folder_button"] == "Add texture folder..."
    assert text["filter_active_parts"] == "Show only active mapped parts"
    assert text["filter_advanced_slots"] == "Show ambiguous/advanced slots"
    assert text["legacy_group_title"] == "Texture Slot Mapping"
    assert "mapped draw slots" in str(text["legacy_hint"])
    assert "asset sidecars" in str(text["legacy_no_sources_hint"])
    assert text["legacy_filter_selected"] == "Selected part only"
    assert text["legacy_headers"] == [
        "Use",
        "Part / slot",
        "Texture parameter",
        "Current DDS",
        "State",
        "Replacement source",
    ]
    assert text["no_suggestions_title"] == "Apply all Suggested for Override Source"
    assert text["no_suggestions_message"] == (
        "No suggested override sources are available for the current advanced DDS override rows."
    )
    assert text["apply_all_reason"] == "Apply every suggested source. Review the final preview before export."


def test_advanced_dds_loading_text_preserves_progress_copy() -> None:
    assert advanced_dds_loading_busy_text() == "Loading advanced DDS override rows..."
    assert advanced_dds_loading_start_text("manual") == "Loading advanced DDS override rows (manual)..."
    assert advanced_dds_preparing_rows_text(8) == "Preparing advanced DDS override rows... 8"
    assert advanced_dds_scanning_candidates_text(150) == "Scanning DDS override candidates... 150"


def test_advanced_dds_override_row_scan_state_builds_rows_and_progress_callbacks() -> None:
    mapping_progress: list[int] = []
    scan_progress: list[int] = []
    mappings = tuple(
        SimpleNamespace(
            target_submesh_name=f"Target{index}",
            source_submesh_indices=(index, index + 1),
        )
        for index in range(9)
    )
    sidecar_bindings = tuple(
        SimpleNamespace(
            part_name="Target8",
            submesh_name="Target8",
            shader_family="Uber",
            sidecar_kind="pac_xml",
            sidecar_path="character/model/target8.pac_xml",
            linked_mesh_path="character/model/target8.pac",
            parameter_name="_base",
            texture_path="character\\texture\\target8_base.dds",
        )
        for _index in range(151)
    )

    state = advanced_dds_override_row_scan_state(
        mappings,
        sidecar_bindings,
        {"target8": object()},
        set(),
        binding_matches_target=lambda binding, target_name: str(getattr(binding, "part_name", "")) == target_name,
        best_source_for_slot=lambda target_name, source_indices, slot_kind, texture_sets, **_kwargs: (
            f"mods/{target_name}_{slot_kind}_{source_indices[0]}.dds"
            if texture_sets
            else ""
        ),
        texture_is_shared=lambda _path: False,
        on_mapping_progress=mapping_progress.append,
        on_scan_progress=scan_progress.append,
    )

    assert mapping_progress == [8]
    assert scan_progress == [150, 300, 450, 600, 750, 900, 1050, 1200, 1350]
    assert state.scan_count == 1359
    assert state.target_source_indices["Target8"] == (8, 9)
    assert len(state.texture_override_rows) == 1
    row = state.texture_override_rows[0]
    assert row["target_name"] == "Target8"
    assert row["source_indices"] == (8, 9)
    assert row["target_path"] == "character/texture/target8_base.dds"
    assert row["parameter_name"] == "_base"
    assert row["part_display"] == "Target8"
    assert row["shader_family"] == "Uber"
    assert row["sidecar_kind"] == "pac_xml"
    assert row["sidecar_path"] == "character/model/target8.pac_xml"
    assert row["linked_mesh"] == "character/model/target8.pac"
    assert row["suggested_source"] == "mods/Target8_base_8.dds"
    assert row["checked"] is False
    assert row["advanced"] is True
    assert row["state_label"] == "Needs review"
    assert row["confidence"] == "manual"


def test_advanced_dds_override_row_scan_state_skips_shared_non_dds_duplicates_and_nonmatching() -> None:
    mapping = SimpleNamespace(target_submesh_name="Body", source_submesh_indices=(2,))
    matching = SimpleNamespace(
        part_name="Body",
        shader_family="",
        parameter_name="_base",
        texture_path="body.dds",
    )
    duplicate = SimpleNamespace(
        part_name="Body",
        shader_family="",
        parameter_name="_base",
        texture_path="body.dds",
    )
    non_dds = SimpleNamespace(part_name="Body", parameter_name="_base", texture_path="body.png")
    nonmatching = SimpleNamespace(part_name="Cape", parameter_name="_base", texture_path="cape.dds")

    state = advanced_dds_override_row_scan_state(
        (mapping,),
        (matching, duplicate, non_dds, nonmatching),
        {},
        set(),
        binding_matches_target=lambda binding, target_name: str(getattr(binding, "part_name", "")) == target_name,
        best_source_for_slot=lambda *_args, **_kwargs: "mods/body.dds",
        texture_is_shared=lambda path: path == "body.dds",
    )

    assert state.scan_count == 4
    assert len(state.texture_override_rows) == 1
    assert state.texture_override_rows[0]["suggested_source"] == ""
    assert len(state.seen_texture_rows) == 1


def test_advanced_dds_suggested_source_counts_normalizes_sources() -> None:
    rows = (
        {"suggested_source": " Textures/Body.dds "},
        {"suggested_source": "textures/body.dds"},
        {"suggested_source": ""},
        {},
    )

    assert advanced_dds_suggested_source_counts(rows) == {"textures/body.dds": 2}


def test_advanced_dds_apply_guidance_state_resets_assignment_fields() -> None:
    row = {
        "parameter_name": "BaseColor",
        "target_path": "textures/body_base.dds",
        "suggested_source": "mods/body_base.dds",
        "checked": True,
        "source_path": "old.dds",
        "slot_kind": "material",
    }

    advanced_dds_apply_guidance_state(
        row,
        suggested_counts={"mods/body_base.dds": 1},
        texture_row_is_shared=lambda _row: False,
        reset_assignment_fields=True,
        texture_role_label_for_slot=lambda slot: f"role:{slot}",
    )

    assert row["checked"] is False
    assert row["source_path"] == ""
    assert row["role_label"] == "role:material"
    assert row["confidence"]
    assert "guidance" in row


def test_advanced_dds_apply_guidance_state_marks_shared_layer_manual() -> None:
    row = {
        "parameter_name": "SharedLayer",
        "target_path": "textures/shared.dds",
        "suggested_source": "mods/shared.dds",
    }

    advanced_dds_apply_guidance_state(
        row,
        suggested_counts={"mods/shared.dds": 1},
        texture_row_is_shared=lambda _row: True,
    )

    assert row["suggested_source"] == ""
    assert row["advanced"] is True
    assert row["state_label"] == "Original shared layer"
    assert row["confidence"] == "manual"
