from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mesh_edit_payload import (
    mesh_edit_payload_choice,
    mesh_edit_stroke_id,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_stroke_finish import (
    create_stroke_finish_callbacks,
)


def test_remove_stroke_finish_uses_payload_delete_mode() -> None:
    events: list[str] = []
    state = SimpleNamespace(
        Mapping=Mapping,
        _mesh_edit_current_tool=lambda: "remove",
        _mesh_edit_payload_choice_helper=mesh_edit_payload_choice,
        _mesh_edit_state=SimpleNamespace(replacement_mesh_for_mapping=object()),
        _mesh_edit_stroke_id=mesh_edit_stroke_id,
        _pop_geometry_undo_snapshot=lambda: events.append("geometry_undo"),
        mesh_edit_active_stroke={"id": 7, "tool": "remove", "delete_mode": "release"},
        mesh_edit_delete_mode_combo=SimpleNamespace(currentData=lambda: "release"),
    )
    callbacks = SimpleNamespace(
        _mesh_edit_clear_active_stroke=lambda: events.append("clear"),
        _mesh_edit_pop_undo_snapshot=lambda: events.append("mesh_undo"),
        _refresh_mesh_edit_controls=lambda: events.append("refresh"),
    )

    finish_stroke = create_stroke_finish_callbacks(state, callbacks)._mesh_edit_finish_stroke
    finish_stroke({"stroke_id": 7, "tool": "remove", "delete_mode": "selection"})

    assert events == ["mesh_undo", "geometry_undo", "clear", "refresh"]
