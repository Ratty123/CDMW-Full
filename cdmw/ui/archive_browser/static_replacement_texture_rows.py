"""Pure texture-row state helpers for static replacement planning."""

from __future__ import annotations

import threading
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from cdmw.services.mesh_workflow_service import is_shared_material_layer_texture
from cdmw.models import RunCancelled


@dataclass(frozen=True, slots=True)
class TextureRowTableDisplay:
    values: tuple[str, str, str, str, str, str, str]
    tooltips: tuple[str, str, str, str, str, str, str]
    role_color: str
    source_color: str
    status_color: str
    status_foreground: str


def source_slot_for_texture_row(texture_set: object, row_state: Mapping[str, object]) -> object | None:
    slots = getattr(texture_set, "slots", {}) or {}
    slot_kind = str(row_state.get("slot_kind", "") or row_state.get("original_slot_kind", "") or "material").strip().lower()
    candidates = [slot_kind]
    if slot_kind == "material_mask":
        candidates.extend(["material_mask", "material"])
    elif slot_kind == "detail_mask":
        candidates.extend(["detail_mask", "material"])
    elif slot_kind == "material":
        candidates.extend(["material_mask", "detail_mask"])
    elif slot_kind == "base":
        candidates.append("base")
    for candidate in candidates:
        source_slot = slots.get(candidate)
        if source_slot is not None and isinstance(getattr(source_slot, "source_path", None), Path):
            return source_slot
    return None


def source_texture_reference_keys(raw_reference: object) -> set[str]:
    raw_text = str(raw_reference or "").strip()
    if not raw_text:
        return set()
    normalized_text = raw_text.replace("\\", "/").lower()
    keys = {normalized_text}
    path = Path(raw_text).expanduser()
    if path.name:
        keys.add(path.name.lower())
    if path.stem:
        keys.add(path.stem.lower())
    try:
        keys.add(str(path.resolve()).replace("\\", "/").lower())
    except Exception:
        pass
    return {key for key in keys if key}


def texture_set_for_source_index(
    source_index: int,
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
) -> object | None:
    if replacement_mesh is None or source_index < 0:
        return None
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    if source_index >= len(submeshes):
        return None
    source = submeshes[source_index]
    source_key = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip().lower()
    texture_set = texture_sets_by_key.get(source_key)
    if texture_set is not None:
        return texture_set
    source_texture_keys = source_texture_reference_keys(getattr(source, "texture", ""))
    if not source_texture_keys:
        return None
    slot_priority = {
        "base": 50,
        "normal": 30,
        "material": 20,
        "height": 10,
    }
    best_texture_set = None
    best_score = 0
    for candidate in texture_sets_by_key.values():
        for slot_kind, slot in (getattr(candidate, "slots", {}) or {}).items():
            slot_keys = source_texture_reference_keys(getattr(slot, "source_path", ""))
            if not (source_texture_keys & slot_keys):
                continue
            score = slot_priority.get(str(slot_kind or "").strip().lower(), 1)
            if score > best_score:
                best_score = score
                best_texture_set = candidate
    return best_texture_set


