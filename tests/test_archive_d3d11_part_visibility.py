from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Callable

from cdmw.ui.archive_browser.preview_d3d11_parts import ArchivePreviewD3D11PartsMixin
from cdmw.ui.archive_browser.preview_cache import ArchivePreviewCacheMixin


class _FakeSignal:
    def __init__(self) -> None:
        self.callbacks: list[Callable[..., object]] = []

    def connect(self, callback: Callable[..., object]) -> None:
        self.callbacks.append(callback)

    def emit(self, *args: object) -> None:
        for callback in tuple(self.callbacks):
            callback(*args)


class _FakeAction:
    def __init__(self, text: str) -> None:
        self.text = text
        self.checked = False
        self.toggled = _FakeSignal()
        self.triggered = _FakeSignal()

    def setCheckable(self, _checkable: bool) -> None:
        return

    def setChecked(self, checked: bool) -> None:
        changed = self.checked != bool(checked)
        self.checked = bool(checked)
        if changed:
            self.toggled.emit(self.checked)

    def isChecked(self) -> bool:
        return self.checked

    def setToolTip(self, _tooltip: str) -> None:
        return

    def setStatusTip(self, _status_tip: str) -> None:
        return

    def setData(self, _data: object) -> None:
        return


class _FakeMenu:
    def __init__(self) -> None:
        self.actions: list[_FakeAction] = []

    def clear(self) -> None:
        self.actions.clear()

    def addAction(self, text: str) -> _FakeAction:
        action = _FakeAction(text)
        self.actions.append(action)
        return action

    def addSeparator(self) -> None:
        return


class _FakeButton:
    def __init__(self) -> None:
        self.text = ""
        self.enabled = False
        self.visible = False

    def setText(self, text: str) -> None:
        self.text = text

    def setEnabled(self, enabled: bool) -> None:
        self.enabled = bool(enabled)

    def setVisible(self, visible: bool) -> None:
        self.visible = bool(visible)


class _FakePreviewHost:
    def __init__(self, *, accept_commands: bool = True) -> None:
        self.accept_commands = bool(accept_commands)
        self.hidden_source_submeshes: list[list[int]] = []
        self.render_tuning_calls: list[object] = []

    def set_hidden_source_submeshes(self, indices: object) -> bool:
        if not self.accept_commands:
            return False
        self.hidden_source_submeshes.append([int(index) for index in indices])
        return True

    def set_render_tuning(self, settings: object) -> bool:
        if not self.accept_commands:
            return False
        self.render_tuning_calls.append(settings)
        return True


class _PartVisibilityHarness(ArchivePreviewD3D11PartsMixin):
    def __init__(self, *, accept_commands: bool = True) -> None:
        self.archive_d3d11_part_visibility_menu = _FakeMenu()
        self.archive_d3d11_part_visibility_button = _FakeButton()
        self.archive_d3d11_preview_host = _FakePreviewHost(accept_commands=accept_commands)
        self.archive_d3d11_preview_status_label = _FakeButton()
        self.archive_d3d11_part_visibility_actions: dict[int, _FakeAction] = {}
        self.archive_d3d11_part_visibility_groups: dict[str, tuple[object, tuple[int, ...], bool, str]] = {}
        self.archive_d3d11_prefab_component_selections: dict[str, set[str]] = {}
        self.archive_d3d11_part_visibility_bulk_update = False
        self.current_entry = SimpleNamespace(
            path="character/body.pac",
            pamt_path=Path("archive.pamt"),
            offset=128,
        )
        self.refresh_calls: list[bool] = []
        self.archive_isolated_renderer_status_file: Path | None = None
        self.archive_isolated_renderer_status_signature = (0, 0)
        self.archive_isolated_renderer_status_payload_text = ""
        self.archive_isolated_renderer_last_status_payload: dict[str, object] = {}
        self.archive_isolated_renderer_process = None
        self.runtime_events: list[tuple[str, dict[str, object]]] = []
        self.status_messages: list[tuple[str, bool]] = []

    def _record_archive_d3d11_runtime_event(self, event: str, **fields: object) -> None:
        self.runtime_events.append((event, dict(fields)))

    def _archive_qprocess_pid(self, _process: object) -> int:
        return 0

    def _promote_archive_d3d11_pending_package_if_loaded(self, _status_file: Path) -> None:
        return

    def _restore_archive_d3d11_pending_view_state(self) -> bool:
        return True

    def _current_model_preview_render_settings(self) -> object:
        return object()

    def _cleanup_archive_isolated_renderer_packages(self, *, include_active: bool = False) -> None:
        assert include_active is False

    def _set_archive_isolated_renderer_debug(self, _message: str) -> None:
        return

    def _format_archive_isolated_renderer_debug(self, _payload: object) -> str:
        return "loaded"

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.status_messages.append((message, bool(error)))

    def _record_archive_memory_audit(self, _event: str, **_fields: object) -> None:
        return

    def _current_archive_entry(self) -> object:
        return self.current_entry

    def _refresh_current_model_preview_assets(self, *, force: bool = False) -> None:
        self.refresh_calls.append(bool(force))


def _write_part_visibility_package(package_dir: Path, *, include_prefab_batch: bool) -> None:
    package_dir.mkdir()
    batches = [
        {
            "index": 0,
            "editor_identity": {
                "source_submesh_index": 0,
                "part_label": "Body",
                "source_model_path": "character/body.pac",
                "source_component_index": 0,
                "prefab_component": False,
            },
        }
    ]
    if include_prefab_batch:
        batches.append(
            {
                "index": 1,
                "editor_identity": {
                    "source_submesh_index": 1,
                    "part_label": "Underwear",
                    "source_model_path": "character/underwear.pac",
                    "source_component_index": 1,
                    "prefab_component": True,
                },
            }
        )
    (package_dir / "manifest.json").write_text(
        json.dumps(
            {
                "asset_family": {
                    "member_rows": [
                        {
                            "group": "Prefab / Components",
                            "role": "Model Component",
                            "display_name": "Underwear",
                            "path": "character/underwear.pac",
                        }
                    ]
                },
                "batches": batches,
            }
        ),
        encoding="utf-8",
    )


