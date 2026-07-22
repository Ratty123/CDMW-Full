from __future__ import annotations

from pathlib import Path

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
