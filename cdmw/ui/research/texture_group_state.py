"""Texture-group status text rules for the Research tab."""

from __future__ import annotations

from dataclasses import dataclass

from cdmw.core.research import TextureSetGroup

__all__ = [
    "TextureGroupExtractState",
    "texture_group_extract_state",
    "texture_group_empty_status_text",
    "texture_group_no_available_status_text",
    "texture_group_population_selected_status_text",
    "texture_group_selected_status_text",
]


@dataclass(frozen=True, slots=True)
class TextureGroupExtractState:
    paths: list[str]
    status_text: str
    is_error: bool


def texture_group_selected_status_text(
    *,
    display_name: str,
    member_count: int,
    package_count: int,
) -> str:
    return f"Selected group: {display_name} ({member_count:,} member(s), {package_count:,} package(s))."


def texture_group_population_selected_status_text(display_name: str) -> str:
    return f"Selected group: {display_name}. Click 'Extract Selected Set' to extract its related files and sidecars."


def texture_group_no_available_status_text() -> str:
    return "No grouped texture sets are available in the current Research snapshot."


def texture_group_empty_status_text(*, has_current_item: bool) -> str:
    return (
        "Select a grouped texture set on the left, then click 'Extract Selected Set'."
        if has_current_item
        else "Select a grouped texture set to extract its related files and sidecars."
    )


def texture_group_extract_state(
    groups_value: object,
    selected_group: TextureSetGroup | None,
) -> TextureGroupExtractState:
    if not isinstance(groups_value, list) or not groups_value:
        return TextureGroupExtractState(
            paths=[],
            status_text="No grouped texture sets are available yet. Click 'Refresh Research' first.",
            is_error=True,
        )
    paths = [member.path for member in selected_group.members] if selected_group is not None else []
    if not paths:
        return TextureGroupExtractState(
            paths=[],
            status_text="Select a grouped texture set first. If the list is stale or empty, click 'Refresh Research'.",
            is_error=True,
        )
    return TextureGroupExtractState(
        paths=paths,
        status_text="Extracting related texture set...",
        is_error=False,
    )
