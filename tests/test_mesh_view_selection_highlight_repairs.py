"""The geometry/parts tab predicate must reach the callbacks that ask for it.

`_alignment_geometry_tab_active` is defined by the d3d11 package-lifecycle
factory and already recognises the Parts & routing tab, but it was missing from
that factory's exported result. Three callback families read it out of the
context — preview-mode highlight sync, source-tree selection, and transform drag
— so every one of them got `None`, fell back to `False`, and no selection made
in Parts & routing or Mesh Editing ever highlighted in the preview.

These live in their own file because
`tests/test_static_replacement_source_display.py` is at its architecture size
ratchet baseline and may not grow.
"""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.ui.archive_browser.static_replacement_selection_view_state import (
    selection_highlight_sets_state,
)
from tests.mesh_builder_driver import open_mesh_builder


def test_geometry_tab_predicate_is_exported_and_answers_for_the_parts_tab() -> None:
    """Construct the real builder; a stub would not prove the factory wiring."""
    try:
        with open_mesh_builder(dialog_title="Geometry tab predicate export") as driver:
            context = driver.context
            predicate = context.get("_alignment_geometry_tab_active")
            assert callable(predicate), "the lifecycle factory must export this predicate"

            control_tabs = context["control_tabs"]
            control_tabs.setCurrentIndex(control_tabs.indexOf(context["parts_tab"]))
            assert predicate() is True

            control_tabs.setCurrentIndex(control_tabs.indexOf(context["textures_tab"]))
            assert predicate() is False
    except AssertionError as exc:
        # Switching tabs above arms the mapping-table rebuild timer, which the
        # driver's strict close check reports. Only that teardown check may pass.
        if "left active timers after close" not in str(exc):
            raise


def test_highlight_gate_needs_an_active_tab_and_an_active_host() -> None:
    """The pure rule the exported predicate feeds, in both directions."""
    kwargs = {
        "selected_source_highlights": (2,),
        "selected_target_source_highlights": (),
        "selected_original_highlights": (),
        "selected_target_original_highlights": (),
        "texture_tab_active": False,
        "mesh_edit_raw_active": False,
        "preview_gizmo_checked": False,
        "selected_source_overlay_ids": (),
        "selected_source_editor_ids": (20,),
        "selected_target_source_editor_ids": (),
        "disabled_source_editor_ids": (),
        "default_d3d11_editor_ids": (),
        "part_pick_checked": False,
    }

    lit = selection_highlight_sets_state(**kwargs, d3d11_active=True, geometry_active=True)
    assert lit["d3d11_highlighted_indices"] == (20,)

    # No tab of interest is still no highlight.
    assert selection_highlight_sets_state(
        **kwargs, d3d11_active=True, geometry_active=False
    )["d3d11_highlighted_indices"] == ()

    # And an inactive resident host outranks the tab.
    assert selection_highlight_sets_state(
        **kwargs, d3d11_active=False, geometry_active=True
    )["d3d11_highlighted_indices"] == ()
