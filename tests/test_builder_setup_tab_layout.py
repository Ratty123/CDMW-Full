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
