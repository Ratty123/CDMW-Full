"""Runtime invariants for real Builder construction, both entry modes.

These replace source-text ordering guards. A widget shown before it is parented
becomes a transient top-level window and then gets reparented, so the finished
widget tree looks correct either way -- the defect is only visible while
construction is running, which is what the driver's Show filter watches.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTabWidget, QWidget

from tests.mesh_builder_driver import open_mesh_builder


_MODES = pytest.mark.parametrize(
    ("modify_original_clone_mode", "mode_name"),
    ((False, "Import Mesh"), (True, "Modify Original")),
)


@_MODES
def test_builder_constructs_and_tears_down_cleanly(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=mode_name,
    ) as builder:
        assert builder.context, "construction context was not published"
        # The viewport display control is the load-bearing one the startup smoke
        # gate also requires, so a silent section drop fails here too.
        assert builder.combo("MeshAlignmentViewportDisplayModeCombo") is not None
        assert builder.events_named("mesh_alignment_construction_failed") == ()
    # open_mesh_builder asserts clean dialog removal, no leftover active timers,
    # and no renderer start on exit.


@_MODES
def test_no_section_becomes_visible_before_it_is_parented(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=mode_name,
    ) as builder:
        leaks = builder.parentless_show.leaks()

    assert not leaks, (
        f"{mode_name} showed widgets before parenting them, so each briefly "
        f"became a top-level window: {leaks}"
    )


def test_dialog_is_maximizable_and_minimizable() -> None:
    """A builder the user cannot maximise is unusable on a dense model."""
    with open_mesh_builder(dialog_title="Window flags") as builder:
        flags = builder.dialog.windowFlags()

        assert flags & Qt.WindowMaximizeButtonHint
        assert flags & Qt.WindowMinimizeButtonHint


def test_workflow_tabs_stay_readable_rather_than_eliding() -> None:
    """Tab labels must scroll, not truncate; a clipped label reads as a typo."""
    with open_mesh_builder(dialog_title="Workflow tabs") as builder:
        assert builder.find(QWidget, "MeshAlignmentStickyControlPanel") is not None
        tabs = builder.find(QTabWidget, "MeshAlignmentStickyWorkflowTabs")

        assert tabs.usesScrollButtons()
        assert tabs.elideMode() == Qt.TextElideMode.ElideNone
        # Expanding tabs would stretch labels to fill and reintroduce elision.
        assert not tabs.tabBar().expanding()

        assert tabs.count() == 5
        untooltipped = [
            tabs.tabText(index)
            for index in range(tabs.count())
            if tabs.tabToolTip(index) != tabs.tabText(index)
        ]
        assert not untooltipped, (
            f"workflow tabs whose tooltip does not repeat the label: {untooltipped}; "
            "a scrolled-out tab is then unidentifiable on hover"
        )
