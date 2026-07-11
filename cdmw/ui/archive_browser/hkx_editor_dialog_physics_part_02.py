from __future__ import annotations

from types import SimpleNamespace

def _dialog_step_0109(_state):
    def _set_connected_target_filter(viewer_id: str, label: str = "") -> bool:
        target_text = str(viewer_id or label or "").strip()
        if not target_text:
            return False
        _state.connected_target_filter_edit.setText(target_text)
        visible_rows = _state._apply_connected_physics_filter()
        selected = _state._select_best_connected_row_for_target(target_text)
        if not selected and visible_rows <= 0 and _state.connected_workflow_combo.currentIndex() > 0:
            _state.connected_workflow_combo.setCurrentIndex(0)
            visible_rows = _state._apply_connected_physics_filter()
            selected = _state._select_best_connected_row_for_target(target_text)
        return bool(selected or visible_rows > 0)
    _state._set_connected_target_filter = _set_connected_target_filter

STEPS = (_dialog_step_0109,)
