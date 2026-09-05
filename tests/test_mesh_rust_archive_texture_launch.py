from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from cdmw.models import ArchiveEntry
from cdmw.services.mesh_rust_contract import RUST_PREVIEW_PACKAGE
from cdmw.workers.mesh_editor_aux_workers import MeshArchiveMaterialContextWorker
from cdmw.ui.archive_browser.preview_dotnet_lifecycle import (
    ArchivePreviewDotNetLifecycleMixin,
)
from cdmw.ui.mesh_editor.shell_bridge import MeshEditorShellBridgeMixin


def _entry(
    tmp_path: Path,
    name: str = "body.pac",
    *,
    offset: int = 0,
    package: str = "0009",
    paz_index: int = 0,
) -> ArchiveEntry:
    return ArchiveEntry(
        path=f"character/model/{name}",
        pamt_path=tmp_path / package / "0.pamt",
        paz_file=tmp_path / package / "0.paz",
        offset=offset,
        comp_size=4,
        orig_size=4,
        flags=0,
        paz_index=paz_index,
    )


def _package(root: Path, entry: ArchiveEntry, *, textured: bool) -> Path:
    root.mkdir()
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "source_path": entry.path,
                "source_identity": {
                    "normalized_path": entry.identity.normalized_path,
                    "source_pamt": entry.identity.source_pamt,
                    "paz_index": entry.identity.paz_index,
                    "entry_offset": entry.identity.entry_offset,
                },
                "batches": [{"index": 0}],
            }
        ),
        encoding="utf-8",
    )
    (root / "net_materials.json").write_text(
        json.dumps(
            {
                "resources": (
                    [{"resource_id": "texture:base", "path": "body.dds"}]
                    if textured
                    else []
                )
            }
        ),
        encoding="utf-8",
    )
    return root


def _compiled_vortice_package(root: Path, entry: ArchiveEntry) -> Path:
    root.mkdir()
    material_signature = "compiled-material-signature"
    archive_identity = "::".join(
        (
            entry.path.casefold(),
            str(entry.pamt_path).casefold(),
            "pamt-stamp",
            str(entry.paz_file).casefold(),
            "paz-stamp",
            "",
            "quality:full",
            str(entry.offset),
            str(entry.comp_size),
            str(entry.orig_size),
            str(entry.flags),
            str(entry.paz_index),
            "renderer:d3d11",
        )
    )
    (root.parent / "cache_entry.json").write_text(
        json.dumps({"schema": 1, "archive_identity": archive_identity}),
        encoding="utf-8",
    )
    (root / "dotnet_launch.json").write_text(
        json.dumps(
            {
                "format": "cdmw_mesh_dotnet_experiment_handoff_v1",
                "input": {
                    "mesh": "mesh.obj",
                    "materials": "net_materials.json",
                    "scene_state": "dotnet_scene.json",
                    "material_signature": material_signature,
                },
            }
        ),
        encoding="utf-8",
    )
    (root / "dotnet_scene.json").write_text(
        json.dumps(
            {
                "format": "cdmw_resident_scene_frame_v2",
                "renderer_authority": "dotnet_vortice_resident_scene",
                "source_identity": "compiled-geometry-identity",
            }
        ),
        encoding="utf-8",
    )
    (root / "net_materials.json").write_text(
        json.dumps(
            {
                "format": "cdmw_mesh_dotnet_materials_v1",
                "renderer_authority": "dotnet_mesh_editor",
                "source_mesh": entry.path,
                "material_signature": material_signature,
                "resources": [{"resource_id": "texture:base", "path": "body.dds"}],
            }
        ),
        encoding="utf-8",
    )
    return root


