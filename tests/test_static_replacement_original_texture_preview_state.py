from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_original_texture_preview_state import (
    original_texture_preview_checkbox_tooltip,
    original_texture_preview_control_text,
    original_texture_preview_enabled,
    original_texture_preview_help_text,
    original_texture_preview_initial_state,
    original_texture_preview_material_preview_enabled,
    original_texture_preview_note_text,
    original_texture_preview_note_tooltip,
    original_texture_preview_set_enabled,
    original_texture_preview_toggle_state,
    original_reference_texture_preview_archive_parity_state,
    original_reference_texture_preview_clear_failure,
    original_reference_texture_preview_clear_loading,
    original_reference_texture_preview_clear_native_package_path,
    original_reference_texture_preview_can_start_load,
    original_reference_texture_preview_error_state,
    original_reference_texture_preview_exception_state,
    original_reference_texture_preview_failed_message,
    original_reference_texture_preview_initial_state,
    original_reference_texture_preview_loaded_detail,
    original_reference_texture_preview_loaded_performance,
    original_reference_texture_preview_loaded_progress_message,
    original_reference_texture_preview_load_start_state,
    original_reference_texture_preview_loading_message,
    original_reference_texture_preview_loading_performance,
    original_reference_texture_preview_mark_failed,
    original_reference_texture_preview_mark_loaded,
    original_reference_texture_preview_mark_loading,
    original_reference_texture_preview_manifest_performance,
    original_reference_texture_preview_ready_result_state,
    original_reference_texture_preview_ready_state,
    original_reference_texture_preview_readiness,
    original_reference_texture_preview_required,
    original_reference_texture_preview_resolve_failed_performance,
    original_reference_texture_preview_resolving_progress_message,
    original_reference_texture_preview_set_native_package_path,
)


def test_original_texture_preview_state_tracks_clone_gated_enablement() -> None:
    state = original_texture_preview_initial_state(enabled=True)

    assert state == {"enabled": True}
    assert original_texture_preview_enabled(state) is True
    assert original_texture_preview_material_preview_enabled(True, state) is True
    assert original_texture_preview_material_preview_enabled(False, state) is False

    assert original_texture_preview_set_enabled(state, True, modify_original_clone_mode=False) is False
    assert state == {"enabled": False}

    assert original_texture_preview_set_enabled(state, True, modify_original_clone_mode=True) is True
    assert state == {"enabled": True}


def test_original_texture_preview_toggle_state_routes_clear_load_and_refresh() -> None:
    preview_state = original_texture_preview_initial_state(enabled=False)
    reference_state = original_reference_texture_preview_initial_state()
    reference_state["failed"] = True
    reference_state["error"] = "old"

    disabled = original_texture_preview_toggle_state(
        preview_state,
        reference_state,
        True,
        modify_original_clone_mode=False,
    )

    assert disabled.enabled is False
    assert disabled.should_clear_failure is False
    assert disabled.should_load is False
    assert disabled.should_refresh is True
    assert reference_state["failed"] is True

    enabled = original_texture_preview_toggle_state(
        preview_state,
        reference_state,
        True,
        modify_original_clone_mode=True,
    )

    assert enabled.enabled is True
    assert enabled.should_clear_failure is True
    assert enabled.should_load is True
    assert enabled.should_refresh is True
    assert reference_state["failed"] is False
    assert reference_state["error"] == ""


def test_original_texture_preview_control_text_preserves_panel_copy() -> None:
    assert original_texture_preview_control_text() == {
        "group_title": "Original Texture Preview",
        "checkbox_label": "Preview with original DDS/materials",
    }


def test_original_texture_preview_display_text_tracks_modify_original_state() -> None:
    assert "resolved texture bindings" in original_texture_preview_checkbox_tooltip()
    assert "Preview-only" in original_texture_preview_help_text()
    assert original_texture_preview_note_text(
        modify_original_clone_mode=False,
        defer_original_texture_preview=True,
    ) == "Exact Modify Original clones only."
    assert original_texture_preview_note_text(
        modify_original_clone_mode=True,
        defer_original_texture_preview=True,
    ).startswith("On by default")
    assert original_texture_preview_note_text(
        modify_original_clone_mode=True,
        defer_original_texture_preview=False,
    ) == "Preview-only; exported only when replaced."
    assert "exact Modify Original clone" in original_texture_preview_note_tooltip(
        modify_original_clone_mode=False,
        defer_original_texture_preview=True,
    )
    assert "faster untextured" in original_texture_preview_note_tooltip(
        modify_original_clone_mode=True,
        defer_original_texture_preview=True,
    )
    assert original_texture_preview_note_tooltip(
        modify_original_clone_mode=True,
        defer_original_texture_preview=False,
    ) == original_texture_preview_help_text()


def test_original_reference_texture_preview_initial_state_matches_dialog_defaults() -> None:
    assert original_reference_texture_preview_initial_state() == {
        "loaded": False,
        "loading": False,
        "failed": False,
        "error": "",
        "native_package_path": "",
    }


