from __future__ import annotations

from cdmw.core.research import (
    UnknownResolverGroup,
    UnknownResolverMember,
    UnknownResolverSuggestion,
)
from cdmw.ui.research.classification_review_state import (
    can_accept_unknown_current_role,
    classification_review_focus_candidates,
    is_unknown_member_classifiable,
    preferred_unknown_choice_for_member,
    primary_unknown_member,
    semantic_subtype_for_unknown_member,
    unknown_no_current_family_unknown_status_text,
    unknown_no_current_role_status_text,
    unknown_no_selected_families_unknown_status_text,
    unknown_group_classification_text,
    unknown_group_display_name,
    unknown_group_empty_status_text,
    unknown_group_filter_progress_status_text,
    unknown_group_focus_status_text,
    unknown_group_matches_filters,
    unknown_group_package_text,
    unknown_group_ready_status_text,
    unknown_group_target_paths,
    unknown_label_choice_index,
    unknown_label_tuple,
    unknown_member_local_text,
    unknown_removed_current_file_status_text,
    unknown_removed_family_status_text,
    unknown_removed_selected_families_status_text,
    unknown_resolver_control_state,
    unknown_saved_current_file_status_text,
    unknown_saved_current_role_status_text,
    unknown_saved_family_status_text,
    unknown_saved_selected_families_status_text,
    unknown_select_dds_status_text,
    unknown_select_families_status_text,
    unknown_select_family_status_text,
    wildcard_filter_matches,
)


def _member(path: str, **overrides: object) -> UnknownResolverMember:
    values = {
        "path": path,
        "package_label": "pak_a",
        "current_kind": "unknown",
        "reason": "test",
        "extension": ".dds",
    }
    values.update(overrides)
    return UnknownResolverMember(**values)  # type: ignore[arg-type]


def _group() -> UnknownResolverGroup:
    members = [
        _member("0001/texture/armor_albedo.dds"),
        _member("0001/texture/armor_normal.dds", current_kind="normal", is_unknown=False),
    ]
    return UnknownResolverGroup(
        group_key="texture/armor",
        display_name="Armor",
        unknown_count=1,
        total_members=len(members),
        package_labels=["pak_a", "pak_b", "pak_c"],
        known_kinds=["normal"],
        sidecar_paths=[],
        suggestion_label="Color / Albedo",
        members=members,
    )


def test_unknown_group_status_text_helpers_format_population_states() -> None:
    assert "Workflow needs a saved local approval" in unknown_group_focus_status_text()
    assert unknown_group_filter_progress_status_text(scanned=1000, total=2000, matched=25) == (
        "Filtering classification review... 1,000 / 2,000 scanned | 25 matched"
    )
    assert unknown_group_empty_status_text(showing_classified=True, has_focus_keys=False) == (
        "No review items are available in the current Research snapshot."
    )
    assert unknown_group_empty_status_text(showing_classified=False, has_focus_keys=False) == (
        "No unresolved review items match the current filters."
    )
    assert "No current-run unclassified DDS files matched" in unknown_group_empty_status_text(
        showing_classified=False,
        has_focus_keys=True,
    )
    assert unknown_group_ready_status_text(
        item_count=2,
        registry_text="registry.json",
        showing_classified=True,
        has_focus_keys=False,
    ) == "2 review item(s) are available. Approved labels are stored in registry.json."
    focused_status = unknown_group_ready_status_text(
        item_count=3,
        registry_text="local registry",
        showing_classified=False,
        has_focus_keys=True,
    )
    assert focused_status.startswith("3 unresolved item(s) need review.")
    assert "targeted DDS files" in focused_status


def test_unknown_action_status_text_helpers_format_user_messages() -> None:
    assert unknown_select_dds_status_text() == "Select a DDS file in Family Members first."
    assert unknown_no_current_role_status_text() == (
        "The selected DDS does not currently have a concrete role to accept yet."
    )
    assert unknown_select_family_status_text() == "Select a texture family first."
    assert unknown_select_families_status_text() == "Select one or more texture families first."
    assert unknown_no_current_family_unknown_status_text() == "No unknown DDS files remain in the current family."
    assert unknown_no_selected_families_unknown_status_text() == (
        "No unknown DDS files remain in the selected families."
    )
    assert unknown_saved_current_role_status_text("normal", "normal") == (
        "Saved current role locally as normal/normal for the selected DDS file. Refreshing Research..."
    )
    assert unknown_saved_current_file_status_text("color", "albedo") == (
        "Saved classification color/albedo for the current DDS file. Refreshing Research..."
    )
    assert unknown_saved_family_status_text("mask", "specular", 3) == (
        "Saved classification mask/specular for 3 file(s) in the current family. Refreshing Research..."
    )
    assert unknown_saved_selected_families_status_text("emissive", "emissive", 4, 2) == (
        "Saved classification emissive/emissive for 4 file(s) across 2 selected family/families. Refreshing Research..."
    )
    assert unknown_removed_current_file_status_text() == (
        "Removed the saved classification override from the current DDS file. Refreshing Research..."
    )
    assert unknown_removed_family_status_text(2) == (
        "Removed 2 saved classification override(s) from the current family. Refreshing Research..."
    )
    assert unknown_removed_selected_families_status_text(5, 3) == (
        "Removed 5 saved classification override(s) across 3 selected family/families. Refreshing Research..."
    )