def _canonical_rust_package(root: Path, entry: ArchiveEntry) -> tuple[Path, Path]:
    native = root / "native-entry" / "package"
    native.mkdir(parents=True)
    texture = native / "body.dds"
    texture.write_bytes(b"DDS " + b"owned body texture" * 8)
    (native / "manifest.json").write_text(json.dumps({
        "source_path": entry.path,
        "material_graph_version": 4,
        "batches": [{
            "editor_identity": {"source_local_submesh_index": 0},
            "material_layers": [{"layer_role": "base", "tint": [0.8, 0.4, 0.2, 1]}],
            "dds_textures": {
                "base": {"source_path": str(texture)},
                "material_inputs": [{
                    "source_path": str(texture), "slot": "base",
                    "semantic_type": "color", "semantic_subtype": "albedo",
                    "parameter_name": "_baseColorTexture", "owner_slot_index": 0,
                    "material_parameters": [{
                        "parameter_name": "_skinDetailScale", "parameter_kind": "float",
                        "numeric_value": 0.032,
                    }],
                }],
            },
        }],
    }), encoding="utf-8")
    (native.parent / "cache_entry.json").write_text(json.dumps({
        "cache_key": "native-key",
        "diagnostics": {"cache_dependency_entries": [{
            "path": entry.path, "pamt_path": str(entry.pamt_path),
            "paz_file": str(entry.paz_file), "paz_index": entry.paz_index,
            "offset": entry.offset,
        }]},
    }), encoding="utf-8")
    rust = root / "rust-entry" / "package"
    rust.mkdir(parents=True)
    (rust / "manifest.json").write_text(json.dumps({
        "schema": RUST_PREVIEW_PACKAGE, "source": {"path": entry.path},
        "textures": [{"role": "base_color", "file": {"path": "body.dds"}}],
    }), encoding="utf-8")
    (rust.parent / "cache_entry.json").write_text(json.dumps({
        "archive_identity": "native-key", "source_package": str(native),
    }), encoding="utf-8")
    return rust, native


class _Lease:
    def __init__(self) -> None:
        self.active = True

    def release(self) -> None:
        self.active = False


class _Tab:
    def __init__(self, backend: str, opened: list[tuple[object, dict[str, object]]]) -> None:
        self.backend = backend
        self.opened = opened

    def _selected_mesh_editor_backend(self) -> str:
        return self.backend

    def open_archive_session(self, entry: ArchiveEntry, **kwargs: object) -> None:
        self.opened.append((entry, kwargs))


class _LaunchHarness(MeshEditorShellBridgeMixin):
    def __init__(
        self,
        entry: ArchiveEntry,
        geometry_package: Path,
        *,
        backend: str = "rust",
    ) -> None:
        self.entry = entry
        self.backend = backend
        self.archive_isolated_renderer_active_package = geometry_package
        self.current_archive_preview_result = SimpleNamespace(
            preview_model="geometry-model",
            dotnet_preview_package_path=str(geometry_package),
        )
        self.opened: list[tuple[object, dict[str, object]]] = []
        self.mesh_editor_tab = _Tab(backend, self.opened)
        self.texture_requests: list[bool] = []
        self.statuses: list[tuple[str, bool]] = []
        self._archive_texture_request_id = 0
        self._archive_texture_request_loading = False
        self._shutting_down = False

    def _current_archive_entry(self) -> ArchiveEntry:
        return self.entry

    def _archive_active_package_has_textures(self) -> bool:
        package = Path(self.archive_isolated_renderer_active_package)
        manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8")) if (package / "manifest.json").is_file() else {}
        if manifest.get("schema") == RUST_PREVIEW_PACKAGE:
            return bool(manifest.get("textures"))
        payload = json.loads((package / "net_materials.json").read_text(encoding="utf-8"))
        return bool(payload.get("resources"))

    def _request_archive_preview_textures(self, *, automatic: bool = False) -> bool:
        self.texture_requests.append(bool(automatic))
        self._archive_texture_request_id = 41
        self._archive_texture_request_loading = True
        return True

    @staticmethod
    def _prepare_mesh_editor_archive_launch(_entry: ArchiveEntry) -> bool:
        return True

    @staticmethod
    def _find_archive_preview_companion_entry(_entry: ArchiveEntry) -> None:
        return None

    @staticmethod
    def _strip_archive_preview_heavy_payloads_for_mesh_editor(_entry: ArchiveEntry) -> None:
        pass

    @staticmethod
    def _activate_tool_widget(_widget: object) -> None:
        pass

    def set_status_message(self, message: str, *, error: bool = False) -> None:
        self.statuses.append((str(message), bool(error)))


def test_rust_preview_handoff_leases_its_exact_native_material_source(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    rust, native = _canonical_rust_package(tmp_path, entry)
    harness = _LaunchHarness(entry, rust)
    harness.current_archive_preview_result.preview_model = None
    lease = _Lease()
    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=lease,
    ) as acquire:
        harness._launch_archive_mesh_editor_for_entry(entry)
    assert harness.texture_requests == []
    acquire.assert_called_once_with(native)
    assert harness.opened[0][1]["material_package_path"] == str(native)
    assert harness.opened[0][1]["material_package_lease"] is lease


