"""The ground grid is a control, not something that comes and goes on its own.

`grid_visible` used to be hardcoded true on the Python side while the resident
renderer kept one presentation context per pane and only wrote the active one
back, so a pane could end up drawing a grid state nobody asked for. These build
the real Builder dialog offscreen and read what actually reaches the resident
presentation payload.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QCheckBox

from tests.mesh_builder_driver import open_mesh_builder


@pytest.fixture
def builder():
    with open_mesh_builder(dialog_title="Grid toggle") as driver:
        yield driver


def _presentation_display(driver) -> dict:
    getter = driver.dialog._mesh_editor_embedded_presentation_state
    return dict(dict(getter()).get("display", {}))


def test_the_grid_checkbox_is_present_and_on_by_default(builder) -> None:
    grid = builder.checkbox("MeshAlignmentGridVisibleCheckbox")
    assert grid.isVisible() or grid.isVisibleTo(builder.dialog)
    assert grid.isChecked()
    assert grid.isEnabled()


def test_original_locked_is_no_longer_shown(builder) -> None:
    # It was permanently checked and permanently disabled: a control that could
    # only ever report the one state the preview already guarantees.
    locked = [
        box
        for box in builder.dialog.findChildren(QCheckBox)
        if box.text() == "Original locked"
    ]
    assert locked, "the widget is still expected to exist for the callbacks that read it"
    assert not any(box.isVisibleTo(builder.dialog) for box in locked)


def test_the_grid_checkbox_drives_the_resident_presentation_state(builder) -> None:
    grid = builder.checkbox("MeshAlignmentGridVisibleCheckbox")

    assert _presentation_display(builder)["grid_visible"] is True

    builder.set_checked(grid, False)
    assert _presentation_display(builder)["grid_visible"] is False

    builder.set_checked(grid, True)
    assert _presentation_display(builder)["grid_visible"] is True


def test_the_grid_choice_survives_into_the_highlight_update(builder) -> None:
    sent: list[dict] = []
    builder.dialog._mesh_editor_embedded_dotnet_active = True
    builder.dialog._mesh_editor_embedded_set_presentation_state = (
        lambda payload: (sent.append(dict(payload)), True)[1]
    )
    grid = builder.checkbox("MeshAlignmentGridVisibleCheckbox")

    builder.set_checked(grid, False)

    # The lighter highlight update carries the overlay flags too, so it must not
    # quietly re-enable the grid the user just turned off.
    grid_flags = [
        dict(payload.get("display", {})).get("grid_visible")
        for payload in sent
        if "display" in payload
    ]
    assert grid_flags, f"no presentation update carried a display block: {sent}"
    assert grid_flags[-1] is False