def _prefab_action(harness: _PartVisibilityHarness) -> _FakeAction:
    return next(
        action
        for action, _source_indices, prefab_component, _model_path
        in harness.archive_d3d11_part_visibility_groups.values()
        if prefab_component
    )


def test_archive_preview_loads_prefab_only_after_its_part_is_enabled(tmp_path: Path) -> None:
    package_dir = tmp_path / "preview"
    _write_part_visibility_package(package_dir, include_prefab_batch=False)
    harness = _PartVisibilityHarness()

    harness._populate_archive_d3d11_part_visibility_menu(package_dir)

    assert harness.archive_d3d11_part_visibility_actions[0].isChecked() is True
    prefab_action = _prefab_action(harness)
    assert prefab_action.isChecked() is False
    assert 1 not in harness.archive_d3d11_part_visibility_actions
    assert harness.archive_d3d11_preview_host.hidden_source_submeshes == [[]]
    assert harness.archive_d3d11_part_visibility_button.text == "Parts 1/2"
    assert harness.archive_d3d11_part_visibility_button.enabled is True
    assert harness.archive_d3d11_part_visibility_button.visible is True

    prefab_action.setChecked(True)

    assert harness.archive_d3d11_preview_host.hidden_source_submeshes[-1] == []
    assert harness.archive_d3d11_part_visibility_button.text == "Parts 2/2"
    assert harness._archive_d3d11_enabled_prefab_component_paths() == ("character/underwear.pac",)
    assert harness.refresh_calls == [True]


def test_archive_preview_disabling_loaded_prefab_hides_then_rebuilds(tmp_path: Path) -> None:
    package_dir = tmp_path / "preview"
    _write_part_visibility_package(package_dir, include_prefab_batch=True)
    harness = _PartVisibilityHarness()
    assert harness._set_archive_d3d11_enabled_prefab_component_paths(("character/underwear.pac",))

    harness._populate_archive_d3d11_part_visibility_menu(package_dir)
    prefab_action = _prefab_action(harness)
    assert prefab_action.isChecked() is True
    assert harness.archive_d3d11_preview_host.hidden_source_submeshes == [[]]

    prefab_action.setChecked(False)

    assert harness.archive_d3d11_preview_host.hidden_source_submeshes[-1] == [1]
    assert harness._archive_d3d11_enabled_prefab_component_paths() == ()
    assert harness.refresh_calls == [True]


def test_archive_preview_reapplies_default_prefab_visibility_after_first_renderer_load(tmp_path: Path) -> None:
    package_dir = tmp_path / "preview"
    _write_part_visibility_package(package_dir, include_prefab_batch=True)
    harness = _PartVisibilityHarness(accept_commands=False)
    assert harness._set_archive_d3d11_enabled_prefab_component_paths(("character/underwear.pac",))

    harness._populate_archive_d3d11_part_visibility_menu(package_dir)

    assert _prefab_action(harness).isChecked() is True
    assert harness.archive_d3d11_preview_host.hidden_source_submeshes == []

    harness.archive_d3d11_preview_host.accept_commands = True
    status_file = package_dir / "host_status.json"
    status_file.write_text(json.dumps({"event": "loaded", "batch_count": 2}), encoding="utf-8")
    harness._set_archive_d3d11_hidden_parts_from_menu()

    assert harness.archive_d3d11_preview_host.hidden_source_submeshes == [[]]
    assert harness.archive_d3d11_part_visibility_button.text == "Parts 2/2"


def test_archive_preview_cache_identity_includes_enabled_prefab_paths(tmp_path: Path) -> None:
    class CacheHarness(ArchivePreviewD3D11PartsMixin, ArchivePreviewCacheMixin):
        archive_sidecar_generation = 0

        def __init__(self) -> None:
            self.archive_d3d11_prefab_component_selections: dict[str, set[str]] = {}
            self.entry = SimpleNamespace(
                path="character/body.pac",
                extension=".pac",
                pamt_path=tmp_path / "archive.pamt",
                paz_file=tmp_path / "archive.paz",
                offset=128,
                comp_size=64,
                orig_size=128,
                flags=0,
                paz_index=0,
            )

        def _current_archive_entry(self) -> object:
            return self.entry

        @staticmethod
        def _archive_model_renderer_backend() -> str:
            return "d3d11_native"

        @staticmethod
        def _current_model_preview_render_settings() -> object:
            return SimpleNamespace(
                disable_all_support_maps=False,
                disable_normal_map=False,
                disable_material_map=False,
                disable_height_map=False,
                visible_texture_mode="mesh_base_first",
                preview_texture_max_dimension=2048,
                low_quality_texture_max_dimension=512,
                flip_texture_v=False,
                high_quality_by_default=True,
                use_textures_by_default=True,
            )

    harness = CacheHarness()
    base_key = harness._archive_preview_cache_key(harness.entry, ())
    assert harness._set_archive_d3d11_enabled_prefab_component_paths(("character/underwear.pac",))
    selected_key = harness._archive_preview_cache_key(harness.entry, ())

    assert base_key != selected_key
    assert "prefabs:character/underwear.pac" in selected_key