@pytest.mark.parametrize("mismatch", ["archive", "cache_key", "source_path", "missing"])
def test_rust_preview_handoff_rejects_unrelated_or_missing_material_source(
    tmp_path: Path, mismatch: str,
) -> None:
    entry = _entry(tmp_path)
    rust, native = _canonical_rust_package(tmp_path, entry)
    if mismatch == "archive":
        entry = _entry(tmp_path, offset=99, package="0010")
    elif mismatch == "cache_key":
        path = rust.parent / "cache_entry.json"
        payload = json.loads(path.read_text())
        payload["archive_identity"] = "other-key"
        path.write_text(json.dumps(payload))
    elif mismatch == "source_path":
        path = rust / "manifest.json"
        payload = json.loads(path.read_text())
        payload["source"]["path"] = "another.pac"
        path.write_text(json.dumps(payload))
    else:
        (native / "manifest.json").unlink()
    assert _LaunchHarness(entry, rust)._mesh_editor_active_textured_package_for_entry(entry) is None


@pytest.mark.parametrize("cancel", [False, True])
def test_current_rust_archive_material_context_preserves_full_graph_and_lease(
    tmp_path: Path, cancel: bool,
) -> None:
    entry = _entry(tmp_path)
    rust, native = _canonical_rust_package(tmp_path, entry)
    worker = MeshArchiveMaterialContextWorker(7, entry, material_package_path=rust)
    contexts, errors = [], []
    worker.context_resolved.connect(lambda _request, context: contexts.append(context))
    worker.error.connect(lambda _request, message: errors.append(message))
    lease = _Lease()
    decode = worker._native_package_material_model

    def decode_and_optionally_cancel():
        result = decode()
        if cancel:
            worker.stop()
        return result

    with patch.object(worker, "_native_package_material_model", side_effect=decode_and_optionally_cancel), patch(
        "cdmw.workers.mesh_editor_aux_workers.build_archive_preview_result",
        side_effect=AssertionError("Current native material graph must not be discarded and re-resolved"),
    ), patch(
        "cdmw.workers.mesh_editor_aux_workers.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=lease,
    ):
        worker.run()
    assert errors == []
    if cancel:
        assert contexts == []
        assert not lease.active
        return
    assert len(contexts) == 1
    context = contexts[0]
    assert context.material_package_path == str(native)
    assert context.material_package_lease is lease
    part = context.preview_model.meshes[0]
    assert Path(part.preview_texture_dds_path).read_bytes().startswith(b"DDS ")
    assert part.preview_material_texture_inputs[0].material_parameters[0].numeric_value == 0.032
    assert part.preview_native_material_overrides["material_layers"][0]["tint"] == [0.8, 0.4, 0.2, 1]
    context.release()
    assert not lease.active


def test_missing_rust_blocks_before_archive_texture_resolution(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    geometry = _package(tmp_path / "geometry", entry, textured=False)
    harness = _LaunchHarness(entry, geometry)
    syncs: list[bool] = []
    harness.mesh_editor_tab._rust_open_preflight_reason = (  # type: ignore[attr-defined]
        lambda: "the bundled editor was not found"
    )
    harness.mesh_editor_tab._sync_mesh_editor_backend_controls = (  # type: ignore[attr-defined]
        lambda: syncs.append(True)
    )

    harness._launch_archive_mesh_editor_for_entry(entry)

    assert syncs == [True]
    assert harness.texture_requests == []
    assert harness.opened == []
    assert harness.statuses[-1] == (
        "Mesh Editor cannot open: the bundled editor was not found.",
        True,
    )


def test_rust_launch_waits_for_and_leases_the_exact_textured_package(tmp_path: Path) -> None:
    entry = _entry(tmp_path)
    geometry = _package(tmp_path / "geometry", entry, textured=False)
    textured = _package(tmp_path / "textured", entry, textured=True)
    harness = _LaunchHarness(entry, geometry)
    lease = _Lease()

    harness._launch_archive_mesh_editor_for_entry(entry)

    assert harness.opened == []
    assert harness.texture_requests == [True]
    pending = harness._mesh_editor_pending_rust_texture_launch
    assert pending["entry"] is not entry
    assert pending["entry"].identity == entry.identity
    assert harness.statuses[-1][0] == (
        "Resolving this mesh's textures before Mesh Editor opens..."
    )

    harness.archive_isolated_renderer_active_package = textured
    harness.current_archive_preview_result = SimpleNamespace(
        preview_model="textured-archive-model",
        dotnet_preview_package_path=str(textured),
    )
    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=lease,
    ):
        harness._finish_pending_rust_mesh_editor_texture_launch(
            request_id=41,
            success=True,
        )

    assert len(harness.opened) == 1
    opened_entry, kwargs = harness.opened[0]
    assert opened_entry.identity == entry.identity
    assert kwargs["material_preview_model"] == "textured-archive-model"
    assert kwargs["material_package_path"] == str(textured)
    assert kwargs["material_package_lease"] is lease
    assert kwargs["material_context_verified_for_rust"] is True
    assert kwargs["material_source_identity"] == entry.identity


