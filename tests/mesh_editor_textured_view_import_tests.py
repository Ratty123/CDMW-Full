"""A textured Mesh view request must never leave the controls lying.

`_handle_embedded_viewport_display_mode` parks the viewport on the untextured
fallback and waits for a resident material acknowledgement. Every way the
texture resolver can decline to start one has to be answered, or the viewport
stays untextured while the Mesh view control still reads "Solid (Textured)".
"""

from __future__ import annotations

import json
import os
import time
from types import SimpleNamespace
from unittest.mock import patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.services.mesh_dotnet_experiment import mesh_dotnet_material_input_signature
from cdmw.services.mesh_dotnet_material_compiler import (
    snapshot_mesh_dotnet_material_inputs,
)
from cdmw.ui.archive_browser.static_replacement_original_texture_preview_state import (
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE,
    original_reference_texture_preview_initial_state,
    original_reference_texture_preview_load_start_state,
)
from cdmw.ui.mesh_editor import MeshEditorTab
from cdmw.ui.mesh_editor.tab_state import PENDING_TEXTURED_VIEW_MAX_EXTENSIONS
from tests.mesh_builder_driver import open_mesh_builder
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
    _build_two_part_synthetic_mesh,
    _install_shared_dotnet_test_process,
)


from tests.test_mesh_editor_textured_view_request_settles import _display_modes, _mounted_tab

def _material_updates(process: _FakeProcess) -> list[dict[str, object]]:
    return [
        json.loads(raw.decode("utf-8"))
        for raw in process.stdin_writes
        if b'"event":"material_state_update"' in raw
    ]


def _wait_for_material_updates(app, tab: MeshEditorTab, process: _FakeProcess, count: int) -> list[dict[str, object]]:
    deadline = time.monotonic() + 5.0
    updates: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        app.processEvents()
        updates = _material_updates(process)
        if len(updates) >= count and not tab._dotnet_material_compile_active():
            break
        time.sleep(0.005)
    return updates


def _acknowledge_material_update(tab: MeshEditorTab, update: dict[str, object]) -> None:
    assert tab._handle_dotnet_protocol_event(
        {
            "event": "material_state_applied",
            "generation": update["generation"],
            "material_signature": update["material_signature"],
            "texture_resources_ready": True,
        }
    )


def _bind_own_textures_to_working_mesh(builder) -> None:
    """Give the editable mesh the textures an external import binds at preflight."""

    for index, submesh in enumerate(
        tuple(getattr(builder.controller.working_mesh(clone=False), "submeshes", ()) or ())
    ):
        submesh.preview_texture_path = f"C:/imports/wolf_{index}.png"