def test_original_reference_texture_preview_required_modes_need_original_model() -> None:
    assert original_reference_texture_preview_required(
        "side_by_side",
        has_original_reference_model=True,
    ) is True
    assert original_reference_texture_preview_required(
        "overlay",
        has_original_reference_model=True,
    ) is True
    assert original_reference_texture_preview_required(
        "replacement_only",
        has_original_reference_model=True,
    ) is False
    assert original_reference_texture_preview_required(
        "overlay",
        has_original_reference_model=False,
    ) is False


def test_original_reference_texture_preview_readiness_tracks_load_state() -> None:
    state = original_reference_texture_preview_initial_state()

    assert original_reference_texture_preview_readiness(
        state,
        active_preview_mode="replacement_only",
        has_original_reference_model=True,
    ) == "ready"
    assert original_reference_texture_preview_readiness(
        state,
        active_preview_mode="overlay",
        has_original_reference_model=True,
    ) == "start"

    state["loading"] = True
    assert original_reference_texture_preview_readiness(
        state,
        active_preview_mode="overlay",
        has_original_reference_model=True,
    ) == "loading"

    state["loading"] = False
    state["failed"] = True
    assert original_reference_texture_preview_readiness(
        state,
        active_preview_mode="overlay",
        has_original_reference_model=True,
    ) == "ready"


def test_original_reference_texture_preview_ready_state_routes_preview_wait() -> None:
    state = original_reference_texture_preview_initial_state()

    ready = original_reference_texture_preview_ready_state(
        state,
        active_preview_mode="replacement_only",
        has_original_reference_model=True,
        reason="preview_refresh",
    )

    assert ready.ready is True
    assert ready.should_start_load is False

    waiting = original_reference_texture_preview_ready_state(
        state,
        active_preview_mode="overlay",
        has_original_reference_model=True,
        reason="preview_refresh",
    )

    assert waiting.ready is False
    assert waiting.should_start_load is True
    assert waiting.message == "Loading original textures: base/sidecar/support maps..."
    assert waiting.progress_message == "Preparing preview - resolving original textures."
    assert waiting.performance.summary == "Loading original textures: base/sidecar/support maps..."
    assert waiting.performance.details == "reason=preview_refresh"


def test_original_reference_texture_preview_archive_parity_state_routes_wait_start() -> None:
    state = original_reference_texture_preview_initial_state()

    assert original_reference_texture_preview_archive_parity_state(
        state,
        active_preview_mode="overlay",
        has_original_reference_model=True,
    ) == (False, True)

    state["loading"] = True
    assert original_reference_texture_preview_archive_parity_state(
        state,
        active_preview_mode="overlay",
        has_original_reference_model=True,
    ) == (False, False)

    state["loading"] = False
    state["loaded"] = True
    assert original_reference_texture_preview_archive_parity_state(
        state,
        active_preview_mode="overlay",
        has_original_reference_model=True,
    ) == (True, False)


def test_original_reference_texture_preview_can_start_load_ignores_failed_state() -> None:
    state = original_reference_texture_preview_initial_state()

    assert original_reference_texture_preview_can_start_load(
        state,
        has_original_reference_model=False,
    ) is False
    assert original_reference_texture_preview_can_start_load(
        state,
        has_original_reference_model=True,
    ) is True

    state["loading"] = True
    assert original_reference_texture_preview_can_start_load(
        state,
        has_original_reference_model=True,
    ) is False

    state["loading"] = False
    state["failed"] = True
    assert original_reference_texture_preview_can_start_load(
        state,
        has_original_reference_model=True,
    ) is True


def test_original_reference_texture_preview_state_transitions() -> None:
    state = original_reference_texture_preview_initial_state()

    original_reference_texture_preview_mark_loading(state)

    assert state["loading"] is True
    assert state["failed"] is False
    assert state["error"] == ""
    assert state["native_package_path"] == ""

    original_reference_texture_preview_set_native_package_path(state, "package")
    original_reference_texture_preview_mark_loaded(state)

    assert state["loaded"] is True
    assert state["loading"] is False
    assert state["failed"] is False
    assert state["native_package_path"] == "package"

    original_reference_texture_preview_mark_failed(state, "boom")

    assert state["loaded"] is False
    assert state["loading"] is False
    assert state["failed"] is True
    assert state["error"] == "boom"
    assert state["native_package_path"] == ""

    original_reference_texture_preview_clear_failure(state)

    assert state["failed"] is False
    assert state["error"] == ""


def test_original_reference_texture_preview_load_start_state_marks_loading_once() -> None:
    state = original_reference_texture_preview_initial_state()

    skipped = original_reference_texture_preview_load_start_state(
        state,
        has_original_reference_model=False,
    )

    assert skipped.should_start is False
    assert skipped.performance.summary == ""
    assert state["loading"] is False

    started = original_reference_texture_preview_load_start_state(
        state,
        has_original_reference_model=True,
    )

    assert started.should_start is True
    assert started.progress_message == "Preparing preview - resolving original textures."
    assert started.detail == "Loading original textures: base/sidecar/support maps..."
    assert started.performance.summary == "Loading original textures: base/sidecar/support maps..."
    assert started.performance.details == ""
    assert state["loading"] is True
    assert state["failed"] is False

    skipped_while_loading = original_reference_texture_preview_load_start_state(
        state,
        has_original_reference_model=True,
    )

    assert skipped_while_loading.should_start is False


