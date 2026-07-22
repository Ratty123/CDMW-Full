from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.preview_renderer_controls import ArchivePreviewRendererControlsMixin
from cdmw.ui.archive_browser.preview_state import (
    archive_model_initial_view_state,
    archive_model_manifest_source_path,
    archive_model_preview_refresh_tooltip,
)


ROOT = Path(__file__).resolve().parents[1]


def test_archive_model_preview_refresh_tooltip_preserves_copy() -> None:
    assert (
        archive_model_preview_refresh_tooltip()
        == "Refresh Archive Preview now. Works even while Mesh Replacement Builder is open."
    )


def test_archive_model_initial_view_state_is_front_facing_and_centered_by_default() -> None:
    assert archive_model_initial_view_state() == {
        "role": "replacement",
        "reason": "archive_model_initial_front",
        "zoom_factor": 1.0,
        "fit_to_view": True,
        "yaw": 0.0,
        "pitch": 0.0,
        "pan": (0.0, 0.0, 0.0),
    }


def test_archive_model_initial_view_state_uses_overhead_for_weapon_paths_and_names() -> None:
    overhead_paths = (
        "character/model/1_pc/1_phm/weapon/1_longsword/blade.pac",
        "character/model/1_pc/1_phm/subweapon/quiver.pac",
        "character/model/1_pc/1_phm/shield/buckler.pac",
        "character/model/1_pc/1_phm/4_bow/bow.pac",
        "character/model/1_pc/1_phm/twohandweapon/axe.pac",
        "cd_phm_01_sword_0016.pac",
    )
    front_paths = (
        "character/model/1_pc/1_phm/upper/armor.pac",
        "character/model/1_pc/1_phm/lower/trousers.pac",
        "character/model/1_pc/1_phm/hand/gloves.pac",
        "character/model/1_pc/1_phm/foot/boots.pac",
        "cd_pgw_00_head_00_0001.pac",
        "",
    )

    assert all(archive_model_initial_view_state(path)["pitch"] == -89.0 for path in overhead_paths)
    assert all(archive_model_initial_view_state(path)["pitch"] == 0.0 for path in front_paths)


def test_archive_model_manifest_source_path_is_safe_and_bounded(tmp_path: Path) -> None:
    package_dir = tmp_path / "package"
    package_dir.mkdir()
    (package_dir / "manifest.json").write_text(
        '{"source_path":"character/model/weapon/1_longsword/blade.pac"}',
        encoding="utf-8",
    )

    assert archive_model_manifest_source_path(package_dir).endswith("1_longsword/blade.pac")
    (package_dir / "manifest.json").write_text("[]", encoding="utf-8")
    assert archive_model_manifest_source_path(package_dir) == ""


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
    assert "archive_model_initial_view_state(" in source
    assert "initial_view_state=initial_view_state" in source
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
