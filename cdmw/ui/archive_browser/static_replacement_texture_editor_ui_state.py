"""Selected texture editor UI state for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class SelectedTextureEditorState:
    has_row: bool
    source_choices: tuple[tuple[str, str], ...]
    source_path: str
    source_index: int
    label_text: str
    label_tooltip: str
    role_kind: str
    suggestion_available: bool
    suggestion_button_text: str
    suggestion_tooltip: str


@dataclass(frozen=True, slots=True)
class TextureDetailsState:
    target_name: str
    assigned_count: int
    target_row_count: int


@dataclass(frozen=True, slots=True)
class TextureClearAssignmentState:
    rows: tuple[dict[str, object], ...]
    has_rows: bool


@dataclass(frozen=True, slots=True)
class SelectedTextureSourceCommitState:
    source_path: str
    desired_checked: bool
    changed: bool


@dataclass(frozen=True, slots=True)
class SelectedTextureSourceComboChangeState:
    combo_index: int
    source_path: str


def selected_texture_row_initial_state() -> dict[str, object]:
    return {"row": None}


def selected_texture_editor_loading_initial_state() -> dict[str, bool]:
    return {"active": False}


def selected_texture_source_committing_initial_state() -> dict[str, bool]:
    return {"active": False}


def selected_texture_source_commit_state(
    source_path: object,
    *,
    current_source: object,
    current_checked: bool,
) -> SelectedTextureSourceCommitState:
    normalized_source = str(source_path or "").strip()
    desired_checked = bool(normalized_source)
    return SelectedTextureSourceCommitState(
        source_path=normalized_source,
        desired_checked=desired_checked,
        changed=normalized_source != str(current_source or "").strip() or desired_checked != bool(current_checked),
    )


def selected_texture_source_combo_change_state(
    index: object,
    *,
    current_index: Callable[[], int],
    count: Callable[[], int],
    item_data: Callable[[int], object],
) -> SelectedTextureSourceComboChangeState:
    try:
        combo_index = int(index)
    except (TypeError, ValueError):
        combo_index = int(current_index())
    if combo_index < 0 or combo_index >= int(count()):
        combo_index = int(current_index())
    return SelectedTextureSourceComboChangeState(
        combo_index=combo_index,
        source_path=str(item_data(combo_index) or "").strip(),
    )


def texture_clear_assignment_state(rows: Sequence[dict[str, object]]) -> TextureClearAssignmentState:
    selected_rows = tuple(rows or ())
    return TextureClearAssignmentState(rows=selected_rows, has_rows=bool(selected_rows))


def target_texture_clear_assignment_state(
    texture_rows_by_target: Mapping[str, list[dict[str, object]]],
    target_name: object,
) -> TextureClearAssignmentState:
    return texture_clear_assignment_state(texture_rows_by_target.get(str(target_name or ""), []))


def texture_filter_refresh_initial_state() -> dict[str, object]:
    return {"func": None}


def final_dds_contract_summary_html(row_count: int) -> str:
    return (
        "<div style='font-size:0.8em; line-height:1.08; padding:2px 5px; border-left:3px solid #f2cc60; background:#211b12;'>"
        "<span style='color:#f2cc60; font-weight:700;'>Final DDS</span>"
        f"<span style='color:#c9d1d9;'> | rows {int(row_count):,}</span>"
        "</div>"
    )


def texture_editor_control_text() -> dict[str, object]:
    return {
        "selected_label": "Selected row",
        "role_label": "Role",
        "role_tooltip": "Manual repair role for the selected original DDS slot.",
        "source_label": "Source",
        "source_tooltip": "Texture source for the selected original DDS slot. Keep original disables this manual override.",
        "choose_button": "Choose...",
        "choose_tooltip": "Open the texture source picker for the selected row.",
        "apply_suggestion_button": "Use Suggested",
        "apply_suggestion_tooltip": "Apply the suggested source texture to the selected original DDS slot.",
        "texture_assignments_busy": "Updating texture assignments...",
        "override_headers": ["Target", "Source", "Role", "DDS", "Assigned", "Status", "Controls"],
        "role_options": ("base", "normal", "height", "material"),
        "no_editable_slots": "No editable texture slots were found for the currently suggested replacement mapping.",
        "no_sidecar_slots": "No sidecar texture slots were found for this asset.",
    }


def selected_texture_editor_state(
    row_state: Mapping[str, object] | None,
    *,
    source_choices: Callable[[Mapping[str, object] | None], list[tuple[str, str]]],
    effective_source: Callable[[Mapping[str, object]], str],
    source_summary: Callable[[Mapping[str, object]], str],
    source_summary_tooltip: Callable[[Mapping[str, object]], str],
) -> SelectedTextureEditorState:
    has_row = row_state is not None
    choices = tuple(source_choices(row_state if has_row else None))
    source_path = effective_source(row_state) if row_state is not None else ""
    source_index = 0
    for index, (_label, candidate_source) in enumerate(choices):
        if candidate_source == source_path:
            source_index = index
            break
    if row_state is not None:
        affects_text = source_summary(row_state)
        if len(affects_text) > 58:
            affects_text = affects_text[:55].rstrip() + "..."
        label_text = f"Affects: {affects_text}"
        label_tooltip = source_summary_tooltip(row_state)
        role_kind = str(row_state.get("slot_kind", "") or "material")
        suggested_source = str(row_state.get("suggested_source", "") or "").strip()
    else:
        label_text = texture_editor_control_text()["selected_label"]
        label_tooltip = ""
        role_kind = "material"
        suggested_source = ""
    suggestion_available = bool(has_row and suggested_source and suggested_source != source_path)
    return SelectedTextureEditorState(
        has_row=has_row,
        source_choices=choices,
        source_path=source_path,
        source_index=source_index,
        label_text=label_text,
        label_tooltip=label_tooltip,
        role_kind=role_kind,
        suggestion_available=suggestion_available,
        suggestion_button_text=texture_editor_control_text()["apply_suggestion_button"],
        suggestion_tooltip=(
            f"Apply suggested source:\n{suggested_source}"
            if suggestion_available
            else "No unapplied suggestion is available for the selected row."
        ),
    )


def texture_details_state(
    row_state: Mapping[str, object] | None,
    *,
    current_target_name: Callable[[], str],
    texture_rows_by_target: Mapping[str, list[dict[str, object]]],
    assigned: Callable[[Mapping[str, object]], bool],
) -> TextureDetailsState:
    target_name = str(row_state.get("target_name", "") or "") if row_state is not None else current_target_name()
    target_rows = texture_rows_by_target.get(target_name, [])
    assigned_count = sum(1 for target_row in target_rows if assigned(target_row))
    return TextureDetailsState(
        target_name=target_name,
        assigned_count=assigned_count,
        target_row_count=len(target_rows),
    )


__all__ = [
    "SelectedTextureEditorState",
    "SelectedTextureSourceCommitState",
    "SelectedTextureSourceComboChangeState",
    "TextureClearAssignmentState",
    "TextureDetailsState",
    "final_dds_contract_summary_html",
    "selected_texture_editor_loading_initial_state",
    "selected_texture_editor_state",
    "selected_texture_row_initial_state",
    "selected_texture_source_commit_state",
    "selected_texture_source_combo_change_state",
    "selected_texture_source_committing_initial_state",
    "target_texture_clear_assignment_state",
    "texture_clear_assignment_state",
    "texture_details_state",
    "texture_editor_control_text",
    "texture_filter_refresh_initial_state",
]