def source_material_group_label(
    source_index: int,
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
    source_part_adjustments: Mapping[int, object],
) -> str:
    source = None
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if 0 <= source_index < len(submeshes):
        source = submeshes[source_index]
        explicit_key = str(getattr(source, "cdmw_source_texture_set_key", "") or "").strip()
        if explicit_key:
            return explicit_key
    texture_set = texture_set_for_source_index(source_index, replacement_mesh, texture_sets_by_key)
    material_name = str(getattr(texture_set, "material_name", "") or "").strip() if texture_set is not None else ""
    material_key = material_name.lower()
    if not material_key and source is not None:
        material_key = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip().lower()
    if material_key and replacement_mesh is not None:
        duplicate_count = 0
        for candidate_index, candidate in enumerate(submeshes):
            candidate_texture_set = texture_set_for_source_index(candidate_index, replacement_mesh, texture_sets_by_key)
            candidate_key = (
                str(getattr(candidate_texture_set, "material_name", "") or "").strip().lower()
                if candidate_texture_set is not None
                else ""
            )
            if not candidate_key:
                candidate_key = str(getattr(candidate, "material", "") or getattr(candidate, "name", "") or "").strip().lower()
            if candidate_key == material_key:
                duplicate_count += 1
        adjustment = source_part_adjustments.get(source_index)
        if duplicate_count > 1 and adjustment is not None:
            role = str(getattr(adjustment, "material_role", "") or "").strip()
            glow_rgb = tuple(getattr(adjustment, "emissive_color_rgb", ()) or ())
            if role or glow_rgb:
                return f"__source_part_{source_index}_{material_key}"
    if material_name:
        return material_name
    if source is None:
        return f"source {source_index}"
    return str(getattr(source, "material", "") or getattr(source, "name", "") or f"source {source_index}").strip()


def routing_source_material_labels(
    source_indices: Sequence[int],
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
) -> tuple[str, ...]:
    material_labels: dict[str, str] = {}
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if not submeshes:
        return ()
    for source_index in tuple(source_indices or ()):
        if source_index < 0 or source_index >= len(submeshes):
            continue
        source = submeshes[source_index]
        texture_set = texture_set_for_source_index(int(source_index), replacement_mesh, texture_sets_by_key)
        label = str(getattr(texture_set, "material_name", "") or "").strip() if texture_set is not None else ""
        if not label:
            label = str(getattr(source, "material", "") or getattr(source, "name", "") or f"source {source_index}").strip()
        if label:
            material_labels.setdefault(label.lower(), label)
    return tuple(material_labels.values())


def source_material_names_for_mapping(
    mapping: object,
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
) -> tuple[str, ...]:
    material_names: dict[str, str] = {}
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if not submeshes:
        return ()
    for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
        try:
            normalized_source_index = int(source_index)
        except (TypeError, ValueError):
            continue
        if normalized_source_index < 0 or normalized_source_index >= len(submeshes):
            continue
        texture_set = texture_set_for_source_index(normalized_source_index, replacement_mesh, texture_sets_by_key)
        material_name = str(getattr(texture_set, "material_name", "") or "").strip() if texture_set is not None else ""
        if material_name:
            material_names.setdefault(material_name.lower(), material_name)
    return tuple(material_names.values())


def material_routing_conflict_messages(
    mappings: Sequence[object],
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
) -> tuple[str, ...]:
    messages: list[str] = []
    for mapping in tuple(mappings or ()):
        material_names = source_material_names_for_mapping(mapping, replacement_mesh, texture_sets_by_key)
        if len(material_names) <= 1:
            continue
        target_name = str(getattr(mapping, "target_submesh_name", "") or "target").strip()
        messages.append(
            f"{target_name} receives multiple replacement materials ({', '.join(material_names)}). "
            "One game draw/material slot can bind one source material set; split the routing or atlas/bake textures to preserve both."
        )
    return tuple(messages)


def target_material_name_for_index(target_index: int, original_mesh: object | None) -> str:
    submeshes = tuple(getattr(original_mesh, "submeshes", ()) or ()) if original_mesh is not None else ()
    if target_index < 0 or target_index >= len(submeshes):
        return ""
    target = submeshes[target_index]
    return str(getattr(target, "material", "") or getattr(target, "name", "") or f"target {target_index}").strip()


def selected_material_target_index(
    selected_target_index: Callable[[], int],
    combo_current_data: Callable[[], object],
) -> int:
    target_index = selected_target_index()
    if target_index >= 0:
        return target_index
    try:
        return int(combo_current_data())
    except (TypeError, ValueError):
        return -1


