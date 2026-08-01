"""A failed mode read must not publish a mode change.

Both scene modes are read out of live builder widgets at publish time. The read
used to answer a failure with the literal ``placement``, which is published as an
authoritative scene frame: on the helper's side a frame naming ``placement``
while the reader is inside Edit Mesh is a real transition, so it runs the full
interaction-mode pass, returns the shared sections to the placement flanks,
un-collapses both splitters and reveals the placement panels. The next correct
frame puts the rail back. That is the placement side panel appearing behind the
tool dock, manufactured out of a transient read failure rather than anything the
reader did.

``ReassertInteractionModeControls`` cannot defend against this: the guard it
grew in 53e51498 skips a *redundant* frame, and a wrong-mode frame is not
redundant, it is a genuine transition.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.mesh_editor.tab import MeshEditorTab
from tests.test_mesh_editor_action_bar import _EmbeddedMeshBuilder

_APP = QApplication.instance() or QApplication([])


def _embedded_tab(name: str) -> tuple[MeshEditorTab, _EmbeddedMeshBuilder]:
    settings = QSettings("CDMWTests", name)
    settings.clear()
    tab = MeshEditorTab(settings=settings)
    builder = _EmbeddedMeshBuilder()
    tab.mount_embedded_builder(builder)
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    return tab, builder


def _raise(*_args: object, **_kwargs: object) -> str:
    raise RuntimeError("the builder widget was not readable")


def test_a_failed_interaction_read_keeps_the_reader_in_mesh_edit() -> None:
    tab, builder = _embedded_tab("MeshSceneModeInteractionFailure")
    try:
        tab.standalone_dotnet_scene_desired["interaction_mode"] = "mesh_edit"
        builder._mesh_editor_embedded_interaction_mode = _raise  # type: ignore[attr-defined]

        _comparison, interaction = tab._dotnet_initial_scene_modes(embedded=True)

        assert interaction == "mesh_edit", (
            "a transient widget read failure published a placement frame; the "
            "helper takes that as a real transition and reveals the placement "
            f"panels behind the tool dock (got {interaction!r})"
        )
    finally:
        tab.deleteLater()


def test_a_failed_comparison_read_keeps_the_last_comparison_mode() -> None:
    tab, builder = _embedded_tab("MeshSceneModeComparisonFailure")
    try:
        tab.standalone_dotnet_scene_desired["comparison_mode"] = "side_by_side"
        builder._mesh_editor_embedded_comparison_mode = _raise  # type: ignore[attr-defined]

        comparison, _interaction = tab._dotnet_initial_scene_modes(embedded=True)

        assert comparison == "side_by_side", (
            f"a failed comparison read changed the comparison mode (got {comparison!r})"
        )
    finally:
        tab.deleteLater()


def test_a_failed_read_is_recorded_rather_than_swallowed() -> None:
    """The retained mode hides the failure from the reader, not from the log."""

    tab, builder = _embedded_tab("MeshSceneModeFailureRecorded")
    try:
        recorded: list[tuple[str, dict]] = []
        tab._record_mesh_dotnet_event = (  # type: ignore[method-assign]
            lambda event, **payload: recorded.append((str(event), dict(payload)))
        )
        tab.standalone_dotnet_scene_desired["interaction_mode"] = "mesh_edit"
        builder._mesh_editor_embedded_interaction_mode = _raise  # type: ignore[attr-defined]

        tab._dotnet_initial_scene_modes(embedded=True)

        events = [name for name, _payload in recorded]
        assert "mesh_dotnet_interaction_mode_read_failed" in events, (
            f"a failed mode read left no trace ({events})"
        )
    finally:
        tab.deleteLater()


def test_a_working_read_still_wins_over_the_retained_mode() -> None:
    """Retaining is the failure path only; a readable widget is authoritative."""

    tab, builder = _embedded_tab("MeshSceneModeReadWins")
    try:
        tab.standalone_dotnet_scene_desired["interaction_mode"] = "mesh_edit"
        builder._mesh_editor_embedded_interaction_mode = lambda: "placement"  # type: ignore[attr-defined]

        _comparison, interaction = tab._dotnet_initial_scene_modes(embedded=True)

        assert interaction == "placement", (
            "leaving Edit Mesh never reached the helper; the retained mode must "
            f"only cover a failed read (got {interaction!r})"
        )
    finally:
        tab.deleteLater()
