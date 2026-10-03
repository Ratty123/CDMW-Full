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
from cdmw.ui.widgets import CollapsibleSection
from cdmw.ui.preview.profile import DotNetPreviewProfile


_MODES = pytest.mark.parametrize(
    ("modify_original_clone_mode", "mode_name"),
    ((False, "Import Mesh"), (True, "Modify Original")),
)


@_MODES
def test_builder_has_compact_sections_and_a_standalone_rust_preview(
    modify_original_clone_mode: bool, mode_name: str,
) -> None:
    with open_mesh_builder(modify_original_clone_mode=modify_original_clone_mode) as builder:
        layout = builder.control('setup_layout')
        sections = [layout.itemAt(i).widget() for i in range(layout.count())]
        sections = [widget for widget in sections if isinstance(widget, CollapsibleSection) and not widget.isHidden()]
        expected = ['Options', 'Transform and Parts', 'Item Icon']
        if not modify_original_clone_mode:
            expected.append('Source Mixing')
        assert [section.toggle_button.text() for section in sections] == expected
        assert all(not section.toggle_button.isChecked() for section in sections)
        assert builder.control('advanced_setup_section').isHidden()
        assert builder.control('mesh_edit_enabled_checkbox').isHidden()
        assert builder.control('alignment_d3d11_preview_host').profile is DotNetPreviewProfile.PREVIEW
        # Exercise the toggle and process Qt's queued layout updates before checking visibility.
        builder.click(sections[0].toggle_button)
        if not modify_original_clone_mode:
            assert builder.control('complete_external_swap_checkbox').isVisibleTo(builder.dialog)
            builder.click(sections[-1].toggle_button)
            assert builder.control('add_archive_source_button').isVisibleTo(builder.dialog)
        builder.click(sections[1].toggle_button)
        for name in ('offset_x_spin', 'rotate_y_spin', 'scale_z_spin', 'part_source_combo'):
            assert builder.control(name).isVisibleTo(builder.dialog), name


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


@_MODES
def test_output_impact_review_names_the_operation_the_build_will_run(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    """The review answers from the classified operation, not from the toggles.

    A source assertion cannot prove this: the review is refreshed through a
    callback resolved at runtime, and its label is a live widget. Constructing
    the Builder and reading the tooltip is the smallest real path.
    """
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=f"{mode_name} output review",
    ) as builder:
        builder.control("_refresh_output_impact_review")()
        tooltip = builder.control("output_impact_review_label").toolTip()

        expected = (
            "Operation: Modify Original Mesh"
            if modify_original_clone_mode
            else "Operation: Replace"
        )
        assert expected in tooltip
        for authority in ("Geometry:", "Material bindings:", "Textures:"):
            assert authority in tooltip
        assert "Target keeps:" in tooltip
        assert "Build replaces:" in tooltip
        # The review it already carried is prefixed, not displaced.
        assert "Removed targets:" in tooltip


def test_output_impact_review_reports_edited_geometry_once_the_mesh_is_edited() -> None:
    """Modify Original replaces nothing until it does.

    The session opens on the target's own geometry, so "replaces nothing" is
    correct at entry. After an edit the export serializes the working mesh, and
    a summary still reading "nothing" would be the silent policy change the
    operation specification exists to prevent.
    """
    with open_mesh_builder(
        modify_original_clone_mode=True, dialog_title="Modify Original edited"
    ) as builder:
        refresh = builder.control("_refresh_output_impact_review")
        label = builder.control("output_impact_review_label")

        refresh()
        assert "Geometry: original" in label.toolTip()
        assert "Build replaces: nothing" in label.toolTip()

        builder.control("mesh_edit_revision")["value"] = 1
        refresh()
        assert "Geometry: working_edited" in label.toolTip()
        assert "Build replaces: geometry" in label.toolTip()