def resolve_dds_detail_preview_path(
    raw_path: object,
    slot_kind: object = "base",
    *,
    parse_dds_file: Callable[[Path], object],
    ensure_dds_display_preview: Callable[..., object],
    stop_event: threading.Event | None = None,
) -> tuple[Path | None, str]:
    raw_text = str(raw_path or "").strip()
    if not raw_text:
        return None, "No local preview source is available for this row."
    candidate = Path(raw_text).expanduser()
    if not candidate.is_file():
        return None, f"Preview source is not a local file: {raw_text}"
    if candidate.suffix.lower() != ".dds":
        return candidate, "Visible thumbnail from the source image."
    try:
        dds_info = None
        try:
            dds_info = parse_dds_file(candidate)
        except Exception:
            dds_info = None
        preview_kwargs = {
            "dds_info": dds_info,
            "max_dimension": 512,
            "slot_kind": str(slot_kind or "base").strip().lower() or "base",
        }
        if stop_event is not None:
            preview_kwargs["stop_event"] = stop_event
        preview_path = ensure_dds_display_preview(
            candidate,
            **preview_kwargs,
        )
    except RunCancelled:
        raise
    except Exception as exc:
        return None, f"DDS is not previewable here: {exc}"
    return Path(preview_path), "Visible thumbnail from decoded DDS preview."


def source_texture_slot_count(
    source_indices: Sequence[int],
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
) -> int:
    if replacement_mesh is None or not texture_sets_by_key:
        return 0
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ())
    count = 0
    for source_index in tuple(source_indices or ()):
        try:
            source = submeshes[int(source_index)]
        except (IndexError, TypeError, ValueError):
            continue
        material_name = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip().lower()
        texture_set = texture_sets_by_key.get(material_name)
        if texture_set is not None:
            count += len(getattr(texture_set, "slots", {}) or {})
    return count


def target_texture_status_details(
    target_label_text: str,
    sidecar_bindings: Sequence[object],
    source_indices: Sequence[int],
    replacement_mesh: object | None,
    texture_sets_by_key: Mapping[str, object],
) -> str:
    target_key = str(target_label_text or "").strip().lower()
    original_rows: list[str] = []
    for binding in tuple(sidecar_bindings or ()):
        binding_names = (
            str(getattr(binding, "part_name", "") or ""),
            str(getattr(binding, "submesh_name", "") or ""),
            str(getattr(binding, "material_name", "") or ""),
        )
        if target_key and not any(name.strip().lower() == target_key for name in binding_names):
            continue
        texture_path = str(getattr(binding, "texture_path", "") or getattr(binding, "reference_name", "") or "")
        if not texture_path.lower().endswith(".dds"):
            continue
        parameter = str(getattr(binding, "parameter_name", "") or getattr(binding, "sidecar_parameter_name", "") or "DDS")
        original_rows.append(f"{parameter}: {texture_path}")

    source_rows: list[str] = []
    submeshes = tuple(getattr(replacement_mesh, "submeshes", ()) or ()) if replacement_mesh is not None else ()
    if submeshes and texture_sets_by_key:
        for source_index in tuple(source_indices or ()):
            try:
                source = submeshes[int(source_index)]
            except (IndexError, TypeError, ValueError):
                continue
            material_name = str(getattr(source, "material", "") or getattr(source, "name", "") or "").strip()
            texture_set = texture_sets_by_key.get(material_name.lower())
            source_slots = sorted((getattr(texture_set, "slots", {}) or {}).items()) if texture_set is not None else ()
            for slot_kind, slot in source_slots:
                source_rows.append(f"{material_name} / {slot_kind}: {getattr(slot, 'source_path', '-')}")

    original_text = "\n".join(original_rows[:24]) if original_rows else "No original DDS rows matched this target."
    source_text = "\n".join(source_rows[:24]) if source_rows else "No routed replacement DDS source is currently detected."
    return f"Original DDS refs:\n{original_text}\n\nReplacement DDS sources:\n{source_text}"


