from __future__ import annotations

from types import SimpleNamespace

from cdmw.ui.archive_browser.preview_d3d11_runtime import (
    ArchivePreviewD3D11RuntimeMixin,
    archive_model_initial_view_state,
)
from cdmw.ui.archive_browser.preview_state import archive_model_preview_refresh_tooltip


def test_archive_model_preview_refresh_tooltip_preserves_copy() -> None:
    assert (
        archive_model_preview_refresh_tooltip()
        == "Refresh Archive Preview now. Works even while Mesh Replacement Builder is open."
    )


def test_archive_model_initial_view_state_is_overhead_and_fitted() -> None:
    assert archive_model_initial_view_state() == {
        "role": "replacement",
        "reason": "archive_model_initial_overhead",
        "zoom_factor": 1.0,
        "fit_to_view": True,
        "yaw": 0.0,
        "pitch": -89.0,
        "pan": (0.0, 0.0, 0.0),
    }


def test_archive_model_pending_view_state_clears_only_after_restore() -> None:
    restored_states: list[dict[str, object]] = []

    class _Host:
        restore_succeeds = False

        def restore_view_state(self, state: object) -> bool:
            restored_states.append(dict(state))
            return self.restore_succeeds

    host = _Host()
    runtime = SimpleNamespace(
        archive_d3d11_pending_view_state=archive_model_initial_view_state(),
        archive_d3d11_preview_host=host,
    )

    assert not ArchivePreviewD3D11RuntimeMixin._restore_archive_d3d11_pending_view_state(runtime)
    assert runtime.archive_d3d11_pending_view_state == archive_model_initial_view_state()

    host.restore_succeeds = True
    assert ArchivePreviewD3D11RuntimeMixin._restore_archive_d3d11_pending_view_state(runtime)
    assert restored_states == [archive_model_initial_view_state(), archive_model_initial_view_state()]
    assert runtime.archive_d3d11_pending_view_state == {}