def test_classification_review_focus_candidates_include_stripped_archive_prefix() -> None:
    assert classification_review_focus_candidates(r"0001\texture\armor_albedo.dds") == {
        "0001/texture/armor_albedo.dds",
        "texture/armor_albedo.dds",
    }


def test_unknown_group_display_and_status_text() -> None:
    group = _group()

    assert unknown_group_display_name(group, primary_member=group.members[0]) == "armor_albedo.dds (+1)"
    assert primary_unknown_member(group) == group.members[0]
    assert primary_unknown_member(None) is None
    assert unknown_group_classification_text(group) == "Color / Albedo"
    assert unknown_group_package_text(group) == "pak_a, pak_b..."


def test_unknown_member_local_text_formats_saved_approval() -> None:
    assert unknown_member_local_text(_member("a.dds")) == "No"
    assert unknown_member_local_text(
        _member("a.dds", local_texture_type="COLOR", local_semantic_subtype="ALBEDO")
    ) == "Yes: color/albedo"
    assert unknown_label_tuple(("mask_specular", "mask", "specular")) == (
        "mask_specular",
        "mask",
        "specular",
    )
    assert unknown_label_tuple("bad") == ("color_albedo", "color", "albedo")
    assert unknown_label_choice_index(
        [("color_albedo", "color", "albedo"), ("mask_specular", "mask", "specular")],
        "mask_specular",
    ) == 1
    assert unknown_label_choice_index([], "mask_specular") == -1


def test_unknown_group_matches_focus_name_and_package_filters() -> None:
    group = _group()

    assert wildcard_filter_matches("armor_albedo.dds", "armor")
    assert unknown_group_matches_filters(
        group,
        pending_focus_keys={"texture/armor_albedo.dds"},
        name_filter="armor",
        package_filter="pak_b",
        primary_member=group.members[0],
    )
    assert unknown_group_target_paths([group], unknown_only=True) == ["0001/texture/armor_albedo.dds"]
    assert unknown_group_target_paths([group], unknown_only=False) == [
        "0001/texture/armor_albedo.dds",
        "0001/texture/armor_normal.dds",
    ]
    assert not unknown_group_matches_filters(
        group,
        pending_focus_keys={"texture/missing.dds"},
        name_filter="armor",
        package_filter="pak_b",
        primary_member=group.members[0],
    )


def test_preferred_unknown_choice_uses_current_kind_then_group_suggestion() -> None:
    mask_member = _member("texture/armor_spec.dds", current_kind="mask")
    assert semantic_subtype_for_unknown_member(mask_member) == "specular"
    assert preferred_unknown_choice_for_member(mask_member, None) == "mask_specular"

    group = _group()
    group.suggestions.append(
        UnknownResolverSuggestion(
            choice_key="emissive_emissive",
            texture_type="emissive",
            semantic_subtype="emissive",
            confidence=80,
            reason="test",
        )
    )
    assert preferred_unknown_choice_for_member(_member("texture/unknown.dds"), group) == "emissive_emissive"


def test_unknown_member_classifiable_and_accept_current_role_predicates() -> None:
    assert not is_unknown_member_classifiable(None)
    assert not is_unknown_member_classifiable(_member("notes.txt", extension=".txt"))
    assert is_unknown_member_classifiable(_member("texture/color.dds"))

    assert not can_accept_unknown_current_role(_member("texture/unknown.dds", current_kind="unknown"))
    assert not can_accept_unknown_current_role(_member("texture/sidecar.dds", current_kind="sidecar"))
    assert can_accept_unknown_current_role(_member("texture/normal.dds", current_kind="normal"))


def test_unknown_resolver_control_state_enables_actions_from_selection_state() -> None:
    controls = unknown_resolver_control_state(
        has_group=True,
        has_selected_groups=True,
        current_member=_member("texture/normal.dds", current_kind="normal"),
        has_rows=True,
    )

    assert controls.label_combo_enabled
    assert controls.preview_button_enabled
    assert controls.accept_current_role_enabled
    assert controls.apply_current_file_enabled
    assert controls.apply_selected_enabled
    assert controls.apply_group_enabled
    assert controls.clear_current_file_enabled
    assert controls.clear_selected_enabled
    assert controls.clear_group_enabled
    assert controls.select_all_enabled
    assert controls.clear_family_selection_enabled

    disabled = unknown_resolver_control_state(
        has_group=False,
        has_selected_groups=False,
        current_member=None,
        has_rows=False,
    )

    assert not any(
        (
            disabled.label_combo_enabled,
            disabled.preview_button_enabled,
            disabled.accept_current_role_enabled,
            disabled.apply_current_file_enabled,
            disabled.apply_selected_enabled,
            disabled.apply_group_enabled,
            disabled.clear_current_file_enabled,
            disabled.clear_selected_enabled,
            disabled.clear_group_enabled,
            disabled.select_all_enabled,
            disabled.clear_family_selection_enabled,
        )
    )