def target_texture_status_text(
    target_label_text: str,
    sidecar_bindings: Sequence[object],
    source_count: int,
) -> str:
    target_key = str(target_label_text or "").strip().lower()
    if not target_key:
        return "No target"
    count = 0
    for binding in tuple(sidecar_bindings or ()):
        binding_names = (
            str(getattr(binding, "part_name", "") or ""),
            str(getattr(binding, "submesh_name", "") or ""),
            str(getattr(binding, "material_name", "") or ""),
        )
        if not any(name.strip().lower() == target_key for name in binding_names):
            continue
        texture_path = str(getattr(binding, "texture_path", "") or getattr(binding, "reference_name", "") or "")
        if not texture_path.lower().endswith(".dds"):
            continue
        count += 1
    if count or source_count:
        return f"Orig {count} | Src {source_count}"
    if not tuple(sidecar_bindings or ()):
        return "Sidecar unknown"
    return "Orig 0 | Src 0"


def source_indices_for_target_contract(
    target_name: str,
    material_name: str = "",
    *,
    target_index_for_name: Callable[[str], int],
    mappings: Sequence[object],
    source_indices_for_material_name: Callable[[str], Sequence[int]],
) -> tuple[int, ...]:
    target_index = target_index_for_name(target_name)
    material_index = target_index_for_name(material_name)
    normalized_target = str(target_name or "").strip().lower()
    normalized_material = str(material_name or "").strip().lower()
    for mapping in tuple(mappings or ()):
        mapping_target_index = int(getattr(mapping, "target_submesh_index", -1) or -1)
        mapping_target_name = str(getattr(mapping, "target_submesh_name", "") or "").strip().lower()
        if (
            (target_index >= 0 and mapping_target_index == target_index)
            or (material_index >= 0 and mapping_target_index == material_index)
            or (normalized_target and mapping_target_name == normalized_target)
            or (normalized_material and mapping_target_name == normalized_material)
        ):
            source_indices: list[int] = []
            for source_index in tuple(getattr(mapping, "source_submesh_indices", ()) or ()):
                try:
                    normalized_source_index = int(source_index)
                except (TypeError, ValueError):
                    continue
                if normalized_source_index >= 0:
                    source_indices.append(normalized_source_index)
            return tuple(source_indices)
    return tuple(source_indices_for_material_name(material_name or target_name))


def texture_source_choices_for_row(
    row_state: Mapping[str, object] | None,
    texture_files_for_mapping: Sequence[Path],
    *,
    effective_source: Callable[[Mapping[str, object]], str],
    source_key: Callable[[str], str],
) -> list[tuple[str, str]]:
    choices: list[tuple[str, str]] = [("Keep original", "")]
    added_source_paths: set[str] = set()

    def add_source_choice(label: str, source_path: str) -> None:
        normalized_source_path = str(source_path or "").strip()
        if not normalized_source_path:
            return
        normalized_key = source_key(normalized_source_path)
        if normalized_key in added_source_paths:
            return
        added_source_paths.add(normalized_key)
        choices.append((label, normalized_source_path))

    if row_state is not None:
        source_path_for_row = effective_source(row_state)
        suggested_source_for_row = str(row_state.get("suggested_source", "") or "").strip()
        if source_path_for_row:
            add_source_choice(f"Assigned: {Path(source_path_for_row).name}", source_path_for_row)
        if suggested_source_for_row and source_key(suggested_source_for_row) != source_key(source_path_for_row):
            add_source_choice(f"Use suggested: {Path(suggested_source_for_row).name}", suggested_source_for_row)
    for texture_file in texture_files_for_mapping:
        add_source_choice(texture_file.name, str(texture_file))
    return choices


def texture_summary_metrics(
    texture_rows: Sequence[Mapping[str, object]],
    *,
    visible_count: int | None,
    visible_predicate: Callable[[Mapping[str, object]], bool],
    assigned_predicate: Callable[[Mapping[str, object]], bool],
    show_advanced: bool,
) -> tuple[int, int, int, int]:
    rows = tuple(texture_rows or ())
    resolved_visible_count = (
        int(visible_count)
        if visible_count is not None
        else sum(1 for row_state in rows if visible_predicate(row_state))
    )
    assigned_count = sum(1 for row_state in rows if assigned_predicate(row_state))
    advanced_hidden = sum(1 for row_state in rows if bool(row_state.get("advanced")) and not bool(show_advanced))
    return resolved_visible_count, assigned_count, advanced_hidden, len(rows)


