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


def _mounted_tab(name: str, resolver):
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", name))
    builder = _EmbeddedMeshBuilder()
    setattr(builder, "_mesh_editor_embedded_request_material_resources", resolver)
    tab.mount_embedded_builder(builder)
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = True
    tab.standalone_dotnet_target_controller = builder.controller
    tab._connect_dotnet_protocol(process)
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2", "viewport_display_modes_v1"),
    )
    setattr(builder, "_mesh_editor_embedded_dotnet_active", True)
    return app, tab, builder, process


def _display_modes(process: _FakeProcess) -> list[str]:
    return [
        str(payload.get("mode"))
        for payload in (json.loads(raw.decode("utf-8")) for raw in process.stdin_writes)
        if payload.get("event") == "viewport_display_update"
    ]


def _direct_tab(name: str):
    app = QApplication.instance() or QApplication([])
    tab = MeshEditorTab(settings=QSettings("CDMWTests", name))
    tab.open_mesh_session(
        _build_two_part_synthetic_mesh(),
        session_id="direct-textured-view",
        mode="edit",
    )
    assert tab.standalone_controller is not None
    process = _FakeProcess(tab)
    process._state = process.Running
    tab.standalone_dotnet_target_embedded = False
    tab.standalone_dotnet_target_controller = tab.standalone_controller
    tab._connect_dotnet_protocol(process)
    session_id = tab.standalone_controller.session_view().session_id
    _install_shared_dotnet_test_process(
        tab,
        process,
        capabilities=("resident_material_updates_v2", "viewport_display_modes_v1"),
        session_id=session_id,
    )
    tab.standalone_dotnet_lifecycle_session_id = session_id
    return app, tab, process


def _mark_material_role_ready(
    tab: MeshEditorTab,
    *,
    role: str = "editable_imported",
    generation: int = 1,
    signature: str = "resident-materials",
) -> None:
    tab.standalone_dotnet_material_generation = generation
    tab.standalone_dotnet_completed_material_generation = generation
    tab.standalone_dotnet_applied_material_generation = generation
    tab.standalone_dotnet_material_generation_by_role[role] = generation
    tab.standalone_dotnet_completed_material_generation_by_role[role] = generation
    tab.standalone_dotnet_applied_material_generation_by_role[role] = generation
    tab.standalone_dotnet_texture_resources_ready_by_role[role] = True
    tab.standalone_dotnet_material_signature_by_role[role] = signature


def test_load_start_state_reports_why_no_worker_started() -> None:
    idle = original_reference_texture_preview_initial_state()
    assert (
        original_reference_texture_preview_load_start_state(
            idle, has_original_reference_model=False
        ).outcome
        == ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE
    )

    fresh = original_reference_texture_preview_initial_state()
    started = original_reference_texture_preview_load_start_state(
        fresh, has_original_reference_model=True
    )
    assert started.should_start
    assert started.outcome == ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED
    # The same state is now marked loading, so a second request must say so
    # rather than look like a fresh start.
    assert (
        original_reference_texture_preview_load_start_state(
            fresh, has_original_reference_model=True
        ).outcome
        == ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT
    )

    loaded = dict(original_reference_texture_preview_initial_state(), loaded=True)
    assert (
        original_reference_texture_preview_load_start_state(
            loaded, has_original_reference_model=True
        ).outcome
        == ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED
    )