@pytest.mark.parametrize(
    "preset",
    [
        {},
        {"full_import_model_replacement": True},
        {"materials_and_textures_only": True},
    ],
    ids=["plain", "full_import", "materials_only"],
)
def test_the_builder_opens_under_every_workflow_preset(preset: dict) -> None:
    """Construct the real Builder for each preset, not just check signatures.

    Two shipped crashes were a keyword one link accepted and the next refused,
    and a signature test only sees the link it names. This drives the tail the
    way the app does -- the prompt, the shell context, and the workflow mode --
    so a preset that cannot open the Builder says so here rather than in a
    crash log. `tests/test_mesh_import_setup_flag_chain.py` covers the head of
    the same chain, which cannot run headless because the prompt is modal.
    """
    with open_mesh_builder(dialog_title="Preset construction", **preset) as builder:
        assert builder.dialog is not None
        for flag in ("full_import_model_replacement", "materials_and_textures_only"):
            assert bool(builder.context.get(flag)) is bool(preset.get(flag, False)), flag


def _has_ancestor(widget: QWidget, ancestor: QWidget) -> bool:
    parent = widget.parentWidget()
    while parent is not None:
        if parent is ancestor:
            return True
        parent = parent.parentWidget()
    return False


def _section_titled(builder, title: str) -> CollapsibleSection:
    matches = [
        section
        for section in builder.dialog.findChildren(CollapsibleSection)
        if section.toggle_button.text() == title
    ]
    assert matches, f"no section titled {title!r}"
    return matches[0]


def test_material_authority_is_hidden_for_modify_original() -> None:
    with open_mesh_builder(
        modify_original_clone_mode=True, dialog_title="Modify Original authority"
    ) as builder:
        assert builder.control("material_authority_section").isHidden()


def test_expanding_transform_and_parts_requests_the_deferred_mapping() -> None:
    with open_mesh_builder() as builder:
        requested = builder.control("mapping_table_build_requested")
        assert not requested.get("started")

        builder.click(_section_titled(builder, "Transform and Parts").toggle_button)

        assert requested.get("started")
        builder.control("mapping_table_build_timer").stop()


@_MODES
def test_the_parts_and_routing_tab_is_hidden(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=f"{mode_name} parts tab",
    ) as builder:
        tabs = builder.control("control_tabs")
        parts_tab = builder.control("parts_tab")
        setup_tab = builder.control("setup_tab")

        assert not tabs.isTabVisible(tabs.indexOf(parts_tab))
        assert tabs.isTabVisible(tabs.indexOf(setup_tab))


def test_options_reads_controls_then_summary_then_notes_then_compatibility() -> None:
    """The Options section's order, and that it does not say Options twice."""
    from PySide6.QtWidgets import QGroupBox

    with open_mesh_builder(dialog_title="Options order") as builder:
        options = _section_titled(builder, "Options")
        layout = options.body_layout
        widgets = [layout.itemAt(index).widget() for index in range(layout.count())]
        widgets = [widget for widget in widgets if widget is not None]

        # The alignment controls come first, and their group carries no title of
        # its own inside a section that is already called Options.
        first = widgets[0]
        assert _has_ancestor(builder.control("alignment_mode_combo"), first) or first is builder.control("alignment_mode_combo").parentWidget()
        assert isinstance(first, QGroupBox) and first.title() == ""

        titles = []
        for widget in widgets[1:]:
            if isinstance(widget, QGroupBox):
                titles.append(widget.title())
            elif isinstance(widget, CollapsibleSection):
                titles.append(widget.toggle_button.text())
        # Alignment Summary, then (Import Notes when the import produced any),
        # then the compatibility details.
        assert titles[0] == "Alignment Summary"
        assert titles[-1] == "Compatibility Details"
        if "Import Notes" in titles:
            assert titles.index("Import Notes") == 1


def test_modify_original_writes_material_changes_only_when_something_was_tuned() -> None:
    """The gate is gone; the build decides from what the reader actually moved."""
    with open_mesh_builder(
        modify_original_clone_mode=True, dialog_title="Modify Original tuned"
    ) as builder:
        active = builder.context["_modify_original_texture_tuning_active"]
        assert not active(), "an untouched session keeps the target's own materials"

        controls = builder.control("manual_profile_controls")
        key, control = next(
            (name, widget)
            for name, widget in controls.items()
            if hasattr(widget, "setValue") and hasattr(widget, "maximum")
        )
        control.setValue(control.maximum())
        builder.pump()

        assert active(), f"moving {key} did not register as tuning"