def texture_summary_label_html(
    *,
    visible_count: int,
    assigned_count: int,
    total_count: int,
    advanced_hidden: int,
) -> str:
    return (
        "<div style='line-height:1.35;'>"
        "<span style='color:#79c0ff; font-weight:700;'>Visible rows</span>"
        f"<span style='color:#f0f6fc;'> {int(visible_count):,}</span>"
        "<span style='color:#8b949e;'> | </span>"
        "<span style='color:#7ee787; font-weight:700;'>Assigned</span>"
        f"<span style='color:#f0f6fc;'> {int(assigned_count):,}/{int(total_count):,}</span>"
        "<span style='color:#8b949e;'> | </span>"
        "<span style='color:#d2a8ff; font-weight:700;'>Advanced hidden</span>"
        f"<span style='color:#f0f6fc;'> {int(advanced_hidden):,}</span>"
        "</div>"
    )


def texture_row_contract_status_color(contract_action: str, fallback_status_color: str) -> str:
    normalized = str(contract_action or "").strip()
    if normalized == "will_prune":
        return "#fb923c"
    if normalized == "kept":
        return "#8b949e"
    if normalized == "replaced":
        return "#3fb950"
    if normalized == "review":
        return "#d29922"
    return str(fallback_status_color or "#8b949e")


def texture_row_table_role_color(row_state: Mapping[str, object]) -> str:
    return {
        "base": "#7ee787",
        "normal": "#79c0ff",
        "height": "#ffa657",
        "material": "#d2a8ff",
    }.get(str(row_state.get("slot_kind", "") or "").strip().lower(), "#c9d1d9")


def texture_row_source_color(
    row_state: Mapping[str, object],
    *,
    contract_action: str,
    assigned: bool,
) -> str:
    if str(contract_action or "").strip() == "replaced" or bool(assigned):
        return "#7ee787"
    if str(row_state.get("suggested_source", "") or "").strip():
        return "#f2cc60"
    return "#8b949e"


def texture_row_table_display(
    row_state: Mapping[str, object],
    table_row: object,
    *,
    source_summary: str,
    source_summary_tooltip: str,
    effective_source: str,
    assigned: bool,
    status_color_for_label: Callable[[str], str],
    dark_foreground_statuses: Sequence[str],
) -> TextureRowTableDisplay:
    contract_action = str(row_state.get("_contract_action", "") or "").strip()
    contract_reason = str(row_state.get("_contract_reason", "") or "").strip()
    contract_source = str(row_state.get("_contract_selected_source", "") or "").strip()
    status = getattr(table_row, "status", None)
    status_label = contract_action.replace("_", " ").title() if contract_action else str(getattr(status, "label", "") or "")
    status_color = texture_row_contract_status_color(
        contract_action,
        status_color_for_label(status_label),
    )
    values = (
        str(getattr(table_row, "part_label", "") or getattr(table_row, "part_material", "") or ""),
        str(source_summary or ""),
        str(getattr(table_row, "role", "") or ""),
        str(getattr(table_row, "original_slot", "") or ""),
        Path(contract_source).name if contract_source else str(getattr(table_row, "override_source", "") or ""),
        status_label,
        contract_reason or str(getattr(table_row, "controls", "") or ""),
    )
    source_path = contract_source or effective_source
    status_detail = str(getattr(status, "detail", "") or "")
    controls = str(getattr(table_row, "controls", "") or "")
    tooltips = (
        str(getattr(table_row, "full_part_material", "") or getattr(table_row, "part_material", "") or ""),
        str(source_summary_tooltip or ""),
        controls,
        str(getattr(table_row, "target_dds", "") or getattr(table_row, "original_slot", "") or ""),
        source_path or status_detail or str(getattr(table_row, "override_source", "") or ""),
        contract_reason or status_detail or status_label,
        controls,
    )
    return TextureRowTableDisplay(
        values=values,
        tooltips=tooltips,
        role_color=texture_row_table_role_color(row_state),
        source_color=texture_row_source_color(row_state, contract_action=contract_action, assigned=assigned),
        status_color=status_color,
        status_foreground="#0d1117" if status_label in set(dark_foreground_statuses) else "#ffffff",
    )