def test_already_loaded_does_not_claim_textures_that_were_never_applied() -> None:
    """"Already loaded" is about the resolver, not about the resident viewport.

    Both material generations start at zero, so `generation <= completed` held
    before anything had ever been applied. A resolver reporting `already_loaded`
    then completed the request as a success, the viewport was told to show
    "textured" over a launch package whose materials are deliberately empty
    (`"reason": "textures_on_demand"`), and Solid (Textured) drew exactly like
    Faces (No Textures) with no diagnostic anywhere.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewAlreadyLoaded",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED,
    )

    assert tab.standalone_dotnet_applied_material_generation == 0
    assert tab._handle_embedded_viewport_display_mode("textured")

    # No claim of success, and the viewport stays honestly untextured while the
    # watchdog waits for an acknowledgement that may still arrive.
    assert tab.standalone_dotnet_pending_textured_view is True
    assert _display_modes(process)[-1] == "untextured_faces"
    assert tab.standalone_dotnet_pending_textured_view_timer.isActive()

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_already_resolved_textures_apply_without_a_new_acknowledgement() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewAlreadyLoadedApplied",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED,
    )
    # A material state really was applied earlier in this session, so the
    # resolver's "already loaded" genuinely describes the resident viewport.
    _mark_material_role_ready(tab)

    assert tab._handle_embedded_viewport_display_mode("textured")

    # Nothing is in flight, so no material_state_applied is coming; the request
    # has to complete itself instead of waiting forever.
    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "textured"
    assert not tab.standalone_dotnet_pending_textured_view_timer.isActive()

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_direct_archive_session_can_load_and_keep_solid_textured_without_builder() -> None:
    app, tab, process = _direct_tab("MeshEditorDirectTexturedView")
    material_model = SimpleNamespace(
        meshes=(SimpleNamespace(preview_texture_path="resolved.dds"),)
    )
    tab.standalone_archive_material_preview_model = material_model

    with patch.object(
        tab,
        "apply_resident_clone_material_resources",
        return_value=True,
    ) as publish:
        assert tab._handle_dotnet_protocol_event(
            {
                "event": "viewport_display_request",
                "session_id": "direct-textured-view",
                "request_id": 71,
                "process_generation": 1,
                "mode": "textured",
            }
        )

    publish.assert_called_once_with(material_model)
    assert tab.standalone_dotnet_pending_textured_view is True
    assert _display_modes(process)[-1] == "untextured_faces"

    _mark_material_role_ready(tab)
    tab._finish_pending_textured_view(success=True)
    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "textured"

    assert tab._handle_dotnet_protocol_event(
        {
            "event": "viewport_display_request",
            "session_id": "direct-textured-view",
            "request_id": 72,
            "process_generation": 1,
            "mode": "vertices",
        }
    )
    assert _display_modes(process)[-1] == "vertices"

    tab.deleteLater()
    app.processEvents()


def test_unavailable_textures_restore_honest_untextured_display_authority() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewUnavailable",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")

    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "untextured_faces"
    assert combo.currentData() == "untextured_faces"
    assert tab.standalone_dotnet_presentation_desired["display"]["mode"] == "untextured_faces"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_a_resolver_that_starts_work_arms_the_watchdog_and_still_times_out() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewWatchdog",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert tab.standalone_dotnet_pending_textured_view is True
    assert tab.standalone_dotnet_pending_textured_view_timer.isActive()

    # Fire the watchdog directly rather than waiting out its real interval.
    tab._handle_pending_textured_view_timeout()
    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "untextured_faces"
    assert combo.currentData() == "untextured_faces"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def _acknowledge_material_state(
    tab: MeshEditorTab,
    process: _FakeProcess,
    *,
    texture_resources_ready: bool = True,
) -> None:
    """Deliver the acknowledgement a finished resident material update sends."""
    tab.standalone_dotnet_material_generation = 1
    tab.standalone_dotnet_material_generation_by_role["editable_imported"] = 1
    tab.standalone_dotnet_material_role_by_generation[1] = "editable_imported"
    process.emit_stdout(
        json.dumps(
            {
                "event": "material_state_applied",
                "generation": 1,
                "material_signature": "resident-materials",
                "texture_resources_ready": texture_resources_ready,
            }
        )
        + "\n"
    )


def test_material_ack_without_a_bound_texture_keeps_the_honest_fallback() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewNoBoundTexture",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    combo = tab.embedded_workspace.viewport_display_combo
    runtime_events: list[tuple[str, dict[str, object]]] = []
    tab.runtime_event_requested.connect(
        lambda event, payload: runtime_events.append((str(event), dict(payload)))
    )

    assert tab._handle_embedded_viewport_display_mode("textured")
    _acknowledge_material_state(
        tab,
        process,
        texture_resources_ready=False,
    )

    assert tab.standalone_dotnet_pending_textured_view is False
    assert tab.standalone_dotnet_deferred_textured_view_mode == "textured"
    assert tab.standalone_dotnet_texture_resources_ready_by_role["editable_imported"] is False
    assert _display_modes(process)[-1] == "untextured_faces"
    assert combo.currentData() == "untextured_faces"
    assert any(
        event == "mesh_dotnet_textured_view_failed"
        and payload.get("reason") == "editable_imported_texture_resources_not_ready"
        for event, payload in runtime_events
    )

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_unsupported_texture_helper_keeps_fallback_authority_when_send_fails() -> None:
    app, tab, builder, _process = _mounted_tab(
        "MeshEditorTexturedViewUnsupportedSendFailure",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    tab.standalone_dotnet_capabilities.discard("resident_material_updates_v2")
    tab._send_dotnet_protocol_message = lambda _payload: False  # type: ignore[method-assign]

    assert not tab._handle_embedded_viewport_display_mode("textured")
    assert (
        tab.standalone_dotnet_presentation_desired["display"]["mode"]
        == "untextured_faces"
    )
    assert tab.embedded_workspace.viewport_display_combo.currentData() == "untextured_faces"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_failed_textured_request_can_be_selected_again_as_a_real_retry() -> None:
    outcomes = iter(
        (
            ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE,
            ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
        )
    )
    calls: list[str] = []

    def resolve() -> str:
        calls.append("resolve")
        return next(outcomes)

    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewRetry",
        resolve,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert combo.currentData() == "untextured_faces"
    assert tab.standalone_dotnet_pending_textured_view is False

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert calls == ["resolve", "resolve"]
    assert tab.standalone_dotnet_pending_textured_view is True
    assert tab.standalone_dotnet_pending_textured_view_timer.isActive()
    assert combo.currentData() == "untextured_faces"
    assert _display_modes(process)[-1] == "untextured_faces"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_a_busy_compiler_extends_the_wait_instead_of_failing_it() -> None:
    """The watchdog must not abandon the compile it is waiting on.

    Reading a full character's original textures out of the archive and
    compiling them outlasts one interval, and giving up parked the viewport on
    the untextured fallback while the work that would have textured it was still
    running.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewBusyCompiler",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")
    tab.standalone_dotnet_material_update_worker = object()
    assert tab._dotnet_material_compile_active()

    tab._handle_pending_textured_view_timeout()

    assert tab.standalone_dotnet_pending_textured_view is True
    assert tab.standalone_dotnet_pending_textured_view_extensions == 1
    assert tab.standalone_dotnet_pending_textured_view_timer.isActive()
    # Still waiting, so nothing has been put back yet.
    assert _display_modes(process)[-1] == "untextured_faces"
    assert tab.standalone_dotnet_deferred_textured_view_mode == ""

    # A compile that never finishes still has to surface, so the extensions are
    # bounded rather than unlimited.
    tab.standalone_dotnet_pending_textured_view_extensions = (
        PENDING_TEXTURED_VIEW_MAX_EXTENSIONS
    )
    tab._handle_pending_textured_view_timeout()
    assert tab.standalone_dotnet_pending_textured_view is False
    assert combo.currentData() == "untextured_faces"

    tab.standalone_dotnet_material_update_worker = None
    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_textures_that_land_after_the_wait_still_restore_the_textured_view() -> None:
    """Giving up on the wait does not cancel the resolve or the compile.

    Those finish anyway, so the acknowledgement arrives after the controls were
    put back. Dropping it left the viewport flat for the rest of the session
    even though the resident scene was holding exactly the requested materials.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewLateArrival",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")
    tab._handle_pending_textured_view_timeout()
    assert combo.currentData() == "untextured_faces"
    assert tab.standalone_dotnet_deferred_textured_view_mode == "textured"

    _acknowledge_material_state(tab, process)

    assert tab.standalone_dotnet_deferred_textured_view_mode == ""
    assert _display_modes(process)[-1] == "textured"
    assert combo.currentData() == "textured"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_a_later_mode_choice_cancels_the_restore() -> None:
    """Whatever the user picked after the failure is what they get to keep."""
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewSuperseded",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")
    tab._handle_pending_textured_view_timeout()
    assert tab.standalone_dotnet_deferred_textured_view_mode == "textured"

    assert tab._handle_embedded_viewport_display_mode("vertices")
    assert tab.standalone_dotnet_deferred_textured_view_mode == ""

    _acknowledge_material_state(tab, process)

    assert _display_modes(process)[-1] == "vertices"
    assert combo.currentData() == "vertices"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def _resident_material_signature(tab: MeshEditorTab) -> str:
    controller = tab._dotnet_target_controller()
    package = getattr(tab, "standalone_dotnet_experiment_package", None)
    return str(
        mesh_dotnet_material_input_signature(
            snapshot_mesh_dotnet_material_inputs(
                controller.working_mesh(clone=False),
                scene_material_slot_indices=tuple(
                    getattr(package, "scene_material_slot_indices", ()) or ()
                ),
                submesh_index_offset=0,
            )
        )
    )


def test_a_deduplicated_material_publish_completes_the_textured_view() -> None:
    """Resolved materials the helper already holds still have to settle the wait.

    The publish path returns success after deduplicating, having sent nothing,
    so no material_state_applied is coming. That left the viewport on the
    untextured fallback for the full watchdog interval before the Mesh view
    control silently snapped back to "Faces (No Textures)".
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewDeduplicated",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert tab.standalone_dotnet_pending_textured_view is True
    assert _display_modes(process)[-1] == "untextured_faces"

    # The resolver's model carries exactly the materials the helper reported at
    # ready, so publishing it deduplicates instead of sending an update.
    tab.standalone_dotnet_material_signature = _resident_material_signature(tab)
    # A generation was applied while the request was in flight, which is what
    # makes "the helper already holds these" true rather than merely unproven.
    _mark_material_role_ready(
        tab,
        signature=tab.standalone_dotnet_material_signature,
    )
    assert tab._send_dotnet_material_state(reason="late_exact_clone_resources")
    assert tab.standalone_dotnet_lifecycle_counts["material_state_deduplicated_count"] == 1

    assert tab.standalone_dotnet_pending_textured_view is False
    assert not tab.standalone_dotnet_pending_textured_view_timer.isActive()
    assert _display_modes(process)[-1] == "textured"
    assert combo.currentData() == "textured"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_same_session_package_swap_republishes_before_restoring_textured_view() -> None:
    """A geometry package cannot inherit the prior package's material readiness."""

    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewPackageSwap",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    combo = tab.embedded_workspace.viewport_display_combo
    resident_signature = _resident_material_signature(tab)
    tab.standalone_dotnet_material_signature = resident_signature
    _mark_material_role_ready(tab, signature=resident_signature)
    tab.standalone_dotnet_material_input_signature_by_role[
        "editable_imported"
    ] = resident_signature

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert combo.currentData() == "textured"
    assert tab._send_dotnet_material_state(reason="already_resident")
    assert tab.standalone_dotnet_lifecycle_counts[
        "material_state_deduplicated_count"
    ] == 1
    assert not any(
        b'"event":"material_state_update"' in raw
        for raw in process.stdin_writes
    )

    retries: list[str] = []

    def republish_after_package() -> str:
        retries.append("requested")
        assert tab._send_dotnet_material_state(reason="resident_package_replaced")
        return ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED

    setattr(
        builder,
        "_mesh_editor_embedded_request_material_resources",
        republish_after_package,
    )
    controller = tab._active_shared_dotnet_controller()
    assert controller is not None
    controller._applied_package_generation = 2
    runtime_events: list[tuple[str, object]] = []
    tab.runtime_event_requested.connect(
        lambda event, fields: runtime_events.append((str(event), fields))
    )
    tab.standalone_dotnet_pending_textured_view = True
    tab.standalone_dotnet_pending_textured_view_mode = "textured"

    # The accepted-package rehydrator runs before the helper is revealed. It
    # must invalidate the old acknowledgement before replaying presentation, so
    # that replay carries the honest untextured fallback rather than Textured.
    assert tab._rehydrate_shared_dotnet_controller(controller)
    boundary_generation = tab.standalone_dotnet_material_generation
    assert boundary_generation == tab.standalone_dotnet_completed_material_generation
    assert tab.standalone_dotnet_applied_material_generation == 0
    assert not tab.standalone_dotnet_applied_material_generation_by_role
    assert not tab.standalone_dotnet_texture_resources_ready_by_role
    assert not tab._dotnet_material_roles_ready()
    assert "mesh_dotnet_textured_view_deferred" in {
        event for event, _fields in runtime_events
    }
    assert "mesh_dotnet_textured_view_failed" not in {
        event for event, _fields in runtime_events
    }
    assert combo.currentData() == "untextured_faces"
    assert (
        tab.standalone_dotnet_presentation_desired["display"]["mode"]
        == "untextured_faces"
    )

    tab._handle_shared_dotnet_package_applied(controller, "geometry-only", 2)
    deadline = time.monotonic() + 3.0
    material_updates: list[dict[str, object]] = []
    while time.monotonic() < deadline:
        app.processEvents()
        material_updates = [
            json.loads(raw.decode("utf-8"))
            for raw in process.stdin_writes
            if b'"event":"material_state_update"' in raw
        ]
        if material_updates and not tab._dotnet_material_compile_active():
            break
        time.sleep(0.005)

    assert retries == ["requested"]
    assert len(material_updates) == 1
    material_update = material_updates[0]
    assert material_update["generation"] > boundary_generation
    assert material_update["package_generation"] == 2
    assert tab.standalone_dotnet_lifecycle_counts[
        "material_state_deduplicated_count"
    ] == 1
    assert tab.standalone_dotnet_pending_textured_view is True
    assert combo.currentData() == "untextured_faces"

    assert tab._handle_dotnet_protocol_event(
        {
            "event": "material_state_applied",
            "generation": material_update["generation"],
            "package_generation": 2,
            "material_signature": material_update["material_signature"],
            "texture_resources_ready": True,
        }
    )
    assert tab.standalone_dotnet_pending_textured_view is False
    assert tab._dotnet_material_roles_ready()
    assert combo.currentData() == "textured"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_the_launch_package_signature_does_not_deduplicate_the_first_publish() -> None:
    """The launch package's signature is not evidence that textures are resident.

    `_start_standalone_dotnet_editor_process` seeds
    `standalone_dotnet_material_signature` from the launch package, whose
    materials are deliberately empty. On an unedited mesh the first real publish
    therefore computed the very same signature, and with both generations still
    at zero `generation <= completed` held too -- so the publish deduplicated,
    no compile ever ran, and the textured view was reported as succeeding over a
    package with no material resources at all.
    """
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewLaunchSignature",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    )
    # Exactly what the launch package seeds, for a mesh nobody has edited yet.
    tab.standalone_dotnet_material_signature = _resident_material_signature(tab)
    assert tab.standalone_dotnet_applied_material_generation == 0

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert tab.standalone_dotnet_pending_textured_view is True

    assert tab._send_dotnet_material_state(reason="textured_view_requested")

    # The publish must do real work rather than assume the helper already holds
    # materials it was never sent.
    assert tab.standalone_dotnet_lifecycle_counts["material_state_deduplicated_count"] == 0
    assert tab.standalone_dotnet_material_generation > 0
    assert tab.standalone_dotnet_pending_textured_view is True
    assert _display_modes(process)[-1] == "untextured_faces"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_a_resolver_returning_nothing_still_waits_for_its_acknowledgement() -> None:
    calls: list[str] = []
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewLegacyResolver",
        lambda: calls.append("requested"),
    )

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert calls == ["requested"]
    assert tab.standalone_dotnet_pending_textured_view is True

    _acknowledge_material_state(tab, process)
    assert _display_modes(process)[-1] == "textured"
    assert not tab.standalone_dotnet_pending_textured_view_timer.isActive()

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def _texture_preview_state(driver, **flags) -> None:
    state = driver.context["original_reference_texture_preview_state"]
    state.clear()
    state.update(
        {
            "loaded": False,
            "loading": False,
            "failed": False,
            "error": "",
            "native_package_path": "",
            **flags,
        }
    )


