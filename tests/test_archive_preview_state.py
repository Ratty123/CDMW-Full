from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.preview_renderer_controls import ArchivePreviewRendererControlsMixin
from cdmw.ui.archive_browser.preview_state import archive_model_preview_refresh_tooltip


ROOT = Path(__file__).resolve().parents[1]


def test_archive_model_preview_refresh_tooltip_preserves_copy() -> None:
    assert (
        archive_model_preview_refresh_tooltip()
        == "Refresh Archive Preview now. Works even while Mesh Replacement Builder is open."
    )


def test_archive_model_view_is_restored_by_the_shared_vortice_host() -> None:
    host_source = (ROOT / "cdmw/ui/preview/dotnet_host.py").read_text(encoding="utf-8")
    controller_source = (ROOT / "cdmw/ui/preview/dotnet_session.py").read_text(encoding="utf-8")

    assert "def restore_view_state(" in host_source
    assert '"absolute_camera_state_v1"' in controller_source
    assert '"view_state_changed_v1"' in controller_source
    assert '"presentation"' in controller_source


def test_archive_warm_selection_keeps_view_for_same_resident_package() -> None:
    source = (ROOT / "cdmw/ui/archive_browser/preview_result.py").read_text(encoding="utf-8")

    assert "same_model = package_dir ==" in source
    assert "reset_view=not same_model" in source
    assert "self.archive_d3d11_preview_host.clear_preview()" in source


def test_non_model_preview_clears_shared_host_without_retired_worker_state() -> None:
    paused: list[bool] = []
    cleared: list[bool] = []

    class Harness(ArchivePreviewRendererControlsMixin):
        def __init__(self) -> None:
            self.archive_model_preview = SimpleNamespace(
                pause_interactive_timers=lambda: paused.append(True)
            )
            self.archive_d3d11_preview_host = SimpleNamespace(
                clear_preview=lambda: cleared.append(True)
            )
            self.archive_isolated_renderer_active_package = Path("preview-package")

    harness = Harness()
    harness._deactivate_archive_model_renderers_for_non_model_preview()

    assert paused == [True]
    assert cleared == [True]
    assert harness.archive_isolated_renderer_active_package is None
    assert not hasattr(harness, "archive_isolated_package_request_id")
