"""A freshly opened Mesh Editor must be camera-only.

Selecting geometry in the viewport is Edit Mesh's job, and picking whole parts
belongs to Parts & Routing. On open, neither is allowed: a left drag orbits.

The regression was invisible in the UI. The Part Pick toolbar checkbox was
removed but its widget was left `setChecked(True)` and merely hidden, so every
presentation snapshot still reported `part_pick_enabled: True`. MeshViewport then
routes a plain left click into `BeginSelectionDrag(..., "source")` whenever that
flag arrives true outside `mesh_edit` mode, which made whole-part selection live
the moment the Builder opened.

These construct the real Builder offscreen rather than reading source text,
because the defect was in a runtime widget state, not in the wiring around it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from cdmw.ui.archive_browser.static_replacement_dotnet_presentation import (
    builder_part_highlight_state,
)
from tests.mesh_builder_driver import open_mesh_builder


REPO_ROOT = Path(__file__).resolve().parents[1]
MESH_VIEWPORT_INPUT = (
    REPO_ROOT / "tools" / "dotnet_mesh_editor_experiment" / "MeshViewport.Input.cs"
)


@pytest.fixture
def builder():
    with open_mesh_builder(dialog_title="Camera-only on open") as driver:
        yield driver


def test_part_pick_gizmo_and_edit_mesh_are_all_off_when_the_builder_opens(builder) -> None:
    part_pick = builder.checkbox("MeshAlignmentPartPickCheckbox")
    gizmo = builder.checkbox("MeshAlignmentGizmoVisibleCheckbox")
    mesh_edit = builder.checkbox("MeshEditModeCheckbox")

    assert part_pick.isChecked() is False, (
        "viewport part picking is live on open, so a left click selects a part "
        "instead of orbiting"
    )
    assert part_pick.isVisible() is False
    assert gizmo.isChecked() is False, (
        "the placement gizmo is live on open, so a left click on a handle starts "
        "a placement drag instead of orbiting"
    )
    assert mesh_edit.isChecked() is False


def test_presentation_snapshot_on_open_reports_no_viewport_picking(builder) -> None:
    captured: list[dict[str, object]] = []
    builder.dialog._mesh_editor_embedded_dotnet_active = True
    builder.dialog._mesh_editor_embedded_set_presentation_state = (
        lambda payload: (captured.append(dict(payload)), True)[1]
    )

    sync = builder.control("_sync_highlight_sets")
    assert callable(sync)
    sync()
    builder.pump()

    assert captured, "the Builder sent no presentation snapshot to the resident viewport"
    display = captured[-1].get("display")
    assert isinstance(display, dict)
    assert display.get("part_pick_enabled") is False
    # PlacementGizmoEnabled gates TryBeginPlacementGizmoDrag, so this is what
    # keeps a handle from swallowing the first left click.
    assert display.get("gizmo_visible") is False


def test_enabling_part_pick_is_what_turns_viewport_picking_back_on(builder) -> None:
    """The flag still works, so the fix is the default and not a removal."""
    captured: list[dict[str, object]] = []
    builder.dialog._mesh_editor_embedded_dotnet_active = True
    builder.dialog._mesh_editor_embedded_set_presentation_state = (
        lambda payload: (captured.append(dict(payload)), True)[1]
    )

    builder.set_checked(builder.checkbox("MeshAlignmentPartPickCheckbox"), True)
    builder.control("_sync_highlight_sets")()
    builder.pump()

    assert captured
    assert captured[-1]["display"]["part_pick_enabled"] is True


def test_turning_the_gizmo_on_persists_and_a_later_builder_opens_with_it(builder) -> None:
    """Off is the default for an unset preference, not a state forced on open."""
    gizmo = builder.checkbox("MeshAlignmentGizmoVisibleCheckbox")
    assert gizmo.isChecked() is False

    builder.set_checked(gizmo, True)

    assert (
        builder.settings.value("ui/mesh_alignment/gizmo_visible") in (True, "true", "True")
    ), "the gizmo choice never reached settings, so it dies with the session"

    # A second Builder over the same settings must honour the stored choice.
    with open_mesh_builder(
        dialog_title="Camera-only reopen",
        settings=builder.settings,
    ) as reopened:
        assert reopened.checkbox("MeshAlignmentGizmoVisibleCheckbox").isChecked() is True


def test_highlight_state_carries_the_flag_the_viewport_gate_reads() -> None:
    payload = builder_part_highlight_state(
        selection_active=False,
        grid_visible=True,
        gizmo_visible=True,
        part_pick_enabled=False,
        mesh_edit_active=False,
    )

    assert payload["display"]["part_pick_enabled"] is False


def test_viewport_only_begins_a_source_drag_behind_the_part_pick_gate() -> None:
    """Pin the consumer, so the flag cannot be re-read somewhere ungated.

    MeshViewport is C#; the Python gate above is only meaningful while this is
    the sole path from a non-edit left click into whole-part selection.
    """
    source = MESH_VIEWPORT_INPUT.read_text(encoding="utf-8")
    gate = source.index("if (PartPickEnabled)")
    drag = source.index('BeginSelectionDrag(e.Location, "source")', gate)
    between = source[gate:drag]

    assert "\n        }" not in between, (
        'BeginSelectionDrag(..., "source") is no longer directly inside the '
        "PartPickEnabled gate"
    )
    assert source.count('BeginSelectionDrag(e.Location, "source")') == 1
