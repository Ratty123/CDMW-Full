"""Where the Builder's controls live, checked against a real construction.

The Setup tab was rearranged on the owner's direction: alignment options moved
out of Advanced into a section renamed Options; Material Authority is Advanced's
content rather than a section inside a group inside it; and the whole Parts &
Routing tab was folded into Part Setup, which now holds the per-part inspector
followed by the routing overview that used to be that tab.

Widget parentage is the thing that changes here, and it is resolved at runtime,
so these construct the Builder and walk up from each control to see which
section it ended up under.
"""

from __future__ import annotations

import pytest
from PySide6.QtWidgets import QWidget

from cdmw.ui.panel_widgets import CollapsibleSection

from tests.mesh_builder_driver import open_mesh_builder


_MODES = pytest.mark.parametrize(
    ("modify_original_clone_mode", "mode_name"),
    ((False, "Import Mesh"), (True, "Modify Original")),
)


def _enclosing_section(widget: QWidget) -> CollapsibleSection | None:
    """The nearest CollapsibleSection above `widget`, or None."""
    parent = widget.parentWidget()
    while parent is not None:
        if isinstance(parent, CollapsibleSection):
            return parent
        parent = parent.parentWidget()
    return None


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


@_MODES
def test_alignment_options_live_under_options_not_advanced(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=f"{mode_name} options placement",
    ) as builder:
        options = _section_titled(builder, "Options")
        advanced = _section_titled(builder, "Advanced")

        alignment_mode = builder.control("alignment_mode_combo")
        assert _enclosing_section(alignment_mode) is options
        assert _enclosing_section(alignment_mode) is not advanced


def test_material_authority_is_advanced_content_not_a_nested_section() -> None:
    with open_mesh_builder(dialog_title="Material Authority placement") as builder:
        advanced = _section_titled(builder, "Advanced")
        authority = builder.control("material_authority_section")

        # It sits directly in Advanced, and reads as content rather than as
        # another collapsible: its own header is hidden.
        assert authority.parentWidget() is advanced.body_frame
        assert authority.toggle_button.isHidden()
        assert authority.toggle_button.isChecked(), "expanded, since there is no header to expand it"


def test_material_authority_is_hidden_for_modify_original() -> None:
    with open_mesh_builder(
        modify_original_clone_mode=True, dialog_title="Modify Original authority"
    ) as builder:
        assert builder.control("material_authority_section").isHidden()


@_MODES
def test_part_setup_holds_the_inspector_and_the_routing_overview(
    modify_original_clone_mode: bool, mode_name: str
) -> None:
    with open_mesh_builder(
        modify_original_clone_mode=modify_original_clone_mode,
        dialog_title=f"{mode_name} part setup",
    ) as builder:
        part_setup = _section_titled(builder, "Part Setup")

        # The per-part inspector and the routing overview that was the whole
        # Parts & Routing tab both live here now.
        assert _enclosing_section(builder.control("part_inspector")) is part_setup
        assert _enclosing_section(builder.control("mapping_group")) is part_setup
        # And the overview's trees came with it: nothing was removed. The
        # mapping tree sits inside its own advanced sub-section within the
        # group, so ancestry rather than nearest-section is the right test.
        for name in ("source_tree", "original_tree", "mapping_tree"):
            assert _has_ancestor(builder.control(name), part_setup), name


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


def test_opening_part_setup_starts_the_deferred_mapping_build() -> None:
    """The mapping table built lazily when the Parts tab was shown; the tab is
    hidden, so opening Part Setup is the trigger now."""
    with open_mesh_builder(dialog_title="Part Setup build trigger") as builder:
        part_setup = _section_titled(builder, "Part Setup")
        # `mapping_table_build_requested` is where the "started" flag lives;
        # `mapping_table_build_state` tracks progress once it is running.
        requested = builder.control("mapping_table_build_requested")
        assert not requested.get("started"), "the build must not have been requested before the section was opened"

        part_setup.set_expanded(True)
        builder.pump()

        assert requested.get("started"), (
            "expanding Part Setup did not request the mapping table build"
        )
        # The build runs in chunks on a timer, as it always did. What is under
        # test is that opening the section requested it; the driver refuses to
        # close over a live timer, so stop it once that is established.
        builder.control("mapping_table_build_timer").stop()


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


def test_modify_original_advanced_holds_the_tuning_controls_without_a_gate() -> None:
    """One Advanced in Modify Original, with the tuning group inside and no tick required."""
    with open_mesh_builder(
        modify_original_clone_mode=True, dialog_title="Modify Original advanced"
    ) as builder:
        advanced = _section_titled(builder, "Advanced")
        tuning_group = builder.control("manual_profile_group")

        assert _has_ancestor(tuning_group, advanced)
        # No second section, and no gate the reader has to tick.
        assert builder.control("modify_original_texture_tuning_section").isHidden()
        gate = builder.control("modify_original_texture_tuning_checkbox")
        assert gate.isHidden() and gate.isChecked()


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


def test_import_mesh_material_authority_has_one_switch_and_the_acknowledgement() -> None:
    from PySide6.QtWidgets import QCheckBox

    with open_mesh_builder(dialog_title="Material Authority switch") as builder:
        authority = builder.control("material_authority_section")
        swap = builder.checkbox("MeshAlignmentCompleteExternalSwapCheckbox")
        unsafe = builder.checkbox("MeshAlignmentUnsafeMaterialPreflightExportCheckbox")

        assert _has_ancestor(swap, authority)
        assert _has_ancestor(unsafe, authority)
        assert not swap.isHidden() and not unsafe.isHidden()
        # The five routing checkboxes the switch replaced are gone from view.
        for name in (
            "rebuild_sidecar_checkbox",
            "prune_unmapped_original_dds_checkbox",
            "inject_base_color_checkbox",
            "source_color_faithful_checkbox",
            "external_material_reset_checkbox",
        ):
            assert builder.control(name).isHidden(), name
