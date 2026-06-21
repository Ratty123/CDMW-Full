"""Selection-view state helpers for static replacement UI."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping, Sequence


def single_selection_index_initial_state() -> dict[str, int]:
    return {"index": -1}


def mesh_replacement_selection_view_initial_model() -> dict[str, object]:
    return {
        "kind": "none",
        "source_indices": (),
        "target_indices": (),
        "material_name": "",
        "texture_role": "",
        "texture_path": "",
        "warning": "",
    }


def target_source_indices(
    target_index: int,
    mapping_edits_by_target: Mapping[int, object],
    *,
    parse_mapping_edit: Callable[[object], Sequence[int]],
) -> tuple[int, ...]:
    edit = mapping_edits_by_target.get(int(target_index))
    if edit is None:
        return ()
    return tuple(int(index) for index in parse_mapping_edit(edit))


def nonnegative_indices(raw_indices: Sequence[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw_index in tuple(raw_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index >= 0:
            normalized.append(index)
    return tuple(normalized)


def unique_nonnegative_indices(raw_indices: Sequence[int]) -> tuple[int, ...]:
    normalized: list[int] = []
    for raw_index in tuple(raw_indices or ()):
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            continue
        if index >= 0 and index not in normalized:
            normalized.append(index)
    return tuple(normalized)


def update_mesh_replacement_selection_view_model(
    model: MutableMapping[str, object],
    *,
    kind: str,
    source_indices: Sequence[int] = (),
    target_indices: Sequence[int] = (),
    material_name: str = "",
    texture_role: str = "",
    texture_path: str = "",
    warning: str = "",
) -> None:
    model["kind"] = str(kind or "none")
    model["source_indices"] = nonnegative_indices(source_indices)
    model["target_indices"] = nonnegative_indices(target_indices)
    model["material_name"] = str(material_name or "")
    model["texture_role"] = str(texture_role or "")
    model["texture_path"] = str(texture_path or "")
    model["warning"] = str(warning or "")


def target_mapping_selection_view_payload(
    *,
    selected_target_index: int,
    target_index: int,
    source_indices: Sequence[int],
) -> dict[str, object] | None:
    if int(selected_target_index) != int(target_index):
        return None
    return {
        "kind": "target",
        "target_indices": (int(target_index),),
        "source_indices": nonnegative_indices(source_indices),
    }


def source_selection_view_payload(source_index: int, target_indices: Sequence[int]) -> dict[str, object]:
    if int(source_index) < 0:
        return {"kind": "none", "source_indices": (), "target_indices": tuple(int(index) for index in tuple(target_indices or ()))}
    return {
        "kind": "source",
        "source_indices": (int(source_index),),
        "target_indices": tuple(int(index) for index in tuple(target_indices or ())),
    }


def target_selection_view_payload(target_index: int, source_indices: Sequence[int] = ()) -> dict[str, object]:
    if int(target_index) < 0:
        return {"kind": "none", "target_indices": (), "source_indices": tuple(int(index) for index in tuple(source_indices or ()))}
    return {
        "kind": "target",
        "target_indices": (int(target_index),),
        "source_indices": tuple(int(index) for index in tuple(source_indices or ())),
    }


def selection_view_update_kwargs(payload: Mapping[str, object]) -> dict[str, object]:
    return {
        "kind": str(payload.get("kind", "none") or "none"),
        "source_indices": nonnegative_indices(payload.get("source_indices", ())),  # type: ignore[arg-type]
        "target_indices": nonnegative_indices(payload.get("target_indices", ())),  # type: ignore[arg-type]
        "material_name": str(payload.get("material_name", "") or ""),
        "texture_role": str(payload.get("texture_role", "") or ""),
        "texture_path": str(payload.get("texture_path", "") or ""),
        "warning": str(payload.get("warning", "") or ""),
    }


def target_selection_highlight_state(target_index: int, source_indices: Sequence[int] = ()) -> dict[str, tuple[int, ...]]:
    try:
        normalized_target_index = int(target_index)
    except (TypeError, ValueError):
        normalized_target_index = -1
    if normalized_target_index < 0:
        return {"target_original_indices": (), "target_source_indices": ()}
    return {
        "target_original_indices": (normalized_target_index,),
        "target_source_indices": nonnegative_indices(source_indices),
    }


def source_selection_highlight_state(source_index: int) -> dict[str, tuple[int, ...]]:
    source_indices = single_selection_highlight_indices(source_index)
    return {
        "source_indices": source_indices,
        "transform_source_indices": source_indices,
        "target_original_indices": (),
        "target_source_indices": (),
    }


def single_selection_highlight_indices(selected_index: int) -> tuple[int, ...]:
    try:
        normalized_index = int(selected_index)
    except (TypeError, ValueError):
        normalized_index = -1
    return (normalized_index,) if normalized_index >= 0 else ()


def source_selection_state(source_index: int, target_indices: Sequence[int]) -> dict[str, object]:
    try:
        normalized_source_index = int(source_index)
    except (TypeError, ValueError):
        normalized_source_index = -1
    highlight_state = source_selection_highlight_state(normalized_source_index)
    return {
        "source_index": normalized_source_index,
        "source_highlight_indices": highlight_state["source_indices"],
        "transform_source_indices": highlight_state["transform_source_indices"],
        "target_original_highlight_indices": (),
        "target_source_highlight_indices": (),
        "selection_view": source_selection_view_payload(normalized_source_index, target_indices),
    }


def d3d11_source_selection_index(current_source_index: int, source_indices: Sequence[int]) -> int:
    normalized_source_indices = nonnegative_indices(source_indices)
    if not normalized_source_indices:
        return -1
    try:
        normalized_current = int(current_source_index)
    except (TypeError, ValueError):
        normalized_current = -1
    return normalized_current if normalized_current in normalized_source_indices else int(normalized_source_indices[0])


def selection_filter_refresh_needed(*, has_filter_refresh: bool, selected_filter_enabled: bool) -> bool:
    return bool(has_filter_refresh) and bool(selected_filter_enabled)


def material_plan_highlight_state(
    *,
    has_item: bool,
    source_indices: Sequence[int],
    target_index: int,
    material_name: str,
    texture_role: str,
    texture_path: str,
) -> dict[str, object]:
    target_highlight_state = target_selection_highlight_state(target_index, source_indices)
    normalized_source_indices = nonnegative_indices(source_indices)
    target_indices = target_highlight_state["target_original_indices"]
    return {
        "selected_source_index": -1,
        "source_highlight_indices": (),
        "transform_source_indices": (),
        "selected_target_index": int(target_index) if target_indices else -1,
        "target_source_highlight_indices": target_highlight_state["target_source_indices"],
        "target_original_highlight_indices": target_indices,
        "texture_plan_source": {
            "material_name": str(material_name or ""),
            "source_indices": normalized_source_indices,
        },
        "selection_view": {
            "kind": "material" if bool(has_item) else "none",
            "source_indices": normalized_source_indices,
            "target_indices": target_indices,
            "material_name": str(material_name or ""),
            "texture_role": str(texture_role or ""),
            "texture_path": str(texture_path or ""),
        },
    }


def added_part_texture_highlight_state(
    *,
    source_index: int,
    target_indices: Sequence[int],
    material_name: str,
    texture_state: str,
) -> dict[str, object]:
    normalized_source_indices = single_selection_highlight_indices(source_index)
    has_source = bool(normalized_source_indices)
    normalized_targets = nonnegative_indices(target_indices) if has_source else ()
    has_targets = bool(normalized_targets)
    return {
        "selected_source_index": -1,
        "source_highlight_indices": normalized_source_indices,
        "transform_source_indices": (),
        "selected_target_index": int(normalized_targets[0]) if has_targets else -1,
        "target_source_highlight_indices": normalized_source_indices if has_targets else (),
        "target_original_highlight_indices": normalized_targets,
        "selection_view": {
            "kind": "source" if has_source else "none",
            "source_indices": normalized_source_indices,
            "target_indices": normalized_targets,
            "material_name": str(material_name or "") if has_source else "",
            "warning": "" if str(texture_state or "") == "Ready" else str(texture_state or ""),
        },
    }


def original_selection_index(raw_indices: object) -> int:
    try:
        raw_index = raw_indices[0] if isinstance(raw_indices, (tuple, list)) and raw_indices else raw_indices
        return int(raw_index)
    except (TypeError, ValueError):
        return -1


def original_selection_state(raw_indices: object) -> dict[str, object]:
    selected_index = original_selection_index(raw_indices)
    return {
        "original_index": selected_index,
        "original_highlight_indices": single_selection_highlight_indices(selected_index),
        "selection_view": target_selection_view_payload(selected_index),
    }


def target_selection_index(raw_value: object) -> int:
    try:
        return int(raw_value)
    except (TypeError, ValueError):
        return -1


def target_selection_state(raw_value: object, source_indices: Sequence[int] = ()) -> dict[str, object]:
    selected_index = target_selection_index(raw_value)
    highlight_state = target_selection_highlight_state(selected_index, source_indices)
    return {
        "target_index": selected_index,
        "target_original_highlight_indices": highlight_state["target_original_indices"],
        "target_source_highlight_indices": highlight_state["target_source_indices"],
        "selection_view": target_selection_view_payload(
            selected_index,
            highlight_state["target_source_indices"],
        ),
    }


def part_selection_state_active(
    *,
    selected_source_index: int,
    selected_original_index: int,
    selected_target_index: int,
    selected_source_highlights: Sequence[int],
    selected_target_source_highlights: Sequence[int],
    selected_original_highlights: Sequence[int],
    selected_target_original_highlights: Sequence[int],
    source_tree_has_selection: bool,
    original_tree_has_selection: bool,
    mapping_tree_has_selection: bool,
) -> bool:
    return (
        int(selected_source_index) >= 0
        or int(selected_original_index) >= 0
        or int(selected_target_index) >= 0
        or bool(tuple(selected_source_highlights or ()))
        or bool(tuple(selected_target_source_highlights or ()))
        or bool(tuple(selected_original_highlights or ()))
        or bool(tuple(selected_target_original_highlights or ()))
        or bool(source_tree_has_selection)
        or bool(original_tree_has_selection)
        or bool(mapping_tree_has_selection)
    )


def part_selection_clear_state() -> dict[str, object]:
    return {
        "selected_source_index": -1,
        "selected_original_index": -1,
        "selected_target_index": -1,
        "selected_source_highlights": (),
        "selected_target_source_highlights": (),
        "selected_original_highlights": (),
        "selected_target_original_highlights": (),
        "selection_view": {"kind": "none", "source_indices": (), "target_indices": ()},
    }


def part_selection_clear_scope_state(scope: str) -> dict[str, object]:
    normalized_scope = str(scope or "").strip().lower()
    state: dict[str, object] = {
        "selected_source_index": None,
        "selected_original_index": None,
        "selected_target_index": None,
        "clear_source_highlights": False,
        "clear_original_highlights": False,
        "clear_target_source_highlights": False,
        "clear_target_original_highlights": False,
        "clear_transform_sources": False,
        "selection_view": {"kind": "none", "source_indices": (), "target_indices": ()},
    }
    if normalized_scope in {"source", "all"}:
        state["selected_source_index"] = -1
        state["clear_source_highlights"] = True
        state["clear_transform_sources"] = True
    if normalized_scope in {"original", "all"}:
        state["selected_original_index"] = -1
        state["clear_original_highlights"] = True
        state["clear_transform_sources"] = True
    if normalized_scope in {"target", "all"}:
        state["selected_target_index"] = -1
        state["clear_target_source_highlights"] = True
        state["clear_target_original_highlights"] = True
    return state


from cdmw.ui.archive_browser.static_replacement_selection_highlight_state import (  # noqa: E402
    parts_outliner_target_selection_state,
    selection_highlight_sets_state,
    texture_row_selection_highlight_state,
)


__all__ = [
    "added_part_texture_highlight_state",
    "d3d11_source_selection_index",
    "material_plan_highlight_state",
    "mesh_replacement_selection_view_initial_model",
    "nonnegative_indices",
    "original_selection_index",
    "original_selection_state",
    "part_selection_clear_state",
    "part_selection_clear_scope_state",
    "part_selection_state_active",
    "parts_outliner_target_selection_state",
    "selection_filter_refresh_needed",
    "selection_highlight_sets_state",
    "selection_view_update_kwargs",
    "source_selection_highlight_state",
    "source_selection_state",
    "source_selection_view_payload",
    "single_selection_highlight_indices",
    "single_selection_index_initial_state",
    "target_source_indices",
    "target_mapping_selection_view_payload",
    "target_selection_highlight_state",
    "target_selection_index",
    "target_selection_state",
    "target_selection_view_payload",
    "texture_row_selection_highlight_state",
    "unique_nonnegative_indices",
    "update_mesh_replacement_selection_view_model",
]
