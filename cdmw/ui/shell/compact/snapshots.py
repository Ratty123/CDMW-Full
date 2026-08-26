"""Side-effect-free status facts for the Compact Workspace bottom strip."""

from __future__ import annotations

from collections.abc import Mapping, Sized
from typing import Callable

from PySide6.QtWidgets import QWidget

from cdmw.ui.shell.compact.activity import CompactStatusSnapshot
from cdmw.ui.shell.compact.registry import COMPACT_TOOL_SPECS, compact_tool_label
from cdmw.ui.shell.lazy_tool_tab import created_tool_widget


_TOOL_CONTAINER_ATTRIBUTES = {
    "archive_browser": "archive_browser_tab",
    "model_library": "model_library_tab",
    "item_icons": "item_icons_tab",
    "new_item_studio": "new_item_studio_tab",
    "mesh_editor": "mesh_editor_tab",
    "placement_studio": "placement_studio_tab",
    "texture_workflow": "workflow_tab",
    "replace_assistant": "replace_assistant_tab",
    "recolor_variants": "recolor_variants_tab",
    "texture_editor": "texture_editor_tab",
    "mod_package_retrofit": "mod_package_retrofit_tab",
    "format_explorer": "format_explorer_tab",
    "translation_studio": "translation_studio_tab",
    "research": "research_tab",
    "text_search": "text_search_tab",
}


def _attribute(target: object | None, name: str) -> object | None:
    if target is None:
        return None
    try:
        return getattr(target, name)
    except (AttributeError, RuntimeError, TypeError):
        return None


def _first_attribute(sources: tuple[object, ...], *names: str) -> object | None:
    for source in sources:
        for name in names:
            value = _attribute(source, name)
            if value is not None:
                return value
    return None


def _existing_tool_widget(owner: object, tool_key: str) -> QWidget | None:
    """Return an already-created tool only; never ask a lazy tab to construct it."""

    containers = _attribute(owner, "_tool_widgets_by_key")
    if isinstance(containers, Mapping):
        widget = created_tool_widget(containers.get(tool_key))
        if widget is not None:
            return widget
    attribute_name = _TOOL_CONTAINER_ATTRIBUTES.get(tool_key, "")
    return created_tool_widget(_attribute(owner, attribute_name)) if attribute_name else None


def _sources_for(owner: object, tool_key: str) -> tuple[object, ...]:
    widget = _existing_tool_widget(owner, tool_key)
    if tool_key in {"archive_browser", "texture_workflow"}:
        return (owner,) if widget is None or widget is owner else (owner, widget)
    return (widget,) if widget is not None else ()


def _display_text(value: object | None) -> str:
    if value is None:
        return ""
    for method_name in ("text", "currentText"):
        method = _attribute(value, method_name)
        if callable(method):
            try:
                return str(method() or "").strip()
            except (RuntimeError, TypeError):
                return ""
    return str(value).strip() if isinstance(value, str) else ""


def _numeric_value(value: object | None) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return max(0, value)
    text = _display_text(value).replace(",", "")
    if text.isdigit():
        return int(text)
    return None


def _collection_count(sources: tuple[object, ...], *names: str) -> int | None:
    value = _first_attribute(sources, *names)
    if value is None or isinstance(value, (str, bytes, bytearray)):
        return None
    if isinstance(value, Sized):
        try:
            return max(0, len(value))
        except (RuntimeError, TypeError):
            return None
    return None


def _call_int(target: object | None, method_name: str) -> int | None:
    method = _attribute(target, method_name)
    if not callable(method):
        return None
    try:
        return int(method())
    except (RuntimeError, TypeError, ValueError):
        return None


def _view_row_count(view: object | None) -> int | None:
    for method_name in ("topLevelItemCount", "rowCount", "count"):
        count = _call_int(view, method_name)
        if count is not None:
            return max(0, count)
    model_getter = _attribute(view, "model")
    if callable(model_getter):
        try:
            count = _call_int(model_getter(), "rowCount")
            return max(0, count) if count is not None else None
        except (RuntimeError, TypeError):
            return None
    return None


def _selected_row_count(view: object | None) -> int:
    selection_model_getter = _attribute(view, "selectionModel")
    if callable(selection_model_getter):
        try:
            selection_model = selection_model_getter()
            selected_rows = _attribute(selection_model, "selectedRows")
            if callable(selected_rows):
                return len(selected_rows())
        except (RuntimeError, TypeError):
            pass
    selected_items = _attribute(view, "selectedItems")
    if callable(selected_items):
        try:
            return len(selected_items())
        except (RuntimeError, TypeError):
            pass
    return 0


def _mode_text(value: object | None, *, suffix: str = "") -> str:
    text = str(value or "").strip().replace("_", " ")
    if not text:
        return ""
    return f"{text.title()} {suffix}".strip()


def _image_dimensions(value: object | None) -> tuple[int, int] | None:
    if value is None:
        return None
    width = _attribute(value, "width")
    height = _attribute(value, "height")
    try:
        resolved_width = int(width() if callable(width) else width)
        resolved_height = int(height() if callable(height) else height)
    except (RuntimeError, TypeError, ValueError):
        return None
    if resolved_width <= 0 or resolved_height <= 0:
        return None
    return resolved_width, resolved_height


