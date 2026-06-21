from __future__ import annotations

from cdmw.ui.archive_browser.static_replacement_preview_batch_state import (
    static_preview_batch_begin,
    static_preview_batch_end,
    static_preview_batch_initial_state,
    static_preview_batch_queue_request,
)


def test_static_preview_batch_initial_state_preserves_flags() -> None:
    assert static_preview_batch_initial_state() == {
        "depth": 0,
        "texture": False,
        "texture_uv": False,
        "rebuild": False,
        "refresh": False,
    }


def test_static_preview_batch_queue_request_only_records_inside_batch() -> None:
    state: dict[str, object] = {"depth": 0}

    assert static_preview_batch_queue_request(state, "texture_uv") is False
    assert "texture_uv" not in state

    static_preview_batch_begin(state)

    assert static_preview_batch_queue_request(state, "texture_uv") is True
    assert state["texture_uv"] is True


def test_static_preview_batch_end_returns_outermost_requests_and_resets() -> None:
    state: dict[str, object] = {"depth": 0}

    static_preview_batch_begin(state)
    static_preview_batch_begin(state)
    static_preview_batch_queue_request(state, "texture")

    assert static_preview_batch_end(state) is None

    static_preview_batch_queue_request(state, "rebuild")
    payload = static_preview_batch_end(state)

    assert payload == {
        "texture": True,
        "texture_uv": False,
        "rebuild": True,
        "refresh": False,
    }
    assert state["depth"] == 0
    assert state["texture"] is False
    assert state["texture_uv"] is False
    assert state["rebuild"] is False
    assert state["refresh"] is False
