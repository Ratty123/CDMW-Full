from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from cdmw.ui.archive_browser.preview_dotnet_lifecycle import ArchivePreviewDotNetLifecycleMixin


class _FakeController:
    def __init__(self) -> None:
        self.is_running = True
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


class _LifecycleHarness(ArchivePreviewDotNetLifecycleMixin):
    def __init__(self) -> None:
        self.archive_d3d11_preview_host = _FakeHost()
        self.archive_isolated_renderer_active_package: Path | None = Path("preview-package")
        self.archive_isolated_renderer_package_source = "dotnet-canonical"
        self._shutting_down = False
        self.messages: list[tuple[str, bool]] = []
        self.render_requests: list[tuple[object, bool]] = []
        self.entry = SimpleNamespace(path="character/body.pac")
        self.settings = object()

    def _current_archive_entry(self) -> object:
        return self.entry

    def _render_archive_preview(self, entry: object, *, force: bool = False) -> None:
        self.render_requests.append((entry, bool(force)))

    def _current_model_preview_render_settings(self) -> object:
        return self.settings

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.messages.append((message, bool(error)))


def test_archive_lifecycle_reads_shared_controller_process_state() -> None:
    harness = _LifecycleHarness()

    assert harness._archive_isolated_renderer_process_running() is True
    harness.archive_d3d11_preview_host.controller.is_running = False
    assert harness._archive_isolated_renderer_process_running() is False


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


def test_compatibility_reload_uses_resident_vortice_package() -> None:
    harness = _LifecycleHarness()

    harness._open_archive_isolated_d3d11_preview()

    assert harness.archive_d3d11_preview_host.loads == [(Path("preview-package"), False)]
    assert harness.archive_d3d11_preview_host.tuning == [harness.settings]
    assert harness.messages[-1] == ("Reloaded .NET/Vortice Preview.", False)


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