def _snapshot(tool_key: str, *facts: str) -> CompactStatusSnapshot:
    useful: list[str] = []
    for fact in facts:
        text = str(fact or "").strip()
        if text and text not in useful:
            useful.append(text)
        if len(useful) == 3:
            break
    return CompactStatusSnapshot(
        tool_key=tool_key,
        facts=tuple(useful),
        label=compact_tool_label(tool_key, tool_key),
    )


def _archive_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    tree = _first_attribute(sources, "archive_tree")
    selected = _selected_row_count(tree)
    shown = _collection_count(sources, "archive_filtered_entries")
    total = _collection_count(sources, "archive_entries")
    count_fact = ""
    if shown is not None:
        count_fact = f"{shown:,}/{total:,} files" if total is not None and total != shown else f"{shown:,} files"
    elif total is not None:
        count_fact = f"{total:,} files"
    return _snapshot(key, f"{selected:,} selected" if selected else "", count_fact)


def _model_library_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    tree = _first_attribute(sources, "results_tree")
    rows = _view_row_count(tree)
    active_view = str(_first_attribute(sources, "_active_results_view") or "")
    if rows is None:
        rows = _collection_count(sources, "local_models" if active_view == "local" else "mirror_results")
    selected = _selected_row_count(tree)
    return _snapshot(
        key,
        f"{rows:,} results" if rows is not None else "",
        f"{selected:,} selected" if selected else "",
        "Local library" if active_view == "local" else "Mirror catalogue" if active_view else "",
    )


def _item_icons_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    tree = _first_attribute(sources, "records_tree")
    shown = _view_row_count(tree)
    total = _collection_count(sources, "records")
    selected = _selected_row_count(tree)
    count_fact = ""
    if shown is not None and total is not None and shown != total:
        count_fact = f"{shown:,}/{total:,} icons"
    elif total is not None:
        count_fact = f"{total:,} icons"
    elif shown is not None:
        count_fact = f"{shown:,} icons"
    return _snapshot(key, count_fact, f"{selected:,} selected" if selected else "")


def _new_item_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    current_step = _numeric_value(_first_attribute(sources, "_current_step"))
    page_count = _view_row_count(_first_attribute(sources, "pages"))
    controller = _first_attribute(sources, "controller")
    busy = bool(_attribute(controller, "busy"))
    pending = sum(
        value is not None
        for value in (
            _first_attribute(sources, "_pending_template"),
            _first_attribute(sources, "_pending_model_import"),
        )
    )
    return _snapshot(
        key,
        f"Step {current_step + 1}/{page_count}" if current_step is not None and page_count else "",
        "Working" if busy else "",
        f"{pending} pending" if pending else "",
    )


def _mesh_editor_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    edit_mode = _first_attribute(sources, "current_edit_mode")
    selection_mode = _first_attribute(sources, "current_selection_mode")
    selection_empty = _first_attribute(sources, "current_selection_empty")
    return _snapshot(
        key,
        _mode_text(edit_mode, suffix="mode"),
        _mode_text(selection_mode, suffix="selection"),
        "Selection active" if selection_empty is False else "",
    )


def _placement_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    tab = sources[0] if sources else None
    studio = _attribute(tab, "_studio")
    if studio is None:
        return _snapshot(key, "Preparing baseline" if _attribute(tab, "_thread") is not None else "")
    lower_tabs = _attribute(studio, "_lower")
    current_text = _attribute(lower_tabs, "tabText")
    current_index = _call_int(lower_tabs, "currentIndex")
    mode = ""
    if callable(current_text) and current_index is not None and current_index >= 0:
        try:
            mode = str(current_text(current_index) or "").strip()
        except (RuntimeError, TypeError):
            mode = ""
    tree = _attribute(studio, "_tree")
    clips = _view_row_count(_attribute(studio, "_clip_list"))
    selected = _selected_row_count(tree)
    return _snapshot(
        key,
        mode,
        f"{selected:,} selected" if selected else "",
        f"{clips:,} clips" if clips is not None else "",
    )


def _texture_workflow_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    processed = _numeric_value(_first_attribute(sources, "converted_value"))
    failed = _numeric_value(_first_attribute(sources, "failed_value"))
    skipped = _numeric_value(_first_attribute(sources, "skipped_value")) or 0
    total = _numeric_value(_first_attribute(sources, "total_files_value", "_texture_workflow_total_files"))
    pending = None
    if total is not None and processed is not None:
        pending = max(0, total - processed - skipped - (failed or 0))
    phase = _display_text(_first_attribute(sources, "phase_value"))
    if processed is None and failed is None and pending is None:
        return _snapshot(key, phase if phase not in {"Idle", "Waiting"} else "")
    return _snapshot(
        key,
        f"{processed:,} processed" if processed is not None else "",
        f"{failed:,} failed" if failed else "",
        f"{pending:,} pending" if pending is not None else "",
    )


