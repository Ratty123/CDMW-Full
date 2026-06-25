"""Virtual texture contract helpers for static replacement."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence
from pathlib import Path

from cdmw.modding.material_replacer import SidecarPatchPlan, patch_material_sidecar_text
from cdmw.modding.static_mesh_replacer import StaticTextureSlotOverride


def alignment_virtual_contract_rows(
    parsed_mappings: Sequence[object],
    *,
    texture_override_rows: Sequence[MutableMapping[str, object]],
    texture_override_assignments: Mapping[tuple[str, str, str], object],
    copied_overrides: Sequence[StaticTextureSlotOverride],
    texture_rows_by_target: Mapping[object, object],
    texture_row_assigned: Callable[[Mapping[str, object]], bool],
    texture_row_current_source_indices: Callable[[Mapping[str, object]], Sequence[int]],
    virtual_contract_prune_removed_targets_enabled: Callable[[], bool],
    virtual_contract_prune_unmapped_enabled: Callable[[], bool],
    texture_row_effective_source: Callable[[Mapping[str, object]], str],
    texture_row_is_shared: Callable[[Mapping[str, object]], bool],
    texture_role_label_for_slot: Callable[[str], str],
    texture_row_override_key: Callable[[Mapping[str, object]], tuple[str, str, str]],
    texture_override_row_sort_key: Callable[..., object],
    texture_slot_contract_key: Callable[[str], str],
) -> list[dict[str, object]]:
    mappings_by_target: dict[str, object] = {
        str(getattr(mapping, "target_submesh_name", "") or "").strip().lower(): mapping
        for mapping in tuple(parsed_mappings or ())
    }
    copied_by_target_slot: dict[tuple[str, str], StaticTextureSlotOverride] = {}
    for copied_override in tuple(copied_overrides or ()):
        copied_by_target_slot[
            (
                str(copied_override.target_material_name or "").strip().lower(),
                texture_slot_contract_key(str(copied_override.slot_kind or "")),
            )
        ] = copied_override

    contract_rows: list[dict[str, object]] = []
    for row_state in sorted(
        texture_override_rows,
        key=lambda row_state: texture_override_row_sort_key(
            row_state,
            texture_rows_by_target,
            assigned_predicate=texture_row_assigned,
        ),
    ):
        target_name = str(row_state.get("target_name", "") or "").strip()
        mapping = mappings_by_target.get(target_name.lower())
        if mapping is not None:
            source_indices = tuple(int(index) for index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()))
        else:
            source_indices = tuple(int(index) for index in tuple(texture_row_current_source_indices(row_state) or ()))
        target_path = str(row_state.get("target_path", "") or "").replace("\\", "/").strip()
        slot_kind = texture_slot_contract_key(str(row_state.get("slot_kind", "") or "material"))
        original_dds = target_path
        row_key = texture_row_override_key(row_state)
        selected_source = ""
        action = "kept"
        reason = "Keep original"
        if not source_indices:
            if virtual_contract_prune_removed_targets_enabled():
                action = "will_prune"
                reason = "Removed target"
            else:
                action = "kept"
                reason = "Removed target, sidecar kept"
        elif row_key in texture_override_assignments:
            selected_source = str(texture_override_assignments.get(row_key, "") or "").strip()
            if selected_source:
                action = "replaced"
                reason = "Manual target-slot override"
            elif virtual_contract_prune_unmapped_enabled():
                action = "will_prune"
                reason = "Manual do-not-emit"
            else:
                action = "kept"
                reason = "Manual keep original"
        else:
            copied_override = copied_by_target_slot.get((target_name.lower(), slot_kind))
            if copied_override is not None and str(copied_override.source_path or "").strip():
                selected_source = str(copied_override.source_path or "").strip()
                action = "replaced"
                reason = "Copied original source texture"
            else:
                selected_source = texture_row_effective_source(row_state)
                if selected_source:
                    action = "replaced"
                    reason = "Route source"
                elif bool(row_state.get("advanced")) or texture_row_is_shared(row_state):
                    action = "review"
                    reason = str(row_state.get("state_label", "") or "Review ambiguous/support texture slot")
                else:
                    action = "kept"
                    reason = "Mapped target; original DDS remains until a replacement source is chosen"

        preview_source = selected_source if action == "replaced" else ""
        final_output = original_dds if selected_source else original_dds
        row_state["_contract_action"] = action
        row_state["_contract_reason"] = reason
        row_state["_contract_selected_source"] = selected_source
        row_state["_contract_final_output_dds"] = final_output
        contract_rows.append(
            {
                "target_name": target_name,
                "source_indices": tuple(source_indices),
                "parameter_name": str(row_state.get("parameter_name", "") or "").strip(),
                "part_display": str(row_state.get("part_display", "") or target_name),
                "slot_kind": slot_kind,
                "role_label": str(row_state.get("role_label", "") or texture_role_label_for_slot(slot_kind)),
                "original_dds": original_dds,
                "selected_source": selected_source,
                "preview_source": preview_source,
                "final_output_dds": final_output,
                "sidecar_action": action,
                "reason": reason,
                "visualized": bool(row_state.get("visualized")),
                "row_state": row_state,
                "sidecar_path": str(row_state.get("sidecar_path", "") or row_state.get("sidecar_kind", "") or ""),
            }
        )
    return contract_rows


def alignment_virtual_contract_preview_specs(
    rows: Sequence[Mapping[str, object]],
    *,
    alignment_contract_preview_path: Callable[[str], str],
) -> list[tuple[str, str, str, str, tuple[int, ...], str]]:
    specs: list[tuple[str, str, str, str, tuple[int, ...], str]] = []
    for row in tuple(rows or ()):
        if str(row.get("sidecar_action", "") or "") != "replaced":
            continue
        source_path = str(row.get("preview_source", "") or "").strip()
        if not source_path or not bool(row.get("visualized")):
            continue
        source_indices = tuple(int(index) for index in tuple(row.get("source_indices", ()) or ()))
        specs.append(
            (
                str(row.get("target_name", "") or ""),
                str(row.get("slot_kind", "") or ""),
                alignment_contract_preview_path(source_path),
                Path(source_path).name,
                source_indices,
                source_path,
            )
        )
    return specs


def alignment_virtual_sidecar_contract_state(
    rows: Sequence[Mapping[str, object]],
    preview_specs: Sequence[object],
    *,
    sidecar_text_for_path: Callable[[str], str],
    prune_removed_targets_enabled: bool,
    prune_unmapped_enabled: bool,
    patch_sidecar_text: Callable[[str, SidecarPatchPlan], tuple[str, object]] = patch_material_sidecar_text,
) -> dict[str, object]:
    replacements_by_sidecar: dict[str, dict[str, str]] = {}
    keep_rules_by_sidecar: dict[str, set[tuple[str, str]]] = {}
    prune_materials_by_sidecar: dict[str, set[str]] = {}
    for row in tuple(rows or ()):
        target_name = str(row.get("target_name", "") or "").strip()
        parameter_name = str(row.get("parameter_name", "") or "").strip()
        sidecar_path = str(row.get("sidecar_path", "") or "").strip()
        sidecar_key = sidecar_path or "__alignment_sidecar__"
        action = str(row.get("sidecar_action", "") or "")
        original_dds = str(row.get("original_dds", "") or "").strip()
        final_dds = str(row.get("final_output_dds", "") or "").strip()
        if action != "will_prune" and target_name and parameter_name:
            keep_rules_by_sidecar.setdefault(sidecar_key, set()).add((target_name, parameter_name))
        if action == "replaced" and original_dds and final_dds:
            replacements_by_sidecar.setdefault(sidecar_key, {})[original_dds] = final_dds
        if action == "will_prune" and target_name:
            prune_materials_by_sidecar.setdefault(sidecar_key, set()).add(target_name)

    patched_sidecar_texts: dict[str, str] = {}
    sidecar_reports: list[object] = []
    sidecar_keys = set(replacements_by_sidecar) | set(keep_rules_by_sidecar) | set(prune_materials_by_sidecar)
    for sidecar_key in sorted(sidecar_keys):
        source_text = sidecar_text_for_path(sidecar_key)
        if not source_text:
            continue
        patched_text, report = patch_sidecar_text(
            source_text,
            SidecarPatchPlan(
                sidecar_path=sidecar_key,
                texture_path_replacements=dict(replacements_by_sidecar.get(sidecar_key, {})),
                texture_parameter_keep_rules=sorted(keep_rules_by_sidecar.get(sidecar_key, set())),
                prune_unmapped_texture_parameters=bool(prune_removed_targets_enabled or prune_unmapped_enabled),
                prune_material_names=sorted(prune_materials_by_sidecar.get(sidecar_key, set())),
            ),
        )
        patched_sidecar_texts[sidecar_key] = patched_text
        sidecar_reports.append(report)

    return {
        "rows": tuple(rows or ()),
        "preview_specs": tuple(preview_specs or ()),
        "patched_sidecar_texts": patched_sidecar_texts,
        "sidecar_reports": tuple(sidecar_reports),
    }


def alignment_virtual_texture_contract_defaults(
    contract: MutableMapping[str, object],
) -> MutableMapping[str, object]:
    contract.setdefault("rows", ())
    contract.setdefault("preview_specs", ())
    contract.setdefault("patched_sidecar_texts", {})
    contract.setdefault("sidecar_reports", ())
    return contract


def copied_source_texture_slot_overrides(
    parsed_mappings: Sequence[object],
    *,
    original_part_texture_intent_rows: Callable[[int], Sequence[Mapping[str, object]]],
    copied_original_texture_intents_by_source: Mapping[int, Sequence[Mapping[str, object]]],
    copied_original_texture_disabled_sources: Sequence[int] | set[int],
    source_display_name: Callable[[int], str],
    texture_slot_contract_key: Callable[[str], str],
    occupied_keys: set[tuple[str, str]] | None = None,
) -> tuple[StaticTextureSlotOverride, ...]:
    """Convert copied-original source DDS intent into target-scoped overrides."""
    occupied = occupied_keys if occupied_keys is not None else set()
    disabled_sources = {int(index) for index in tuple(copied_original_texture_disabled_sources or ())}
    copied_rows_by_source = copied_original_texture_intents_by_source if hasattr(copied_original_texture_intents_by_source, "get") else {}

    def _target_rows(index: int) -> tuple[Mapping[str, object], ...]:
        if not callable(original_part_texture_intent_rows):
            return ()
        return tuple(original_part_texture_intent_rows(index) or ())

    def _slot_key(value: object) -> str:
        if callable(texture_slot_contract_key):
            return texture_slot_contract_key(str(value or ""))
        return str(value or "").strip().lower() or "material"

    def _source_label(index: int) -> str:
        if callable(source_display_name):
            return str(source_display_name(index))
        return f"source {index}"

    overrides: list[StaticTextureSlotOverride] = []
    for mapping in tuple(parsed_mappings or ()):
        try:
            target_index = int(getattr(mapping, "target_submesh_index", -1))
        except (TypeError, ValueError):
            continue
        target_rows = _target_rows(target_index)
        if not target_rows:
            continue
        target_rows_by_slot: dict[str, list[Mapping[str, object]]] = {}
        for target_row in target_rows:
            target_rows_by_slot.setdefault(
                _slot_key(target_row.get("slot_kind", "")),
                [],
            ).append(target_row)
        for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
            try:
                source_index = int(source_index)
            except (TypeError, ValueError):
                continue
            if source_index in disabled_sources:
                continue
            copied_rows = tuple(copied_rows_by_source.get(source_index, ()) or ())
            if not copied_rows:
                continue
            for copied_row in copied_rows:
                source_path = str(copied_row.get("source_path", "") or "").strip()
                if not source_path:
                    continue
                slot_key = _slot_key(copied_row.get("slot_kind", ""))
                matching_target_rows = list(target_rows_by_slot.get(slot_key, ()))
                if not matching_target_rows and slot_key == "base":
                    matching_target_rows = list(target_rows_by_slot.get("material", ()))
                for target_row in matching_target_rows[:1]:
                    target_path = str(target_row.get("texture_path", "") or "").strip()
                    slot_kind = str(target_row.get("slot_kind", "") or copied_row.get("slot_kind", "") or "material")
                    if not target_path:
                        continue
                    override_key = (target_path.replace("\\", "/").lower(), _slot_key(slot_kind))
                    if override_key in occupied:
                        continue
                    occupied.add(override_key)
                    overrides.append(
                        StaticTextureSlotOverride(
                            target_texture_path=target_path,
                            source_path=source_path,
                            slot_kind=slot_kind,
                            target_material_name=str(getattr(mapping, "target_submesh_name", "") or ""),
                            enabled=True,
                            source_material_name=_source_label(source_index),
                        )
                    )
    return tuple(overrides)


def copied_source_texture_preview_specs(
    parsed_mappings: Sequence[object],
    overrides: Sequence[StaticTextureSlotOverride],
    *,
    source_preview_path: Callable[[str], str],
) -> tuple[tuple[str, str, str, str, tuple[int, ...], str], ...]:
    specs: list[tuple[str, str, str, str, tuple[int, ...], str]] = []
    for override in tuple(overrides or ()):
        source_path = str(override.source_path or "")
        if not source_path:
            continue
        source_indices = tuple(
            int(source_index)
            for mapping in tuple(parsed_mappings or ())
            if str(getattr(mapping, "target_submesh_name", "") or "") == str(override.target_material_name or "")
            for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ())
        )
        specs.append(
            (
                str(override.target_material_name or ""),
                str(override.slot_kind or ""),
                source_preview_path(source_path),
                Path(source_path).name,
                source_indices,
                source_path,
            )
        )
    return tuple(specs)


def virtual_contract_sidecar_text_for_path(
    sidecar_path: str,
    *,
    sidecar_texts_by_normalized_path: Mapping[str, Sequence[object]],
    sidecar_texts_by_basename: Mapping[str, Sequence[object]],
    sidecar_text_values: Sequence[object],
    normalize_texture_reference: Callable[[str], str],
) -> str:
    normalized = normalize_texture_reference(sidecar_path)
    for key in (
        normalized,
        str(sidecar_path or "").replace("\\", "/").strip().lower(),
        Path(str(sidecar_path or "")).name.lower(),
    ):
        if not key:
            continue
        candidates = sidecar_texts_by_normalized_path.get(key)
        if candidates:
            return str(candidates[0] or "")
        candidates = sidecar_texts_by_basename.get(key)
        if candidates:
            return str(candidates[0] or "")
    for values in sidecar_texts_by_normalized_path.values():
        if values:
            return str(values[0] or "")
    return str(sidecar_text_values[0] if sidecar_text_values else "")


__all__ = [
    "alignment_virtual_contract_preview_specs",
    "alignment_virtual_contract_rows",
    "alignment_virtual_sidecar_contract_state",
    "alignment_virtual_texture_contract_defaults",
    "copied_source_texture_preview_specs",
    "copied_source_texture_slot_overrides",
    "virtual_contract_sidecar_text_for_path",
]