def test_original_reference_texture_preview_selective_clear_helpers() -> None:
    state = original_reference_texture_preview_initial_state()
    state["loading"] = True
    state["native_package_path"] = "package"

    original_reference_texture_preview_mark_failed(
        state,
        "boom",
        clear_loading=False,
        clear_native_package=False,
    )

    assert state["loading"] is True
    assert state["native_package_path"] == "package"

    original_reference_texture_preview_clear_loading(state)
    original_reference_texture_preview_clear_native_package_path(state)

    assert state["loading"] is False
    assert state["native_package_path"] == ""


def test_original_reference_texture_preview_status_text() -> None:
    assert (
        original_reference_texture_preview_loading_message()
        == "Loading original textures: base/sidecar/support maps..."
    )
    assert (
        original_reference_texture_preview_resolving_progress_message()
        == "Preparing preview - resolving original textures."
    )
    assert (
        original_reference_texture_preview_loaded_progress_message()
        == "Preparing preview - original textures loaded."
    )
    assert original_reference_texture_preview_loaded_detail() == "Original textures loaded; applying resident materials."

    loading = original_reference_texture_preview_loading_performance("material")
    assert loading.summary == "Loading original textures: base/sidecar/support maps..."
    assert loading.details == "reason=material"
    assert original_reference_texture_preview_loading_performance().details == ""

    manifest = original_reference_texture_preview_manifest_performance(1200)
    assert manifest.summary == "Original native material manifest applied: 1,200 batch(es)."
    assert manifest.details == ""

    loaded = original_reference_texture_preview_loaded_performance(12.25)
    assert loaded.summary == "Original textures loaded; applying resident materials."
    assert loaded.details == "worker_elapsed_ms=12.2"

    assert (
        original_reference_texture_preview_failed_message("missing dds")
        == "Original texture preview failed; continuing untextured: missing dds"
    )
    failed = original_reference_texture_preview_resolve_failed_performance("missing dds")
    assert failed.summary == "Original texture resolve failed."
    assert failed.details == "missing dds"


def test_original_reference_texture_preview_ready_result_state_handles_current_live_request() -> None:
    state = original_reference_texture_preview_initial_state()
    state["loading"] = True

    stale = original_reference_texture_preview_ready_result_state(
        state,
        request_current=False,
        widgets_live=True,
        native_material_batches=3,
        elapsed_ms=7.5,
        d3d11_preview_active=True,
    )

    assert stale.handled is False
    assert state["loading"] is True

    active = original_reference_texture_preview_ready_result_state(
        state,
        request_current=True,
        widgets_live=True,
        native_material_batches=3,
        elapsed_ms=7.5,
        d3d11_preview_active=True,
    )

    assert active.handled is True
    assert active.should_apply_model is False
    assert active.should_apply_manifest_performance is True
    assert active.should_update_d3d11_progress is True
    assert active.manifest_performance.summary == "Original native material manifest applied: 3 batch(es)."
    assert active.loaded_performance.details == "worker_elapsed_ms=7.5"
    assert active.progress_message == "Preparing preview - original textures loaded."
    assert active.progress_detail == "Original textures loaded; applying resident materials."
    assert state["loaded"] is True
    assert state["loading"] is False

    non_d3d11 = original_reference_texture_preview_ready_result_state(
        original_reference_texture_preview_initial_state(),
        request_current=True,
        widgets_live=True,
        native_material_batches=0,
        elapsed_ms=1.0,
        d3d11_preview_active=False,
    )

    assert non_d3d11.should_apply_model is True
    assert non_d3d11.should_apply_manifest_performance is False
    assert non_d3d11.should_update_d3d11_progress is False


def test_original_reference_texture_preview_error_and_exception_states_mutate_status() -> None:
    state = original_reference_texture_preview_initial_state()
    state["loading"] = True

    stale = original_reference_texture_preview_error_state(
        state,
        request_current=False,
        message="old request",
    )

    assert stale.handled is False
    assert state["loading"] is True

    active = original_reference_texture_preview_error_state(
        state,
        request_current=True,
        message="missing dds",
    )

    assert active.handled is True
    assert active.message == "Original texture preview failed; continuing untextured: missing dds"
    assert active.performance.summary == "Original texture resolve failed."
    assert active.performance.details == "missing dds"
    assert state["loading"] is False
    assert state["failed"] is True
    assert state["error"] == "missing dds"

    exception_state = original_reference_texture_preview_initial_state()
    exception_state["loading"] = True
    exception_state["native_package_path"] = "keep"
    routed = original_reference_texture_preview_exception_state(exception_state, RuntimeError("boom"))

    assert routed.message == "Original texture preview failed; continuing untextured: boom"
    assert routed.performance.details == "boom"
    assert exception_state["loading"] is True
    assert exception_state["native_package_path"] == "keep"
    assert exception_state["failed"] is True