def _replace_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    queue = _first_attribute(sources, "queue_tree")
    queued = _view_row_count(queue)
    selected = _selected_row_count(queue)
    review = _collection_count(sources, "pending_review_items")
    return _snapshot(
        key,
        f"{queued:,} queued" if queued is not None else "",
        f"{selected:,} selected" if selected else "",
        f"{review:,} need review" if review else "",
    )


def _recolor_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    targets = _first_attribute(sources, "targets_tree")
    selected = _selected_row_count(targets)
    outputs = _view_row_count(_first_attribute(sources, "outputs_tree"))
    dimensions = None
    preview_label = _first_attribute(sources, "preview_result_image_label")
    pixmap_getter = _attribute(preview_label, "pixmap")
    if callable(pixmap_getter):
        try:
            dimensions = _image_dimensions(pixmap_getter())
        except RuntimeError:
            dimensions = None
    return _snapshot(
        key,
        f"{selected:,} selected" if selected else "",
        f"{outputs:,} outputs" if outputs is not None else "",
        f"{dimensions[0]} x {dimensions[1]}" if dimensions else "",
    )


def _texture_editor_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    document = _first_attribute(sources, "document")
    dimensions = _image_dimensions(document)
    layers = _collection_count((document,), "layers") if document is not None else None
    mode = _display_text(_first_attribute(sources, "view_mode_combo"))
    return _snapshot(
        key,
        mode,
        f"{dimensions[0]} x {dimensions[1]}" if dimensions else "",
        f"{layers:,} layers" if layers is not None else "",
    )


def _table_snapshot(owner: object, key: str, noun: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    table = _first_attribute(sources, "table")
    rows = _view_row_count(table)
    selected = _selected_row_count(table)
    return _snapshot(
        key,
        f"{rows:,} {noun}" if rows is not None else "",
        f"{selected:,} selected" if selected else "",
    )


def _translation_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    table = _first_attribute(sources, "table")
    rows = _view_row_count(table)
    catalogue = _first_attribute(sources, "_catalogue")
    pending = _numeric_value(_attribute(catalogue, "edit_count"))
    language = _display_text(_first_attribute(sources, "language_box"))
    return _snapshot(
        key,
        f"{rows:,} lines" if rows is not None else "",
        f"{pending:,} pending changes" if pending else "",
        language,
    )


def _research_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    tabs = _first_attribute(sources, "tab_widget")
    current_index = _call_int(tabs, "currentIndex")
    tab_text = _attribute(tabs, "tabText")
    mode = ""
    if callable(tab_text) and current_index is not None and current_index >= 0:
        try:
            mode = str(tab_text(current_index) or "").strip()
        except (RuntimeError, TypeError):
            mode = ""
    tree = _first_attribute(sources, "archive_picker_tree")
    results = _view_row_count(tree)
    processed = _numeric_value(_first_attribute(sources, "_refresh_population_processed"))
    return _snapshot(
        key,
        mode,
        f"{results:,} results" if results is not None else "",
        f"{processed:,} processed" if processed else "",
    )


def _text_search_snapshot(owner: object, key: str) -> CompactStatusSnapshot:
    sources = _sources_for(owner, key)
    results = _collection_count(sources, "search_results")
    tree = _first_attribute(sources, "results_tree")
    if results is None:
        results = _view_row_count(tree)
    pending = _collection_count(sources, "_pending_result_indexes")
    selected = _selected_row_count(tree)
    return _snapshot(
        key,
        f"{results:,} results" if results is not None else "",
        f"{selected:,} selected" if selected else "",
        f"{pending:,} pending" if pending else "",
    )


_SNAPSHOT_PROVIDERS: dict[str, Callable[[object, str], CompactStatusSnapshot]] = {
    "archive_browser": _archive_snapshot,
    "model_library": _model_library_snapshot,
    "item_icons": _item_icons_snapshot,
    "new_item_studio": _new_item_snapshot,
    "mesh_editor": _mesh_editor_snapshot,
    "placement_studio": _placement_snapshot,
    "texture_workflow": _texture_workflow_snapshot,
    "replace_assistant": _replace_snapshot,
    "recolor_variants": _recolor_snapshot,
    "texture_editor": _texture_editor_snapshot,
    "mod_package_retrofit": lambda owner, key: _table_snapshot(owner, key, "packages"),
    "format_explorer": lambda owner, key: _table_snapshot(owner, key, "formats"),
    "translation_studio": _translation_snapshot,
    "research": _research_snapshot,
    "text_search": _text_search_snapshot,
}

if set(_SNAPSHOT_PROVIDERS) != {spec.key for spec in COMPACT_TOOL_SPECS}:
    raise RuntimeError("Compact status providers must cover the stable tool registry.")


def compact_status_snapshot_for(owner: object, tool_key: str) -> CompactStatusSnapshot:
    """Read concise facts from existing state without constructing or starting anything."""

    key = str(tool_key or "")
    provider = _SNAPSHOT_PROVIDERS.get(key)
    return provider(owner, key) if provider is not None else _snapshot(key)


__all__ = ["compact_status_snapshot_for"]
