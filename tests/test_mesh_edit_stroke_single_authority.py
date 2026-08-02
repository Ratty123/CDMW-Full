"""Resident-editor strokes have exactly one native authority: the tab.

Both the tab's live-stroke dispatcher and the builder's stroke callbacks
received every helper `stroke_*` event in the embedded flow, and both applied
the native stroke. The second `begin` for the same stroke id was refused with
"mesh editor stroke is already active", raised unhandled out of the signal
slot, and abandoned the session -- recorded live on 2026-08-02 12:18, one
crash report per stroke. The builder's four stroke callbacks now stand down
for any payload carrying a `stroke_*` protocol event; legacy preview-panel
strokes carry no event and keep their path.
"""

from __future__ import annotations

from collections.abc import Mapping
from types import SimpleNamespace

from cdmw.ui.archive_browser.static_replacement_mesh_edit_payload_apply import (
    _mesh_edit_apply_preview_payload,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_stroke_finish import (
    _mesh_edit_finish_stroke,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_stroke_history import (
    _mesh_edit_begin_stroke,
)
from cdmw.ui.archive_browser.static_replacement_mesh_edit_topology import (
    _mesh_edit_cancel_stroke,
)


class _Recorder:
    """Raises on any attribute access past the gate: the gate must be first."""

    def __init__(self) -> None:
        object.__setattr__(self, "touched", [])

    def __getattr__(self, name: str):
        object.__getattribute__(self, "touched").append(name)
        raise AssertionError(f"handler reached past the resident-stroke gate: {name}")


def _state_with_gate_only() -> SimpleNamespace:
    # Only what the gate itself reads; anything else raises via _Recorder.
    state = _Recorder()
    object.__setattr__(state, "Mapping", Mapping)
    return state


def _helper_payload(event: str) -> dict[str, object]:
    return {
        "event": event,
        "stroke_id": "1",
        "tool": "grab",
        "screen_drag": {"start_x": 0, "start_y": 0, "end_x": 5, "end_y": 5},
    }


def test_all_four_builder_handlers_stand_down_for_helper_strokes() -> None:
    handlers = (
        (_mesh_edit_begin_stroke, "stroke_begin"),
        (_mesh_edit_apply_preview_payload, "stroke_update"),
        (_mesh_edit_finish_stroke, "stroke_end"),
        (_mesh_edit_cancel_stroke, "stroke_cancel"),
    )
    for handler, event in handlers:
        state = _state_with_gate_only()
        callbacks = _Recorder()
        # Returning without touching state or callbacks proves the handler
        # never reached its native-apply body.
        handler(state, callbacks, _helper_payload(event))
        assert not object.__getattribute__(callbacks, "touched")


def test_a_legacy_stroke_payload_still_enters_the_handler_body() -> None:
    # No "event" key: the legacy preview panels' shape. The handler must get
    # past the gate -- proven by it touching the state the body reads first.
    state = _state_with_gate_only()
    callbacks = _Recorder()
    try:
        _mesh_edit_begin_stroke(state, callbacks, {"stroke_id": "1"})
    except AssertionError as exc:
        assert "_mesh_edit_state" in str(exc)
    else:  # pragma: no cover - the recorder always raises past the gate
        raise AssertionError("expected the legacy payload to enter the handler body")
