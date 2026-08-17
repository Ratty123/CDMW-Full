"""Where an imported model's own materials are published, and what settles a pane.

Two rules are pinned here, both of which the plan's audit named as the
architecture faults behind Solid (Textured) staying grey.

The first is ownership: importing an editable model owns publishing that model's
material resources, at the boundary where the working model joins the resident
session. Driving it from the Original resolver instead meant the Imported pane
could only become textured as a side effect of resolving a different pane.

The second is that the pane in front of the reader settles the textured request.
Readiness used to be all-or-nothing across every role the resident package
carried, so a secondary pane that failed or was still compiling held the visible
mesh grey behind it.
"""

from __future__ import annotations

import json
import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cdmw.ui.archive_browser.static_replacement_original_texture_preview_state import (
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE,
)
from tests.test_mesh_editor_textured_view_request_settles import (
    _acknowledge_material_update,
    _bind_own_textures_to_working_mesh,
    _display_modes,
    _mark_material_role_ready,
    _material_updates,
    _mounted_tab,
    _wait_for_material_updates,
)


def test_an_import_becomes_textured_without_the_original_resolver_running() -> None:
    """A single-pane import must not depend on a resolver for the other pane.

    This is the failure the commit-boundary move exists to prevent: with the
    publish driven from the Original resolver, an import whose Original pane
    never resolved -- a single-pane workflow, or a resolver that errored -- had
    no route to `editable_imported` at all and sat grey until the watchdog gave
    up.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewImportedNoReference",
        # The Original resolver is unavailable, exactly as in a single-pane
        # workflow. Nothing here may publish the imported role.
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE,
    )
    tab.standalone_dotnet_experiment_package = SimpleNamespace(
        reference_submesh_count=0,
        scene_material_slot_indices=(),
    )
    _bind_own_textures_to_working_mesh(builder)
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab.commit_imported_working_model_materials(reason="resident_ready")
    updates = _wait_for_material_updates(app, tab, process, 1)
    assert len(updates) == 1, updates
    assert updates[0]["reason"] == "resident_ready"
    assert tab._dotnet_material_roles_for_generation(updates[0]["generation"]) == (
        "editable_imported",
    )

    _acknowledge_material_update(tab, updates[0])
    assert tab._dotnet_material_roles_ready()

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert _display_modes(process)[-1] == "textured"
    assert combo.currentData() == "textured"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_a_model_without_its_own_textures_does_not_publish_at_the_commit_boundary() -> None:
    """An exact clone has nothing of its own to publish yet.

    Its bindings are copied from the resolved originals later. Publishing at
    activation would compile an empty material set and report the role ready
    with no textures on it, which is the same wrong answer the old signature
    dedupe gave.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewCloneCommit",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )

    assert tab.commit_imported_working_model_materials(reason="resident_ready") is False
    assert _material_updates(process) == []
    assert not tab.standalone_dotnet_material_publications.has_work()

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_the_commit_boundary_does_not_republish_an_already_ready_role() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewCommitIdempotent",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    _bind_own_textures_to_working_mesh(builder)
    _mark_material_role_ready(tab)

    assert tab.commit_imported_working_model_materials(reason="resident_activated")
    assert _material_updates(process) == []

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_an_original_pane_failure_leaves_the_imported_pane_textured() -> None:
    """A secondary pane's failure must not un-texture the pane in front of you.

    Readiness used to be all-or-nothing across every role the package carried,
    so an Original compile that failed -- a shared-texture blocker, a missing
    map, an archive read that never returned -- held the Imported mesh grey even
    though its own materials were resident.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewOriginalFails",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT,
    )
    tab.standalone_dotnet_experiment_package = SimpleNamespace(
        reference_submesh_count=1,
        scene_material_slot_indices=(),
    )
    _mark_material_role_ready(tab)

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert _display_modes(process)[-1] == "textured"

    tab.standalone_dotnet_material_generation = 2
    tab.standalone_dotnet_material_generation_by_role["original_reference"] = 2
    tab.standalone_dotnet_material_role_by_generation[2] = "original_reference"
    assert not tab._handle_dotnet_protocol_event(
        {
            "event": "material_state_failed",
            "generation": 2,
            "role": "original_reference",
            "message": "missing base map",
        }
    )

    # The Original pane reports its own failure...
    assert tab._dotnet_material_role_status("original_reference")["stage"] == "failed"
    assert "missing base map" in tab._dotnet_material_role_blocking_reason(
        "original_reference"
    )
    # ...and the Imported pane keeps the mode it reached.
    assert tab._dotnet_material_role_status("editable_imported")["stage"] == "textured"
    assert tab._dotnet_active_material_role_ready()
    assert _display_modes(process)[-1] == "textured"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_the_active_role_follows_an_original_only_comparison() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewOriginalOnly",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT,
    )
    assert tab._dotnet_active_material_role() == "editable_imported"

    tab.standalone_dotnet_scene_desired["comparison_mode"] = "original_only"
    assert tab._dotnet_active_material_role() == "original_reference"

    tab.standalone_dotnet_scene_desired["comparison_mode"] = "side_by_side"
    assert tab._dotnet_active_material_role() == "editable_imported"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()
