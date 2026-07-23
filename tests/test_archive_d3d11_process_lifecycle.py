from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cdmw.models import ModelPreviewRenderSettings
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import ArchivePreviewDotNetLifecycleMixin


class _FakeController:
    def __init__(self) -> None:
        self.is_running = True
        self.applied_package_path = ""
        self.clear_count = 0
        self.shutdown_count = 0

    def clear_preview(self) -> bool:
        self.clear_count += 1
        return True

    def shutdown(self) -> None:
        self.shutdown_count += 1


class _FakeHost:
    def __init__(self) -> None:
        self.controller = _FakeController()
        self.clear_count = 0
        self.loads: list[tuple[Path, bool]] = []
        self.tuning: list[object] = []
        self.viewport_modes: list[str] = []
        self.accept_load = True

    def clear_preview(self) -> bool:
        self.clear_count += 1
        return True

    def load_package(self, package: Path, *, reset_view: bool) -> bool:
        self.loads.append((Path(package), bool(reset_view)))
        return self.accept_load

    def set_render_tuning(self, settings: object) -> bool:
        self.tuning.append(settings)
        return True

    def set_viewport_display_mode(self, mode: str) -> bool:
        self.viewport_modes.append(str(mode))
        return True


class _LifecycleHarness(ArchivePreviewDotNetLifecycleMixin):
    def __init__(self) -> None:
        self.archive_d3d11_preview_host = _FakeHost()
        self.archive_isolated_renderer_active_package: Path | None = Path("preview-package")
        self.archive_isolated_renderer_package_source = "dotnet-canonical"
        self._shutting_down = False
        self.messages: list[tuple[str, bool]] = []
        self.render_requests: list[tuple[object, bool]] = []
        self.entry = SimpleNamespace(path="character/body.pac")
        self.settings = ModelPreviewRenderSettings()
        self.archive_preview_request_id = 0
        self.current_archive_preview_result = None
        self.details_refresh_count = 0

    def _current_archive_entry(self) -> object:
        return self.entry

    def _render_archive_preview(self, entry: object, *, force: bool = False) -> None:
        self.render_requests.append((entry, bool(force)))

    def _current_model_preview_render_settings(self) -> object:
        return self.settings

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.messages.append((message, bool(error)))

    def _refresh_archive_preview_details_text(self) -> None:
        self.details_refresh_count += 1


def test_archive_lifecycle_reads_shared_controller_process_state() -> None:
    harness = _LifecycleHarness()

    assert harness._archive_isolated_renderer_process_running() is True
    harness.archive_d3d11_preview_host.controller.is_running = False
    assert harness._archive_isolated_renderer_process_running() is False


def test_resident_scene_failure_keeps_previous_model_visible() -> None:
    harness = _LifecycleHarness()
    harness.archive_d3d11_preview_host.controller.applied_package_path = "resident-package"

    assert harness._preserve_archive_resident_scene_error("replacement package failed") is True

    assert harness.archive_d3d11_preview_host.clear_count == 0
    assert harness.messages[-1] == (
        "Preview update failed; the previous model remains visible: replacement package failed",
        True,
    )


def test_clear_request_never_leaves_previous_package_visible() -> None:
    harness = _LifecycleHarness()

    harness._clear_archive_isolated_renderer_surface_for_request()

    assert harness.archive_d3d11_preview_host.clear_count == 1
    assert harness.archive_isolated_renderer_active_package is None
    assert harness.archive_isolated_renderer_package_source == ""


def test_long_lived_archive_host_clears_normally_and_shuts_down_with_app() -> None:
    harness = _LifecycleHarness()

    harness._shutdown_archive_isolated_renderer_host()
    assert harness.archive_d3d11_preview_host.controller.clear_count == 1
    assert harness.archive_d3d11_preview_host.controller.shutdown_count == 0

    harness.archive_isolated_renderer_active_package = Path("preview-package")
    harness._shutting_down = True
    harness._shutdown_archive_isolated_renderer_host()
    assert harness.archive_d3d11_preview_host.controller.shutdown_count == 1


