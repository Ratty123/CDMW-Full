"""Runtime invariants for real Builder construction, both entry modes.

These replace source-text ordering guards. A widget shown before it is parented
becomes a transient top-level window and then gets reparented, so the finished
widget tree looks correct either way -- the defect is only visible while
construction is running, which is what the driver's Show filter watches.
"""

from __future__ import annotations

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDoubleSpinBox, QPushButton, QTabWidget, QWidget

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


@_MODES
def test_builder_chrome_does_not_reserve_preview_height(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=f"{mode_name} compact chrome",
        placement_context_note="Review placement before export.",
    ) as builder:
        controls_panel = builder.find(QWidget, "MeshAlignmentStickyControlPanel")
        selection_label = builder.find(QWidget, "SelectionContextLabel")
        resident_status_sink = builder.find(QWidget, "MeshAlignmentResidentStatusSink")
        preview_status_sink = builder.find(QWidget, "MeshAlignmentPreviewStatusSink")

        assert builder.dialog.findChild(QWidget, "SelectionContextFrame") is None
        assert selection_label.isHidden()
        assert builder.context["placement_note"] is None
        assert resident_status_sink.isHidden()
        assert preview_status_sink.isHidden()
        assert not builder.control("alignment_d3d11_preview_status_label").isVisibleTo(
            builder.dialog
        )
        assert not builder.control("preview_performance_label").isVisibleTo(builder.dialog)

        build_button = getattr(builder.dialog, "_material_authority_build_button")
        cancel_button = next(
            button
            for button in builder.dialog.findChildren(QPushButton)
            if button.text() == "Cancel"
        )
        for button in (build_button, cancel_button):
            parent = button.parentWidget()
            while parent is not None and parent is not controls_panel:
                parent = parent.parentWidget()
            assert parent is controls_panel


@_MODES
def test_export_transform_axes_keep_distinct_numeric_fields(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=f"{mode_name} transform density",
    ) as builder:
        row_keys = (
            ("offset_x_spin", "offset_y_spin", "offset_z_spin"),
            ("rotate_x_spin", "rotate_y_spin", "rotate_z_spin"),
            ("scale_x_spin", "scale_y_spin", "scale_z_spin"),
        )
        for row in row_keys:
            spins = tuple(builder.control(key) for key in row)
            assert all(isinstance(spin, QDoubleSpinBox) for spin in spins)
            assert tuple(spin.prefix() for spin in spins) == ("X ", "Y ", "Z ")
            assert all(spin.minimumWidth() == 72 for spin in spins)

        sliders = tuple(builder.control("alignment_transform_sliders").values())
        assert len(sliders) == 9
        assert all(slider.minimumWidth() == 72 for slider in sliders)
