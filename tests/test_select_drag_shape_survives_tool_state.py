"""One protocol field, one vocabulary: `selection_mode` is a Select drag shape.

Two hosts publish `tool_state`. The builder's Selection combo sends the drag
shape -- brush, lasso or rectangle -- and the Mesh Editor tab used to send its
element mode (vertex, face, edge, part) in the same field. The helper records
whatever it last heard so it can tell a real host change from the host simply
republishing its state, and recording an element mode there made the builder's
very next refresh look like a change back to brush: combo assignment included.

A reader who picked Lasso therefore had it taken away again on the next control
refresh, every time, which is why lasso appeared not to work at all.
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HELPER = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def _host_state_source() -> str:
    return (HELPER / "ExperimentForm.HostState.cs").read_text(encoding="utf-8")


def test_the_helper_discards_a_selection_mode_that_is_not_a_drag_shape() -> None:
    source = _host_state_source()
    adopt = source.split("var selectionDragMode =", maxsplit=1)[1].split(
        "// Re-asserting the tool", maxsplit=1
    )[0]
    # The three-shape gate has to stand in front of the record and the combo,
    # not only in front of the viewport: SetSelectionDragMode already ignored
    # an unknown value, and the defect was everything that ran beside it.
    assert 'is "brush" or "lasso" or "rectangle"' in adopt
    guard_at = adopt.index('is "brush" or "lasso" or "rectangle"')
    assert guard_at < adopt.index("_lastHostSelectionDragMode =")
    assert guard_at < adopt.index("_selectionShape.SelectedItem = shapeItem")


def test_the_mesh_editor_tab_publishes_only_its_normalized_drag_shape() -> None:
    source = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_shell.py").read_text(encoding="utf-8")
    call = source.split("def _sync_standalone_native_mesh_edit_state", maxsplit=1)[-1]
    call = call.split("def _standalone_preview_mesh_snapshot", maxsplit=1)[0]
    assert "target_mode=target," in call, "the element mode still has to reach the helper"
    publications = re.findall(r"^\s*selection_mode=(.+),$", call, re.MULTILINE)
    assert publications == ['"brush"', 'str(self.current_selection_mode or "brush")']

    runtime = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_shell_runtime.py").read_text(encoding="utf-8")
    state = (ROOT / "cdmw" / "ui" / "mesh_editor" / "tab_state.py").read_text(encoding="utf-8")
    assert 'self.current_selection_mode = "brush"' in runtime
    assert "self.current_selection_mode = normalize_mesh_selection_shape(active_selection_mode)" in state