def texture_slot_contract_key(slot_kind: str) -> str:
    normalized = str(slot_kind or "").strip().lower()
    if normalized in {"material", "material_mask", "detail_mask", "mask"}:
        return "material"
    return normalized or "material"


def texture_row_is_shared(row_state: Mapping[str, object]) -> bool:
    return is_shared_material_layer_texture(str(row_state.get("target_path", "") or ""))


def texture_row_override_key(row_state: Mapping[str, object]) -> tuple[str, str, str]:
    stored_key = row_state.get("override_key")
    if isinstance(stored_key, tuple) and len(stored_key) == 3:
        return (
            str(stored_key[0] or "").lower(),
            str(stored_key[1] or "").lower(),
            str(stored_key[2] or "").lower(),
        )
    return (
        str(row_state.get("target_name", "") or "").strip().lower(),
        str(row_state.get("parameter_name", "") or "").strip().lower(),
        str(row_state.get("target_path", "") or "").replace("\\", "/").strip().lower(),
    )


def texture_row_effective_source(
    row_state: Mapping[str, object],
    texture_override_assignments: Mapping[tuple[str, str, str], object],
) -> str:
    row_key = texture_row_override_key(row_state)
    if row_key in texture_override_assignments:
        return str(texture_override_assignments.get(row_key, "") or "").strip()
    if bool(row_state.get("checked")):
        return str(row_state.get("source_path", "") or "").strip()
    return ""


def texture_row_is_assigned(
    row_state: Mapping[str, object],
    texture_override_assignments: Mapping[tuple[str, str, str], object],
) -> bool:
    return bool(texture_row_effective_source(row_state, texture_override_assignments))


def sync_texture_row_assignment_state(
    row_state: dict[str, object],
    texture_override_assignments: Mapping[tuple[str, str, str], object],
) -> dict[str, object]:
    source_path = texture_row_effective_source(row_state, texture_override_assignments)
    row_state["source_path"] = source_path
    row_state["checked"] = bool(source_path)
    return row_state


def texture_overrides_dirty_initial_state() -> dict[str, bool]:
    return {"dirty": True}


def set_texture_row_assignment(
    row_state: dict[str, object],
    texture_override_assignments: dict[tuple[str, str, str], str],
    texture_overrides_dirty: dict[str, bool],
    *,
    source_path: str,
    checked: bool,
) -> None:
    row_key = texture_row_override_key(row_state)
    normalized_source_path = str(source_path or "").strip()
    if checked and normalized_source_path:
        texture_override_assignments[row_key] = normalized_source_path
    else:
        texture_override_assignments[row_key] = ""
        normalized_source_path = ""
    row_state["source_path"] = normalized_source_path
    row_state["checked"] = bool(normalized_source_path)
    texture_overrides_dirty["dirty"] = True


def texture_row_visible(
    row_state: Mapping[str, object],
    *,
    show_advanced: bool,
    filter_selected: bool,
    selected_source_index: int,
) -> bool:
    if not bool(show_advanced) and bool(row_state.get("advanced")):
        return False
    source_indices = tuple(row_state.get("source_indices", ()) or ())
    if filter_selected and selected_source_index >= 0 and selected_source_index not in source_indices:
        return False
    return True


