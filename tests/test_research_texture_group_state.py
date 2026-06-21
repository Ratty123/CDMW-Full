from __future__ import annotations

from cdmw.core.research import TextureSetGroup, TextureSetMember
from cdmw.ui.research.texture_group_state import (
    texture_group_extract_state,
    texture_group_empty_status_text,
    texture_group_no_available_status_text,
    texture_group_population_selected_status_text,
    texture_group_selected_status_text,
)


def test_texture_group_status_text_helpers_format_selection_states() -> None:
    assert texture_group_empty_status_text(has_current_item=False) == (
        "Select a grouped texture set to extract its related files and sidecars."
    )
    assert texture_group_empty_status_text(has_current_item=True) == (
        "Select a grouped texture set on the left, then click 'Extract Selected Set'."
    )
    assert texture_group_selected_status_text(display_name="Armor", member_count=1200, package_count=3) == (
        "Selected group: Armor (1,200 member(s), 3 package(s))."
    )
    assert texture_group_population_selected_status_text("Armor") == (
        "Selected group: Armor. Click 'Extract Selected Set' to extract its related files and sidecars."
    )
    assert texture_group_no_available_status_text() == (
        "No grouped texture sets are available in the current Research snapshot."
    )


def test_texture_group_extract_state_reports_empty_selection_and_ready_paths() -> None:
    no_groups = texture_group_extract_state([], None)
    assert no_groups.is_error
    assert no_groups.paths == []
    assert no_groups.status_text == "No grouped texture sets are available yet. Click 'Refresh Research' first."

    group = TextureSetGroup(
        group_key="armor",
        display_name="Armor",
        member_count=2,
        package_labels=["pak_a"],
        member_kinds=["color", "normal"],
        members=[
            TextureSetMember("texture/armor_a.dds", "pak_a", "color", ".dds"),
            TextureSetMember("texture/armor_n.dds", "pak_a", "normal", ".dds"),
        ],
    )
    no_selection = texture_group_extract_state([group], None)
    assert no_selection.is_error
    assert no_selection.paths == []
    assert no_selection.status_text == "Select a grouped texture set first. If the list is stale or empty, click 'Refresh Research'."

    ready = texture_group_extract_state([group], group)
    assert not ready.is_error
    assert ready.paths == ["texture/armor_a.dds", "texture/armor_n.dds"]
    assert ready.status_text == "Extracting related texture set..."
