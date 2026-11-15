"""Automation reads of the Scene panel and the Mesh Editor's parts (test runs only).

The built exe's pass compares the two lists (same parts, names and order) and checks
that nothing is selected or highlighted when a model or set is first shown.
"""

from __future__ import annotations

_HIGHLIGHTS: list[list[int]] = []
_WATCHED: set[int] = set()


def watch_scene_panel(window) -> None:
    """Record every highlight the Scene panel asks the view for, from now on."""

    panel = getattr(getattr(window, "archive", None), "archive_item_set_components", None)
    if panel is None or id(panel) in _WATCHED:
        return
    _WATCHED.add(id(panel))
    panel.highlightRequested.connect(lambda indices: _HIGHLIGHTS.append([int(i) for i in indices or ()]))


def scene_panel_rows(window, _args: dict) -> dict[str, object]:
    """The Scene panel's files and parts in their shown order, ticks, selection and the
    highlights it asked the view for since it was watched."""

    from PySide6.QtCore import Qt

    panel = getattr(window.archive, "archive_item_set_components", None)
    if panel is None:
        return {"available": False}
    tree = panel.tree
    files = []
    for top in range(tree.topLevelItemCount()):
        group = tree.topLevelItem(top)
        files.append({
            "label": group.text(0),
            "count": group.text(1),
            "path": group.toolTip(0),
            "parts": [{
                "label": group.child(row).text(0),
                "index": group.child(row).data(0, Qt.ItemDataRole.UserRole),
                "ticked": group.child(row).checkState(0) == Qt.CheckState.Checked,
            } for row in range(group.childCount())],
        })
    return {
        "available": True,
        "visible": bool(panel.isVisible()),
        "files": files,
        "selected": [item.text(0) for item in tree.selectedItems()],
        "highlights": list(_HIGHLIGHTS),
        "count_column_width": tree.columnWidth(1),
        "count_texts_fit": all(
            tree.fontMetrics().horizontalAdvance(item["count"]) <= tree.columnWidth(1) for item in files),
    }


def mesh_editor_parts(window, _args: dict) -> dict[str, object]:
    """The shown Mesh Editor document's parts as its Parts list names them, and its selection."""

    from cdmw.ui.shell.lazy_tool_tab import created_tool_widget

    view = created_tool_widget(window.shell.mesh_editor_tab)
    tab = getattr(view, "active", None) or view
    session = getattr(tab, "standalone_rust_authoring_session", None)
    if session is None:
        return {"available": False}
    service, session_id = session.shadow_service, session.shadow_session_id
    mesh = service.working_mesh(session_id)
    selection = service.session_view(session_id).selection
    return {
        "available": True,
        "parts": [{"index": index, "name": str(getattr(part, "name", "") or "")}
                  for index, part in enumerate(getattr(mesh, "submeshes", ()) or ())],
        "selected_parts": sorted(int(i) for i in getattr(selection, "source_indices", ()) or ()),
        "selected_faces": sum(len(v) for v in (selection.face_map() or {}).values()) if selection else 0,
    }
