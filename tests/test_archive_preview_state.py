from __future__ import annotations

from cdmw.ui.archive_browser.preview_state import archive_model_preview_refresh_tooltip


def test_archive_model_preview_refresh_tooltip_preserves_copy() -> None:
    assert (
        archive_model_preview_refresh_tooltip()
        == "Refresh Archive Preview now. Works even while Mesh Replacement Builder is open."
    )