def texture_row_current_source_indices(
    row_state: Mapping[str, object] | None,
    *,
    source_indices_for_target_name: Callable[[str], Sequence[int]],
) -> tuple[int, ...]:
    if row_state is None:
        return ()
    target_name = str(row_state.get("target_name", "") or "").strip()
    source_indices = tuple(source_indices_for_target_name(target_name)) if target_name else ()
    if source_indices:
        return tuple(source_indices)
    parsed: list[int] = []
    for raw_index in tuple(row_state.get("source_indices", ()) or ()):
        try:
            source_index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if source_index not in parsed:
            parsed.append(source_index)
    return tuple(parsed)


def texture_row_source_summary(
    source_indices: Sequence[int],
    *,
    source_display_name: Callable[[int], str],
    limit: int = 3,
) -> str:
    indices = tuple(source_indices or ())
    if not indices:
        return "No replacement source"
    labels = [source_display_name(source_index) for source_index in indices[:limit]]
    if len(indices) > limit:
        labels.append(f"+{len(indices) - limit} more")
    return ", ".join(labels)


def texture_row_can_auto_apply(row_state: Mapping[str, object], guidance: object) -> bool:
    if not str(row_state.get("suggested_source", "") or "").strip():
        return False
    if texture_row_is_shared(row_state):
        return False
    slot_kind = str(row_state.get("slot_kind", "") or "").strip().lower()
    classification = row_state.get("classification")
    if bool(getattr(guidance, "checked_by_default", False)):
        return True
    if slot_kind in {"base", "normal", "height"} and bool(getattr(classification, "visualized", False)):
        return True
    if slot_kind in {"material", "material_mask", "detail_mask"}:
        subtype = str(getattr(classification, "semantic_subtype", "") or "").strip().lower()
        return subtype in {
            "material_mask",
            "material_response",
            "packed_mask",
            "orm",
            "rma",
            "mra",
            "arm",
            "roughness",
            "metallic",
            "ao",
            "specular",
            "subsurface",
        }
    return False


def texture_row_can_apply_suggested_for_target(row_state: Mapping[str, object], guidance: object) -> bool:
    if texture_row_can_auto_apply(row_state, guidance):
        return True
    state_label = str(getattr(guidance, "state_label", "") or "").strip().lower()
    if "repeated" not in state_label:
        return False
    if not str(row_state.get("suggested_source", "") or "").strip():
        return False
    if texture_row_is_shared(row_state):
        return False
    classification = row_state.get("classification")
    slot_kind = str(row_state.get("slot_kind", "") or "").strip().lower()
    subtype = str(getattr(classification, "semantic_subtype", "") or "").strip().lower()
    if subtype in {
        "color_blending_mask",
        "detail_mask",
        "emissive",
        "rgb_layer",
        "skin_detail_mask",
        "opacity_mask",
        "flow_vector",
        "direction_vector",
    }:
        return False
    return bool(getattr(classification, "visualized", False)) and slot_kind in {"base", "normal", "height", "material_mask"}


__all__ = [
    "TextureRowTableDisplay",
    "material_routing_conflict_messages",
    "routing_source_material_labels",
    "source_indices_for_target_contract",
    "source_material_names_for_mapping",
    "source_material_group_label",
    "source_slot_for_texture_row",
    "source_texture_reference_keys",
    "source_texture_slot_count",
    "selected_material_target_index",
    "resolve_dds_detail_preview_path",
    "set_texture_row_assignment",
    "sync_texture_row_assignment_state",
    "target_material_name_for_index",
    "target_texture_status_details",
    "target_texture_status_text",
    "texture_set_for_source_index",
    "texture_source_choices_for_row",
    "texture_row_can_apply_suggested_for_target",
    "texture_row_can_auto_apply",
    "texture_row_contract_status_color",
    "texture_row_current_source_indices",
    "texture_row_effective_source",
    "texture_overrides_dirty_initial_state",
    "texture_row_is_assigned",
    "texture_row_is_shared",
    "texture_row_override_key",
    "texture_row_source_summary",
    "texture_row_source_color",
    "texture_row_table_role_color",
    "texture_row_table_display",
    "texture_row_visible",
    "texture_slot_contract_key",
    "texture_summary_label_html",
    "texture_summary_metrics",
]
