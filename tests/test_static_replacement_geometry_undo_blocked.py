"""Undo must not consume its snapshot when the restore was refused.

`_restore_geometry_history_state` returns without touching the mesh while an active
Mesh Editor session owns geometry history. Undo popped its snapshot, called it,
released the snapshot in a `finally` regardless, and then wrote "Undid ..." over the
error the blocked branch had just reported -- so the one recoverable state was
destroyed by an operation that changed nothing and claimed it had worked.
"""

from __future__ import annotations

import os
import unittest
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.ui.archive_browser.static_replacement_dialog_callbacks_remaining_geometry_history_part_01 import (
    _remaining_geometry_history_step_028,
)


def _state_with(*, restore_succeeds: bool) -> SimpleNamespace:
    released: list[object] = []
    statuses: list[str] = []
    refreshes: list[bool] = []
    state = SimpleNamespace(
        geometry_undo_stack=[{"reason": "Smooth"}],
        released=released,
        statuses=statuses,
        refreshes=refreshes,
        _restore_geometry_history_state=lambda _snapshot: restore_succeeds,
        _release_geometry_history_snapshot=released.append,
        _refresh_geometry_history_buttons=lambda: refreshes.append(True),
        _geometry_undo_status_text_helper=lambda reason: f"Undid {reason}.",
        self=SimpleNamespace(set_status_message=lambda message, **_kw: statuses.append(message)),
    )
    _remaining_geometry_history_step_028(state)
    return state


class GeometryUndoBlockedTests(unittest.TestCase):
    def test_a_refused_restore_keeps_the_snapshot_and_claims_nothing(self) -> None:
        state = _state_with(restore_succeeds=False)
        snapshot = state.geometry_undo_stack[0]

        state._undo_geometry_change()

        self.assertEqual([snapshot], state.geometry_undo_stack)
        self.assertEqual([], state.released)
        self.assertEqual([], state.statuses)
        self.assertEqual([True], state.refreshes)

    def test_a_successful_restore_still_consumes_and_reports(self) -> None:
        state = _state_with(restore_succeeds=True)
        snapshot = state.geometry_undo_stack[0]

        state._undo_geometry_change()

        self.assertEqual([], state.geometry_undo_stack)
        self.assertEqual([snapshot], state.released)
        self.assertEqual(["Undid Smooth."], state.statuses)

    def test_an_empty_stack_is_still_a_no_op(self) -> None:
        state = _state_with(restore_succeeds=True)
        state.geometry_undo_stack.clear()

        state._undo_geometry_change()

        self.assertEqual([], state.released)
        self.assertEqual([], state.statuses)


if __name__ == "__main__":
    unittest.main()