def test_rust_texture_completion_is_dropped_after_archive_selection_changes(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    geometry = _package(tmp_path / "geometry", entry, textured=False)
    harness = _LaunchHarness(entry, geometry)
    harness._launch_archive_mesh_editor_for_entry(entry)

    harness.entry = _entry(tmp_path, "other.pac", offset=8)
    harness._finish_pending_rust_mesh_editor_texture_launch(
        request_id=41,
        success=False,
        message="stale result",
    )

    assert harness.opened == []
    assert harness._mesh_editor_pending_rust_texture_launch is None


def test_rust_texture_failure_opens_untextured_once_without_recursive_request(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    geometry = _package(tmp_path / "geometry", entry, textured=False)
    harness = _LaunchHarness(entry, geometry)
    lease = _Lease()
    harness._launch_archive_mesh_editor_for_entry(entry)

    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=lease,
    ):
        harness._finish_pending_rust_mesh_editor_texture_launch(
            request_id=41,
            success=False,
            message="no matching DDS",
        )

    assert harness.texture_requests == [True]
    assert len(harness.opened) == 1
    assert harness.opened[0][1]["material_preview_model"] == "geometry-model"
    assert harness.opened[0][1]["material_package_path"] == str(geometry)
    assert harness.mesh_editor_tab.standalone_rust_texture_unavailable_reason == (
        "no matching DDS"
    )
    assert harness.statuses[-1] == (
        "Texture loading failed; the untextured model remains available: no matching DDS",
        True,
    )


def test_retired_vortice_preference_cannot_bypass_rust_texture_handoff(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    geometry = _package(tmp_path / "geometry", entry, textured=False)
    harness = _LaunchHarness(entry, geometry, backend="vortice")

    harness._launch_archive_mesh_editor_for_entry(entry)

    assert harness.texture_requests == [True]
    assert harness.opened == []
    assert harness._mesh_editor_pending_rust_texture_launch is not None


def test_texture_lifecycle_queues_mesh_editor_notification_after_resident_publication(
    tmp_path: Path,
) -> None:
    callbacks: list[object] = []
    entry = _entry(tmp_path)
    textured = _package(tmp_path / "textured", entry, textured=True)
    pending_result = object()

    class Harness(ArchivePreviewDotNetLifecycleMixin):
        _archive_texture_request_id = 73
        _archive_texture_request_loading = True
        _archive_texture_request_automatic = False
        _archive_texture_package_generation = 9
        _archive_texture_package_path = str(textured)
        _archive_texture_render_settings = None
        _archive_pending_texture_result = pending_result
        archive_isolated_renderer_active_package = None
        archive_d3d11_preview_host = None

        def __init__(self) -> None:
            self.notifications: list[tuple[int, bool, str, object]] = []
            self.current_archive_preview_result = None

        def _archive_active_package_has_textures(self) -> bool:
            payload = json.loads(
                (
                    Path(self.archive_isolated_renderer_active_package)
                    / "net_materials.json"
                ).read_text(encoding="utf-8")
            )
            return bool(payload.get("resources"))

        @staticmethod
        def _sync_archive_texture_action_state() -> None:
            pass

        @staticmethod
        def _schedule_archive_texture_request_retry(_automatic: bool) -> None:
            pass

        @staticmethod
        def _populate_archive_d3d11_part_visibility_menu(_package: Path) -> None:
            pass

        @staticmethod
        def _current_model_preview_render_settings() -> object:
            return SimpleNamespace(use_textures_by_default=True)

        @staticmethod
        def _refresh_archive_preview_details_text() -> None:
            pass

        @staticmethod
        def set_status_message(_message: str, *, error: bool = False) -> None:
            del error

        def _finish_pending_rust_mesh_editor_texture_launch(
            self,
            *,
            request_id: int,
            success: bool,
            message: str,
        ) -> None:
            self.notifications.append(
                (request_id, success, message, self.current_archive_preview_result)
            )

    harness = Harness()
    with patch(
        "cdmw.ui.archive_browser.preview_dotnet_lifecycle.QTimer.singleShot",
        side_effect=lambda _delay, callback: callbacks.append(callback),
    ):
        harness._handle_archive_resident_package_applied(str(textured), 9)

    assert harness.notifications == []
    assert harness.current_archive_preview_result is pending_result
    assert len(callbacks) == 1
    callbacks[0]()
    assert harness.notifications == [(73, True, "", pending_result)]


def test_active_texture_package_rejects_mismatched_declared_source_identity(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    package = _package(tmp_path / "textured", entry, textured=True)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest["source_identity"] = {
        "normalized_path": "character/model/another.pac",
        "source_pamt": entry.identity.source_pamt,
        "paz_index": entry.identity.paz_index,
        "entry_offset": entry.identity.entry_offset,
    }
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    harness = _LaunchHarness(entry, package)

    assert harness._mesh_editor_active_textured_package_for_entry(entry) is None


def test_active_texture_package_rejects_path_only_manifest_without_cache_identity(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    package = _package(tmp_path / "textured", entry, textured=True)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("source_identity")
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    harness = _LaunchHarness(entry, package)

    assert harness._mesh_editor_active_textured_package_for_entry(entry) is None


def test_active_texture_package_accepts_path_only_manifest_with_exact_cache_dependency(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    package = _package(tmp_path / "textured", entry, textured=True)
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    manifest.pop("source_identity")
    (package / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (package.parent / "cache_entry.json").write_text(
        json.dumps(
            {
                "diagnostics": {
                    "cache_dependency_entries": [
                        {
                            "path": entry.path,
                            "pamt_path": str(entry.pamt_path),
                            "paz_file": str(entry.paz_file),
                            "paz_index": entry.paz_index,
                            "offset": entry.offset,
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    harness = _LaunchHarness(entry, package)

    assert harness._mesh_editor_active_textured_package_for_entry(entry) == package

    same_path_other_archive = _entry(
        tmp_path,
        package="0010",
        offset=8,
        paz_index=1,
    )
    assert harness._mesh_editor_active_textured_package_for_entry(same_path_other_archive) is None


def test_active_texture_package_accepts_exact_compiled_vortice_package_without_manifest(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    package = _compiled_vortice_package(tmp_path / "compiled", entry)
    harness = _LaunchHarness(entry, package)

    assert not (package / "manifest.json").exists()
    assert harness._mesh_editor_active_textured_package_for_entry(entry) == package

    wrong_entry = _entry(tmp_path, "other.pac", offset=8)
    assert harness._mesh_editor_active_textured_package_for_entry(wrong_entry) is None

    same_path_other_archive = _entry(
        tmp_path,
        package="0010",
        offset=8,
        paz_index=1,
    )
    assert (
        harness._mesh_editor_active_textured_package_for_entry(same_path_other_archive)
        is None
    )

    (package.parent / "cache_entry.json").unlink()
    assert harness._mesh_editor_active_textured_package_for_entry(entry) is None


def test_idle_rust_relaunch_refreshes_material_context_from_active_package(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    textured = _package(tmp_path / "textured", entry, textured=True)
    controller = SimpleNamespace(active_session_id="preserved")
    old_lease = _Lease()
    new_lease = _Lease()

    class Tab(_Tab):
        standalone_controller = controller

        def __init__(self) -> None:
            super().__init__("rust", [])
            self.launched: list[object] = []
            self.archive_material_context_package_lease = old_lease
            self.archive_material_context_package_path = "old-package"
            self.standalone_archive_material_preview_model = object()
            self.archive_material_context_verified_for_rust = True
            self.archive_material_context_source_identity = entry.identity
            self.standalone_rust_texture_unavailable_reason = "old failure"

        @staticmethod
        def active_builder() -> None:
            return None

        @staticmethod
        def has_active_standalone_session() -> bool:
            return True

        @staticmethod
        def _current_target_entry() -> ArchiveEntry:
            return entry

        @staticmethod
        def _rust_editor_task_active() -> bool:
            return False

        @staticmethod
        def _archive_material_preview_model_ready(_preview_model: object) -> bool:
            return True

        def _start_selected_mesh_editor(self, active_controller: object) -> None:
            self.launched.append(active_controller)

        def _replace_archive_material_context_package_lease(self, lease: object) -> None:
            self.archive_material_context_package_lease.release()
            self.archive_material_context_package_lease = lease

    class Harness(MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            self.mesh_editor_tab = Tab()
            self.archive_isolated_renderer_active_package = textured
            self._modeless_alignment_dialogs = {}

        @staticmethod
        def _archive_active_package_has_textures() -> bool:
            return True

        @staticmethod
        def _activate_tool_widget(_widget: object) -> None:
            pass

        @staticmethod
        def set_status_message(_message: str, **_kwargs: object) -> None:
            pass

    harness = Harness()
    with patch(
        "cdmw.ui.mesh_editor.shell_bridge.acquire_dotnet_preview_package_cache_lease_for_path",
        return_value=new_lease,
    ):
        assert harness._prepare_mesh_editor_archive_launch(entry) is False

    tab = harness.mesh_editor_tab
    assert tab.launched == [controller]
    assert not old_lease.active
    assert tab.archive_material_context_package_lease is new_lease
    assert tab.archive_material_context_package_path == str(textured)
    assert tab.standalone_archive_material_preview_model is not None
    assert tab.archive_material_context_verified_for_rust
    assert tab.standalone_rust_texture_unavailable_reason == ""


def test_idle_rust_relaunch_rejects_same_path_materials_from_another_archive(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    stale_entry = _entry(tmp_path, package="0010", offset=8, paz_index=1)
    textured = _package(tmp_path / "textured", entry, textured=True)

    class Tab(_Tab):
        def __init__(self) -> None:
            super().__init__("rust", [])
            self.archive_material_context_source_identity = stale_entry.identity
            self.archive_material_context_verified_for_rust = True

        @staticmethod
        def _replace_archive_material_context_package_lease(_lease: object) -> None:
            raise AssertionError("a stale material identity must not acquire a lease")

    class Harness(MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            self.mesh_editor_tab = Tab()
            self.archive_isolated_renderer_active_package = textured

        @staticmethod
        def _archive_active_package_has_textures() -> bool:
            return True

    harness = Harness()

    assert not harness._refresh_active_rust_material_context_from_archive(entry)
    assert not harness.mesh_editor_tab.archive_material_context_verified_for_rust


def test_rust_relaunch_requested_during_dispose_is_queued_once(
    tmp_path: Path,
) -> None:
    entry = _entry(tmp_path)
    controller = SimpleNamespace(active_session_id="preserved")

    class Tab(_Tab):
        standalone_controller = controller

        def __init__(self) -> None:
            super().__init__("rust", [])
            self.queued: list[object] = []
            self.launched: list[object] = []

        @staticmethod
        def active_builder() -> None:
            return None

        @staticmethod
        def has_active_standalone_session() -> bool:
            return True

        @staticmethod
        def _current_target_entry() -> ArchiveEntry:
            return entry

        @staticmethod
        def _rust_editor_task_active() -> bool:
            return True

        def _queue_rust_relaunch_after_dispose(self, active_controller: object) -> bool:
            if not self.queued:
                self.queued.append(active_controller)
            return True

        def _start_selected_mesh_editor(self, active_controller: object) -> None:
            self.launched.append(active_controller)

    class Harness(MeshEditorShellBridgeMixin):
        def __init__(self) -> None:
            self.mesh_editor_tab = Tab()
            self._modeless_alignment_dialogs = {}
            self.statuses: list[str] = []

        @staticmethod
        def _activate_tool_widget(_widget: object) -> None:
            pass

        def set_status_message(self, message: str, **_kwargs: object) -> None:
            self.statuses.append(message)

    harness = Harness()

    assert harness._prepare_mesh_editor_archive_launch(entry) is False
    assert harness.mesh_editor_tab.queued == [controller]
    assert harness.mesh_editor_tab.launched == []
    assert harness.statuses[-1] == "Launching Mesh Editor..."