def test_the_real_builder_resolver_reports_and_republishes() -> None:
    """The production resolver, not a stand-in, has to answer every request.

    The tab's textured-view wait is only as honest as what this returns, and it
    is generated code reached through several context layers, so a stub proves
    nothing about the wiring.
    """
    with open_mesh_builder(dialog_title="Textured view resolver") as driver:
        resolver = driver.dialog._mesh_editor_embedded_request_material_resources
        published: list[str] = []
        failures: list[str] = []
        driver.dialog._mesh_editor_embedded_apply_reference_material_resources = (
            lambda _model: (published.append("reference"), True)[1]
        )
        driver.dialog._mesh_editor_embedded_apply_clone_material_resources = (
            lambda _model: (published.append("clone"), True)[1]
        )
        driver.dialog._mesh_editor_embedded_texture_request_failed = failures.append

        # Textures already resolved: previously a silent return, which left the
        # viewport parked on the untextured fallback for good.
        _texture_preview_state(driver, loaded=True)
        assert resolver() == ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED
        assert published == ["reference"]
        assert failures == []

        # A load already running will publish and acknowledge on its own.
        published.clear()
        _texture_preview_state(driver, loading=True)
        assert resolver() == ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT
        assert published == []
        assert failures == []


def test_a_settled_material_state_still_resolves_the_original_pane_textures() -> None:
    """Solid (Textured) has to texture both panes, without one holding the other.

    The Imported pane's materials were published earlier in the session, so a
    material state for that role has been applied before the reader picks a
    textured Mesh view. The Original pane's textures are not part of that; the
    embedded builder resolves them lazily, through this same resolver, and
    deliberately not at open. The fast path returned as soon as the editable
    materials were settled and never asked for them, which is exactly "Solid
    (Textured) loads for the Imported preview but not the Original".

    The active pane is the one that settles the request, so the Imported mesh
    goes textured immediately rather than waiting behind a pane that may take a
    full character's archive read to compile. The reference resolve is still
    kicked off, and the Original pane textures itself when its own correlated
    update lands.
    """
    requests: list[str] = []

    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewResolvesReference",
        lambda: (
            requests.append("resolve"),
            ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT,
        )[1],
    )
    tab.standalone_dotnet_experiment_package = SimpleNamespace(
        reference_submesh_count=1,
        scene_material_slot_indices=(),
    )
    # The editable package's materials are resident and settled.
    _mark_material_role_ready(tab)

    assert tab._handle_embedded_viewport_display_mode("textured")

    # The active pane is ready, so it textures now.
    assert _display_modes(process)[-1] == "textured"
    assert tab.standalone_dotnet_pending_textured_view is False
    # ...and the Original pane's lazy resolve was still asked for, which is the
    # part that used to be skipped entirely on this fast path.
    assert requests == ["resolve"]
    # The Original pane is not textured yet and says so on its own.
    assert tab._dotnet_missing_material_roles() == ("original_reference",)
    assert (
        tab._dotnet_material_role_blocking_reason("original_reference")
        == "Original pane materials have not been published yet."
    )

    tab.standalone_dotnet_material_generation = 2
    tab.standalone_dotnet_material_generation_by_role["original_reference"] = 2
    tab.standalone_dotnet_material_role_by_generation[2] = "original_reference"
    process.emit_stdout(
        json.dumps(
            {
                "event": "material_state_applied",
                "generation": 2,
                "role": "original_reference",
                "material_signature": "reference-materials",
                "texture_resources_ready": True,
            }
        )
        + "\n"
    )

    assert tab._dotnet_material_roles_ready()
    assert tab._dotnet_material_role_blocking_reason("original_reference") == ""
    assert _display_modes(process)[-1] == "textured"

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


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