def test_archive_texture_action_starts_one_latest_wins_texture_request() -> None:
    harness = _LifecycleHarness()

    harness._open_archive_isolated_d3d11_preview()

    assert harness.render_requests == [(harness.entry, True)]
    assert harness._archive_texture_request_id == 1
    assert harness._archive_texture_request_loading is True
    harness._open_archive_isolated_d3d11_preview()
    assert harness.render_requests == [(harness.entry, True)]


def test_archive_texture_action_hides_and_shows_loaded_textures_without_package_reload(tmp_path: Path) -> None:
    package = tmp_path / "textured-package"
    package.mkdir()
    (package / "net_materials.json").write_text(
        json.dumps({"resources": [{"resource_id": "texture:base", "path": "base.dds"}]}),
        encoding="utf-8",
    )
    harness = _LifecycleHarness()
    harness.archive_isolated_renderer_active_package = package
    harness._archive_textures_visible = True

    harness._open_archive_isolated_d3d11_preview()
    harness._open_archive_isolated_d3d11_preview()

    assert harness.archive_d3d11_preview_host.loads == []
    assert harness.archive_d3d11_preview_host.viewport_modes == ["untextured_wire", "textured"]
    assert harness._archive_textures_visible is True


def test_resident_texture_failure_preserves_existing_scene_and_clears_request(tmp_path: Path) -> None:
    old_package = tmp_path / "geometry"
    old_package.mkdir()
    (old_package / "net_materials.json").write_text('{"resources":[]}', encoding="utf-8")
    harness = _LifecycleHarness()
    harness.archive_isolated_renderer_active_package = old_package
    harness.current_archive_preview_result = "geometry-result"
    harness._archive_texture_request_id = 4
    harness._archive_texture_request_loading = True
    harness._archive_texture_package_generation = 7
    harness._archive_texture_package_path = str(tmp_path / "textured")
    harness._archive_pending_texture_result = "textured-result"

    harness._handle_archive_resident_package_failed(str(tmp_path / "textured"), 7, "DDS decode failed")

    assert harness.archive_isolated_renderer_active_package == old_package
    assert harness.current_archive_preview_result == "geometry-result"
    assert harness._archive_texture_request_loading is False
    assert harness.messages[-1][1] is True


def test_resident_texture_apply_commits_latest_generation_once(tmp_path: Path) -> None:
    package = tmp_path / "textured"
    package.mkdir()
    (package / "net_materials.json").write_text(
        json.dumps({"resources": [{"resource_id": "texture:base", "path": "base.dds"}]}),
        encoding="utf-8",
    )
    harness = _LifecycleHarness()
    harness._archive_texture_request_id = 5
    harness._archive_texture_request_loading = True
    harness._archive_texture_package_generation = 9
    harness._archive_texture_package_path = str(package)
    harness._archive_texture_render_settings = ModelPreviewRenderSettings(use_textures_by_default=True)
    harness._archive_pending_texture_result = "textured-result"

    harness._handle_archive_resident_package_applied(str(package), 8)
    assert harness._archive_texture_request_loading is True
    harness._handle_archive_resident_package_applied(str(package), 9)

    assert harness.archive_isolated_renderer_active_package == package
    assert harness.current_archive_preview_result == "textured-result"
    assert harness._archive_texture_request_loading is False
    assert len(harness.archive_d3d11_preview_host.tuning) == 1
    assert harness.archive_d3d11_preview_host.viewport_modes == ["textured"]


def test_reload_without_package_requests_canonical_preparation() -> None:
    harness = _LifecycleHarness()
    harness.archive_isolated_renderer_active_package = None

    harness._open_archive_isolated_d3d11_preview()

    assert harness.render_requests == [(harness.entry, True)]


def test_material_debug_reads_canonical_net_materials(tmp_path: Path) -> None:
    package = tmp_path / "package"
    package.mkdir()
    (package / "net_materials.json").write_text(
        json.dumps(
            {
                "submeshes": [
                    {
                        "material_name": "Armor",
                        "packaged_channels": {"base_color": "armor.dds", "normal": ""},
                    }
                ]
            }
        ),
        encoding="utf-8",
    )
    harness = _LifecycleHarness()

    detail = harness._archive_material_channel_debug_from_package(package)

    assert detail == "Material Authority: part 0 Armor: base_color"
