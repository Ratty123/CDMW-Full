"""A textured Mesh view request must never leave the controls lying.

`_handle_embedded_viewport_display_mode` parks the viewport on the untextured
fallback and waits for a resident material acknowledgement. Every way the
texture resolver can decline to start one has to be answered, or the viewport
stays untextured while the Mesh view control still reads "Solid (Textured)".
"""

from __future__ import annotations

import json
import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QSettings
from PySide6.QtWidgets import QApplication

from cdmw.ui.archive_browser.static_replacement_original_texture_preview_state import (
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_IN_FLIGHT,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_STARTED,
    ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE,
    original_reference_texture_preview_initial_state,
    original_reference_texture_preview_load_start_state,
)
from cdmw.ui.mesh_editor import MeshEditorTab
from tests.mesh_builder_driver import open_mesh_builder
from tests.test_mesh_editor_action_bar import (
    _EmbeddedMeshBuilder,
    _FakeProcess,
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


def test_already_resolved_textures_apply_without_a_new_acknowledgement() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewAlreadyLoaded",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_ALREADY_LOADED,
    )

    assert tab._handle_embedded_viewport_display_mode("textured")

    # Nothing is in flight, so no material_state_applied is coming; the request
    # has to complete itself instead of waiting forever.
    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "textured"
    assert not tab.standalone_dotnet_pending_textured_view_timer.isActive()

    tab.deleteLater()
    builder.deleteLater()
    app.processEvents()


def test_unavailable_textures_put_the_controls_back_to_the_untextured_view() -> None:
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewUnavailable",
        lambda: ORIGINAL_REFERENCE_TEXTURE_REQUEST_UNAVAILABLE,
    )
    combo = tab.embedded_workspace.viewport_display_combo

    assert tab._handle_embedded_viewport_display_mode("textured")

    assert tab.standalone_dotnet_pending_textured_view is False
    assert _display_modes(process)[-1] == "untextured_faces"
    assert combo.currentData() == "untextured_faces"

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


def test_a_resolver_returning_nothing_still_waits_for_its_acknowledgement() -> None:
    calls: list[str] = []
    app, tab, builder, process = _mounted_tab(
        "MeshEditorTexturedViewLegacyResolver",
        lambda: calls.append("requested"),
    )

    assert tab._handle_embedded_viewport_display_mode("textured")
    assert calls == ["requested"]
    assert tab.standalone_dotnet_pending_textured_view is True

    tab._finish_pending_textured_view(success=True)
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
