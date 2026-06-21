"""Advanced DDS override lazy-load state helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass

from cdmw.modding.asset_replacement import classify_texture_binding
from cdmw.modding.material_replacer import classify_texture_assignment_guidance


@dataclass(frozen=True, slots=True)
class AdvancedDdsOverrideRowScanState:
    rows_by_target: dict[str, tuple[dict[str, object], ...]]
    target_source_indices: dict[str, tuple[int, ...]]
    texture_override_rows: tuple[dict[str, object], ...]
    seen_texture_rows: set[tuple[str, str, str, str]]
    scan_count: int


def advanced_dds_overrides_initial_state() -> dict[str, object]:
    return {"loaded": False, "loading": False, "load_requested": False}


def advanced_dds_overrides_loaded(state: Mapping[str, object]) -> bool:
    return bool(state.get("loaded"))


def advanced_dds_overrides_loading(state: Mapping[str, object]) -> bool:
    return bool(state.get("loading"))


def advanced_dds_overrides_mark_loading(state: MutableMapping[str, object]) -> None:
    state["loading"] = True
    state["load_requested"] = True


def advanced_dds_overrides_mark_loaded(state: MutableMapping[str, object]) -> None:
    state["loaded"] = True


def advanced_dds_overrides_clear_loading(state: MutableMapping[str, object]) -> None:
    state["loading"] = False


def advanced_dds_control_text() -> dict[str, object]:
    return {
        "section_title": "Advanced Original DDS Overrides",
        "group_title": "Advanced DDS Overrides",
        "group_tooltip": (
            "Manual original-sidecar DDS slot overrides. Use the material contract and live preview first; "
            "expand only for explicit slot repair."
        ),
        "hint_label": "Manual DDS slot repair.",
        "hint_html": (
            "<div style='font-size:8px; line-height:1.08; padding:2px 5px; border-left:3px solid #8b949e; background:#24292f;'>"
            "<span style='color:#d2a8ff; font-weight:700;'>Advanced DDS Overrides</span>"
            "<span style='color:#c9d1d9;'> | Use route source | Keep original | Choose file | Do not emit</span>"
            "</div>"
        ),
        "hint_tooltip": (
            "These rows come from the original material sidecar and are not the default replacement workflow. "
            "Use only when overriding a specific original DDS slot."
        ),
        "no_sources_hint": "No replacement texture files supplied.",
        "lazy_label": "Advanced DDS Overrides can be expanded after the material contract loads.",
        "lazy_tooltip": (
            "The original sidecar DDS slot table can contain thousands of candidate rows. "
            "Loading it lazily keeps Mesh Replacement Builder responsive at startup."
        ),
        "load_button": "Load Advanced DDS Overrides",
        "load_tooltip": "Build original sidecar DDS override rows now.",
        "apply_all_button": "Apply all Suggested for Override Source",
        "apply_all_short": "Apply Suggested",
        "apply_all_tooltip": (
            "Apply every available suggested source to the Override Source column after review. "
            "Suggestions are guesses and are not guaranteed to work in game."
        ),
        "clear_target_button": "Clear Target",
        "clear_target_tooltip": "Disable replacement texture assignments for the selected target.",
        "keep_original_button": "Keep Original",
        "keep_original_tooltip": "Keep the original DDS bindings for this target.",
        "do_not_emit_button": "Do Not Emit",
        "do_not_emit_tooltip": (
            "Clear replacement assignment for the selected target slot; patched sidecar pruning controls "
            "whether the original DDS parameter follows."
        ),
        "add_textures_button": "Add textures...",
        "add_textures_tooltip": "Add PNG/DDS texture sources that were not included when the dialog opened.",
        "add_folder_button": "Add texture folder...",
        "add_folder_tooltip": "Add a folder of PNG/DDS texture sources and rescan suggestions.",
        "filter_active_parts": "Show only active mapped parts",
        "filter_active_parts_tooltip": "When a replacement source is selected, show only targets fed by that source.",
        "filter_advanced_slots": "Show ambiguous/advanced slots",
        "filter_advanced_slots_tooltip": (
            "Show shared layers, blend/detail masks, shader-only rows, and low-confidence suggestions."
        ),
        "legacy_group_title": "Texture Slot Mapping",
        "legacy_hint": (
            "Choose replacement textures for mapped draw slots. Hover a row to highlight the affected part in the preview."
        ),
        "legacy_no_sources_hint": (
            "Texture slots were found in the asset sidecars, but no replacement texture files were supplied."
        ),
        "legacy_filter_selected": "Selected part only",
        "legacy_filter_selected_tooltip": "Show only texture rows for the currently selected replacement source part.",
        "legacy_headers": [
            "Use",
            "Part / slot",
            "Texture parameter",
            "Current DDS",
            "State",
            "Replacement source",
        ],
        "no_suggestions_title": "Apply all Suggested for Override Source",
        "no_suggestions_message": "No suggested override sources are available for the current advanced DDS override rows.",
        "apply_all_reason": "Apply every suggested source. Review the final preview before export.",
    }


def advanced_dds_loading_busy_text() -> str:
    return "Loading advanced DDS override rows..."


def advanced_dds_loading_start_text(reason: object) -> str:
    return f"Loading advanced DDS override rows ({reason})..."


def advanced_dds_preparing_rows_text(mapping_index: object) -> str:
    return f"Preparing advanced DDS override rows... {mapping_index}"


def advanced_dds_scanning_candidates_text(scan_count: object) -> str:
    return f"Scanning DDS override candidates... {scan_count}"


def advanced_dds_override_row_scan_state(
    suggested_mappings: Sequence[object],
    sidecar_bindings: Sequence[object],
    texture_sets: Mapping[str, object],
    seen_texture_rows: set[tuple[str, str, str, str]],
    *,
    binding_matches_target: Callable[[object, str], bool],
    best_source_for_slot: Callable[..., str],
    texture_is_shared: Callable[[str], bool],
    on_mapping_progress: Callable[[int], None] | None = None,
    on_scan_progress: Callable[[int], None] | None = None,
) -> AdvancedDdsOverrideRowScanState:
    rows_by_target: dict[str, list[dict[str, object]]] = {}
    target_source_indices: dict[str, tuple[int, ...]] = {}
    texture_override_rows: list[dict[str, object]] = []
    seen_rows = set(seen_texture_rows)
    scan_count = 0
    for mapping_index, mapping in enumerate(list(suggested_mappings or [])):
        if mapping_index and mapping_index % 8 == 0 and on_mapping_progress is not None:
            on_mapping_progress(mapping_index)
        target_name = str(getattr(mapping, "target_submesh_name", "") or "")
        source_indices = tuple(int(index) for index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()))
        target_rows = rows_by_target.setdefault(target_name, [])
        target_source_indices[target_name] = source_indices
        for binding in tuple(sidecar_bindings or ()):
            scan_count += 1
            if scan_count % 150 == 0 and on_scan_progress is not None:
                on_scan_progress(scan_count)
            target_path = str(getattr(binding, "texture_path", "") or "").replace("\\", "/").strip()
            if not target_path.lower().endswith(".dds"):
                continue
            if not binding_matches_target(binding, target_name):
                continue
            parameter_name = str(getattr(binding, "parameter_name", "") or "").strip()
            texture_classification = classify_texture_binding(parameter_name, target_path)
            slot_kind = str(getattr(texture_classification, "slot_kind", "") or "")
            row_key = (
                target_name.lower(),
                parameter_name.lower(),
                target_path.lower(),
                slot_kind,
            )
            if row_key in seen_rows:
                continue
            seen_rows.add(row_key)
            binding_part_name = str(
                getattr(binding, "part_name", "") or getattr(binding, "submesh_name", "") or ""
            ).strip()
            binding_shader_family = str(getattr(binding, "shader_family", "") or "").strip()
            suggested_source = (
                ""
                if texture_is_shared(target_path)
                else best_source_for_slot(
                    target_name,
                    source_indices,
                    slot_kind,
                    texture_sets,
                    parameter_name=parameter_name,
                    target_texture_path=target_path,
                    target_shader_family=binding_shader_family,
                )
            )
            row_state: dict[str, object] = {
                "target_name": target_name,
                "source_indices": source_indices,
                "target_path": target_path,
                "slot_kind": slot_kind,
                "original_slot_kind": slot_kind,
                "role_label": str(getattr(texture_classification, "slot_label", "") or slot_kind.title()),
                "original_role_label": str(getattr(texture_classification, "slot_label", "") or slot_kind.title()),
                "parameter_name": parameter_name,
                "part_display": binding_part_name or target_name,
                "shader_family": binding_shader_family,
                "sidecar_kind": str(getattr(binding, "sidecar_kind", "") or "").strip(),
                "sidecar_path": str(getattr(binding, "sidecar_path", "") or "").strip(),
                "linked_mesh": str(getattr(binding, "linked_mesh_path", "") or "").strip(),
                "classification": texture_classification,
                "visualized": bool(getattr(texture_classification, "visualized", False)),
                "suggested_source": suggested_source,
                "source_path": "",
                "checked": False,
                "override_key": row_key[:3],
                "advanced": True,
                "state_label": "Needs review",
                "confidence": "manual",
            }
            target_rows.append(row_state)
            texture_override_rows.append(row_state)
    return AdvancedDdsOverrideRowScanState(
        rows_by_target={target: tuple(rows) for target, rows in rows_by_target.items()},
        target_source_indices=target_source_indices,
        texture_override_rows=tuple(texture_override_rows),
        seen_texture_rows=seen_rows,
        scan_count=scan_count,
    )


def advanced_dds_suggested_source_counts(texture_override_rows: Sequence[Mapping[str, object]]) -> dict[str, int]:
    suggested_counts: dict[str, int] = {}
    for row_state in tuple(texture_override_rows or ()):
        suggested_source_key = str(row_state.get("suggested_source", "") or "").strip().lower()
        if suggested_source_key:
            suggested_counts[suggested_source_key] = suggested_counts.get(suggested_source_key, 0) + 1
    return suggested_counts


def advanced_dds_apply_guidance_state(
    row_state: MutableMapping[str, object],
    *,
    suggested_counts: Mapping[str, int],
    texture_row_is_shared: Callable[[Mapping[str, object]], bool],
    reset_assignment_fields: bool = False,
    texture_role_label_for_slot: Callable[[str], str] | None = None,
) -> None:
    suggested_source = str(row_state.get("suggested_source", "") or "").strip()
    guidance = classify_texture_assignment_guidance(
        str(row_state.get("parameter_name", "") or ""),
        str(row_state.get("target_path", "") or ""),
        suggested_source=suggested_source,
        repeated_suggestion_count=suggested_counts.get(suggested_source.lower(), 1) if suggested_source else 1,
    )
    row_state["guidance"] = guidance
    if reset_assignment_fields:
        row_state["checked"] = False
        row_state["source_path"] = ""
    row_state["advanced"] = bool(guidance.advanced)
    row_state["state_label"] = str(guidance.state_label or "")
    row_state["confidence"] = str(guidance.confidence or "manual")
    if texture_role_label_for_slot is not None:
        row_state["role_label"] = texture_role_label_for_slot(str(row_state.get("slot_kind", "") or "material"))
    if texture_row_is_shared(row_state):
        row_state["suggested_source"] = ""
        row_state["advanced"] = True
        row_state["state_label"] = "Original shared layer"
        row_state["confidence"] = "manual"


__all__ = [
    "AdvancedDdsOverrideRowScanState",
    "advanced_dds_apply_guidance_state",
    "advanced_dds_control_text",
    "advanced_dds_loading_busy_text",
    "advanced_dds_loading_start_text",
    "advanced_dds_override_row_scan_state",
    "advanced_dds_overrides_clear_loading",
    "advanced_dds_overrides_initial_state",
    "advanced_dds_overrides_loaded",
    "advanced_dds_overrides_loading",
    "advanced_dds_overrides_mark_loaded",
    "advanced_dds_overrides_mark_loading",
    "advanced_dds_preparing_rows_text",
    "advanced_dds_scanning_candidates_text",
    "advanced_dds_suggested_source_counts",
]
