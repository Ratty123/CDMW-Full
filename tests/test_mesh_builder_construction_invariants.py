"""Runtime invariants for real Builder construction, both entry modes.

These replace source-text ordering guards. A widget shown before it is parented
becomes a transient top-level window and then gets reparented, so the finished
widget tree looks correct either way -- the defect is only visible while
construction is running, which is what the driver's Show filter watches.
"""

from __future__ import annotations

import pytest

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