def test_an_external_import_publishes_its_own_materials_at_its_commit_boundary() -> None:
    """Solid (Textured) on an imported model has to send the imported textures.

    The launch package deliberately carries no textures, so each pane is
    textured by a later publish. An exact clone borrows the resolved originals
    and the Original pane has its lazy resolver, but an external import's own
    textures, bound to the working mesh at preflight, were never sent by any
    path. The `editable_imported` role therefore never became ready and every
    textured request ended in `acknowledgement_timeout` -- the wolf sword over
    `cd_phm_01_sword_0039.pac` could not leave Faces (No Textures).

    The import now publishes from its own commit boundary, when the working
    model joins the resident session, rather than from the Original resolver.
    The Original publish that follows finds a compile in flight, is deferred,
    and is flushed after the Imported acknowledgement, so the later publish
    never pre-empts the earlier compile and both roles end up resident.
    """
    resolver_holder: dict[str, object] = {}
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewImportedPublish",
        lambda: resolver_holder["resolve"](),
    )
    tab.standalone_dotnet_experiment_package = SimpleNamespace(
        reference_submesh_count=1,
        scene_material_slot_indices=(),
    )
    controller = builder.controller
    _bind_own_textures_to_working_mesh(builder)
    reference_model = SimpleNamespace(
        meshes=[SimpleNamespace(material_name="original", preview_texture_path="")]
    )

    from cdmw.ui.archive_browser.static_replacement_preview_materials import (
        apply_resolved_original_materials_to_resident_editor,
    )

    def resolve() -> str:
        # Exactly what the builder's resolver does when the originals are
        # already resolved: republish through the mounted tab's hooks. It owns
        # the reference role only.
        apply_resolved_original_materials_to_resident_editor(
            dialog=builder,
            replacement_mesh_base=controller.base_mesh(clone=False),
            replacement_mesh=controller.working_mesh(clone=False),
            preview_model=reference_model,
            modify_original_clone_mode=False,
            publish_resident_updates=True,
        )
        return ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED

    resolver_holder["resolve"] = resolve
    combo = tab.embedded_workspace.viewport_display_combo

    # The working model joins the resident session. This is the commit boundary
    # that owns publishing an imported model's own materials.
    assert tab.commit_imported_working_model_materials(reason="resident_ready")

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert tab.standalone_dotnet_pending_textured_view is True
    assert _display_modes(process)[-1] == "untextured_faces"

    updates = _wait_for_material_updates(app, tab, process, 1)
    assert len(updates) == 1, updates
    imported_update = updates[0]
    assert imported_update["reason"] == "resident_ready"
    assert tab._dotnet_material_roles_for_generation(imported_update["generation"]) == (
        "editable_imported",
    )
    # The Original publish found the Imported compile in flight and waited.
    assert tab.standalone_dotnet_pending_reference_material_model is reference_model
    assert tab.standalone_dotnet_pending_textured_view is True

    _acknowledge_material_update(tab, imported_update)
    # The Imported pane is the active one, so it textures on its own
    # acknowledgement instead of waiting behind the Original pane.
    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "textured"
    assert combo.currentData() == "textured"
    # The Original publish that was waiting still goes out on the flush that
    # follows the acknowledgement, so both panes end up resident.
    assert tab._dotnet_missing_material_roles() == ("original_reference",)
    updates = _wait_for_material_updates(app, tab, process, 2)
    assert len(updates) == 2, updates
    reference_update = updates[1]
    assert reference_update["reason"] == "late_original_reference_resources"
    assert tab._dotnet_material_roles_for_generation(reference_update["generation"]) == (
        "original_reference",
    )

    _acknowledge_material_update(tab, reference_update)
    assert tab._dotnet_material_roles_ready()
    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "textured"
    assert combo.currentData() == "textured"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()

def test_an_imported_publish_behind_a_running_compile_is_flushed_after_it() -> None:
    """The Imported publish must not pre-empt whatever compile is running.

    The material compiler is latest-wins: a new request stops the active worker
    and takes its place, and the stopped one is not re-sent. Publishing straight
    away while an Original compile ran would have silently dropped it.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewImportedDeferred",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    # A compile is in flight: the desired generation is ahead of completion.
    tab.standalone_dotnet_material_generation = 3
    tab.standalone_dotnet_completed_material_generation = 2

    assert tab.apply_resident_imported_material_resources()
    assert tab.standalone_dotnet_pending_imported_material_publish is True
    assert _material_updates(process) == []

    # That compile lands; the flush that follows sends the remembered publish.
    tab.standalone_dotnet_completed_material_generation = 3
    tab._flush_pending_dotnet_reference_material_resources()
    assert tab.standalone_dotnet_pending_imported_material_publish is False
    assert tab.standalone_dotnet_material_generation == 4
    updates = _wait_for_material_updates(app, tab, process, 1)
    assert [update["reason"] for update in updates] == ["late_imported_resources"]

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_pending_texture_fallback_keeps_grid_and_requested_mode_authority() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedFallbackPresentation",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert tab._send_dotnet_presentation_state(
        {"display": {"grid_visible": True}}
    )

    writes = [json.loads(raw.decode("utf-8")) for raw in process.stdin_writes]
    presentation = next(
        payload
        for payload in reversed(writes)
        if payload.get("event") == "presentation_state_update"
    )
    assert presentation["display"]["mode"] == "untextured_faces"
    assert presentation["display"]["grid_visible"] is True
    assert tab.standalone_dotnet_presentation_desired["display"]["mode"] == "untextured_faces"
    assert tab.standalone_dotnet_presentation_desired["display"]["grid_visible"] is True

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()
