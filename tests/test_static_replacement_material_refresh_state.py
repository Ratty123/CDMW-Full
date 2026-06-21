from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_material_refresh_state import (
    material_edit_refresh_initial_state,
    material_edit_refresh_interval_ms,
    material_edit_refresh_queued_performance,
    material_edit_refresh_queued_progress_message,
    material_edit_refresh_running_performance,
    material_edit_refresh_running_progress_message,
    queue_material_edit_refresh_state,
    queue_source_material_plan_refresh_state,
    source_material_plan_refresh_initial_state,
    source_material_plan_refresh_interval_ms,
    take_material_edit_refresh_state,
    take_source_material_plan_refresh_state,
)


def test_material_refresh_initial_states_preserve_flags() -> None:
    assert material_edit_refresh_initial_state() == {
        "refresh_plan": False,
        "force_plan": False,
        "refresh_preview": False,
        "reason": "",
    }
    assert source_material_plan_refresh_initial_state() == {"force_plan": False, "reason": ""}


def test_queue_material_edit_refresh_state_merges_flags_and_reason() -> None:
    state: dict[str, object] = {
        "refresh_plan": True,
        "force_plan": False,
        "refresh_preview": False,
        "reason": "old",
    }

    reason = queue_material_edit_refresh_state(
        state,
        refresh_plan=False,
        force_plan=True,
        refresh_preview=True,
        reason=" role change ",
    )

    assert reason == "role change"
    assert state == {
        "refresh_plan": True,
        "force_plan": True,
        "refresh_preview": True,
        "reason": "role change",
    }


def test_take_material_edit_refresh_state_returns_payload_and_resets() -> None:
    state: dict[str, object] = {
        "refresh_plan": True,
        "force_plan": True,
        "refresh_preview": True,
        "reason": "role change",
    }

    payload = take_material_edit_refresh_state(state)

    assert payload == {
        "refresh_plan": True,
        "force_plan": True,
        "refresh_preview": True,
        "reason": "role change",
    }
    assert state == {
        "refresh_plan": False,
        "force_plan": False,
        "refresh_preview": False,
        "reason": "",
    }


def test_material_edit_refresh_status_helpers_keep_debounce_messages() -> None:
    assert material_edit_refresh_interval_ms() == 520
    assert source_material_plan_refresh_interval_ms() == 260

    queued = material_edit_refresh_queued_performance("role change")
    assert queued.summary == "Preview update queued: role change."
    assert (
        queued.details
        == "Material edits are debounced so role and slider changes do not rebuild preview per click."
    )
    assert material_edit_refresh_queued_progress_message("role change") == "Preview update queued - role change."

    running = material_edit_refresh_running_performance("slider change")
    assert running.summary == "Refreshing material preview: slider change."
    assert running.details == "Queued material edit is being applied after input settled."
    assert (
        material_edit_refresh_running_progress_message("slider change")
        == "Refreshing material preview - slider change."
    )


def test_source_material_plan_refresh_state_queue_take_cycle() -> None:
    state: dict[str, object] = {"force_plan": False, "reason": ""}

    reason = queue_source_material_plan_refresh_state(
        state,
        force_plan=True,
        reason=" material sliders ",
    )

    assert reason == "material sliders"
    assert state == {"force_plan": True, "reason": "material sliders"}
    assert take_source_material_plan_refresh_state(state) == {
        "force_plan": True,
        "reason": "material sliders",
    }
    assert state == {"force_plan": False, "reason": ""}
