from __future__ import annotations

from pathlib import Path
import unittest

from tests.mesh_editor_source_support import mesh_editor_tab_source
from tests.native_source_text import d3d11_preview_source
from tests.source_function_map import function_source
from tests.static_replacement_source_support import (
    static_replacement_callback_factory_source,
    static_replacement_mesh_edit_implementation_source,
    static_replacement_remaining_callback_source,
    static_replacement_routing_callback_source,
    static_replacement_source_part_mutation_callback_source,
    static_replacement_texture_callback_source,
    static_replacement_ui_section_source,
)


ROOT = Path(__file__).resolve().parents[1]

def _native_mesh_core_source() -> str:
    source_root = ROOT / "native" / "cdmw_mesh_core" / "src"
    cmake = (source_root.parent / "CMakeLists.txt").read_text(encoding="utf-8")
    owner_block = cmake.split("set(MESH_CORE_OWNER_SOURCES", 1)[1].split("\n)", 1)[0]
    owners = (
        (source_root.parent / relative.strip()).read_text(encoding="utf-8")
        for relative in owner_block.splitlines()
        if relative.strip().startswith("src/owners/")
    )
    return "\n".join(
        (
            (source_root / "mesh_core_internal.hpp").read_text(encoding="utf-8"),
            *owners,
            (source_root / "main.cpp").read_text(encoding="utf-8"),
        )
    )


def _read(relative: str) -> str:
    if relative == "cdmw/services/mesh_service.py":
        return "\n".join(_read(path) for path in (relative + ".facade", "cdmw/services/mesh_service_selection.py"))
    if relative.endswith(".facade"):
        relative = relative.removesuffix(".facade")
    if relative == "native/cdmw_d3d11_preview/src/main.cpp":
        return d3d11_preview_source()
    if relative == "native/cdmw_mesh_core/src/main.cpp":
        return _native_mesh_core_source()
    if relative == "cdmw/modding/mesh_native_core.py":
        return _mesh_native_core_source()
    if relative == "cdmw/ui/mesh_editor/tab.py":
        return mesh_editor_tab_source(ROOT)
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py":
        return static_replacement_callback_factory_source(ROOT)
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py":
        return static_replacement_ui_section_source(ROOT)
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py":
        return static_replacement_mesh_edit_implementation_source(ROOT)
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py":
        return static_replacement_remaining_callback_source(ROOT)
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_routing_callbacks.py":
        return static_replacement_routing_callback_source(ROOT)
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_source_part_mutation_callbacks.py":
        return static_replacement_source_part_mutation_callback_source(ROOT)
    if relative == "cdmw/ui/archive_browser/static_replacement_dialog_texture_callbacks.py":
        return static_replacement_texture_callback_source(ROOT)
    return (ROOT / relative).read_text(encoding="utf-8")


def _function_source(source: str, name: str) -> str:
    return function_source(source, name)


def _mesh_native_core_source() -> str:
    owner_order = (
        "mesh_native_core.py",
        "mesh_native_core_constants.py",
        "mesh_native_core_payload_helpers.py",
        "mesh_native_core_blend_helpers.py",
        "mesh_native_outputs.py",
        "mesh_native_preview_model.py",
        "mesh_native_transforms.py",
        "mesh_native_snapshot_create.py",
        "mesh_native_snapshot_restore.py",
        "mesh_native_snapshot_codec.py",
        "mesh_native_selection_operations.py",
        "mesh_native_selection.py",
        "mesh_native_preview_groups.py",
        "mesh_native_submesh_geometry.py",
        "mesh_native_selection_preview.py",
        "mesh_native_session_payloads.py",
        "mesh_native_session_state.py",
        "mesh_native_session_api.py",
        "mesh_native_morph.py",
        "mesh_native_rigging.py",
        "mesh_native_brush.py",
        "mesh_native_normals.py",
        "mesh_native_uv.py",
        "mesh_native_topology_payloads.py",
        "mesh_native_topology_basic.py",
        "mesh_native_topology_selection.py",
        "mesh_native_duplicate_reports.py",
        "mesh_native_topology_parts.py",
        "mesh_native_report_edits.py",
        "mesh_native_report_application.py",
        "mesh_native_report_geometry.py",
        "mesh_native_dispatch.py",
        "mesh_native_preview_payloads.py",
        "mesh_native_history.py",
        "mesh_native_payloads.py",
        "mesh_native_binary_io.py",
        "mesh_native_client.py",
        "mesh_native_core_diagnostics.py",
        "mesh_native_core_temp_paths.py",
    )
    return "\n".join(
        (ROOT / "cdmw/modding" / name).read_text(encoding="utf-8")
        for name in owner_order
    )


def _mesh_edit_source() -> str:
    return "\n".join(
        (
            _read("cdmw/ui/shell/app_window.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_shell.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_open.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_state_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_transform.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_a.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_state_b.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_preview_shell.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_workflow_shell.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py"),
            _read("cdmw/ui/archive_browser/static_replacement_combo_options.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_status_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_runtime_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_d3d11_watchdog_state.py"),
            _read("cdmw/ui/archive_browser/static_replacement_diagnostics.py"),
        )
    )


class MeshEditResponsivenessSourceGuardTests(unittest.TestCase):
    def test_native_topology_preview_uses_binary_descriptor_output(self) -> None:
        native_source = _read("native/cdmw_mesh_core/src/main.cpp")

        self.assertGreaterEqual(native_source.count('"preview_triangle_output_path"'), 2)
        self.assertIn('"preview_triangles", ".bin"', native_source)

    def test_build_fast_profile_still_rebuilds_native_helpers(self) -> None:
        build_script = _read("build_pyside6_app.ps1")
        build_bat = _read("build.bat")
        build_gui = _read("build_gui.py")
        self.assertIn('Write-Host "Building native helpers ($Configuration)..."', build_script)
        self.assertIn('& (Join-Path $scriptDir "build_native_windows.ps1") @nativeBuildArgs', build_script)
        self.assertNotIn("Skipping native helper build for fast profile", build_script)
        self.assertNotIn('$BuildProfile -eq "fast" -and (Test-NativeOutputsPresent', build_script)
        self.assertIn("native helpers still rebuild incrementally", build_bat)
        self.assertIn("native helpers still rebuild", build_gui)

    def test_standalone_mesh_file_load_uses_worker_thread(self) -> None:
        tab_source = _read("cdmw/ui/mesh_editor/tab.py")
        worker_source, aux_worker_source = (_read("cdmw/workers/mesh_editor_workers.py"), _read("cdmw/workers/mesh_editor_aux_workers.py"))
        close_source = _read("cdmw/ui/shell/close_controller.py")
        d3d11_host_source = _read("cdmw/ui/native_d3d11_preview_host.py")
        d3d11_native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        runtime_source = _read("cdmw/ui/mesh_editor/native_preview_runtime.py")
        actions_source = _read("cdmw/ui/mesh_editor/actions.py")

        import cdmw.ui.mesh_editor.tab as tab_facade, cdmw.workers.mesh_editor_workers as mesh_editor_workers; self.assertEqual((tab_facade.MeshFileSessionLoadWorker, tab_facade.MeshNativePreviewPackageWorker), (mesh_editor_workers.MeshFileSessionLoadWorker, mesh_editor_workers.MeshNativePreviewPackageWorker))
        self.assertIn("MeshFileSessionLoadWorker", tab_source)
        self.assertIn("MeshNativePreviewPackageWorker", tab_source)
        self.assertIn("def open_mesh_file_session_async(", tab_source)
        file_open_start = tab_source.index("def open_mesh_file_session(")
        file_open_body = tab_source[file_open_start:tab_source.index("def open_mesh_file_session_async(", file_open_start)]
        self.assertIn("mesh = mesh_service.load_mesh_file(source_path, run_roundtrip=True)", file_open_body)
        self.assertIn("self._show_standalone_session(view, mesh=mesh", file_open_body)
        self.assertNotIn("working_mesh(clone=False)", file_open_body)
        self.assertIn("def start_standalone_native_preview_async(", tab_source)
        self.assertIn("thread.start(QThread.LowPriority)", tab_source)
        self.assertIn("def iter_shutdown_workers(self)", tab_source)
        self.assertIn("def request_shutdown(self)", tab_source)
        self.assertIn("class MeshFileSessionLoadWorker(QObject):", aux_worker_source)
        self.assertIn("class MeshNativePreviewPackageWorker(QObject):", worker_source)
        self.assertIn("service = MeshService()", aux_worker_source)
        self.assertIn("mesh = service.load_mesh_file(self.path, run_roundtrip=True)", aux_worker_source)
        self.assertIn("view = service.open_edit_session(", aux_worker_source)
        self.assertIn("self.loaded.emit(self.request_id, service, view, mesh)", aux_worker_source)
        self.assertIn("def _handle_standalone_file_loaded(", tab_source)
        file_loaded_start = tab_source.index("def _handle_standalone_file_loaded(")
        file_loaded_body = tab_source[file_loaded_start:tab_source.index("def _handle_standalone_file_load_error", file_loaded_start)]
        self.assertNotIn("working_mesh(clone=False)", file_loaded_body)
        self.assertIn("prepared_preview = self.prepare_native_preview(self.mesh)", worker_source)
        self.assertIn("write_isolated_d3d11_preview_package(", worker_source)
        self.assertTrue(all("cdmw.ui." not in source for source in (worker_source, aux_worker_source)))
        self.assertIn('"mesh_editor_tab"', close_source)

        package_start = tab_source.index("def start_standalone_native_preview_async(")
        package_body = tab_source[package_start: tab_source.index("def _handle_standalone_native_package_ready", package_start)]
        self.assertIn("Legacy native Mesh Editor preview is disabled", package_body)
        self.assertIn("return False", package_body)
        self.assertNotIn("MeshNativePreviewPackageWorker(", package_body)
        self.assertIn("def _standalone_pose_native_preview_context(", tab_source)
        self.assertIn("controller.pose_preview_native_context()", tab_source)
        self.assertIn("or self.standalone_texture_preview_overrides", tab_source)
        sync_package_start = tab_source.index("def write_standalone_native_preview_package(")
        sync_package_body = tab_source[sync_package_start: tab_source.index("def load_standalone_native_preview_package", sync_package_start)]
        self.assertIn("mesh_editor_write_prepared_native_preview_package", tab_source)
        self.assertIn("pose_native_context = self._standalone_pose_native_preview_context()", sync_package_body)
        self.assertIn("mesh, pose_skeleton, pose_rotations = pose_native_context", sync_package_body)
        self.assertIn("prepared = _tab.mesh_pose_to_native_preview(", sync_package_body)
        self.assertIn("_tab.mesh_editor_write_prepared_native_preview_package(", sync_package_body)
        self.assertIn("mesh = self._standalone_preview_mesh_snapshot()", sync_package_body)
        self.assertLess(
            sync_package_body.index("pose_native_context = self._standalone_pose_native_preview_context()"),
            sync_package_body.index("mesh = self._standalone_preview_mesh_snapshot()"),
        )
        self.assertIn("def mesh_editor_write_prepared_native_preview_package(", runtime_source)
        self.assertIn("write_isolated_d3d11_preview_package(", runtime_source)
        self.assertIn("self.standalone_native_package_compare_mode = self.standalone_native_package_pending_compare_mode", tab_source)
        self.assertNotIn("def _confirm_standalone_auto_uv_topology_change(", tab_source)
        self.assertNotIn("native_mesh_auto_uv_report", tab_source)
        self.assertIn('("auto_uv", True), ("allow_topology_change", True)', actions_source)
        preview_refresh_start = tab_source.index("def _refresh_standalone_preview(")
        preview_refresh_body = tab_source[
            preview_refresh_start: tab_source.index("def _set_standalone_compare_mode(", preview_refresh_start)
        ]
        self.assertIn('self.standalone_compare_mode != "source" and controller.native_editor_mesh_dirty()', preview_refresh_body)
        self.assertIn("Python preview rebuild is disabled while C++ mesh state is dirty.", preview_refresh_body)
        self.assertLess(
            preview_refresh_body.index("controller.native_editor_mesh_dirty()"),
            preview_refresh_body.index("controller.native_preview_data()"),
        )
        compare_start = tab_source.index("def _set_standalone_compare_mode(")
        compare_body = tab_source[compare_start: tab_source.index("def _update_standalone_status", compare_start)]
        self.assertIn("self.standalone_native_package_has_reference", compare_body)
        self.assertIn('self.standalone_native_package_compare_mode == "source"', compare_body)
        self.assertIn("package_can_show_source", compare_body)
        self.assertIn('setter("original_only")', compare_body)
        self.assertLess(compare_body.index('setter("original_only")'), compare_body.index("self._refresh_standalone_preview()"))
        source_branch = compare_body[compare_body.index('if normalized == "source":'):compare_body.index('if normalized == "ghost"')]
        self.assertIn("self._standalone_native_preview_update_active()", source_branch)
        self.assertIn("self.start_standalone_native_preview_async(reset_view=False)", source_branch)
        self.assertLess(
            source_branch.index("self.start_standalone_native_preview_async(reset_view=False)"),
            source_branch.index("self._refresh_standalone_preview()"),
        )
        ghost_branch = compare_body[compare_body.index('if normalized == "ghost"'):compare_body.index("host = self.standalone_native_host", compare_body.index('if normalized == "ghost"'))]
        self.assertIn("self._standalone_native_preview_update_active()", ghost_branch)
        self.assertIn("not self.standalone_native_package_has_reference", ghost_branch)
        self.assertIn("self.start_standalone_native_preview_async(reset_view=False)", ghost_branch)
        host_mode_branch = compare_body[compare_body.index("host = self.standalone_native_host"):]
        self.assertIn("Native D3D11 compare view update failed; preview is stale.", host_mode_branch)
        self.assertIn("self.status_message_requested.emit(message, True)", host_mode_branch)
        self.assertLess(
            host_mode_branch.index("if self._standalone_native_preview_update_active():"),
            host_mode_branch.index("self._refresh_standalone_preview()"),
        )
        finish_start = tab_source.index("def _handle_standalone_native_preview_finished(")
        finish_body = tab_source[finish_start: tab_source.index("def _handle_standalone_native_preview_error", finish_start)]
        self.assertIn("Native D3D11 preview stopped unexpectedly; preview is stale.", finish_body)
        self.assertIn("self.status_message_requested.emit(message, True)", finish_body)
        self.assertNotIn("_refresh_standalone_preview()", finish_body)
        skeleton_preview_start = tab_source.index("def _handle_skeleton_pose_request(")
        skeleton_preview_body = tab_source[
            skeleton_preview_start: tab_source.index("def _tick_standalone_animation_playback", skeleton_preview_start)
        ]
        self.assertIn("if self._standalone_native_preview_update_active():", skeleton_preview_body)
        self.assertLess(
            skeleton_preview_body.index("if self._standalone_native_preview_update_active():"),
            skeleton_preview_body.index("self._refresh_standalone_preview()"),
        )
        animation_tick_start = tab_source.index("def _tick_standalone_animation_playback(")
        animation_tick_body = tab_source[
            animation_tick_start: tab_source.index("def _handle_uv_region_selection", animation_tick_start)
        ]
        self.assertIn("if self._standalone_native_preview_update_active():", animation_tick_body)
        self.assertLess(
            animation_tick_body.index("if self._standalone_native_preview_update_active():"),
            animation_tick_body.index("self._refresh_standalone_preview()"),
        )
        self.assertIn('"original_only"', d3d11_host_source)
        self.assertIn('value == "original_only"', d3d11_native_source)
        self.assertIn('display_mode_ == "original_only" && has_reference', d3d11_native_source)

    def test_standalone_d3d11_update_failure_does_not_refresh_python_preview(self) -> None:
        tab_source = _read("cdmw/ui/mesh_editor/tab.py")

        update_start = tab_source.index("def _apply_standalone_native_update(")
        update_body = tab_source[update_start: tab_source.index("def _refresh_standalone_preview", update_start)]
        self.assertIn("if _native_update_has_payload(update) or self._standalone_native_preview_update_active():", update_body)
        self.assertIn("Native D3D11 preview update failed; preview is stale.", update_body)
        self.assertIn("self.status_message_requested.emit(message, True)", update_body)
        self.assertLess(
            update_body.index("host = self.standalone_native_host"),
            update_body.index("if _native_update_has_payload(update) or self._standalone_native_preview_update_active():"),
        )
        self.assertNotIn("self._refresh_standalone_preview()", update_body)
        stroke_start = tab_source.index("def _apply_standalone_native_mesh_edit_stroke(")
        stroke_body = tab_source[stroke_start: tab_source.index("def _standalone_native_mesh_edit_stroke_command(", stroke_start)]
        self.assertIn("if not self._apply_standalone_native_update(native_update):", stroke_body)
        failure_branch = stroke_body[
            stroke_body.index("if not self._apply_standalone_native_update(native_update):"):
        ]
        self.assertIn("\n                return\n", failure_branch)

    def test_remaining_mesh_clone_and_preview_rebuild_sites_are_classified(self) -> None:
        ordinary_scan_paths = (
            "cdmw/services/mesh_service.py",
            "cdmw/services/model_library_preview.py",
            "cdmw/modding/mesh_morph_sliders.py",
            "cdmw/modding/mesh_edit_ops.py",
            "cdmw/ui/mesh_editor/tab.py",
            "cdmw/ui/archive_browser/mesh_launch_flow.py",
            "cdmw/ui/shell/model_library_bridge.py",
            "cdmw/ui/archive_browser/static_replacement_prompt_preflight.py",
        )
        scan_sources = [*[(path, _read(path)) for path in ordinary_scan_paths],
            ("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py", static_replacement_mesh_edit_implementation_source(ROOT)),
            ("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py", static_replacement_remaining_callback_source(ROOT)),
            ("cdmw/ui/archive_browser/static_replacement_dialog_source_part_mutation_callbacks.py", static_replacement_source_part_mutation_callback_source(ROOT)),
        ]
        expected_boundary_or_fallback_sites = [
            ("cdmw/services/mesh_service.py", "mesh=clone_mesh_for_editing(session.working_mesh),"),
            ("cdmw/services/mesh_service.py", "return clone_mesh_for_editing(mesh), clone_mesh_for_editing(mesh)"),
            ("cdmw/services/mesh_service.py", "cloned = clone_mesh_for_editing(mesh)"),
            ("cdmw/services/model_library_preview.py", "preview_model = parsed_mesh_to_preview_model(scene_result.mesh)"),
            ("cdmw/modding/mesh_morph_sliders.py", "result = clone_mesh_for_editing(base_mesh)"),
            ("cdmw/ui/archive_browser/mesh_launch_flow.py", "preview_model = parsed_mesh_to_preview_model(scene_import_result.mesh)"),
            ("cdmw/ui/shell/model_library_bridge.py", "preview_model = parsed_mesh_to_preview_model(scene_result.mesh)"),
            (
                "cdmw/ui/archive_browser/static_replacement_prompt_preflight.py",
                "original_preview = parsed_mesh_to_preview_model(original_mesh)",
            ),
            (
                "cdmw/ui/archive_browser/static_replacement_prompt_preflight.py",
                "replacement_preview = parsed_mesh_to_preview_model(replacement_mesh)",
            ),
            (
                "cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py",
                "_state._mesh_edit_state.replacement_preview_model = _state.parsed_mesh_to_preview_model(",
            ),
            (
                "cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py",
                "_state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(_state.state.replacement_mesh_for_mapping)",
            ),
            (
                "cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py",
                "_state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(_state.state.replacement_mesh_for_mapping) if _state.state.replacement_mesh_for_mapping is not None else None",
            ),
            (
                "cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py",
                "_state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(_state.state.replacement_mesh_for_mapping)",
            ),
            (
                "cdmw/ui/archive_browser/static_replacement_dialog_source_part_mutation_callbacks.py",
                "_state._set_replacement_preview_model(_state.parsed_mesh_to_preview_model(replacement_mesh_for_mapping) if replacement_mesh_for_mapping is not None else None)",
            ),
        ]
        actual: list[tuple[str, str]] = []
        for relative, source in scan_sources:
            for line in source.splitlines():
                stripped = line.strip()
                if "clone_mesh_for_editing(" in stripped or "parsed_mesh_to_preview_model(" in stripped:
                    actual.append((relative, stripped))
        self.assertEqual(expected_boundary_or_fallback_sites, actual)

    def test_initial_preview_identity_blob_is_native_owned(self) -> None:
        writer_source = _read("cdmw/rendering/native_preview_package_writer.py")
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        native_source = _read("native/cdmw_mesh_core/src/main.cpp")

        self.assertIn("from cdmw.modding.mesh_native_core import write_native_preview_identity_blob", writer_source)
        self.assertIn("def _write_editor_identity_blob_native(", writer_source)
        self.assertIn("_write_editor_identity_blob_native(aggregate_identity_path, batch, vertex_count)", writer_source)
        self.assertIn('with aggregate_identity_path.open("ab") as identity_stream:', writer_source)
        aggregate_identity_start = writer_source.index("source_indices_are_descriptor_backed = (")
        aggregate_identity_body = writer_source[
            aggregate_identity_start: writer_source.index("aggregate_identity_size += identity_size", aggregate_identity_start)
        ]
        self.assertIn("if source_indices_are_descriptor_backed:", aggregate_identity_body)
        self.assertIn('raise RuntimeError("native preview identity generation failed for descriptor-backed source ids")', aggregate_identity_body)
        self.assertLess(
            aggregate_identity_body.index("if source_indices_are_descriptor_backed:"),
            aggregate_identity_body.index("editor_identity, identity_blob = _editor_identity_blob(batch, vertex_count)"),
        )
        identity_blob_start = writer_source.index("def _editor_identity_blob(")
        identity_blob_body = writer_source[identity_blob_start: writer_source.index("def _editor_identity_metadata(", identity_blob_start)]
        identity_metadata_start = writer_source.index("def _editor_identity_metadata(")
        identity_metadata_body = writer_source[identity_metadata_start: writer_source.index("def _batch_source_range(", identity_metadata_start)]
        self.assertLess(identity_blob_body.index("source_vertex_range = _batch_source_range("), identity_blob_body.index("raw_source_vertices = ("))
        self.assertLess(identity_blob_body.index("source_face_range = _batch_source_range("), identity_blob_body.index("raw_source_faces = ("))
        self.assertIn("if source_vertex_range is not None", identity_blob_body)
        self.assertIn("if source_face_range is not None", identity_blob_body)
        self.assertLess(identity_metadata_body.index("source_vertex_range = _batch_source_range("), identity_metadata_body.index("raw_source_vertices = ("))
        self.assertLess(identity_metadata_body.index("source_face_range = _batch_source_range("), identity_metadata_body.index("raw_source_faces = ("))
        self.assertIn("if source_vertex_range is not None", identity_metadata_body)
        self.assertIn("if source_face_range is not None", identity_metadata_body)
        self.assertIn("def _source_index_at(", writer_source)
        self.assertIn("def _source_index_max(", writer_source)
        self.assertNotIn('else tuple(int(index) for index in (getattr(batch, "source_vertex_indices"', writer_source)
        self.assertNotIn('else tuple(int(index) for index in (getattr(batch, "source_face_indices"', writer_source)
        self.assertIn('"preview-identity-json"', bridge_source)
        self.assertIn("def write_native_preview_identity_blob(", bridge_source)
        self.assertIn("source_vertex_indices_binary: Mapping[str, object] | None = None", bridge_source)
        self.assertIn("source_vertex_start: int | None = None", bridge_source)
        self.assertIn('"source_vertex_indices_binary"] = source_vertex_descriptor', bridge_source)
        self.assertIn('tempfile.mkdtemp(prefix="cdmw_mesh_core_preview_identity_")', bridge_source)
        self.assertIn('payload["source_vertex_indices_binary"] = _write_int_binary_payload(', bridge_source)
        self.assertIn('payload["source_face_indices_binary"] = _write_int_binary_payload(', bridge_source)
        self.assertNotIn('payload["source_vertex_indices"] = [int(index) for index in tuple(source_vertex_indices or ())]', bridge_source)
        self.assertNotIn('payload["source_face_indices"] = [int(index) for index in tuple(source_face_indices or ())]', bridge_source)
        self.assertIn('"source_vertex_start"] = int(source_vertex_start)', bridge_source)
        self.assertIn("std::string run_preview_identity(const JsonValue& root)", native_source)
        self.assertIn('int_or(root.get("source_vertex_start"), -1)', native_source)
        self.assertIn('int_or(root.get("source_face_start"), -1)', native_source)
        self.assertIn('int_vector_from_binary_or_json(root, "source_vertex_indices_binary", "source_vertex_indices")', native_source)
        self.assertIn('int_vector_from_binary_or_json(root, "source_face_indices_binary", "source_face_indices")', native_source)
        self.assertIn("source_vertex_start + vertex_offset", native_source)
        self.assertIn("source_face_start + face_offset", native_source)
        self.assertIn("append_i32_le(identity, source_submesh_index)", native_source)
        self.assertIn('if (command == "preview-identity-json") return preview_identity_json_command(job_path, report_path);', native_source)

    def test_initial_preview_geometry_blob_is_native_owned(self) -> None:
        prepare_source = _read("cdmw/rendering/model_preview_prepare.py")
        mesh_editor_payload_source = _read("cdmw/ui/mesh_editor/native_preview_payloads.py")
        static_mapping_source = _read("cdmw/ui/archive_browser/static_replacement_preview_mapping.py")
        package_source = _read("cdmw/rendering/native_preview_package_writer.py")
        payload_source = _read("cdmw/rendering/native_preview_payloads.py")
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        native_source = _read("native/cdmw_mesh_core/src/main.cpp")

        self.assertIn("def _build_vertex_blob_native(", prepare_source)
        self.assertIn("from cdmw.modding.mesh_native_core import write_native_preview_geometry_blob", prepare_source)
        self.assertIn("native_result = _build_vertex_blob_native(model, flip_texture_v=flip_texture_v)", prepare_source)
        self.assertLess(
            prepare_source.index("native_result = _build_vertex_blob_native(model, flip_texture_v=flip_texture_v)"),
            prepare_source.index("return _build_vertex_blob_impl(model, flip_texture_v=flip_texture_v, use_numpy=True)"),
        )
        self.assertIn('"preview-geometry-json"', bridge_source)
        self.assertIn("def write_native_preview_geometry_blob(", bridge_source)
        self.assertIn("std::string run_preview_geometry(const JsonValue& root)", native_source)
        self.assertIn("append_preview_vertex(", native_source)
        preview_geometry_bridge_start = bridge_source.index("def write_native_preview_geometry_blob(")
        preview_geometry_bridge_body = bridge_source[
            preview_geometry_bridge_start: bridge_source.index("def build_native_preview_model_in_original_frame(", preview_geometry_bridge_start)
        ]
        self.assertIn('"positions_binary"] = _write_vec3_binary_payload', preview_geometry_bridge_body)
        self.assertIn('"normals_binary"] = _write_vec3_binary_payload', preview_geometry_bridge_body)
        self.assertIn('"texture_coordinates_binary"] = _write_vec2_binary_payload', preview_geometry_bridge_body)
        self.assertIn('"indices_binary"] = _write_int_binary_payload', preview_geometry_bridge_body)
        self.assertIn("_put_source_vertex_indices_payload(item, prefix", preview_geometry_bridge_body)
        self.assertIn("_put_source_face_indices_payload(item, prefix", preview_geometry_bridge_body)
        self.assertNotIn('"source_vertex_indices_binary"] = _write_int_binary_payload', preview_geometry_bridge_body)
        self.assertNotIn('"source_face_indices_binary"] = _write_int_binary_payload', preview_geometry_bridge_body)
        self.assertNotIn("for mesh_index, mesh in enumerate(tuple(meshes or ()))", preview_geometry_bridge_body)
        self.assertNotIn('tuple(item.pop("indices") or ())', preview_geometry_bridge_body)
        self.assertNotIn('tuple(item.pop("faces") or ())', preview_geometry_bridge_body)
        self.assertNotIn('tuple(item.pop("source_vertex_indices") or ())', preview_geometry_bridge_body)
        self.assertNotIn('tuple(item.pop("source_face_indices") or ())', preview_geometry_bridge_body)
        self.assertNotIn('"meshes": [dict(mesh) for mesh in tuple(meshes or ())]', preview_geometry_bridge_body)
        preview_geometry_native_start = native_source.index("std::string run_preview_geometry(const JsonValue& root)")
        preview_geometry_native_body = native_source[
            preview_geometry_native_start: native_source.index("std::string run_preview_identity", preview_geometry_native_start)
        ]
        self.assertIn('item_has_direct_geometry(item, "positions_binary", "positions")', preview_geometry_native_body)
        self.assertIn('vertices_from_binary_or_json(item, "positions_binary", "positions")', preview_geometry_native_body)
        self.assertIn("mesh_vertices_from_item(item)", preview_geometry_native_body)
        self.assertIn("preview_triangle_index_stream_from_binary_or_json(item, positions.size())", preview_geometry_native_body)
        self.assertIn("faces = mesh_faces_from_item(item, positions.size())", preview_geometry_native_body)
        self.assertIn("preview_triangle_index_stream_from_faces(faces)", preview_geometry_native_body)
        self.assertIn("mesh_source_vertex_indices_from_item(item, positions.size())", preview_geometry_native_body)
        self.assertIn("mesh_source_face_indices_from_item(", preview_geometry_native_body)
        self.assertIn("mesh_normals_from_item(item)", preview_geometry_native_body)
        self.assertIn('item_has_direct_geometry(item, "texture_coordinates_binary", "texture_coordinates")', preview_geometry_native_body)
        self.assertIn('uvs_from_binary_or_json(item, "texture_coordinates_binary", "texture_coordinates")', preview_geometry_native_body)
        self.assertIn("mesh_uvs_from_item(item)", preview_geometry_native_body)
        self.assertNotIn('vertices_from_json(item.get("positions"))', preview_geometry_native_body)
        self.assertNotIn('preview_triangle_index_stream_from_json(item.get("indices")', preview_geometry_native_body)
        self.assertNotIn('vertices_from_json(item.get("normals"))', preview_geometry_native_body)
        self.assertNotIn('uvs_from_json(item.get("texture_coordinates"))', preview_geometry_native_body)
        self.assertIn("contiguous_int_range(batch.source_vertex_indices, source_vertex_start)", native_source)
        self.assertIn('out << ",\\"source_vertex_start\\":" << source_vertex_start', native_source)
        self.assertIn("contiguous_int_range(batch.source_face_indices, source_face_start)", native_source)
        self.assertIn('out << ",\\"source_face_start\\":" << source_face_start', native_source)
        self.assertIn("write_int_binary_descriptor(out, source_vertices_path", native_source)
        self.assertIn("write_int_binary_descriptor(out, source_faces_path", native_source)
        build_vertex_blob_native_body = prepare_source[
            prepare_source.index("def _build_vertex_blob_native("): prepare_source.index("def _model_preview_binary_descriptor", prepare_source.index("def _build_vertex_blob_native("))
        ]
        self.assertIn("source_vertex_indices_binary=_model_preview_binary_descriptor(", build_vertex_blob_native_body)
        self.assertIn("source_face_indices_binary=_model_preview_binary_descriptor(", build_vertex_blob_native_body)
        self.assertIn('_source_range_from_mesh(mesh, "source_vertex_range_start", "source_vertex_range_count")', build_vertex_blob_native_body)
        self.assertIn("def _put_preview_source_i32_payload(", prepare_source)
        self.assertIn('mesh_payload["source_vertex_start"] = source_vertex_range[0]', build_vertex_blob_native_body)
        self.assertIn('mesh_payload["source_face_start"] = source_face_range[0]', build_vertex_blob_native_body)
        self.assertIn('_put_preview_source_i32_payload(\n                    mesh_payload,\n                    getattr(mesh, "source_vertex_indices", ()) or (),', build_vertex_blob_native_body)
        self.assertIn('_put_preview_source_i32_payload(\n                    mesh_payload,\n                    getattr(mesh, "source_face_indices", ()) or (),', build_vertex_blob_native_body)
        self.assertNotIn('mesh_payload["source_vertex_indices"] = list(', build_vertex_blob_native_body)
        self.assertNotIn('mesh_payload["source_face_indices"] = list(', build_vertex_blob_native_body)
        self.assertNotIn('_i32_list_from_binary_descriptor(raw_batch.get("source_vertex_indices_binary"))', build_vertex_blob_native_body)
        mesh_editor_native_body = mesh_editor_payload_source[
            mesh_editor_payload_source.index("def _mesh_to_native_preview_native("):
            mesh_editor_payload_source.index("def _int_tuple(", mesh_editor_payload_source.index("def _mesh_to_native_preview_native("))
        ]
        mesh_to_preview_start = mesh_editor_payload_source.index("def mesh_to_native_preview(")
        mesh_to_preview_body = mesh_editor_payload_source[
            mesh_to_preview_start: mesh_editor_payload_source.index("def _mesh_to_native_preview_native(", mesh_to_preview_start)
        ]
        self.assertIn('if not _allow_python_preview_fallback(mesh, "preview_geometry", submesh_index=-1):', mesh_to_preview_body)
        self.assertIn('raise RuntimeError("native Mesh Editor preview geometry unavailable; Python preview fallback is disabled")', mesh_to_preview_body)
        self.assertLess(
            mesh_to_preview_body.index('if not _allow_python_preview_fallback(mesh, "preview_geometry", submesh_index=-1):'),
            mesh_to_preview_body.index('raise RuntimeError("native Mesh Editor preview geometry unavailable; Python preview fallback is disabled")'),
        )
        self.assertIn("source_vertex_indices_binary=source_vertices_binary or {}", mesh_editor_native_body)
        self.assertIn("source_face_indices_binary=source_faces_binary or {}", mesh_editor_native_body)
        self.assertNotIn("_i32_tuple_from_binary_descriptor(", mesh_editor_native_body)
        self.assertLess(
            mesh_editor_native_body.index("source_vertices_binary = _native_binary_descriptor("),
            mesh_editor_native_body.index('source_vertices = _int_tuple(raw_batch.get("source_vertex_indices"))'),
        )
        self.assertLess(
            mesh_editor_native_body.index("source_faces_binary = _native_binary_descriptor("),
            mesh_editor_native_body.index('source_faces = _int_tuple(raw_batch.get("source_face_indices"))'),
        )
        self.assertIn('raw_batch.get("source_vertex_indices_binary")', mesh_editor_payload_source)
        self.assertIn('"preview-model-json"', bridge_source)
        self.assertIn("def build_native_preview_model_in_original_frame(", bridge_source)
        self.assertIn("std::string run_preview_model(const JsonValue& root)", native_source)
        preview_model_bridge_start = bridge_source.index("def build_native_preview_model_in_original_frame(")
        preview_model_bridge_body = bridge_source[
            preview_model_bridge_start: bridge_source.index("def apply_native_mesh_transform(", preview_model_bridge_start)
        ]
        self.assertIn("raw_source_indices = source_indices or ()", preview_model_bridge_body)
        self.assertIn('for submesh_position, submesh in enumerate(getattr(parsed_mesh, "submeshes", ()) or ())', preview_model_bridge_body)
        self.assertNotIn("raw_source_indices = tuple(source_indices or ())", preview_model_bridge_body)
        self.assertNotIn('tuple(getattr(parsed_mesh, "submeshes", ()) or ())', preview_model_bridge_body)
        self.assertIn("session_id = _ensure_native_mesh_session_submesh", preview_model_bridge_body)
        self.assertIn('item["session_id"] = session_id', preview_model_bridge_body)
        self.assertIn('item["vertices_binary"] = _write_vec3_binary_payload', preview_model_bridge_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', preview_model_bridge_body)
        self.assertIn('item["uvs_binary"] = _write_vec2_binary_payload', preview_model_bridge_body)
        self.assertIn('item["normals_binary"] = _write_vec3_binary_payload', preview_model_bridge_body)
        self.assertIn('"positions_output_path": _native_preview_delta_output_path', preview_model_bridge_body)
        self.assertIn('"texture_coordinates_output_path": _native_preview_delta_output_path', preview_model_bridge_body)
        self.assertIn('"indices_output_path": _native_preview_delta_output_path', preview_model_bridge_body)
        self.assertIn('"source_vertex_indices_output_path": _native_preview_delta_output_path', preview_model_bridge_body)
        self.assertIn('"source_face_indices_output_path": _native_preview_delta_output_path', preview_model_bridge_body)
        self.assertIn("return _hydrate_native_preview_model_report(report)", preview_model_bridge_body)
        self.assertIn("mesh.pop(\"positions\", None)", bridge_source)
        self.assertIn("mesh.pop(\"indices\", None)", bridge_source)
        self.assertNotIn("mesh[\"positions\"] = list(positions)", bridge_source)
        self.assertNotIn("mesh[\"indices\"] = list(indices)", bridge_source)
        self.assertLess(
            preview_model_bridge_body.index("session_id = _ensure_native_mesh_session_submesh"),
            preview_model_bridge_body.index("faces, _source_face_indices = _face_json_with_source_indices"),
        )
        self.assertNotIn('"vertices": vertices', preview_model_bridge_body)
        self.assertNotIn('"faces": faces', preview_model_bridge_body)
        self.assertNotIn('"uvs": uvs', preview_model_bridge_body)
        preview_model_native_start = native_source.index("std::string run_preview_model(const JsonValue& root)")
        preview_model_native_body = native_source[
            preview_model_native_start: native_source.index("std::string run_preview_geometry(const JsonValue& root)", preview_model_native_start)
        ]
        preview_model_report_start = native_source.index("std::string preview_model_report_json(")
        preview_model_report_body = native_source[
            preview_model_report_start: native_source.index("std::string run_preview_model(const JsonValue& root)", preview_model_report_start)
        ]
        self.assertIn("mesh_vertices_from_item(item)", preview_model_native_body)
        self.assertIn("mesh_faces_from_item(item, vertices.size())", preview_model_native_body)
        self.assertIn("preview_triangle_index_stream_from_faces(faces)", preview_model_native_body)
        self.assertIn("mesh_source_vertex_indices_from_item(item, vertices.size())", preview_model_native_body)
        self.assertIn("mesh_source_face_indices_from_item(item, faces.size())", preview_model_native_body)
        self.assertIn("contiguous_int_range(mesh.source_vertex_indices, source_vertex_start)", preview_model_report_body)
        self.assertIn("contiguous_int_range(mesh.source_face_indices, source_face_start)", preview_model_report_body)
        self.assertLess(
            preview_model_report_body.index("contiguous_int_range(mesh.source_vertex_indices, source_vertex_start)"),
            preview_model_report_body.index("write_int_binary_file(mesh.source_vertex_indices_path, mesh.source_vertex_indices)"),
        )
        self.assertLess(
            preview_model_report_body.index("contiguous_int_range(mesh.source_face_indices, source_face_start)"),
            preview_model_report_body.index("write_int_binary_file(mesh.source_face_indices_path, mesh.source_face_indices)"),
        )
        self.assertIn("positions_path = string_or(item.get(\"positions_output_path\")", preview_model_native_body)
        preview_model_report_start = native_source.index("std::string preview_model_report_json(")
        preview_model_report_body = native_source[preview_model_report_start: preview_model_native_start]
        self.assertIn("write_vec3_binary_descriptor(out, mesh.positions_path", preview_model_report_body)
        self.assertIn("write_int_binary_descriptor(out, mesh.indices_path", preview_model_report_body)
        self.assertIn("write_int_binary_descriptor(out, mesh.source_vertex_indices_path", preview_model_report_body)
        self.assertIn("report.uvs = mesh_uvs_from_item(item)", preview_model_native_body)
        self.assertIn("report.normals = mesh_normals_from_item(item)", preview_model_native_body)
        self.assertNotIn('vertices_from_binary_or_json(item, "vertices_binary", "vertices")', preview_model_native_body)
        self.assertNotIn("faces_from_binary_or_json(item, vertices.size())", preview_model_native_body)
        self.assertNotIn("vertices_from_json(item.get(\"vertices\"))", preview_model_native_body)
        self.assertNotIn("preview_triangle_index_stream_from_faces_json(item.get(\"faces\")", preview_model_native_body)
        self.assertIn("native_preview = _preview_model_in_original_frame_native(", static_mapping_source)
        self.assertIn("def _preview_model_in_original_frame_python_reference(", static_mapping_source)
        self.assertIn("source_vertex_range_start=source_vertex_range_start", static_mapping_source)
        self.assertIn("source_vertex_range_start=0", static_mapping_source)
        self.assertIn("source_vertex_range_count=len(vertices)", static_mapping_source)
        self.assertIn("source_face_range_start=0", static_mapping_source)
        self.assertIn("source_face_range_count=len(faces)", static_mapping_source)
        self.assertNotIn("source_vertex_indices = list(range(len(vertices)))", static_mapping_source)
        self.assertNotIn("source_face_indices = list(range(len(faces)))", static_mapping_source)
        self.assertIn("def _native_preview_range(", static_mapping_source)
        self.assertIn("identity_output_path", native_source)
        self.assertIn("preview_triangle_index_stream_from_faces(faces)", native_source)
        self.assertIn("report.source_vertex_indices.push_back(source_vertex_index)", native_source)
        self.assertIn("report.source_face_indices.push_back(source_face_index)", native_source)
        self.assertIn("append_i32_le(identity, source_submesh_index)", native_source)
        self.assertIn('if (command == "preview-geometry-json") return preview_geometry_json_command(job_path, report_path);', native_source)
        self.assertIn('"identity_output_path": str(identity_path) if identity_path is not None else ""', bridge_source)
        self.assertIn("identity_output_path=identity_path", prepare_source)
        self.assertIn("_model_preview_binary_descriptor(getattr(mesh, \"positions_binary\", None)", prepare_source)
        self.assertIn('mesh_payload["positions_binary"] = positions_binary', prepare_source)
        self.assertIn("positions_binary=positions_binary or {}", static_mapping_source)
        self.assertIn("indices_binary=indices_binary or {}", static_mapping_source)
        self.assertIn("preview_base_color=tuple(batch.base_color or ())", prepare_source)
        self.assertIn("preview_bounds_min=tuple(batch.bounds_min or ())", prepare_source)
        self.assertIn("tangents_usable=bool(batch.tangents_usable)", prepare_source)
        self.assertIn("source_vertex_indices=emitted_source_vertices", prepare_source)
        self.assertIn("source_vertex_range_start = 0", prepare_source)
        self.assertIn("source_vertex_range_count = int(batch.vertex_count)", prepare_source)
        self.assertIn("source_face_range_count = max(0, int(batch.vertex_count) // 3)", prepare_source)
        self.assertNotIn("tuple(range(int(batch.vertex_count)))", prepare_source)
        self.assertNotIn("tuple(range(max(0, int(batch.vertex_count) // 3)))", prepare_source)
        self.assertIn("editor_identity_blob=bytes(batch.editor_identity_blob or b\"\")", prepare_source)
        self.assertIn("precomputed_identity_blob = bytes(getattr(batch, \"editor_identity_blob\", b\"\") or b\"\")", package_source)
        self.assertIn("def _write_identity_source_i32_sidecar(", package_source)
        self.assertIn('source_vertex_indices=(),', package_source)
        self.assertIn('source_face_indices=(),', package_source)
        self.assertNotIn('tuple(int(index) for index in tuple(getattr(batch, "source_vertex_indices"', package_source)
        self.assertNotIn('tuple(int(index) for index in tuple(getattr(batch, "source_face_indices"', package_source)
        self.assertNotIn("tuple(int(index) for index in tuple(batch.source_vertex_indices", prepare_source)
        self.assertNotIn("tuple(int(index) for index in tuple(batch.source_face_indices", prepare_source)
        self.assertIn("_batch_tangents_usable(batch, usable_blob, vertex_count)", package_source)
        self.assertIn("_batch_base_color(batch, usable_blob)", package_source)
        self.assertNotIn("_tangents_usable(usable_blob, vertex_count)", package_source)
        self.assertNotIn("_first_vertex_color(usable_blob)", package_source)
        self.assertIn("def _batch_bounds(", payload_source)
        self.assertIn("bounds_min, bounds_max = _batch_bounds(batch, vertex_blob, vertex_count)", payload_source)
        prepare_start = prepare_source.index("def prepare_model_preview(")
        prepare_body = prepare_source[prepare_start: prepare_source.index("def alignment_euler_xyz_matrix", prepare_start)]
        self.assertNotIn("for face_ordinal, index_offset in enumerate(range(0, len(mesh_indices) - 2, 3))", prepare_body)
        mesh_editor_entry = mesh_editor_payload_source[
            mesh_editor_payload_source.index("def mesh_to_native_preview("):
            mesh_editor_payload_source.index("def _mesh_to_native_preview_native(")
        ]
        self.assertIn("native_preview = _mesh_to_native_preview_native(mesh)", mesh_editor_entry)
        self.assertNotIn("_vertex_blob(", mesh_editor_entry)
        self.assertIn("write_native_preview_geometry_blob", mesh_editor_payload_source)
        mesh_editor_native_start = mesh_editor_payload_source.index("def _mesh_to_native_preview_native(")
        mesh_editor_native_body = mesh_editor_payload_source[
            mesh_editor_native_start: mesh_editor_payload_source.index("def _int_tuple(", mesh_editor_native_start)
        ]
        self.assertIn("_ensure_native_mesh_session_submesh(", mesh_editor_native_body)
        self.assertIn('"session_id": session_id', mesh_editor_native_body)
        self.assertIn('vertex_count = _sequence_len(getattr(submesh, "vertices", ()))', mesh_editor_native_body)
        self.assertIn('face_count = _sequence_len(getattr(submesh, "faces", ()))', mesh_editor_native_body)
        self.assertIn('submeshes = getattr(mesh, "submeshes", ()) or ()', mesh_editor_native_body)
        self.assertNotIn('submeshes = tuple(getattr(mesh, "submeshes", ()) or ())', mesh_editor_native_body)
        self.assertNotIn('vertices = tuple(getattr(submesh, "vertices", ()) or ())', mesh_editor_native_body)
        self.assertNotIn('faces = tuple(getattr(submesh, "faces", ()) or ())', mesh_editor_native_body)
        self.assertNotIn('"positions": vertices', mesh_editor_native_body)
        self.assertNotIn('"normals": normals', mesh_editor_native_body)
        self.assertNotIn('"texture_coordinates": uvs', mesh_editor_native_body)
        self.assertNotIn('"faces": faces', mesh_editor_native_body)
        self.assertNotIn('"source_vertex_indices": list(range(len(vertices)))', mesh_editor_native_body)
        self.assertNotIn('"source_face_indices": list(range(len(faces)))', mesh_editor_native_body)
        self.assertNotIn("def _mesh_to_native_preview_python_reference(", mesh_editor_payload_source)
        self.assertNotIn("def _empty_native_preview_data(", mesh_editor_payload_source)
        self.assertNotIn("def _vertex_blob(", mesh_editor_payload_source)

    def test_native_mesh_fallback_telemetry_guards_long_harness(self) -> None:
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        service_source = _read("cdmw/services/mesh_service.py")
        kernel_source = _read("cdmw/services/mesh_service_kernel.py")
        edit_ops_source = _read("cdmw/modding/mesh_edit_ops.py")
        mesh_deformer_source = _read("cdmw/modding/mesh_deformer.py")
        payload_source = _read("cdmw/ui/mesh_editor/native_preview_payloads.py")
        harness_source = _read("tools/mesh_harness/native_workflow.py")

        self.assertIn("def record_native_mesh_core_fallback(", bridge_source)
        self.assertIn("def native_mesh_core_fallback_counts(", bridge_source)
        self.assertIn("def native_mesh_core_fallback_events(", bridge_source)
        self.assertIn("def clear_native_mesh_core_fallback_counts(", bridge_source)
        self.assertIn("native_mesh_core_fallback_events", service_source)
        self.assertIn("fallback_event_start = len(native_mesh_core_fallback_events())", service_source)
        self.assertIn("def _native_blocked_fallback_diagnostics(", kernel_source)
        self.assertIn("Edit was not applied: native mesh core failed and Python fallback was blocked", kernel_source)
        self.assertIn("_append_unique_diagnostics(", kernel_source)
        self.assertIn("def _allow_python_history_restore_fallback(", service_source)
        self.assertIn('f"{operation}.blocked"', service_source)
        self.assertIn('"history.sparse_restore"', service_source)
        self.assertIn('"history.restore_normals"', service_source)
        history_restore_start = service_source.index("def _allow_python_history_restore_fallback(")
        history_restore_body = service_source[
            history_restore_start: service_source.index("def _allow_python_history_snapshot_fallback(", history_restore_start)
        ]
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT", history_restore_body)
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_FACE_LIMIT", history_restore_body)
        self.assertIn("Python mesh history restore fallback blocked while native mesh core is available", history_restore_body)
        restore_deltas_start = service_source.index("def _restore_vertex_position_deltas(")
        restore_deltas_body = service_source[restore_deltas_start: service_source.index("def _delta_positions_by_vertex(", restore_deltas_start)]
        self.assertLess(
            restore_deltas_body.index('_allow_python_history_restore_fallback(mesh, deltas, "history.sparse_restore")'),
            restore_deltas_body.index("_current_vertex_position_deltas(mesh, deltas)"),
        )
        self.assertLess(
            restore_deltas_body.index('_allow_python_history_restore_fallback(mesh, deltas, "history.restore_normals")'),
            restore_deltas_body.index("recompute_mesh_normals(mesh)"),
        )
        self.assertIn("_record_native_edit_fallback(mesh, \"live_edit.transform\"", edit_ops_source)
        self.assertNotIn("_PYTHON_MESH_EDIT_FALLBACK_VERTEX_LIMIT", edit_ops_source)
        self.assertNotIn("_PYTHON_MESH_EDIT_FALLBACK_FACE_LIMIT", edit_ops_source)
        self.assertIn("def _allow_python_mesh_edit_fallback(", edit_ops_source)
        self.assertIn("Python mesh edit fallback blocked while native mesh core is available", edit_ops_source)
        self.assertIn('f"{operation}.blocked"', edit_ops_source)
        self.assertNotIn("enumerate(tuple(submesh.faces or ()))", edit_ops_source)
        self.assertNotIn("for face in tuple(submesh.faces or ())", edit_ops_source)
        self.assertNotIn("vertices = tuple(submesh.vertices or ())", service_source)
        self.assertNotIn("for face in tuple(submesh.faces or ())", service_source)
        self.assertNotIn("_PYTHON_SELECTION_EXPANSION_FALLBACK_VERTEX_LIMIT", mesh_deformer_source)
        self.assertNotIn("_PYTHON_SELECTION_EXPANSION_FALLBACK_FACE_LIMIT", mesh_deformer_source)
        self.assertIn("def _allow_python_selection_expansion_fallback(", mesh_deformer_source)
        self.assertIn("Python selection expansion fallback blocked while native mesh core is available", mesh_deformer_source)
        self.assertIn("def _valid_source_indices(", mesh_deformer_source)
        self.assertNotIn("for raw_vertex in tuple(raw_vertices or ())", mesh_deformer_source)
        self.assertNotIn("for raw_index in tuple(source_indices or ())", mesh_deformer_source)
        self.assertNotIn("enumerate(tuple(submesh.faces or ()))", mesh_deformer_source)
        grow_selection_start = mesh_deformer_source.index("def grow_vertex_selection(")
        grow_selection_body = mesh_deformer_source[
            grow_selection_start: mesh_deformer_source.index("def shrink_vertex_selection(", grow_selection_start)
        ]
        self.assertIn('"selection.grow"', grow_selection_body)
        self.assertLess(
            grow_selection_body.index("_allow_python_selection_expansion_fallback("),
            grow_selection_body.index("build_vertex_adjacency("),
        )
        shrink_selection_start = mesh_deformer_source.index("def shrink_vertex_selection(")
        shrink_selection_body = mesh_deformer_source[
            shrink_selection_start: mesh_deformer_source.index("def smooth_vertex_selection(", shrink_selection_start)
        ]
        self.assertIn('"selection.shrink"', shrink_selection_body)
        self.assertLess(
            shrink_selection_body.index("_allow_python_selection_expansion_fallback("),
            shrink_selection_body.index("build_vertex_adjacency("),
        )
        smooth_selection_start = mesh_deformer_source.index("def smooth_vertex_selection(")
        smooth_selection_body = mesh_deformer_source[
            smooth_selection_start: mesh_deformer_source.index("def invert_vertex_selection(", smooth_selection_start)
        ]
        self.assertIn('"selection.smooth"', smooth_selection_body)
        self.assertLess(
            smooth_selection_body.index("_allow_python_selection_expansion_fallback("),
            smooth_selection_body.index("build_vertex_adjacency("),
        )
        invert_selection_start = mesh_deformer_source.index("def invert_vertex_selection(")
        invert_selection_body = mesh_deformer_source[
            invert_selection_start: mesh_deformer_source.index("def select_all_vertex_selection(", invert_selection_start)
        ]
        self.assertIn("target_sources = _valid_source_indices(mesh, source_indices)", invert_selection_body)
        self.assertLess(
            invert_selection_body.index("_allow_python_selection_expansion_fallback("),
            invert_selection_body.index("set(range(vertex_count))"),
        )
        select_all_selection_start = mesh_deformer_source.index("def select_all_vertex_selection(")
        select_all_selection_body = mesh_deformer_source[
            select_all_selection_start: mesh_deformer_source.index("def build_x_mirror_pairs(", select_all_selection_start)
        ]
        self.assertIn("target_sources = _valid_source_indices(mesh, source_indices)", select_all_selection_body)
        self.assertLess(
            select_all_selection_body.index("_allow_python_selection_expansion_fallback("),
            select_all_selection_body.index("set(range(vertex_count))"),
        )
        self.assertIn("def _recompute_normals_after_native_edit(", edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "normals.recalculate"', edit_ops_source)
        transform_start = edit_ops_source.index("def _transform(")
        transform_body = edit_ops_source[transform_start: edit_ops_source.index("def _mirror_pairs_for_submesh(", transform_start)]
        self.assertIn("_recompute_normals_after_native_edit(", transform_body)
        self.assertNotIn("native_normals = apply_native_mesh_recalculate_normals(mesh, set(native_changed))", transform_body)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "live_edit.transform"', edit_ops_source)
        self.assertIn("python_expansion_domains = selection.edge_map() or selection.face_map() or set(selection.source_indices)", transform_body)
        self.assertLess(
            transform_body.index("python_expansion_domains = selection.edge_map() or selection.face_map() or set(selection.source_indices)"),
            transform_body.index("vertices_by_submesh = _selected_vertices(mesh, selection"),
        )
        self.assertLess(
            transform_body.index('"live_edit.transform"'),
            transform_body.index("vertices_by_submesh = _selected_vertices(mesh, selection"),
        )
        brush_start = edit_ops_source.index("def _brush(")
        brush_body = edit_ops_source[brush_start: edit_ops_source.index("def _delete(", brush_start)]
        self.assertIn("python_expansion_domains = selection.edge_map() or selection.face_map() or set(selection.source_indices)", brush_body)
        self.assertLess(
            brush_body.index("python_expansion_domains = selection.edge_map() or selection.face_map() or set(selection.source_indices)"),
            brush_body.index("selected = _selected_vertices(mesh, selection"),
        )
        self.assertLess(
            brush_body.index("python_expansion_domains and not _allow_python_mesh_edit_fallback("),
            brush_body.index("selected = _selected_vertices(mesh, selection"),
        )
        self.assertIn("\"topology.delete\"", edit_ops_source)
        self.assertIn("\"topology.dissolve\"", edit_ops_source)
        self.assertIn("\"topology.extrude\"", edit_ops_source)
        self.assertIn("\"topology.inset\"", edit_ops_source)
        self.assertIn("\"topology.subdivide\"", edit_ops_source)
        self.assertIn("\"topology.refine_smooth\"", edit_ops_source)
        self.assertIn("\"topology.split\"", edit_ops_source)
        self.assertIn("\"topology.fix_winding\"", edit_ops_source)
        self.assertIn("\"topology.fill_holes\"", edit_ops_source)
        self.assertIn("\"topology.triangulate_display\"", edit_ops_source)
        self.assertIn("\"topology.bridge\"", edit_ops_source)
        self.assertIn("\"topology.fill\"", edit_ops_source)
        self.assertIn("\"topology.edge_split\"", edit_ops_source)
        self.assertIn("\"topology.duplicate\"", edit_ops_source)
        self.assertIn("\"topology.separate\"", edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.delete"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.dissolve"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.extrude"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.inset"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.subdivide"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.refine_smooth"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.split"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.fix_winding"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.fill_holes"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.triangulate_display"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.bridge"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.duplicate"', edit_ops_source)
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.separate"', edit_ops_source)
        dissolve_start = edit_ops_source.index("def _dissolve(")
        dissolve_body = edit_ops_source[dissolve_start: edit_ops_source.index("def _delete_submeshes(", dissolve_start)]
        self.assertIn("apply_native_mesh_dissolve(", dissolve_body)
        self.assertLess(
            dissolve_body.index("apply_native_mesh_dissolve("),
            dissolve_body.index("_dissolve_internal_edges(mesh, edges)"),
        )
        extrude_start = edit_ops_source.index("def _extrude(")
        extrude_body = edit_ops_source[extrude_start: edit_ops_source.index("def _extrude_edges(", extrude_start)]
        self.assertIn("apply_native_mesh_extrude(", extrude_body)
        self.assertLess(
            extrude_body.index("apply_native_mesh_extrude("),
            extrude_body.index("_selected_faces(mesh, selection"),
        )
        inset_start = edit_ops_source.index("def _inset(")
        inset_body = edit_ops_source[inset_start: edit_ops_source.index("def _inset_amount(", inset_start)]
        self.assertIn("apply_native_mesh_inset(", inset_body)
        self.assertLess(
            inset_body.index("apply_native_mesh_inset("),
            inset_body.index("_selected_faces(mesh, selection"),
        )
        fix_winding_start = edit_ops_source.index("def _fix_winding(")
        fix_winding_body = edit_ops_source[fix_winding_start: edit_ops_source.index("def _fill_holes(", fix_winding_start)]
        self.assertIn("apply_native_mesh_fix_winding(mesh, target_indices", fix_winding_body)
        self.assertLess(
            fix_winding_body.index("apply_native_mesh_fix_winding(mesh, target_indices"),
            fix_winding_body.index("for submesh_index in target_indices:"),
        )
        fill_holes_start = edit_ops_source.index("def _fill_holes(")
        fill_holes_body = edit_ops_source[fill_holes_start: edit_ops_source.index("def _triangulate_display(", fill_holes_start)]
        self.assertIn("apply_native_mesh_fill_holes(mesh, target_indices", fill_holes_body)
        self.assertLess(
            fill_holes_body.index("apply_native_mesh_fill_holes(mesh, target_indices"),
            fill_holes_body.index("for submesh_index in target_indices:"),
        )
        triangulate_start = edit_ops_source.index("def _triangulate_display(")
        triangulate_body = edit_ops_source[triangulate_start: edit_ops_source.index("def _closed_edge_loop_order(", triangulate_start)]
        self.assertIn("apply_native_mesh_triangulate_display(", triangulate_body)
        self.assertLess(
            triangulate_body.index("apply_native_mesh_triangulate_display("),
            triangulate_body.index("for submesh_index in target_indices:"),
        )
        bridge_start = edit_ops_source.index("def _bridge(")
        bridge_body = edit_ops_source[bridge_start: edit_ops_source.index("def _surface_channel_target_indices(", bridge_start)]
        self.assertIn("apply_native_mesh_bridge(mesh, selected_edges", bridge_body)
        self.assertLess(
            bridge_body.index("apply_native_mesh_bridge(mesh, selected_edges"),
            bridge_body.index("for submesh_index, edges in selected_edges.items():"),
        )
        fill_start = edit_ops_source.index("def _fill(")
        fill_body = edit_ops_source[fill_start: edit_ops_source.index("def _remove_doubles(", fill_start)]
        self.assertIn("apply_native_mesh_fill(", fill_body)
        self.assertIn("_allow_python_mesh_edit_fallback(", fill_body)
        self.assertIn('"topology.fill"', fill_body)
        self.assertLess(
            fill_body.index("apply_native_mesh_fill("),
            fill_body.index("_closed_edge_loop_order(edges)"),
        )
        edge_split_start = edit_ops_source.index("def _edge_split(")
        edge_split_body = edit_ops_source[edge_split_start: edit_ops_source.index("def _edge_key(", edge_split_start)]
        self.assertIn("apply_native_mesh_edge_split(", edge_split_body)
        self.assertIn('"topology.edge_split"', edge_split_body)
        self.assertLess(
            edge_split_body.index("apply_native_mesh_edge_split("),
            edge_split_body.index("for submesh_index, edges in selected_edges.items():"),
        )
        duplicate_start = edit_ops_source.index("def _duplicate(")
        duplicate_body = edit_ops_source[duplicate_start: edit_ops_source.index("def _mirror(", duplicate_start)]
        self.assertIn("apply_native_mesh_duplicate(", duplicate_body)
        self.assertLess(
            duplicate_body.index("apply_native_mesh_duplicate("),
            duplicate_body.index("_selected_faces(mesh, selection"),
        )
        self.assertLess(
            duplicate_body.index('_allow_python_mesh_edit_fallback(mesh, "topology.duplicate"'),
            duplicate_body.index("_selected_faces(mesh, selection"),
        )
        self.assertLess(
            duplicate_body.index("apply_native_mesh_duplicate("),
            duplicate_body.index("_append_face_copy("),
        )
        separate_start = edit_ops_source.index("def _separate(")
        separate_body = edit_ops_source[separate_start: edit_ops_source.index("def _duplicate(", separate_start)]
        self.assertIn("apply_native_mesh_separate(", separate_body)
        self.assertLess(
            separate_body.index("apply_native_mesh_separate("),
            separate_body.index("_selected_faces(mesh, selection"),
        )
        self.assertLess(
            separate_body.index('_allow_python_mesh_edit_fallback(mesh, "topology.separate"'),
            separate_body.index("_selected_faces(mesh, selection"),
        )
        self.assertLess(
            separate_body.index("apply_native_mesh_separate("),
            separate_body.index("split_faces_to_submesh("),
        )
        split_deformer_start = mesh_deformer_source.index("def split_faces_to_submesh(")
        split_deformer_body = mesh_deformer_source[
            split_deformer_start: mesh_deformer_source.index("def subdivide_faces_touching_vertices(", split_deformer_start)
        ]
        self.assertNotIn("dict(selected_faces_by_submesh or {}).items()", split_deformer_body)
        self.assertNotIn("dict(selected_vertices_by_submesh or {}).items()", split_deformer_body)
        self.assertNotIn("enumerate(tuple(source.faces or ()))", split_deformer_body)
        subdivide_deformer_start = mesh_deformer_source.index("def subdivide_faces_touching_vertices(")
        subdivide_deformer_body = mesh_deformer_source[
            subdivide_deformer_start: mesh_deformer_source.index("def _vec3", subdivide_deformer_start)
        ]
        self.assertNotIn("dict(selected_faces_by_submesh or {}).items()", subdivide_deformer_body)
        self.assertNotIn("dict(selected_vertices_by_submesh or {}).items()", subdivide_deformer_body)
        self.assertNotIn("enumerate(tuple(submesh.faces or ()))", subdivide_deformer_body)
        self.assertIn("_record_native_preview_fallback(mesh, \"preview_geometry\"", payload_source)
        self.assertIn("\"preview_vertex_update\"", payload_source)
        self.assertIn("\"preview_triangle_group\"", payload_source)
        self.assertIn("\"selection_overlay\"", payload_source)
        self.assertIn("clear_native_mesh_core_fallback_counts()", harness_source)
        self.assertIn("native_available = native_mesh_core_available()", harness_source)
        self.assertIn("fallback_ok = not (native_available and fallback_counts)", harness_source)
        self.assertIn("'native_fallback_counts': fallback_counts", harness_source)
        self.assertIn("'native_fallback_events': fallback_events", harness_source)
        self.assertIn("toggle_persistence_ok = _mesh_geometry_signature(after) == _mesh_geometry_signature(toggled)", harness_source)
        self.assertIn("'toggle_persistence_ok': toggle_persistence_ok", harness_source)

    def test_morph_slider_apply_is_native_owned_before_python_fallback(self) -> None:
        morph_source = _read("cdmw/modding/mesh_morph_sliders.py")
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        native_source = _read("native/cdmw_mesh_core/src/main.cpp")
        morph_state_source = _read("cdmw/ui/archive_browser/static_replacement_morph_slider_state.py")
        static_callbacks_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py")

        apply_start = morph_source.index("def apply_morph_slider_values(")
        apply_body = morph_source[apply_start:morph_source.index("def _safe_slider_id", apply_start)]
        self.assertIn("native_result = _apply_native_morph_slider_values", apply_body)
        self.assertLess(apply_body.index("native_result ="), apply_body.index("result = clone_mesh_for_editing"))
        self.assertIn('_allow_python_morph_fallback(base_mesh, "morph_apply")', apply_body)
        self.assertLess(
            apply_body.index('_allow_python_morph_fallback(base_mesh, "morph_apply")'),
            apply_body.index("result = clone_mesh_for_editing"),
        )
        build_delta_start = morph_source.index("def build_morph_delta(")
        build_delta_body = morph_source[build_delta_start:morph_source.index("def _vec3", build_delta_start)]
        self.assertIn("native_deltas = _build_native_morph_delta", build_delta_body)
        self.assertIn("validate_morph_target(base_mesh, target_mesh)", build_delta_body)
        self.assertIn('_allow_python_morph_fallback(base_mesh, "morph_target_delta")', build_delta_body)
        self.assertLess(
            build_delta_body.index("native_deltas = _build_native_morph_delta"),
            build_delta_body.index("validate_morph_target(base_mesh, target_mesh)"),
        )
        self.assertLess(
            build_delta_body.index('_allow_python_morph_fallback(base_mesh, "morph_target_delta")'),
            build_delta_body.index("validate_morph_target(base_mesh, target_mesh)"),
        )
        self.assertNotIn("_PYTHON_MORPH_FALLBACK_VERTEX_LIMIT", morph_source)
        self.assertNotIn("_PYTHON_MORPH_FALLBACK_FACE_LIMIT", morph_source)
        morph_fallback_start = morph_source.index("def _allow_python_morph_fallback(")
        morph_fallback_body = morph_source[morph_fallback_start:morph_source.index("def _mesh_count_hint(", morph_fallback_start)]
        self.assertNotIn("<= _PYTHON_MORPH_FALLBACK", morph_fallback_body)
        self.assertIn("Python morph fallback blocked while native mesh core is available", morph_fallback_body)
        self.assertIn("def _build_native_morph_delta(", morph_source)
        self.assertIn("build_native_morph_target_delta(base_mesh, target_mesh)", morph_source)
        self.assertIn('"morph_target_delta"', morph_source)
        self.assertIn("def _apply_native_morph_slider_values(", morph_source)
        self.assertIn("record_native_mesh_core_fallback(", morph_source)
        topology_start = morph_source.index("def _topology_faces(")
        topology_body = morph_source[topology_start:morph_source.index("def _signature_matches(", topology_start)]
        self.assertNotIn('tuple(getattr(submesh, "faces", ()) or ())', topology_body)
        self.assertNotIn('len(tuple(getattr(submesh, "vertices", ()) or ()))', topology_body)
        validate_start = morph_source.index("def validate_morph_target(")
        validate_body = morph_source[validate_start:morph_source.index("def _morph_target_basic_identity_compatible(", validate_start)]
        self.assertNotIn('base_vertices = tuple(getattr(base_submesh, "vertices", ()) or ())', validate_body)
        self.assertNotIn('target_vertices = tuple(getattr(target_submesh, "vertices", ()) or ())', validate_body)
        selection_start = morph_source.index("def _normalized_vertex_selection(")
        selection_body = morph_source[selection_start:morph_source.index("def _feathered_selection_weights(", selection_start)]
        self.assertNotIn('len(tuple(getattr(mesh.submeshes[submesh_index], "vertices", ()) or ()))', selection_body)
        self.assertNotIn("for raw_vertex_index in tuple(raw_vertex_indices or ())", selection_body)
        region_start = morph_source.index("def build_region_volume_delta(")
        region_body = morph_source[region_start:morph_source.index("def _post_edit_delta_at", region_start)]
        self.assertIn("native_deltas = _build_native_region_volume_delta", region_body)
        self.assertIn("_compute_smooth_normals(submesh.vertices, submesh.faces)", region_body)
        self.assertLess(region_body.index("native_deltas ="), region_body.index("_compute_smooth_normals("))
        self.assertIn('_allow_python_morph_fallback(base_mesh, "region_volume_delta")', region_body)
        self.assertLess(
            region_body.index('_allow_python_morph_fallback(base_mesh, "region_volume_delta")'),
            region_body.index("_compute_smooth_normals("),
        )
        self.assertNotIn("normal_mesh = clone_mesh_for_editing", region_body)
        self.assertNotIn("recompute_mesh_normals(normal_mesh)", region_body)
        self.assertNotIn('tuple(getattr(submesh, "vertices", ()) or ())', region_body)
        self.assertNotIn('tuple(getattr(normal_submesh, "normals", ()) or ())', region_body)
        write_region_start = morph_source.index("def _write_region_delta_file(")
        write_region_body = morph_source[
            write_region_start: morph_source.index("def create_region_volume_slider_profile(", write_region_start)
        ]
        self.assertNotIn("dict(selected_vertices_by_submesh or {}).items()", write_region_body)
        self.assertIn("def _build_native_region_volume_delta(", morph_source)
        self.assertIn('"region_volume_delta"', morph_source)

        self.assertIn("def apply_native_morph_slider_values(", bridge_source)
        self.assertIn("def build_native_region_volume_delta(", bridge_source)
        self.assertIn("def build_native_morph_post_edit_deltas(", bridge_source)
        self.assertIn("def build_native_morph_target_delta(", bridge_source)
        self.assertIn('"morph-apply-json"', bridge_source)
        self.assertIn('"morph-post-edit-delta-json"', bridge_source)
        self.assertIn('"morph-target-delta-json"', bridge_source)
        self.assertIn('"region-volume-delta-json"', bridge_source)
        self.assertIn("def _read_vec3_binary_payload(", bridge_source)
        self.assertIn("_ensure_native_mesh_session_submesh(", bridge_source)
        self.assertIn('"deltas_binary": _write_vec3_binary_payload', bridge_source)
        self.assertIn('"post_edit_deltas_binary"] = _write_vec3_binary_payload', bridge_source)
        self.assertIn('"apply_native_morph_slider_values"', bridge_source)
        self.assertIn('"build_native_morph_post_edit_deltas"', bridge_source)
        self.assertIn('"build_native_morph_target_delta"', bridge_source)
        self.assertIn('"build_native_region_volume_delta"', bridge_source)
        morph_apply_bridge_start = bridge_source.index("def apply_native_morph_slider_values(")
        morph_apply_bridge_body = bridge_source[
            morph_apply_bridge_start: bridge_source.index("def build_native_morph_post_edit_deltas(", morph_apply_bridge_start)
        ]
        self.assertIn("_ensure_native_mesh_session_submesh(", morph_apply_bridge_body)
        self.assertIn('item["session_id"] = session_id', morph_apply_bridge_body)
        self.assertIn("vertices = submesh.vertices or ()", morph_apply_bridge_body)
        self.assertIn("base_snapshot = snapshot_native_mesh_submeshes(base_mesh", morph_apply_bridge_body)
        self.assertIn("result = ParsedMesh()", morph_apply_bridge_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(result, base_snapshot", morph_apply_bridge_body)
        self.assertIn("dispose_native_mesh_submesh_snapshot(", morph_apply_bridge_body)
        self.assertIn("_invalidate_native_mesh_session_submeshes(result, range(len(result.submeshes)))", morph_apply_bridge_body)
        self.assertNotIn("clone_mesh_for_editing(base_mesh)", morph_apply_bridge_body)
        self.assertNotIn("vertices = tuple(submesh.vertices or ())", morph_apply_bridge_body)
        self.assertNotIn("post_values = tuple(submesh_values(post_edit_deltas, submesh_index) or ())", morph_apply_bridge_body)
        self.assertNotIn("for delta_index, delta in enumerate(tuple(deltas or ()))", morph_apply_bridge_body)
        self.assertNotIn('enumerate(tuple(getattr(delta, "deltas", ()) or ()))', morph_apply_bridge_body)
        post_edit_bridge_start = bridge_source.index("def build_native_morph_post_edit_deltas(")
        post_edit_bridge_body = bridge_source[
            post_edit_bridge_start: bridge_source.index("def build_native_morph_target_delta(", post_edit_bridge_start)
        ]
        self.assertNotIn('working_vertices = tuple(getattr(working_submesh, "vertices", ()) or ())', post_edit_bridge_body)
        self.assertNotIn('slider_vertices = tuple(getattr(slider_submesh, "vertices", ()) or ())', post_edit_bridge_body)
        self.assertIn('if bool(raw_item.get("zero_delta")):', post_edit_bridge_body)
        self.assertIn("outputs[submesh_index] = []", post_edit_bridge_body)
        target_delta_bridge_start = bridge_source.index("def build_native_morph_target_delta(")
        target_delta_bridge_body = bridge_source[
            target_delta_bridge_start: bridge_source.index("def build_native_region_volume_delta(", target_delta_bridge_start)
        ]
        self.assertNotIn('base_vertices = tuple(getattr(base_submesh, "vertices", ()) or ())', target_delta_bridge_body)
        self.assertNotIn('target_vertices = tuple(getattr(target_submesh, "vertices", ()) or ())', target_delta_bridge_body)

        capture_start = morph_state_source.index("def morph_slider_capture_post_edit_deltas(")
        capture_body = morph_state_source[
            capture_start: morph_state_source.index("def morph_slider_expected_vertex_counts", capture_start)
        ]
        self.assertIn("native_result = _morph_slider_native_post_edit_deltas", capture_body)
        self.assertIn("return _morph_slider_capture_post_edit_deltas_fallback", capture_body)
        self.assertIn(
            "_allow_python_morph_post_edit_delta_fallback(working_mesh, slider_only_mesh)",
            capture_body,
        )
        self.assertLess(
            capture_body.index("native_result = _morph_slider_native_post_edit_deltas"),
            capture_body.index("return _morph_slider_capture_post_edit_deltas_fallback"),
        )
        self.assertLess(
            capture_body.index("_allow_python_morph_post_edit_delta_fallback(working_mesh, slider_only_mesh)"),
            capture_body.index("return _morph_slider_capture_post_edit_deltas_fallback"),
        )
        self.assertIn("build_native_morph_post_edit_deltas(working_mesh, slider_only_mesh)", morph_state_source)
        self.assertIn('"morph_post_edit_delta"', morph_state_source)
        self.assertNotIn("_PYTHON_MORPH_POST_EDIT_FALLBACK_VERTEX_LIMIT", morph_state_source)
        morph_post_fallback_start = morph_state_source.index("def _allow_python_morph_post_edit_delta_fallback(")
        morph_post_fallback_body = morph_state_source[
            morph_post_fallback_start: morph_state_source.index("def morph_slider_zero_post_edit_deltas(", morph_post_fallback_start)
        ]
        self.assertNotIn("<= _PYTHON_MORPH_POST_EDIT_FALLBACK_VERTEX_LIMIT", morph_post_fallback_body)
        self.assertIn(
            "Python morph post-edit delta fallback blocked while native mesh core is available",
            morph_post_fallback_body,
        )
        vertex_count_start = morph_state_source.index("def _morph_slider_vertex_count(")
        vertex_count_body = morph_state_source[
            vertex_count_start: morph_state_source.index("def _morph_slider_native_post_edit_deltas(", vertex_count_start)
        ]
        self.assertNotIn('len(tuple(getattr(submesh, "vertices", ()) or ()))', vertex_count_body)
        fallback_start = morph_state_source.index("def _morph_slider_capture_post_edit_deltas_fallback(")
        fallback_body = morph_state_source[
            fallback_start: morph_state_source.index("def morph_slider_capture_post_edit_deltas(", fallback_start)
        ]
        self.assertNotIn('tuple(getattr(working_submesh, "vertices", ()) or ())', fallback_body)
        self.assertNotIn('tuple(getattr(slider_submesh, "vertices", ()) or ())', fallback_body)
        expected_counts_start = morph_state_source.index("def morph_slider_expected_vertex_counts(")
        expected_counts_body = morph_state_source[
            expected_counts_start: morph_state_source.index("def morph_slider_post_edit_deltas_need_reset(", expected_counts_start)
        ]
        self.assertNotIn('len(tuple(getattr(submesh, "vertices", ()) or ()))', expected_counts_body)
        zero_post_start = morph_state_source.index("def morph_slider_zero_post_edit_deltas(")
        zero_post_body = morph_state_source[
            zero_post_start: morph_state_source.index("def _morph_slider_capture_post_edit_deltas_fallback(", zero_post_start)
        ]
        self.assertIn("return []", zero_post_body)
        self.assertNotIn("for _vertex in", zero_post_body)
        reset_start = morph_state_source.index("def morph_slider_post_edit_deltas_need_reset(")
        reset_body = morph_state_source[
            reset_start: morph_state_source.index("def morph_slider_zero_post_edit_deltas_for_sources(", reset_start)
        ]
        self.assertIn("if not post_edit_deltas:", reset_body)
        self.assertIn("len(post_edit_deltas[index]) not in {0, int(expected_count)}", reset_body)

        self.assertIn("struct SubmeshMorphApplyResult", native_source)
        self.assertIn("struct SubmeshMorphPostEditDeltaResult", native_source)
        self.assertIn("struct SubmeshRegionVolumeDeltaResult", native_source)
        self.assertIn("std::vector<SubmeshMorphApplyResult> run_morph_apply", native_source)
        self.assertIn("std::vector<SubmeshMorphPostEditDeltaResult> run_morph_post_edit_delta", native_source)
        self.assertIn("std::vector<SubmeshMorphPostEditDeltaResult> run_morph_target_delta", native_source)
        self.assertIn("std::vector<SubmeshRegionVolumeDeltaResult> run_region_volume_delta", native_source)
        self.assertIn("region_volume_selection_weights", native_source)
        self.assertIn("morph_delta_for_submesh", native_source)
        self.assertIn("compute_smooth_normals(vertices, faces)", native_source)
        self.assertIn("write_vec3_binary_file(vertices_path, vertices)", native_source)
        self.assertIn("bool zero_delta = false;", native_source)
        self.assertIn("zero_delta", native_source)
        self.assertIn('if (command == "morph-apply-json") return morph_apply_json_command(job_path, report_path);', native_source)
        self.assertIn('if (command == "morph-post-edit-delta-json") return morph_post_edit_delta_json_command(job_path, report_path);', native_source)
        self.assertIn('if (command == "morph-target-delta-json") return morph_target_delta_json_command(job_path, report_path);', native_source)
        self.assertIn('if (command == "region-volume-delta-json") return region_volume_delta_json_command(job_path, report_path);', native_source)

        static_bake_body = _function_source(static_callbacks_source, "_morph_slider_bake")
        static_bake_clone_body = _function_source(static_callbacks_source, "_morph_slider_clone_working_mesh_for_bake")
        self.assertNotIn("def _morph_slider_python_bake_clone_fallback_allowed", static_callbacks_source)
        self.assertNotIn('"morph_slider.bake_clone"', static_callbacks_source)
        self.assertNotIn("morph_slider_python_bake_clone_fallback_blocked", static_callbacks_source)
        self.assertNotIn("clone_mesh_for_static_replacement_native_first(", static_bake_clone_body)
        self.assertNotIn("fallback_allowed=_morph_slider_python_bake_clone_fallback_allowed", static_bake_clone_body)
        self.assertIn("snapshot_native_mesh_submeshes(mesh)", static_bake_clone_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(baked_mesh, native_snapshot)", static_bake_clone_body)
        self.assertIn("morph_slider_native_bake_snapshot_failed", static_bake_clone_body)
        self.assertNotIn("return clone_mesh_for_editing(mesh)", static_bake_clone_body)
        self.assertLess(
            static_bake_body.index("baked_base_mesh = _callbacks._morph_slider_clone_working_mesh_for_bake()"),
            static_bake_body.index("_callbacks._morph_slider_begin_change(bake_state.change_label)"),
        )
        self.assertIn("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices(), replace_all=True)", static_bake_body)
        self.assertNotIn("clone_mesh_for_editing(_mesh_edit_state.replacement_mesh_for_mapping)", static_bake_body)
        self.assertNotIn("_queue_static_preview_rebuild()", static_bake_body)
        static_apply_body = _function_source(static_callbacks_source, "_morph_slider_apply_to_working_mesh")
        static_capture_body = _function_source(static_callbacks_source, "_morph_slider_capture_post_edit_deltas")
        self.assertIn("except Exception as exc:", static_capture_body)
        self.assertIn('_state.morph_slider_topology_blocked["blocked"] = True', static_capture_body)
        self.assertIn("_state.self.set_status_message(str(exc))", static_capture_body)
        self.assertIn("if _state._mesh_edit_tab_active():", static_apply_body)
        self.assertNotIn("if _state._mesh_edit_tab_active() and not _state._alignment_d3d11_preview_active():", static_apply_body)
        self.assertIn("Python mesh mutation fallback is disabled", static_apply_body)
        self.assertLess(
            static_apply_body.index("if _state._mesh_edit_tab_active():"),
            static_apply_body.index("_state.apply_morph_slider_values("),
        )
        active_apply_body = static_apply_body[
            static_apply_body.index("if _state._mesh_edit_tab_active():"):
            static_apply_body.index("_callbacks._morph_slider_ensure_post_edit_deltas()")
        ]
        self.assertIn("_callbacks._mesh_edit_mark_native_preview_stale(", active_apply_body)
        self.assertIn("return False", active_apply_body)
        self.assertNotIn("_state._queue_static_preview_rebuild()", active_apply_body)
        self.assertIn("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)", static_apply_body)
        self.assertIn("if _state._alignment_d3d11_preview_active():", static_apply_body)
        self.assertIn("_callbacks._mesh_edit_update_live_preview(", static_apply_body)
        self.assertIn("_state._mesh_edit_all_live_vertices_for_sources(_state._mesh_edit_preview_source_indices())", static_apply_body)
        self.assertIn("include_normals=True", static_apply_body)
        self.assertIn("immediate=True", static_apply_body)
        self.assertIn("elif _state._mesh_edit_tab_active():", static_apply_body)
        self.assertIn("Active Mesh Editor morph-slider apply requires native geometry execution", static_apply_body)
        self.assertLess(
            static_apply_body.index("if _state._alignment_d3d11_preview_active():"),
            static_apply_body.index("_state._queue_static_preview_rebuild()"),
        )

    def test_static_whole_source_selection_stays_range_based(self) -> None:
        state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")
        d3d11_source = _read("cdmw/ui/native_d3d11_preview_host.py")
        panel_source = _read("cdmw/ui/native_preview_panel.py")

        helper_start = state_source.index("def mesh_edit_all_vertices_by_source(")
        helper_body = state_source[helper_start: state_source.index("def mesh_edit_inverted_vertex_selection(", helper_start)]
        self.assertIn("selection: dict[int, range] = {}", helper_body)
        self.assertIn("selection[source_index] = range(vertex_count)", helper_body)
        self.assertNotIn("set(range(vertex_count))", helper_body)
        self.assertIn("if isinstance(raw_values, range):", d3d11_source)
        self.assertIn("if isinstance(raw_values, range):", panel_source)

    def test_static_donor_alignment_is_native_owned_before_python_fallback(self) -> None:
        builder_source = _read("cdmw/modding/mesh_builder_common.py")
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        native_source = _read("native/cdmw_mesh_core/src/main.cpp")

        choose_start = builder_source.index("def _choose_static_donor_indices(")
        choose_body = builder_source[choose_start:builder_source.index("def _combine_static_submeshes", choose_start)]
        self.assertIn("native_donor_indices = _build_native_static_donor_indices(orig_sm, new_sm)", choose_body)
        self.assertLess(
            choose_body.index("native_donor_indices = _build_native_static_donor_indices"),
            choose_body.index("donor_indices = _align_static_vertex_sequences"),
        )
        self.assertIn("def _build_native_static_donor_indices(", builder_source)
        self.assertIn("build_native_static_donor_indices(orig_sm, new_sm)", builder_source)

        self.assertIn("def build_native_static_donor_indices(", bridge_source)
        donor_bridge_start = bridge_source.index("def build_native_static_donor_indices(")
        donor_bridge_body = bridge_source[
            donor_bridge_start: bridge_source.index("def _apply_native_skin_weight_report", donor_bridge_start)
        ]
        self.assertNotIn('original_vertices = tuple(getattr(original_submesh, "vertices", ()) or ())', donor_bridge_body)
        self.assertNotIn('new_vertices = tuple(getattr(new_submesh, "vertices", ()) or ())', donor_bridge_body)
        self.assertIn('original_vertices = getattr(original_submesh, "vertices", ()) or ()', donor_bridge_body)
        self.assertIn('new_vertices = getattr(new_submesh, "vertices", ()) or ()', donor_bridge_body)
        self.assertIn('"static-donor-indices-json"', bridge_source)
        self.assertIn('"original_vertices_binary"', bridge_source)
        self.assertIn('"new_vertices_binary"', bridge_source)
        self.assertIn('"donor_indices_binary"', bridge_source)
        self.assertIn('"build_native_static_donor_indices"', bridge_source)

        self.assertIn("struct SubmeshStaticDonorIndicesResult", native_source)
        self.assertIn("std::vector<SubmeshStaticDonorIndicesResult> run_static_donor_indices", native_source)
        self.assertIn("choose_static_donor_indices_native", native_source)
        self.assertIn("align_static_donor_vertex_sequences", native_source)
        self.assertIn("nearest_static_donor_point_index", native_source)
        self.assertIn('if (command == "static-donor-indices-json") return static_donor_indices_json_command(job_path, report_path);', native_source)

    def test_obj_export_geometry_is_native_owned_before_python_fallback(self) -> None:
        exporter_source = _read("cdmw/modding/mesh_exporter.py")
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        native_source = _read("native/cdmw_mesh_core/src/main.cpp")

        export_start = exporter_source.index("def export_obj(")
        export_body = exporter_source[export_start:exporter_source.index("def _export_obj_split", export_start)]
        self.assertIn("_export_obj_native(mesh, obj_path, mtl_path, base, scale, manifest_path=sidecar_path, **native_kwargs)", export_body)
        self.assertLess(
            export_body.index("_export_obj_native(mesh, obj_path, mtl_path, base, scale, manifest_path=sidecar_path, **native_kwargs)"),
            export_body.index("for sm in mesh.submeshes:"),
        )
        self.assertIn('_allow_python_export_fallback(mesh, "export.obj")', export_body)
        self.assertLess(
            export_body.index('_allow_python_export_fallback(mesh, "export.obj")'),
            export_body.index("for sm in mesh.submeshes:"),
        )
        self.assertIn("def _export_obj_native(", exporter_source)
        self.assertIn("export_native_obj(", exporter_source)
        self.assertIn("write_native_obj_roundtrip_manifest", exporter_source)
        self.assertIn("manifest_path=sidecar_path", export_body)
        self.assertIn("def _allow_python_export_fallback(", exporter_source)
        export_fallback_body = exporter_source[
            exporter_source.index("def _allow_python_export_fallback("):
            exporter_source.index("def _mesh_count_hint(", exporter_source.index("def _allow_python_export_fallback("))
        ]
        self.assertIn("native_mesh_core_available()", export_fallback_body)
        self.assertIn("record_native_mesh_core_fallback(", export_fallback_body)
        self.assertNotIn("_PYTHON_EXPORT_FALLBACK_VERTEX_LIMIT", exporter_source)
        self.assertNotIn("_PYTHON_EXPORT_FALLBACK_FACE_LIMIT", exporter_source)
        self.assertNotIn("<= _PYTHON_EXPORT_FALLBACK", export_fallback_body)
        self.assertIn("Python export fallback blocked while native mesh core is available", export_fallback_body)

        self.assertIn("def export_native_obj(", bridge_source)
        self.assertIn("def write_native_obj_roundtrip_manifest(", bridge_source)
        self.assertIn('"obj-export-json"', bridge_source)
        self.assertIn('"obj-manifest-json"', bridge_source)
        self.assertIn('"vertices_binary"', bridge_source)
        self.assertIn('"faces_binary"', bridge_source)
        self.assertIn('"source_vertex_map_binary"', bridge_source)
        self.assertIn('"export_native_obj"', bridge_source)

        self.assertIn("struct ObjExportResult", native_source)
        self.assertIn("struct ObjRoundtripManifestSubmesh", native_source)
        self.assertIn("ObjExportResult run_obj_export", native_source)
        self.assertIn("ObjManifestResult run_obj_manifest", native_source)
        self.assertIn("write_obj_roundtrip_manifest", native_source)
        self.assertIn("obj_export_report_json", native_source)
        self.assertIn('if (command == "obj-export-json") return obj_export_json_command(job_path, report_path);', native_source)
        self.assertIn('if (command == "obj-manifest-json") return obj_manifest_json_command(job_path, report_path);', native_source)

    def test_fbx_export_geometry_arrays_are_native_owned_before_python_fallback(self) -> None:
        exporter_source = _read("cdmw/modding/mesh_exporter.py")
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        native_source = _read("native/cdmw_mesh_core/src/main.cpp")

        export_start = exporter_source.index("def export_fbx(")
        export_body = exporter_source[export_start:exporter_source.index("def export_fbx_with_skeleton", export_start)]
        self.assertIn("_export_fbx_native(mesh, fbx_path, base, scale)", export_body)
        self.assertLess(
            export_body.index("_export_fbx_native(mesh, fbx_path, base, scale)"),
            export_body.index("buf = io.BytesIO()"),
        )
        self.assertIn("native_geometry = _fbx_geometry_native(mesh, scale=scale)", export_body)
        self.assertIn('_allow_python_export_fallback(mesh, "export.fbx")', export_body)
        self.assertLess(export_body.index("native_geometry = _fbx_geometry_native(mesh, scale=scale)"), export_body.index("buf = io.BytesIO()"))
        self.assertLess(export_body.index('_allow_python_export_fallback(mesh, "export.fbx")'), export_body.index("buf = io.BytesIO()"))
        self.assertLess(export_body.index("native_geometry = _fbx_geometry_native(mesh, scale=scale)"), export_body.index("verts_flat = []"))
        self.assertIn('verts_flat = native_item["vertices"]', export_body)
        self.assertIn('indices_flat = native_item["indices"]', export_body)
        self.assertIn('normals_flat = native_item["normals"]', export_body)
        self.assertIn('uvs_flat = native_item["uvs"]', export_body)
        self.assertIn("def _export_fbx_native(", exporter_source)
        self.assertIn("export_native_fbx(", exporter_source)

        skeleton_start = exporter_source.index("def export_fbx_with_skeleton(")
        skeleton_body = exporter_source[skeleton_start:]
        self.assertIn("_export_fbx_native(mesh, fbx_path, base, scale, skeleton=skeleton)", skeleton_body)
        self.assertLess(
            skeleton_body.index("_export_fbx_native(mesh, fbx_path, base, scale, skeleton=skeleton)"),
            skeleton_body.index("buf = io.BytesIO()"),
        )
        self.assertIn("native_geometry = _fbx_geometry_native(mesh, scale=scale, require_vertex_aligned_uvs=True)", skeleton_body)
        self.assertIn('_allow_python_export_fallback(mesh, "export.fbx_skeleton")', skeleton_body)
        self.assertLess(
            skeleton_body.index("native_geometry = _fbx_geometry_native(mesh, scale=scale, require_vertex_aligned_uvs=True)"),
            skeleton_body.index("buf = io.BytesIO()"),
        )
        self.assertLess(
            skeleton_body.index('_allow_python_export_fallback(mesh, "export.fbx_skeleton")'),
            skeleton_body.index("buf = io.BytesIO()"),
        )
        self.assertLess(
            skeleton_body.index("native_geometry = _fbx_geometry_native(mesh, scale=scale, require_vertex_aligned_uvs=True)"),
            skeleton_body.index("verts_flat = []"),
        )

        self.assertIn("class _FbxBinaryArray", exporter_source)
        self.assertIn("def _fbx_geometry_native(", exporter_source)
        self.assertIn("build_native_fbx_geometry_arrays(", exporter_source)

        self.assertIn("def export_native_fbx(", bridge_source)
        self.assertIn('"fbx-export-json"', bridge_source)
        self.assertIn('"bones": _native_fbx_bone_payloads(skeleton)', bridge_source)
        self.assertIn("def _native_fbx_bone_payloads(", bridge_source)
        self.assertIn("def build_native_fbx_geometry_arrays(", bridge_source)
        self.assertIn('"fbx-geometry-json"', bridge_source)
        self.assertIn('"vertices_output_path"', bridge_source)
        self.assertIn('"indices_output_path"', bridge_source)
        self.assertIn('"session_id"', bridge_source)
        self.assertIn('"export_native_fbx"', bridge_source)
        self.assertIn('"build_native_fbx_geometry_arrays"', bridge_source)

        self.assertIn("struct FbxExportResult", native_source)
        self.assertIn("FbxExportResult run_fbx_export", native_source)
        self.assertIn("struct NativeFbxBone", native_source)
        self.assertIn("std::vector<NativeFbxBone> native_fbx_bones_from_json", native_source)
        self.assertIn('fbx_node(attr_out, "TypeFlags", {fbx_string("Skeleton")});', native_source)
        self.assertIn("fbx_export_report_json", native_source)
        self.assertIn('if (command == "fbx-export-json") return fbx_export_json_command(job_path, report_path);', native_source)
        self.assertIn("struct FbxGeometrySubmeshResult", native_source)
        self.assertIn("std::vector<FbxGeometrySubmeshResult> run_fbx_geometry", native_source)
        self.assertIn("flatten_fbx_vertices", native_source)
        self.assertIn("flatten_fbx_polygon_indices", native_source)
        self.assertIn("fbx_geometry_report_json", native_source)
        self.assertIn('if (command == "fbx-geometry-json") return fbx_geometry_json_command(job_path, report_path);', native_source)

    def test_mesh_edit_control_changes_sync_state_without_preview_reload(self) -> None:
        source = _mesh_edit_source()
        ui_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py")
        mesh_edit_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py")
        builder_body = _function_source(mesh_edit_source, "_connect_callbacks")
        refresh_body = _function_source(mesh_edit_source, "_refresh_mesh_edit_controls")

        self.assertIn("_state._populate_combo_options_helper(_state.mesh_edit_selection_depth_combo, _state.MESH_EDIT_SELECTION_DEPTH_OPTIONS)", ui_source)
        self.assertIn("MESH_EDIT_SELECTION_DEPTH_OPTIONS", source)
        self.assertIn('("Visible Only", "visible")', source)
        self.assertIn('("X-Ray", "xray")', source)
        self.assertIn("_state.compact_selection_mode_combo = _state.QComboBox(_state.compact_mesh_edit_options_widget)", ui_source)
        self.assertIn("_state.compact_selection_mode_combo.setObjectName('ClassicMeshEditSelectionModeCombo')", ui_source)
        self.assertIn("_state._populate_combo_options_helper(_state.compact_selection_mode_combo, _state.MESH_EDIT_SELECTION_MODE_OPTIONS)", ui_source)
        self.assertIn("_state.compact_selection_depth_combo = _state.QComboBox(_state.compact_mesh_edit_options_widget)", ui_source)
        self.assertIn("_state.compact_selection_depth_combo.setObjectName('ClassicMeshEditSelectionDepthCombo')", ui_source)
        self.assertIn("_state._populate_combo_options_helper(_state.compact_selection_depth_combo, _state.MESH_EDIT_SELECTION_DEPTH_OPTIONS)", ui_source)
        self.assertIn("_state.mesh_edit_tool_combo.setCurrentIndex(_state.max(0, _state.mesh_edit_tool_combo.findData('vertex')))", ui_source)
        self.assertIn("button.setChecked(tool == current_tool)", refresh_body)
        self.assertIn("widget.setVisible(select_tool)", refresh_body)
        self.assertIn("widget.setEnabled(editing_requested and not topology_busy and select_tool)", refresh_body)
        self.assertIn("_mesh_edit_preview_source_indices = lambda", source)
        self.assertIn("def _mesh_edit_enabled_toggled(_state, _callbacks, _checked: bool = False) -> None:", mesh_edit_source)
        self.assertNotIn("def _start_mesh_edit_fallback", mesh_edit_source)
        self.assertIn('"mesh_edit_dotnet_failed"', mesh_edit_source)
        self.assertIn("state.mesh_edit_enabled_checkbox.toggled.connect(callbacks._mesh_edit_enabled_toggled)", builder_body)
        self.assertIn('prompt_shell_context["_sync_mesh_edit_preview_settings"] = _sync_mesh_edit_preview_settings', source)
        self.assertIn('prompt_shell_context.get(\n                "_sync_mesh_edit_preview_settings"', source)
        for signal in (
            "state.mesh_edit_scope_combo.currentIndexChanged",
            "state.mesh_edit_part_combo.currentIndexChanged",
            "state.mesh_edit_tool_combo.currentIndexChanged",
            "state.mesh_edit_falloff_combo.currentIndexChanged",
            "state.mesh_edit_selection_mode_combo.currentIndexChanged",
            "state.mesh_edit_selection_depth_combo.currentIndexChanged",
            "state.mesh_edit_radius_spin.valueChanged",
            "state.mesh_edit_strength_spin.valueChanged",
        ):
            self.assertIn(signal, builder_body)
        self.assertIn("signal.connect(lambda _value: callbacks._refresh_mesh_edit_controls())", builder_body)
        self.assertNotIn("_queue_static_preview_refresh", builder_body)

    def test_live_vertex_update_bridge_is_wired(self) -> None:
        main_source = _mesh_edit_source()
        bridge_source = _read("cdmw/ui/native_d3d11_preview_host.py")
        panel_source = _read("cdmw/ui/native_preview_panel.py")
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        native_d3d11_source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        for source in (bridge_source,):
            self.assertIn('"command": "update_mesh_edit_vertices"', source)
            self.assertIn("_MESH_EDIT_VERTEX_FILE_THRESHOLD = 512 * 1024", source)
            self.assertIn('file_command="update_mesh_edit_vertices_file"', source)
            self.assertIn('file_prefix="cdmw_mesh_edit_vertices_"', source)
            self.assertIn('"command": "replace_mesh_edit_triangles"', source)
            self.assertIn("def _send_mesh_edit_json_or_file(", source)
            self.assertIn("self._last_mesh_edit_send_metrics", source)
            self.assertIn("def last_mesh_edit_send_metrics(self) -> Dict[str, object]:", source)
            self.assertIn('"payload_bytes": len(encoded)', source)
            self.assertIn('"send_ms": max(0.0, (time.perf_counter() - send_started) * 1000.0)', source)
            self.assertIn("def _write_i32_preview_delta(", source)
            self.assertIn("def _compact_nonnegative_indices(", source)
            self.assertIn("def _compact_mesh_edit_selection_group(", source)
            self.assertIn("def _mesh_edit_json_groups(", source)
            self.assertIn("_compact_mesh_edit_selection_group(group, temp_paths=temp_paths)", source)
            self.assertIn('"groups": _mesh_edit_json_groups(groups)', source)
            self.assertIn('binary_suffix="_selection_vertices.bin"', source)
            self.assertIn('binary_suffix="_selection_faces.bin"', source)
            self.assertIn('group[binary_key] = descriptor', source)
            self.assertIn('"source_vertex_indices_binary": descriptor', source)
            self.assertIn('"source_vertex_start": index_range[0]', source)
            self.assertIn('"source_vertex_count": index_range[1]', source)
            self.assertIn('json_key="source_face_indices"', source)
            self.assertIn('start_key="source_face_start"', source)
            self.assertNotIn("for raw_vertex in tuple(raw_vertices or ())", source)
            self.assertNotIn("dict(selected_vertices_by_submesh or {}).items()", source)
            self.assertNotIn("for group in tuple(groups or ())", source)

            self.assertNotIn("tuple(source_submesh_indices or ())", source)
            self.assertNotIn("tuple(replacement_submesh_indices or ())", source)
            self.assertNotIn("tuple(original_submesh_indices or ())", source)
            self.assertNotIn('tuple(item.get("source_submesh_indices", ()) or ())', source)
            self.assertNotIn("for item in tuple(part_transforms or ())", source)
            self.assertIn("ordered = _sorted_nonnegative_indices(source_submesh_indices)", source)
            self.assertIn("replacement = _sorted_nonnegative_indices(replacement_submesh_indices)", source)
            self.assertIn("original = _sorted_nonnegative_indices(original_submesh_indices)", source)
            self.assertNotIn('"source_vertex_indices": sorted(set(vertices))', source)
            self.assertNotIn("group[json_key] = values\n    return compacted", source)
            self.assertNotIn('"groups": list(groups or ())', source)
            self.assertNotIn("groups\": [dict(group) for group in tuple(groups or ())", source)
            self.assertIn('selection_depth_mode: str = "visible"', source)
            self.assertIn('"selection_depth_mode": str(selection_depth_mode or "visible")', source)
            self.assertIn('"smooth_iterations": int(smooth_iterations or 3)', source)
        self.assertIn('"mesh_edit_live_stroke_timing"', main_source)
        self.assertIn("_record_mesh_edit_live_stroke_timing(", main_source)
        self.assertIn("d3d11_send_metrics=_callbacks._mesh_edit_last_d3d11_send_metrics()", main_source)
        self.assertIn("service_total_ms=float(metrics.get(\"service_total_ms\", 0.0) or 0.0)", main_source)
        self.assertIn("native_apply_roundtrip_ms=float(metrics.get(\"native_apply_roundtrip_ms\", 0.0) or 0.0)", main_source)
        self.assertIn("d3d11_frame_count=_callbacks._mesh_edit_payload_frame_count(payload)", main_source)
        self.assertIn('<< ",\\"frame_count\\":" << frame_count_', native_d3d11_source)
        self.assertIn("def _compact_nonnegative_indices(", panel_source)
        self.assertIn('"source_vertex_start": index_range[0]', panel_source)
        self.assertIn('"source_vertex_count": index_range[1]', panel_source)
        self.assertNotIn('"source_vertex_indices": sorted(set(vertices))', panel_source)
        self.assertNotIn("tuple(int(index) for index in tuple(indices or ()))", panel_source)
        self.assertNotIn("dict(selected_vertices_by_submesh or {}).items()", panel_source)
        self.assertNotIn('sum(len(group["source_vertex_indices"])', panel_source)
        self.assertIn("def _mesh_edit_live_vertex_update_groups(", main_source)
        self.assertIn("mesh_edit_preview_model_dirty = {\"value\": False}", main_source)
        self.assertIn("def _mesh_edit_refresh_replacement_preview_model(", main_source)
        self.assertIn("allow_defer_for_incremental_d3d11", main_source)
        refresh_body = _function_source(main_source, "_mesh_edit_refresh_replacement_preview_model")
        self.assertNotIn(
            "and original_reference_preview_model is not None\n        )",
            refresh_body,
        )
        self.assertIn("_state.mesh_edit_preview_model_dirty[\"value\"] = True", main_source)
        self.assertIn("edit_enabled = bool(_state.mesh_edit_enabled_checkbox.isChecked())", main_source)
        self.assertIn("_callbacks._mesh_editor_finalize_edit_mode_exit(\"mesh_edit_toggle\", mesh_changed=True)", main_source)
        toggle_body = _function_source(main_source, "_mesh_edit_enabled_toggled")
        self.assertNotIn("_start_mesh_edit_fallback", toggle_body)
        self.assertIn("preview cannot start", toggle_body)
        self.assertIn("preview is disabled by configuration", toggle_body)
        self.assertNotIn("_mesh_edit_apply_preview_mode_transition(\"mesh_edit_toggle\")", toggle_body)
        self.assertNotIn("_mesh_edit_refresh_replacement_preview_model()\n", toggle_body)
        finish_body = _function_source(main_source, "_mesh_edit_finish_geometry_stroke")
        self.assertIn("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)", finish_body)
        self.assertNotIn("parsed_mesh_to_preview_model(", finish_body)
        self.assertIn("Active Mesh Editor stroke finish requires native D3D11 refresh", finish_body)
        self.assertIn("_callbacks._mesh_edit_mark_native_preview_stale(", finish_body)
        self.assertNotIn("_queue_static_preview_rebuild()", finish_body)
        self.assertIn("mesh_edit_live_update_timer.setInterval(16)", main_source)
        self.assertIn("if include_normals and normal_count == vertex_count:", payload_source)
        self.assertIn("changed_vertices_by_submesh: Mapping[int, object] | None,", payload_source)
        self.assertNotIn("changed_vertices_by_submesh: Mapping[int, Iterable[int]] | None,", payload_source)
        self.assertIn("mesh_edit_native_live_vertex_update_groups", payload_source)
        self.assertIn("def _record_native_preview_fallback(", payload_source)
        self.assertIn("def _mesh_edit_generated_live_vertex_update_groups(", payload_source)
        self.assertIn("build_native_mesh_preview_vertex_update_groups(mesh, requested)", payload_source)
        self.assertIn("invalidate_native_mesh_session_submeshes(mesh, missing.keys())", payload_source)
        self.assertIn("_mesh_edit_native_live_vertex_update_groups_helper", main_source)
        live_group_body = _function_source(main_source, "_mesh_edit_live_vertex_update_groups")
        self.assertIn("if _callbacks._alignment_d3d11_mesh_edit_commands_active():\n            return []", live_group_body)
        self.assertNotIn("allow_python_fallback=True", live_group_body)
        self.assertLess(
            live_group_body.index("if _callbacks._alignment_d3d11_mesh_edit_commands_active():\n            return []"),
            live_group_body.index("_callbacks._mesh_edit_transformed_sources_for_live_preview("),
        )
        self.assertIn("source_affine_for_transformed_preview", main_source)
        self.assertIn("source_normal_transform_for_transformed_preview", main_source)
        self.assertIn("position_transform_by_source", payload_source)
        self.assertIn("normal_transform_by_source", payload_source)
        self.assertIn("allow_source_space", payload_source)
        self.assertIn('"position_space"', payload_source)
        self.assertIn('"source_affine"', payload_source)
        self.assertNotIn("dict(changed_vertices_by_submesh or {}).items()", payload_source)
        native_live_start = payload_source.index("def mesh_edit_native_live_vertex_update_groups(")
        native_live_body = payload_source[
            native_live_start: payload_source.index("def mesh_edit_triangle_replace_groups(", native_live_start)
        ]
        self.assertIn("generated_native = _mesh_edit_generated_live_vertex_update_groups", native_live_body)
        self.assertIn("def _index_upper_bound(", payload_source)
        self.assertIn("max_index = _index_upper_bound(expected_indices)", payload_source)
        self.assertNotIn("max(expected_indices", payload_source)
        generated_index = native_live_body.index("generated_native = _mesh_edit_generated_live_vertex_update_groups")
        self.assertLess(
            generated_index,
            native_live_body.index("if group is None:\n            return []", generated_index),
        )
        python_live_start = payload_source.index("def mesh_edit_live_vertex_update_groups(")
        python_live_body = payload_source[
            python_live_start: payload_source.index("def mesh_edit_native_live_vertex_update_groups(", python_live_start)
        ]
        self.assertNotIn("_PYTHON_PREVIEW_FALLBACK_VERTEX_LIMIT", payload_source)
        self.assertNotIn("_PYTHON_PREVIEW_FALLBACK_FACE_LIMIT", payload_source)
        self.assertIn("def _allow_python_preview_fallback(", payload_source)
        self.assertIn('"Python preview fallback blocked while native mesh core is available"', payload_source)
        self.assertIn("allow_python_fallback: bool = False", python_live_body)
        self.assertIn("allow_python_fallback=allow_python_fallback", python_live_body)
        self.assertIn('"static_preview_vertex_update"', python_live_body)
        self.assertIn('raw_vertex_values = getattr(submesh, "vertices", ()) or ()', python_live_body)
        self.assertIn("fallback_candidate_count =", python_live_body)
        self.assertIn("mesh_vertex_count = _nonnegative_int", python_live_body)
        self.assertIn("guard_vertex_count = max(mesh_vertex_count, vertex_count, fallback_candidate_count or 0)", python_live_body)
        self.assertIn("if not _allow_python_preview_fallback(", python_live_body)
        self.assertIn("vertices = raw_vertex_values", python_live_body)
        self.assertIn("normals = raw_normal_values", python_live_body)
        self.assertIn("normal_count = _sequence_len(normals) or 0", python_live_body)
        self.assertIn("_source_vertex_indices(raw_vertices, vertex_count)", python_live_body)
        self.assertLess(
            python_live_body.index("fallback_candidate_count ="),
            python_live_body.index("vertices = raw_vertex_values"),
        )
        self.assertLess(
            python_live_body.index("mesh_vertex_count = _nonnegative_int"),
            python_live_body.index("vertices = raw_vertex_values"),
        )
        self.assertLess(
            python_live_body.index("guard_vertex_count ="),
            python_live_body.index("vertices = raw_vertex_values"),
        )
        self.assertLess(
            python_live_body.index("fallback_candidate_count ="),
            python_live_body.index("_source_vertex_indices(raw_vertices, vertex_count)"),
        )
        self.assertNotIn("tuple(raw_vertices or ())", python_live_body)
        self.assertNotIn("vertices = tuple(raw_vertex_values)", python_live_body)
        self.assertNotIn("normals = tuple(raw_normal_values)", python_live_body)
        self.assertNotIn("_source_vertex_indices(raw_vertices, len(vertices))", python_live_body)
        self.assertIn("changed_vertex_count=len(source_vertex_indices)", python_live_body)
        self.assertIn("if source_vertex_indices and not _allow_python_preview_fallback(", python_live_body)
        triangle_start = payload_source.index("def mesh_edit_triangle_replace_groups(")
        triangle_body = payload_source[triangle_start: payload_source.index("def _triangle_group_has_geometry(", triangle_start)]
        self.assertIn('"static_preview_triangle_group"', triangle_body)
        self.assertIn("allow_python_fallback: bool = False", triangle_body)
        self.assertIn("allow_python_fallback=allow_python_fallback", triangle_body)
        self.assertIn('raw_face_values = getattr(submesh, "faces", ()) or ()', triangle_body)
        self.assertIn('not _allow_python_preview_fallback(', triangle_body)
        self.assertIn("vertices = raw_vertex_values", triangle_body)
        self.assertIn("normals = raw_normal_values", triangle_body)
        self.assertIn("faces = raw_face_values", triangle_body)
        self.assertIn("normal_count = _sequence_len(normals) or 0", triangle_body)
        self.assertNotIn("vertices = tuple(raw_vertex_values)", triangle_body)
        self.assertNotIn("normals = tuple(raw_normal_values)", triangle_body)
        self.assertNotIn("faces = tuple(raw_face_values)", triangle_body)
        self.assertLess(
            triangle_body.index('not _allow_python_preview_fallback('),
            triangle_body.index("vertices = raw_vertex_values"),
        )
        preview_native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        self.assertIn('if (command == "update_mesh_edit_vertices_file")', preview_native_source)
        self.assertIn('filename.rfind(L"cdmw_mesh_edit_vertices_", 0) != 0', preview_native_source)
        self.assertIn('const bool source_space_positions = position_space == "source";', preview_native_source)
        self.assertIn('const bool source_affine_positions = position_space == "source_affine";', preview_native_source)
        self.assertIn('json_float_array_field(group, "position_transform")', preview_native_source)
        self.assertIn('json_float_array_field(group, "normal_transform")', preview_native_source)
        self.assertIn("x = position_transform[0] * sx + position_transform[1] * sy + position_transform[2] * sz + position_transform[3];", preview_native_source)
        self.assertIn("nx = normal_transform[0] * sx + normal_transform[1] * sy + normal_transform[2] * sz;", preview_native_source)
        self.assertIn("nx /= length;", preview_native_source)
        self.assertIn('x = (x - cx) * normalization_scale;', preview_native_source)
        self.assertIn('lower_copy(json_string_field(group, "preview_backend")) == "cdmw_mesh_core"', preview_native_source)
        self.assertIn("source_to_preview_position_for_batch(batch, position)", preview_native_source)
        self.assertIn("mesh_edit_source_world_transform_for_batch(batch)", preview_native_source)
        self.assertIn("if _state.alignment_d3d11_preview_host.update_mesh_edit_vertices(groups):", main_source)
        self.assertIn("def _mesh_edit_source_indices_from_groups(_state, _callbacks, groups: _state.Iterable[_state.Mapping[str, object]]) -> tuple[int, ...]:", main_source)
        self.assertIn('"mesh_edit_live_vertex_update_failed"', main_source)
        self.assertIn("if source_indices and _callbacks._mesh_edit_replace_live_triangles(source_indices):", main_source)
        self.assertIn("Native D3D11 mesh edit preview update failed; preview is stale.", main_source)
        triangle_replace_body = _function_source(main_source, "_mesh_edit_triangle_replace_groups")
        self.assertIn("if _callbacks._alignment_d3d11_mesh_edit_commands_active():\n        return []", triangle_replace_body)
        self.assertNotIn("allow_python_fallback=True", triangle_replace_body)
        self.assertLess(
            triangle_replace_body.index("if _callbacks._alignment_d3d11_mesh_edit_commands_active():\n        return []"),
            triangle_replace_body.index("_callbacks._mesh_edit_transformed_sources_for_live_preview("),
        )
        self.assertIn('"mesh_edit_native_preview_stale"', main_source)
        self.assertIn("source_submesh_indices=requested_source_indices", main_source)
        self.assertIn('"source_submesh_indices": sources', bridge_source)
        self.assertIn("_callbacks._mesh_edit_update_live_preview(pending_live_vertices_by_submesh)", main_source)
        self.assertIn("def _mesh_editor_apply_result_native_update(_state, _callbacks, result: object) -> bool:", main_source)
        apply_result_body = _function_source(main_source, "_mesh_editor_apply_result_native_update")
        self.assertIn("_callbacks._mesh_editor_result_has_deferred_native_python_apply(result)", apply_result_body)
        self.assertIn("active_commands = _callbacks._alignment_d3d11_mesh_edit_commands_active()", apply_result_body)
        self.assertIn("_callbacks._mesh_editor_result_changes_mesh(result)", apply_result_body)
        self.assertIn("_callbacks._mesh_editor_queue_native_preview_rebuild_from_working_mesh", apply_result_body)
        self.assertIn("Active native mesh edit result had no preview payload", apply_result_body)
        self.assertIn("Active native mesh edit preview payload was rejected", apply_result_body)
        self.assertIn("rebuilding native preview from the working mesh", apply_result_body)
        self.assertLess(
            apply_result_body.index("_mesh_editor_result_has_deferred_native_python_apply(result)"),
            apply_result_body.index("return False"),
        )
        self.assertLess(
            apply_result_body.index("Active native mesh edit result had no preview payload"),
            apply_result_body.index("return False", apply_result_body.index("Active native mesh edit result had no preview payload")),
        )
        self.assertIn("live_native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)", main_source)
        self.assertNotIn("pending_live_vertices_by_submesh.setdefault(source_submesh_index, set()).update(changed)", main_source)
        self.assertLess(
            main_source.index("live_native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)"),
            main_source.index(
                "_state._mesh_edit_queue_live_vertex_updates_helper(pending_live_vertices_by_submesh, changed_by_submesh)",
                main_source.index("live_native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)"),
            ),
        )
        preview_groups_start = mesh_native_source.index("def build_native_mesh_preview_vertex_update_groups(")
        preview_groups_body = mesh_native_source[
            preview_groups_start: mesh_native_source.index("def _native_selection_preview_group(", preview_groups_start)
        ]
        self.assertIn("changed_all_vertices = (", preview_groups_body)
        self.assertIn("changed_descriptor = _changed_vertices_binary_descriptor(raw_indices, vertex_count)", preview_groups_body)
        self.assertIn("changed_range = _changed_vertex_range(raw_indices, vertex_count)", preview_groups_body)
        self.assertIn("def _iter_valid_changed_vertex_indices(", mesh_native_source)
        self.assertIn('item["changed_all_vertices"] = True', preview_groups_body)
        self.assertIn('item["changed_vertex_start"] = int(changed_range[0])', preview_groups_body)
        self.assertIn('item["changed_vertex_count"] = int(changed_range[1])', preview_groups_body)
        self.assertIn('item["changed_vertices_binary"] = changed_descriptor', preview_groups_body)
        self.assertIn("_iter_valid_changed_vertex_indices(raw_indices, vertex_count)", preview_groups_body)
        self.assertNotIn("tuple(raw_indices or ())", preview_groups_body)
        self.assertIn("_MESH_EDIT_TRIANGLE_FILE_THRESHOLD = 512 * 1024", bridge_source)
        self.assertIn('file_command="replace_mesh_edit_triangles_file"', bridge_source)
        self.assertIn('file_prefix="cdmw_mesh_edit_triangles_"', bridge_source)
        self.assertIn('"payload_file": str(temp_path)', bridge_source)

    def test_standalone_topology_preview_update_uses_affected_sources(self) -> None:
        controller_source = _read("cdmw/ui/mesh_editor/controller.py")
        preview_native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        mesh_core_source = _read("native/cdmw_mesh_core/src/main.cpp")
        static_payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        mesh_deformer_source = _read("cdmw/modding/mesh_deformer.py")

        topology_start = controller_source.index("if result.topology_changed:")
        topology_body = controller_source[topology_start: controller_source.index('if result.action in {"material_assign", "material_copy"}', topology_start)]
        self.assertIn("_topology_refresh_source_indices(mesh, result)", topology_body)
        self.assertIn("mesh_edit_triangle_groups(", topology_body)
        self.assertIn("refresh_sources", topology_body)
        self.assertIn("replace_all_triangles=replace_all", topology_body)
        self.assertIn("result.submesh_count_delta < 0", topology_body)
        self.assertNotIn("mesh_edit_triangle_groups(mesh))", topology_body)
        self.assertIn('\\"preview_triangle_group\\"', mesh_core_source)
        self.assertIn('\\"preview_vertex_update_group\\"', mesh_core_source)
        self.assertIn("preview_uvs_for_result", mesh_core_source)
        self.assertIn("write_preview_vertex_update_group", mesh_core_source)
        self.assertIn("write_preview_triangle_group", mesh_core_source)
        self.assertIn("preview_triangle_groups_report_json", mesh_core_source)
        self.assertIn('"preview-triangle-groups-json"', mesh_core_source)
        self.assertIn("preview_vertex_update_groups_report_json", mesh_core_source)
        self.assertIn('"preview-vertex-update-groups-json"', mesh_core_source)
        self.assertIn("write_full_preview_vertex_update_group", mesh_core_source)
        self.assertIn("std::vector<int> source_vertex_ids_for_indices(", mesh_core_source)
        self.assertIn("void write_preview_source_vertex_ids(", mesh_core_source)
        preview_update_start = mesh_core_source.index("void write_preview_vertex_update_group")
        preview_update_body = mesh_core_source[
            preview_update_start: mesh_core_source.index("void write_sparse_preview_vertex_update_group", preview_update_start)
        ]
        self.assertIn("const std::string& source_indices_path", preview_update_body)
        self.assertIn("const std::vector<int>& source_vertex_map", preview_update_body)
        self.assertIn(
            "write_preview_source_vertex_ids(out, source_vertex_ids_for_indices(indices, source_vertex_map, indices.size()), source_indices_path)",
            preview_update_body,
        )
        self.assertNotIn('out << ",\\"source_vertex_indices\\":["', preview_update_body)
        vertex_update_start = mesh_core_source.index("std::string preview_vertex_update_groups_report_json")
        vertex_update_body = mesh_core_source[vertex_update_start: mesh_core_source.index("std::string string_from_ufbx", vertex_update_start)]
        self.assertIn("const std::vector<int> source_vertex_map = mesh_source_vertex_map_from_item(item, vertices.size());", vertex_update_body)
        self.assertIn('const bool changed_all_vertices = bool_or(item.get("changed_all_vertices"), false);', vertex_update_body)
        self.assertIn('const int changed_vertex_start = int_or(item.get("changed_vertex_start"), -1);', vertex_update_body)
        self.assertIn('const int changed_vertex_count = int_or(item.get("changed_vertex_count"), 0);', vertex_update_body)
        self.assertIn("const bool changed_vertex_range = changed_vertex_start >= 0", vertex_update_body)
        self.assertIn("if (changed_all_vertices && !preview_vertex_path.empty())", vertex_update_body)
        self.assertIn("write_full_preview_vertex_update_group(", vertex_update_body)
        self.assertIn("source_vertex_map", vertex_update_body)
        self.assertIn("} else if (changed_vertex_range) {", vertex_update_body)
        self.assertIn("changed_vertices.push_back(changed_vertex_start + offset);", vertex_update_body)
        self.assertIn("changed_all_vertices ? 0 : (changed_vertex_range ? changed_vertex_start : -1)", vertex_update_body)
        self.assertIn("changed_vertex_range ? changed_vertex_start : -1", vertex_update_body)
        self.assertLess(
            vertex_update_body.index("if (changed_all_vertices && !preview_vertex_path.empty())"),
            vertex_update_body.index('int_vector_from_binary_or_json(item, "changed_vertices_binary", "changed_vertices")'),
        )
        full_update_start = mesh_core_source.index("void write_full_preview_vertex_update_group")
        full_update_body = mesh_core_source[full_update_start: mesh_core_source.index("void write_preview_triangle_group", full_update_start)]
        self.assertIn("const std::vector<int>& source_vertex_map", full_update_body)
        self.assertIn("write_preview_source_vertex_ids(", full_update_body)
        self.assertIn("source_vertex_map.size() == count ? source_vertex_map : identity", full_update_body)
        self.assertIn('sibling_binary_path(positions_path, ".source_indices.bin")', full_update_body)
        self.assertIn("write_vec3_binary_file(positions_path, vertices)", full_update_body)
        self.assertNotIn('out << ",\\"source_vertex_indices\\":["', full_update_body)
        sparse_update_start = mesh_core_source.index("void write_sparse_preview_vertex_update_group")
        sparse_update_body = mesh_core_source[
            sparse_update_start: mesh_core_source.index("void write_preview_triangle_group", sparse_update_start)
        ]
        self.assertIn("const std::vector<int>& source_vertex_map", sparse_update_body)
        self.assertIn(
            "source_indices = source_vertex_ids_for_indices(changed_vertices, source_vertex_map, count);",
            sparse_update_body,
        )
        self.assertIn("bool preview_source_vertex_range_for_indices", mesh_core_source)
        self.assertIn("void write_preview_source_vertex_range", mesh_core_source)
        self.assertIn("const bool direct_source_range = has_changed_source_ids", sparse_update_body)
        self.assertIn("? contiguous_int_range(source_indices, direct_source_start)", sparse_update_body)
        self.assertIn(": preview_source_vertex_range_for_indices(", sparse_update_body)
        self.assertIn("write_preview_source_vertex_range(out, direct_source_start, count);", sparse_update_body)
        self.assertIn('sibling_binary_path(changed_positions_path, ".source_indices.bin")', sparse_update_body)
        self.assertIn("write_preview_source_vertex_ids(out, source_indices)", sparse_update_body)
        self.assertNotIn("source_indices.push_back(source_vertex_start + static_cast<int>(index));", sparse_update_body)
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        self.assertIn("build_native_mesh_preview_triangle_groups", mesh_native_source)
        self.assertIn("build_native_mesh_preview_vertex_update_groups", mesh_native_source)
        native_triangle_groups_start = mesh_native_source.index("def build_native_mesh_preview_triangle_groups(")
        native_triangle_groups_body = mesh_native_source[
            native_triangle_groups_start: mesh_native_source.index("def build_native_mesh_preview_vertex_update_groups(", native_triangle_groups_start)
        ]
        self.assertIn("requested = range(len(mesh.submeshes))", native_triangle_groups_body)
        self.assertIn("for raw_index in source_indices or ()", native_triangle_groups_body)
        self.assertNotIn("tuple(range(len(mesh.submeshes)))", native_triangle_groups_body)
        self.assertNotIn("tuple(source_indices or ())", native_triangle_groups_body)
        mesh_editor_payload_source = _read("cdmw/ui/mesh_editor/native_preview_payloads.py")
        self.assertIn("invalidate_native_mesh_session_submeshes", mesh_editor_payload_source)
        self.assertNotIn("_PYTHON_PREVIEW_FALLBACK_VERTEX_LIMIT", mesh_editor_payload_source)
        self.assertNotIn("_PYTHON_PREVIEW_FALLBACK_FACE_LIMIT", mesh_editor_payload_source)
        self.assertIn("def _allow_python_preview_fallback(", mesh_editor_payload_source)
        self.assertIn('"Python preview fallback blocked while native mesh core is available"', mesh_editor_payload_source)
        self.assertIn("_mesh_edit_triangle_groups_native(mesh, missing_native)", mesh_editor_payload_source)
        self.assertIn("_mesh_edit_vertex_update_groups_native(mesh, missing_native)", mesh_editor_payload_source)
        native_vertex_groups_start = mesh_editor_payload_source.index("def _mesh_edit_vertex_update_groups_native(")
        native_vertex_groups_body = mesh_editor_payload_source[
            native_vertex_groups_start: mesh_editor_payload_source.index("def _native_binary_descriptor(", native_vertex_groups_start)
        ]
        self.assertIn("native_groups = build_native_mesh_preview_vertex_update_groups(mesh, requested)", native_vertex_groups_body)
        self.assertNotIn(
            "build_native_mesh_preview_vertex_update_groups(mesh, changed_vertices_by_submesh)",
            native_vertex_groups_body,
        )
        self.assertIn("invalidate_native_mesh_session_submeshes(mesh, missing.keys())", native_vertex_groups_body)
        self.assertIn("consume(build_native_mesh_preview_vertex_update_groups(mesh, missing))", native_vertex_groups_body)
        triangle_groups_start = mesh_editor_payload_source.index("def mesh_edit_triangle_groups(")
        triangle_groups_body = mesh_editor_payload_source[
            triangle_groups_start: mesh_editor_payload_source.index("def _mesh_edit_triangle_groups_native(", triangle_groups_start)
        ]
        self.assertIn("allow_python_fallback: bool = False", triangle_groups_body)
        self.assertIn("if not allow_python_fallback:", triangle_groups_body)
        self.assertIn("native triangle update group unavailable; Python fallback is disabled", triangle_groups_body)
        self.assertIn('not _allow_python_preview_fallback(', triangle_groups_body)
        self.assertIn('group["source_vertex_start"] = 0', triangle_groups_body)
        self.assertIn('group["source_vertex_count"] = len(submesh.vertices)', triangle_groups_body)
        self.assertIn("_contiguous_index_range(source_face_indices)", triangle_groups_body)
        self.assertNotIn('"source_vertex_indices": list(range(len(submesh.vertices)))', triangle_groups_body)
        vertex_groups_start = _read("cdmw/ui/mesh_editor/native_preview_payloads.py").index("def mesh_edit_vertex_update_groups(")
        vertex_groups_body = _read("cdmw/ui/mesh_editor/native_preview_payloads.py")[
            vertex_groups_start: _read("cdmw/ui/mesh_editor/native_preview_payloads.py").index("def _mesh_edit_vertex_update_groups_native(", vertex_groups_start)
        ]
        self.assertIn("allow_python_fallback: bool = False", vertex_groups_body)
        self.assertIn("if not allow_python_fallback:", vertex_groups_body)
        self.assertIn("native vertex update group unavailable; Python fallback is disabled", vertex_groups_body)
        self.assertIn("changed_all_vertices = _is_full_vertex_range(raw_indices, vertex_count)", vertex_groups_body)
        self.assertIn("native_count = _changed_vertex_input_count(raw_indices, vertex_count)", vertex_groups_body)
        self.assertIn("expected_count=native_count", vertex_groups_body)
        self.assertIn("if isinstance(raw_indices, Mapping):", vertex_groups_body)
        self.assertIn("missing_native[submesh_index] = raw_indices", vertex_groups_body)
        mesh_editor_consume_triangle_start = mesh_editor_payload_source.index("def _consume_native_triangle_group(")
        mesh_editor_consume_triangle_body = mesh_editor_payload_source[
            mesh_editor_consume_triangle_start: mesh_editor_payload_source.index("def mesh_edit_material_override_groups(", mesh_editor_consume_triangle_start)
        ]
        self.assertLess(
            mesh_editor_consume_triangle_body.index('raw_source_vertices_binary = group.get("source_vertex_indices_binary")'),
            mesh_editor_consume_triangle_body.index('source_vertices = _source_vertex_indices(group.get("source_vertex_indices"), 1 << 30)'),
        )
        self.assertLess(
            mesh_editor_consume_triangle_body.index('raw_source_faces_binary = group.get("source_face_indices_binary")'),
            mesh_editor_consume_triangle_body.index('source_faces = _source_vertex_indices(group.get("source_face_indices"), 1 << 30)'),
        )
        self.assertLess(
            mesh_editor_consume_triangle_body.index('raw_indices_binary = group.get("indices_binary")'),
            mesh_editor_consume_triangle_body.index('raw_indices = iter(group.get("indices") or ())'),
        )
        self.assertNotIn('indices = [int(index) for index in tuple(group.get("indices") or ())', mesh_editor_consume_triangle_body)
        self.assertIn('group.pop("source_vertex_indices", None)', mesh_editor_consume_triangle_body)
        self.assertIn('group.pop("source_face_indices", None)', mesh_editor_consume_triangle_body)
        self.assertIn('group.pop("indices", None)', mesh_editor_consume_triangle_body)
        mesh_editor_consume_vertex_start = mesh_editor_payload_source.index("def _consume_native_vertex_update_group(")
        mesh_editor_consume_vertex_body = mesh_editor_payload_source[
            mesh_editor_consume_vertex_start: mesh_editor_payload_source.index("def _record_native_preview_fallback(", mesh_editor_consume_vertex_start)
        ]
        self.assertLess(
            mesh_editor_consume_vertex_body.index("source_indices_binary = _native_binary_descriptor("),
            mesh_editor_consume_vertex_body.index('source_indices = _source_vertex_indices(group.get("source_vertex_indices"),'),
        )
        self.assertIn(
            '_put_index_range_or_values(group, indices, "source_vertex_indices", "source_vertex_start", "source_vertex_count")',
            vertex_groups_body,
        )
        self.assertIn('not _allow_python_preview_fallback(', vertex_groups_body)
        self.assertNotIn('"source_vertex_indices": indices', vertex_groups_body)
        self.assertLess(
            vertex_groups_body.index("changed_all_vertices = _is_full_vertex_range(raw_indices, vertex_count)"),
            vertex_groups_body.index("_source_vertex_indices(raw_indices, vertex_count)"),
        )
        self.assertLess(
            vertex_groups_body.index("expected_count=native_count"),
            vertex_groups_body.index("_source_vertex_indices(raw_indices, vertex_count)"),
        )
        self.assertLess(
            vertex_groups_body.index("if isinstance(raw_indices, Mapping):"),
            vertex_groups_body.index("_source_vertex_indices(raw_indices, vertex_count)"),
        )
        source_indices_start = mesh_editor_payload_source.index("def _source_vertex_indices(")
        source_indices_body = mesh_editor_payload_source[
            source_indices_start: mesh_editor_payload_source.index("def _is_full_vertex_range", source_indices_start)
        ]
        self.assertIn("if isinstance(indices, range):", source_indices_body)
        self.assertIn("compact_range = _contiguous_valid_index_range(indices, vertex_count)", source_indices_body)
        self.assertIn("return compact_range", source_indices_body)
        self.assertLess(
            source_indices_body.index("if isinstance(indices, range):"),
            source_indices_body.index("iterator = iter(raw_indices)"),
        )
        self.assertLess(
            source_indices_body.index("compact_range = _contiguous_valid_index_range(indices, vertex_count)"),
            source_indices_body.index("iterator = iter(raw_indices)"),
        )
        selection_groups_start = mesh_editor_payload_source.index("def mesh_edit_selection_groups(")
        selection_groups_body = mesh_editor_payload_source[
            selection_groups_start: mesh_editor_payload_source.index("def _mesh_edit_selection_groups_native(", selection_groups_start)
        ]
        self.assertIn("stop_event: threading.Event | None = None", selection_groups_body)
        self.assertIn("allow_python_fallback: bool = False", selection_groups_body)
        self.assertIn("_mesh_edit_selection_groups_native(mesh, selection, stop_event=stop_event)", selection_groups_body)
        self.assertIn("if not allow_python_fallback:", selection_groups_body)
        self.assertIn("native selection overlay groups unavailable; Python fallback is disabled", selection_groups_body)
        self.assertIn("vertex_work, face_work = _selection_preview_fallback_work(mesh, selection)", selection_groups_body)
        self.assertIn('not _allow_python_preview_fallback(', selection_groups_body)
        self.assertGreaterEqual(selection_groups_body.count('not _allow_python_preview_fallback('), 2)
        self.assertLess(
            selection_groups_body.index("if not allow_python_fallback:"),
            selection_groups_body.index("vertex_work, face_work = _selection_preview_fallback_work(mesh, selection)"),
        )
        selection_work_start = mesh_editor_payload_source.index("def _selection_preview_fallback_work(")
        selection_work_body = mesh_editor_payload_source[
            selection_work_start: mesh_editor_payload_source.index("def _finite_float", selection_work_start)
        ]
        self.assertIn('submeshes = getattr(mesh, "submeshes", ()) or ()', selection_work_body)
        self.assertNotIn('submeshes = tuple(getattr(mesh, "submeshes", ()) or ())', selection_work_body)
        contiguous_start = mesh_editor_payload_source.index("def _contiguous_index_range(")
        contiguous_body = mesh_editor_payload_source[
            contiguous_start: mesh_editor_payload_source.index("def _put_index_range_or_values", contiguous_start)
        ]
        self.assertIn("if isinstance(indices, range):", contiguous_body)
        self.assertIn("iterator = iter(indices)", contiguous_body)
        self.assertIn("start = int(next(iterator))", contiguous_body)
        self.assertNotIn("values = tuple(", contiguous_body)
        self.assertNotIn("tuple(indices or ())", contiguous_body)
        valid_faces_start = mesh_editor_payload_source.index("def _valid_face_items(")
        valid_faces_body = mesh_editor_payload_source[
            valid_faces_start: mesh_editor_payload_source.index("def _valid_face_vertices", valid_faces_start)
        ]
        self.assertIn('vertex_count = _sequence_len(getattr(submesh, "vertices", ())) or 0', valid_faces_body)
        self.assertNotIn('vertices = tuple(getattr(submesh, "vertices", ()) or ())', valid_faces_body)
        self.assertNotIn('tuple(getattr(submesh, "faces", ()) or ())', valid_faces_body)
        edge_filter_start = mesh_editor_payload_source.index("def _valid_selected_edges_for_submesh(")
        edge_filter_body = mesh_editor_payload_source[
            edge_filter_start: mesh_editor_payload_source.index("def _existing_face_edges", edge_filter_start)
        ]
        self.assertIn('vertex_count = _sequence_len(getattr(submesh, "vertices", ())) or 0', edge_filter_body)
        self.assertNotIn('len(tuple(getattr(submesh, "vertices", ()) or ()))', edge_filter_body)
        self.assertNotIn('if not tuple(getattr(submesh, "faces", ()) or ()):', edge_filter_body)
        all_vertices_start = controller_source.index("def _all_vertices_by_submesh(")
        all_vertices_body = controller_source[all_vertices_start: controller_source.index("def _topology_refresh_source_indices(", all_vertices_start)]
        self.assertIn("index: range(len(mesh.submeshes[index].vertices))", all_vertices_body)
        self.assertNotIn("tuple(range(len(mesh.submeshes[index].vertices)))", all_vertices_body)
        self.assertLess(
            vertex_groups_body.index("generated_native = _mesh_edit_vertex_update_groups_native(mesh, missing_native)"),
            vertex_groups_body.index("_record_native_preview_fallback("),
        )
        self.assertIn("preview_triangle_output_path", _read("cdmw/modding/mesh_native_core.py"))
        self.assertIn("preview_vertex_output_path", _read("cdmw/modding/mesh_native_core.py"))
        self.assertIn("result.preview_triangle_path = string_or(item.get(\"preview_triangle_output_path\"), \"\")", mesh_core_source)
        self.assertIn("\"indices_binary\"", mesh_core_source)
        self.assertIn("\"source_face_indices_binary\"", mesh_core_source)
        self.assertIn("contiguous_int_range(preview_source_vertex_indices, source_vertex_start)", mesh_core_source)
        self.assertIn("contiguous_int_range(preview_source_face_indices, source_face_start)", mesh_core_source)
        self.assertIn("write_int_binary_file(indices_path, indices)", mesh_core_source)
        self.assertIn("std::vector<int> source_face_indices;", mesh_core_source)
        self.assertIn("mesh_source_face_indices_from_item(item, original_faces.size())", mesh_core_source)
        self.assertIn("result.source_face_indices.push_back(source_face_index)", mesh_core_source)
        self.assertIn("result.source_face_indices = identity_indices(result.faces.size())", mesh_core_source)
        self.assertIn("session->source_face_indices = result.source_face_indices.size() == result.faces.size()", mesh_core_source)
        self.assertIn("const std::vector<int> preview_source_face_indices = source_face_indices.size() == faces.size()", mesh_core_source)
        self.assertIn("result.source_vertex_map,\n        result.source_face_indices", mesh_core_source)
        self.assertNotIn("const std::vector<int> source_face_indices = identity_indices(faces.size());", mesh_core_source)
        self.assertNotIn("const std::vector<int> source_vertex_indices = identity_indices(vertices.size());", mesh_core_source)
        self.assertIn("cdmw_native_preview_triangle_group", _read("cdmw/modding/mesh_native_core.py"))
        self.assertIn("cdmw_native_preview_vertex_update_group", _read("cdmw/modding/mesh_native_core.py"))
        self.assertIn('source_vertex_start = _index(value.get("source_vertex_start"))', _read("cdmw/modding/mesh_native_core.py"))
        self.assertIn('source_face_start = _index(value.get("source_face_start"))', _read("cdmw/modding/mesh_native_core.py"))
        self.assertIn("cdmw_native_preview_triangle_group", mesh_deformer_source)
        self.assertIn("def _consume_native_triangle_group(", static_payload_source)
        self.assertIn("def _mesh_edit_triangle_replace_groups_native(", static_payload_source)
        self.assertIn("build_native_mesh_preview_triangle_groups(mesh, source_indices=source_indices)", static_payload_source)
        self.assertIn('source_vertex_start = _coerce_index(group.get("source_vertex_start"))', _read("cdmw/ui/mesh_editor/native_preview_payloads.py"))
        self.assertIn('source_face_start = int(raw_group.get("source_face_start", -1))', static_payload_source)
        replace_groups_start = static_payload_source.index("def mesh_edit_triangle_replace_groups(")
        replace_groups_body = static_payload_source[
            replace_groups_start: static_payload_source.index("def _mesh_edit_triangle_replace_groups_native(", replace_groups_start)
        ]
        self.assertLess(
            replace_groups_body.index("generated_native = _mesh_edit_triangle_replace_groups_native(mesh, requested_source_indices)"),
            replace_groups_body.index("submesh = transformed_sources_by_index.get(source_index)"),
        )
        self.assertIn('"static_preview_triangle_group"', replace_groups_body)
        self.assertIn("source_face_count=len(source_face_indices)", replace_groups_body)
        self.assertIn('native_group["position_space"] = "source_affine"', static_payload_source)
        self.assertIn('native_group["position_space"] = "source"', static_payload_source)
        self.assertIn("normal_transform_by_source", static_payload_source)
        self.assertIn("_consume_native_triangle_group(mesh.submeshes[submesh_index], submesh_index)", _read("cdmw/ui/mesh_editor/native_preview_payloads.py"))
        self.assertIn("_consume_native_vertex_update_group(submesh, submesh_index, indices)", _read("cdmw/ui/mesh_editor/native_preview_payloads.py"))
        static_consume_triangle_start = static_payload_source.index("def _consume_native_triangle_group(")
        static_consume_triangle_body = static_payload_source[
            static_consume_triangle_start: static_payload_source.index("def _triangle_group_with_material_fields(", static_consume_triangle_start)
        ]
        self.assertLess(
            static_consume_triangle_body.index('raw_source_vertices_binary = raw_group.get("source_vertex_indices_binary")'),
            static_consume_triangle_body.index('source_vertices = _source_vertex_indices(raw_group.get("source_vertex_indices", ()), 1 << 30)'),
        )
        self.assertLess(
            static_consume_triangle_body.index('raw_source_faces_binary = raw_group.get("source_face_indices_binary")'),
            static_consume_triangle_body.index('source_faces = _source_vertex_indices(raw_group.get("source_face_indices", ()), 1 << 30)'),
        )
        self.assertLess(
            static_consume_triangle_body.index('raw_indices_binary = raw_group.get("indices_binary")'),
            static_consume_triangle_body.index('raw_indices = iter(raw_group.get("indices", ()) or ())'),
        )
        self.assertNotIn(
            'indices = [int(index) for index in tuple(raw_group.get("indices", ()) or ())',
            static_consume_triangle_body,
        )
        static_source_group_start = static_payload_source.index("def _native_source_vertex_group(")
        static_source_group_body = static_payload_source[
            static_source_group_start: static_payload_source.index("def _affine_transform_for_source(", static_source_group_start)
        ]
        self.assertLess(
            static_source_group_body.index("source_indices_binary = _native_binary_descriptor("),
            static_source_group_body.index('source_indices = _source_vertex_indices(value.get("source_vertex_indices", ()), max_index)'),
        )
        self.assertIn('json_int_array_field(payload, "source_submesh_indices")', preview_native_source)
        self.assertIn('const std::string position_space = lower_copy(json_string_field(group, "position_space"));', preview_native_source)
        self.assertIn("transform_replacement_position", preview_native_source)
        self.assertIn("transform_replacement_normal", preview_native_source)
        self.assertIn("group_source_submeshes.find(batch.source_submesh_index) == group_source_submeshes.end()", preview_native_source)

    def test_native_visible_selection_depth_and_double_click_guards_exist(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertIn('std::string selection_depth_mode = "visible";', source)
        self.assertIn('std::string selection_operation = "replace";', source)
        self.assertIn("struct MeshEditDepthMaskCache", source)
        self.assertIn("mesh_edit_depth_mask_for_view", source)
        self.assertIn("mesh_edit_screen_vertex_visible_in_depth_mask", source)
        self.assertIn('command == "update_mesh_edit_vertices"', source)
        self.assertIn('command == "replace_mesh_edit_triangles"', source)
        self.assertIn("update_mesh_edit_vertices_from_payload", source)
        self.assertIn("process_pending_mesh_edit_vertex_update()", source)
        self.assertIn("pending_mesh_edit_vertices_payload_", source)
        self.assertIn("queue_mesh_edit_vertices_payload(payload, mesh_edit_revision_field(payload));", source)
        self.assertIn("queue_mesh_edit_vertices_file(payload_file, delete_after, mesh_edit_revision_field(payload));", source)
        self.assertNotIn("mesh_edit_vertices_queued", source)
        command_start = source.index('if (command == "update_mesh_edit_vertices")')
        command_body = source[command_start: source.index('if (command == "replace_mesh_edit_triangles")', command_start)]
        self.assertIn("queue_mesh_edit_vertices_payload(payload, mesh_edit_revision_field(payload));", command_body)
        self.assertIn("queue_mesh_edit_vertices_file(payload_file, delete_after, mesh_edit_revision_field(payload));", command_body)
        self.assertNotIn("update_mesh_edit_vertices_from_payload(payload)", command_body)
        self.assertNotIn("read_text(payload_file)", command_body)
        update_start = source.index("struct ParsedUpdateGroup")
        update_body = source[update_start: source.index("void flush_pending_mesh_edit_vertex_uploads()", update_start)]
        self.assertIn('json_int_field(group, "source_vertex_start", 0)', update_body)
        self.assertIn('json_int_field(group, "source_vertex_count", 0)', update_body)
        self.assertIn("const bool has_source_vertex_values =", update_body)
        self.assertIn("!has_source_vertex_values && source_vertex_start >= 0 && source_vertex_count > 0", update_body)
        self.assertIn("if (!source_vertex_range) {", update_body)
        self.assertIn('source_vertices = json_i32_array_or_json_field(group, "source_vertex_indices_binary", "source_vertex_indices");', update_body)
        self.assertLess(
            update_body.index("const bool source_vertex_range ="),
            update_body.index('source_vertices = json_i32_array_or_json_field(group, "source_vertex_indices_binary", "source_vertex_indices");'),
        )
        self.assertIn("source_vertex_start + static_cast<int>(index)", update_body)
        self.assertIn("struct ParsedUpdateGroup", update_body)
        self.assertIn("std::vector<ParsedUpdateGroup> groups;", update_body)
        self.assertIn("std::set<int> group_source_submeshes;", update_body)
        self.assertIn("group_source_submeshes.insert(source_submesh);", update_body)
        self.assertIn("group_source_submeshes.find(batch.source_submesh_index) == group_source_submeshes.end()", update_body)
        self.assertIn("supports_direct_source_range", update_body)
        self.assertIn("batch.cpu_source_vertices[vertex_index] != static_cast<int>(vertex_index)", update_body)
        self.assertIn("rebuild_batch_source_vertex_lookup(batch)", update_body)
        self.assertIn("batch.pending_vertex_upload = true;", update_body)
        self.assertIn("batch.pending_vertex_upload_min = std::min(batch.pending_vertex_upload_min, min_changed_vertex);", update_body)
        self.assertNotIn("context_->UpdateSubresource", update_body)
        self.assertNotIn("std::map<std::pair<int, int>, DirectX::XMFLOAT3> updates", update_body)
        self.assertIn("void flush_pending_mesh_edit_vertex_uploads()", source)
        self.assertIn("flush_pending_mesh_edit_vertex_uploads();", source)
        flush_body = source[source.index("void flush_pending_mesh_edit_vertex_uploads()"):]
        self.assertIn("context_->UpdateSubresource", flush_body)
        self.assertNotIn("updates[key] =", update_body)
        self.assertIn("const bool full_buffer_update = min_changed_vertex == 0u && max_changed_vertex + 1u >= vertex_limit;", flush_body)
        self.assertNotIn("|| max_changed_vertex + 1u >= vertex_limit", update_body)
        self.assertIn("&box", flush_body)
        self.assertIn("replace_mesh_edit_triangles_from_payload", source)
        self.assertIn("if (!delivered) {", source)
        self.assertIn("write_status(args_.status_file, payload);", source)
        self.assertIn("const bool xray_mode = !mesh_edit_depth_filter_enabled();", source)
        self.assertIn("draw_colored_triangles(vertices, identity, xray_mode);", source)
        self.assertIn("draw_colored_triangles(screen_overlay_vertices, identity, true);", source)
        self.assertIn("draw_mesh_edit_vertex_dots_instanced(view, *dot_vertices, xray_mode);", source)
        self.assertNotIn("brush_vertices", source)
        self.assertIn("mesh_edit_source_face_selected(batch, triangle_index, base)", source)
        self.assertIn("mesh_edit_source_edge_selected(key0, key1)", source)
        self.assertIn("const bool exact_selection = !mesh_edit_.selected_edges.empty() || !mesh_edit_.selected_faces.empty();", source)
        self.assertIn("if (selected_face) {", source)
        self.assertIn("} else if (selected_edge) {", source)
        self.assertIn("context_->OMSetDepthStencilState(no_depth && overlay_depth_state_", source)
        self.assertIn("cpu_source_vertex_lookup", source)
        self.assertIn("rebuild_batch_source_vertex_lookup", source)
        self.assertIn("cpu_source_face_vertex_lookup", source)
        self.assertIn("rebuild_batch_source_face_vertex_lookup", source)
        face_cache_start = source.index("void rebuild_batch_source_face_vertex_lookup")
        face_cache_body = source[face_cache_start: source.index("bool mesh_edit_source_vertex_selected", face_cache_start)]
        self.assertIn(
            "batch.cpu_source_face_vertex_lookup[std::pair<int, int>(source_submesh, source_face)].insert(source_vertex);",
            face_cache_body,
        )
        self.assertIn("mesh_edit_preview_event_due", source)
        self.assertIn("std::uint64_t mesh_edit_selection_event_count = 0;", source)
        self.assertIn("mesh_edit_selection_event_count", source)
        self.assertIn("++stats_.mesh_edit_selection_event_count;", source)
        self.assertIn('if (command == "get_status")', source)
        self.assertIn('loaded_payload_for_event(stats_, "status")', source)
        self.assertIn("UpdateSubresource(", flush_body)
        self.assertIn("batch.vertex_buffer.Get()", flush_body)
        self.assertIn("&box", flush_body)
        self.assertIn("return elapsed_ms >= 16.0;", source)
        self.assertNotIn("return elapsed_ms >= 16.0 || (dx * dx + dy * dy) >= 9;", source)
        self.assertIn('if (command == "clear_mesh_edit_selection")', source)
        self.assertIn('if (command == "set_mesh_edit_selection")', source)
        self.assertIn("send_mesh_edit_selection_event();\n            request_render();\n            return true;", source)

        dbl_click_start = source.index("case WM_LBUTTONDBLCLK:")
        dbl_click_body = source[dbl_click_start: source.index("case WM_LBUTTONUP:", dbl_click_start)]
        self.assertIn("if (mesh_edit_.enabled || source_part_.picking_enabled)", dbl_click_body)
        self.assertIn("return true;", dbl_click_body)

    def test_rectangle_and_lasso_selection_send_native_screen_region(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        region_start = source.index("std::string mesh_edit_screen_region_json")
        region_body = source[region_start: source.index("std::string mesh_edit_payload_json", region_start)]
        self.assertIn('\\"mode\\":', region_body)
        self.assertIn('\\"start_x\\":', region_body)
        self.assertIn('\\"start_y\\":', region_body)
        self.assertIn('\\"end_x\\":', region_body)
        self.assertIn('\\"end_y\\":', region_body)
        self.assertIn('\\"points\\":', region_body)
        self.assertIn('\\"world_view_projection\\":', region_body)
        self.assertIn("XMStoreFloat4x4(&world_view_projection, current_mvp_matrix())", region_body)

        event_start = source.index("void send_mesh_edit_screen_region_selection_event")
        event_body = source[event_start: source.index("void send_mesh_edit_selection_event", event_start)]
        self.assertIn('\\"target_mode\\":', event_body)
        self.assertIn('\\"selection_depth_mode\\":', event_body)
        self.assertIn('\\"screen_region\\":', event_body)

        selection_start = source.index("void apply_mesh_edit_region_selection")
        selection_body = source[selection_start: source.index("void finish_mesh_edit_selection_drag", selection_start)]
        self.assertIn("send_mesh_edit_screen_region_selection_event(x, y)", selection_body)
        self.assertNotIn("mesh_edit_depth_filter_enabled()", selection_body)
        self.assertNotIn("mesh_edit_screen_point_in_selection_region", selection_body)
        self.assertNotIn("mesh_edit_faces_in_selection_region", selection_body)
        self.assertNotIn("apply_mesh_edit_face_selection_delta", selection_body)
        self.assertNotIn("mesh_edit_screen_vertex_visible_in_depth_mask", selection_body)

        command_start = source.index('if (command == "select_mesh_edit_region")')
        command_body = source[command_start: source.index('if (command == "update_mesh_edit_vertices")', command_start)]
        self.assertIn("mesh_edit_.selection_depth_mode = lower_copy(json_string_field(payload, \"selection_depth_mode\", mesh_edit_.selection_depth_mode));", command_body)
        self.assertIn("mesh_edit_.start_x = json_int_field(payload, \"start_x\", last_mouse_x_);", command_body)
        self.assertIn("mesh_edit_.start_y = json_int_field(payload, \"start_y\", last_mouse_y_);", command_body)
        self.assertIn("json_float_array_field(payload, \"points\")", command_body)
        self.assertIn("apply_mesh_edit_region_selection(end_x, end_y);", command_body)

    def test_select_vertices_is_selection_only_and_uses_modifier_combine(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        begin_start = source.index("bool begin_mesh_edit_drag")
        begin_body = source[begin_start: source.index("bool update_mesh_edit_drag", begin_start)]
        vertex_block = begin_body[
            begin_body.index("if (selection_mode) {"):
            begin_body.index("const bool has_resident_selection")
        ]
        selection_predicate = begin_body[
            begin_body.index("bool selection_mode ="):
            begin_body.index("if (selection_mode) {")
        ]
        self.assertIn('bool selection_mode = mesh_edit_.tool == "vertex" || remove_selection_mode;', selection_predicate)
        self.assertNotIn('mesh_edit_.target_mode == "vertex"', selection_predicate)
        self.assertNotIn('mesh_edit_.target_mode == "edge"', selection_predicate)
        self.assertNotIn('mesh_edit_.target_mode == "face"', selection_predicate)
        self.assertIn('mesh_edit_.target_mode == "selection"', begin_body)
        self.assertIn("mesh_edit_.selection_drag_active = true;", vertex_block)
        self.assertIn("mesh_edit_selection_operation_from_modifiers(wparam)", vertex_block)
        self.assertIn("apply_mesh_edit_brush_selection(x, y);", vertex_block)
        self.assertIn('if (mesh_edit_.selection_operation == "replace")', vertex_block)
        self.assertIn('mesh_edit_.selection_operation = "add";', vertex_block)
        self.assertIn("mark_mesh_edit_preview_event();", vertex_block)
        self.assertIn("return true;", vertex_block)
        self.assertNotIn("mesh_edit_stroke_started", vertex_block)

        update_start = source.index("bool update_mesh_edit_drag")
        update_body = source[update_start: source.index("bool finish_mesh_edit_drag", update_start)]
        selection_update_block = update_body[
            update_body.index("if (mesh_edit_.selection_drag_active) {"):
            update_body.index("if (!mesh_edit_.drag_active) return false;")
        ]
        self.assertIn("if (mesh_edit_preview_event_due(force_preview))", selection_update_block)
        self.assertIn("apply_mesh_edit_brush_selection(x, y);", selection_update_block)
        self.assertIn("mark_mesh_edit_preview_event();", selection_update_block)

        finish_start = source.index("bool finish_mesh_edit_drag")
        finish_body = source[finish_start: source.index("bool cancel_mesh_edit_drag", finish_start)]
        brush_finish_block = finish_body[
            finish_body.index('if (mesh_edit_.selection_mode == "brush") {'):
            finish_body.index("} else {", finish_body.index('if (mesh_edit_.selection_mode == "brush") {'))
        ]
        self.assertIn("apply_mesh_edit_brush_selection(x, y);", brush_finish_block)
        self.assertIn("mark_mesh_edit_preview_event();", brush_finish_block)
        resident_selection_start = begin_body.index("const bool has_resident_selection = !mesh_edit_.selected_vertices.empty()")
        brush_start_block = begin_body[
            resident_selection_start:
            begin_body.index(
                "if (!native_selection_tool) return true;",
                resident_selection_start,
            )
        ]
        self.assertNotIn("mesh_edit_selected_candidates()", brush_start_block)
        self.assertIn("|| !mesh_edit_.selected_edges.empty()", brush_start_block)
        self.assertIn("|| !mesh_edit_.selected_faces.empty()", brush_start_block)
        self.assertIn("|| !mesh_edit_.selected_sources.empty();", brush_start_block)
        self.assertIn('move_screen_selection_tool = mesh_edit_.tool == "move" && !has_resident_selection', brush_start_block)
        self.assertIn('grab_screen_selection_tool = mesh_edit_.tool == "grab" && mesh_edit_.target_mode == "selection" && !has_resident_selection', brush_start_block)
        self.assertIn("bool screen_selection_tool = move_screen_selection_tool || grab_screen_selection_tool", brush_start_block)
        self.assertIn("bool resident_selection_drag_tool = selection_drag_tool && has_resident_selection", brush_start_block)
        self.assertIn('mesh_edit_.tool == "grab" && mesh_edit_.target_mode != "selection"', brush_start_block)
        self.assertIn("bool screen_brush_tool = screen_selection_tool", brush_start_block)
        self.assertIn("bool native_selection_tool = screen_brush_tool || resident_selection_drag_tool", brush_start_block)
        self.assertNotIn("std::vector<EditorCandidate>", brush_start_block)
        self.assertNotIn("mesh_edit_payload_json(candidates", begin_body)
        self.assertNotIn("drag_candidates", begin_body)
        self.assertIn('mesh_edit_.target_mode == "selection"', brush_start_block)
        self.assertLess(
            brush_start_block.index('mesh_edit_.target_mode == "selection"'),
            brush_start_block.index("resident_selection_drag_tool"),
        )

        self.assertIn('if (shift_down && ctrl_down) return "toggle";', source)
        self.assertIn('if (ctrl_down) return "subtract";', source)
        self.assertIn('if (shift_down) return "add";', source)

    def test_native_brush_select_command_sends_native_screen_payload(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        brush_start = source.index("void apply_mesh_edit_brush_selection")
        brush_body = source[brush_start: source.index("bool mesh_edit_preview_event_due", brush_start)]
        self.assertIn("send_mesh_edit_screen_brush_selection_event(x, y)", brush_body)
        self.assertNotIn("candidate.source_submesh_index", brush_body)
        self.assertNotIn("candidate.source_vertex_index", brush_body)

        command_start = source.index('if (command == "select_mesh_edit_brush")')
        command_body = source[command_start: source.index('if (command == "select_mesh_edit_region")', command_start)]
        self.assertIn('json_string_field(payload, "target_mode", mesh_edit_.target_mode)', command_body)
        self.assertIn('target_mode == "vertex" || target_mode == "edge" || target_mode == "face"', command_body)
        self.assertIn('mesh_edit_.selection_mode = "brush";', command_body)
        self.assertIn('json_string_field(payload, "operation", "replace")', command_body)

        load_start = source.index("bool load_package(")
        load_body = source[load_start: source.index("bool clear_preview", load_start)]
        self.assertIn("mesh_edit_.selected_vertices.clear();", load_body)
        self.assertIn("mesh_edit_.selected_edges.clear();", load_body)
        self.assertIn("mesh_edit_.selected_faces.clear();", load_body)

    def test_native_harness_stresses_brush_drag_selection_budget(self) -> None:
        source = "\n".join(
            _read(path)
            for path in (
                "tools/mesh_harness/constants.py",
                "tools/mesh_harness/native_protocol.py",
                "tools/mesh_harness/native_smoke.py",
                "tools/mesh_harness/png_evidence.py",
            )
        )

        self.assertIn("_WM_MOUSEMOVE = 0x0200", source)
        self.assertIn("_WM_LBUTTONDOWN = 0x0201", source)
        self.assertIn("_WM_LBUTTONUP = 0x0202", source)
        self.assertIn("def _send_mouse_message(", source)
        self.assertIn("{'command': 'get_status'}", source)
        self.assertIn("for step in range(1, 61)", source)
        self.assertIn("440 + step * 4", source)
        self.assertIn("brush_drag_elapsed_ms", source)
        self.assertIn(
            "state.brush_drag_event_budget = max(4, int(math.ceil(state.brush_drag_elapsed_ms / 16.0)) + 3)",
            source,
        )
        self.assertIn("state.brush_drag_selection_event_delta", source)
        self.assertIn(
            "1 <= state.brush_drag_selection_event_delta <= state.brush_drag_event_budget",
            source,
        )
        self.assertIn("def _write_checker_png(", source)
        self.assertIn("use_textures=True", source)
        self.assertIn("texture_status_before", source)
        self.assertIn("texture_status_enabled", source)
        self.assertIn("texture_status_disabled", source)
        self.assertIn("texture_toggle_ok", source)
        self.assertIn("'enabled': False", source)

    def test_mesh_edit_selection_ids_and_topology_replacement_are_safe_for_d3d11(self) -> None:
        main_source = _mesh_edit_source()
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        bridge_source = _read("cdmw/ui/native_d3d11_preview_host.py")

        self.assertIn("source_indices_for_editor_id=_state._alignment_d3d11_source_indices_for_editor_id", main_source)
        self.assertIn("source_indices_for_editor_id(editor_submesh_index)", payload_source)
        self.assertIn("def _mesh_edit_clear_topology_selection(_state, _callbacks, ) -> None:", main_source)
        self.assertIn("_state.alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", main_source)
        selection_body = _function_source(main_source, "_mesh_edit_selection_changed")
        self.assertIn('raw_screen_region = payload.get("screen_region")', main_source)
        self.assertIn('screen_payload["screen_region"] = _state._native_screen_payload(raw_screen_region)', main_source)
        self.assertNotIn('screen_payload["screen_region"] = dict(raw_screen_region)', main_source)
        self.assertIn("def _mesh_edit_apply_native_screen_selection(", main_source)
        self.assertIn("session.select(operation=operation, _native_screen_selection_payload=screen_payload)", main_source)
        self.assertIn("_callbacks._mesh_edit_sync_d3d11_selection()", main_source)
        self.assertIn("_callbacks._mesh_edit_apply_native_screen_selection(payload, screen_payload)", selection_body)
        self.assertLess(
            selection_body.index("_callbacks._mesh_edit_apply_native_screen_selection(payload, screen_payload)"),
            selection_body.index("_state._mesh_edit_vertices_from_payload(payload)"),
        )
        self.assertIn("_state._mesh_edit_vertices_from_payload(payload)", selection_body)
        self.assertIn("_callbacks._mesh_edit_edges_from_payload(payload)", selection_body)
        self.assertIn("_state._mesh_edit_faces_from_payload(payload)", selection_body)
        self.assertIn("allowed_indices = set(int(index) for index in allowed_source_indices)", payload_source)
        self.assertIn("def _mesh_edit_i32_payload_values(", payload_source)
        payload_i32_start = payload_source.index("def _mesh_edit_i32_payload_values(")
        payload_i32_body = payload_source[
            payload_i32_start: payload_source.index("def _mesh_edit_f32_payload_values(", payload_i32_start)
        ]
        self.assertNotIn("return list(range(start, start + count))", payload_source)
        self.assertIn("return range(start, start + count)", payload_source)
        self.assertIn("raw_values = iter(group.get(json_key) or ())", payload_i32_body)
        self.assertNotIn("tuple(group.get(json_key) or ())", payload_i32_body)
        self.assertNotIn('tuple(payload.get("groups") or ())', payload_source)
        self.assertNotIn("tuple(native_groups or ())", payload_source)
        self.assertNotIn('tuple(group.get("source_edges") or ())', payload_source)
        source_indices_start = payload_source.index("def _source_vertex_indices(")
        source_indices_body = payload_source[
            source_indices_start: payload_source.index("def _contiguous_index_range", source_indices_start)
        ]
        self.assertIn("if isinstance(indices, range):", source_indices_body)
        self.assertIn("compact_range = _contiguous_valid_index_range(indices, vertex_count)", source_indices_body)
        self.assertIn("return compact_range", source_indices_body)
        self.assertLess(
            source_indices_body.index("if isinstance(indices, range):"),
            source_indices_body.index("iterator = iter(raw_indices)"),
        )
        self.assertLess(
            source_indices_body.index("compact_range = _contiguous_valid_index_range(indices, vertex_count)"),
            source_indices_body.index("iterator = iter(raw_indices)"),
        )
        self.assertIn("def _mesh_edit_f32_payload_values(", payload_source)
        self.assertIn("mesh_edit_payload_edge_groups", payload_source)
        self.assertIn("_mesh_edit_payload_edge_groups_helper", main_source)
        self.assertIn("collection_count = len(", payload_source)
        self.assertIn("if 0 <= index < collection_count:", payload_source)
        self.assertIn('payload_index_key="source_face_indices"', main_source)
        self.assertIn("mesh_edit_selected_faces_by_submesh", selection_body)
        self.assertIn("add_mesh_edit_face_vertices_to_selection(source_submesh, source_faces);", native_source)
        face_add_start = native_source.index("void add_mesh_edit_face_vertices_to_selection")
        face_add_body = native_source[
            face_add_start: native_source.index(
                "void add_mesh_edit_source_vertices_to_selection",
                face_add_start,
            )
        ]
        self.assertIn(
            "batch.cpu_source_face_vertex_lookup.find(std::pair<int, int>(source_submesh, source_face))",
            face_add_body,
        )
        self.assertLess(
            face_add_body.index("cpu_source_face_vertex_lookup.find"),
            face_add_body.index("const size_t vertex_limit"),
        )
        self.assertIn("std::set<std::tuple<int, int, int>> selected_edges;", native_source)
        self.assertIn("selected_edge_count", native_source)
        self.assertIn("mesh_edit_.selected_edges.insert(mesh_edit_edge_key(source_submesh, left, right));", native_source)
        self.assertNotIn("struct EditorCandidate", native_source)
        self.assertNotIn("struct MeshEditEdgeCandidate", native_source)
        self.assertNotIn("mesh_edit_candidates_at_in_view", native_source)
        self.assertNotIn("mesh_edit_edge_candidates_at_in_view", native_source)
        self.assertIn("source_vertex_count", native_source)
        self.assertNotIn("left >= batch.source_vertex_count || right >= batch.source_vertex_count", native_source)
        self.assertIn("source_face_count", native_source)
        self.assertIn('command == "select_mesh_edit_region"', native_source)
        self.assertIn("send_mesh_edit_screen_region_selection_event", native_source)
        self.assertNotIn("distance_to_screen_segment", native_source)
        self.assertIn('json_int_field(payload, "x", last_mouse_x_)', native_source)
        self.assertIn('json_int_field(payload, "y", last_mouse_y_)', native_source)
        self.assertIn("def _mesh_edit_edges_from_payload(_state, _callbacks, payload: object) -> dict[int, set[tuple[int, int]]]:", main_source)
        self.assertIn("_state.mesh_edit_selected_edges_by_submesh.update(_callbacks._mesh_edit_edges_from_payload(payload))", selection_body)
        edge_selection_body = _function_source(main_source, "_mesh_editor_edge_selection")
        edge_count_body = _function_source(main_source, "_mesh_editor_selected_edge_count")
        self.assertNotIn("for face in tuple(submesh.faces", edge_selection_body)
        self.assertNotIn("for face_index in set(", edge_selection_body)
        self.assertNotIn("dict(mesh_edit_selected_edges_by_submesh or {}).items()", edge_selection_body)
        self.assertNotIn("for edge_item in tuple(edge_items or ())", edge_selection_body)
        self.assertNotIn("dict(mesh_edit_selected_edges_by_submesh or {}).values()", edge_count_body)
        self.assertNotIn("len(tuple(edge_items or ()))", edge_count_body)
        self.assertIn("std::set<std::pair<int, int>> selected_faces;", native_source)
        self.assertIn("selected_face_count", native_source)
        self.assertIn("mesh_edit_.selected_faces.insert(std::pair<int, int>(source_submesh, source_face));", native_source)
        self.assertIn('const std::string target_mode = remove_screen_tool ? "face"', native_source)
        self.assertIn('target_mode == "vertex" || target_mode == "edge" || target_mode == "face" || target_mode == "source"', native_source)
        self.assertIn('json_i32_array_or_json_field(group, "source_vertex_indices_binary", "source_vertex_indices")', native_source)
        self.assertIn('json_i32_array_or_json_values_field(group, "source_edges_binary", "source_edges")', native_source)
        self.assertIn('json_i32_array_or_json_field(payload, "source_face_indices_binary", "source_face_indices")', native_source)
        self.assertIn("write_i32_range_or_descriptor_json(", native_source)
        self.assertIn('"source_vertex_start"', native_source)
        self.assertIn('"source_face_start"', native_source)
        self.assertIn("write_i32_temp_descriptor_json(edge_values, 2, L\"selection_edges\")", native_source)
        self.assertNotIn("std::string mesh_edit_groups_json", native_source)
        self.assertNotIn("L\"stroke_vertices\"", native_source)
        self.assertNotIn("L\"stroke_weights\"", native_source)
        self.assertNotIn("L\"stroke_faces\"", native_source)
        self.assertNotIn("drag_candidates", native_source)
        self.assertIn("_mesh_edit_f32_payload_values(group, \"source_vertex_weights_binary\")", payload_source)
        apply_body = _function_source(main_source, "_mesh_edit_apply_preview_payload")
        remove_body = _function_source(main_source, "_mesh_edit_apply_remove_payload")
        self.assertIn('raw_screen_brush = payload.get("screen_brush")', remove_body)
        self.assertIn('delete_mode in {"live", "release"}', remove_body)
        self.assertIn('"target_mode": "face"', remove_body)
        self.assertIn("session.select(", remove_body)
        self.assertIn("_native_screen_selection_payload=screen_payload", remove_body)
        self.assertIn('"native_release_remove_selected"', remove_body)
        self.assertIn("native_delete_groups = (", remove_body)
        self.assertIn("native_delete_vertices_by_submesh", remove_body)
        self.assertIn('"native_selected_vertices_binary_by_submesh": native_delete_vertices_by_submesh', remove_body)
        self.assertIn('delete_mode == "live" and native_delete_vertices_by_submesh', remove_body)
        self.assertIn("session.apply_current_selection(", main_source)
        self.assertNotIn("for native_group in tuple(native_delete_groups or ())", remove_body)
        self.assertIn("for native_group in native_delete_groups or ():", remove_body)
        self.assertLess(
            remove_body.index("native_delete_groups = ("),
            remove_body.index("_mesh_edit_vertices_from_payload(payload)"),
        )
        self.assertLess(
            remove_body.index('raw_screen_brush = payload.get("screen_brush")'),
            remove_body.index("native_delete_groups = ("),
        )
        self.assertIn('mesh_editor_action_bar_selection_mode = {"value": "vertex"}', main_source)
        self.assertIn('mesh_editor_action_bar_selection_mode["value"] = selection_mode', main_source)
        self.assertIn('"indices": indices', payload_source)
        self.assertIn("def _contiguous_index_range(", payload_source)
        static_contiguous_start = payload_source.index("def _contiguous_index_range(")
        static_contiguous_body = payload_source[
            static_contiguous_start: payload_source.index("def _put_index_range_or_values", static_contiguous_start)
        ]
        self.assertIn("iterator = iter(indices)", static_contiguous_body)
        self.assertIn("start = int(next(iterator))", static_contiguous_body)
        self.assertNotIn("values = tuple(", static_contiguous_body)
        self.assertNotIn("tuple(indices or ())", static_contiguous_body)
        self.assertIn(
            '_put_index_range_or_values(group, source_vertex_indices, "source_vertex_indices", "source_vertex_start", "source_vertex_count")',
            payload_source,
        )
        self.assertIn(
            '_put_index_range_or_values(group, source_face_indices, "source_face_indices", "source_face_start", "source_face_count")',
            payload_source,
        )
        self.assertNotIn('"source_vertex_indices": source_vertex_indices', payload_source)
        self.assertNotIn('"source_face_indices": source_face_indices', payload_source)
        self.assertNotIn("source_vertex_indices.append(int(vertex_index))", payload_source)
        self.assertNotIn("delete_faces_by_indices(", main_source)
        self.assertNotIn("delete_faces_touching_vertices(", main_source)
        self.assertNotIn("compact_orphan_vertices(", main_source)
        prompt_base_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py")
        for helper_name in (
            "apply_brush_deformation",
            "apply_vertex_delta",
            "build_vertex_adjacency",
            "build_x_mirror_pairs",
            "clone_mesh_for_editing",
            "compact_orphan_vertices",
            "delete_faces_by_indices",
            "delete_faces_touching_vertices",
            "recompute_mesh_normals",
            "split_faces_to_submesh",
            "subdivide_faces_touching_vertices",
        ):
            self.assertNotIn(helper_name, prompt_base_source)
        self.assertIn('"delete"', main_source)
        self.assertIn('"delete_loose_vertices"', main_source)
        self.assertIn("record_history=False", main_source)
        self.assertIn("def apply_native_mesh_compact_orphans(", _read("cdmw/modding/mesh_native_core.py"))
        self.assertIn("run_compact_orphans_for_submesh", _read("native/cdmw_mesh_core/src/main.cpp"))
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_face_candidates_at_in_view", native_source)
        self.assertNotIn("std::vector<EditorCandidate> mesh_edit_brush_candidates_at(", native_source)
        self.assertIn("source_face_indices", native_source)
        self.assertIn('group.indices = json_i32_array_or_json_field(payload, "indices_binary", "indices");', native_source)
        self.assertIn('group.indexed_payload = json_has_field(payload, "indices") || json_has_field(payload, "indices_binary");', native_source)
        self.assertIn('std::vector<int> source_faces;', native_source)
        self.assertIn('group.source_faces = json_i32_array_or_json_field(payload, "source_face_indices_binary", "source_face_indices");', native_source)
        self.assertIn('group.source_vertex_start = json_int_field(payload, "source_vertex_start", -1);', native_source)
        self.assertIn('group.source_face_start = json_int_field(payload, "source_face_start", -1);', native_source)
        triangle_update_start = native_source.index("static TriangleReplacementGroup parse_triangle_replacement_group")
        triangle_update_body = native_source[
            triangle_update_start: native_source.index("static DirectX::XMFLOAT3 transform_replacement_normal", triangle_update_start)
        ]
        self.assertIn("const bool has_source_vertex_values =", triangle_update_body)
        self.assertIn("const bool has_source_face_values =", triangle_update_body)
        self.assertIn("!has_source_vertex_values && group.source_vertex_start >= 0 && group.source_vertex_range_count > 0", triangle_update_body)
        self.assertIn("!has_source_face_values && group.source_face_start >= 0 && group.source_face_range_count > 0", triangle_update_body)
        self.assertLess(
            triangle_update_body.index("group.source_vertex_range ="),
            triangle_update_body.index('group.source_vertices = json_i32_array_or_json_field('),
        )
        self.assertLess(
            triangle_update_body.index("group.source_face_range ="),
            triangle_update_body.index('group.source_faces = json_i32_array_or_json_field('),
        )
        self.assertIn("static int triangle_source_vertex_id(", native_source)
        self.assertIn("static int triangle_source_face_id(", native_source)
        self.assertIn("batch.cpu_source_vertices.push_back(triangle_source_vertex_id(group, source_slot));", native_source)
        self.assertIn("append_vertex(index, triangle_source_face_id(group, index / 3u));", native_source)
        self.assertIn('json_bool_field(payload, "replace_all", false)', native_source)
        self.assertIn("def _mesh_edit_replace_live_triangles(_state, _callbacks, source_indices: _state.Iterable[int], *, replace_all: bool = False) -> bool:", main_source)
        replace_triangles_body = _function_source(main_source, "_mesh_edit_replace_live_triangles")
        self.assertIn("requested_source_indices = _state._mesh_edit_requested_source_indices_helper(", replace_triangles_body)
        self.assertIn("if groups or requested_source_indices:", replace_triangles_body)
        self.assertIn("if _state.alignment_d3d11_preview_host.replace_mesh_edit_triangles(", replace_triangles_body)
        self.assertIn('"mesh_edit_live_triangle_replace_failed"', replace_triangles_body)
        self.assertLess(
            replace_triangles_body.index("if groups or requested_source_indices:"),
            replace_triangles_body.index("if _state.alignment_d3d11_preview_host.replace_mesh_edit_triangles("),
        )
        self.assertIn("def _mesh_edit_replace_live_triangles_or_queue_rebuild(_state, _callbacks, source_indices: _state.Iterable[int], *, replace_all: bool = False) -> None:", main_source)
        helper_body = _function_source(main_source, "_mesh_edit_replace_live_triangles_or_queue_rebuild")
        self.assertIn("requested_source_indices = _callbacks._mesh_edit_reusable_source_indices(source_indices)", helper_body)
        self.assertIn("def _mesh_edit_reusable_source_indices(", main_source)
        reusable_body = _function_source(main_source, "_mesh_edit_reusable_source_indices")
        self.assertIn("if isinstance(source_indices, _state._SequenceABC):", reusable_body)
        self.assertIn("return source_indices", reusable_body)
        self.assertNotIn("requested_source_indices = tuple(source_indices or ())", helper_body)
        self.assertIn("_mesh_edit_replace_live_triangles_or_queue_rebuild(topology_source_indices)", main_source)
        self.assertNotIn("_mesh_edit_replace_live_triangles_or_queue_rebuild(tuple(topology_source_indices))", main_source)
        self.assertNotIn('for raw_index in tuple(getattr(result, "affected_submesh_indices", ()) or ()):', main_source)
        self.assertNotIn("for raw_index in tuple(keys() or ()):", main_source)
        self.assertIn("if _callbacks._mesh_edit_replace_live_triangles(requested_source_indices, replace_all=replace_all):", helper_body)
        self.assertIn("if _callbacks._alignment_d3d11_mesh_edit_commands_active():", helper_body)
        self.assertIn("Native D3D11 mesh edit triangle update failed; rebuilding native preview from the working mesh.", helper_body)
        self.assertIn("_mesh_editor_queue_native_preview_rebuild_from_working_mesh", helper_body)
        self.assertIn("if _state._alignment_d3d11_preview_active():", helper_body)
        self.assertIn("Native D3D11 mesh edit commands are unavailable; preview is stale.", helper_body)
        self.assertIn("if _state._mesh_edit_tab_active():", helper_body)
        self.assertIn("Active Mesh Editor triangle refresh requires native D3D11 refresh", helper_body)
        self.assertLess(helper_body.index("_callbacks._mesh_edit_replace_live_triangles("), helper_body.index("_state._queue_static_preview_rebuild()"))
        self.assertLess(
            helper_body.index("if _callbacks._alignment_d3d11_mesh_edit_commands_active():"),
            helper_body.index("_state._queue_static_preview_rebuild()"),
        )
        self.assertLess(
            helper_body.index("if _state._alignment_d3d11_preview_active():"),
            helper_body.index("_state._queue_static_preview_rebuild()"),
        )
        active_triangle_start = helper_body.index("if _state._mesh_edit_tab_active():")
        active_triangle_body = helper_body[active_triangle_start:helper_body.index("_state._queue_static_preview_rebuild()", active_triangle_start)]
        self.assertNotIn("_queue_static_preview_rebuild()", active_triangle_body)
        self.assertIn("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices(), replace_all=True)", main_source)
        self.assertIn("return replace_all", native_source)
        self.assertIn("? !requested", native_source)
        self.assertIn('<< ",\\"removed_batches\\":" << removed_batches', native_source)
        self.assertIn("new_batch.source_submesh_index = group.source_submesh;", native_source)
        self.assertIn('new_batch.editor_role = "replacement_preview";', native_source)
        self.assertIn(
            'json_float_field(\n            group.payload, "material_source_submesh_index", static_cast<float>(group.source_submesh))',
            native_source,
        )
        self.assertIn("new_batch = *material_template;", native_source)
        self.assertIn("new_batch.part_label = json_string_field(", native_source)
        self.assertIn('group.payload,\n            "material_name"', native_source)
        self.assertIn("batches_.push_back(std::move(new_batch));", native_source)
        self.assertIn('if (command == "replace_mesh_edit_triangles_file")', native_source)
        self.assertIn("read_text(payload_file)", native_source)
        self.assertIn('filename.rfind(L"cdmw_mesh_edit_triangles_", 0) == 0', native_source)
        self.assertIn('file_command="replace_mesh_edit_triangles_file"', bridge_source)
        self.assertIn('file_prefix="cdmw_mesh_edit_triangles_"', bridge_source)

    def test_mesh_edit_tool_controls_are_capability_scoped(self) -> None:
        source = _mesh_edit_source()
        state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")

        self.assertNotIn('("Selection only", "selection")', source)
        self.assertIn("_state.mesh_edit_field_rows: _state.Dict[_state.str, _state.Tuple[_state.QLabel, _state.QWidget]] = {}", source)
        self.assertIn('"select_part": "Select Whole Part"', state_source)
        self.assertIn('"invert_selection": "Invert Selection"', state_source)
        self.assertIn("_state.mesh_edit_select_part_button = _state.QPushButton(_state.mesh_edit_action_control_text['select_part'])", source)
        self.assertIn("_state.mesh_edit_invert_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['invert_selection'])", source)
        self.assertIn('"selection_actions_visible": bool(select_tool or int(selected_count) > 0)', state_source)
        self.assertIn('_set_mesh_edit_row_visible("radius", sculpt_tool or remove_tool or brush_selection_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("strength", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("falloff", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("iterations", smooth_tool)', source)
        self.assertIn('"smooth_tool": tool == "smooth"', state_source)
        self.assertIn('_set_mesh_edit_row_visible("selection", select_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible("depth", select_tool)', source)
        self.assertIn("_state.mesh_edit_mirror_checkbox.setVisible(sculpt_tool)", source)
        self.assertIn("_state.mesh_edit_select_part_button.setVisible(select_tool)", source)
        self.assertIn("_state.mesh_edit_invert_selection_button.setVisible(select_tool)", source)
        self.assertIn("_state.mesh_edit_subdivide_selection_button.setVisible(select_tool)", source)
        self.assertIn("_state.mesh_edit_refine_smooth_selection_button.setVisible(select_tool)", source)
        self.assertIn("_state.mesh_edit_split_selection_button.setVisible(select_tool)", source)
        self.assertIn("_state.mesh_edit_delete_faces_button.setVisible(select_tool)", source)
        self.assertIn("_state.mesh_edit_selected_source_indices = _state.context.get('mesh_edit_selected_source_indices')", source)
        self.assertIn("mesh_edit_selected_source_indices: set[int] = set()", _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_state_callbacks.py"))
        self.assertIn("def _mesh_edit_set_source_selection(_state, _callbacks, source_indices: _state.Iterable[int]) -> None:", source)
        set_source_body = _function_source(source, "_mesh_edit_set_source_selection")
        self.assertNotIn("for raw_index in tuple(source_indices or ())", set_source_body)
        selected_source_count_body = _function_source(source, "_mesh_edit_selected_source_vertex_count")
        self.assertNotIn('submeshes = tuple(getattr(mesh, "submeshes", ()) or ())', selected_source_count_body)
        disable_empty_body = _function_source(source, "_mesh_edit_disable_emptied_parts")
        self.assertNotIn("for source_index in tuple(source_indices or ())", disable_empty_body)
        self.assertIn("_mesh_edit_source_enable_mutation_blocked", disable_empty_body)
        self.assertNotIn("_ensure_source_part_adjustment", disable_empty_body)
        enable_block_body = _function_source(source, "_mesh_edit_source_enable_mutation_blocked")
        self.assertIn("Active Mesh Editor source enable changes require native part-state execution", enable_block_body)
        self.assertIn("Python source adjustment mutation fallback is disabled", enable_block_body)
        self.assertIn("source_indices=_state.mesh_edit_selected_source_indices", source)
        self.assertIn("def _mesh_edit_native_all_vertex_selection(", source)
        native_all_body = _function_source(source, "_mesh_edit_native_all_vertex_selection")
        self.assertIn("prune_native_mesh_selection(", native_all_body)
        self.assertIn("selected_all_vertices_by_submesh=allowed_sources", native_all_body)
        self.assertIn("current_vertices_by_submesh=_state.mesh_edit_selected_vertices_by_submesh", native_all_body)
        self.assertIn("def _mesh_edit_native_selection_unavailable(_state, _callbacks, action_text: str) -> None:", source)
        self.assertIn('_state.mesh_edit_status_label.setText(f"Native {action_text} is unavailable.")', source)
        self.assertIn("def _mesh_edit_select_whole_part(_state, _callbacks, ) -> None:", source)
        select_all_body = _function_source(source, "_mesh_edit_select_whole_part")
        self.assertIn("allowed_sources = _state._mesh_edit_allowed_source_indices()", select_all_body)
        self.assertIn("_callbacks._mesh_edit_set_source_selection(allowed_sources)", select_all_body)
        self.assertIn('_callbacks._mesh_edit_native_all_vertex_selection(operation="replace")', select_all_body)
        self.assertIn("if selection is not None:", select_all_body)
        self.assertIn('_callbacks._mesh_edit_native_selection_unavailable("Select Part")', select_all_body)
        self.assertNotIn("select_all_vertex_selection(", select_all_body)
        self.assertNotIn("_mesh_edit_all_vertices_in_scope()", select_all_body)
        self.assertLess(
            select_all_body.index("_callbacks._mesh_edit_set_source_selection(allowed_sources)"),
            select_all_body.index('_callbacks._mesh_edit_native_all_vertex_selection(operation="replace")'),
        )
        self.assertLess(
            select_all_body.index('_callbacks._mesh_edit_native_all_vertex_selection(operation="replace")'),
            select_all_body.index('_callbacks._mesh_edit_native_selection_unavailable("Select Part")'),
        )
        self.assertIn("def _mesh_edit_invert_selection(_state, _callbacks, ) -> None:", source)
        invert_body = _function_source(source, "_mesh_edit_invert_selection")
        self.assertIn("allowed_sources = tuple(_state._mesh_edit_allowed_source_indices())", invert_body)
        self.assertIn("_state.mesh_edit_selected_source_indices and not (", invert_body)
        self.assertIn("_callbacks._mesh_edit_set_source_selection(source for source in allowed_sources if source not in selected_sources)", invert_body)
        self.assertIn('_callbacks._mesh_edit_native_all_vertex_selection(operation="toggle")', invert_body)
        self.assertIn('_callbacks._mesh_edit_native_selection_unavailable("Invert Selection")', invert_body)
        self.assertNotIn("invert_vertex_selection(", invert_body)
        self.assertNotIn("_mesh_edit_all_vertices_in_scope()", invert_body)
        self.assertLess(
            invert_body.index("_callbacks._mesh_edit_set_source_selection(source for source in allowed_sources if source not in selected_sources)"),
            invert_body.index('_callbacks._mesh_edit_native_all_vertex_selection(operation="toggle")'),
        )
        self.assertLess(
            invert_body.index('_callbacks._mesh_edit_native_all_vertex_selection(operation="toggle")'),
            invert_body.index('_callbacks._mesh_edit_native_selection_unavailable("Invert Selection")'),
        )
        self.assertIn("def _mesh_edit_native_vertex_selection(", source)
        native_selection_body = _function_source(source, "_mesh_edit_native_vertex_selection")
        self.assertIn("apply_native_mesh_selection(", native_selection_body)
        self.assertIn("selected_edges_by_submesh=selected_edges", native_selection_body)
        self.assertIn("selected_faces_by_submesh=selected_faces", native_selection_body)
        self.assertIn("source_indices=selected_sources", native_selection_body)
        self.assertIn("operation=operation", native_selection_body)
        self.assertIn("state.mesh_edit_selection_worker_state = {", source)
        self.assertIn("def _mesh_edit_start_selection_worker(", source)
        selection_worker_body = _function_source(source, "_mesh_edit_start_selection_worker")
        self.assertIn("worker = _state.MeshEditCommandWorker(", selection_worker_body)
        self.assertIn('_state.MeshEditCommand("select", selection=selection, params={"operation": operation}, mode="edit")', selection_worker_body)
        self.assertIn("session.controller.mesh_service", selection_worker_body)
        self.assertIn("thread.start(_state.QThread.LowPriority)", selection_worker_body)
        self.assertNotIn("_mesh_edit_record_snapshot()", selection_worker_body)
        self.assertNotIn("_mesh_edit_pop_undo_snapshot()", selection_worker_body)
        for operation, action_text in (
            ("grow", "Grow Selection"),
            ("shrink", "Shrink Selection"),
            ("smooth", "Smooth Selection"),
        ):
            action_body = _function_source(source, f"_mesh_edit_{operation}_selection")
            worker_call = f'_callbacks._mesh_edit_start_selection_worker("{operation}", "{operation.capitalize()} Selection")'
            native_call = f'_callbacks._mesh_edit_native_vertex_selection("{operation}")'
            unavailable_call = f'_callbacks._mesh_edit_native_selection_unavailable("{action_text}")'
            self.assertIn(worker_call, action_body)
            self.assertIn(native_call, action_body)
            self.assertIn(unavailable_call, action_body)
            self.assertNotIn("_mesh_edit_cached_vertex_selection(", action_body)
            self.assertLess(action_body.index(worker_call), action_body.index(native_call))
            self.assertLess(action_body.index(native_call), action_body.index(unavailable_call))
        for action_name in (
            "_mesh_edit_delete_selected_faces",
            "_mesh_edit_subdivide_selection",
            "_mesh_edit_split_selection_to_part",
        ):
            action_body = _function_source(source, action_name)
            self.assertIn("selected_sources = _callbacks._mesh_editor_action_source_indices()", action_body)
            self.assertIn("selected_source_indices=selected_sources", action_body)
            self.assertIn("source_indices=selected_sources", action_body)
        self.assertIn("mesh_edit_select_part_button.clicked.connect", source)
        self.assertIn("mesh_edit_invert_selection_button.clicked.connect", source)

    def test_mesh_edit_sculpt_payloads_map_d3d11_editor_ids_to_source_ids(self) -> None:
        source = _mesh_edit_source()
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        apply_body = _function_source(source, "_mesh_edit_apply_geometry_payload")

        self.assertIn("_state._mesh_edit_payload_native_vertex_groups_helper(", apply_body)
        self.assertIn("source_indices_for_editor_id=_state._alignment_d3d11_source_indices_for_editor_id", apply_body)
        self.assertIn("allowed_source_indices=_state._mesh_edit_allowed_source_indices()", apply_body)
        self.assertIn("allowed_indices = set(int(index) for index in allowed_source_indices)", payload_source)
        self.assertIn("editor_submesh_index = int(group.get(\"source_submesh_index\", -1))", payload_source)
        self.assertIn("source_indices_for_editor_id(editor_submesh_index)", payload_source)
        self.assertIn("for source_submesh_index in source_indices:", payload_source)
        self.assertIn("if source_submesh_index not in allowed_indices:", payload_source)
        self.assertIn("def _mesh_editor_action_result_within_allowed_scope(_state, _callbacks, result: object) -> bool:", source)
        self.assertIn("_state._mesh_edit_allowed_source_indices(require_enabled=False)", source)
        self.assertIn("Mesh Editor action blocked outside selected scope", source)

    def test_mesh_edit_loading_watchdog_clears_stale_d3d11_state(self) -> None:
        source = _mesh_edit_source()
        presentation_source = _read("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py")
        worker_source = _read("cdmw/workers/d3d11_package_workers.py")
        package_source = "\n".join(
            (
                _read("cdmw/rendering/native_preview_package.py"),
                _read("cdmw/rendering/native_preview_package_writer.py"),
            )
        )
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertIn("def _reset_alignment_d3d11_request_state(", source)
        self.assertIn("def _alignment_d3d11_request_active() -> bool:", source)
        self.assertIn("_state._clear_stuck_alignment_d3d11_loading('loading watchdog')", source)
        self.assertIn("Preview idle.", source)
        self.assertIn("_alignment_d3d11_loading_cleared_performance_helper(", source)
        self.assertIn('"D3D11 preview loading state cleared."', presentation_source)
        self.assertIn("def _set_alignment_d3d11_progress(", source)
        self.assertIn("Preview reload restarted.", source)
        self.assertIn("_alignment_d3d11_restart_performance_helper(", source)
        self.assertIn("D3D11 preview reload restarted", presentation_source)
        self.assertIn('"stale_reload_restart_count": 0', source)
        self.assertIn("def _alignment_d3d11_live_frame_available() -> bool:", source)
        self.assertIn("active=not live_frame_available", source)
        self.assertIn("progress_changed = Signal(int, int, int, str)", worker_source)
        self.assertIn("class _AlignmentD3D11PackageWorkerReceiver(_state.QObject):", source)
        self.assertIn("@_state.Slot(int, int, int, str)", source)
        self.assertIn("@_state.Slot(int, object, float, float)", source)
        self.assertIn("@_state.Slot(int, str)", source)
        self.assertIn("_state.alignment_d3d11_package_worker_receiver.handle_progress", source)
        self.assertIn("_state.alignment_d3d11_package_worker_receiver.handle_completed", source)
        self.assertIn("_state.alignment_d3d11_package_worker_receiver.handle_error", source)
        self.assertIn("_state.Qt.QueuedConnection", source)
        self.assertIn('percent = int(round(float(payload.get("percent", 0) or 0)))', source)
        self.assertIn("on_progress: Optional[Callable[[int, int, str], None]] = None", package_source)
        self.assertIn("on_progress=_emit_package_progress", worker_source)
        self.assertIn('\\"percent\\":85', native_source)
        self.assertIn('\\"percent\\":90', native_source)
        self.assertIn("resources_loaded_payload", native_source)
        self.assertIn('loaded_payload_for_event(stats, "resources_loaded")', native_source)
        self.assertIn('\\"render_suppressed_reason\\"', native_source)
        self.assertIn('\\"parent_renderable\\"', native_source)

    def test_mesh_edit_raw_package_and_live_restore_paths_exist(self) -> None:
        source = _mesh_edit_source()
        worker_source = _read("cdmw/workers/d3d11_package_workers.py")
        d3d11_cache_source = _read("cdmw/ui/archive_browser/static_replacement_d3d11_cache.py")
        d3d11_presentation_source = _read("cdmw/ui/archive_browser/static_replacement_d3d11_presentation_state.py")
        raw_preview_state_source = _read("cdmw/ui/archive_browser/static_replacement_raw_preview_state.py")
        mesh_edit_state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")

        self.assertIn("_mesh_edit_raw_preview_active = lambda", source)
        self.assertIn("def mesh_edit_raw_preview_initial_state() -> dict[str, bool]:", raw_preview_state_source)
        self.assertIn(
            "mesh_edit_raw_preview_state = _mesh_edit_raw_preview_initial_state_helper()",
            source,
        )
        self.assertIn(
            "_mesh_edit_raw_preview_record_state_helper(",
            source,
        )
        self.assertIn("def _mesh_edit_apply_preview_mode_transition(reason: str) -> None:", source)
        self.assertIn('"mesh_edit_preview_mode_transition"', source)
        self.assertIn('_alignment_d3d11_invalidate_package_cache("mesh_edit_mode")', source)
        transition_start = source.index("def _mesh_edit_apply_preview_mode_transition(reason: str) -> None:")
        transition_body = source[transition_start: source.index("def _commit_spinbox_text", transition_start)]
        self.assertIn("_alignment_d3d11_clear_active_package_helper(", transition_body)
        self.assertIn("context.get('alignment_d3d11_preview_host')", source)
        self.assertIn("set_mesh_edit_state(enabled=False, source_submesh_indices=())", transition_body)
        self.assertLess(
            transition_body.index("_alignment_d3d11_clear_active_package_helper("),
            transition_body.index("_queue_static_preview_refresh()"),
        )
        self.assertLess(
            transition_body.index("_alignment_d3d11_clear_active_package_helper("),
            transition_body.index("_queue_texture_preview_refresh()"),
        )
        finalize_body = _function_source(source, "_mesh_editor_finalize_edit_mode_exit")
        post_exit_body = _function_source(source, "_mesh_editor_queue_post_edit_textured_preview_rebuild")
        toggle_body = _function_source(source, "_mesh_edit_enabled_toggled")
        self.assertIn("_state.mesh_edit_enabled_checkbox.setChecked(False)", finalize_body)
        self.assertIn("_callbacks._mesh_editor_sync_static_replacement_session_to_working_mesh", finalize_body)
        self.assertIn("_state._mesh_edit_apply_preview_mode_transition", post_exit_body)
        self.assertIn("_callbacks._mesh_editor_queue_post_edit_textured_preview_rebuild", finalize_body)
        self.assertIn("if not edit_enabled:", toggle_body)
        self.assertIn('_callbacks._mesh_editor_finalize_edit_mode_exit("mesh_edit_toggle", mesh_changed=True)', toggle_body)
        self.assertIn("_queue_texture_preview_refresh()", post_exit_body)
        self.assertLess(
            post_exit_body.index("_mesh_edit_apply_preview_mode_transition"),
            post_exit_body.index("_queue_texture_preview_refresh"),
        )
        self.assertNotIn("_queue_static_preview_rebuild()", post_exit_body)
        self.assertNotIn("_restore_textured_preview_after_mesh_edit_surface_exit", source)
        self.assertIn("def alignment_d3d11_raw_package_active_or_pending(state: Mapping[str, object]) -> bool:", source)
        self.assertIn('_alignment_d3d11_raw_package_active_or_pending_helper(alignment_d3d11_state)', source)
        self.assertIn('"request_package_qualities": {},', source)
        self.assertIn('"package_quality": "normal",', source)
        self.assertIn('normalized_reason in {"material", "mesh_edit_mode"}', d3d11_cache_source)
        self.assertIn('"mode_dirty"', d3d11_cache_source)

        self.assertIn('state["package_quality"] = str(package_quality or "normal")', d3d11_cache_source)
        self.assertIn('state["package_quality"] = "normal"', d3d11_cache_source)
        self.assertIn("_queue_texture_preview_refresh()", source)
        self.assertNotIn('_mesh_edit_apply_preview_mode_transition("left_mesh_edit_tab")', source)
        self.assertIn('_state.mesh_edit_surface_tab_state["active"] = _state._mesh_edit_surface_tab_active(index)', source)
        self.assertIn("def _mesh_edit_surface_tab_active(_state, _callbacks, index: int | None = None) -> bool:", source)
        self.assertIn('"classic mesh editing"', source)
        self.assertIn('"merged mesh editing"', source)
        self.assertIn('state.mesh_edit_surface_tab_state = {"active": state._mesh_edit_surface_tab_active()}', source)
        self.assertNotIn("previous_surface = bool(mesh_edit_surface_tab_state.get(\"active\"))", source)
        self.assertIn("def _mesh_edit_commit_geometry_preview_state(_state, _callbacks, ) -> None:", source)
        commit_body = _function_source(source, "_mesh_edit_commit_geometry_preview_state")
        self.assertIn("_callbacks._mesh_editor_remember_static_replacement_session_mesh()", commit_body)
        self.assertIn("_state.static_preview_geometry_cache.clear()", commit_body)
        self.assertIn("_state.static_preview_prepared_cache.clear()", commit_body)
        self.assertIn('_state._mark_alignment_d3d11_rebuild_reason("geometry")', commit_body)
        self.assertIn('_state._alignment_d3d11_invalidate_package_cache("geometry")', commit_body)
        self.assertNotIn('return _alignment_d3d11_fast_render_settings(settings), False, False, "fast_geometry"', source)
        self.assertIn('return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "material_refresh"', d3d11_presentation_source)
        self.assertIn('return clamp_model_preview_render_settings(settings), high_quality_textures, enable_material_combiner, "mesh_edit_raw"', d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_all_support_maps = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_normal_map = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_material_map = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_height_map = True", d3d11_presentation_source)
        self.assertIn("def _mesh_edit_raw_preview_active_value() -> bool:", source)
        self.assertIn("mesh_edit_raw_package = _state._mesh_edit_raw_preview_active_value()", source)
        self.assertIn("worker_use_textures = bool(getattr(settings, 'use_textures_by_default', True))", source)
        self.assertIn("original_reference_material_parity=worker_original_reference_material_parity", source)
        self.assertIn("reuse_prepared_geometry=bool(geometry_signature)", source)
        self.assertIn("def _mesh_by_source_identity", worker_source)
        poll_body = _function_source(source, "_poll_alignment_d3d11_status")
        loaded_start = poll_body.index("if event == 'loaded':")
        loaded_block = poll_body[loaded_start: poll_body.index("elif event == 'loading':", loaded_start)]
        self.assertIn("_sync_mesh_edit_preview_settings_if_ready()", loaded_block)
        self.assertIn("enable_material_combiner=bool(self.enable_material_combiner and self.use_textures)", worker_source)
        self.assertIn("def _mesh_edit_full_reset_mesh(_state, _callbacks, ) -> None:", source)
        self.assertIn('"full_reset_mesh": "Full Reset Mesh"', mesh_edit_state_source)
        self.assertIn("_state.mesh_edit_full_reset_button = _state.QPushButton(_state.mesh_edit_action_control_text['full_reset_mesh'])", source)
        self.assertIn("_mesh_edit_part_enabled_snapshot = lambda", source)
        self.assertIn("def _mesh_edit_restore_enabled_snapshot(_state, _callbacks, snapshot: object) -> None:", source)
        restore_enabled_body = _function_source(source, "_mesh_edit_restore_enabled_snapshot")
        self.assertIn("bool(snapshot.get('metadata_only'))", restore_enabled_body)
        self.assertIn("restore(current)", restore_enabled_body)
        self.assertIn("_mesh_edit_source_enable_mutation_blocked", restore_enabled_body)
        self.assertNotIn("_ensure_source_part_adjustment", restore_enabled_body)
        self.assertNotIn("adjustment.enabled", restore_enabled_body)
        self.assertNotIn("def _mesh_edit_restore_adjustment_snapshot", source)
        self.assertIn("mesh_edit_should_restore_deleted_output(", mesh_edit_state_source)
        self.assertIn("def _mesh_edit_restore_base_sources_native(_state, _callbacks, source_indices: _state.Sequence[int], *, operation: str) -> bool:", source)
        native_restore_body = _function_source(source, "_mesh_edit_restore_base_sources_native")
        self.assertIn("restore_native_mesh_submeshes_from_mesh", native_restore_body)
        self.assertIn("timeout_seconds=20.0", native_restore_body)
        reset_body = _function_source(source, "_mesh_edit_reset_scope")
        full_reset_body = _function_source(source, "_mesh_edit_full_reset_mesh")
        for body in (reset_body, full_reset_body):
            self.assertIn("restore_deleted_output_by_source: dict[int, bool] = {}", body)
            self.assertIn("restore_deleted_output_by_source[source_index] = _state._mesh_edit_should_restore_deleted_output_helper(", body)
            self.assertIn("_callbacks._mesh_edit_restore_base_sources_native(source_indices, operation=", body)
            self.assertIn("_callbacks._mesh_edit_abort_recorded_snapshot()", body)
            self.assertIn("Python geometry clone fallback is disabled.", body)
            self.assertIn("_callbacks._mesh_edit_source_enable_mutation_blocked", body)
            self.assertNotIn("_ensure_source_part_adjustment", body)
            self.assertNotIn("adjustment.enabled = True", body)
            self.assertNotIn("allow_python_full_mesh_clone_fallback(", body)
            self.assertNotIn("copy.deepcopy(\n                    base_source", body)
        self.assertIn("def _mesh_edit_transformed_sources_for_live_preview(_state, _callbacks, source_indices: _state.Iterable[int])", source)
        self.assertIn("def _mesh_edit_submesh_for_live_preview(_state, _callbacks, source_index: int):", source)
        self.assertIn(
            "alignment_basis_mesh=_state._mesh_edit_state.replacement_mesh_base_for_mapping or _state._mesh_edit_state.replacement_mesh_for_mapping",
            source,
        )
        self.assertIn("transformed_sources_by_index = _callbacks._mesh_edit_transformed_sources_for_live_preview", source)
        self.assertIn("alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", source)
        self.assertIn("_mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices)", source)

    def test_action_bar_sculpt_tools_select_live_brush_and_move_stays_selection_drag(self) -> None:
        source = _mesh_edit_source()

        action_body = _function_source(source, "_mesh_editor_action_bar_action_requested")
        select_body = _function_source(source, "_select_mesh_edit_tool")
        self.assertIn("_callbacks._sync_mesh_edit_preview_settings()", select_body)
        show_body = _function_source(source, "_show_mesh_edit_tab")
        self.assertNotIn("setCurrentWidget", show_body)
        self.assertNotIn("set_current_widget(mesh_edit_tab)", show_body)
        self.assertIn('if key == "transform_move":', action_body)
        self.assertIn('return _callbacks._select_mesh_edit_tool("grab", active_action_key="transform_move")', action_body)
        self.assertIn('if command == "brush":', action_body)
        brush_block = action_body[action_body.index('if command == "brush":'): action_body.index('if command in _SERVICE_TOPOLOGY_ACTIONS:', action_body.index('if command == "brush":'))]
        self.assertIn("return _callbacks._select_mesh_edit_tool(tool, active_action_key=active_key)", brush_block)
        self.assertNotIn("_mesh_editor_apply_selected_brush_action", brush_block)
        self.assertIn('if str(_state.mesh_editor_action_bar_active_tool_key.get("value") or "") == "transform_move":', source)
        self.assertIn('return "selection"', source)
        sync_body = _function_source(source, "_sync_mesh_editor_tab_action_state")
        self.assertIn('mode = "edit" if editing_active else "object"', sync_body)
        self.assertIn("selected_edge_count", sync_body)
        self.assertNotIn('mode = "sculpt" if editing_active and sculpt_tool', sync_body)
        refresh_body = _function_source(source, "_refresh_mesh_edit_controls")
        self.assertIn("selected_element_count = selected_count + selected_face_count + selected_edge_count", refresh_body)
        self.assertIn("vertex_selection_active", refresh_body)
        self.assertIn("_state.mesh_edit_grow_selection_button.setEnabled(vertex_selection_active and not topology_busy)", refresh_body)
        self.assertIn('"generate_tangents"', source)
        self.assertIn('"sharpen_normals"', source)
        self.assertIn('"soften_normals"', source)
        self.assertIn('"weighted_normals"', source)
        self.assertIn('"copy_normals"', source)
        self.assertIn('if command == "refine_smooth":', action_body)
        self.assertIn("_callbacks._mesh_edit_subdivide_selection(refine_smooth=True)", action_body)
        self.assertIn("_SERVICE_CLEANUP_ACTIONS = frozenset(", source)
        self.assertIn('"remove_doubles"', source)
        self.assertIn('"delete_loose_vertices"', source)
        self.assertIn('"fill_holes"', source)
        cleanup_body = source[source.index("_SERVICE_CLEANUP_ACTIONS = frozenset("):source.index("_SERVICE_NON_TOPOLOGY_ACTIONS = frozenset(")]
        self.assertNotIn('"triangulate_display"', cleanup_body)
        self.assertNotIn('"quadrangulate_display"', cleanup_body)
        self.assertIn('if command in {"triangulate_display", "quadrangulate_display"}:', action_body)
        self.assertIn("legacy display-shape cleanup", action_body)
        worker_source = _read("cdmw/workers/mesh_editor_workers.py")
        self.assertIn('_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})', worker_source)
        self.assertIn("legacy display-shape cleanup", worker_source)
        self.assertIn("_SERVICE_NON_TOPOLOGY_ACTIONS = frozenset(", source)
        self.assertIn("require_selection=False", action_body)
        self.assertNotIn("def _mesh_editor_selected_brush_bounds(", source)
        self.assertNotIn("def _mesh_editor_apply_selected_brush_action(", source)
        self.assertNotIn('if command == "brush" or key == "transform_move":', action_body)
        ui_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py")
        compact_body = _function_source(ui_source, "_mesh_geometry_preview_step_008")
        self.assertNotIn('"recalculate_normals"', compact_body)
        self.assertNotIn('"weighted_normals"', compact_body)
        self.assertNotIn('"flip_normals"', compact_body)

    def test_native_mesh_edit_events_are_late_bound_to_real_callbacks(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py")

        connect_body = _function_source(source, "_setup_options_transform_step_016")
        self.assertIn("_state.preview_widget.mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))", connect_body)
        self.assertIn("_state.preview_widget.mesh_edit_stroke_previewed.connect(lambda payload: _state._mesh_edit_apply_preview_payload(payload))", connect_body)
        self.assertIn("_state.preview_widget.mesh_edit_stroke_finished.connect(lambda payload: _state._mesh_edit_finish_stroke(payload))", connect_body)
        self.assertIn("_state.preview_widget.mesh_edit_selection_changed.connect(lambda payload: _state._mesh_edit_selection_changed(payload))", connect_body)
        self.assertIn("_state.alignment_d3d11_preview_host.mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))", connect_body)
        self.assertIn("_state.alignment_d3d11_preview_host.mesh_edit_stroke_previewed.connect(lambda payload: _state._mesh_edit_apply_preview_payload(payload))", connect_body)
        self.assertIn("_state.alignment_d3d11_preview_host.mesh_edit_stroke_finished.connect(lambda payload: _state._mesh_edit_finish_stroke(payload))", connect_body)
        self.assertIn("_state.alignment_d3d11_preview_host.mesh_edit_selection_changed.connect(lambda payload: _state._mesh_edit_selection_changed(payload))", connect_body)

    def test_static_replacement_topology_actions_use_background_worker(self) -> None:
        source = _mesh_edit_source()
        tab_source = _read("cdmw/ui/mesh_editor/tab.py")
        worker_source = _read("cdmw/workers/mesh_editor_workers.py")

        self.assertIn("from cdmw.workers.mesh_editor_workers import MeshEditCommandWorker", source)
        self.assertNotIn("MESH_EDIT_TOPOLOGY_ASYNC_SELECTION_THRESHOLD", source)
        self.assertNotIn("def _mesh_edit_topology_selection_size(", source)
        should_worker_body = _function_source(source, "_mesh_edit_should_run_topology_worker")
        self.assertIn("return True", should_worker_body)
        self.assertNotIn("_mesh_edit_topology_selection_size", should_worker_body)
        self.assertIn("def _mesh_edit_start_topology_worker(", source)
        self.assertIn("QProgressDialog(f\"Applying {action_text}...\"", source)
        self.assertIn("progress.canceled.connect(_callbacks._mesh_edit_cancel_topology_worker)", source)
        self.assertIn("worker.completed.connect(", source)
        self.assertIn("worker.cancelled.connect(_callbacks._mesh_edit_topology_worker_cancelled)", source)
        self.assertIn("worker.error.connect(_callbacks._mesh_edit_topology_worker_failed)", source)
        self.assertIn("thread.start(_state.QThread.LowPriority)", source)
        self.assertIn("def _mesh_edit_worker_active(_state, _callbacks, ) -> bool:", source)
        self.assertIn("if _callbacks._mesh_edit_worker_active():", source)
        self.assertIn("commit_callback=_callbacks._mesh_edit_commit_delete_result", source)
        self.assertIn("_callbacks._mesh_edit_commit_subdivide_result(", source)
        self.assertIn("commit_callback=_callbacks._mesh_edit_commit_split_result", source)
        self.assertIn("worker = _state.MeshEditCommandWorker(", source)
        self.assertIn("command = _state.MeshEditCommand(", source)
        self.assertIn("session.controller.mesh_service", source)
        self.assertIn("before = session.submesh_counts", source)
        self.assertNotIn("for submesh in session.controller.working_mesh(clone=False).submeshes", source)
        self.assertIn("session._result(edit_result, before=before, selection=selection)", source)
        action_bar_body = _function_source(source, "_mesh_editor_apply_action_bar_service_action")
        self.assertIn("if _callbacks._mesh_edit_start_topology_worker(", action_bar_body)
        self.assertLess(
            action_bar_body.index("if _callbacks._mesh_edit_start_topology_worker("),
            action_bar_body.index("result = _callbacks._mesh_editor_apply_static_replacement_edit("),
        )
        self.assertNotIn("MeshTopologyEditApplyWorker", source)
        self.assertNotIn("class MeshTopologyEditApplyWorker(QObject):", worker_source)
        self.assertNotIn("apply_static_replacement_mesh_edit(", worker_source)
        self.assertIn("MeshEditCommandWorker", tab_source)
        self.assertIn("class MeshEditCommandWorker(QObject):", worker_source)
        self.assertNotIn("MESH_EDITOR_STANDALONE_ASYNC_SELECTION_THRESHOLD", tab_source)
        self.assertIn("def _should_run_standalone_action_worker(", tab_source)
        self.assertIn("def _start_standalone_action_worker(", tab_source)
        self.assertIn('QProgressDialog(f"Applying {action_text}..."', tab_source)
        self.assertIn("progress.canceled.connect(self._cancel_standalone_action_worker)", tab_source)
        self.assertIn("thread.start(QThread.LowPriority)", tab_source)
        self.assertIn("service.apply_command(", worker_source)
        self.assertIn("self.service.undo(", worker_source)
        self.assertIn("self.service.redo(", worker_source)
        run_start = tab_source.index("def _run_standalone_action(")
        run_body = tab_source[run_start: tab_source.index("def _finish_standalone_action_execution(", run_start)]
        self.assertIn("if self._should_run_standalone_action_worker(action, controller):", run_body)
        self.assertIn("return self._start_standalone_action_worker(action, action_text=text)", run_body)
        self.assertLess(
            run_body.index("self._should_run_standalone_action_worker(action, controller)"),
            run_body.index("controller.run_editor_action(action)"),
        )
        self.assertIn('params["stop_event"] = self.stop_event', worker_source)

    def test_mesh_editor_ui_does_not_call_legacy_geometry_helpers_directly(self) -> None:
        forbidden = (
            "apply_mesh_edit_geometry_action(",
            "delete_faces_by_indices(",
            "delete_faces_touching_vertices(",
            "subdivide_faces_touching_vertices(",
            "split_faces_to_submesh(",
            "MeshTopologyEditApplyWorker",
        )
        runtime_files = (
            "cdmw/ui/mesh_editor/controller.py",
            "cdmw/ui/mesh_editor/tab.py",
            "cdmw/workers/mesh_editor_workers.py",
            "cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py",
            "cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py",
            "cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py",
        )
        for relative in runtime_files:
            source = _read(relative)
            for token in forbidden:
                with self.subTest(file=relative, token=token):
                    self.assertNotIn(token, source)

    def test_mesh_edit_strokes_reuse_session_topology_cache(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py")
        remaining_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py")
        callback_factory_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py")
        prompt_state_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_state_callbacks.py")
        prompt_setup_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py")
        prompt_preflight_source = _read("cdmw/ui/archive_browser/static_replacement_prompt_preflight.py")
        ui_sections_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py")
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        mesh_native_source = _mesh_native_core_source()
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")
        sparse_history_source = _read("cdmw/ui/archive_browser/static_replacement_sparse_history.py")

        self.assertNotIn("mesh_edit_session_cache: dict[str, object] = {", source)
        self.assertNotIn("def _mesh_edit_cached_vertex_selection(", source)
        self.assertNotIn('"selection_expansion": {}', source)
        self.assertNotIn("def _mesh_edit_selection_cache_key(", source)
        self.assertNotIn("_MESH_EDIT_SELECTION_CACHE_VERTEX_LIMIT", source)
        self.assertIn("def _mesh_edit_native_selection_unavailable(_state, _callbacks, action_text: str) -> None:", source)
        self.assertIn('_state.mesh_edit_status_label.setText(f"Native {action_text} is unavailable.")', source)
        begin_body = _function_source(source, "_mesh_edit_begin_stroke")
        self.assertNotIn("_mesh_edit_cached_adjacency", source)
        self.assertNotIn("_mesh_edit_cached_mirror_pairs", source)
        self.assertNotIn("build_vertex_adjacency(submesh)", begin_body)
        self.assertNotIn("build_x_mirror_pairs(submesh.vertices)", begin_body)
        self.assertIn(
            "def _mesh_edit_push_undo_snapshot(_state, _callbacks, snapshot: _state.ParsedMesh, *, take_ownership: bool = False) -> bool:",
            source,
        )
        self.assertIn("def _mesh_edit_pop_active_stroke_snapshots(_state, _callbacks, ) -> None:", source)
        self.assertIn("def _mesh_edit_capture_undo_snapshot(", source)
        self.assertIn("def _mesh_edit_restore_undo_snapshot(", source)
        capture_undo_body = _function_source(source, "_mesh_edit_capture_undo_snapshot")
        self.assertIn("snapshot_native_mesh_submeshes(snapshot)", capture_undo_body)
        self.assertIn("mesh_edit_native_undo_snapshot_failed", capture_undo_body)
        self.assertIn("Python full-mesh undo snapshot fallback is disabled.", capture_undo_body)
        self.assertNotIn("clone_mesh_for_static_replacement_native_first(", capture_undo_body)
        self.assertNotIn("fallback_allowed=_mesh_edit_python_undo_snapshot_fallback_allowed", capture_undo_body)
        self.assertNotIn("clone_mesh_for_editing(snapshot)", capture_undo_body)
        self.assertNotIn("def _mesh_edit_python_undo_snapshot_fallback_allowed", source)
        self.assertNotIn("allow_python_mesh_history_snapshot_fallback", source)
        self.assertIn("def _mesh_edit_capture_live_stroke_base_snapshot(_state, _callbacks, mesh: _state.ParsedMesh) -> object | None:", source)
        self.assertIn("def _mesh_edit_restore_live_stroke_base_snapshot(_state, _callbacks, snapshot: object) -> bool:", source)
        self.assertIn("def _mesh_edit_clear_active_stroke(_state, _callbacks, ) -> None:", source)
        self.assertIn("def clone_mesh_for_static_replacement_native_first(", sparse_history_source)
        self.assertIn("snapshot_native_mesh_submeshes(mesh)", sparse_history_source)
        self.assertIn("restore_native_mesh_submesh_snapshot(restored, native_snapshot)", sparse_history_source)
        self.assertIn("allow_python_full_mesh_clone_fallback(mesh, operation, reason)", sparse_history_source)
        self.assertIn("clone_mesh_for_static_replacement_native_first(", prompt_preflight_source)
        self.assertNotIn("replacement_mesh_base_for_mapping = clone_mesh_for_editing(", prompt_setup_source)
        self.assertNotIn("replacement_mesh_for_mapping = clone_mesh_for_editing(", prompt_setup_source)
        self.assertIn("edited_source_mesh = _state.replacement_mesh_for_mapping", callback_factory_source)
        self.assertIn("def clone_static_replacement_options_for_worker(", sparse_history_source)
        self.assertNotIn("edited_source_mesh = clone_mesh_for_editing(", callback_factory_source)
        live_base_capture_body = _function_source(source, "_mesh_edit_capture_live_stroke_base_snapshot")
        self.assertIn("snapshot_native_mesh_submeshes(mesh)", live_base_capture_body)
        self.assertIn("mesh_edit_native_live_stroke_snapshot_failed", live_base_capture_body)
        self.assertIn("Python full-mesh live stroke clone fallback is disabled.", live_base_capture_body)
        self.assertNotIn("clone_mesh_for_static_replacement_native_first(", live_base_capture_body)
        self.assertNotIn("fallback_allowed=_mesh_edit_python_live_stroke_clone_fallback_allowed", live_base_capture_body)
        self.assertNotIn("return clone_mesh_for_editing(mesh)", live_base_capture_body)
        live_base_restore_body = _function_source(source, "_mesh_edit_restore_live_stroke_base_snapshot")
        self.assertIn('snapshot.get("kind") == "native_submesh_snapshot"', live_base_restore_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(restored, snapshot)", live_base_restore_body)
        self.assertIn("if isinstance(snapshot, _state.ParsedMesh):\n        return False", live_base_restore_body)
        self.assertNotIn("_mesh_edit_clone_parsed_mesh_snapshot(", live_base_restore_body)
        self.assertNotIn(
            "_mesh_edit_state.replacement_mesh_for_mapping = clone_mesh_for_editing(snapshot)",
            live_base_restore_body,
        )
        clear_active_body = _function_source(source, "_mesh_edit_clear_active_stroke")
        self.assertIn('_state.release_mesh_history_snapshot(_state.mesh_edit_active_stroke.get("base"))', clear_active_body)
        self.assertEqual(source.count("_state.mesh_edit_active_stroke.clear()"), 1)
        normal_fallback_body = _function_source(source, "_mesh_edit_python_normal_fallback_allowed")
        self.assertNotIn("for raw_index in tuple(source_indices or ())", normal_fallback_body)
        restore_undo_body = _function_source(source, "_mesh_edit_restore_undo_snapshot")
        self.assertIn('snapshot.get("kind") == "native_submesh_snapshot"', restore_undo_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(restored, snapshot)", restore_undo_body)
        self.assertIn("if isinstance(snapshot, _state.ParsedMesh):\n        return None", restore_undo_body)
        self.assertNotIn("def _mesh_edit_clone_parsed_mesh_snapshot(", source)
        self.assertNotIn('"history.static_undo_snapshot_restore"', restore_undo_body)
        self.assertNotIn("clone_mesh_for_static_replacement_native_first(", restore_undo_body)
        self.assertNotIn("fallback_allowed=fallback_allowed", restore_undo_body)
        self.assertNotIn("clone_mesh_for_editing(snapshot)", restore_undo_body)
        self.assertIn("stored_snapshot = _callbacks._mesh_edit_capture_undo_snapshot(snapshot, take_ownership=take_ownership)", source)
        self.assertIn("if stored_snapshot is None:\n        return False", source)
        self.assertIn("retain_mesh_history_snapshot(stored_snapshot)", source)
        self.assertIn("_state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)", source)
        self.assertIn("'_push_geometry_sparse_mesh_edit_snapshot',", source)
        self.assertIn("native_screen_stroke = tool != \"remove\" and (", begin_body)
        self.assertIn("native_descriptor_stroke = (bool(native_descriptor_groups) or native_screen_stroke) and callable(", begin_body)
        self.assertLess(
            begin_body.index("native_descriptor_stroke = (bool(native_descriptor_groups) or native_screen_stroke) and callable("),
            begin_body.index("if not native_descriptor_stroke:"),
        )
        self.assertIn("snapshot = _callbacks._mesh_edit_capture_live_stroke_base_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)", begin_body)
        self.assertLess(
            begin_body.index("snapshot = _callbacks._mesh_edit_capture_live_stroke_base_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)"),
            begin_body.index('_state._push_geometry_undo_snapshot("Mesh edit stroke")'),
        )
        self.assertIn("undo_source = snapshot if isinstance(snapshot, _state.ParsedMesh) else _state._mesh_edit_state.replacement_mesh_for_mapping", begin_body)
        self.assertIn("_callbacks._mesh_edit_push_undo_snapshot(undo_source, take_ownership=isinstance(snapshot, _state.ParsedMesh))", begin_body)
        self.assertIn('"native_descriptor_stroke": native_descriptor_stroke', begin_body)
        self.assertIn('"undo_snapshot_pushed": not native_descriptor_stroke', begin_body)
        self.assertIn('"geometry_snapshot_pushed": not native_descriptor_stroke', begin_body)
        self.assertIn('"geometry_history_mesh_edit_revision": int(_state.mesh_edit_revision.get("value", 0) or 0)', begin_body)
        self.assertLess(
            begin_body.index("if not native_descriptor_stroke:"),
            begin_body.index('_state._push_geometry_undo_snapshot("Mesh edit stroke")'),
        )
        self.assertIn('"snapshot": snapshot', begin_body)
        self.assertIn('"base": snapshot', begin_body)
        self.assertNotIn("clone_mesh_for_editing(_mesh_edit_state.replacement_mesh_for_mapping)", begin_body)
        self.assertNotIn("clone_mesh_for_editing(snapshot)", begin_body)
        self.assertIn("def _push_geometry_sparse_mesh_edit_snapshot(", remaining_source)
        self.assertIn("def _restore_sparse_mesh_edit_geometry_history_state(", remaining_source)
        self.assertIn("snapshot.get('kind') != 'native_sparse_vertex_delta'", remaining_source)
        self.assertIn("def _geometry_history_mesh_snapshot(", remaining_source)
        self.assertIn("snapshot_native_mesh_submeshes(mesh)", remaining_source)
        self.assertIn("allow_python_mesh_history_snapshot_fallback", remaining_source)
        remaining_snapshot_body = _function_source(remaining_source, "_geometry_history_mesh_snapshot")
        self.assertLess(
            remaining_snapshot_body.index("snapshot_native_mesh_submeshes(mesh)"),
            remaining_snapshot_body.index("clone_mesh_for_static_replacement_native_first("),
        )
        self.assertIn("fallback_allowed=_state._geometry_python_mesh_snapshot_fallback_allowed", remaining_snapshot_body)
        self.assertNotIn("return clone_mesh_for_editing(mesh)", remaining_snapshot_body)
        self.assertIn("def _geometry_history_restore_mesh_snapshot(", remaining_source)
        self.assertIn("restore_native_mesh_submesh_snapshot(restored, snapshot)", remaining_source)
        remaining_restore_mesh_body = "\n".join(
            (
                _function_source(remaining_source, "_geometry_history_restore_mesh_snapshot"),
                _function_source(remaining_source, "_geometry_history_clone_parsed_mesh_snapshot"),
            )
        )
        self.assertIn("return _state._geometry_history_clone_parsed_mesh_snapshot(snapshot)", remaining_restore_mesh_body)
        self.assertIn("'history.static_geometry_snapshot_restore'", remaining_restore_mesh_body)
        self.assertIn("_state.clone_mesh_for_static_replacement_native_first(", remaining_restore_mesh_body)
        self.assertIn("fallback_allowed=_state._geometry_python_mesh_snapshot_fallback_allowed", remaining_restore_mesh_body)
        self.assertNotIn("clone_mesh_for_editing(snapshot)", remaining_restore_mesh_body)
        self.assertIn("def _release_geometry_history_snapshot(", remaining_source)
        self.assertIn("dispose_native_mesh_submesh_snapshot(value)", remaining_source)
        remaining_capture_body = _function_source(remaining_source, "_capture_geometry_history_state")
        self.assertIn("replacement_snapshot = None if metadata_only else _state._geometry_history_mesh_snapshot(_state.state.replacement_mesh_for_mapping)", remaining_capture_body)
        self.assertIn("replacement_base_snapshot = None if metadata_only else _state._geometry_history_mesh_snapshot(_state.state.replacement_mesh_base_for_mapping)", remaining_capture_body)
        self.assertIn("if not metadata_only and _state.state.replacement_mesh_for_mapping is not None and replacement_snapshot is None:", remaining_capture_body)
        self.assertIn(
            "if not metadata_only and _state.state.replacement_mesh_base_for_mapping is not None and replacement_base_snapshot is None:",
            remaining_capture_body,
        )
        self.assertIn("replacement_mesh=replacement_snapshot", remaining_capture_body)
        self.assertIn("replacement_base_mesh=replacement_base_snapshot", remaining_capture_body)
        self.assertNotIn("replacement_mesh=clone_mesh_for_editing(state.replacement_mesh_for_mapping)", remaining_capture_body)
        self.assertNotIn(
            "replacement_base_mesh=clone_mesh_for_editing(state.replacement_mesh_base_for_mapping)",
            remaining_capture_body,
        )
        self.assertIn("if _state._restore_sparse_mesh_edit_geometry_history_state(snapshot):", remaining_history_restore_body := _function_source(remaining_source, "_restore_geometry_history_state"))
        self.assertLess(
            remaining_history_restore_body.index("if _state._restore_sparse_mesh_edit_geometry_history_state(snapshot):"),
            remaining_history_restore_body.index("_state._geometry_history_restore_state_helper(snapshot"),
        )
        self.assertIn("def _geometry_history_restore_mutation_blocked() -> bool:", remaining_source)
        self.assertIn(
            "Active Mesh Editor geometry history restore requires native history execution; Python state restore fallback is disabled.",
            remaining_source,
        )
        self.assertIn("_push_geometry_sparse_mesh_edit_snapshot", prompt_state_source)
        self.assertIn("def mesh_edit_payload_native_vertex_groups(", payload_source)
        self.assertIn("def mesh_edit_cleanup_native_vertex_group_descriptors(", payload_source)
        self.assertIn("_mesh_edit_payload_native_vertex_groups_helper", source)
        self.assertNotIn("native_descriptor_handled = False", source)
        self.assertNotIn("for native_group in native_descriptor_groups:", source)
        descriptor_body = _function_source(source, "_mesh_edit_sparse_descriptor_groups")
        self.assertIn('raw_snapshot_id = str(', descriptor_body)
        self.assertIn('group["native_sparse_snapshot_id"] = raw_snapshot_id', descriptor_body)
        self.assertIn("groups.append(group)", descriptor_body)
        self.assertNotIn("not isinstance(raw_indices, (tuple, list)) or not isinstance(raw_binary, Mapping)", descriptor_body)
        self.assertIn("retain_sparse_vertex_snapshot(snapshot)", remaining_source)
        self.assertIn("release_sparse_vertex_snapshot(snapshot)", remaining_source)
        restore_guard = "if not restore_state.metadata_only and _state._geometry_history_restore_mutation_blocked():"
        self.assertIn(restore_guard, remaining_history_restore_body)
        self.assertLess(
            remaining_history_restore_body.index("if _state._restore_sparse_mesh_edit_geometry_history_state(snapshot):"),
            remaining_history_restore_body.index(restore_guard),
        )
        self.assertLess(
            remaining_history_restore_body.index("_state._geometry_history_restore_state_helper(snapshot"),
            remaining_history_restore_body.index(restore_guard),
        )
        self.assertLess(
            remaining_history_restore_body.index(restore_guard),
            remaining_history_restore_body.index("_state.state.replacement_mesh_for_mapping = _state._geometry_history_restore_mesh_snapshot(replacement_mesh)"),
        )
        self.assertLess(
            remaining_history_restore_body.index(restore_guard),
            remaining_history_restore_body.index("_state.texture_override_assignments.clear()"),
        )
        self.assertLess(
            remaining_history_restore_body.index(restore_guard),
            remaining_history_restore_body.index("_state.source_material_texture_override_assignments.clear()"),
        )
        self.assertIn(
            "_state.state.replacement_mesh_for_mapping = _state._geometry_history_restore_mesh_snapshot(replacement_mesh)",
            remaining_history_restore_body,
        )
        self.assertIn(
            "_state.state.replacement_mesh_base_for_mapping = _state._geometry_history_restore_mesh_snapshot(replacement_base_mesh)",
            remaining_history_restore_body,
        )
        self.assertNotIn(
            "clone_mesh_for_editing(replacement_mesh) if isinstance(replacement_mesh, ParsedMesh)",
            remaining_history_restore_body,
        )
        self.assertIn("_geometry_refresh_full_restore_preview()", remaining_history_restore_body)
        self.assertNotIn(
            "state.replacement_preview_model = parsed_mesh_to_preview_model(state.replacement_mesh_for_mapping) if state.replacement_mesh_for_mapping is not None else None",
            remaining_history_restore_body,
        )
        self.assertNotIn("_queue_static_preview_rebuild()", remaining_history_restore_body)
        remaining_push_body = _function_source(remaining_source, "_push_geometry_undo_snapshot")
        self.assertIn("if not snapshot:", remaining_push_body)
        self.assertLess(
            remaining_push_body.index("if not snapshot:"),
            remaining_push_body.index("_geometry_history_push_state_helper("),
        )
        self.assertIn("_release_geometry_history_snapshot(snapshot)", remaining_push_body)
        self.assertIn("_release_geometry_history_snapshot(old_snapshot)", remaining_push_body)
        remaining_undo_body = _function_source(remaining_source, "_undo_geometry_change")
        self.assertIn("_release_geometry_history_snapshot(snapshot)", remaining_undo_body)
        self.assertNotIn("release_sparse_vertex_snapshot(snapshot)", remaining_undo_body)
        self.assertIn("_state.clear_mesh_history_snapshot_stack(_state.mesh_edit_undo_stack)", remaining_source)
        self.assertIn("_state.clear_mesh_history_snapshot_stack(_state.mesh_edit_redo_stack)", remaining_source)
        apply_body = "\n".join(
            (
                _function_source(source, "_mesh_edit_apply_preview_payload"),
                _function_source(source, "_mesh_edit_apply_geometry_payload"),
                _function_source(source, "_mesh_edit_apply_remove_payload"),
            )
        )
        self.assertLess(
            apply_body.index("native_descriptor_groups = ("),
            apply_body.index("if has_screen_drag or has_screen_brush or has_screen_radius:"),
        )
        self.assertNotIn("def _mesh_edit_python_live_stroke_clone_fallback_allowed", source)
        self.assertNotIn('"live_edit.static_stroke_clone"', source)
        self.assertNotIn("_mesh_edit_python_live_stroke_clone_fallback_allowed(base_mesh)", apply_body)
        self.assertNotIn("clone_mesh_for_editing(base_mesh)", apply_body)
        self.assertNotIn('clone_mesh_for_editing(mesh_edit_active_stroke["base"])', apply_body)
        self.assertNotIn("native_descriptor_uses_step_delta = bool(native_descriptor_groups)", apply_body)
        self.assertIn("Python inverse transform fallback is disabled", apply_body)
        self.assertNotIn(
            'if bool(mesh_edit_active_stroke.get("native_descriptor_stroke")) or _alignment_d3d11_mesh_edit_commands_active():',
            apply_body,
        )
        self.assertNotIn("vertex_groups = _mesh_edit_payload_vertex_groups_helper", apply_body)
        self.assertIn("_NATIVE_STROKE_HISTORY_ATTR = \"cdmw_native_mesh_history_vertex_delta\"", source)
        self.assertIn("def _mesh_edit_sparse_descriptor_groups(", source)
        self.assertIn("def _mesh_edit_capture_native_stroke_delta(", source)
        self.assertIn("def _mesh_edit_restore_native_stroke_delta(", source)
        self.assertIn("def _mesh_edit_sparse_vertex_snapshot(", source)
        self.assertIn("def _mesh_edit_current_sparse_vertex_snapshot(", source)
        self.assertIn("def _mesh_edit_restore_sparse_vertex_snapshot(", source)
        self.assertIn("def _mesh_edit_descriptor_vertex_range(", source)
        self.assertIn("def _mesh_edit_descriptor_vertex_values(", source)
        self.assertIn('"vertex_index_start": vertex_range[0]', source)
        self.assertIn('"vertex_index_count": vertex_range[1]', source)
        self.assertIn("for raw_index in raw_indices:", source)
        self.assertIn("def allow_python_sparse_history_restore_fallback(", sparse_history_source)
        self.assertIn("def allow_python_full_mesh_clone_fallback(", sparse_history_source)
        self.assertNotIn("_PYTHON_SPARSE_HISTORY_FALLBACK_VERTEX_LIMIT", sparse_history_source)
        self.assertNotIn("_PYTHON_SPARSE_HISTORY_FALLBACK_FACE_LIMIT", sparse_history_source)
        self.assertIn("Python full-mesh clone fallback blocked while native mesh core is available", sparse_history_source)
        self.assertNotIn("allow_python_sparse_history_restore_fallback(", source)
        self.assertNotIn('"history.static_sparse_restore"', source)
        self.assertNotIn('"history.static_sparse_current"', source)
        self.assertIn("Native sparse history restore failed; Python restore fallback is disabled.", source)
        self.assertIn("Native sparse history current snapshot failed; Python snapshot fallback is disabled.", source)
        self.assertNotIn("allow_python_sparse_history_restore_fallback(", remaining_source)
        self.assertNotIn('"history.static_geometry_sparse_restore"', remaining_source)
        self.assertIn("Native geometry history restore failed; Python restore fallback is disabled.", remaining_source)
        self.assertIn("Native geometry normal recompute failed; Python normal fallback is disabled.", remaining_source)
        current_sparse_body = _function_source(source, "_mesh_edit_current_sparse_vertex_snapshot")
        self.assertIn("snapshot_native_mesh_sparse_vertex_positions", current_sparse_body)
        self.assertIn("_mesh_edit_python_sparse_current_fallback_allowed(", current_sparse_body)
        self.assertNotIn("vertices = getattr(", current_sparse_body)
        self.assertNotIn('vertices = tuple(getattr(submeshes[submesh_index], "vertices", ()) or ())', current_sparse_body)
        self.assertNotIn("tuple(dict(raw_positions_by_vertex).keys())", current_sparse_body)
        self.assertNotIn('submeshes = tuple(getattr(_mesh_edit_state.replacement_mesh_for_mapping, "submeshes", ()) or ())', current_sparse_body)
        self.assertNotIn("dict(before_by_submesh or {}).items()", current_sparse_body)
        self.assertNotIn("vertex_count = len(vertices)", current_sparse_body)
        self.assertNotIn("else raw_positions_by_vertex.keys()", current_sparse_body)
        self.assertIn('entry["groups"].extend(descriptor_groups)', source)
        self.assertIn('positions[submesh_index] = {"groups": descriptor_groups}', source)
        self.assertNotIn("_mesh_edit_sparse_positions_for_fallback", source)
        self.assertNotIn("submesh.vertices = vertices", source)
        self.assertNotIn("_sparse_mesh_edit_positions_for_fallback", remaining_source)
        self.assertNotIn("submesh.vertices = vertices", remaining_source)
        self.assertNotIn("recompute_submesh_normals", remaining_source)
        restore_sparse_body = _function_source(source, "_mesh_edit_restore_sparse_vertex_snapshot")
        self.assertIn("def _mesh_edit_changed_vertex_groups_for_live_update(", source)
        range_groups_body = _function_source(source, "_mesh_edit_changed_vertex_groups_for_live_update")
        self.assertIn("compact_range = _callbacks._mesh_edit_changed_vertex_range(raw_vertices)", range_groups_body)
        self.assertIn("changed[submesh_index] = compact_range", range_groups_body)
        self.assertIn("if isinstance(raw_vertices, _state.Mapping):", range_groups_body)
        self.assertIn("changed[submesh_index] = dict(raw_vertices)", range_groups_body)
        self.assertIn("changed_vertices_by_submesh: dict[int, object] = {}", restore_sparse_body)
        self.assertIn("native_restore_applied = native_restore is not None", restore_sparse_body)
        self.assertIn("_mesh_edit_changed_vertex_groups_for_live_update(native_restore or {})", restore_sparse_body)
        self.assertIn("_mesh_edit_python_sparse_restore_fallback_allowed(mesh, before_by_submesh)", restore_sparse_body)
        self.assertNotIn("submeshes = getattr(mesh", restore_sparse_body)
        self.assertNotIn("for raw_submesh_index, raw_positions_by_vertex in before_by_submesh.items():", restore_sparse_body)
        self.assertIn("normal_changed_vertices_by_submesh: dict[int, object] = {}", restore_sparse_body)
        self.assertIn("_mesh_edit_changed_vertex_groups_for_live_update(native_normals or {})", restore_sparse_body)
        self.assertIn("if native_restore_applied and _state._alignment_d3d11_preview_active():", restore_sparse_body)
        self.assertIn('mesh_edit_preview_model_dirty["value"] = True', restore_sparse_body)
        self.assertLess(
            restore_sparse_body.index("if native_restore_applied and _state._alignment_d3d11_preview_active():"),
            restore_sparse_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        self.assertNotIn("_mesh_edit_index_groups_as_sets_helper(native_restore or {})", restore_sparse_body)
        sparse_snapshot_body = _function_source(source, "_mesh_edit_sparse_vertex_snapshot")
        capture_native_body = _function_source(source, "_mesh_edit_capture_native_stroke_delta")
        self.assertNotIn('submeshes = tuple(getattr(mesh, "submeshes", ()) or ())', capture_native_body)
        self.assertIn("for raw_submesh_index, raw_positions_by_vertex in before_by_submesh.items():", sparse_snapshot_body)
        self.assertIn("for raw_vertex_index, raw_position in raw_positions_by_vertex.items():", sparse_snapshot_body)
        self.assertNotIn("dict(before_by_submesh).items()", sparse_snapshot_body)
        self.assertNotIn("dict(raw_positions_by_vertex).items()", sparse_snapshot_body)
        remaining_restore_body = _function_source(remaining_source, "_restore_sparse_mesh_edit_geometry_history_state")
        self.assertIn("def apply_native_mesh_sparse_vertex_restore(", mesh_native_source)
        self.assertIn('"restore-vertices-json"', mesh_native_source)
        self.assertIn('"apply_native_mesh_sparse_vertex_restore"', mesh_native_source)
        self.assertIn('raw_groups = raw_positions_by_vertex.get("groups")', mesh_native_source)
        self.assertIn("restore_groups = tuple(raw_groups)", mesh_native_source)
        self.assertIn("descriptor_positions_binary = _native_binary_descriptor(", mesh_native_source)
        self.assertIn("_new_native_sparse_vertex_snapshot_id", mesh_native_source)
        self.assertIn('"sparse_snapshot_id"', mesh_native_source)
        self.assertIn('"native_sparse_snapshot_id"', mesh_native_source)
        self.assertIn("def dispose_native_mesh_sparse_vertex_snapshot(", mesh_native_source)
        self.assertIn('prefix = sidecar_root / f"restore_{submesh_index}_{len(submeshes)}"', mesh_native_source)
        self.assertIn("def snapshot_native_mesh_sparse_vertex_positions(", mesh_native_source)
        sparse_snapshot_start = mesh_native_source.index("def snapshot_native_mesh_sparse_vertex_positions(")
        sparse_snapshot_body = mesh_native_source[
            sparse_snapshot_start: mesh_native_source.index("def snapshot_native_mesh_submeshes", sparse_snapshot_start)
        ]
        self.assertNotIn("tuple(dict(raw_positions_by_vertex).keys())", sparse_snapshot_body)
        self.assertNotIn("dict(vertex_indices_by_submesh).items()", sparse_snapshot_body)
        self.assertIn("raw_index_groups = (raw_positions_by_vertex.keys(),)", sparse_snapshot_body)
        self.assertIn('"snapshot-vertices-json"', mesh_native_source)
        self.assertIn('"before_positions_output_path": _native_preview_delta_output_path("_snapshot_positions.bin")', mesh_native_source)
        self.assertIn("**_native_history_delta_vertex_payload(delta)", mesh_native_source)
        self.assertNotIn('"vertex_indices": delta["vertex_indices"]', mesh_native_source)
        self.assertIn("run_restore_vertices(", native_core_source)
        self.assertIn("run_snapshot_vertices(", native_core_source)
        self.assertIn('"vertex_index_start"', native_core_source)
        self.assertIn('"vertex_index_count"', native_core_source)
        native_core_compact = "".join(native_core_source.split())
        self.assertIn(
            'int_vector_from_binary_or_json(item,"vertex_indices_binary","vertex_indices","vertex_index_start","vertex_index_count")',
            native_core_compact,
        )
        self.assertIn("g_sparse_vertex_snapshots", native_core_source)
        self.assertIn("sparse_vertex_snapshot_positions_from_item", native_core_source)
        self.assertIn('"clear_sparse_snapshot"', native_core_source)
        self.assertIn('"native_sparse_snapshot_id"', native_core_source)
        self.assertIn("restore_vertices_json_command", native_core_source)
        self.assertIn("snapshot_vertices_json_command", native_core_source)
        self.assertIn('if (command == "restore-vertices-json")', native_core_source)
        self.assertIn('if (command == "snapshot-vertices-json")', native_core_source)
        native_restore_start = native_core_source.index("std::vector<SubmeshTransformResult> run_restore_vertices(")
        native_restore_body = native_core_source[
            native_restore_start: native_core_source.index("std::vector<Vec2> remap_vec2_by_index_map", native_restore_start)
        ]
        self.assertIn("std::map<int, std::set<int>> restored_indices_by_submesh;", native_restore_body)
        self.assertIn("restored_indices.find(vertex_index) != restored_indices.end()", native_restore_body)
        self.assertIn(
            'result.before_positions_path = string_or(item.get("before_positions_output_path"), "");',
            native_restore_body,
        )
        native_sparse_restore_start = mesh_native_source.index("def apply_native_mesh_sparse_vertex_restore(")
        native_sparse_restore_body = mesh_native_source[
            native_sparse_restore_start: mesh_native_source.index("def apply_native_mesh_selection(", native_sparse_restore_start)
        ]
        self.assertIn("history_delta: bool = False", native_sparse_restore_body)
        self.assertIn("def _put_vertex_indices_payload(", mesh_native_source)
        self.assertIn('start_key="vertex_index_start"', mesh_native_source)
        self.assertIn('count_key="vertex_index_count"', mesh_native_source)
        self.assertNotIn("dict(before_positions_by_submesh).items()", native_sparse_restore_body)
        self.assertIn("_put_vertex_indices_payload(", native_sparse_restore_body)
        self.assertIn('item["before_positions_output_path"] = _native_preview_delta_output_path("_before_positions.bin")', native_sparse_restore_body)
        self.assertIn("apply_native_mesh_sparse_vertex_restore(mesh, before_by_submesh)", restore_sparse_body)
        self.assertLess(
            restore_sparse_body.index("apply_native_mesh_sparse_vertex_restore(mesh, before_by_submesh)"),
            restore_sparse_body.index("_mesh_edit_python_sparse_restore_fallback_allowed(mesh, before_by_submesh)"),
        )
        self.assertIn("return False", restore_sparse_body)
        self.assertNotIn('submeshes = tuple(getattr(mesh, "submeshes", ()) or ())', restore_sparse_body)
        self.assertNotIn("dict(before_by_submesh).items()", restore_sparse_body)
        self.assertIn(
            "apply_native_mesh_sparse_vertex_restore(_state.state.replacement_mesh_for_mapping, before_positions)",
            remaining_restore_body,
        )
        self.assertIn("_state._mesh_edit_update_live_preview = _state.context.get('_mesh_edit_update_live_preview')", remaining_source)
        self.assertIn(
            "_mesh_edit_update_live_preview = alignment_mesh_geometry_preview_section._mesh_edit_update_live_preview",
            prompt_setup_source,
        )
        self.assertIn(
            "_state._mesh_edit_replace_live_triangles_or_queue_rebuild = _state.alignment_mesh_edit_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild",
            ui_sections_source,
        )
        self.assertIn(
            "'_mesh_edit_replace_live_triangles_or_queue_rebuild': vars(_state).get('_mesh_edit_replace_live_triangles_or_queue_rebuild')",
            ui_sections_source,
        )
        self.assertIn(
            "'_mesh_edit_update_live_preview': vars(_state).get('_mesh_edit_update_live_preview')",
            ui_sections_source,
        )
        self.assertIn(
            'getattr(\n            alignment_mesh_geometry_preview_section,\n            "_mesh_edit_replace_live_triangles_or_queue_rebuild",\n            None,\n        )',
            prompt_setup_source,
        )
        self.assertIn(
            "live_preview_updater = _state.context.get('_mesh_edit_update_live_preview') or _state._mesh_edit_update_live_preview",
            remaining_source,
        )
        self.assertIn(
            "_state._mesh_edit_replace_live_triangles_or_queue_rebuild = _state.context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')",
            remaining_source,
        )
        self.assertIn("_state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')", remaining_source)
        self.assertIn("def _geometry_changed_vertex_groups_for_live_update(", remaining_source)
        self.assertIn("def _geometry_refresh_sparse_restore_preview(", remaining_source)
        self.assertIn("def _geometry_refresh_full_restore_preview() -> None:", remaining_source)
        sparse_restore_refresh_body = _function_source(remaining_source, "_geometry_refresh_sparse_restore_preview")
        self.assertIn("if _state._geometry_mesh_edit_active():", sparse_restore_refresh_body)
        self.assertIn("Active Mesh Editor geometry restore requires native D3D11 refresh; Python preview rebuild fallback is disabled.", sparse_restore_refresh_body)
        self.assertLess(
            sparse_restore_refresh_body.index("if _state._geometry_mesh_edit_active():"),
            sparse_restore_refresh_body.index("parsed_mesh_to_preview_model("),
        )
        full_restore_refresh_body = _function_source(remaining_source, "_geometry_refresh_full_restore_preview")
        self.assertIn("_mesh_edit_replace_live_triangles_or_queue_rebuild(", full_restore_refresh_body)
        self.assertIn("replace_all=True", full_restore_refresh_body)
        self.assertIn("if _state._geometry_mesh_edit_active():", full_restore_refresh_body)
        self.assertIn("Active Mesh Editor geometry restore requires native D3D11 refresh; Python preview rebuild fallback is disabled.", full_restore_refresh_body)
        self.assertIn("_state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(", full_restore_refresh_body)
        self.assertIn("_state._queue_static_preview_rebuild()", full_restore_refresh_body)
        self.assertLess(
            full_restore_refresh_body.index("_mesh_edit_replace_live_triangles_or_queue_rebuild("),
            full_restore_refresh_body.index("parsed_mesh_to_preview_model("),
        )
        self.assertLess(
            full_restore_refresh_body.index("if _state._geometry_mesh_edit_active():"),
            full_restore_refresh_body.index("parsed_mesh_to_preview_model("),
        )
        self.assertIn(
            "changed_vertices_by_submesh = _state._geometry_changed_vertex_groups_for_live_update(native_restore or {})",
            remaining_restore_body,
        )
        self.assertIn(
            "normal_changed_vertices_by_submesh = _state._geometry_changed_vertex_groups_for_live_update(native_normals or {})",
            remaining_restore_body,
        )
        self.assertIn(
            "_state._geometry_refresh_sparse_restore_preview(normal_changed_vertices_by_submesh or changed_vertices_by_submesh",
            remaining_restore_body,
        )
        self.assertNotIn("dict(native_restore or {}).items()", remaining_restore_body)
        self.assertNotIn('submeshes = tuple(getattr(state.replacement_mesh_for_mapping, "submeshes", ()) or ())', remaining_restore_body)
        self.assertNotIn("for raw_submesh_index, raw_positions_by_vertex in before_positions.items():", remaining_restore_body)
        self.assertNotIn("_state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model(_state.state.replacement_mesh_for_mapping)", remaining_restore_body)
        self.assertLess(
            remaining_restore_body.index(
                "apply_native_mesh_sparse_vertex_restore(_state.state.replacement_mesh_for_mapping, before_positions)"
            ),
            remaining_restore_body.index(
                "_state._geometry_python_sparse_restore_fallback_allowed(_state.state.replacement_mesh_for_mapping, before_positions)"
            ),
        )
        self.assertIn("return False", remaining_restore_body)
        self.assertIn("def _mesh_edit_replace_active_undo_with_native_sparse_snapshot(", source)
        self.assertIn('"kind": "native_sparse_vertex_delta"', source)
        replace_sparse_body = _function_source(source, "_mesh_edit_replace_active_undo_with_native_sparse_snapshot")
        self.assertIn('if bool(_state.mesh_edit_active_stroke.get("undo_snapshot_pushed")) and _state.mesh_edit_undo_stack:', replace_sparse_body)
        self.assertIn("_state.mesh_edit_undo_stack.append(snapshot)", replace_sparse_body)
        self.assertIn('_state.mesh_edit_active_stroke["undo_snapshot_pushed"] = True', replace_sparse_body)
        self.assertIn("def _mesh_edit_push_active_sparse_geometry_snapshot(_state, _callbacks, ) -> None:", source)
        push_sparse_geometry_body = _function_source(source, "_mesh_edit_push_active_sparse_geometry_snapshot")
        self.assertIn('if bool(_state.mesh_edit_active_stroke.get("geometry_snapshot_pushed")):', push_sparse_geometry_body)
        self.assertIn('_state._push_geometry_sparse_mesh_edit_snapshot("Mesh edit stroke", snapshot)', push_sparse_geometry_body)
        self.assertIn('_state.mesh_edit_active_stroke["geometry_snapshot_pushed"] = True', push_sparse_geometry_body)
        self.assertIn("_callbacks._mesh_editor_result_mesh_for_state(result)", apply_body)
        self.assertIn("_callbacks._mesh_edit_capture_native_stroke_delta(", apply_body)
        self.assertIn('"_require_native_history_delta": True', apply_body)
        undo_body = _function_source(source, "_mesh_edit_undo")
        undo_local_body = undo_body[undo_body.index("snapshot = _state.mesh_edit_undo_stack.pop()"):]
        self.assertIn("current_snapshot = _callbacks._mesh_edit_current_sparse_vertex_snapshot(snapshot)", undo_body)
        self.assertLess(
            undo_local_body.index("current_snapshot = _callbacks._mesh_edit_current_sparse_vertex_snapshot(snapshot)"),
            undo_local_body.index("_callbacks._mesh_edit_capture_undo_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)"),
        )
        self.assertIn("_state.release_mesh_history_snapshot(snapshot)", undo_local_body)
        redo_body = _function_source(source, "_mesh_edit_redo")
        redo_local_body = redo_body[redo_body.index("snapshot = _state.mesh_edit_redo_stack.pop()"):]
        self.assertIn("current_snapshot = _callbacks._mesh_edit_current_sparse_vertex_snapshot(snapshot)", redo_body)
        self.assertLess(
            redo_local_body.index("current_snapshot = _callbacks._mesh_edit_current_sparse_vertex_snapshot(snapshot)"),
            redo_local_body.index("_callbacks._mesh_edit_capture_undo_snapshot(_state._mesh_edit_state.replacement_mesh_for_mapping)"),
        )
        self.assertIn("_state.release_mesh_history_snapshot(snapshot)", redo_local_body)
        finish_body = "\n".join((_function_source(source, "_mesh_edit_finish_stroke"), _function_source(source, "_mesh_edit_finish_geometry_stroke")))
        self.assertIn("_callbacks._mesh_edit_replace_active_undo_with_native_sparse_snapshot()", finish_body)
        self.assertIn("_callbacks._mesh_edit_push_active_sparse_geometry_snapshot()", finish_body)
        self.assertLess(
            finish_body.index("_callbacks._mesh_edit_replace_active_undo_with_native_sparse_snapshot()"),
            finish_body.index("_callbacks._mesh_edit_push_active_sparse_geometry_snapshot()"),
        )
        self.assertLess(
            finish_body.index("_callbacks._mesh_edit_push_active_sparse_geometry_snapshot()"),
            finish_body.index("_callbacks._mesh_edit_clear_active_stroke()", finish_body.index("_callbacks._mesh_edit_replace_active_undo_with_native_sparse_snapshot()")),
        )
        cancel_body = _function_source(source, "_mesh_edit_cancel_stroke")
        self.assertIn("if not _callbacks._mesh_edit_restore_native_stroke_delta():", cancel_body)
        self.assertLess(
            cancel_body.index("if not _callbacks._mesh_edit_restore_native_stroke_delta():"),
            cancel_body.index("_callbacks._mesh_edit_restore_snapshot(snapshot)"),
        )
        self.assertIn('if tool in {"move", "vertex"}:', source)
        self.assertIn("def _mesh_edit_native_descriptor_selection_payload(", source)
        self.assertIn('params["_native_selection_payload"] = descriptor_selection_payload', source)
        self.assertNotIn('if tool != "vertex" and callable(_mesh_edit_payload_native_vertex_groups_helper)', source)
        self.assertNotIn("if len(native_descriptor_groups) == 1:", source)
        self.assertIn("native_selected_vertices_binary_by_submesh", source)
        self.assertNotIn("_mesh_edit_cleanup_native_vertex_group_descriptors_helper([native_group])", source)
        self.assertIn("_mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_descriptor_groups)", source)
        self.assertNotIn("if not native_descriptor_handled:", source)
        self.assertIn('"mirror_x": bool(mirror_x)', mesh_native_source)
        self.assertIn('"vertex_positions_binary"', mesh_native_source)
        self.assertIn("_write_int_binary_payload", mesh_native_source)
        self.assertIn("changed_positions", native_core_source)
        self.assertIn('"pivot_from_selection": pivot is None', mesh_native_source)
        self.assertIn("bool pivot_from_selection = false;", native_core_source)
        self.assertIn("result.pivot_from_selection = bool_or(transform->get(\"pivot_from_selection\"), false);", native_core_source)
        self.assertIn("Vec3 transform_selection_pivot(const JsonValue& submeshes, const Transform& transform)", native_core_source)
        self.assertIn("transform.pivot = transform_selection_pivot(*submeshes, transform);", native_core_source)
        service_source = _read("cdmw/services/mesh_service.py")
        history_source = _read("cdmw/services/mesh_service_history.py")
        reports_source = _read("cdmw/services/mesh_service_reports.py")
        kernel_source = _read("cdmw/services/mesh_service_kernel.py")
        service_payload_source = _read("cdmw/services/mesh_service_payloads.py")
        open_start = service_source.index("    def open_edit_session(")
        open_body = service_source[open_start: service_source.index("    def close_edit_session", open_start)]
        self.assertIn("working_mesh, base_mesh = _clone_mesh_pair_for_session_open(mesh)", open_body)
        self.assertNotIn("working_mesh = clone_mesh_for_editing(mesh)", open_body)
        self.assertNotIn("base_mesh=clone_mesh_for_editing(mesh)", open_body)
        working_clone_start = service_source.index("    def working_mesh(")
        working_clone_body = service_source[working_clone_start: service_source.index("    def pose_preview_mesh(", working_clone_start)]
        self.assertIn("_clone_mesh_for_service_native_snapshot(", working_clone_body)
        self.assertIn('"session.working_mesh_clone"', working_clone_body)
        self.assertNotIn("clone_mesh_for_editing(mesh) if clone else mesh", working_clone_body)
        base_clone_start = service_source.index("    def base_mesh(")
        base_clone_body = service_source[base_clone_start: service_source.index("    def workspace_summary(", base_clone_start)]
        self.assertIn("_clone_mesh_for_service_native_snapshot(", base_clone_body)
        self.assertIn('"session.base_mesh_clone"', base_clone_body)
        self.assertNotIn("clone_mesh_for_editing(mesh) if clone else mesh", base_clone_body)
        service_clone_start = service_source.index("def _clone_mesh_pair_for_session_open(")
        service_clone_body = service_source[
            service_clone_start: service_source.index("def _dispose_history_snapshot(", service_clone_start)
        ]
        self.assertIn("if not _service_session_native_clone_supported(mesh):", service_clone_body)
        self.assertLess(
            service_clone_body.index("if not _service_session_native_clone_supported(mesh):"),
            service_clone_body.index("native_snapshot = snapshot_native_mesh_submeshes(mesh)"),
        )
        self.assertIn("native_snapshot = snapshot_native_mesh_submeshes(mesh)", service_clone_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(working_mesh, native_snapshot)", service_clone_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(base_mesh, native_snapshot)", service_clone_body)
        self.assertIn("dispose_native_mesh_submesh_snapshot(native_snapshot)", service_clone_body)
        self.assertLess(
            service_clone_body.index("native_snapshot = snapshot_native_mesh_submeshes(mesh)"),
            service_clone_body.index('_clone_mesh_pair_for_service_python_fallback(\n        mesh,\n        "session.open_clone"'),
        )
        self.assertIn("guard_native_supported=False", service_clone_body)
        self.assertIn('"session.open_clone_unsupported_topology"', service_clone_body)
        self.assertIn('"session.open_clone"', service_clone_body)
        self.assertIn("def _clone_mesh_pair_for_service_python_fallback(", service_clone_body)
        self.assertIn("def _clone_mesh_for_service_python_fallback(", service_clone_body)
        pair_helper_start = service_clone_body.index("def _clone_mesh_pair_for_service_python_fallback(")
        pair_helper_body = service_clone_body[
            pair_helper_start: service_clone_body.index("def _clone_mesh_for_service_python_fallback(", pair_helper_start)
        ]
        self.assertIn("guard_native_supported and not _allow_python_service_clone_fallback", pair_helper_body)
        self.assertLess(
            pair_helper_body.index("_allow_python_service_clone_fallback("),
            pair_helper_body.index("clone_mesh_for_editing(mesh)"),
        )
        single_helper_body = service_clone_body[service_clone_body.index("def _clone_mesh_for_service_python_fallback(") :]
        self.assertIn("guard_native_supported and not _allow_python_service_clone_fallback", single_helper_body)
        self.assertLess(
            single_helper_body.index("_allow_python_service_clone_fallback("),
            single_helper_body.index("clone_mesh_for_editing(mesh)"),
        )
        self.assertIn("def _service_session_native_clone_supported(mesh: ParsedMesh) -> bool:", service_source)
        service_clone_supported_start = service_source.index("def _service_session_native_clone_supported(")
        service_clone_supported_body = service_source[
            service_clone_supported_start: service_source.index("def _dispose_history_snapshot(", service_clone_supported_start)
        ]
        self.assertIn("if len(raw_face) != 3:", service_clone_supported_body)
        self.assertIn("vertex_index < 0 or vertex_index >= vertex_count", service_clone_supported_body)
        service_clone_fallback_start = service_source.index("def _allow_python_service_clone_fallback(")
        service_clone_fallback_body = service_source[
            service_clone_fallback_start: service_source.index("def _allow_python_pose_preview_fallback", service_clone_fallback_start)
        ]
        self.assertIn("native_mesh_core_available()", service_clone_fallback_body)
        self.assertIn("record_native_mesh_core_fallback(", service_clone_fallback_body)
        self.assertIn("prune_native_mesh_selection", service_source)
        prune_start = service_source.index("def _prune_selection_to_mesh(")
        prune_body = service_source[prune_start: service_source.index("def _valid_selected_edges_for_submesh", prune_start)]
        self.assertIn("native_pruned = prune_native_mesh_selection(", prune_body)
        self.assertIn("vertices_by_submesh=selection.vertex_map()", prune_body)
        self.assertIn("edges_by_submesh=selection.edge_map()", prune_body)
        self.assertIn("faces_by_submesh=selection.face_map()", prune_body)
        self.assertIn("source_indices=selection.source_indices", prune_body)
        self.assertIn('_allow_python_selection_fallback(mesh, "selection.prune")', prune_body)
        self.assertIn("return _source_only_selection_for_mesh(mesh, selection.source_indices)", prune_body)
        self.assertIn("submeshes = mesh.submeshes or ()", prune_body)
        self.assertIn("submesh_count = len(mesh.submeshes or ())", service_source)
        self.assertNotIn("submeshes = tuple(mesh.submeshes or ())", prune_body)
        self.assertNotIn("submesh_count = len(tuple(mesh.submeshes or ()))", service_source)
        self.assertLess(
            prune_body.index("native_pruned = prune_native_mesh_selection("),
            prune_body.index("for submesh_index, vertices in selection.vertex_map().items():"),
        )
        self.assertLess(
            prune_body.index('_allow_python_selection_fallback(mesh, "selection.prune")'),
            prune_body.index("for submesh_index, vertices in selection.vertex_map().items():"),
        )
        apply_selection_start = service_source.index("def _apply_selection_operation_to_mesh(")
        apply_selection_body = service_source[
            apply_selection_start: service_source.index("def _combine_selection_map(", apply_selection_start)
        ]
        self.assertIn("native_pruned = prune_native_mesh_selection(", apply_selection_body)
        self.assertIn('_allow_python_selection_fallback(mesh, "selection.prune")', apply_selection_body)
        self.assertIn("return _source_only_selection_after_operation(mesh, current, incoming, operation)", apply_selection_body)
        apply_command_start = service_source.index("    def apply_command(")
        apply_command_body = service_source[
            apply_command_start: service_source.index("    def _apply_selection_command(", apply_command_start)
        ]
        command_flow_body = service_source[apply_command_start: service_source.index("def _coerce_command(", apply_command_start)]
        select_command_start = service_source.index("    def _apply_selection_command(")
        select_branch_body = service_source[
            select_command_start: service_source.index("    def _apply_geometry_command(", select_command_start)
        ]
        session_view_start = service_source.index("    def session_view(")
        session_view_body = service_source[session_view_start: service_source.index("    def native_editor_mesh_dirty(", session_view_start)]
        self.assertIn("if not session.native_editor_mesh_dirty_counts:", session_view_body)
        self.assertIn("requires native submesh counts", session_view_body)
        self.assertIn("submesh_count = len(session.native_editor_mesh_dirty_counts)", session_view_body)
        self.assertNotIn("or len(session.working_mesh.submeshes)", session_view_body)
        undo_start = history_source.index("    def undo(")
        undo_body = history_source[undo_start: history_source.index("    def redo(", undo_start)]
        redo_start = history_source.index("    def redo(")
        redo_body = history_source[redo_start: history_source.index("    def _session", redo_start)]
        self.assertIn('_LEGACY_DISPLAY_CLEANUP_ACTIONS = frozenset({"triangulate_display", "quadrangulate_display"})', service_source)
        self.assertIn("allow_legacy_display_cleanup", apply_command_body)
        self.assertIn("from an explicit legacy/archive path", apply_command_body)
        self.assertIn("selection = _command_selection(edit_command)", apply_command_body)
        self.assertIn("fallback_event_start = len(native_mesh_core_fallback_events())", select_branch_body)
        self.assertIn("_native_blocked_fallback_diagnostics(fallback_event_start)", select_branch_body)
        self.assertIn("Native editor selection is unavailable; Python selection fallback is blocked.", select_branch_body)
        self.assertNotIn("_apply_selection_operation_to_mesh(", select_branch_body)
        self.assertIn(
            '_NATIVE_EDITOR_SESSION_ACTIONS = frozenset({"select"}) | (\n'
            "    frozenset(MESH_GEOMETRY_ACTIONS) - _LEGACY_DISPLAY_CLEANUP_ACTIONS\n"
            ")",
            service_source,
        )
        native_actions_start = service_source.index("_NATIVE_EDITOR_SESSION_ACTIONS =")
        native_actions_body = service_source[
            native_actions_start:service_source.index("def _attach_mesh_asset_status", native_actions_start)
        ]
        self.assertNotIn('"transform",', native_actions_body)
        self.assertNotIn('"subdivide",', native_actions_body)
        self.assertIn("require_native = action in _NATIVE_EDITOR_SESSION_ACTIONS", apply_command_body)
        dirty_non_native_body = apply_command_body[
            apply_command_body.index("if session.native_editor_mesh_dirty and not require_native:"):
            apply_command_body.index("        selection = _command_selection(edit_command)")
        ]
        self.assertIn("cannot run while native mesh state is dirty", dirty_non_native_body)
        self.assertNotIn("_sync_native_editor_session_to_working_mesh(", dirty_non_native_body)
        self.assertIn(
            "if selection is None:\n            if require_native:\n                selection = session.selection\n            else:\n                session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)\n                selection = session.selection",
            apply_command_body,
        )
        finalize_changed_start = service_source.index("    def _finalize_changed_geometry(")
        finalize_changed_body = service_source[finalize_changed_start:]
        self.assertIn(
            "elif execution.action in MESH_TOPOLOGY_ACTIONS or topology_changed:\n            session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)",
            finalize_changed_body,
        )
        self.assertNotIn(
            "session.selection = _prune_selection_to_mesh(session.working_mesh, session.selection)\n        selection = _command_selection(edit_command)",
            apply_command_body,
        )
        self.assertNotIn("else _prune_selection_to_mesh(session.working_mesh, session.selection)", apply_command_body)
        self.assertIn("_command_may_change_topology(action, command, selection)", command_flow_body)
        self.assertIn("_session_mesh_structure_signature(session)", command_flow_body)
        self.assertNotIn("_mesh_structure_signature(session.working_mesh) if action in MESH_GEOMETRY_ACTIONS else None", command_flow_body)
        self.assertNotIn("apply_native_mesh_editor_session_report", service_source)
        self.assertNotIn("def apply_native_mesh_editor_session_report(", mesh_native_source)
        self.assertNotIn('"apply_native_mesh_editor_session_report"', mesh_native_source)
        self.assertNotIn("_can_defer_native_editor_python_apply", service_source)
        self.assertNotIn("_can_defer_native_editor_history_python_apply", service_source)
        self.assertNotIn("_NATIVE_EDITOR_DEFER_PYTHON_TOPOLOGY_APPLY_ACTIONS", service_source)
        self.assertIn("def _native_editor_dirty_counts_from_report(", reports_source)
        self.assertIn("submesh_counts=dirty_counts or native_submesh_counts", service_source)
        native_apply_start = service_source.index("def _apply_native_editor_session_geometry_action(")
        native_apply_body = service_source[native_apply_start: service_source.index("def _native_live_history_snapshot(", native_apply_start)]
        dirty_guard_body = native_apply_body[native_apply_body.index("if dirty_at_start and "): native_apply_body.index("stroke_phase =")]
        self.assertIn("not session.native_editor_session_ready", dirty_guard_body)
        self.assertNotIn("_sync_native_editor_session_to_working_mesh", dirty_guard_body)
        dispatch_start = service_source.index("    def _dispatch_geometry_command(")
        dispatch_body = service_source[dispatch_start: service_source.index("    @staticmethod", dispatch_start)]
        self.assertIn("unsupported non-native mesh edit action", dispatch_body)
        self.assertLess(
            dispatch_body.index("unsupported non-native mesh edit action"),
            dispatch_body.index("apply_mesh_edit_geometry_action("),
        )
        self.assertIn("history_mode = session.mode", command_flow_body)
        self.assertIn("history_selection=session.selection", command_flow_body)
        self.assertIn("native_history = pushed_history and require_native", command_flow_body)
        self.assertIn("native mesh editor undo requires native history; Python mesh state is stale", undo_body)
        self.assertIn("native mesh editor redo requires native history; Python mesh state is stale", redo_body)
        self.assertNotIn("_sync_native_editor_session_to_working_mesh(", undo_body)
        self.assertNotIn("_sync_native_editor_session_to_working_mesh(", redo_body)
        self.assertIn(
            "pushed_history and not native_history and _can_defer_native_live_history(action, command)",
            command_flow_body,
        )
        self.assertIn('"_require_native_history_delta": True', command_flow_body)
        self.assertIn("except NativeLiveHistoryUnavailable:", dispatch_body)
        live_fallback_start = dispatch_body.index("except NativeLiveHistoryUnavailable:")
        live_fallback_body = dispatch_body[live_fallback_start:dispatch_body.index("except Exception:", live_fallback_start)]
        self.assertIn("snapshot = _snapshot(execution.session, prefer_native=True)", live_fallback_body)
        self.assertIn("native_submesh_snapshot=snapshot.native_submesh_snapshot", live_fallback_body)
        self.assertNotIn("mesh=clone_mesh_for_editing(session.working_mesh)", live_fallback_body)
        self.assertIn("_native_live_history_snapshot(", command_flow_body)
        self.assertIn("mode=execution.history_mode", command_flow_body)
        self.assertIn("selection=execution.history_selection", command_flow_body)
        self.assertIn("def _native_live_history_snapshot(", service_source)
        self.assertIn("def _vertex_indices_from_delta_descriptor(", service_source)
        self.assertIn("def _delta_vertex_indices_payload(", service_source)
        self.assertIn('"vertex_index_start"', service_source)
        self.assertIn('"vertex_index_count"', service_source)
        self.assertIn("def _restore_vertex_position_deltas(", service_source)
        restore_delta_start = service_source.index("def _restore_vertex_position_deltas(")
        restore_delta_body = service_source[
            restore_delta_start: service_source.index("def _allow_python_history_restore_fallback", restore_delta_start)
        ]
        self.assertIn("apply_native_mesh_sparse_vertex_restore", service_source)
        self.assertIn("dispose_native_mesh_sparse_vertex_snapshot", service_source)
        self.assertIn("native_sparse_snapshot_id", service_source)
        self.assertNotIn("dict(native_restore or {}).items()", restore_delta_body)
        self.assertIn(
            "native_restore = apply_native_mesh_sparse_vertex_restore(mesh, restore_positions, history_delta=True)",
            restore_delta_body,
        )
        self.assertIn("group: dict[str, object] = _delta_vertex_indices_payload(delta.vertex_indices)", restore_delta_body)
        self.assertNotIn('"vertex_indices": delta.vertex_indices', restore_delta_body)
        self.assertLess(
            restore_delta_body.index(
                "native_restore = apply_native_mesh_sparse_vertex_restore(mesh, restore_positions, history_delta=True)"
            ),
            restore_delta_body.index("_delta_positions_by_vertex(delta)"),
        )
        self.assertIn("def _delta_positions_by_vertex(", service_source)
        self.assertIn("def _restore_topology_delta(", service_source)
        self.assertIn("topology_changed=outcome.topology_changed", history_source)
        self.assertIn("affected=outcome.affected_submesh_indices", history_source)
        self.assertIn("snapshot_native_mesh_submeshes", service_source)
        self.assertIn("restore_native_mesh_submesh_snapshot", service_source)
        self.assertIn("dispose_native_mesh_submesh_snapshot", service_source)
        self.assertIn("def _dispose_history_snapshot(", service_source)
        self.assertIn("def _discard_history_snapshot(", service_source)
        self.assertIn("def _clear_history_stack(", service_source)
        self.assertNotIn("session.redo_stack.clear()", service_source)
        snapshot_start = service_source.index("def _snapshot(")
        snapshot_body = service_source[snapshot_start: service_source.index("def _restore_snapshot(", snapshot_start)]
        self.assertIn("prefer_native: bool = False", snapshot_body)
        self.assertIn("_service_session_native_clone_supported(session.working_mesh)", snapshot_body)
        self.assertLess(
            snapshot_body.index("_service_session_native_clone_supported(session.working_mesh)"),
            snapshot_body.index("snapshot_native_mesh_submeshes(session.working_mesh)"),
        )
        self.assertLess(
            snapshot_body.index("snapshot_native_mesh_submeshes(session.working_mesh)"),
            snapshot_body.index("_clone_history_snapshot_for_python_fallback(session)"),
        )
        self.assertIn("_allow_python_history_snapshot_fallback(session.working_mesh", snapshot_body)
        self.assertLess(
            snapshot_body.index("snapshot_native_mesh_submeshes(session.working_mesh)"),
            snapshot_body.index("_allow_python_history_snapshot_fallback(session.working_mesh"),
        )
        self.assertLess(
            snapshot_body.index("_allow_python_history_snapshot_fallback(session.working_mesh"),
            snapshot_body.index("_clone_history_snapshot_for_python_fallback(session)"),
        )
        self.assertIn("def _clone_history_snapshot_for_python_fallback(", snapshot_body)
        self.assertIn("def _allow_python_history_snapshot_fallback(", service_source)
        snapshot_fallback_start = service_source.index("def _allow_python_history_snapshot_fallback(")
        snapshot_fallback_body = service_source[
            snapshot_fallback_start: service_source.index("def _allow_python_pose_preview_fallback", snapshot_fallback_start)
        ]
        self.assertIn("native_mesh_core_available()", snapshot_fallback_body)
        self.assertIn("record_native_mesh_core_fallback(", snapshot_fallback_body)
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT", snapshot_fallback_body)
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_FACE_LIMIT", snapshot_fallback_body)
        self.assertIn("Python mesh history snapshot fallback blocked while native mesh core is available", snapshot_fallback_body)
        native_snapshot_start = mesh_native_source.index("def snapshot_native_mesh_submeshes(")
        native_snapshot_body = mesh_native_source[
            native_snapshot_start: mesh_native_source.index("def restore_native_mesh_submesh_snapshot(", native_snapshot_start)
        ]
        self.assertIn("face_count = _face_count_json(", native_snapshot_body)
        self.assertGreaterEqual(native_snapshot_body.count("session_id = _ensure_native_mesh_session_submesh("), 2)
        restore_start = service_source.index("def _restore_snapshot(")
        restore_body = service_source[restore_start: service_source.index("def _changed_vertices_from_deltas", restore_start)]
        self.assertIn("snapshot.native_submesh_snapshot is not None", restore_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(session.working_mesh, snapshot.native_submesh_snapshot)", restore_body)
        self.assertNotIn("restored_mesh = ParsedMesh()", restore_body)
        self.assertNotIn("session.working_mesh = restored_mesh", restore_body)
        self.assertIn("_dispose_history_snapshot(snapshot)", service_source)
        self.assertIn("def _command_may_change_topology(", kernel_source)
        controller_source = _read("cdmw/ui/mesh_editor/controller.py")
        undo_update_start = controller_source.index('if result.action in {"undo", "redo"} and result.ok')
        topology_update_start = controller_source.index("if result.topology_changed:", undo_update_start)
        undo_update_body = controller_source[undo_update_start:topology_update_start]
        self.assertIn('and not result.topology_changed', undo_update_body)
        self.assertIn("replace_all = bool(result.submesh_count_delta < 0 or not requested)", controller_source)
        self.assertIn("indexed_vertices_from_binary_or_json(item, sparse_vertex_count)", native_core_source)
        self.assertIn("return indexed_vertices_from_json(item.get(\"vertex_positions\"), vertex_count)", native_core_source)
        self.assertIn("write_sparse_preview_vertex_update_group", native_core_source)
        self.assertIn('"sparse_output": True', mesh_native_source)
        self.assertIn('"vertices_binary"', mesh_native_source)
        self.assertIn("_write_vec3_binary_payload", mesh_native_source)
        self.assertIn("class NativeMeshCoreServiceClient", mesh_native_source)
        self.assertIn("_native_mesh_core_session_cache", mesh_native_source)
        self.assertIn("_NATIVE_MESH_SESSION_TOKEN_ATTR", mesh_native_source)
        self.assertIn("def _native_mesh_session_cache_key(", mesh_native_source)
        self.assertNotIn("_native_mesh_core_session_cache[(id(mesh)", mesh_native_source)
        self.assertNotIn("cache_key = (id(mesh)", mesh_native_source)
        self.assertIn("def _ensure_native_mesh_session_submesh(", mesh_native_source)
        self.assertIn('"mesh-session-json"', mesh_native_source)
        self.assertIn('item["session_id"] = session_id', mesh_native_source)
        session_start = mesh_native_source.index("def _ensure_native_mesh_session_submesh(")
        session_body = mesh_native_source[
            session_start:mesh_native_source.index("def apply_native_morph_slider_values(", session_start)
        ]
        store_item_start = mesh_native_source.index("def _native_mesh_session_store_item(")
        store_item_body = mesh_native_source[
            store_item_start:mesh_native_source.index("def _ensure_native_mesh_session_submesh(", store_item_start)
        ]
        self.assertIn("_put_i32_range_or_binary_payload(", store_item_body)
        self.assertIn("faces_binary, source_face_indices = _write_face_binary_payload_with_source_indices(", store_item_body)
        self.assertNotIn("faces, source_face_indices = _face_json_with_source_indices(", store_item_body)
        self.assertIn('start_key="source_face_start"', store_item_body)
        self.assertIn('count_key="source_face_count"', store_item_body)
        self.assertIn('binary_key="source_face_indices_binary"', store_item_body)
        self.assertIn("_native_mesh_core_service_known_for_binary(binary)", session_body)
        self.assertIn("not _native_mesh_core_service_running(binary)", session_body)
        self.assertIn("_put_source_vertex_map_payload(item, prefix", store_item_body)
        source_map_payload_start = mesh_native_source.index("def _put_source_vertex_map_payload(")
        source_map_payload_body = mesh_native_source[
            source_map_payload_start:mesh_native_source.index("def _i32_range_report_values(", source_map_payload_start)
        ]
        self.assertIn('start_key="source_vertex_map_start"', source_map_payload_body)
        self.assertIn('count_key="source_vertex_map_count"', source_map_payload_body)
        self.assertIn('binary_key="source_vertex_map_binary"', source_map_payload_body)
        self.assertNotIn("_put_source_vertex_map_payload(item, prefix, tuple(", mesh_native_source)
        self.assertNotIn("_put_source_vertex_offsets_payload(item, prefix, tuple(", mesh_native_source)
        self.assertNotIn("_put_source_vertex_offsets_payload(item, None, tuple(", mesh_native_source)
        contiguous_range_start = mesh_native_source.index("def _contiguous_i32_range(")
        contiguous_range_body = mesh_native_source[
            contiguous_range_start:mesh_native_source.index("def _contiguous_i32_stride_range", contiguous_range_start)
        ]
        self.assertIn("if isinstance(values, range):", contiguous_range_body)
        self.assertIn("iterator = iter(values)", contiguous_range_body)
        self.assertIn("first = int(next(iterator))", contiguous_range_body)
        self.assertNotIn("items = tuple(", contiguous_range_body)
        range_report_start = mesh_native_source.index("def _i32_range_report_values(")
        range_report_body = mesh_native_source[
            range_report_start:mesh_native_source.index("def _write_edge_binary_payload", range_report_start)
        ]
        self.assertNotIn("return list(range(start, start + count))", range_report_body)
        self.assertIn("return range(start, start + count)", range_report_body)
        self.assertIn("def _put_source_vertex_offsets_payload(", mesh_native_source)
        self.assertIn("def _contiguous_i32_stride_range(", mesh_native_source)
        self.assertIn('item["source_vertex_offsets_start"] = start', mesh_native_source)
        self.assertIn('item["source_vertex_offsets_count"] = count', mesh_native_source)
        self.assertIn('item["source_vertex_offsets_stride"] = stride', mesh_native_source)
        self.assertEqual(1, mesh_native_source.count('item["source_vertex_offsets_binary"] = _write_int_binary_payload'))
        self.assertIn("_put_source_vertex_offsets_payload(item, prefix", store_item_body)
        self.assertIn('"source_vertex_map_start"', native_core_source)
        self.assertIn('"source_vertex_map_count"', native_core_source)
        self.assertIn("std::vector<int> source_vertex_offsets_from_item(", native_core_source)
        self.assertIn('"source_vertex_offsets_start"', native_core_source)
        self.assertIn('"source_vertex_offsets_count"', native_core_source)
        self.assertIn('"source_vertex_offsets_stride"', native_core_source)
        self.assertIn("source_vertex_offsets_from_item(item)", native_core_source)
        self.assertIn('item["sparse_output"] = True', mesh_native_source)
        self.assertIn("def _get_native_mesh_core_service(", mesh_native_source)
        self.assertIn("CDMW_DISABLE_NATIVE_MESH_CORE_SERVICE", mesh_native_source)
        self.assertIn("def snapshot_native_mesh_submeshes(", mesh_native_source)
        self.assertIn("def restore_native_mesh_submesh_snapshot(", mesh_native_source)
        self.assertIn("def dispose_native_mesh_submesh_snapshot(", mesh_native_source)
        self.assertIn("def _restore_native_submesh_snapshot_handle_sessions(", mesh_native_source)
        self.assertIn("def _export_native_submesh_snapshot_handle(", mesh_native_source)
        self.assertIn('"snapshot-submeshes-json"', mesh_native_source)
        self.assertIn('"operation": "restore_snapshot"', mesh_native_source)
        self.assertIn('"operation": "export_snapshot"', mesh_native_source)
        self.assertIn('"operation": "clear_snapshot"', mesh_native_source)
        self.assertIn('"snapshot_id": snapshot_id', mesh_native_source)
        restore_snapshot_start = mesh_native_source.index("def restore_native_mesh_submesh_snapshot(")
        restore_snapshot_body = mesh_native_source[
            restore_snapshot_start: mesh_native_source.index("def _native_submesh_snapshot_handle(", restore_snapshot_start)
        ]
        self.assertLess(
            restore_snapshot_body.index("_restore_native_submesh_snapshot_handle_sessions("),
            restore_snapshot_body.index("_export_native_submesh_snapshot_handle("),
        )
        self.assertIn("if restored_native_sessions:", restore_snapshot_body)
        self.assertIn("payloads_available = all(", restore_snapshot_body)
        self.assertIn("if not payloads_available:", restore_snapshot_body)
        self.assertLess(
            restore_snapshot_body.index("if not payloads_available:"),
            restore_snapshot_body.index("_export_native_submesh_snapshot_handle("),
        )
        self.assertIn("use_service = _native_mesh_core_service_enabled(stop_event=stop_event)", mesh_native_source)
        self.assertIn("_get_native_mesh_core_service(binary).run_job(", mesh_native_source)
        self.assertIn("run_process_with_cancellation(", mesh_native_source)
        self.assertIn("MeshSessionSubmesh", native_core_source)
        self.assertIn("g_mesh_sessions", native_core_source)
        self.assertIn("g_mesh_snapshots", native_core_source)
        self.assertIn('if (command == "mesh-session-json") return mesh_session_json_command(job_path, report_path);', native_core_source)
        self.assertIn("snapshot_submeshes_report_json", native_core_source)
        self.assertIn('operation == "restore_snapshot"', native_core_source)
        self.assertIn('operation == "export_snapshot"', native_core_source)
        self.assertIn('operation == "clear_snapshot"', native_core_source)
        snapshot_report_start = native_core_source.index("void mesh_snapshot_write_source_faces")
        snapshot_report_body = native_core_source[
            snapshot_report_start:native_core_source.index("std::string snapshot_submeshes_report_json", snapshot_report_start)
        ]
        self.assertIn("contiguous_int_range(session.source_face_indices, start)", snapshot_report_body)
        self.assertLess(
            snapshot_report_body.index("contiguous_int_range(session.source_face_indices, start)"),
            snapshot_report_body.index("write_int_binary_file(path, session.source_face_indices)"),
        )
        self.assertIn('out << ",\\"source_face_start\\":" << start', snapshot_report_body)
        self.assertIn("contiguous_int_range(session.source_vertex_map, start)", snapshot_report_body)
        self.assertLess(
            snapshot_report_body.index("contiguous_int_range(session.source_vertex_map, start)"),
            snapshot_report_body.index("write_int_binary_file(map_path, session.source_vertex_map)"),
        )
        self.assertIn("contiguous_int_stride_range(session.source_vertex_offsets", snapshot_report_body)
        self.assertLess(
            snapshot_report_body.index("contiguous_int_stride_range(session.source_vertex_offsets"),
            snapshot_report_body.index("write_int_binary_file(offsets_path, session.source_vertex_offsets)"),
        )
        snapshot_item_start = mesh_native_source.index("def _native_submesh_snapshot_item(")
        snapshot_item_body = mesh_native_source[
            snapshot_item_start:mesh_native_source.index("def _copy_snapshot_descriptor(", snapshot_item_start)
        ]
        self.assertIn('_copy_snapshot_i32_range(result, item, "source_face_start", "source_face_count"', snapshot_item_body)
        self.assertIn('_copy_snapshot_i32_range(result, item, "source_vertex_map_start", "source_vertex_map_count"', snapshot_item_body)
        self.assertIn("_copy_snapshot_i32_stride_range(result, item, expected_count=vertex_count)", snapshot_item_body)
        self.assertIn("def _i32_stride_range_report_values(", mesh_native_source)
        session_item_start = mesh_native_source.index("def _mesh_session_item_from_native_snapshot(")
        session_item_body = mesh_native_source[
            session_item_start:mesh_native_source.index("def apply_native_mesh_selection(", session_item_start)
        ]
        self.assertIn('"source_face_start"', session_item_body)
        self.assertIn('"source_face_count"', session_item_body)
        self.assertIn('"source_vertex_map_start"', session_item_body)
        self.assertIn('"source_vertex_map_count"', session_item_body)
        self.assertIn('"source_vertex_offsets_start"', session_item_body)
        self.assertIn('"source_vertex_offsets_stride"', session_item_body)
        self.assertIn("snapshot_submeshes_json_command", native_core_source)
        self.assertIn('if (command == "snapshot-submeshes-json") return snapshot_submeshes_json_command(job_path, report_path);', native_core_source)
        self.assertIn("mesh_vertices_from_item(item)", native_core_source)
        self.assertIn("selected_indices_from_binary_or_json", native_core_source)
        self.assertIn("selected_edges_from_binary_or_json", native_core_source)
        self.assertIn("int run_service()", native_core_source)
        self.assertIn('"--service"', native_core_source)
        self.assertIn("mesh_core_json_command(command, job_path, report_path)", native_core_source)
        native_transform_start = mesh_native_source.index("def apply_native_mesh_transform(")
        native_transform_body = mesh_native_source[
            native_transform_start: mesh_native_source.index("def apply_native_mesh_selection(", native_transform_start)
        ]
        self.assertIn('item["vertices_binary"] = _write_vec3_binary_payload', native_transform_body)
        self.assertNotIn('item["vertices"] = [_vec3_json(vertex) for vertex in submesh.vertices]', native_transform_body)
        self.assertIn("stop_event: threading.Event | None = None", native_transform_body)
        self.assertIn("stop_event=stop_event", native_transform_body)
        self.assertIn("**_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds)", native_transform_body)
        edit_ops_source = _read("cdmw/modding/mesh_edit_ops.py")
        transform_op_start = edit_ops_source.index("def _transform(")
        transform_op_body = edit_ops_source[transform_op_start: edit_ops_source.index("def _mirror_pairs_for_submesh", transform_op_start)]
        self.assertIn("class NativeLiveHistoryUnavailable", edit_ops_source)
        self.assertIn("apply_native_mesh_transform_binary_selection", edit_ops_source)
        self.assertIn("native_binary_vertices = (", transform_op_body)
        self.assertIn("native_changed = apply_native_mesh_transform_binary_selection(", transform_op_body)
        self.assertIn("native_selected_vertices_binary_by_submesh", transform_op_body)
        self.assertIn("if native_binary_vertices:", transform_op_body)
        self.assertLess(
            transform_op_body.index("native_changed = apply_native_mesh_transform_binary_selection("),
            transform_op_body.index("native_changed = apply_native_mesh_transform_selection("),
        )
        self.assertIn("apply_native_mesh_transform_selection", edit_ops_source)
        self.assertIn("native_changed = apply_native_mesh_transform_selection(", transform_op_body)
        self.assertIn("history_delta=history_delta", transform_op_body)
        self.assertIn("**_native_kwargs(params)", transform_op_body)
        self.assertIn("raise NativeLiveHistoryUnavailable", transform_op_body)
        self.assertLess(
            transform_op_body.index("native_changed = apply_native_mesh_transform_selection("),
            transform_op_body.index("vertices_by_submesh = _selected_vertices(mesh, selection, fallback_all=False)"),
        )
        self.assertLess(
            transform_op_body.index("python_expansion_domains and not _allow_python_mesh_edit_fallback("),
            transform_op_body.index("vertices_by_submesh = _selected_vertices(mesh, selection, fallback_all=False)"),
        )
        self.assertIn("pivot_vec = _vec3(pivot) if pivot is not None else None", transform_op_body)
        self.assertLess(
            transform_op_body.index("native_changed = apply_native_mesh_transform("),
            transform_op_body.index("pivot_vec = _selection_center(mesh, vertices_by_submesh) if pivot_vec is None else pivot_vec"),
        )
        brush_op_start = edit_ops_source.index("def _brush(")
        brush_op_body = edit_ops_source[brush_op_start: edit_ops_source.index("def _delete(", brush_op_start)]
        self.assertIn("apply_native_mesh_brush_binary_selection", edit_ops_source)
        self.assertIn("native_binary_vertices = (", brush_op_body)
        self.assertIn("native_binary_selection = apply_native_mesh_brush_binary_selection(", brush_op_body)
        self.assertIn("native_selected_vertices_binary_by_submesh", brush_op_body)
        self.assertIn("native_vertex_weights_binary_by_submesh", brush_op_body)
        self.assertIn("if native_binary_vertices:", brush_op_body)
        self.assertIn("return _changed_from_vertices({})", brush_op_body)
        self.assertIn("apply_native_mesh_brush_selection", edit_ops_source)
        self.assertIn("native_changed = apply_native_mesh_brush_selection(", brush_op_body)
        self.assertIn("history_delta=history_delta", brush_op_body)
        self.assertIn("raise NativeLiveHistoryUnavailable", brush_op_body)
        self.assertLess(
            brush_op_body.index("native_binary_selection = apply_native_mesh_brush_binary_selection("),
            brush_op_body.index("native_changed = apply_native_mesh_brush_selection("),
        )
        self.assertLess(
            brush_op_body.index("native_changed = apply_native_mesh_brush_selection("),
            brush_op_body.index("selected = _selected_vertices(mesh, selection, fallback_all=False)"),
        )
        self.assertLess(
            brush_op_body.index("python_expansion_domains and not _allow_python_mesh_edit_fallback("),
            brush_op_body.index("selected = _selected_vertices(mesh, selection, fallback_all=False)"),
        )
        material_targets_start = edit_ops_source.index("def _material_target_submesh_indices(")
        material_targets_body = edit_ops_source[
            material_targets_start: edit_ops_source.index("def _material_assign_changes", material_targets_start)
        ]
        self.assertNotIn("valid_faces == set(range(len(submesh.faces)))", material_targets_body)
        self.assertIn("if len(valid_faces) == len(submesh.faces):", material_targets_body)
        material_probe_body = edit_ops_source[
            edit_ops_source.index("def _material_assign_changes("): edit_ops_source.index("def _material_signature(", material_targets_start)
        ]
        self.assertIn("from copy import copy", edit_ops_source)
        self.assertNotIn("clone_mesh_for_editing", edit_ops_source)
        self.assertIn("probe = copy(submesh)", material_probe_body)
        self.assertIn("probe = copy(target)", material_probe_body)
        self.assertNotIn("clone_mesh_for_editing(ParsedMesh(submeshes=", material_probe_body)
        self.assertIn("vertices_from_binary_or_json(item, \"vertices_binary\", \"vertices\")", native_core_source)
        self.assertIn("std::set<int> selected_vertices_from_edit_domains(", native_core_source)
        self.assertIn("selected = selected_vertices_from_edit_domains(item, vertex_count, faces)", native_core_source)
        self.assertIn("selected_vertices_from_edit_domains(item, result.vertices.size(), faces)", native_core_source)
        self.assertIn("def _selection_domain_submesh_items(", mesh_native_source)
        self.assertIn("def _iter_valid_submesh_indices(", mesh_native_source)
        self.assertIn("def _sorted_unique_valid_submesh_indices(", mesh_native_source)
        self.assertIn("for index in _iter_valid_submesh_indices(mesh, submesh_indices)", mesh_native_source)
        self.assertIn("target_indices = _sorted_unique_valid_submesh_indices(mesh, submesh_indices, all_when_none=True)", mesh_native_source)
        selection_domain_start = mesh_native_source.index("def _selection_domain_submesh_items(")
        selection_domain_body = mesh_native_source[
            selection_domain_start: mesh_native_source.index("def apply_native_mesh_transform(", selection_domain_start)
        ]
        self.assertIn("for raw in source_indices or ()", selection_domain_body)
        self.assertIn("for raw in vertices_by_submesh.get(submesh_index, set()) or ()", selection_domain_body)
        self.assertIn("for raw_edge in edges_by_submesh.get(submesh_index, set()) or ()", selection_domain_body)
        self.assertIn("for raw in faces_by_submesh.get(submesh_index, set()) or ()", selection_domain_body)
        self.assertNotIn("tuple(source_indices or ())", selection_domain_body)
        self.assertNotIn("tuple(vertices_by_submesh.get(submesh_index", selection_domain_body)
        self.assertNotIn("tuple(edges_by_submesh.get(submesh_index", selection_domain_body)
        self.assertNotIn("tuple(faces_by_submesh.get(submesh_index", selection_domain_body)
        self.assertIn("stop_event: threading.Event | None = None", selection_domain_body)
        self.assertIn("stop_event=stop_event", selection_domain_body)
        self.assertIn("def apply_native_mesh_transform_binary_selection(", mesh_native_source)
        self.assertIn("def apply_native_mesh_transform_selection(", mesh_native_source)
        native_transform_selection_start = mesh_native_source.index("def apply_native_mesh_transform_selection(")
        native_transform_selection_body = mesh_native_source[
            native_transform_selection_start: mesh_native_source.index("def apply_native_mesh_transform_binary_selection(", native_transform_selection_start)
        ]
        self.assertIn("stop_event: threading.Event | None = None", native_transform_selection_body)
        self.assertIn("stop_event=stop_event", native_transform_selection_body)
        self.assertIn("**_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds)", native_transform_selection_body)
        native_binary_transform_start = mesh_native_source.index("def apply_native_mesh_transform_binary_selection(")
        native_binary_transform_body = mesh_native_source[
            native_binary_transform_start: mesh_native_source.index("def apply_native_mesh_selection(", native_binary_transform_start)
        ]
        self.assertIn("selected_range = _native_i32_range_descriptor(raw_descriptor", native_binary_transform_body)
        self.assertIn('item["selected_vertices_binary"] = selected_descriptor', native_binary_transform_body)
        self.assertIn('item["selected_vertex_start"] = selected_range[0]', native_binary_transform_body)
        self.assertIn('item["selected_vertex_count"] = selected_range[1]', native_binary_transform_body)
        self.assertIn('"session_id": session_id', native_binary_transform_body)
        self.assertIn("stop_event=stop_event", native_binary_transform_body)
        self.assertIn("**_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds)", native_binary_transform_body)
        self.assertIn("def apply_native_mesh_brush_binary_selection(", mesh_native_source)
        self.assertIn("def apply_native_mesh_brush_selection(", mesh_native_source)
        native_binary_brush_start = mesh_native_source.index("def apply_native_mesh_brush_binary_selection(")
        native_binary_brush_body = mesh_native_source[
            native_binary_brush_start: mesh_native_source.index("def apply_native_mesh_brush_selection(", native_binary_brush_start)
        ]
        self.assertIn("selected_range = _native_i32_range_descriptor(raw_descriptor", native_binary_brush_body)
        self.assertIn('item["selected_vertices_binary"] = selected_descriptor', native_binary_brush_body)
        self.assertIn('item["selected_vertex_start"] = selected_range[0]', native_binary_brush_body)
        self.assertIn('item["selected_vertex_count"] = selected_range[1]', native_binary_brush_body)
        self.assertIn('edit_payload["vertex_weight_indices_binary"] = submeshes[0]["selected_vertices_binary"]', native_binary_brush_body)
        self.assertIn('edit_payload["vertex_weights_binary"] = weight_descriptors[submesh_index]', native_binary_brush_body)
        self.assertIn("stop_event=stop_event", native_binary_brush_body)
        self.assertIn("**_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds)", native_binary_brush_body)
        self.assertNotIn("if binary is None or stop_event is not None:", native_binary_brush_body)
        native_brush_selection_start = mesh_native_source.index("def apply_native_mesh_brush_selection(")
        native_brush_selection_body = mesh_native_source[
            native_brush_selection_start: mesh_native_source.index("def apply_native_mesh_delete(", native_brush_selection_start)
        ]
        self.assertIn("stop_event: threading.Event | None = None", native_brush_selection_body)
        self.assertIn("stop_event=stop_event", native_brush_selection_body)
        self.assertIn("**_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds)", native_brush_selection_body)
        self.assertNotIn("if binary is None or stop_event is not None:", native_brush_selection_body)
        self.assertIn("def _vertex_weights_binary_payloads(", mesh_native_source)
        self.assertIn('"vertex_weight_indices_binary"', mesh_native_source)
        self.assertIn('"vertex_weights_binary"', mesh_native_source)
        self.assertIn("std::map<int, double> vertex_weights_from_edit(", native_core_source)
        self.assertIn("double_vector_from_f32_or_f64_binary", native_core_source)
        self.assertIn('edit.get("vertex_weight_indices_binary")', native_core_source)
        self.assertIn('edit.get("vertex_weights_binary")', native_core_source)
        delete_op_start = edit_ops_source.index("def _delete(")
        delete_op_body = edit_ops_source[delete_op_start: edit_ops_source.index("def _dissolve(", delete_op_start)]
        self.assertIn("native_binary_vertices = (", delete_op_body)
        self.assertIn("native_selected_vertices_binary_by_submesh", delete_op_body)
        self.assertIn("selected_vertices_binary_by_submesh=native_binary_vertices", delete_op_body)
        self.assertLess(
            delete_op_body.index("native_binary_vertices = ("),
            delete_op_body.index("native_affected = apply_native_mesh_delete("),
        )
        self.assertIn('item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")', native_transform_body)
        self.assertIn('"changed_vertices_output_path": _native_preview_delta_output_path("_changed_vertices.bin")', mesh_native_source)
        self.assertIn('"selected_edges_binary"', mesh_native_source)
        self.assertIn('"selected_faces_binary"', mesh_native_source)
        self.assertIn('"selected_all_vertices"', mesh_native_source)
        native_brush_start = mesh_native_source.index("def apply_native_mesh_brush(")
        native_brush_body = mesh_native_source[
            native_brush_start: mesh_native_source.index("def apply_native_mesh_brush_selection(", native_brush_start)
        ]
        self.assertLess(
            native_brush_body.index("_ensure_native_mesh_session_submesh("),
            native_brush_body.index("faces = _face_json("),
        )
        transform_start = native_core_source.index("std::vector<SubmeshTransformResult> run_transform")
        transform_body = native_core_source[transform_start: native_core_source.index("std::vector<SubmeshCleanupResult> run_cleanup", transform_start)]
        self.assertIn("result.vertices = mesh_vertices_from_item(item)", transform_body)
        self.assertNotIn('result.vertices = vertices_from_json(item.get("vertices"))', transform_body)
        self.assertIn("mesh_faces_from_item(item, result.vertices.size())", native_core_source)
        topology_body = _read("cdmw/modding/mesh_native_topology_payloads.py")
        topology_geometry_start = topology_body.index("def _put_topology_geometry(")
        topology_geometry_body = topology_body[
            topology_geometry_start:topology_body.index("def _put_topology_selection(", topology_geometry_start)
        ]
        self.assertIn("_ensure_native_mesh_session_submesh(", topology_body)
        self.assertIn("preserve_normals: bool = False", topology_body)
        self.assertIn("selected_vertices_binary_by_submesh", topology_body)
        self.assertIn("selected_vertices_binary = _native_i32_descriptor(raw_binary)", topology_body)
        self.assertIn('item["selected_vertices_binary"] = selected_vertices_binary', topology_body)
        self.assertIn('item["session_id"] = session_id', topology_body)
        self.assertIn('"selected_faces_binary"', topology_body)
        self.assertIn('"selected_vertices_binary"', topology_body)
        self.assertIn('"selected_edges_binary"', topology_body)
        self.assertIn('item["vertices_output_path"] = _native_preview_delta_output_path("_topology_vertices.bin")', topology_body)
        self.assertIn('item["faces_output_path"] = _native_preview_delta_output_path("_topology_faces.bin")', topology_body)
        self.assertIn('("normals", "_topology_normals.bin", preserve_normals)', topology_body)
        self.assertIn('("uvs", "_topology_uvs.bin", True)', topology_body)
        self.assertIn('("tangents", "_topology_tangents.bin", True)', topology_body)
        self.assertIn('("tangent_signs", "_topology_tangent_signs.bin", True)', topology_body)
        self.assertIn('("source_vertex_map", "_topology_source_vertex_map.bin", True)', topology_body)
        self.assertIn('("source_vertex_offsets", "_topology_source_vertex_offsets.bin", True)', topology_body)
        self.assertIn('for name in ("counts", "indices", "weights"):', topology_body)
        self.assertIn('item[f"bone_{name}_output_path"] = _native_preview_delta_output_path(', topology_body)
        self.assertIn('item["suppress_vertex_remap_report"] = True', topology_body)
        self.assertNotIn('item["copy_vertex_indices_output_path"] = _native_preview_delta_output_path("_topology_copy_vertex_indices.bin")', topology_body)
        self.assertNotIn('item["vertex_blend_indices_output_path"] = _native_preview_delta_output_path("_topology_vertex_blend_indices.bin")', topology_body)
        self.assertNotIn('item["vertex_blend_factors_output_path"] = _native_preview_delta_output_path("_topology_vertex_blend_factors.bin")', topology_body)
        self.assertNotIn('item["index_map_output_path"] = _native_preview_delta_output_path("_topology_index_map.bin")', topology_body)
        self.assertIn("face_count = len(submesh.faces or ())", topology_body)
        self.assertIn("faces, source_face_indices = _face_json_with_source_indices(", topology_body)
        self.assertIn("def _is_identity_i32_sequence(", mesh_native_source)
        self.assertIn("def _put_source_face_indices_json_payload(", mesh_native_source)
        self.assertIn("if not _is_identity_i32_sequence(source_face_indices):", topology_body)
        self.assertIn("source_face_indices, face_count = geometry", topology_body)
        self.assertIn("_put_topology_selection(", topology_body)
        self.assertNotIn("list(range(len(source_face_indices)))", topology_body)
        self.assertNotIn("list(range(len(selection_source_face_indices)))", topology_body)
        self.assertLess(
            topology_geometry_body.index("_ensure_native_mesh_session_submesh("),
            topology_geometry_body.index("faces, source_face_indices = _face_json_with_source_indices("),
        )
        compact_start = mesh_native_source.index("def apply_native_mesh_compact_orphans(")
        compact_body = mesh_native_source[compact_start: mesh_native_source.index("def apply_native_mesh_split(", compact_start)]
        compact_payload_body = mesh_native_source[compact_start: mesh_native_source.index("def apply_native_mesh_fix_winding(", compact_start)]
        self.assertLess(
            compact_body.index("_ensure_native_mesh_session_submesh("),
            compact_body.index("faces = _face_json("),
        )
        self.assertIn('item["suppress_vertex_remap_report"] = True', compact_payload_body)
        self.assertNotIn('item["copy_vertex_indices_output_path"] = _native_preview_delta_output_path("_topology_copy_vertex_indices.bin")', compact_payload_body)
        self.assertNotIn('item["vertex_blend_indices_output_path"] = _native_preview_delta_output_path("_topology_vertex_blend_indices.bin")', compact_payload_body)
        self.assertNotIn('item["vertex_blend_factors_output_path"] = _native_preview_delta_output_path("_topology_vertex_blend_factors.bin")', compact_payload_body)
        self.assertNotIn('item["index_map_output_path"] = _native_preview_delta_output_path("_topology_index_map.bin")', compact_payload_body)
        triangulate_native_start = mesh_native_source.index("def apply_native_mesh_triangulate_display(")
        triangulate_native_body = mesh_native_source[
            triangulate_native_start:mesh_native_source.index("def _append_native_duplicate_report_submeshes(", triangulate_native_start)
        ]
        self.assertIn('"suppress_vertex_remap_report": True', triangulate_native_body)
        self.assertNotIn('"copy_vertex_indices_output_path": _native_preview_delta_output_path("_topology_copy_vertex_indices.bin")', triangulate_native_body)
        self.assertNotIn('"vertex_blend_indices_output_path": _native_preview_delta_output_path("_topology_vertex_blend_indices.bin")', triangulate_native_body)
        self.assertNotIn('"vertex_blend_factors_output_path": _native_preview_delta_output_path("_topology_vertex_blend_factors.bin")', triangulate_native_body)
        self.assertNotIn('"index_map_output_path": _native_preview_delta_output_path("_topology_index_map.bin")', triangulate_native_body)
        self.assertIn("_write_edge_binary_payload", mesh_native_source)
        self.assertIn("sidecar_root: Path | None = None", mesh_native_source)
        self.assertIn("\"faces_binary\": _write_face_binary_payload", mesh_native_source)
        self.assertIn("sidecar_root=sidecar_root", mesh_native_source)
        self.assertIn("mesh_vertices_from_item(item)", native_core_source)
        self.assertNotIn("const std::vector<Vec3> vertices = vertices_from_binary_or_json(item, \"vertices_binary\", \"vertices\")", native_core_source)
        self.assertIn("raw_changed_positions = item.get(\"changed_positions\")", mesh_native_source)
        self.assertIn('raw_changed_binary = item.get("changed_vertices_binary")', mesh_native_source)
        self.assertIn("def _changed_vertices_from_report_item(", mesh_native_source)
        changed_report_start = mesh_native_source.index("def _changed_vertices_from_report_item(")
        changed_report_body = mesh_native_source[
            changed_report_start:mesh_native_source.index("def _write_vec2_binary_payload", changed_report_start)
        ]
        self.assertNotIn("return list(range(start, start + count))", changed_report_body)
        self.assertIn("return range(start, start + count)", changed_report_body)
        self.assertIn("return range(start, start)", changed_report_body)
        self.assertIn("changed_positions_binary = item.get(\"changed_positions_binary\")", mesh_native_source)
        self.assertIn("def _read_vec3_binary_report_payload(", mesh_native_source)
        self.assertIn('\\"finite_checked\\":true', native_core_source)
        self.assertIn('finite_checked=bool(value.get("finite_checked"))', mesh_native_source)
        self.assertIn('if bool(value.get("finite_checked")):', mesh_native_source)
        self.assertIn("\"changed_positions_output_path\"", mesh_native_source)
        self.assertIn("NATIVE_MESH_HISTORY_VERTEX_DELTA_ATTR", mesh_native_source)
        self.assertIn('"before_positions_output_path"', mesh_native_source)
        self.assertIn('raw_before_positions_binary = item.get("before_positions_binary")', mesh_native_source)
        self.assertIn("def _native_history_vertex_delta(", mesh_native_source)
        history_delta_start = mesh_native_source.index("def _native_history_vertex_delta(")
        history_delta_body = mesh_native_source[
            history_delta_start: mesh_native_source.index("def native_mesh_history_delta_positions(", history_delta_start)
        ]
        self.assertIn('"before_positions_binary": descriptor', history_delta_body)
        self.assertIn('"native_sparse_snapshot_id": native_sparse_snapshot_id', history_delta_body)
        self.assertIn("def _native_history_vertex_payload(", mesh_native_source)
        self.assertIn('"vertex_index_start"', mesh_native_source)
        self.assertIn('"vertex_index_count"', mesh_native_source)
        self.assertIn("def _vertex_indices_from_history_descriptor(", mesh_native_source)
        self.assertIn("start_key=\"vertex_index_start\"", mesh_native_source)
        self.assertIn("count_key=\"vertex_index_count\"", mesh_native_source)
        self.assertNotIn("_read_vec3_binary_report_payload(", history_delta_body)
        self.assertIn("def native_mesh_history_delta_positions(", mesh_native_source)
        self.assertIn("changed_positions_binary", native_core_source)
        self.assertIn("std::vector<Vec3> before_positions;", native_core_source)
        self.assertIn("std::string sparse_snapshot_id;", native_core_source)
        self.assertIn('result.before_positions_path = string_or(item.get("before_positions_output_path"), "")', native_core_source)
        self.assertIn("write_vec3_binary_file(result.before_positions_path, result.before_positions)", native_core_source)
        self.assertIn("store_sparse_vertex_snapshot_values(", native_core_source)
        self.assertIn("before_positions_binary", native_core_source)
        self.assertIn("native_sparse_snapshot_id", native_core_source)
        self.assertIn("std::string changed_vertices_path;", native_core_source)
        self.assertIn('result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "")', native_core_source)
        self.assertIn("write_int_binary_file(changed_vertices_path, changed_vertices)", native_core_source)
        self.assertIn("changed_vertices_binary", native_core_source)
        self.assertIn("write_vec3_binary_file(result.changed_positions_path, result.changed_positions)", native_core_source)
        self.assertIn("result.changed_positions.reserve(result.changed_vertices.size())", native_core_source)
        self.assertIn("if (result.sparse && !result.topology_changed)", native_core_source)
        self.assertIn('result.vertices_path = string_or(item.get("vertices_output_path"), "")', native_core_source)
        self.assertIn('result.faces_path = string_or(item.get("faces_output_path"), "")', native_core_source)
        self.assertIn('result.normals_path = string_or(item.get("normals_output_path"), "")', native_core_source)
        self.assertIn('result.uvs_path = string_or(item.get("uvs_output_path"), "")', native_core_source)
        self.assertIn('result.tangents_path = string_or(item.get("tangents_output_path"), "")', native_core_source)
        self.assertIn('result.tangent_signs_path = string_or(item.get("tangent_signs_output_path"), "")', native_core_source)
        self.assertIn('result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "")', native_core_source)
        self.assertIn('result.bone_indices_path = string_or(item.get("bone_indices_output_path"), "")', native_core_source)
        self.assertIn('result.bone_weights_path = string_or(item.get("bone_weights_output_path"), "")', native_core_source)
        self.assertIn('result.source_vertex_map_path = string_or(item.get("source_vertex_map_output_path"), "")', native_core_source)
        self.assertIn('result.source_vertex_offsets_path = string_or(item.get("source_vertex_offsets_output_path"), "")', native_core_source)
        self.assertIn("write_vec3_binary_file(result.vertices_path, result.vertices)", native_core_source)
        self.assertIn("write_faces_binary_file(result.faces_path, result.faces)", native_core_source)
        self.assertIn("result.normals = vec3_values_for_result(mesh_normals_from_item(item), result)", native_core_source)
        self.assertIn("write_vec3_binary_file(result.normals_path, result.normals)", native_core_source)
        self.assertIn("write_vec2_binary_file(result.uvs_path, result.preview_uvs)", native_core_source)
        self.assertIn("write_vec2_binary_descriptor(out, result.uvs_path, result.preview_uvs.size())", native_core_source)
        self.assertIn("write_vec3_binary_file(result.tangents_path, result.tangents)", native_core_source)
        self.assertIn("write_double_binary_file(result.tangent_signs_path, result.tangent_signs)", native_core_source)
        self.assertIn("vec3_values_for_result(mesh_tangents_from_item(item), result)", native_core_source)
        self.assertIn("double_values_for_result(mesh_tangent_signs_from_item(item), result)", native_core_source)
        self.assertIn("bone_values_for_result(mesh_bones_from_item(item), result)", native_core_source)
        self.assertIn("write_int_binary_file(result.bone_counts_path, bone_counts)", native_core_source)
        self.assertIn("write_int_binary_file(result.bone_indices_path, flat_bone_indices)", native_core_source)
        self.assertIn("write_double_binary_file(result.bone_weights_path, flat_bone_weights)", native_core_source)
        edit_report_start = native_core_source.index("void write_mesh_edit_result_channels(")
        edit_report_body = native_core_source[
            edit_report_start:native_core_source.index("void write_mesh_edit_result_remap(", edit_report_start)
        ]
        self.assertIn("contiguous_int_range(result.source_vertex_map, source_vertex_map_start)", edit_report_body)
        self.assertLess(
            edit_report_body.index("contiguous_int_range(result.source_vertex_map, source_vertex_map_start)"),
            edit_report_body.index("write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map)"),
        )
        self.assertIn("contiguous_int_stride_range(result.source_vertex_offsets", edit_report_body)
        self.assertLess(
            edit_report_body.index("contiguous_int_stride_range(result.source_vertex_offsets"),
            edit_report_body.index("write_int_binary_file(result.source_vertex_offsets_path, result.source_vertex_offsets)"),
        )
        self.assertIn('result.copy_vertex_indices_path = string_or(item.get("copy_vertex_indices_output_path"), "")', native_core_source)
        self.assertIn('result.vertex_blend_indices_path = string_or(item.get("vertex_blend_indices_output_path"), "")', native_core_source)
        self.assertIn('result.vertex_blend_factors_path = string_or(item.get("vertex_blend_factors_output_path"), "")', native_core_source)
        self.assertIn('result.index_map_path = string_or(item.get("index_map_output_path"), "")', native_core_source)
        native_edit_payload_start = service_payload_source.index("def _native_editor_edit_payload(")
        native_edit_payload_body = service_payload_source[
            native_edit_payload_start:service_payload_source.index("def _native_editor_material_extra_attrs(", native_edit_payload_start)
        ]
        self.assertIn("if action in MESH_TOPOLOGY_ACTIONS:", native_edit_payload_body)
        self.assertIn('payload["suppress_vertex_remap_report"] = True', native_edit_payload_body)
        self.assertIn("_NATIVE_EDITOR_SCREEN_PAYLOAD_KEYS", service_payload_source)
        self.assertIn("key_text in _NATIVE_EDITOR_SCREEN_PAYLOAD_KEYS", native_edit_payload_body)
        self.assertIn("payload[key_text] = _native_editor_screen_payload(json_value)", native_edit_payload_body)
        self.assertIn('item.get("suppress_vertex_remap_report")', native_core_source)
        self.assertIn('bool_or(edit.get("suppress_vertex_remap_report"), false)', native_core_source)
        remap_start = native_core_source.index("void write_mesh_edit_result_remap(")
        remap_body = native_core_source[
            remap_start:native_core_source.index("void write_mesh_edit_result_preview(", remap_start)
        ]
        self.assertIn('out << ",\\"vertex_remap_report_suppressed\\":true";', native_core_source)
        self.assertIn("if (!result.suppress_vertex_remap_report)", remap_body)
        self.assertIn("write_int_binary_file(result.copy_vertex_indices_path, result.copy_vertex_indices)", native_core_source)
        self.assertIn("write_int_binary_file(result.vertex_blend_indices_path, flatten_vertex_blend_indices(result.vertex_blends))", native_core_source)
        self.assertIn("write_double_binary_file(result.vertex_blend_factors_path, flatten_vertex_blend_factors(result.vertex_blends))", native_core_source)
        self.assertIn("write_int_binary_file(result.index_map_path, result.index_map)", native_core_source)
        self.assertIn("source_vertex_values_for_result(", native_core_source)
        source_values_start = native_core_source.index("std::vector<int> source_vertex_values_for_result(")
        source_values_body = native_core_source[
            source_values_start:native_core_source.index("std::vector<SubmeshMeshEditResult> run_mesh_edit", source_values_start)
        ]
        self.assertIn('"source_vertex_map_start"', source_values_body)
        self.assertIn('"source_vertex_map_count"', source_values_body)
        self.assertIn("source_vertex_offsets_from_item(item)", source_values_body)
        self.assertIn('raw_vertices_binary = item.get("vertices_binary")', mesh_native_source)
        self.assertIn('raw_faces_binary = item.get("faces_binary")', mesh_native_source)
        self.assertIn('raw_normals_binary = item.get("normals_binary")', mesh_native_source)
        self.assertIn('raw_uvs_binary = item.get("uvs_binary")', mesh_native_source)
        self.assertIn('raw_tangents_binary = item.get("tangents_binary")', mesh_native_source)
        self.assertIn('raw_tangent_signs_binary = item.get("tangent_signs_binary")', mesh_native_source)
        self.assertIn('raw_bone_counts_binary = item.get("bone_counts_binary")', mesh_native_source)
        self.assertIn('raw_bone_indices_binary = item.get("bone_indices_binary")', mesh_native_source)
        self.assertIn('raw_bone_weights_binary = item.get("bone_weights_binary")', mesh_native_source)
        self.assertIn("def _source_vertex_map_report_values(", mesh_native_source)
        self.assertIn("def _source_vertex_offsets_report_values(", mesh_native_source)
        self.assertIn("_source_vertex_map_report_values(item, vertex_count)", mesh_native_source)
        self.assertIn("_source_vertex_offsets_report_values(item, vertex_count)", mesh_native_source)
        self.assertIn("def _copy_vertex_indices_from_report_item(", mesh_native_source)
        self.assertIn("def _vertex_blends_from_report_item(", mesh_native_source)
        self.assertIn('item.get("copy_vertex_indices_binary")', mesh_native_source)
        self.assertIn('item.get("vertex_blend_indices_binary")', mesh_native_source)
        self.assertIn('item.get("vertex_blend_factors_binary")', mesh_native_source)
        self.assertIn("def _read_vec2_binary_report_payload(", mesh_native_source)
        self.assertIn("def _read_i32_components_binary_report_payload(", mesh_native_source)
        self.assertIn("def _read_f64_binary_report_payload(", mesh_native_source)
        self.assertIn("def _read_bone_binary_report_payloads(", mesh_native_source)
        self.assertIn("def _read_i32_binary_report_payload(", mesh_native_source)
        self.assertIn("skip_topology_normals: bool = False", mesh_native_source)
        self.assertIn("skip_normals=skip_topology_normals or channels.normals is not None", mesh_native_source)
        self.assertIn("skip_normals: bool = False", mesh_native_source)
        self.assertGreaterEqual(mesh_native_source.count("skip_topology_normals=recompute_normals"), 4)
        self.assertGreaterEqual(mesh_native_source.count("preserve_normals=not recompute_normals"), 3)
        self.assertIn("skip_uvs=channels.uvs is not None", mesh_native_source)
        self.assertIn("skip_tangents=channels.tangents is not None", mesh_native_source)
        self.assertIn("skip_tangent_signs=channels.tangent_signs is not None", mesh_native_source)
        self.assertIn("skip_bones=channels.bones is not None", mesh_native_source)
        self.assertIn("has_source_map = bool(channels.source_vertex_map)", mesh_native_source)
        self.assertIn("has_source_offsets = bool(channels.source_vertex_offsets)", mesh_native_source)
        self.assertIn("skip_source_vertex_map=has_source_map", mesh_native_source)
        self.assertIn("skip_source_vertex_offsets=has_source_offsets", mesh_native_source)
        self.assertIn("_native_preview_delta_output_path(\"_positions.bin\")", mesh_native_source)
        self.assertIn("write_preview_binary_descriptor", native_core_source)
        self.assertIn("\"positions_binary\"", native_core_source)
        self.assertIn("\"source_vertex_indices_binary\"", native_core_source)
        self.assertIn("write_int_binary_file(source_indices_path, source_indices)", native_core_source)
        apply_report_item_start = mesh_native_source.index("def _apply_mesh_edit_report_item(")
        apply_report_item_body = mesh_native_source[
            apply_report_item_start:mesh_native_source.index("def _apply_mesh_edit_report(", apply_report_item_start)
        ]
        apply_report_start = mesh_native_source.index("def _apply_mesh_edit_report(", apply_report_item_start)
        apply_report_body = mesh_native_source[
            apply_report_start: mesh_native_source.index("def _native_preview_triangle_group(", apply_report_start)
        ]
        self.assertNotIn("vertices != [_vec3(vertex) for vertex in submesh.vertices]", apply_report_item_body)
        self.assertIn('elif item.get("vertices") is not None or item.get("vertices_binary") is not None:', apply_report_item_body)
        self.assertIn("changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = {}", apply_report_body)
        self.assertIn("changed = _bounded_changed_vertices(state.changed, len(state.vertices))", apply_report_item_body)
        self.assertNotIn("changed = set(changed_ordered)", apply_report_item_body)
        sparse_writer_start = native_core_source.index("void write_sparse_preview_vertex_update_group(")
        sparse_binary_branch = native_core_source[
            native_core_source.index("if (!changed_positions_path.empty())", sparse_writer_start):
            native_core_source.index("return;", sparse_writer_start)
        ]
        self.assertNotIn('"source_vertex_indices":[', sparse_binary_branch)
        self.assertIn("write_preview_source_vertex_ids(", sparse_binary_branch)
        self.assertIn('sibling_binary_path(changed_positions_path, ".source_indices.bin")', sparse_binary_branch)
        self.assertIn("delete_after", native_core_source)
        d3d11_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        self.assertIn("json_f64_array_or_json_field", d3d11_source)
        self.assertIn("json_i32_array_or_json_field", d3d11_source)
        self.assertIn("json_i32_range_or_array_or_json_field", d3d11_source)
        self.assertIn("write_i32_range_or_descriptor_json", d3d11_source)
        self.assertIn('json_f64_array_or_json_field(group, "positions_binary", "positions", 3)', d3d11_source)
        self.assertIn('json_i32_array_or_json_field(group, "source_vertex_indices_binary", "source_vertex_indices")', d3d11_source)
        self.assertIn('"source_vertex_start",', d3d11_source)
        self.assertIn('"source_vertex_count"', d3d11_source)
        self.assertIn("self_test_i32_descriptor_reader", d3d11_source)
        self.assertIn('"selection_binary", "ok"', d3d11_source)
        self.assertIn('filename.rfind(L"cdmw_mesh_preview_delta_", 0) != 0', d3d11_source)
        self.assertIn("def apply_native_mesh_selection(", mesh_native_source)
        self.assertIn('"selection-json"', mesh_native_source)
        selection_start = mesh_native_source.index("def apply_native_mesh_selection(")
        selection_body = mesh_native_source[
            selection_start: mesh_native_source.index("def build_native_mesh_selection_groups(", selection_start)
        ]
        self.assertIn("_ensure_native_mesh_session_submesh(", selection_body)
        self.assertIn("for raw in source_indices or ()", selection_body)
        self.assertNotIn("tuple(source_indices or ())", selection_body)
        self.assertIn('item["session_id"] = session_id', selection_body)
        self.assertIn("face_count = len(submesh.faces or ())", selection_body)
        self.assertIn('item["vertex_count"] = vertex_count', selection_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', selection_body)
        self.assertIn("_put_i32_range_or_binary_payload(", selection_body)
        self.assertIn('start_key="selected_vertex_start"', selection_body)
        self.assertIn('binary_key="selected_vertices_binary"', selection_body)
        self.assertIn('item["selected_edges_binary"] = _write_edge_binary_payload', selection_body)
        self.assertIn('start_key="selected_face_start"', selection_body)
        self.assertIn('binary_key="selected_faces_binary"', selection_body)
        self.assertIn('item["selected_all_vertices"] = True', selection_body)
        self.assertIn('item["selected_vertices_output_path"] = _native_preview_delta_output_path("_selection_vertices.bin")', selection_body)
        self.assertIn("stop_event: threading.Event | None = None", selection_body)
        self.assertIn("stop_event=stop_event", selection_body)
        self.assertIn("**_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds)", selection_body)
        self.assertLess(
            selection_body.index("_ensure_native_mesh_session_submesh("),
            selection_body.index("faces = _face_json("),
        )
        self.assertNotIn('"vertices": [_vec3_json(vertex) for vertex in submesh.vertices]', selection_body)
        self.assertNotIn('"faces": faces', selection_body)
        self.assertNotIn('"selected_vertices": kept', selection_body)
        apply_selection_start = mesh_native_source.index("def _apply_selection_report(")
        apply_selection_body = mesh_native_source[
            apply_selection_start: mesh_native_source.index("def _apply_recalculate_normals_report(", apply_selection_start)
        ]
        self.assertIn('raw_selected_binary = item.get("selected_vertices_binary")', apply_selection_body)
        self.assertIn('start_key="selected_vertex_start"', apply_selection_body)
        self.assertIn('count_key="selected_vertex_count"', apply_selection_body)
        self.assertIn("_read_int_binary_report_payload(raw_selected_binary", apply_selection_body)
        self.assertIn("def select_native_mesh_uv_vertices(", mesh_native_source)
        self.assertIn('"uv-selection-json"', mesh_native_source)
        uv_selection_start = mesh_native_source.index("def select_native_mesh_uv_vertices(")
        uv_selection_body = mesh_native_source[
            uv_selection_start: mesh_native_source.index("def prune_native_mesh_selection(", uv_selection_start)
        ]
        self.assertIn("_ensure_native_mesh_session_submesh(", uv_selection_body)
        self.assertIn('item["session_id"] = session_id', uv_selection_body)
        self.assertIn('polygon = [_vec2_json(point) for point in points or ()]', uv_selection_body)
        self.assertIn('for submesh_index, submesh in enumerate(mesh.submeshes or ()):', uv_selection_body)
        self.assertIn('uvs = getattr(submesh, "uvs", ()) or ()', uv_selection_body)
        self.assertNotIn('tuple(points or ())', uv_selection_body)
        self.assertNotIn('enumerate(tuple(mesh.submeshes or ()))', uv_selection_body)
        self.assertNotIn('uvs = tuple(getattr(submesh, "uvs", ()) or ())', uv_selection_body)
        self.assertIn('item["uvs_binary"] = _write_vec2_binary_payload', uv_selection_body)
        self.assertLess(
            uv_selection_body.index("_ensure_native_mesh_session_submesh("),
            uv_selection_body.index('uvs = getattr(submesh, "uvs", ()) or ()'),
        )
        self.assertLess(
            uv_selection_body.index('item["session_id"] = session_id'),
            uv_selection_body.index('uvs = getattr(submesh, "uvs", ()) or ()'),
        )
        self.assertIn('"selected_vertices_output_path": _native_preview_delta_output_path("_uv_selected_vertices.bin")', uv_selection_body)
        self.assertIn('return _apply_selection_report(mesh, report)', uv_selection_body)
        self.assertNotIn('"uvs": [_vec2_json(uv) for uv in uvs]', uv_selection_body)
        self.assertIn("std::vector<SubmeshUvSelectionResult> run_uv_selection", native_core_source)
        self.assertIn("uv_point_in_polygon", native_core_source)
        self.assertIn("mesh_uvs_from_item(item)", native_core_source)
        uv_selection_report_start = native_core_source.index("std::string uv_selection_report_json(")
        uv_selection_report_body = native_core_source[
            uv_selection_report_start: native_core_source.index("std::string uv_summary_report_json", uv_selection_report_start)
        ]
        self.assertIn("contiguous_int_range(result.selected_vertices, selected_vertex_start)", uv_selection_report_body)
        self.assertLess(
            uv_selection_report_body.index("contiguous_int_range(result.selected_vertices, selected_vertex_start)"),
            uv_selection_report_body.index("write_int_binary_file(result.selected_vertices_path, result.selected_vertices)"),
        )
        self.assertIn('\\"selected_vertex_start\\"', uv_selection_report_body)
        self.assertIn('\\"selected_vertex_count\\"', uv_selection_report_body)
        self.assertIn('if (command == "uv-selection-json") return uv_selection_json_command(job_path, report_path);', native_core_source)
        self.assertIn("def summarize_native_mesh_uvs(", mesh_native_source)
        self.assertIn('"uv-summary-json"', mesh_native_source)
        uv_summary_start = mesh_native_source.index("def summarize_native_mesh_uvs(")
        uv_summary_body = mesh_native_source[
            uv_summary_start: mesh_native_source.index("def prune_native_mesh_selection(", uv_summary_start)
        ]
        self.assertIn('for raw_index in getattr(selection, "source_indices", ()) or ()', uv_summary_body)
        self.assertIn('for submesh_index, submesh in enumerate(mesh.submeshes or ()):', uv_summary_body)
        self.assertIn('uvs = getattr(submesh, "uvs", ()) or ()', uv_summary_body)
        self.assertNotIn('tuple(getattr(selection, "source_indices", ()) or ())', uv_summary_body)
        self.assertNotIn('enumerate(tuple(mesh.submeshes or ()))', uv_summary_body)
        self.assertNotIn('uvs = tuple(getattr(submesh, "uvs", ()) or ())', uv_summary_body)
        self.assertIn("_ensure_native_mesh_session_submesh(", uv_summary_body)
        self.assertIn('item["session_id"] = session_id', uv_summary_body)
        self.assertIn('raw_faces = getattr(submesh, "faces", ()) or ()', uv_summary_body)
        self.assertIn('item["uvs_binary"] = _write_vec2_binary_payload', uv_summary_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', uv_summary_body)
        self.assertLess(
            uv_summary_body.index("_ensure_native_mesh_session_submesh("),
            uv_summary_body.index('uvs = getattr(submesh, "uvs", ()) or ()'),
        )
        self.assertLess(
            uv_summary_body.index('item["session_id"] = session_id'),
            uv_summary_body.index('raw_faces = getattr(submesh, "faces", ()) or ()'),
        )
        self.assertIn("_put_source_face_indices_payload(item, prefix, source_face_indices)", uv_summary_body)
        self.assertIn('start_key="selected_vertex_start"', uv_summary_body)
        self.assertIn('binary_key="selected_vertices_binary"', uv_summary_body)
        self.assertIn('start_key="selected_face_start"', uv_summary_body)
        self.assertIn('binary_key="selected_faces_binary"', uv_summary_body)
        self.assertNotIn('item["source_face_indices_binary"] = _write_int_binary_payload', uv_summary_body)
        self.assertNotIn('item["selected_vertices_binary"] = _write_int_binary_payload', uv_summary_body)
        self.assertNotIn('item["selected_faces_binary"] = _write_int_binary_payload', uv_summary_body)
        self.assertNotIn('"uvs": [_vec2_json(uv) for uv in uvs]', uv_summary_body)
        self.assertIn("std::vector<UvIslandSummaryResult> run_uv_summary", native_core_source)
        self.assertIn("native_uv_edge_key", native_core_source)
        self.assertIn("mesh_source_face_indices_from_item(item, faces.size())", native_core_source)
        uv_summary_native_start = native_core_source.index("std::vector<UvIslandSummaryResult> run_uv_summary")
        uv_summary_native_body = native_core_source[
            uv_summary_native_start: native_core_source.index("std::vector<SubmeshMetadataResult> run_mesh_metadata", uv_summary_native_start)
        ]
        self.assertIn('"selected_face_start"', uv_summary_native_body)
        self.assertIn('"selected_face_count"', uv_summary_native_body)
        self.assertIn('if (command == "uv-summary-json") return uv_summary_json_command(job_path, report_path);', native_core_source)
        service_source = _read("cdmw/services/mesh_service.py")
        self.assertIn("select_native_mesh_uv_vertices", service_source)
        self.assertIn("summarize_native_mesh_uvs", service_source)
        workspace_summary_start = service_source.index("def workspace_summary(")
        workspace_summary_body = service_source[
            workspace_summary_start: service_source.index("def compare_summary(", workspace_summary_start)
        ]
        self.assertIn("summarize_native_mesh_editor_session(session.session_id)", workspace_summary_body)
        self.assertIn("_mesh_workspace_summary_from_native(", service_source)
        self.assertIn("native mesh editor workspace summary failed; Python mesh state is stale", workspace_summary_body)
        self.assertLess(
            workspace_summary_body.index("if session.native_editor_mesh_dirty:"),
            workspace_summary_body.index("_prune_selection_to_mesh(session.working_mesh, session.selection)"),
        )
        compare_summary_start = service_source.index("def compare_summary(")
        compare_summary_body = service_source[
            compare_summary_start: service_source.index("def uv_summary(", compare_summary_start)
        ]
        self.assertIn("if session.native_editor_mesh_dirty:", compare_summary_body)
        self.assertIn("native mesh editor compare summary unavailable; Python mesh state is stale", compare_summary_body)
        self.assertNotIn("_sync_native_editor_session_to_working_mesh(", compare_summary_body)
        service_uv_summary_start = service_source.index("def uv_summary(")
        service_uv_summary_body = service_source[
            service_uv_summary_start: service_source.index("def select_uv_region(", service_uv_summary_start)
        ]
        self.assertIn("if session.native_editor_mesh_dirty:", service_uv_summary_body)
        self.assertIn("native mesh editor UV summary unavailable; Python mesh state is stale", service_uv_summary_body)
        self.assertIn("native_summary = summarize_native_mesh_uvs(", service_uv_summary_body)
        self.assertLess(
            service_uv_summary_body.index("if session.native_editor_mesh_dirty:"),
            service_uv_summary_body.index("_prune_selection_to_mesh(session.working_mesh, session.selection)"),
        )
        self.assertLess(
            service_uv_summary_body.index("native_summary = summarize_native_mesh_uvs("),
            service_uv_summary_body.index("summarize_mesh_uvs("),
        )
        self.assertIn(',\\"uv_count\\":', native_core_source)
        self.assertIn(',\\"selected_vertex_count\\":', native_core_source)
        self.assertIn(',\\"has_skinning\\":', native_core_source)
        uv_region_start = service_source.index("def select_uv_region(")
        uv_region_body = service_source[uv_region_start: service_source.index("def select_uv_lasso(", uv_region_start)]
        self.assertIn("native_vertices = select_native_mesh_uv_vertices(", uv_region_body)
        self.assertIn("_record_blocked_python_selection_fallback(", uv_region_body)
        self.assertIn("return self._select_native_uv_vertices(", uv_region_body)
        self.assertIn('status="error"', uv_region_body)
        self.assertNotIn("mesh_uv_region_selection(", uv_region_body)
        self.assertNotIn("_allow_python_selection_fallback(", uv_region_body)
        self.assertNotIn("_apply_selection_operation_to_mesh(", uv_region_body)
        uv_lasso_start = service_source.index("def select_uv_lasso(")
        uv_lasso_body = service_source[uv_lasso_start: service_source.index("def apply_command(", uv_lasso_start)]
        self.assertIn("native_vertices = select_native_mesh_uv_vertices(", uv_lasso_body)
        self.assertIn("_record_blocked_python_selection_fallback(", uv_lasso_body)
        self.assertIn("return self._select_native_uv_vertices(", uv_lasso_body)
        self.assertIn("_apply_native_editor_session_selection_operation(", uv_lasso_body)
        self.assertIn('status="error"', uv_lasso_body)
        self.assertNotIn("mesh_uv_lasso_selection(", uv_lasso_body)
        self.assertNotIn("_allow_python_selection_fallback(", uv_lasso_body)
        self.assertNotIn("_apply_selection_operation_to_mesh(", uv_lasso_body)
        self.assertIn("def _allow_python_selection_fallback(", service_source)
        selection_fallback_start = service_source.index("def _allow_python_selection_fallback(")
        selection_fallback_body = service_source[
            selection_fallback_start: service_source.index("def _selected_skin_weight_vertex_count(", selection_fallback_start)
        ]
        self.assertIn("native_mesh_core_available()", selection_fallback_body)
        self.assertIn("record_native_mesh_core_fallback(", selection_fallback_body)
        self.assertIn(".blocked", selection_fallback_body)
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT", selection_fallback_body)
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_FACE_LIMIT", selection_fallback_body)
        self.assertIn("Python mesh selection fallback blocked while native mesh core is available", selection_fallback_body)
        self.assertIn("def build_native_mesh_selection_groups(", mesh_native_source)
        self.assertIn('"selection-preview-json"', mesh_native_source)
        self.assertIn("run_selection_preview", native_core_source)
        self.assertIn("selection_preview_report_json", native_core_source)
        selection_preview_start = mesh_native_source.index("def build_native_mesh_selection_groups(")
        selection_preview_body = mesh_native_source[
            selection_preview_start: mesh_native_source.index("def select_native_mesh_uv_vertices(", selection_preview_start)
        ]
        self.assertIn("_ensure_native_mesh_session_submesh(", selection_preview_body)
        self.assertIn("stop_event: threading.Event | None = None", selection_preview_body)
        self.assertIn("stop_event=stop_event", selection_preview_body)
        self.assertIn("**_native_job_kwargs(stop_event=stop_event, timeout_seconds=timeout_seconds)", selection_preview_body)
        self.assertIn('item["session_id"] = session_id', selection_preview_body)
        self.assertIn('"selection_preview_output_path": _native_preview_delta_output_path("_selection.bin")', selection_preview_body)
        self.assertIn("for index in source_indices or ()", selection_preview_body)
        self.assertNotIn("tuple(source_indices or ())", selection_preview_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', selection_preview_body)
        self.assertIn("_put_source_face_indices_payload(item, prefix, source_face_indices)", selection_preview_body)
        self.assertNotIn('item["source_face_indices_binary"] = _write_int_binary_payload', selection_preview_body)
        self.assertIn("_put_i32_range_or_binary_payload(", selection_preview_body)
        self.assertIn('start_key="selected_vertex_start"', selection_preview_body)
        self.assertIn('binary_key="selected_vertices_binary"', selection_preview_body)
        self.assertIn('item["selected_edges_binary"] = _write_edge_binary_payload', selection_preview_body)
        self.assertIn('start_key="selected_face_start"', selection_preview_body)
        self.assertIn('binary_key="selected_faces_binary"', selection_preview_body)
        self.assertIn("_native_selection_preview_group(raw_group, source_submesh_index)", selection_preview_body)
        self.assertNotIn('"faces": faces', selection_preview_body)
        self.assertNotIn('"source_face_indices": source_face_indices', selection_preview_body)
        self.assertNotIn('"selected_vertices": selected_vertices', selection_preview_body)
        self.assertNotIn('"selected_edges": selected_edges', selection_preview_body)
        self.assertNotIn('"selected_faces": selected_faces', selection_preview_body)
        preview_native_start = native_core_source.index("std::vector<SubmeshSelectionPreviewResult> run_selection_preview")
        preview_native_body = native_core_source[
            preview_native_start: native_core_source.index("double brush_falloff_weight", preview_native_start)
        ]
        self.assertIn("mesh_vertex_count_from_item(item)", preview_native_body)
        self.assertIn("mesh_faces_from_item(item, vertex_count)", preview_native_body)
        self.assertIn("mesh_source_face_indices_from_item(item, faces.size())", preview_native_body)
        self.assertIn("def prune_native_mesh_selection(", mesh_native_source)
        self.assertIn('"selection-prune-json"', mesh_native_source)
        combine_sources_start = mesh_native_source.index("def _combine_native_selection_sources(")
        combine_sources_body = mesh_native_source[
            combine_sources_start: mesh_native_source.index("def _empty_pruned_selection(", combine_sources_start)
        ]
        self.assertIn("for raw_index in (current if current is not None else ())", combine_sources_body)
        self.assertIn("for raw_index in (incoming if incoming is not None else ())", combine_sources_body)
        self.assertNotIn("tuple(current or ())", combine_sources_body)
        self.assertNotIn("tuple(incoming or ())", combine_sources_body)
        prune_bridge_body = _read("cdmw/modding/mesh_native_selection.py")
        self.assertIn("_ensure_native_mesh_session_submesh(", prune_bridge_body)
        self.assertIn('item["session_id"] = session_id', prune_bridge_body)
        self.assertIn('"face_count": face_count', prune_bridge_body)
        self.assertIn('"selection_operation": operation', prune_bridge_body)
        self.assertIn("_put_i32_range_or_binary_payload(", prune_bridge_body)
        self.assertIn('start_key="selected_vertex_start"', prune_bridge_body)
        self.assertIn('binary_key="selected_vertices_binary"', prune_bridge_body)
        self.assertIn('item["selected_edges_binary"] = _write_edge_binary_payload', prune_bridge_body)
        self.assertIn('start_key="selected_face_start"', prune_bridge_body)
        self.assertIn('binary_key="selected_faces_binary"', prune_bridge_body)
        self.assertIn("selected_all_vertices_by_submesh: Sequence[int] = ()", prune_bridge_body)
        self.assertIn("selected_all_sources = {", prune_bridge_body)
        self.assertNotIn("tuple(selected_all_vertices_by_submesh or ())", prune_bridge_body)
        self.assertIn("| selected_all_sources", prune_bridge_body)
        self.assertIn('item["selected_all_vertices"] = True', prune_bridge_body)
        self.assertIn('start_key="current_selected_vertex_start"', prune_bridge_body)
        self.assertIn('binary_key="current_selected_vertices_binary"', prune_bridge_body)
        self.assertIn('item["current_selected_edges_binary"] = _write_edge_binary_payload', prune_bridge_body)
        self.assertIn('start_key="current_selected_face_start"', prune_bridge_body)
        self.assertIn('binary_key="current_selected_faces_binary"', prune_bridge_body)
        self.assertIn('"_pruned_edges.bin"', prune_bridge_body)
        self.assertIn("_read_i32_components_binary_report_payload", prune_bridge_body)
        self.assertNotIn("_face_json([raw_faces[index]], vertex_count)", prune_bridge_body)
        self.assertNotIn('"selected_edges": selected_edges', prune_bridge_body)
        self.assertIn("std::vector<SubmeshSelectionPruneResult> run_selection_prune", native_core_source)
        prune_native_start = native_core_source.index("std::vector<SubmeshSelectionPruneResult> run_selection_prune")
        prune_native_body = native_core_source[
            prune_native_start: native_core_source.index("double brush_falloff_weight", prune_native_start)
        ]
        self.assertIn("mesh_vertex_count_from_item(item)", prune_native_body)
        self.assertIn("mesh_faces_from_item(item, vertex_count)", prune_native_body)
        self.assertIn("face_edge_set(faces)", prune_native_body)
        self.assertIn("combine_selection_sets(", prune_native_body)
        self.assertIn('"current_selected_vertices_binary"', prune_native_body)
        self.assertIn('"current_selected_edges_binary"', prune_native_body)
        self.assertIn('"current_selected_faces_binary"', prune_native_body)
        self.assertIn('selected_vertices_from_binary_or_json(item, vertex_count)', prune_native_body)
        self.assertIn("selected_edges_from_binary_or_json(item, vertex_count)", prune_native_body)
        self.assertIn("mesh_source_face_indices_from_item(item, faces.size())", prune_native_body)
        self.assertIn("selected_prune_faces_from_keys(", prune_native_body)
        self.assertIn("selected_indices_from_binary_or_json(", native_core_source)
        self.assertIn('"selected_vertex_start"', native_core_source)
        self.assertIn('"selected_face_start"', native_core_source)
        self.assertIn('"current_selected_vertex_start"', native_core_source)
        self.assertIn('"current_selected_face_start"', native_core_source)
        self.assertIn('"selected_faces_binary"', prune_native_body)
        self.assertIn("selection_face_count > faces.size()", native_core_source)
        self.assertIn("selected_faces = std::move(kept_faces)", native_core_source)
        self.assertIn("bool strict_int_or(const JsonValue* value, int& out)", native_core_source)
        self.assertIn("!strict_int_or(&item.array_value[0], a)", native_core_source)
        self.assertIn("!strict_int_or(&item.array_value[1], b)", native_core_source)
        self.assertIn("!strict_int_or(&item.array_value[2], c)", native_core_source)
        self.assertIn("source_face_indices_from_faces_json", native_core_source)
        self.assertIn("raw_source_faces.size() == faces.size()", prune_native_body)
        self.assertIn("selection_prune_report_json", native_core_source)
        self.assertIn("selection_prune_json_command", native_core_source)
        self.assertIn('command == "selection-prune-json"', native_core_source)
        selection_native_start = native_core_source.index("std::vector<SubmeshSelectionResult> run_selection_edit")
        selection_native_body = native_core_source[
            selection_native_start: native_core_source.index("std::vector<Vec2> vec2_array_from_json", selection_native_start)
        ]
        self.assertIn("selected_vertices_from_edit_domains(item, vertex_count, faces)", selection_native_body)
        self.assertNotIn("selected_vertices_from_binary_or_json(item, vertex_count)", selection_native_body)
        self.assertIn('string_or(item.get("selection_preview_output_path"), "")', native_core_source)
        self.assertIn("write_selection_preview_group", native_core_source)
        self.assertIn("contiguous_int_range(result.source_vertex_indices, source_vertex_start)", native_core_source)
        self.assertIn("contiguous_int_range(result.source_face_indices, source_face_start)", native_core_source)
        self.assertIn("contiguous_int_range(result.selected_vertices, selected_vertex_start)", native_core_source)
        self.assertIn("contiguous_int_range(result.selected_faces, selected_face_start)", native_core_source)
        self.assertIn("source_vertex_indices_binary", native_core_source)
        self.assertIn("source_edges_binary", native_core_source)
        self.assertIn("source_face_indices_binary", native_core_source)
        selection_group_start = mesh_native_source.index("def _native_selection_preview_group(")
        selection_group_body = mesh_native_source[
            selection_group_start: mesh_native_source.index("def _write_vec3_binary_payload(", selection_group_start)
        ]
        self.assertIn('source_vertex_start = _index(value.get("source_vertex_start"))', selection_group_body)
        self.assertIn('source_face_start = _index(value.get("source_face_start"))', selection_group_body)
        self.assertIn("selected_vertices_from_binary_or_json(item, vertex_count)", preview_native_body)
        self.assertIn('"selected_faces_binary",', preview_native_body)
        self.assertIn('"selected_faces",', preview_native_body)
        self.assertIn('"selected_face_start",', preview_native_body)
        self.assertIn('"selected_face_count"', preview_native_body)
        self.assertIn("selected_edges_from_binary_or_json(item, vertex_count)", preview_native_body)
        self.assertNotIn("vertices_from_json(item.get(\"vertices\"))", preview_native_body)
        self.assertNotIn("faces_from_json(item.get(\"faces\")", preview_native_body)
        self.assertNotIn("selected_edges_from_json(item.get(\"selected_edges\")", preview_native_body)
        standalone_payload_source = _read("cdmw/ui/mesh_editor/native_preview_payloads.py")
        self.assertIn("native_groups = _mesh_edit_selection_groups_native(mesh, selection, stop_event=stop_event)", standalone_payload_source)
        self.assertIn("def _mesh_edit_selection_groups_python_reference(", standalone_payload_source)
        selection_fallback_start = standalone_payload_source.index("def _mesh_edit_selection_groups_python_reference(")
        selection_fallback_body = standalone_payload_source[
            selection_fallback_start: standalone_payload_source.index("def mesh_edit_vertex_update_groups(", selection_fallback_start)
        ]
        self.assertIn("whole_vertex_submeshes.add(submesh_index)", selection_fallback_body)
        self.assertIn('vertices: Sequence[int] = range(len(submesh.vertices))', selection_fallback_body)
        self.assertIn(
            '_put_index_range_or_values(group, vertices, "source_vertex_indices", "source_vertex_start", "source_vertex_count")',
            selection_fallback_body,
        )
        self.assertIn(
            '_put_index_range_or_values(group, selected_faces, "source_face_indices", "source_face_start", "source_face_count")',
            selection_fallback_body,
        )
        self.assertNotIn(".update(range(len(mesh.submeshes[submesh_index].vertices)))", selection_fallback_body)
        self.assertIn("build_x_mirror_pairs_native(result.vertices)", native_core_source)
        self.assertIn("build_vertex_adjacency(original.size(), faces)", native_core_source)
        self.assertIn("run_selection_edit", native_core_source)
        selection_native_start = native_core_source.index("std::vector<SubmeshSelectionResult> run_selection_edit")
        selection_native_body = native_core_source[
            selection_native_start: native_core_source.index("std::vector<Vec2> vec2_array_from_json", selection_native_start)
        ]
        self.assertIn('result.selected_vertices_path = string_or(item.get("selected_vertices_output_path"), "")', selection_native_body)
        self.assertIn("mesh_vertex_count_from_item(item)", selection_native_body)
        self.assertIn("mesh_faces_from_item(item, vertex_count)", selection_native_body)
        self.assertIn("selected_vertices_from_edit_domains(item, vertex_count, faces)", selection_native_body)
        self.assertIn('const bool invert_operation = operation == "invert";', selection_native_body)
        self.assertIn("if (selected.empty() && !invert_operation && !all_operation)", selection_native_body)
        self.assertIn("if (invert_operation) {", selection_native_body)
        self.assertIn('if normalized_operation not in {"grow", "shrink", "smooth", "invert", "all"}:', mesh_native_source)
        self.assertIn('selected_all_vertices = normalized_operation != "invert" and submesh_index in requested_sources', mesh_native_source)
        self.assertIn('invert_scope = normalized_operation == "invert" and submesh_index in requested_sources', mesh_native_source)
        self.assertIn('const bool all_operation = operation == "all";', selection_native_body)
        self.assertIn("if (all_operation) {", selection_native_body)
        self.assertNotIn("selected_vertices_from_binary_or_json(item, vertex_count)", selection_native_body)
        self.assertNotIn("vertices_from_json(item.get(\"vertices\"))", selection_native_body)
        self.assertNotIn("faces_from_json(item.get(\"faces\")", selection_native_body)
        selection_report_start = native_core_source.index("std::string selection_report_json(")
        selection_report_body = native_core_source[
            selection_report_start: native_core_source.index("std::vector<int> flatten_selection_edges", selection_report_start)
        ]
        self.assertIn("contiguous_int_range(result.selected_vertices, selected_vertex_start)", selection_report_body)
        self.assertLess(
            selection_report_body.index("contiguous_int_range(result.selected_vertices, selected_vertex_start)"),
            selection_report_body.index("write_int_binary_file(result.selected_vertices_path, result.selected_vertices)"),
        )
        self.assertIn('\\"selected_vertex_start\\"', selection_report_body)
        self.assertIn('\\"selected_vertex_count\\"', selection_report_body)
        self.assertIn("write_int_binary_file(result.selected_vertices_path, result.selected_vertices)", selection_report_body)
        self.assertIn("write_int_binary_descriptor(out, result.selected_vertices_path, result.selected_vertices.size(), 1)", selection_report_body)
        cleanup_start = mesh_native_source.index("def apply_native_mesh_remove_doubles(")
        cleanup_body = mesh_native_source[
            cleanup_start: mesh_native_source.index("def native_mesh_auto_uv_report(", cleanup_start)
        ]
        self.assertIn("session_id = _ensure_native_mesh_session_submesh", cleanup_body)
        self.assertIn('item["session_id"] = session_id', cleanup_body)
        self.assertIn('item["vertices_binary"] = _write_vec3_binary_payload', cleanup_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', cleanup_body)
        self.assertLess(
            cleanup_body.index("session_id = _ensure_native_mesh_session_submesh"),
            cleanup_body.index("_face_json("),
        )
        self.assertIn("selected_all_vertices = selected is None", cleanup_body)
        self.assertIn('item["selected_all_vertices"] = True', cleanup_body)
        self.assertIn("_put_selected_vertices_payload(item, prefix, kept", cleanup_body)
        self.assertNotIn('item["selected_vertices_binary"] = _write_int_binary_payload', cleanup_body)
        self.assertIn('"vertices_output_path": _native_preview_delta_output_path("_cleanup_vertices.bin")', cleanup_body)
        self.assertIn('"faces_output_path": _native_preview_delta_output_path("_cleanup_faces.bin")', cleanup_body)
        self.assertIn('"suppress_index_map_report": True', cleanup_body)
        self.assertNotIn('"index_map_output_path": _native_preview_delta_output_path("_cleanup_index_map.bin")', cleanup_body)
        self.assertIn('"normals_output_path": _native_preview_delta_output_path("_cleanup_normals.bin")', cleanup_body)
        self.assertIn('item["uvs_binary"] = _write_vec2_binary_payload', cleanup_body)
        self.assertIn('item["uvs_output_path"] = _native_preview_delta_output_path("_cleanup_uvs.bin")', cleanup_body)
        self.assertIn('item["tangents_binary"] = _write_vec3_binary_payload', cleanup_body)
        self.assertIn('item["tangents_output_path"] = _native_preview_delta_output_path("_cleanup_tangents.bin")', cleanup_body)
        self.assertIn('item["bone_counts_output_path"] = _native_preview_delta_output_path("_cleanup_bone_counts.bin")', cleanup_body)
        self.assertIn('item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_cleanup_source_vertex_map.bin")', cleanup_body)
        self.assertIn("_put_source_vertex_map_payload(item, prefix", cleanup_body)
        self.assertIn('item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_cleanup_source_vertex_offsets.bin")', cleanup_body)
        self.assertIn("_put_source_vertex_offsets_payload(item, prefix", cleanup_body)
        self.assertNotIn('"vertices": [_vec3_json(vertex) for vertex in submesh.vertices]', cleanup_body)
        self.assertNotIn('"faces": _face_json(submesh.faces, len(submesh.vertices))', cleanup_body)
        self.assertNotIn('"selected_vertices": kept', cleanup_body)
        self.assertNotIn('tuple(getattr(submesh, "tangents", ()) or ())', cleanup_body)
        self.assertNotIn('tuple(getattr(submesh, "tangent_signs", ()) or ())', cleanup_body)
        self.assertNotIn('tuple(getattr(submesh, "source_vertex_map", ()) or ())', cleanup_body)
        self.assertNotIn('tuple(getattr(submesh, "source_vertex_offsets", ()) or ())', cleanup_body)
        cleanup_native_start = native_core_source.index("std::vector<SubmeshCleanupResult> run_cleanup")
        cleanup_native_body = native_core_source[
            cleanup_native_start: native_core_source.index("std::vector<SubmeshOptimizeResult> run_optimize", cleanup_native_start)
        ]
        self.assertIn("mesh_vertices_from_item(item)", cleanup_native_body)
        self.assertIn("mesh_faces_from_item(item, vertices.size())", cleanup_native_body)
        selected_helper_start = native_core_source.index("std::set<int> selected_vertices_from_binary_or_json(")
        selected_helper_body = native_core_source[
            selected_helper_start: native_core_source.index("std::set<int> selected_indices_from_binary_or_json", selected_helper_start)
        ]
        selected_keyed_start = native_core_source.index("std::set<int> selected_vertices_from_binary_or_json_keys(")
        selected_keyed_body = native_core_source[
            selected_keyed_start: native_core_source.index("std::set<int> selected_vertices_from_binary_or_json(", selected_keyed_start)
        ]
        self.assertIn('bool_or(item.get("selected_all_vertices"), false)', selected_helper_body)
        self.assertLess(
            selected_helper_body.index('bool_or(item.get("selected_all_vertices"), false)'),
            selected_helper_body.index("selected_vertices_from_binary_or_json_keys("),
        )
        self.assertIn('"selected_vertex_start"', selected_helper_body)
        self.assertIn('"selected_vertex_count"', selected_helper_body)
        self.assertIn("int_vector_from_binary_or_json(", selected_keyed_body)
        self.assertIn("range_start_key", selected_keyed_body)
        self.assertIn("range_count_key", selected_keyed_body)
        self.assertNotIn('vertices_from_binary_or_json(item, "vertices_binary", "vertices")', cleanup_native_body)
        self.assertNotIn("faces_from_binary_or_json(item, vertices.size())", cleanup_native_body)
        self.assertIn("selected_vertices_from_binary_or_json(item, vertices.size())", cleanup_native_body)
        self.assertIn('result.vertices_path = vertices_path', cleanup_native_body)
        self.assertIn('result.faces_path = faces_path', cleanup_native_body)
        self.assertIn('result.index_map_path = index_map_path', cleanup_native_body)
        self.assertIn("result.normals = compute_smooth_normals(result.vertices, result.faces)", cleanup_native_body)
        self.assertIn("result.uvs = remap_vec2_by_index_map(mesh_uvs_from_item(item), result.index_map, result.vertices.size())", cleanup_native_body)
        self.assertIn("result.tangents = remap_vec3_by_index_map(mesh_tangents_from_item(item), result.index_map, result.vertices.size())", cleanup_native_body)
        self.assertIn("result.bones = remap_bones_by_index_map(mesh_bones_from_item(item), result.index_map, result.vertices.size())", cleanup_native_body)
        self.assertIn("result.source_vertex_map = remap_int_by_index_map(", cleanup_native_body)
        self.assertIn("source_vertex_map = session->source_vertex_map", cleanup_native_body)
        self.assertIn("source_vertex_offsets = session->source_vertex_offsets", cleanup_native_body)
        self.assertIn("mutable_mesh_session_submesh_for_item(item)", cleanup_native_body)
        self.assertIn("session->vertices = result.vertices", cleanup_native_body)
        self.assertNotIn("vertices_from_json(item.get(\"vertices\"))", cleanup_native_body)
        cleanup_report_start = native_core_source.index("std::string cleanup_report_json(")
        cleanup_report_body = native_core_source[
            cleanup_report_start: native_core_source.index("std::string mesh_edit_report_json(", cleanup_report_start)
        ]
        self.assertIn("write_vec3_binary_file(result.vertices_path, result.vertices)", cleanup_report_body)
        self.assertIn("write_vec3_binary_descriptor(out, result.vertices_path, result.vertices.size())", cleanup_report_body)
        self.assertIn("write_faces_binary_file(result.faces_path, result.faces)", cleanup_report_body)
        self.assertIn("write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3)", cleanup_report_body)
        self.assertIn("if (result.suppress_index_map_report)", cleanup_report_body)
        self.assertIn('out << ",\\"index_map_report_suppressed\\":true"', cleanup_report_body)
        self.assertIn("write_int_binary_file(result.index_map_path, result.index_map)", cleanup_report_body)
        self.assertIn("write_int_binary_descriptor(out, result.index_map_path, result.index_map.size(), 1)", cleanup_report_body)
        self.assertIn("write_vec3_binary_file(result.normals_path, result.normals)", cleanup_report_body)
        self.assertIn("write_vec2_binary_file(result.uvs_path, result.uvs)", cleanup_report_body)
        self.assertIn("write_vec3_binary_file(result.tangents_path, result.tangents)", cleanup_report_body)
        self.assertIn("write_int_binary_file(result.bone_counts_path, bone_counts)", cleanup_report_body)
        self.assertIn("write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map)", cleanup_report_body)
        apply_cleanup_start = mesh_native_source.index("def _apply_cleanup_report(")
        apply_cleanup_body = mesh_native_source[
            apply_cleanup_start: mesh_native_source.index("def _apply_auto_uv_report(", apply_cleanup_start)
        ]
        self.assertIn('raw_vertices_binary = item.get("vertices_binary")', apply_cleanup_body)
        self.assertIn('raw_faces_binary = item.get("faces_binary")', apply_cleanup_body)
        self.assertIn('raw_index_map_binary = item.get("index_map_binary")', apply_cleanup_body)
        self.assertIn('raw_normals_binary = item.get("normals_binary")', apply_cleanup_body)
        self.assertIn('raw_uvs_binary = item.get("uvs_binary")', apply_cleanup_body)
        self.assertIn('raw_bone_counts_binary = item.get("bone_counts_binary")', apply_cleanup_body)
        self.assertIn('raw_source_vertex_map_binary = item.get("source_vertex_map_binary")', apply_cleanup_body)
        self.assertIn("_read_vec3_binary_report_payload(raw_vertices_binary", apply_cleanup_body)
        self.assertIn("_read_face_binary_report_payload(raw_faces_binary", apply_cleanup_body)
        self.assertIn("_read_i32_binary_report_payload(raw_index_map_binary", apply_cleanup_body)
        self.assertIn("if index_map is None:", apply_cleanup_body)
        self.assertIn("if native_normals is None:", apply_cleanup_body)
        self.assertIn("_read_vertex_aligned_native_channels(item, len(parsed_vertices))", apply_cleanup_body)
        channel_reader_source = _read("cdmw/modding/mesh_native_report_geometry.py")
        channel_reader_start = channel_reader_source.index("def _read_vertex_aligned_native_channels(")
        channel_reader_body = channel_reader_source[
            channel_reader_start:channel_reader_source.index("def _apply_cleanup_report(", channel_reader_start)
        ]
        self.assertIn("(_read_vec3_binary_report_payload, raw_normals_binary)", channel_reader_body)
        self.assertIn("(_read_vec2_binary_report_payload, raw_uvs_binary)", channel_reader_body)
        self.assertIn("_read_bone_binary_report_payloads(", channel_reader_body)
        self.assertIn("(_read_i32_binary_report_payload, raw_source_vertex_map_binary)", channel_reader_body)
        self.assertIn("if native_normals is None:", apply_cleanup_body)
        self.assertIn("recompute_submesh_normals(submesh)", apply_cleanup_body)
        auto_uv_start = mesh_native_source.index("def native_mesh_auto_uv_report(")
        auto_uv_body = mesh_native_source[
            auto_uv_start: mesh_native_source.index("def native_scene_import_report(", auto_uv_start)
        ]
        self.assertIn("session_id = _ensure_native_mesh_session_submesh", auto_uv_body)
        self.assertIn('item["session_id"] = session_id', auto_uv_body)
        self.assertIn('item["vertices_binary"] = _write_vec3_binary_payload', auto_uv_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', auto_uv_body)
        self.assertLess(
            auto_uv_body.index("session_id = _ensure_native_mesh_session_submesh"),
            auto_uv_body.index("faces = _face_json("),
        )
        self.assertIn('"vertices_output_path": _native_preview_delta_output_path("_auto_uv_vertices.bin")', auto_uv_body)
        self.assertIn('"vertex_remap_output_path": _native_preview_delta_output_path("_auto_uv_vertex_remap.bin")', auto_uv_body)
        self.assertIn('"faces_output_path": _native_preview_delta_output_path("_auto_uv_faces.bin")', auto_uv_body)
        self.assertIn('"uvs_output_path": _native_preview_delta_output_path("_auto_uv_uvs.bin")', auto_uv_body)
        self.assertIn('"changed_vertices_output_path": _native_preview_delta_output_path("_auto_uv_changed_vertices.bin")', auto_uv_body)
        self.assertIn('"normals_output_path": _native_preview_delta_output_path("_auto_uv_normals.bin")', auto_uv_body)
        self.assertIn('item["tangents_output_path"] = _native_preview_delta_output_path("_auto_uv_tangents.bin")', auto_uv_body)
        self.assertIn('item["tangent_signs_output_path"] = _native_preview_delta_output_path("_auto_uv_tangent_signs.bin")', auto_uv_body)
        self.assertIn('item["bone_counts_output_path"] = _native_preview_delta_output_path("_auto_uv_bone_counts.bin")', auto_uv_body)
        self.assertIn('item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_auto_uv_source_vertex_map.bin")', auto_uv_body)
        self.assertIn("_put_source_vertex_map_payload(item, prefix", auto_uv_body)
        self.assertIn('item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_auto_uv_source_vertex_offsets.bin")', auto_uv_body)
        self.assertIn("_put_source_vertex_offsets_payload(item, prefix", auto_uv_body)
        self.assertNotIn('"vertices": [_vec3_json(vertex) for vertex in submesh.vertices]', auto_uv_body)
        self.assertNotIn('"faces": faces', auto_uv_body)
        apply_auto_uv_start = mesh_native_source.index("def _apply_auto_uv_report(")
        apply_auto_uv_body = mesh_native_source[
            apply_auto_uv_start: mesh_native_source.index("def _apply_uv_transform_report(", apply_auto_uv_start)
        ]
        self.assertIn('raw_remap_binary = item.get("vertex_remap_binary")', apply_auto_uv_body)
        self.assertIn('raw_vertices_binary = item.get("vertices_binary")', apply_auto_uv_body)
        self.assertIn('raw_uvs_binary = item.get("uvs_binary")', apply_auto_uv_body)
        self.assertIn('raw_faces_binary = item.get("faces_binary")', apply_auto_uv_body)
        self.assertIn('raw_normals_binary = item.get("normals_binary")', apply_auto_uv_body)
        self.assertIn('raw_bone_counts_binary = item.get("bone_counts_binary")', apply_auto_uv_body)
        self.assertIn('raw_source_vertex_map_binary = item.get("source_vertex_map_binary")', apply_auto_uv_body)
        self.assertIn("_read_i32_binary_report_payload(raw_remap_binary", apply_auto_uv_body)
        self.assertIn("_read_vec3_binary_report_payload(raw_vertices_binary", apply_auto_uv_body)
        self.assertIn("_read_vec2_binary_report_payload(raw_uvs_binary", apply_auto_uv_body)
        self.assertIn("_read_face_binary_report_payload(raw_faces_binary", apply_auto_uv_body)
        self.assertIn("_read_vertex_aligned_native_channels(item, len(remap))", apply_auto_uv_body)
        self.assertIn("(_read_vec3_binary_report_payload, raw_normals_binary)", channel_reader_body)
        self.assertIn("_read_bone_binary_report_payloads(", channel_reader_body)
        self.assertIn("(_read_i32_binary_report_payload, raw_source_vertex_map_binary)", channel_reader_body)
        self.assertIn("parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_uvs))", apply_auto_uv_body)
        self.assertIn("has_native_changed_vertices = parsed_changed_ordered is not None", apply_auto_uv_body)
        self.assertIn("old_uvs = () if has_native_changed_vertices else", apply_auto_uv_body)
        self.assertLess(
            apply_auto_uv_body.index("parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_uvs))"),
            apply_auto_uv_body.index("old_uvs = () if has_native_changed_vertices else"),
        )
        optimize_start = mesh_native_source.index("def native_mesh_optimization_report(")
        optimize_body = mesh_native_source[
            optimize_start: mesh_native_source.index("def apply_native_mesh_auto_uv(", optimize_start)
        ]
        self.assertIn("session_id = _ensure_native_mesh_session_submesh", optimize_body)
        self.assertIn('item["session_id"] = session_id', optimize_body)
        self.assertIn('item["vertices_binary"] = _write_vec3_binary_payload', optimize_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', optimize_body)
        self.assertLess(
            optimize_body.index("session_id = _ensure_native_mesh_session_submesh"),
            optimize_body.index("faces = _face_json("),
        )
        self.assertNotIn('"vertices": [_vec3_json(vertex) for vertex in submesh.vertices]', optimize_body)
        self.assertNotIn('"faces": faces', optimize_body)
        uv_transform_start = mesh_native_source.index("def apply_native_mesh_uv_transform(")
        uv_transform_body = mesh_native_source[
            uv_transform_start: mesh_native_source.index("def _topology_edit_submeshes(", uv_transform_start)
        ]
        self.assertIn("session_id = _ensure_native_mesh_session_submesh", uv_transform_body)
        self.assertIn('item["session_id"] = session_id', uv_transform_body)
        self.assertIn('item["uvs_binary"] = _write_vec2_binary_payload', uv_transform_body)
        self.assertLess(
            uv_transform_body.index("session_id = _ensure_native_mesh_session_submesh"),
            uv_transform_body.index('item["uvs_binary"] = _write_vec2_binary_payload'),
        )
        self.assertIn("_put_selected_edit_domain_payload(", uv_transform_body)
        self.assertIn("needs_missing_uv_init = bool(initialize_missing_uvs or needs_projection)", uv_transform_body)
        self.assertIn('"projection": projection', uv_transform_body)
        self.assertIn('"pack": pack', uv_transform_body)
        self.assertIn('"snap_step": snap_step', uv_transform_body)
        self.assertIn("selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None", uv_transform_body)
        self.assertIn("selected_faces_by_submesh: Mapping[int, set[int]] | None = None", uv_transform_body)
        self.assertIn("source_indices: Sequence[int] = ()", uv_transform_body)
        self.assertNotIn("_put_selected_vertices_payload(item, prefix, kept", uv_transform_body)
        self.assertNotIn("kept = sorted(index for index in selected", uv_transform_body)
        self.assertNotIn('"selected_vertices_binary": _write_int_binary_payload', uv_transform_body)
        self.assertIn('"uvs_output_path": _native_preview_delta_output_path("_uv_transform_uvs.bin")', uv_transform_body)
        self.assertIn('"changed_vertices_output_path": _native_preview_delta_output_path("_uv_transform_changed_vertices.bin")', uv_transform_body)
        self.assertNotIn('"uvs": [_vec2_json(uv) for uv in submesh.uvs]', uv_transform_body)
        self.assertNotIn('"selected_vertices": kept', uv_transform_body)
        apply_uv_start = mesh_native_source.index("def _apply_uv_transform_report(")
        apply_uv_body = mesh_native_source[apply_uv_start: mesh_native_source.index("def _native_job_kwargs(", apply_uv_start)]
        self.assertIn('raw_uvs_binary = item.get("uvs_binary")', apply_uv_body)
        self.assertIn("expected_uv_count = len(submesh.uvs)", apply_uv_body)
        self.assertIn("expected_uv_count = len(submesh.vertices)", apply_uv_body)
        self.assertIn("mesh.has_uvs = True", apply_uv_body)
        self.assertIn("_read_vec2_binary_report_payload(raw_uvs_binary", apply_uv_body)
        self.assertIn("parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_uvs))", apply_uv_body)
        self.assertIn("_merge_changed_vertices(", apply_uv_body)
        self.assertIn("parsed_changed_ordered,", apply_uv_body)
        self.assertNotIn("parsed_changed = set(parsed_changed_ordered)", apply_uv_body)
        optimize_native_start = native_core_source.index("std::vector<SubmeshOptimizeResult> run_optimize")
        optimize_native_body = native_core_source[
            optimize_native_start: native_core_source.index("std::vector<SubmeshUvTransformResult> run_uv_transform", optimize_native_start)
        ]
        self.assertIn("mesh_vertices_from_item(item)", optimize_native_body)
        self.assertIn("mesh_faces_from_item(item, vertices.size())", optimize_native_body)
        self.assertNotIn('vertices_from_binary_or_json(item, "vertices_binary", "vertices")', optimize_native_body)
        self.assertNotIn("faces_from_binary_or_json(item, vertices.size())", optimize_native_body)
        self.assertNotIn("vertices_from_json(item.get(\"vertices\"))", optimize_native_body)
        uv_native_start = native_core_source.index("std::vector<SubmeshUvTransformResult> run_uv_transform")
        uv_native_body = native_core_source[uv_native_start: native_core_source.index("Vec3 face_normal", uv_native_start)]
        self.assertIn("result.uvs = mesh_uvs_from_item(item)", uv_native_body)
        self.assertIn("mesh_vertex_count_from_item(item)", uv_native_body)
        self.assertNotIn("result.uvs = uvs_from_binary_or_json(item)", uv_native_body)
        self.assertIn('result.uvs_path = string_or(item.get("uvs_output_path"), "")', uv_native_body)
        self.assertIn('result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "")', uv_native_body)
        self.assertIn("selected_vertices_from_edit_domains(item, result.uvs.size(), faces)", uv_native_body)
        self.assertIn("uv_transform_projects(transform)", uv_native_body)
        self.assertIn("normalize_uv_indices(result.uvs", uv_native_body)
        self.assertIn("pack_uvs(result.uvs", uv_native_body)
        self.assertIn("align_uvs(result.uvs", uv_native_body)
        self.assertIn("snap_uvs(result.uvs", uv_native_body)
        self.assertIn("mutable_mesh_session_submesh_for_item(item)", uv_native_body)
        self.assertIn("session->uvs = result.uvs", uv_native_body)
        self.assertNotIn("uvs_from_json(item.get(\"uvs\"))", uv_native_body)
        self.assertNotIn("selected_vertices_from_json(item.get(\"selected_vertices\")", uv_native_body)
        uv_report_start = native_core_source.index("std::string uv_transform_report_json(")
        uv_report_body = native_core_source[uv_report_start: native_core_source.index("std::string auto_uv_report_json(", uv_report_start)]
        self.assertIn("write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start)", uv_report_body)
        self.assertIn("write_vec2_binary_file(result.uvs_path, result.uvs)", uv_report_body)
        self.assertIn("write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size())", uv_report_body)
        auto_uv_native_start = native_core_source.index("std::vector<SubmeshAutoUvResult> run_auto_uv")
        auto_uv_native_body = native_core_source[auto_uv_native_start: native_core_source.index("Vec3 add_vec3", auto_uv_native_start)]
        self.assertIn("mesh_vertices_from_item(item)", auto_uv_native_body)
        self.assertIn("mesh_faces_from_item(item, vertices.size())", auto_uv_native_body)
        self.assertNotIn('vertices_from_binary_or_json(item, "vertices_binary", "vertices")', auto_uv_native_body)
        self.assertNotIn("faces_from_binary_or_json(item, vertices.size())", auto_uv_native_body)
        self.assertIn('result.uvs_path = string_or(item.get("uvs_output_path"), "")', auto_uv_native_body)
        self.assertIn('result.faces_path = string_or(item.get("faces_output_path"), "")', auto_uv_native_body)
        self.assertIn('result.vertex_remap_path = string_or(item.get("vertex_remap_output_path"), "")', auto_uv_native_body)
        self.assertIn('result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "")', auto_uv_native_body)
        self.assertIn('result.vertices_path = string_or(item.get("vertices_output_path"), "")', auto_uv_native_body)
        self.assertIn('result.normals_path = string_or(item.get("normals_output_path"), "")', auto_uv_native_body)
        self.assertIn('result.tangents_path = string_or(item.get("tangents_output_path"), "")', auto_uv_native_body)
        self.assertIn('result.bone_counts_path = string_or(item.get("bone_counts_output_path"), "")', auto_uv_native_body)
        self.assertIn("populate_auto_uv_remapped_channels(result, item, vertices)", auto_uv_native_body)
        auto_uv_channels_start = native_core_source.index("void populate_auto_uv_remapped_channels(")
        auto_uv_channels_body = native_core_source[
            auto_uv_channels_start:native_core_source.index("std::vector<SubmeshAutoUvResult> run_auto_uv", auto_uv_channels_start)
        ]
        self.assertIn("copy_values_by_vertex_remap(vertices, result.vertex_remap)", auto_uv_channels_body)
        self.assertIn("copy_values_by_vertex_remap(mesh_normals_from_item(item), result.vertex_remap)", auto_uv_channels_body)
        self.assertIn("copy_bones_by_vertex_remap(mesh_bones_from_item(item), result.vertex_remap)", auto_uv_channels_body)
        self.assertIn("mesh_uvs_from_item(item)", auto_uv_native_body)
        self.assertIn("result.changed_vertices.push_back", auto_uv_native_body)
        self.assertIn("source_vertex_map = session->source_vertex_map", auto_uv_channels_body)
        self.assertIn("source_vertex_offsets = session->source_vertex_offsets", auto_uv_channels_body)
        self.assertNotIn("vertices_from_json(item.get(\"vertices\"))", auto_uv_native_body)
        auto_uv_report_start = native_core_source.index("std::string auto_uv_report_json(")
        auto_uv_report_body = native_core_source[auto_uv_report_start: native_core_source.index("std::string normals_report_json(", auto_uv_report_start)]
        self.assertIn("write_int_binary_file(result.vertex_remap_path, result.vertex_remap)", auto_uv_report_body)
        self.assertIn("write_int_binary_descriptor(out, result.vertex_remap_path, result.vertex_remap.size(), 1)", auto_uv_report_body)
        self.assertIn("write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start)", auto_uv_report_body)
        self.assertIn("write_faces_binary_file(result.faces_path, result.faces)", auto_uv_report_body)
        self.assertIn("write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3)", auto_uv_report_body)
        self.assertIn("write_vec2_binary_file(result.uvs_path, result.uvs)", auto_uv_report_body)
        self.assertIn("write_vec2_binary_descriptor(out, result.uvs_path, result.uvs.size())", auto_uv_report_body)
        self.assertIn("write_vec3_binary_file(result.vertices_path, result.vertices)", auto_uv_report_body)
        self.assertIn("write_vec3_binary_file(result.normals_path, result.normals)", auto_uv_report_body)
        self.assertIn("write_vec3_binary_file(result.tangents_path, result.tangents)", auto_uv_report_body)
        self.assertIn("write_double_binary_file(result.tangent_signs_path, result.tangent_signs)", auto_uv_report_body)
        self.assertIn("write_int_binary_file(result.bone_counts_path, bone_counts)", auto_uv_report_body)
        self.assertIn("write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map)", auto_uv_report_body)
        for operation, action_text in (
            ("grow", "Grow Selection"),
            ("shrink", "Shrink Selection"),
            ("smooth", "Smooth Selection"),
        ):
            action_body = _function_source(source, f"_mesh_edit_{operation}_selection")
            worker_call = f'_callbacks._mesh_edit_start_selection_worker("{operation}", "{operation.capitalize()} Selection")'
            native_call = f'_callbacks._mesh_edit_native_vertex_selection("{operation}")'
            unavailable_call = f'_callbacks._mesh_edit_native_selection_unavailable("{action_text}")'
            self.assertIn(worker_call, action_body)
            self.assertIn(native_call, action_body)
            self.assertIn(unavailable_call, action_body)
            self.assertNotIn("_mesh_edit_cached_vertex_selection(", action_body)
            self.assertLess(action_body.index(worker_call), action_body.index(native_call))
            self.assertLess(action_body.index(native_call), action_body.index(unavailable_call))

    def test_pose_preview_normals_use_native_kernel_before_python_fallback(self) -> None:
        service_source = _read("cdmw/services/mesh_service.py")
        bridge_source = _read("cdmw/modding/mesh_native_core.py")
        controller_source = _read("cdmw/ui/mesh_editor/controller.py")
        payload_source = _read("cdmw/ui/mesh_editor/native_preview_payloads.py")
        tab_source = _read("cdmw/ui/mesh_editor/tab.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")

        pose_start = service_source.index("def pose_preview_mesh(")
        pose_body = service_source[pose_start: service_source.index("def base_mesh(", pose_start)]
        native_context_start = service_source.index("def pose_preview_native_context(")
        native_context_body = service_source[native_context_start: service_source.index("def base_mesh(", native_context_start)]
        self.assertIn("def apply_native_mesh_pose_preview(", bridge_source)
        self.assertIn("def write_native_pose_preview_geometry_blob(", bridge_source)
        self.assertIn('"pose-preview-json"', bridge_source)
        self.assertIn("std::vector<SubmeshPosePreviewResult> run_pose_preview(", native_core_source)
        self.assertIn("Vec3 pose_skin_vertex(", native_core_source)
        self.assertIn('if (command == "pose-preview-json") return pose_preview_json_command(job_path, report_path);', native_core_source)
        self.assertIn("mesh = _clone_mesh_for_service_native_snapshot(", pose_body)
        self.assertIn("native mesh editor pose preview unavailable; Python mesh state is stale", pose_body)
        self.assertLess(
            pose_body.index("if session.native_editor_mesh_dirty:"),
            pose_body.index("mesh = _clone_mesh_for_service_native_snapshot("),
        )
        self.assertNotIn("clone_mesh_for_editing(session.working_mesh)", pose_body)
        self.assertIn("native_deformed = apply_native_mesh_pose_preview(session.working_mesh, session.skeleton, pose_rotations)", pose_body)
        self.assertIn('if not _allow_python_pose_preview_fallback(session.working_mesh, "preview.pose_deform"):', pose_body)
        self.assertIn('raise RuntimeError("native mesh editor pose preview unavailable; Python pose preview fallback is disabled")', pose_body)
        self.assertIn("deformed = mesh_pose_deformed_vertices(mesh, session.skeleton, pose_rotations)", pose_body)
        self.assertIn("native_normals = apply_native_mesh_recalculate_normals(mesh, deformed.keys())", pose_body)
        self.assertIn('if not _allow_python_pose_preview_fallback(mesh, "preview.pose_normals"):', pose_body)
        self.assertIn('raise RuntimeError("native mesh editor pose preview normals unavailable; Python pose preview fallback is disabled")', pose_body)
        self.assertIn("recompute_mesh_normals(mesh)", pose_body)
        self.assertLess(
            pose_body.index("mesh = _clone_mesh_for_service_native_snapshot("),
            pose_body.index("native_deformed = apply_native_mesh_pose_preview(session.working_mesh, session.skeleton, pose_rotations)"),
        )
        self.assertLess(
            pose_body.index("native_deformed = apply_native_mesh_pose_preview(session.working_mesh, session.skeleton, pose_rotations)"),
            pose_body.index("deformed = mesh_pose_deformed_vertices(mesh, session.skeleton, pose_rotations)"),
        )
        self.assertLess(
            pose_body.index('if not _allow_python_pose_preview_fallback(session.working_mesh, "preview.pose_deform"):'),
            pose_body.index("deformed = mesh_pose_deformed_vertices(mesh, session.skeleton, pose_rotations)"),
        )
        self.assertLess(
            pose_body.index("native_normals = apply_native_mesh_recalculate_normals(mesh, deformed.keys())"),
            pose_body.index('if not _allow_python_pose_preview_fallback(mesh, "preview.pose_normals"):'),
        )
        self.assertLess(
            pose_body.index('if not _allow_python_pose_preview_fallback(mesh, "preview.pose_normals"):'),
            pose_body.index("recompute_mesh_normals(mesh)"),
        )
        pose_fallback_start = service_source.index("def _allow_python_pose_preview_fallback(")
        pose_fallback_body = service_source[
            pose_fallback_start: service_source.index("def _allow_python_skin_weight_fallback(", pose_fallback_start)
        ]
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT", pose_fallback_body)
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_FACE_LIMIT", pose_fallback_body)
        self.assertIn("Python pose preview fallback blocked; native mesh core is required for active Mesh Editor pose preview", pose_fallback_body)
        self.assertIn("native_core_available=native_mesh_core_available()", pose_fallback_body)
        self.assertIn("native_core_disabled=bool(os.environ.get", pose_fallback_body)
        pose_clone_start = service_source.index("def _clone_mesh_for_service_native_snapshot(")
        pose_clone_body = service_source[
            pose_clone_start: service_source.index("def _service_session_native_clone_supported(", pose_clone_start)
        ]
        self.assertIn("native_snapshot = snapshot_native_mesh_submeshes(mesh)", pose_clone_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(restored_mesh, native_snapshot)", pose_clone_body)
        self.assertIn("dispose_native_mesh_submesh_snapshot(native_snapshot)", pose_clone_body)
        self.assertIn("_allow_python_service_clone_fallback(mesh, operation, reason)", pose_clone_body)
        native_pose_clone_body = pose_clone_body[pose_clone_body.index("native_snapshot = snapshot_native_mesh_submeshes(mesh)") :]
        self.assertLess(
            native_pose_clone_body.index("native_snapshot = snapshot_native_mesh_submeshes(mesh)"),
            native_pose_clone_body.index("clone_mesh_for_editing(mesh)"),
        )
        self.assertLess(
            native_pose_clone_body.index("_allow_python_service_clone_fallback(mesh, operation, reason)"),
            native_pose_clone_body.index("clone_mesh_for_editing(mesh)"),
        )
        self.assertIn('"preview.pose_clone"', pose_body)
        self.assertIn("native mesh editor pose preview unavailable; Python mesh state is stale", native_context_body)
        self.assertLess(
            native_context_body.index("if session.native_editor_mesh_dirty:"),
            native_context_body.index("return session.working_mesh, session.skeleton, pose_rotations"),
        )
        self.assertIn("return session.working_mesh, session.skeleton, pose_rotations", native_context_body)
        self.assertIn("def mesh_pose_to_native_preview(", payload_source)
        self.assertIn("write_native_pose_preview_geometry_blob(", payload_source)
        self.assertIn('if not _allow_python_preview_fallback(mesh, "preview.pose_geometry"', payload_source)
        self.assertIn('raise RuntimeError("native Mesh Editor pose preview geometry unavailable; Python preview fallback is disabled")', payload_source)
        self.assertIn("def pose_preview_native_context(", controller_source)
        self.assertIn("mesh_pose_to_native_preview(", controller_source)
        native_preview_start = controller_source.index("def native_preview_data(")
        native_preview_body = controller_source[
            native_preview_start: controller_source.index("def source_preview_data(", native_preview_start)
        ]
        self.assertIn("return mesh_pose_to_native_preview(", native_preview_body)
        pose_branch = native_preview_body[: native_preview_body.index("return mesh_to_native_preview(self.pose_preview_mesh())")]
        self.assertNotIn("self.pose_preview_mesh()", pose_branch)
        self.assertIn("def _standalone_pose_native_preview_context(", tab_source)
        sync_native_start = tab_source.index("def write_standalone_native_preview_package(")
        sync_native_body = tab_source[
            sync_native_start: tab_source.index("def load_standalone_native_preview_package", sync_native_start)
        ]
        self.assertIn("mesh_pose_to_native_preview(", sync_native_body)
        self.assertLess(
            sync_native_body.index("mesh_pose_to_native_preview("),
            sync_native_body.index("mesh = self._standalone_preview_mesh_snapshot()"),
        )

    def test_alignment_mesh_editor_texture_settings_and_view_mode_are_wired(self) -> None:
        source = (
            _mesh_edit_source()
            + "\n"
            + _read("cdmw/ui/archive_browser/preview_settings.py")
            + "\n"
            + _read("cdmw/ui/archive_browser/static_replacement_d3d11_cache.py")
        )

        self.assertIn("dialog.settings_changed.connect(settings_changed_handler)", source)
        self.assertIn("alignment_d3d11_view_mode_combo = QComboBox()", source)
        self.assertIn(
            "_d3d11_view_mode_options_helper(D3D11_PREVIEW_VIEW_MODES, D3D11_PREVIEW_VIEW_MODE_LABELS)",
            source,
        )
        self.assertIn("_populate_combo_options_helper(", source)
        self.assertIn("alignment_d3d11_view_mode_combo,", source)
        self.assertIn("(_state.alignment_d3d11_view_mode_combo, settings.d3d11_view_mode)", source)
        self.assertIn("alignment_d3d11_view_mode_combo.currentIndexChanged.connect(_apply_alignment_preview_render_settings)", source)
        self.assertIn("def _alignment_preview_render_settings_from_controls(", source)
        self.assertIn("settings.d3d11_view_mode = str(", source)
        self.assertIn('package_fields = (', source)
        self.assertIn('"use_textures_by_default"', source)
        self.assertIn('"high_quality_by_default"', source)
        self.assertIn("_state._alignment_d3d11_invalidate_package_cache('material')", source)
        self.assertIn("_state._mark_alignment_d3d11_rebuild_reason('material')", source)
        self.assertIn('bool(getattr(settings, "use_textures_by_default", True))', source)
        self.assertIn('bool(getattr(settings, "high_quality_by_default", True))', source)

    def test_mesh_edit_live_preview_uses_frozen_alignment_basis(self) -> None:
        main_source = _mesh_edit_source()
        replacer_source = "\n".join(
            (
                _read("cdmw/modding/static_mesh_replacer.py"),
                _read("cdmw/modding/static_mesh_runtime_builder.py"),
            )
        )

        self.assertIn("alignment_basis_mesh: ParsedMesh | None = None", replacer_source)
        self.assertIn("basis_mesh = alignment_basis_mesh or replacement_mesh", replacer_source)
        self.assertIn("alignment_replacement_mesh = copy.copy(basis_mesh)", replacer_source)
        self.assertIn("alignment_basis_mesh=_state.replacement_mesh_base_for_mapping if _state._mesh_edit_active_for_alignment_basis() else None", main_source)
        self.assertIn("replacement_mesh_base_for_mapping", main_source)

    def test_static_replacement_runtime_merge_routes_through_native_mesh_core_first(self) -> None:
        runtime_source = _read("cdmw/modding/static_mesh_runtime_builder.py")
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")

        merge_start = runtime_source.index("def _merge_source_submeshes(")
        merge_body = runtime_source[merge_start: runtime_source.index("def _atlas_rects_by_source_index(", merge_start)]
        self.assertIn("merge_native_mesh_submeshes(submeshes)", merge_body)
        self.assertLess(
            merge_body.index("merge_native_mesh_submeshes(submeshes)"),
            merge_body.index("merged.vertices.extend"),
        )
        self.assertIn("def merge_native_mesh_submeshes(", mesh_native_source)
        self.assertIn('"merge-submeshes-json"', mesh_native_source)
        self.assertIn("merge_submeshes_report_json", native_core_source)
        self.assertIn('"merge-submeshes-json"', native_core_source)
        native_merge_start = native_core_source.index("std::string merge_submeshes_report_json")
        native_merge_body = native_core_source[native_merge_start: native_core_source.index("std::string string_from_ufbx", native_merge_start)]
        self.assertIn("compute_smooth_normals(merged_vertices, merged_faces)", native_merge_body)
        self.assertIn("face[0] + base", native_merge_body)
        self.assertIn("write_vec3_binary_descriptor(out, vertices_path", native_merge_body)
        self.assertIn("write_int_binary_descriptor(out, faces_path", native_merge_body)

    def test_static_replacement_runtime_metadata_routes_through_native_mesh_core_first(self) -> None:
        runtime_source = _read("cdmw/modding/static_mesh_runtime_builder.py")
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")

        self.assertIn("def _mesh_metadata_for_submeshes(", runtime_source)
        metadata_start = runtime_source.index("def _mesh_metadata_for_submeshes(")
        metadata_body = runtime_source[metadata_start: runtime_source.index("def _replacement_mesh_with_original_part_copies(", metadata_start)]
        self.assertIn("summarize_native_mesh_submesh_metadata(submesh_list)", metadata_body)
        self.assertLess(
            metadata_body.index("summarize_native_mesh_submesh_metadata(submesh_list)"),
            metadata_body.index("all_vertices = [vertex for submesh in submesh_list for vertex in submesh.vertices]"),
        )
        replacement_start = runtime_source.index("def _replacement_mesh_with_original_part_copies(")
        replacement_body = runtime_source[replacement_start: runtime_source.index("def _build_mapped_replacement_mesh(", replacement_start)]
        self.assertIn("_mesh_metadata_for_submeshes(effective_mesh.submeshes)", replacement_body)
        self.assertNotIn("all_vertices = [vertex for submesh in effective_mesh.submeshes", replacement_body)
        mapped_start = runtime_source.index("def _build_mapped_replacement_mesh(")
        mapped_body = runtime_source[mapped_start: runtime_source.index("def _transformed_replacement_sources(", mapped_start)]
        self.assertIn("_mesh_metadata_for_submeshes(mapped_submeshes)", mapped_body)
        self.assertNotIn("all_vertices = [vertex for submesh in mapped_submeshes", mapped_body)
        delta_start = runtime_source.index("def _mesh_delta_bounds(")
        delta_body = runtime_source[delta_start: runtime_source.index("def _mesh_edit_forward_transformed_delta(", delta_start)]
        self.assertIn("_mesh_metadata_for_submeshes(submeshes)", delta_body)
        self.assertNotIn("vertices = [vertex for submesh in submeshes", delta_body)

        self.assertIn("def summarize_native_mesh_submesh_metadata(", mesh_native_source)
        self.assertIn('"mesh-metadata-json"', mesh_native_source)
        metadata_bridge_start = mesh_native_source.index("def summarize_native_mesh_submesh_metadata(")
        metadata_bridge_body = mesh_native_source[metadata_bridge_start: mesh_native_source.index("def merge_native_mesh_submeshes(", metadata_bridge_start)]
        self.assertIn('"vertices_binary"] = _write_vec3_binary_payload', metadata_bridge_body)
        self.assertIn('"face_count": len(faces)', metadata_bridge_body)
        self.assertNotIn("for submesh_index, submesh in enumerate(tuple(submeshes or ()))", metadata_bridge_body)
        self.assertNotIn('vertices = tuple(getattr(submesh, "vertices", ()) or ())', metadata_bridge_body)
        self.assertNotIn('"vertices": [_vec3_json', metadata_bridge_body)
        self.assertNotIn('"faces_binary"', metadata_bridge_body)

        self.assertIn("std::vector<SubmeshMetadataResult> run_mesh_metadata", native_core_source)
        self.assertIn("std::string mesh_metadata_report_json", native_core_source)
        self.assertIn('if (command == "mesh-metadata-json") return mesh_metadata_json_command(job_path, report_path);', native_core_source)

    def test_static_replacement_preview_bounds_routes_through_native_metadata_first(self) -> None:
        preview_source = _read("cdmw/ui/archive_browser/static_replacement_preview_models.py")
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")

        bounds_start = preview_source.index("def preview_submesh_bounds(")
        bounds_body = preview_source[bounds_start: preview_source.index("def parsed_preview_mesh_from_submeshes(", bounds_start)]
        self.assertIn("_preview_submesh_native_metadata(submesh_list)", bounds_body)
        self.assertLess(
            bounds_body.index("_preview_submesh_native_metadata(submesh_list)"),
            bounds_body.index("vertices = ["),
        )
        self.assertNotIn("for submesh in tuple(submeshes or ())", bounds_body)
        parsed_start = preview_source.index("def parsed_preview_mesh_from_submeshes(")
        parsed_body = preview_source[parsed_start: preview_source.index("def apply_missing_texture_overlay_color(", parsed_start)]
        self.assertIn("native_metadata = _preview_submesh_native_metadata(submesh_list)", parsed_body)
        self.assertIn("preview_submesh_bounds(submesh_list, native_metadata=native_metadata)", parsed_body)
        self.assertLess(
            parsed_body.index("native_metadata = _preview_submesh_native_metadata(submesh_list)"),
            parsed_body.index("sum(len(getattr(submesh, \"vertices\", ()) or ()) for submesh in submesh_list)"),
        )
        self.assertLess(
            parsed_body.index("_preview_submesh_metadata_count(native_metadata, \"total_faces\")"),
            parsed_body.index("sum(len(getattr(submesh, \"faces\", ()) or ()) for submesh in submesh_list)"),
        )
        self.assertLess(
            parsed_body.index('native_metadata.get("has_uvs")'),
            parsed_body.index("any(bool(getattr(submesh, \"uvs\", ()) or ()) for submesh in submesh_list)"),
        )

        self.assertIn("def summarize_native_mesh_submesh_metadata(", mesh_native_source)
        self.assertIn('"mesh-metadata-json"', mesh_native_source)
        self.assertIn("std::vector<SubmeshMetadataResult> run_mesh_metadata", native_core_source)
        self.assertIn('if (command == "mesh-metadata-json") return mesh_metadata_json_command(job_path, report_path);', native_core_source)

    def test_static_replacement_selection_region_amount_routes_through_native_bounds_first(self) -> None:
        state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")

        amount_start = state_source.index("def mesh_edit_selection_region_default_amount(")
        amount_body = state_source[amount_start: state_source.index("__all__", amount_start)]
        self.assertIn("_mesh_edit_native_selection_bounds(mesh, selected_vertices_by_source)", amount_body)
        self.assertLess(
            amount_body.index("_mesh_edit_native_selection_bounds(mesh, selected_vertices_by_source)"),
            amount_body.index("points = mesh_edit_selected_vertex_points(mesh, selected_vertices_by_source)"),
        )
        points_start = state_source.index("def mesh_edit_selected_vertex_points(")
        points_body = state_source[points_start: state_source.index("def _mesh_edit_native_selection_bounds(", points_start)]
        self.assertIn("_allow_python_selected_vertex_points_fallback(mesh, selected_vertices_by_source)", points_body)
        self.assertLess(
            points_body.index("_allow_python_selected_vertex_points_fallback(mesh, selected_vertices_by_source)"),
            points_body.index("mesh_edit_sorted_index_groups(selected_vertices_by_source, mesh=mesh)"),
        )
        self.assertNotIn('submesh_vertices = tuple(getattr(submesh, "vertices", ()) or ())', points_body)
        sorted_start = state_source.index("def mesh_edit_sorted_index_groups(")
        sorted_body = state_source[sorted_start: state_source.index("def mesh_edit_optional_sorted_indices(", sorted_start)]
        self.assertNotIn('len(tuple(getattr(mesh, "submeshes", ()) or ()))', sorted_body)
        self.assertNotIn("for raw_index in tuple(raw_indices or ())", sorted_body)
        reset_start = state_source.index("def mesh_edit_reset_scope_source_indices(")
        reset_body = state_source[reset_start: state_source.index("def mesh_edit_should_restore_deleted_output(", reset_start)]
        self.assertIn("raw_indices = range(base_count)", reset_body)
        self.assertNotIn("raw_indices = tuple(range(base_count))", reset_body)
        self.assertNotIn('len(tuple(getattr(working_mesh, "submeshes", ()) or ()))', reset_body)
        self.assertNotIn('len(tuple(getattr(base_mesh, "submeshes", ()) or ()))', reset_body)
        self.assertNotIn("_PYTHON_SELECTION_BOUNDS_FALLBACK_VERTEX_LIMIT", state_source)
        self.assertNotIn("large Python selected-vertex point fallback", state_source)
        self.assertIn("selection.vertex_points.blocked", state_source)
        self.assertIn("Python selected-vertex point fallback blocked while native mesh core is available", state_source)
        native_helper_start = state_source.index("def _mesh_edit_native_selection_bounds(")
        native_helper_body = state_source[native_helper_start: state_source.index("def mesh_edit_selection_region_default_amount(", native_helper_start)]
        self.assertIn("summarize_native_mesh_selection_bounds(mesh, selected_vertices_by_source)", native_helper_body)

        self.assertIn("def summarize_native_mesh_selection_bounds(", mesh_native_source)
        bounds_bridge_start = mesh_native_source.index("def summarize_native_mesh_selection_bounds(")
        bounds_bridge_body = mesh_native_source[bounds_bridge_start: mesh_native_source.index("def merge_native_mesh_submeshes(", bounds_bridge_start)]
        self.assertIn('"selection-bounds-json"', bounds_bridge_body)
        self.assertIn("_selected_vertex_values(raw_vertices, vertex_count)", bounds_bridge_body)
        self.assertIn("_put_selected_vertices_payload(item, prefix, selected", bounds_bridge_body)
        self.assertNotIn("dict(selected_vertices_by_submesh or {}).items()", bounds_bridge_body)
        self.assertNotIn("tuple(raw_vertices or ())", bounds_bridge_body)
        self.assertNotIn("selected = sorted(", bounds_bridge_body)
        self.assertIn("_ensure_native_mesh_session_submesh(", bounds_bridge_body)
        self.assertLess(
            bounds_bridge_body.index("_ensure_native_mesh_session_submesh("),
            bounds_bridge_body.index('"vertices_binary"] = _write_vec3_binary_payload'),
        )

        self.assertIn("std::vector<SubmeshSelectionBoundsResult> run_selection_bounds", native_core_source)
        self.assertIn("std::string selection_bounds_report_json", native_core_source)
        self.assertIn('if (command == "selection-bounds-json") return selection_bounds_json_command(job_path, report_path);', native_core_source)

    def test_static_replacement_source_transform_routes_through_native_affine_kernel_first(self) -> None:
        runtime_source = _read("cdmw/modding/static_mesh_runtime_builder.py")
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        geometry_math_source = _read("cdmw/ui/archive_browser/static_replacement_geometry_math.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")

        transform_start = runtime_source.index("def _transformed_replacement_sources(")
        transform_body = runtime_source[transform_start: runtime_source.index("def _mesh_delta_bounds(", transform_start)]
        self.assertIn("_apply_native_preview_decimation(", transform_body)
        self.assertLess(
            transform_body.index("_apply_native_preview_decimation("),
            transform_body.index("_decimate_submesh_for_preview(submesh, max_preview_faces)"),
        )
        preview_decimate_start = runtime_source.index("def _apply_native_preview_decimation(")
        preview_decimate_body = runtime_source[preview_decimate_start: runtime_source.index("def _apply_native_texture_uv_transforms(", preview_decimate_start)]
        self.assertIn("decimate_native_mesh_preview_submeshes(", preview_decimate_body)
        self.assertIn("_apply_native_texture_uv_transforms(", transform_body)
        self.assertIn("source_index in native_uv_transformed_indices", transform_body)
        self.assertLess(
            transform_body.index("_apply_native_texture_uv_transforms("),
            transform_body.index("_apply_texture_uv_transform(submesh, uv_transform)"),
        )
        uv_start = runtime_source.index("def _apply_native_texture_uv_transforms(")
        uv_body = runtime_source[uv_start: runtime_source.index("def _apply_native_source_part_adjustments(", uv_start)]
        self.assertIn("_texture_uv_transform_payload(", uv_body)
        self.assertIn("apply_native_mesh_uv_transform_submeshes(", uv_body)
        self.assertIn("_apply_native_source_part_adjustments(", transform_body)
        self.assertIn("source_index in native_adjusted_indices", transform_body)
        self.assertLess(
            transform_body.index("_apply_native_source_part_adjustments("),
            transform_body.index("_apply_source_part_adjustment(submesh, adjustment"),
        )
        self.assertNotIn("adjustment_pivots = {", transform_body)
        self.assertNotIn("_center(*_bbox(submesh.vertices))", transform_body)
        self.assertNotIn("all_vertices = [vertex for submesh in alignment_bound_sources", transform_body)
        self.assertIn("def fallback_global_transform_state()", transform_body)
        self.assertIn("_apply_native_global_source_transforms(", transform_body)
        self.assertIn("source_index in native_transformed_indices", transform_body)
        self.assertLess(
            transform_body.index("native_transformed_indices = _apply_native_global_source_transforms("),
            transform_body.index("alignment, fit_scale_xyz, fit_offset = fallback_global_transform_state()"),
        )
        self.assertLess(
            transform_body.index("_apply_native_global_source_transforms("),
            transform_body.index("_apply_transform(vertex, transform, fit_scale_xyz, fit_offset, alignment)"),
        )
        source_part_start = runtime_source.index("def _apply_native_source_part_adjustments(")
        source_part_body = runtime_source[source_part_start: runtime_source.index("def _apply_native_global_source_transforms(", source_part_start)]
        self.assertIn('"scale_xyz": tuple(adjustment.scale_xyz', source_part_body)
        self.assertIn('"pivot_vertices"', source_part_body)
        self.assertIn("adjustment_pivot_sources", source_part_body)
        self.assertIn("apply_native_mesh_affine_transform_submeshes(", source_part_body)
        self.assertIn("source_part_adjustments_by_index=native_adjustments", source_part_body)
        self.assertNotIn("_center(*_bbox", source_part_body)
        self.assertNotIn("_source_part_adjustment_matrices(", source_part_body)
        helper_start = runtime_source.index("def _apply_native_global_source_transforms(")
        helper_body = runtime_source[helper_start: runtime_source.index("def _mesh_delta_bounds(", helper_start)]
        self.assertIn("source_affine_for_transformed_preview(", helper_body)
        self.assertIn("source_normal_transform_for_transformed_preview(", helper_body)
        self.assertIn("apply_native_mesh_affine_transform_submeshes(", helper_body)
        mirror_start = geometry_math_source.index("def mirror_submesh_x(")
        mirror_body = geometry_math_source[mirror_start: geometry_math_source.index("def _mirror_submesh_x_native_clone(", mirror_start)]
        self.assertIn("_mirror_submesh_x_native_clone(source, plane_x)", mirror_body)
        self.assertLess(
            mirror_body.index("_mirror_submesh_x_native_clone(source, plane_x)"),
            mirror_body.index("mirrored = copy.deepcopy(source)"),
        )
        self.assertLess(
            mirror_body.index("mirrored = copy.deepcopy(source)"),
            mirror_body.index("mirrored.vertices = ["),
        )
        mirror_clone_start = geometry_math_source.index("def _mirror_submesh_x_native_clone(")
        mirror_clone_body = geometry_math_source[mirror_clone_start: geometry_math_source.index("def copy_source_part_with_adjustment(", mirror_clone_start)]
        self.assertIn("clone_native_mesh_affine_transformed_submesh(", mirror_clone_body)
        self.assertIn("position_matrix=position_matrix", mirror_clone_body)
        self.assertIn("normal_matrix=normal_matrix", mirror_clone_body)
        self.assertIn("reverse_face_winding=True", mirror_clone_body)
        self.assertNotIn("apply_native_mesh_affine_transform_submeshes", mirror_clone_body)
        copy_part_start = geometry_math_source.index("def copy_source_part_with_adjustment(")
        copy_part_body = geometry_math_source[copy_part_start: geometry_math_source.index("__all__", copy_part_start)]
        self.assertIn("_copy_source_part_with_adjustment_native_copy(", copy_part_body)
        self.assertIn("mirror_x_around_bounds_center", copy_part_body)
        self.assertLess(
            copy_part_body.index("_copy_source_part_with_adjustment_native_copy("),
            copy_part_body.index("copied = copy.deepcopy(source)"),
        )
        self.assertIn("_copy_source_part_with_adjustment_native(copied, adjustment)", copy_part_body)
        self.assertLess(
            copy_part_body.index("_copy_source_part_with_adjustment_native(copied, adjustment)"),
            copy_part_body.index("for vertex in vertices:"),
        )
        self.assertIn("source_part_adjustments_by_index={0: adjustment}", copy_part_body)
        self.assertIn("def clone_native_mesh_affine_transformed_submesh(", mesh_native_source)
        self.assertIn("def apply_native_mesh_affine_transform_submeshes(", mesh_native_source)
        self.assertIn("source_part_adjustments_by_index", mesh_native_source)
        self.assertIn('"source_part_adjustment"', mesh_native_source)
        self.assertIn('"pivot_vertices_binary"', mesh_native_source)
        self.assertIn('"mirror_x_around_bounds_center"', mesh_native_source)
        self.assertIn("reverse_face_winding_by_index", mesh_native_source)
        clone_bridge_start = mesh_native_source.index("def clone_native_mesh_affine_transformed_submesh(")
        clone_bridge_body = mesh_native_source[clone_bridge_start: mesh_native_source.index("def _native_selection_preview_group(", clone_bridge_start)]
        self.assertIn("position_matrix: Sequence[float] | None = None", clone_bridge_body)
        self.assertIn("normal_matrix: Sequence[float] | None = None", clone_bridge_body)
        self.assertIn("reverse_face_winding: bool = False", clone_bridge_body)
        self.assertIn('"position_matrix"', clone_bridge_body)
        self.assertIn('"normal_matrix"', clone_bridge_body)
        self.assertIn('"reverse_face_winding"', clone_bridge_body)
        self.assertIn('"faces_output_path"', mesh_native_source)
        self.assertIn("def apply_native_mesh_uv_transform_submeshes(", mesh_native_source)
        self.assertIn("def decimate_native_mesh_preview_submeshes(", mesh_native_source)
        self.assertIn('"preview-decimate-json"', mesh_native_source)
        decimate_bridge_start = mesh_native_source.index("def decimate_native_mesh_preview_submeshes(")
        decimate_bridge_body = mesh_native_source[decimate_bridge_start: mesh_native_source.index("def apply_native_mesh_affine_transform_submeshes(", decimate_bridge_start)]
        self.assertIn('"vertices_binary"', decimate_bridge_body)
        self.assertIn('"faces_binary"', decimate_bridge_body)
        self.assertIn("_write_bone_binary_payloads(", decimate_bridge_body)
        self.assertIn("_read_bone_binary_report_payloads(", decimate_bridge_body)
        self.assertNotIn("for submesh_index, submesh in enumerate(tuple(submeshes or ()))", decimate_bridge_body)
        self.assertNotIn('vertices = tuple(getattr(submesh, "vertices", ()) or ())', decimate_bridge_body)
        self.assertNotIn('for face in tuple(getattr(submesh, "faces", ()) or ())', decimate_bridge_body)
        affine_bridge_start = mesh_native_source.index("def apply_native_mesh_affine_transform_submeshes(")
        affine_bridge_body = mesh_native_source[affine_bridge_start: mesh_native_source.index("def clone_native_mesh_affine_transformed_submesh(", affine_bridge_start)]
        self.assertNotIn('vertices = tuple(getattr(submesh, "vertices", ()) or ())', affine_bridge_body)
        self.assertNotIn('faces = tuple(getattr(submesh, "faces", ()) or ())', affine_bridge_body)
        clone_bridge_body = mesh_native_source[clone_bridge_start: mesh_native_source.index("def _native_selection_preview_group(", clone_bridge_start)]
        self.assertNotIn('vertices = tuple(getattr(submesh, "vertices", ()) or ())', clone_bridge_body)
        self.assertNotIn('faces = tuple(getattr(submesh, "faces", ()) or ())', clone_bridge_body)
        self.assertNotIn('len(tuple(getattr(submesh, "faces", ()) or ()))', clone_bridge_body)
        i32_range_start = mesh_native_source.index("def _contiguous_i32_range(")
        i32_range_body = mesh_native_source[i32_range_start: mesh_native_source.index("def _is_identity_i32_sequence(", i32_range_start)]
        self.assertNotIn("items = tuple(int(value) for value in values)", i32_range_body)
        uv_submesh_start = mesh_native_source.index("def apply_native_mesh_uv_transform_submeshes(")
        uv_submesh_body = mesh_native_source[
            uv_submesh_start:mesh_native_source.index("def apply_native_mesh_uv_atlas_submesh(", uv_submesh_start)
        ]
        self.assertIn('"selected_all_vertices": True', uv_submesh_body)
        self.assertIn('"uv_transform": transform_payload', uv_submesh_body)
        self.assertNotIn('"selected_vertices_binary"', uv_submesh_body)
        atlas_start = runtime_source.index("def _rewrite_submesh_uvs_for_material_atlas(")
        atlas_body = runtime_source[atlas_start: runtime_source.index("def _build_removed_runtime_placeholder_submesh(", atlas_start)]
        self.assertIn("apply_native_mesh_uv_atlas_submesh(", atlas_body)
        self.assertLess(
            atlas_body.index("apply_native_mesh_uv_atlas_submesh("),
            atlas_body.index("for raw_u, raw_v in submesh.uvs:"),
        )
        self.assertIn("def apply_native_mesh_uv_atlas_submesh(", mesh_native_source)
        self.assertIn('"input_bounds_min": (-1.0e-4, -1.0e-4)', mesh_native_source)
        self.assertIn('"clamp_input_uv": True', mesh_native_source)
        self.assertIn('"affine-transform-json"', mesh_native_source)
        self.assertIn('"uv-transform-json"', mesh_native_source)
        self.assertIn("std::string preview_decimate_report_json", native_core_source)
        self.assertIn('"preview-decimate-json"', native_core_source)
        preview_decimate_native_start = native_core_source.index("std::vector<SubmeshPreviewDecimateResult> run_preview_decimate")
        preview_decimate_native_body = native_core_source[preview_decimate_native_start: native_core_source.index("std::string merge_submeshes_report_json", preview_decimate_native_start)]
        self.assertIn("copy_values_by_vertex_remap(uvs, source_remap)", preview_decimate_native_body)
        self.assertIn("copy_bones_by_vertex_remap(bones, source_remap)", preview_decimate_native_body)
        self.assertIn("source_vertex_map_binary", preview_decimate_native_body)
        self.assertIn("source_vertex_map_start", preview_decimate_native_body)
        self.assertIn("std::string affine_transform_report_json", native_core_source)
        self.assertIn('"affine-transform-json"', native_core_source)
        self.assertIn("source_part_adjustment_transform", native_core_source)
        self.assertIn("bounds_center_for_vertices", native_core_source)
        self.assertIn("pivot_vertices_binary", native_core_source)
        self.assertIn("bounds_center_for_vertices(pivot_vertices)", native_core_source)
        self.assertIn('const UvTransform transform = item.get("uv_transform")', native_core_source)
        self.assertIn("validate_input_bounds", native_core_source)
        self.assertIn("clamp_input_uv", native_core_source)
        self.assertIn("input UV outside allowed bounds", native_core_source)
        affine_start = native_core_source.index("std::string affine_transform_report_json")
        affine_body = native_core_source[affine_start: native_core_source.index("std::string string_from_ufbx", affine_start)]
        self.assertIn("position_matrix", affine_body)
        self.assertIn("source_part_adjustment", affine_body)
        self.assertIn("transform_vertex(vertex, source_part_transform)", affine_body)
        self.assertIn("normal_transform.rotate = source_part_transform.rotate", affine_body)
        self.assertIn("normal_matrix", affine_body)
        self.assertIn("write_vec3_binary_descriptor(out, vertices_path", affine_body)
        self.assertIn("normalized_vec3(", affine_body)
        self.assertIn("reverse_face_winding", affine_body)
        self.assertIn("faces_output_path", affine_body)
        self.assertIn("write_int_binary_descriptor(out, faces_path", affine_body)

    def test_mesh_edit_drag_inverts_preview_delta_without_display_space_rewrite(self) -> None:
        source = _mesh_edit_source()
        callback_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py")
        prompt_deps_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_deps_base.py")
        native_source = _read("native/cdmw_d3d11_preview/src/main.cpp")
        prep_source = _read("cdmw/rendering/model_preview_prepare.py")
        package_source = "\n".join(
            (
                _read("cdmw/rendering/native_preview_package.py"),
                _read("cdmw/rendering/native_preview_package_writer.py"),
            )
        )

        live_body = _function_source(source, "_mesh_edit_update_live_preview")
        self.assertIn("_callbacks._queue_mesh_edit_live_vertex_updates(", live_body)
        self.assertIn("include_normals=include_normals", live_body)
        self.assertIn("immediate=immediate", live_body)
        self.assertIn("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices())", live_body)
        self.assertNotIn("_mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())", live_body)
        self.assertLess(
            live_body.index("_callbacks._queue_mesh_edit_live_vertex_updates("),
            live_body.index("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices())"),
        )
        restore_body = _function_source(source, "_mesh_edit_restore_snapshot")
        self.assertIn(
            "_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices(), replace_all=True)",
            restore_body,
        )
        self.assertIn('_state.mesh_edit_preview_model_dirty["value"] = True', restore_body)
        self.assertLess(
            restore_body.index("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(_state._mesh_edit_preview_source_indices(), replace_all=True)"),
            restore_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        self.assertNotIn("_mesh_edit_replace_live_triangles(_mesh_edit_preview_source_indices())", restore_body)
        apply_body = _function_source(source, "_mesh_edit_apply_geometry_payload")
        finish_body = _function_source(source, "_mesh_edit_finish_geometry_stroke")
        self.assertIn('transform_screen_stroke = tool in {"move", "grab", "vertex"} and has_screen_drag', apply_body)
        self.assertIn('params["stroke_phase"] = "update" if transform_screen_stroke_started else "begin"', apply_body)
        self.assertIn('params["stroke_id"] = str(stroke_id)', apply_body)
        self.assertIn('_state.mesh_edit_active_stroke["native_transform_stroke_started"] = True', apply_body)
        self.assertIn('native_transform_stroke_started = bool(_state.mesh_edit_active_stroke.get("native_transform_stroke_started"))', finish_body)
        self.assertIn('stroke_phase="end"', finish_body)
        self.assertIn('stroke_id=str(stroke_id)', finish_body)
        self.assertIn('_state.mesh_edit_active_stroke["native_update_applied"] = True', apply_body)
        self.assertIn("apply_native_mesh_recalculate_normals(", finish_body)
        self.assertIn("return_changed_vertices=True", finish_body)
        self.assertIn('native_update_applied = bool(_state.mesh_edit_active_stroke.get("native_update_applied"))', finish_body)
        self.assertIn("if not native_update_applied:", finish_body)
        self.assertLess(
            finish_body.index("if not native_update_applied:"),
            finish_body.index("apply_native_mesh_recalculate_normals("),
        )
        self.assertIn("normal_changed_vertices_by_submesh = _callbacks._mesh_edit_changed_vertex_groups_for_live_update(native_normals or {})", finish_body)
        self.assertIn("def _mesh_edit_python_normal_fallback_allowed(", source)
        normal_fallback_body = _function_source(source, "_mesh_edit_python_normal_fallback_allowed")
        self.assertNotIn("_allow_python_normal_recompute_fallback", normal_fallback_body)
        self.assertNotIn("recompute_submesh_normals", normal_fallback_body)
        self.assertIn("Python normal fallback is disabled.", normal_fallback_body)
        self.assertIn("mesh_edit_python_normals_fallback_blocked", source)
        self.assertNotIn("recompute_submesh_normals", finish_body)
        self.assertNotIn("elif _mesh_edit_python_normal_fallback_allowed(", finish_body)
        self.assertIn("else:\n            _callbacks._mesh_edit_python_normal_fallback_allowed(", finish_body)
        self.assertIn("normal_changed_vertices_by_submesh\n            or _callbacks._mesh_edit_changed_vertex_groups_for_live_update", finish_body)
        self.assertNotIn("_mesh_edit_index_groups_as_sets_helper(native_normals or {})", finish_body)
        self.assertLess(
            finish_body.index("return_changed_vertices=True"),
            finish_body.index("else:\n            _callbacks._mesh_edit_python_normal_fallback_allowed("),
        )
        self.assertLess(
            finish_body.index("if native_update_applied:"),
            finish_body.index("_callbacks._mesh_edit_update_live_preview("),
        )
        self.assertIn('_state.mesh_edit_preview_model_dirty["value"] = True', finish_body)
        self.assertNotIn("recompute_mesh_normals(", finish_body)
        self.assertIn("def _mesh_edit_preview_delta_to_source_delta(", source)
        self.assertIn("def _mesh_edit_preview_point_to_source_point(", source)
        self.assertIn("def _mesh_edit_preview_distance_to_source_distance(", source)
        self.assertIn("_DEFAULT_INVERSE_TRANSFORM_HELPERS = {", source)
        self.assertIn("state._mesh_edit_has_inverse_transform_context_helper = (\n            state._default_mesh_edit_has_inverse_transform_context", source)
        self.assertNotIn("_mesh_edit_preview_to_source_point_helper", callback_source)
        self.assertNotIn("_mesh_edit_preview_to_source_vector_helper", callback_source)
        self.assertNotIn("_mesh_edit_preview_to_source_point_helper", prompt_deps_source)
        self.assertNotIn("_mesh_edit_preview_to_source_vector_helper", prompt_deps_source)
        self.assertNotIn("source_delta_for_transformed_delta", callback_source)
        self.assertNotIn("source_point_for_transformed_point", callback_source)
        self.assertNotIn("source_distance_for_transformed_distance", callback_source)
        self.assertNotIn("source_delta_for_transformed_delta", prompt_deps_source)
        self.assertNotIn("source_point_for_transformed_point", prompt_deps_source)
        self.assertNotIn("source_distance_for_transformed_distance", prompt_deps_source)
        self.assertNotIn("def _mesh_edit_inverse_transform_helper", callback_source)
        self.assertNotIn("def _mesh_edit_runtime_callback", callback_source)
        self.assertIn("def _mesh_edit_inverse_transform_disabled(_state, _callbacks, ) -> RuntimeError:", source)
        self.assertIn("raise _callbacks._mesh_edit_inverse_transform_disabled()", source)
        self.assertIn("def _mesh_edit_native_screen_selection_payload(", source)
        self.assertIn("def _mesh_edit_native_descriptor_selection_payload(", source)
        self.assertIn("native_screen_stroke = tool != \"remove\" and (", source)
        self.assertIn("native_descriptor_stroke = (bool(native_descriptor_groups) or native_screen_stroke)", source)
        self.assertIn('"native_screen_stroke": native_screen_stroke', source)
        self.assertIn('raw_screen_drag = payload.get("screen_drag")', apply_body)
        self.assertIn('raw_screen_brush = payload.get("screen_brush")', apply_body)
        self.assertIn('raw_screen_radius = payload.get("screen_radius")', apply_body)
        self.assertIn('if tool in {"move", "grab", "vertex"} and not has_screen_drag', apply_body)
        self.assertNotIn(
            "if not native_descriptor_groups and (has_screen_drag or has_screen_brush or has_screen_radius):",
            apply_body,
        )
        screen_start = apply_body.index("if has_screen_drag or has_screen_brush or has_screen_radius:")
        screen_body = apply_body[
            screen_start: apply_body.index('if tool in {"move", "grab", "vertex", "smooth", "inflate", "pinch"}:', screen_start)
        ]
        self.assertIn(
            "descriptor_selection_payload = _callbacks._mesh_edit_native_descriptor_selection_payload(native_descriptor_groups)",
            screen_body,
        )
        self.assertIn('params["screen_drag"] = _state._native_screen_payload(raw_screen_drag)', screen_body)
        self.assertIn('params["_native_screen_selection_payload"] = screen_selection_payload', screen_body)
        self.assertIn('params["_native_selection_payload"] = descriptor_selection_payload', screen_body)
        self.assertIn('params["screen_brush"] = _state._native_screen_payload(raw_screen_brush)', screen_body)
        self.assertIn('params["screen_radius"] = _state._native_screen_payload(raw_screen_radius)', screen_body)
        self.assertIn('params["target_mode"] = str(payload.get("target_mode") or "vertex")', screen_body)
        self.assertIn('params["selection_depth_mode"] = str(payload.get("selection_depth_mode") or "visible")', screen_body)
        self.assertIn('"transform"', screen_body)
        self.assertIn('"brush"', screen_body)
        self.assertIn("_callbacks._mesh_edit_changed_vertex_groups_for_live_update(result.changed_vertices_by_submesh or {})", screen_body)
        self.assertIn("_state._mesh_edit_cleanup_native_vertex_group_descriptors_helper(native_descriptor_groups)", screen_body)
        self.assertNotIn("_mesh_edit_preview_delta_to_source_delta", screen_body)
        self.assertNotIn("_mesh_edit_preview_point_to_source_point", screen_body)
        self.assertNotIn("_mesh_edit_preview_distance_to_source_distance", screen_body)
        fail_closed_index = apply_body.index('if tool in {"move", "grab", "vertex", "smooth", "inflate", "pinch"}:')
        self.assertLess(
            screen_start,
            fail_closed_index,
        )
        self.assertNotIn("source_delta = _mesh_edit_preview_delta_to_source_delta", apply_body)
        self.assertNotIn("source_step_delta = _mesh_edit_preview_delta_to_source_delta", apply_body)
        self.assertNotIn("source_center = _mesh_edit_preview_point_to_source_point", apply_body)
        self.assertNotIn("source_radius = _mesh_edit_preview_distance_to_source_distance", apply_body)
        self.assertNotIn("source_amount = _mesh_edit_preview_distance_to_source_distance", apply_body)
        self.assertNotIn('mesh_edit_active_stroke.pop("inverse_failed"', apply_body)
        self.assertIn(
            'if tool in {"move", "grab", "vertex", "smooth", "inflate", "pinch"}:\n'
            '        raise RuntimeError("native mesh edit stroke payload did not include native screen update data; Python inverse transform fallback is disabled")',
            apply_body,
        )
        self.assertNotIn("_mesh_edit_abort_inverse_stroke()", source)
        delta_body = _function_source(source, "_mesh_edit_preview_delta_to_source_delta")
        self.assertIn("raise _callbacks._mesh_edit_inverse_transform_disabled()", delta_body)
        self.assertNotIn("return delta", delta_body)
        self.assertNotIn("return None", delta_body)
        self.assertNotIn("_mesh_edit_runtime_callback", delta_body)
        self.assertNotIn("current_mappings = current_mappings_callback()", delta_body)
        self.assertNotIn("_current_static_alignment_transform(),", delta_body)
        self.assertNotIn("_current_source_part_adjustments(),", delta_body)
        self.assertNotIn("_current_dialog_mappings_for_preview()", delta_body)
        self.assertNotIn("apply_vertex_delta(", apply_body)
        self.assertNotIn("apply_brush_deformation(", apply_body)
        self.assertIn('"transform"', apply_body)
        self.assertIn('"brush"', apply_body)
        self.assertIn('"record_history": False', apply_body)
        self.assertIn('"recompute_normals": False', apply_body)
        self.assertIn("_callbacks._mesh_editor_remember_static_replacement_session_mesh()", apply_body)
        self.assertIn("def _mesh_edit_changed_vertices_for_source(", source)
        changed_helper_body = _function_source(source, "_mesh_edit_changed_vertex_range") + "\n" + _function_source(source, "_mesh_edit_changed_vertices_for_source")
        self.assertIn("-> object:", changed_helper_body)
        self.assertIn("def _mesh_edit_changed_vertex_range(_state, _callbacks, raw_vertices: object) -> range | None:", changed_helper_body)
        self.assertIn('("changed_vertex_start", "changed_vertex_count")', changed_helper_body)
        self.assertIn('("source_vertex_start", "source_vertex_count")', changed_helper_body)
        self.assertIn("compact_range = _callbacks._mesh_edit_changed_vertex_range(raw_vertices)", changed_helper_body)
        self.assertIn("if isinstance(raw_vertices, _state.Mapping):\n        return dict(raw_vertices)", changed_helper_body)
        self.assertNotIn("changed = _mesh_edit_changed_vertices_for_source(result.changed_vertices_by_submesh, source_submesh_index)", apply_body)
        self.assertNotIn("changed = set((result.changed_vertices_by_submesh or {}).get(source_submesh_index, set()))", apply_body)
        self.assertNotIn("tuple(changed or ())", apply_body)
        self.assertIn("changed_vertices_by_submesh: _state.Mapping[int, object] | None = None,", live_body)
        self.assertNotIn("changed_vertices_by_submesh: Mapping[int, Iterable[int]] | None,", live_body)
        source_space_allowed_body = _function_source(source, "_mesh_edit_source_space_live_update_allowed")
        affine_transform_body = _function_source(source, "_mesh_edit_affine_preview_transforms")
        self.assertNotIn("for source_index in tuple(source_indices or ())", source_space_allowed_body)
        self.assertNotIn("for source_index in tuple(source_indices or ())", affine_transform_body)
        self.assertIn("pending_live_vertices_by_submesh: _state.Dict[int, object] = {}", apply_body)
        self.assertIn("_state._mesh_edit_queue_live_vertex_updates_helper(pending_live_vertices_by_submesh, changed_by_submesh)", apply_body)
        self.assertIn("_state._mesh_edit_queue_live_vertex_updates_helper(stroke_changed_vertices, changed_by_submesh)", apply_body)
        self.assertNotIn("pending_live_vertices_by_submesh.setdefault(source_submesh_index, set()).update(changed)", apply_body)
        self.assertNotIn("stroke_changed_vertices.setdefault(source_submesh_index, set()).update(changed)", apply_body)
        self.assertNotIn("vertices_by_submesh={source_submesh_index: tuple(vertex_indices or ())}", apply_body)
        self.assertNotIn("mirror_pairs_by_submesh={source_submesh_index: mirror_pairs}", apply_body)
        self.assertNotIn("adjacency_by_submesh={source_submesh_index: adjacency}", apply_body)
        self.assertNotIn("center=source_center", apply_body)
        self.assertNotIn("radius=source_radius", apply_body)
        self.assertNotIn("amount=source_amount", apply_body)
        self.assertNotIn('delta=source_delta if tool in {"grab"} else source_step_delta', apply_body)
        self.assertNotIn("def _mesh_edit_apply_display_space_vertex_result(", source)
        self.assertNotIn("display_submesh = _mesh_edit_submesh_for_live_preview(source_submesh_index)", apply_body)
        self.assertIn("bool alignment_batch_editable(const PreviewBatch& batch) const {", native_source)
        self.assertIn("return !batch_is_reference(batch) && batch.editor_editable;", native_source)
        self.assertIn("if (!alignment_.enabled || view.role == PreviewViewRole::Reference) return;", native_source)
        self.assertIn('reference_role = "reference" in editor_role_key or "original" in editor_role_key', prep_source)
        self.assertIn("editor_editable = bool((mesh_source_submesh_index >= 0 or replacement_role) and not reference_role)", prep_source)
        self.assertIn('"editable": bool(getattr(batch, "editor_editable", source_submesh_index >= 0)) and not reference_role', package_source)
        self.assertIn("batch.editor_editable = false;", native_source)

    def test_native_mesh_edit_json_float_parser_accepts_exponent_numbers(self) -> None:
        source = _read("native/cdmw_d3d11_preview/src/main.cpp")

        self.assertGreaterEqual(source.count(r"(?:[eE][+-]?\\d+)?"), 3)

    def test_modify_original_material_preview_is_not_skipped_during_mesh_edit(self) -> None:
        source = _mesh_edit_source()

        refresh_body = _function_source(source, "_refresh_static_dialog_preview")
        static_preview_state = _read(
            "cdmw/ui/archive_browser/static_replacement_static_preview_state.py"
        )
        self.assertIn("needs_original_material_preview = _state._original_texture_preview_material_preview_enabled_helper(", refresh_body)
        self.assertIn("refresh_route.require_original_reference", refresh_body)
        self.assertIn("not mesh_edit_direct_source_preview or needs_original_material_preview", static_preview_state)
        self.assertIn("_state._apply_original_material_preview(", refresh_body)
        self.assertNotIn("if not mesh_edit_direct_source_preview:\n                        _apply_original_material_preview(", refresh_body)

    def test_active_mesh_edit_live_static_refresh_blocks_python_preview_rebuild(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py")

        refresh_body = _function_source(source, "_safe_refresh_static_dialog_preview")
        self.assertIn("if live_mesh_edit and _state._mesh_edit_tab_active():", refresh_body)
        self.assertIn("mesh_edit_static_preview_refresh_blocked", refresh_body)
        self.assertIn(
            "Active Mesh Editor static preview refresh requires native D3D11; Python preview rebuild fallback is disabled.",
            refresh_body,
        )
        self.assertLess(
            refresh_body.index("if live_mesh_edit and _state._mesh_edit_tab_active():"),
            refresh_body.index("_state._refresh_static_dialog_preview(live_mesh_edit=live_mesh_edit)"),
        )
        self.assertLess(
            refresh_body.index("return"),
            refresh_body.index("_state._refresh_static_dialog_preview(live_mesh_edit=live_mesh_edit)"),
        )

    def test_native_mesh_edit_commands_require_host_capability(self) -> None:
        source = _mesh_edit_source()

        helper_body = _function_source(source, "_alignment_d3d11_mesh_edit_commands_active")
        self.assertIn("_state._alignment_d3d11_preview_active()", helper_body)
        self.assertIn('callable(getattr(_state.alignment_d3d11_preview_host, "set_mesh_edit_state", None))', helper_body)
        self.assertIn('callable(getattr(_state.alignment_d3d11_preview_host, "update_mesh_edit_vertices", None))', helper_body)
        self.assertIn('callable(getattr(_state.alignment_d3d11_preview_host, "replace_mesh_edit_triangles", None))', helper_body)

        sync_body = _function_source(source, "_sync_mesh_edit_preview_settings")
        self.assertIn("if _callbacks._alignment_d3d11_mesh_edit_commands_active():", sync_body)
        self.assertLess(
            sync_body.index("if _callbacks._alignment_d3d11_mesh_edit_commands_active():"),
            sync_body.index("_state.alignment_d3d11_preview_host.set_mesh_edit_state("),
        )

        update_body = _function_source(source, "_mesh_edit_update_live_preview")
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        queue_start = payload_source.index("def mesh_edit_queue_live_vertex_updates(")
        queue_body = payload_source[queue_start: payload_source.index("def mesh_edit_live_vertex_update_groups(", queue_start)]
        self.assertIn("pending_vertices: MutableMapping[int, object]", queue_body)
        self.assertIn("if isinstance(raw_vertices, Mapping):", queue_body)
        self.assertIn("pending_vertices[source_index] = dict(raw_vertices)", queue_body)
        self.assertIn("compact_range = _compact_vertex_range(raw_vertices)", queue_body)
        self.assertIn("if compact_range.start == 0:", queue_body)
        self.assertIn("pending_vertices[source_index] = compact_range", queue_body)
        self.assertIn("if isinstance(existing, range) and existing.start == 0:", queue_body)
        self.assertIn("set(_nonnegative_indices(existing))", queue_body)
        self.assertIn("pending.update(_nonnegative_indices(raw_vertices))", queue_body)
        self.assertIn("def _nonnegative_indices(", payload_source)
        self.assertNotIn("tuple(raw_vertices or ())", queue_body)
        self.assertIn("def _compact_vertex_range(", payload_source)
        self.assertIn("def _full_vertex_range(", payload_source)
        native_live_start = payload_source.index("def mesh_edit_native_live_vertex_update_groups(")
        generated_live_start = payload_source.index("def _mesh_edit_generated_live_vertex_update_groups(")
        native_live_body = payload_source[
            native_live_start: generated_live_start
        ]
        generated_live_body = payload_source[
            generated_live_start: payload_source.index("def mesh_edit_triangle_replace_groups(", generated_live_start)
        ]
        self.assertIn("full_range = _full_vertex_range(raw_vertices)", native_live_body)
        self.assertIn("full_range is not None and full_range.stop == vertex_count", native_live_body)
        self.assertIn("native_count = _changed_vertex_input_count(raw_vertices, vertex_count)", native_live_body)
        self.assertIn("elif isinstance(raw_vertices, Mapping):", native_live_body)
        self.assertIn("missing_native[source_index] = raw_vertices if isinstance(raw_vertices, Mapping) else expected", native_live_body)
        self.assertIn("def _changed_vertex_input_count(", payload_source)
        self.assertIn('for descriptor_key in ("changed_vertices_binary", "source_vertex_indices_binary")', payload_source)
        self.assertIn("expected_count=native_count", native_live_body)
        self.assertLess(
            native_live_body.index("full_range = _full_vertex_range(raw_vertices)"),
            native_live_body.index("_source_vertex_indices(raw_vertices, vertex_count)"),
        )
        self.assertLess(
            native_live_body.index("expected_count=native_count"),
            native_live_body.index("_source_vertex_indices(raw_vertices, vertex_count)"),
        )
        self.assertIn("invalidate_native_mesh_session_submeshes", generated_live_body)
        self.assertIn("consume(build_native_mesh_preview_vertex_update_groups(mesh, requested))", generated_live_body)
        self.assertIn("missing = {source_index: requested[source_index] for source_index in requested if source_index not in result}", generated_live_body)
        self.assertIn("consume(build_native_mesh_preview_vertex_update_groups(mesh, missing))", generated_live_body)
        flush_body = _function_source(source, "_flush_mesh_edit_live_vertex_updates")
        self.assertIn('"mesh_edit_live_vertex_update_empty"', flush_body)
        self.assertIn("Native D3D11 mesh edit preview produced no vertex update payload; preview is stale.", flush_body)
        self.assertLess(
            flush_body.index("if not groups:"),
            flush_body.index("_state.alignment_d3d11_preview_host.update_mesh_edit_vertices(groups)"),
        )
        self.assertIn(
            "if changed_vertices_by_submesh and not immediate and _state._alignment_d3d11_preview_active():",
            update_body,
        )
        self.assertIn('"mesh_edit_live_preview_deferred"', update_body)
        self.assertIn("Native D3D11 mesh edit commands are unavailable; preview is stale.", update_body)
        self.assertIn("if _state._mesh_edit_tab_active():", update_body)
        self.assertIn("Active Mesh Editor live preview requires native D3D11", update_body)
        self.assertIn('"mesh_edit_live_preview_rebuild_blocked"', update_body)
        self.assertIn("def _native_screen_payload(", source)
        self.assertIn("_LEGACY_SCREEN_CAMERA_FIELDS", source)
        self.assertIn("params[\"screen_drag\"] = _state._native_screen_payload(raw_screen_drag)", source)
        self.assertIn("params[\"screen_brush\"] = _state._native_screen_payload(raw_screen_brush)", source)
        self.assertIn("params[\"screen_radius\"] = _state._native_screen_payload(raw_screen_radius)", source)
        self.assertIn("screen_payload[\"screen_region\"] = _state._native_screen_payload(raw_screen_region)", source)
        self.assertNotIn("params[\"screen_drag\"] = dict(raw_screen_drag)", source)
        self.assertNotIn("params[\"screen_brush\"] = dict(raw_screen_brush)", source)
        self.assertNotIn("params[\"screen_radius\"] = dict(raw_screen_radius)", source)
        self.assertNotIn("screen_payload[\"screen_region\"] = dict(raw_screen_region)", source)
        self.assertLess(
            update_body.index("if changed_vertices_by_submesh and not immediate"),
            update_body.index("_state._safe_refresh_static_dialog_preview(live_mesh_edit=True)"),
        )
        self.assertLess(
            update_body.index("if _state._alignment_d3d11_preview_active():"),
            update_body.index("_state._safe_refresh_static_dialog_preview(live_mesh_edit=True)"),
        )
        self.assertLess(
            update_body.index("if _state._mesh_edit_tab_active():"),
            update_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model()"),
        )

    def test_static_replacement_payload_builders_stream_source_inputs(self) -> None:
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")

        native_start = payload_source.index("def mesh_edit_payload_native_vertex_groups(")
        cleanup_start = payload_source.index("def mesh_edit_cleanup_native_vertex_group_descriptors(")
        vertex_start = payload_source.index("def mesh_edit_payload_vertex_groups(")
        selected_start = payload_source.index("def mesh_edit_payload_selected_indices(")
        edge_start = payload_source.index("def mesh_edit_payload_edge_groups(")
        requested_start = payload_source.index("def mesh_edit_requested_source_indices(")
        all_live_start = payload_source.index("def mesh_edit_all_live_vertices_for_sources(")
        queue_start = payload_source.index("def mesh_edit_queue_live_vertex_updates(")
        live_start = payload_source.index("def mesh_edit_live_vertex_update_groups(")
        native_live_start = payload_source.index("def mesh_edit_native_live_vertex_update_groups(")
        generated_live_start = payload_source.index("def _mesh_edit_generated_live_vertex_update_groups(")
        triangle_start = payload_source.index("def mesh_edit_triangle_replace_groups(")
        triangle_end = payload_source.index("def _triangle_group_has_geometry(", triangle_start)

        native_body = payload_source[native_start:cleanup_start]
        vertex_body = payload_source[vertex_start:selected_start]
        selected_body = payload_source[selected_start:edge_start]
        edge_body = payload_source[edge_start:requested_start]
        requested_body = payload_source[requested_start:all_live_start]
        all_live_body = payload_source[all_live_start:queue_start]
        live_body = payload_source[live_start:native_live_start]
        native_live_body = payload_source[native_live_start:generated_live_start]
        triangle_body = payload_source[triangle_start:triangle_end]

        for body in (
            native_body,
            vertex_body,
            selected_body,
            edge_body,
            requested_body,
            all_live_body,
            live_body,
            native_live_body,
            triangle_body,
        ):
            self.assertNotIn('submeshes = tuple(getattr(mesh, "submeshes", ()) or ())', body)
        self.assertNotIn("source_indices = tuple(source_indices_for_editor_id", native_body + vertex_body)
        self.assertNotIn("for raw_index in tuple(source_indices or ())", requested_body)
        self.assertNotIn('tuple(group.get("source_vertex_weights") or ())', payload_source)
        self.assertNotIn("tuple(raw_edge or ())", edge_body)
        self.assertNotIn("tuple(face or ())", triangle_body)
        self.assertNotIn("vertices = tuple(raw_vertex_values)", live_body + triangle_body)
        self.assertNotIn("normals = tuple(raw_normal_values)", live_body + triangle_body)
        self.assertNotIn("faces = tuple(raw_face_values)", triangle_body)
        self.assertIn('submeshes = getattr(mesh, "submeshes", ()) or ()', native_body)
        self.assertIn("source_indices = source_indices_for_editor_id(editor_submesh_index) or ()", native_body)
        self.assertIn("def _mesh_edit_source_vertex_range_descriptor(", payload_source)
        self.assertIn("_mesh_edit_source_vertex_range_descriptor(group, vertex_count)", native_body)
        self.assertIn('"type": "i32_range"', payload_source)

    def test_mesh_edit_inverse_transform_fallback_is_disabled(self) -> None:
        source = _mesh_edit_source()

        self.assertNotIn("mesh_edit_inverse_fallback_warnings", source)
        self.assertNotIn('f"mesh_edit_{kind}_inverse_fallback"', source)
        self.assertNotIn('f"mesh_edit_{kind}_inverse_error"', source)
        self.assertNotIn("mesh_edit_inverse_fallback_warnings.clear()", source)
        self.assertNotIn('mesh_edit_active_stroke["inverse_failed"] = True', source)
        self.assertIn("def _mesh_edit_inverse_transform_disabled(_state, _callbacks, ) -> RuntimeError:", source)

        delta_body = _function_source(source, "_mesh_edit_preview_delta_to_source_delta")
        self.assertIn("raise _callbacks._mesh_edit_inverse_transform_disabled()", delta_body)
        self.assertNotIn("return delta", delta_body)
        self.assertNotIn("return None", delta_body)

        point_body = _function_source(source, "_mesh_edit_preview_point_to_source_point")
        self.assertIn("raise _callbacks._mesh_edit_inverse_transform_disabled()", point_body)
        self.assertNotIn("return point", point_body)
        self.assertNotIn("return None", point_body)

        distance_body = _function_source(source, "_mesh_edit_preview_distance_to_source_distance")
        self.assertIn("raise _callbacks._mesh_edit_inverse_transform_disabled()", distance_body)
        self.assertNotIn("return abs(distance)", distance_body)
        self.assertNotIn("return None", distance_body)

        apply_body = _function_source(source, "_mesh_edit_apply_geometry_payload")
        self.assertNotIn('mesh_edit_active_stroke.pop("inverse_failed"', apply_body)
        self.assertIn("Python inverse transform fallback is disabled", apply_body)

    def test_mesh_edit_disables_native_alignment_transform(self) -> None:
        source = _mesh_edit_source()

        sync_body = _function_source(source, "_sync_mesh_edit_preview_settings")
        self.assertIn("_state._clear_alignment_d3d11_fast_transform_state()", sync_body)
        self.assertIn("_state.alignment_d3d11_preview_host.set_alignment_state(", sync_body)
        self.assertIn("enabled=False", sync_body)
        self.assertIn("_state.alignment_d3d11_preview_host.set_alignment_preview_transform()", sync_body)

        highlight_body = _function_source(source, "_sync_highlight_sets")
        self.assertIn("_state._selection_highlight_sets_state_helper(", highlight_body)
        self.assertIn("_state.mesh_edit_enabled_checkbox = _state.context.get('mesh_edit_enabled_checkbox')", source)
        self.assertIn("mesh_edit_raw_active=bool(_state._mesh_edit_raw_preview_active()) if d3d11_active else False", highlight_body)
        self.assertIn("preview_gizmo_checked=bool(_state.preview_gizmo_checkbox.isChecked()) if d3d11_active else False", highlight_body)
        self.assertIn("mesh_edit_active=bool(_state.mesh_edit_enabled_checkbox.isChecked()) if d3d11_active else False", highlight_body)
        self.assertIn("part_pick_checked=part_pick_checked", highlight_body)
        self.assertIn("enabled=bool(selection_state['d3d11_gizmo_enabled'])", highlight_body)

        replay_body = _function_source(source, "_replay_alignment_d3d11_fast_transform")
        self.assertIn("_state._alignment_d3d11_fast_transform_replay_state_helper(", replay_body)
        self.assertIn("raw_geometry_conflict = bool(_state._mesh_edit_raw_preview_active()) and package_quality == 'mesh_edit_raw'", replay_body)
        self.assertIn("mesh_edit_raw_active=raw_geometry_conflict", replay_body)
        self.assertIn("package_quality=package_quality", replay_body)
        self.assertIn("_state._clear_alignment_d3d11_fast_transform_state()", replay_body)
        self.assertIn("_state.alignment_d3d11_preview_host.set_alignment_preview_transform()", replay_body)

    def test_subdivide_selection_is_explicit_topology_path_not_sculpt_toggle(self) -> None:
        source = _mesh_edit_source()
        deformer_source = _read("cdmw/modding/mesh_deformer.py")
        mesh_native_source = _mesh_native_core_source()
        mesh_ops_source = _read("cdmw/modding/mesh_edit_ops.py")
        mesh_service_source = _read("cdmw/services/mesh_service.py")
        mesh_history_source = _read("cdmw/services/mesh_service_history.py")
        mesh_report_source = _read("cdmw/services/mesh_service_reports.py")
        mesh_controller_source = _read("cdmw/ui/mesh_editor/controller.py")
        static_adapter_source = _read("cdmw/ui/mesh_editor/static_replacement_adapter.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")
        mesh_edit_state_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_state.py")

        self.assertIn('"subdivide_selection": "Subdivide Selection"', mesh_edit_state_source)
        self.assertIn('"refine_smooth_selection": "Refine Smooth Selection"', mesh_edit_state_source)
        self.assertIn("_state.mesh_edit_subdivide_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['subdivide_selection'])", source)
        self.assertIn("_state.mesh_edit_refine_smooth_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['refine_smooth_selection'])", source)
        self.assertIn('"split_selection": "Split Selection To Part"', mesh_edit_state_source)
        self.assertIn("_state.mesh_edit_split_selection_button = _state.QPushButton(_state.mesh_edit_action_control_text['split_selection'])", source)
        self.assertIn("def _mesh_edit_subdivide_selection(_state, _callbacks, *, refine_smooth: bool = False) -> None:", source)
        self.assertIn("def _mesh_edit_split_selection_to_part(_state, _callbacks, ) -> None:", source)
        self.assertIn("mesh_edit_subdivide_selection_button.clicked.connect", source)
        self.assertIn("mesh_edit_refine_smooth_selection_button.clicked.connect", source)
        self.assertIn('"refine_smooth" if refine_smooth else "subdivide"', source)
        self.assertIn("faces_by_submesh=selected_faces", source)
        self.assertIn("mesh_edit_split_selection_button.clicked.connect", source)
        self.assertIn('if selection_mode not in {"vertex", "edge", "face"}:', source)
        self.assertIn("from cdmw.ui.mesh_editor.controller import apply_native_update_to_host", source)
        self.assertIn("from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession", source)
        self.assertNotIn("mesh_editor_apply_static_replacement_edit = context.get", source)
        self.assertNotIn("return apply_static_replacement_edit(mesh, action, **params)", source)
        self.assertIn("active static Mesh Editor edit requires a native session revision", source)
        self.assertIn("active static Mesh Editor edit requires a native session", source)
        self.assertIn("def _mesh_editor_apply_static_replacement_edit(_state, _callbacks, mesh, action: str, **params: object):", source)
        self.assertIn("def _mesh_editor_apply_native_update(_state, _callbacks, native_update: object) -> bool:", source)
        self.assertIn("return _state.apply_native_update_to_host(_state.alignment_d3d11_preview_host, native_update)", source)
        self.assertIn("mesh_editor_static_replacement_session_state", source)
        self.assertIn("StaticReplacementMeshEditSession(session_id=\"static-replacement\")", source)
        self.assertIn("_state.mesh_editor_static_replacement_session_state[\"revision\"] = current_revision + (1 if changed else 0)", source)
        result_body = static_adapter_source[
            static_adapter_source.index("    def _result("):
            static_adapter_source.index("def apply_static_replacement_edit(", static_adapter_source.index("    def _result("))
        ]
        self.assertNotIn("NATIVE_EDITOR_SESSION_COMMANDS", static_adapter_source)
        open_start = static_adapter_source.index("    def open(self, mesh: ParsedMesh) -> None:")
        open_body = static_adapter_source[open_start:static_adapter_source.index("    def close(self) -> None:", open_start)]
        self.assertIn("self.mesh = mesh", open_body)
        self.assertNotIn("self.controller.working_mesh(clone=False)", open_body)
        self.assertNotIn("self.controller.working_mesh(clone=False)", result_body)
        self.assertIn("Python working mesh hydration is disabled", result_body)
        self.assertNotIn("self.controller.working_mesh(clone=True)", result_body)
        self.assertNotIn("or _mesh_counts(mesh)", result_body)
        self.assertIn("after = edit_result.submesh_counts", result_body)
        self.assertIn("def _mesh_editor_fresh_static_replacement_session(_state, _callbacks, ):", source)
        self.assertIn("mesh_editor_session = _callbacks._mesh_editor_fresh_static_replacement_session()", source)
        self.assertIn("mesh_editor_session.view().undo_count > 0", source)
        self.assertIn("result = mesh_editor_session.undo()", source)
        self.assertIn("def _mesh_editor_result_has_deferred_native_python_apply(_state, _callbacks, result: object) -> bool:", source)
        self.assertIn('metrics.get("python_apply_deferred", 0.0)', source)
        self.assertIn("def _mesh_editor_store_result_mesh(_state, _callbacks, result: object", source)
        self.assertIn("mesh_edit_native_result_submesh_counts", source)
        self.assertIn("def _mesh_editor_result_submesh_counts(_state, _callbacks, result: object) -> tuple[tuple[int, int], ...]:", source)
        self.assertIn('_state.mesh_edit_native_result_submesh_counts["value"] = counts if _callbacks._mesh_editor_result_has_deferred_native_python_apply(result) else ()', source)
        update_totals_body = _function_source(source, "_mesh_edit_update_mesh_totals")
        self.assertLess(
            update_totals_body.index('native_counts = tuple(_state.mesh_edit_native_result_submesh_counts.get("value") or ())'),
            update_totals_body.index("totals = _state._mesh_edit_mesh_totals_helper("),
        )
        refresh_model_body = _function_source(source, "_mesh_edit_refresh_replacement_preview_model")
        self.assertLess(
            refresh_model_body.index('tuple(_state.mesh_edit_native_result_submesh_counts.get("value") or ())'),
            refresh_model_body.index("_state.parsed_mesh_to_preview_model("),
        )
        self.assertIn("Python preview rebuild fallback is disabled", refresh_model_body)
        self.assertIn("allow_defer_for_incremental_d3d11\n        and _state._mesh_edit_tab_active()\n        and _state._alignment_d3d11_preview_active()", refresh_model_body)
        self.assertLess(
            refresh_model_body.index("allow_defer_for_incremental_d3d11\n        and _state._mesh_edit_tab_active()\n        and _state._alignment_d3d11_preview_active()"),
            refresh_model_body.index("_state.parsed_mesh_to_preview_model("),
        )
        self.assertIn("def _mesh_edit_replace_result_working_mesh(_state, _callbacks, result: object) -> None:", source)
        self.assertIn("native deferred history result did not include preview payload", source)
        self.assertEqual(
            source.count("_mesh_edit_replace_result_working_mesh(result)"),
            2,
        )
        replace_working_body = _function_source(source, "_mesh_edit_replace_working_mesh")
        self.assertIn("native_update_applied = bool(", replace_working_body)
        self.assertLess(
            replace_working_body.index("_callbacks._mesh_editor_apply_native_update(native_update)"),
            replace_working_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        self.assertIn("if native_update_applied:", replace_working_body)
        self.assertIn("if not native_update_applied:", replace_working_body)
        mesh_edit_callback_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_mesh_edit_callbacks.py")
        self.assertNotIn("result.mesh", mesh_edit_callback_source)
        self.assertNotIn("compact_result.mesh", mesh_edit_callback_source)
        self.assertIn("mesh_editor_session.view().redo_count > 0", source)
        self.assertIn("result = mesh_editor_session.redo()", source)
        self.assertIn("_mesh_editor_remember_static_replacement_session_mesh()", source)
        delete_commit_body = _function_source(source, "_mesh_edit_commit_delete_result")
        self.assertIn("native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)", delete_commit_body)
        self.assertLess(
            delete_commit_body.index("_callbacks._mesh_editor_apply_result_native_update(result)"),
            delete_commit_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        self.assertIn("if not native_update_applied:", delete_commit_body)
        subdivide_commit_body = _function_source(source, "_mesh_edit_commit_subdivide_result")
        self.assertIn("native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)", subdivide_commit_body)
        self.assertLess(
            subdivide_commit_body.index("_callbacks._mesh_editor_apply_result_native_update(result)"),
            subdivide_commit_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        self.assertIn("if not native_update_applied:", subdivide_commit_body)
        self.assertIn('"split",', source)
        self.assertIn("def _mesh_edit_commit_split_result(_state, _callbacks, result: object) -> None:", source)
        split_commit_body = _function_source(source, "_mesh_edit_commit_split_result")
        split_body = _function_source(source, "_mesh_edit_split_selection_to_part")
        self.assertIn('_callbacks._mesh_edit_start_topology_worker(\n        "split",', split_body)
        self.assertIn('action_text="Split Selection To Part"', split_body)
        self.assertIn("commit_callback=_callbacks._mesh_edit_commit_split_result", split_body)
        self.assertLess(
            split_body.index('_callbacks._mesh_edit_start_topology_worker(\n        "split",'),
            split_body.index("_callbacks._mesh_edit_record_snapshot()"),
        )
        self.assertIn("native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)", split_commit_body)
        self.assertIn("if not native_update_applied:", split_commit_body)
        self.assertIn("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild((source_index, new_source_index))", split_commit_body)
        self.assertIn("_state.alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", split_commit_body)
        self.assertIn("_state.appended_source_indices.add(new_source_index)", split_commit_body)
        self.assertIn('_state.selected_source_part["index"] = new_source_index', split_commit_body)
        self.assertNotIn("source_part_adjustments[new_source_index]", split_commit_body)
        self.assertNotIn("deepcopy(source_adjustment)", split_commit_body)
        self.assertLess(
            split_commit_body.index("if _state._alignment_d3d11_preview_active():"),
            split_commit_body.index("_callbacks._mesh_editor_apply_result_native_update(result)"),
        )
        self.assertLess(
            split_commit_body.index("_callbacks._mesh_editor_apply_result_native_update(result)"),
            split_commit_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        action_result_body = _function_source(source, "_mesh_editor_commit_action_bar_service_result")
        sync_new_source_body = _function_source(source, "_mesh_editor_sync_new_source_part")
        self.assertIn("appended_source_indices.add(new_source_index)", sync_new_source_body)
        self.assertIn('selected_source_part["index"] = new_indices[0]', sync_new_source_body)
        self.assertNotIn("source_part_adjustments[new_source_index]", sync_new_source_body)
        self.assertNotIn("deepcopy(source_adjustment)", sync_new_source_body)
        self.assertIn("native_update_applied = _callbacks._mesh_editor_apply_result_native_update(result)", action_result_body)
        self.assertIn("if not native_update_applied:", action_result_body)
        self.assertLess(
            action_result_body.index("_callbacks._mesh_editor_apply_result_native_update(result)"),
            action_result_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        self.assertLess(
            action_result_body.index("_callbacks._mesh_editor_apply_result_native_update(result)"),
            action_result_body.index("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild("),
        )
        commit_working_body = _function_source(source, "_mesh_edit_commit_working_mesh")
        refresh_preview_body = _function_source(source, "_mesh_edit_refresh_replacement_preview_model")
        self.assertIn("Active Mesh Editor preview refresh requires native D3D11", refresh_preview_body)
        self.assertLess(
            refresh_preview_body.index("and _state._mesh_edit_tab_active()"),
            refresh_preview_body.index("_state.parsed_mesh_to_preview_model("),
        )
        self.assertIn("native_result: object | None = None", commit_working_body)
        self.assertLess(
            commit_working_body.index("_callbacks._mesh_editor_apply_result_native_update(native_result)"),
            commit_working_body.index("_callbacks._mesh_edit_update_mesh_totals()"),
        )
        self.assertLess(
            commit_working_body.index("_callbacks._mesh_editor_apply_result_native_update(native_result)"),
            commit_working_body.index("_callbacks._mesh_edit_refresh_replacement_preview_model(allow_defer_for_incremental_d3d11=True)"),
        )
        self.assertIn("if not native_update_applied:", commit_working_body)
        self.assertIn("Active Mesh Editor commit requires native D3D11 refresh", commit_working_body)
        active_no_d3d_commit_start = commit_working_body.index("elif _state._mesh_edit_tab_active():")
        active_no_d3d_commit_body = commit_working_body[
            active_no_d3d_commit_start:commit_working_body.index("else:", active_no_d3d_commit_start)
        ]
        self.assertNotIn("_queue_static_preview_rebuild()", active_no_d3d_commit_body)
        self.assertLess(
            commit_working_body.index("_callbacks._mesh_editor_apply_result_native_update(native_result)"),
            commit_working_body.index("_callbacks._mesh_edit_replace_live_triangles_or_queue_rebuild(topology_source_indices)"),
        )
        apply_payload_body = "\n".join(
            (
                _function_source(source, "_mesh_edit_apply_preview_payload"),
                _function_source(source, "_mesh_edit_apply_geometry_payload"),
                _function_source(source, "_mesh_edit_apply_remove_payload"),
            )
        )
        self.assertGreaterEqual(apply_payload_body.count("_mesh_editor_apply_result_native_update(result)"), 3)
        self.assertLess(
            apply_payload_body.index("_mesh_editor_apply_result_native_update(result)"),
            apply_payload_body.index("_mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)"),
        )
        self.assertIn("_mesh_edit_replace_live_triangles_or_queue_rebuild(result.affected_submesh_indices)", source)
        self.assertIn("topology_source_indices=result.affected_submesh_indices", source)
        self.assertNotIn("affected_sources = tuple(result.affected_submesh_indices)", source)
        self.assertIn("_queue_static_preview_rebuild()", source)
        self.assertIn("from cdmw.ui.mesh_editor.native_preview_payloads import mesh_edit_selection_groups", source)
        self.assertIn("def _mesh_edit_current_selection(_state, _callbacks, ) -> _state.MeshEditSelection:", source)
        self.assertIn("def _mesh_edit_sync_d3d11_selection(_state, _callbacks, ) -> bool:", source)
        selection_sync_body = _function_source(source, "_mesh_edit_sync_d3d11_selection")
        self.assertIn('getattr(_state.alignment_d3d11_preview_host, "set_mesh_edit_selection_groups", None)', selection_sync_body)
        self.assertIn("selection = _callbacks._mesh_edit_current_selection()", selection_sync_body)
        self.assertIn("groups = _state.mesh_edit_selection_groups(", selection_sync_body)
        self.assertIn("selection,", selection_sync_body)
        self.assertNotIn("allow_python_fallback=True", selection_sync_body)
        self.assertIn('"mesh_edit_selection_group_update_unavailable"', selection_sync_body)
        self.assertIn('"mesh_edit_selection_group_build_failed"', selection_sync_body)
        self.assertIn('if not groups and not selection.is_empty():', selection_sync_body)
        self.assertIn('"mesh_edit_selection_group_build_empty"', selection_sync_body)
        self.assertIn('"mesh_edit_selection_group_update_failed"', selection_sync_body)
        self.assertIn("return False", selection_sync_body)
        self.assertNotIn('getattr(_state.alignment_d3d11_preview_host, "set_mesh_edit_vertex_selection", None)', selection_sync_body)
        source_selection_body = _function_source(source, "_mesh_edit_set_source_selection")
        self.assertIn("if not d3d11_synced and not _state._alignment_d3d11_preview_active():", source_selection_body)
        self.assertLess(
            selection_sync_body.index("groups = _state.mesh_edit_selection_groups("),
            selection_sync_body.index('"mesh_edit_selection_group_update_failed"'),
        )
        self.assertIn("_mesh_edit_sync_d3d11_selection()", source)
        self.assertNotIn("mesh_edit_detail_refine_checkbox", source)
        self.assertNotIn("def _mesh_edit_refine_detail_for_payload(", source)
        self.assertNotIn('"detail_refined_sources": set()', source)
        self.assertIn("class MeshSubdivisionResult", deformer_source)
        self.assertIn("def subdivide_faces_touching_vertices(", deformer_source)
        self.assertIn("def apply_native_mesh_split(", mesh_native_source)
        self.assertIn('"operation": "split"', mesh_native_source)
        self.assertIn("selected_edges_by_submesh", mesh_native_source)
        self.assertIn('"selected_edges"', mesh_native_source)
        self.assertIn('"selected_all_faces"', mesh_native_source)
        self.assertIn("def _recompute_normals_native_or_fallback(", mesh_native_source)
        self.assertIn("apply_native_mesh_recalculate_normals(mesh, submesh_indices", mesh_native_source)
        normal_fallback_start = mesh_native_source.index("def _allow_python_normal_recompute_fallback(")
        normal_fallback_body = mesh_native_source[
            normal_fallback_start: mesh_native_source.index("def apply_native_mesh_recalculate_normals(", normal_fallback_start)
        ]
        self.assertNotIn("_PYTHON_NORMAL_FALLBACK_VERTEX_LIMIT", mesh_native_source)
        self.assertNotIn("_PYTHON_NORMAL_FALLBACK_FACE_LIMIT", mesh_native_source)
        self.assertIn('"normals.recalculate.blocked"', normal_fallback_body)
        self.assertIn("Python normal recompute fallback blocked while native mesh core is available", normal_fallback_body)
        self.assertLess(
            normal_fallback_body.index('"normals.recalculate.blocked"'),
            normal_fallback_body.index("recompute_submesh_normals(mesh.submeshes[submesh_index])"),
        )
        self.assertIn("return_changed_vertices: bool = False", mesh_native_source)
        self.assertIn("def apply_native_mesh_weighted_normals(", mesh_native_source)
        self.assertIn("def apply_native_mesh_flip_normals(", mesh_native_source)
        self.assertIn('operation="weighted_normals"', mesh_native_source)
        self.assertIn('operation="flip_normals"', mesh_native_source)
        self.assertIn('"normals_binary"', mesh_native_source)
        self.assertIn("\"recalculate-normals-json\"", mesh_native_source)
        self.assertIn("cdmw_mesh_core_normals_", mesh_native_source)
        normal_start = mesh_native_source.index("def _apply_native_mesh_normal_edit(")
        normal_body = mesh_native_source[normal_start: mesh_native_source.index("def native_mesh_auto_uv_report(", normal_start)]
        self.assertIn("_ensure_native_mesh_session_submesh(", normal_body)
        self.assertIn('item["session_id"] = session_id', normal_body)
        self.assertIn("face_count = len(submesh.faces or ())", normal_body)
        self.assertLess(
            normal_body.index("_ensure_native_mesh_session_submesh("),
            normal_body.index("faces = _face_json("),
        )
        self.assertIn('item["vertices_binary"] = _write_vec3_binary_payload', normal_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', normal_body)
        self.assertIn("_put_i32_range_or_binary_payload(", normal_body)
        self.assertIn('start_key="selected_face_start"', normal_body)
        self.assertIn('binary_key="selected_faces_binary"', normal_body)
        self.assertIn('item["normals_output_path"] = _native_preview_delta_output_path("_normals.bin")', normal_body)
        self.assertIn('item["changed_vertices_output_path"] = _native_preview_delta_output_path("_changed_vertices.bin")', normal_body)
        self.assertIn('item["faces_output_path"] = _native_preview_delta_output_path("_faces.bin")', normal_body)
        self.assertIn('item["preview_vertex_output_path"] = _native_preview_delta_output_path("_normal_vertices.bin")', normal_body)
        self.assertIn("_mark_native_mesh_session_submeshes_current(mesh, submesh_indices)", normal_body)
        apply_normals_start = mesh_native_source.index("def _apply_recalculate_normals_report(")
        apply_normals_body = mesh_native_source[
            apply_normals_start: mesh_native_source.index("def _apply_generate_tangents_report(", apply_normals_start)
        ]
        self.assertIn("def _read_face_binary_report_payload(", mesh_native_source)
        face_reader_start = mesh_native_source.index("def _read_face_binary_report_payload(")
        face_reader_body = mesh_native_source[face_reader_start: mesh_native_source.index("def _read_int_binary_report_payload(", face_reader_start)]
        self.assertIn("Face = tuple[int, int, int]", mesh_native_source)
        self.assertIn(") -> list[Face] | None:", face_reader_body)
        self.assertIn('faces = list(struct.iter_unpack("=iii", raw))', face_reader_body)
        self.assertNotIn("face = [", face_reader_body)
        self.assertIn("def _read_int_binary_report_payload(", mesh_native_source)
        self.assertIn("parsed_normals = _read_vec3_binary_report_payload(", apply_normals_body)
        self.assertIn('item.get("normals_binary")', apply_normals_body)
        self.assertIn("parsed_faces = _read_face_binary_report_payload(", apply_normals_body)
        self.assertIn('faces_binary = item.get("faces_binary")', apply_normals_body)
        self.assertIn("def _changed_vertices_from_report_item(", mesh_native_source)
        self.assertIn('raw_changed_binary = item.get("changed_vertices_binary")', mesh_native_source)
        self.assertIn('"changed_vertex_start" in item or "changed_vertex_count" in item', mesh_native_source)
        self.assertIn("parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_normals))", apply_normals_body)
        self.assertIn("has_native_changed_vertices = parsed_changed_ordered is not None", apply_normals_body)
        self.assertIn("before_normals = () if has_native_changed_vertices else", apply_normals_body)
        self.assertLess(
            apply_normals_body.index("parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_normals))"),
            apply_normals_body.index("before_normals = () if has_native_changed_vertices else"),
        )
        self.assertLess(
            apply_normals_body.index("if has_native_changed_vertices:"),
            apply_normals_body.index("elif normals_changed:"),
        )
        self.assertIn("mesh_normals_from_item(item)", native_core_source)
        self.assertIn("mesh_faces_from_item(item, vertices.size())", native_core_source)
        self.assertIn('result.normals_path = string_or(item.get("normals_output_path"), "")', native_core_source)
        self.assertIn('result.faces_path = string_or(item.get("faces_output_path"), "")', native_core_source)
        self.assertIn('result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "")', native_core_source)
        self.assertIn('result.preview_vertex_path = string_or(item.get("preview_vertex_output_path"), "")', native_core_source)
        self.assertIn("mutable_mesh_session_submesh_for_item(item)", native_core_source)
        self.assertIn("compute_weighted_normals", native_core_source)
        self.assertIn('operation == "weighted_normals"', native_core_source)
        self.assertIn('operation == "flip_normals"', native_core_source)
        self.assertIn("result.faces = faces", native_core_source)
        self.assertIn("std::swap(result.faces", native_core_source)
        self.assertIn("result.changed_vertices.push_back", native_core_source)
        normals_report_start = native_core_source.index("std::string normals_report_json(")
        normals_report_body = native_core_source[normals_report_start: native_core_source.index("std::string tangents_report_json", normals_report_start)]
        self.assertIn("write_vec3_binary_file(result.normals_path, result.normals)", normals_report_body)
        self.assertIn("write_vec3_binary_descriptor(out, result.normals_path, result.normals.size())", normals_report_body)
        self.assertIn("write_int_binary_file(result.faces_path, flat_faces)", normals_report_body)
        self.assertIn("write_int_binary_descriptor(out, result.faces_path, result.faces.size(), 3)", normals_report_body)
        self.assertIn("void write_changed_vertices_report(", native_core_source)
        self.assertIn('out << ",\\"changed_vertex_start\\":0,\\"changed_vertex_count\\":0";', native_core_source)
        self.assertIn('out << ",\\"changed_vertex_start\\":" << changed_vertex_start', native_core_source)
        self.assertIn("write_int_binary_file(changed_vertices_path, changed_vertices)", native_core_source)
        self.assertIn("write_int_binary_descriptor(out, changed_vertices_path, changed_vertices.size(), 1)", native_core_source)
        self.assertIn("write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start)", normals_report_body)
        self.assertLess(
            normals_report_body.index("write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start)"),
            normals_report_body.index("if (!result.changed_vertices.empty())"),
        )
        self.assertNotIn("if (!result.changed_vertices.empty()) {\n            if (!result.changed_vertices_path.empty())", normals_report_body)
        self.assertIn("preview_vertex_update_group", normals_report_body)
        self.assertIn("write_vec3_binary_file(result.preview_vertex_path, changed_positions)", normals_report_body)
        self.assertIn("write_sparse_preview_vertex_update_group(", normals_report_body)
        self.assertIn("changed_vertex_start", normals_report_body)
        self.assertIn("write_preview_vertex_update_group(", normals_report_body)
        self.assertIn('"changed_vertices"', mesh_native_source)
        self.assertIn('item.get("preview_vertex_update_group")', mesh_native_source)
        tangents_start = mesh_native_source.index("def apply_native_mesh_generate_tangents(")
        tangents_body = mesh_native_source[
            tangents_start: mesh_native_source.index("def apply_native_mesh_remove_doubles(", tangents_start)
        ]
        self.assertIn("_ensure_native_mesh_session_submesh(", tangents_body)
        self.assertIn('item["session_id"] = session_id', tangents_body)
        self.assertIn('item["vertices_binary"] = _write_vec3_binary_payload', tangents_body)
        self.assertIn('item["uvs_binary"] = _write_vec2_binary_payload', tangents_body)
        self.assertIn('item["faces_binary"] = _write_face_binary_payload', tangents_body)
        self.assertLess(
            tangents_body.index("_ensure_native_mesh_session_submesh("),
            tangents_body.index("faces = _face_json("),
        )
        self.assertIn('"_generated_vertices.bin"', tangents_body)
        self.assertIn('"_generated_faces.bin"', tangents_body)
        self.assertIn('"_generated_uvs.bin"', tangents_body)
        self.assertIn('"_generated_normals.bin"', tangents_body)
        self.assertIn('"_generated_tangents.bin"', tangents_body)
        self.assertIn('"_generated_tangent_signs.bin"', tangents_body)
        self.assertIn('"_generated_changed_vertices.bin"', tangents_body)
        self.assertIn('"tangents_output_path": _native_preview_delta_output_path', tangents_body)
        self.assertIn('"changed_vertices_output_path": _native_preview_delta_output_path', tangents_body)
        self.assertIn('item["bone_counts_output_path"] = _native_preview_delta_output_path("_generated_bone_counts.bin")', tangents_body)
        self.assertIn('item["source_vertex_map_output_path"] = _native_preview_delta_output_path("_generated_source_vertex_map.bin")', tangents_body)
        self.assertIn("_put_source_vertex_map_payload(item, prefix", tangents_body)
        self.assertIn('item["source_vertex_offsets_output_path"] = _native_preview_delta_output_path("_generated_source_vertex_offsets.bin")', tangents_body)
        self.assertIn("_put_source_vertex_offsets_payload(item, prefix", tangents_body)
        self.assertIn('item["normals_binary"] = _write_vec3_binary_payload', tangents_body)
        self.assertIn('item["tangents_binary"] = _write_vec3_binary_payload', tangents_body)
        self.assertNotIn('"vertices": [_vec3_json(vertex) for vertex in submesh.vertices]', tangents_body)
        self.assertNotIn('"uvs": [_vec2_json(uv) for uv in submesh.uvs]', tangents_body)
        self.assertNotIn('"faces": faces', tangents_body)
        apply_tangents_start = mesh_native_source.index("def _apply_generate_tangents_report(")
        apply_tangents_body = mesh_native_source[
            apply_tangents_start: mesh_native_source.index("def _tangent_face_corner_report(", apply_tangents_start)
        ]
        self.assertIn("_apply_native_tangent_split_result(submesh, item)", apply_tangents_body)
        self.assertIn("def _apply_native_tangent_split_result(", mesh_native_source)
        self.assertIn('item.get("topology_split_applied")', mesh_native_source)
        self.assertIn('item.get("vertices_binary")', mesh_native_source)
        self.assertIn('item.get("tangent_signs_binary")', mesh_native_source)
        self.assertIn("_read_bone_binary_report_payloads(", mesh_native_source)
        self.assertIn('item.get("source_vertex_map_binary")', mesh_native_source)
        self.assertIn('raw_tangents_binary = item.get("tangents_binary")', apply_tangents_body)
        self.assertIn("_read_vec3_binary_report_payload(raw_tangents_binary", apply_tangents_body)
        self.assertIn("parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_tangents))", apply_tangents_body)
        self.assertIn("has_native_changed_vertices = parsed_changed_ordered is not None", apply_tangents_body)
        self.assertIn("before = () if has_native_changed_vertices else", apply_tangents_body)
        self.assertLess(
            apply_tangents_body.index("parsed_changed_ordered = _changed_vertices_from_report_item(item, len(parsed_tangents))"),
            apply_tangents_body.index("before = () if has_native_changed_vertices else"),
        )
        tangents_native_start = native_core_source.index("std::vector<SubmeshTangentsResult> run_generate_tangents")
        tangents_native_body = native_core_source[
            tangents_native_start: native_core_source.index("void write_flat_vec3_for_indices", tangents_native_start)
        ]
        self.assertIn("mesh_vertices_from_item(item)", tangents_native_body)
        self.assertIn("mesh_uvs_from_item(item)", tangents_native_body)
        self.assertIn("mesh_normals_from_item(item)", tangents_native_body)
        self.assertIn("mesh_tangents_from_item(item)", tangents_native_body)
        self.assertIn("mesh_faces_from_item(item, vertices.size())", tangents_native_body)
        self.assertIn('result.vertices_path = string_or(item.get("vertices_output_path"), "")', tangents_native_body)
        self.assertIn('result.tangents_path = string_or(item.get("tangents_output_path"), "")', tangents_native_body)
        self.assertIn('result.changed_vertices_path = string_or(item.get("changed_vertices_output_path"), "")', tangents_native_body)
        self.assertIn("result.changed_vertices.push_back", tangents_native_body)
        self.assertIn("build_tangent_split_result(item, vertices, uvs, normals, faces, build, result)", tangents_native_body)
        self.assertNotIn('vertices_from_binary_or_json(item, "vertices_binary", "vertices")', tangents_native_body)
        self.assertNotIn("vertices_from_json(item.get(\"vertices\"))", tangents_native_body)
        self.assertNotIn("uvs_from_json(item.get(\"uvs\"))", tangents_native_body)
        tangent_split_start = native_core_source.index("bool build_tangent_split_result(")
        tangent_split_body = native_core_source[tangent_split_start:tangents_native_start]
        self.assertIn("source_vertex_map = session->source_vertex_map", tangent_split_body)
        self.assertIn("source_vertex_offsets = session->source_vertex_offsets", tangent_split_body)
        tangents_report_start = native_core_source.index("std::string tangents_report_json(")
        tangents_report_body = native_core_source[
            tangents_report_start: native_core_source.index("std::string cleanup_report_json(", tangents_report_start)
        ]
        self.assertIn("if (result.topology_split_applied)", tangents_report_body)
        self.assertIn("write_vec3_binary_file(result.vertices_path, result.vertices)", tangents_report_body)
        self.assertIn("write_faces_binary_file(result.faces_path, result.faces)", tangents_report_body)
        self.assertIn("write_vec2_binary_file(result.uvs_path, result.uvs)", tangents_report_body)
        self.assertIn("write_double_binary_file(result.tangent_signs_path, result.tangent_signs)", tangents_report_body)
        self.assertIn("write_int_binary_file(result.bone_counts_path, bone_counts)", tangents_report_body)
        self.assertIn("write_int_binary_file(result.source_vertex_map_path, result.source_vertex_map)", tangents_report_body)
        self.assertIn("if (!result.vertex_storage_safe && !result.topology_split_applied)", tangents_report_body)
        self.assertIn("write_vec3_binary_file(result.tangents_path, result.tangents)", tangents_report_body)
        self.assertIn("write_vec3_binary_descriptor(out, result.tangents_path, result.tangents.size())", tangents_report_body)
        self.assertIn("write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start)", tangents_report_body)
        self.assertIn("apply_native_mesh_split(", mesh_ops_source)
        self.assertIn("apply_native_mesh_fix_winding(", mesh_ops_source)
        remove_doubles_start = mesh_ops_source.index("def _remove_doubles(")
        remove_doubles_body = mesh_ops_source[
            remove_doubles_start: mesh_ops_source.index("def _delete_loose_vertices", remove_doubles_start)
        ]
        self.assertIn("selected: dict[int, set[int] | None]", remove_doubles_body)
        self.assertIn("for submesh_index in selection.source_indices:", remove_doubles_body)
        self.assertIn("selected[submesh_index] = None", remove_doubles_body)
        self.assertLess(
            remove_doubles_body.index("for submesh_index in selection.source_indices:"),
            remove_doubles_body.index("_selected_vertices(mesh, explicit_selection"),
        )
        self.assertLess(
            remove_doubles_body.index("selected[submesh_index] = None"),
            remove_doubles_body.index("apply_native_mesh_remove_doubles(mesh, selected"),
        )
        self.assertIn("selected = {index: None for index, submesh in enumerate(mesh.submeshes) if len(submesh.vertices) >= 2}", remove_doubles_body)
        self.assertLess(
            remove_doubles_body.index("selected = {index: None for index, submesh in enumerate(mesh.submeshes) if len(submesh.vertices) >= 2}"),
            remove_doubles_body.index("apply_native_mesh_remove_doubles(mesh, selected"),
        )
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.remove_doubles"', remove_doubles_body)
        self.assertLess(
            remove_doubles_body.index('_allow_python_mesh_edit_fallback(mesh, "topology.remove_doubles"'),
            remove_doubles_body.index("fallback_selected = {"),
        )
        self.assertNotIn(
            "set(range(len(submesh.vertices)))",
            remove_doubles_body[: remove_doubles_body.index("apply_native_mesh_remove_doubles(mesh, selected")],
        )
        compact_start = mesh_ops_source.index("def _delete_loose_vertices(")
        compact_body = mesh_ops_source[compact_start: mesh_ops_source.index("def _fix_winding", compact_start)]
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "topology.compact_orphans"', compact_body)
        self.assertLess(
            compact_body.index('_allow_python_mesh_edit_fallback(mesh, "topology.compact_orphans"'),
            compact_body.index("compact_orphan_vertices("),
        )
        self.assertIn("apply_native_mesh_weighted_normals(mesh, target_indices)", mesh_ops_source)
        self.assertIn(
            "apply_native_mesh_recalculate_normals(mesh, target_indices, return_changed_vertices=True)",
            mesh_ops_source,
        )
        self.assertIn("apply_native_mesh_flip_normals(", mesh_ops_source)
        recalc_start = mesh_ops_source.index("def _recalculate_normals")
        recalc_body = mesh_ops_source[recalc_start: mesh_ops_source.index("def _weighted_normals", recalc_start)]
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "normals.recalculate"', recalc_body)
        self.assertLess(recalc_body.index("return_changed_vertices=True"), recalc_body.index("for submesh_index in sorted(target_indices):"))
        self.assertLess(
            recalc_body.index('_allow_python_mesh_edit_fallback(mesh, "normals.recalculate"'),
            recalc_body.index("for submesh_index in sorted(target_indices):"),
        )
        update_start = mesh_controller_source.index("def native_update_for_result(")
        legacy_update_start = mesh_controller_source.index("def legacy_python_update_for_result(")
        update_body = mesh_controller_source[update_start:legacy_update_start]
        native_update_start = mesh_controller_source.index("class MeshEditorNativeUpdate:")
        native_update_body = mesh_controller_source[native_update_start:update_start]
        self.assertIn("vertex_groups: Sequence[Mapping[str, object]]", native_update_body)
        self.assertIn("triangle_groups: Sequence[Mapping[str, object]]", native_update_body)
        self.assertIn("selection_groups: Sequence[Mapping[str, object]]", native_update_body)
        self.assertIn("material_override_groups: Sequence[Mapping[str, object]]", native_update_body)
        self.assertIn("stop_event: threading.Event | None = None", update_body)
        self.assertIn("result.action in NATIVE_EDITOR_SESSION_COMMANDS", update_body)
        self.assertIn("active native {result.action} result did not include preview payload", update_body)
        self.assertIn("return MeshEditorNativeUpdate()", update_body)
        self.assertIn("legacy Python preview rebuild is disabled", update_body)
        self.assertNotIn("self.working_mesh(clone=False)", update_body)
        legacy_update_body = mesh_controller_source[legacy_update_start:mesh_controller_source.index("def _session_id(", legacy_update_start)]
        self.assertIn("allow_archive_legacy_preview_rebuild: bool = False", legacy_update_body)
        self.assertIn("legacy Python preview rebuild is archive-only", legacy_update_body)
        self.assertIn("mesh = self.working_mesh(clone=False)", legacy_update_body)
        self.assertLess(
            legacy_update_body.index("legacy Python preview rebuild is archive-only"),
            legacy_update_body.index("mesh = self.working_mesh(clone=False)"),
        )
        self.assertLess(
            update_body.index("result.action in NATIVE_EDITOR_SESSION_COMMANDS"),
            update_body.index("legacy Python preview rebuild is disabled"),
        )
        self.assertLess(
            update_body.index("return MeshEditorNativeUpdate()"),
            update_body.index("legacy Python preview rebuild is disabled"),
        )
        self.assertIn("allow_python_fallback=True", legacy_update_body)
        self.assertGreaterEqual(legacy_update_body.count("allow_python_fallback=True"), 3)
        self.assertNotIn("tuple(mesh_edit_selection_groups(", update_body)
        self.assertNotIn("tuple(mesh_edit_vertex_update_groups(", update_body)
        self.assertNotIn("tuple(mesh_edit_triangle_groups(", update_body)
        self.assertNotIn("tuple(mesh_edit_material_override_groups(", update_body)
        self.assertNotIn("affected = tuple(int(index) for index in result.affected_submesh_indices)", update_body)
        self.assertIn("affected = result.affected_submesh_indices", legacy_update_body)
        self.assertIn("changed_vertices = _changed_vertices_by_submesh_for_preview(result)", update_body)
        self.assertIn("def _changed_vertices_by_submesh_for_preview(", mesh_controller_source)
        preview_changed_start = mesh_controller_source.index("def _changed_vertices_by_submesh_for_preview(")
        preview_changed_body = mesh_controller_source[
            preview_changed_start: mesh_controller_source.index("def _topology_refresh_source_indices(", preview_changed_start)
        ]
        self.assertIn("if isinstance(indices, Mapping):", preview_changed_body)
        self.assertIn("changed[submesh_index] = indices", preview_changed_body)
        self.assertIn("if isinstance(indices, (tuple, range, set)):", preview_changed_body)
        self.assertLess(
            preview_changed_body.index("if isinstance(indices, Mapping):"),
            preview_changed_body.index("tuple(int(index) for index in indices)"),
        )
        service_result_start = mesh_history_source.index("    def _result(")
        service_result_body = mesh_history_source[service_result_start:]
        self.assertIn("_changed_vertex_indices_for_result(indices)", service_result_body)
        self.assertNotIn("tuple(sorted(indices))", service_result_body)
        service_changed_result_start = mesh_report_source.index("def _changed_vertex_indices_for_result(")
        service_changed_result_body = mesh_report_source[service_changed_result_start:]
        self.assertIn("_CHANGED_VERTEX_RESULT_TUPLE_LIMIT = 10_000", mesh_report_source)
        self.assertIn("descriptor = _changed_vertex_descriptor_for_result(indices)", service_changed_result_body)
        self.assertIn("return descriptor", service_changed_result_body)
        self.assertIn("def _changed_vertex_descriptor_for_result(", service_changed_result_body)
        self.assertIn('"changed_vertices_binary"', service_changed_result_body)
        self.assertIn('"source_vertex_indices_binary"', service_changed_result_body)
        self.assertIn("if isinstance(indices, set) and len(indices) > _CHANGED_VERTEX_RESULT_TUPLE_LIMIT:", service_changed_result_body)
        self.assertIn("return indices", service_changed_result_body)
        self.assertIn("return range(start, start + count)", service_changed_result_body)
        self.assertNotIn("tuple(changed_range)", service_changed_result_body)
        self.assertNotIn("len(indices) > _PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT", service_changed_result_body)
        self.assertIn("def _changed_vertices_for_static_result(", static_adapter_source)
        self.assertIn("changed_vertices_by_submesh: dict[int, object] | None", static_adapter_source)
        self.assertIn("if isinstance(indices, Mapping):", static_adapter_source)
        self.assertIn("changed[submesh] = dict(indices)", static_adapter_source)
        self.assertIn("if isinstance(indices, range) and indices.step == 1:", static_adapter_source)
        self.assertNotIn(
            "set(int(index) for index in indices)\n        for submesh, indices in edit_result.changed_vertices_by_submesh",
            static_adapter_source,
        )
        changed_from_vertices_start = mesh_ops_source.index("def _changed_from_vertices(")
        changed_from_vertices_body = mesh_ops_source[
            changed_from_vertices_start: mesh_ops_source.index("def _changed_vertex_values(", changed_from_vertices_start)
        ]
        self.assertIn("_changed_vertex_values(values)", changed_from_vertices_body)
        self.assertNotIn("set(values) for index, values", changed_from_vertices_body)
        auto_uv_apply_start = mesh_native_source.index("def _apply_auto_uv_report(")
        auto_uv_apply_body = mesh_native_source[auto_uv_apply_start: mesh_native_source.index("def _apply_uv_transform_report(", auto_uv_apply_start)]
        self.assertIn("changed_vertices = range(len(submesh.vertices))", auto_uv_apply_body)
        self.assertIn("_merge_changed_vertices(changed, submesh_index, changed_vertices)", auto_uv_apply_body)
        self.assertNotIn("set(range(len(submesh.vertices)))", auto_uv_apply_body)
        apply_normals_start = mesh_native_source.index("def _apply_recalculate_normals_report(")
        apply_normals_body = mesh_native_source[apply_normals_start: mesh_native_source.index("def _apply_generate_tangents_report(", apply_normals_start)]
        self.assertIn("_merge_changed_vertices(changed, submesh_index, range(len(parsed_normals)))", apply_normals_body)
        self.assertNotIn("set(range(len(parsed_normals)))", apply_normals_body)
        self.assertIn("def _changed_vertices_for_report(", mesh_native_source)
        self.assertNotIn("set(parsed_changed_ordered", mesh_native_source)
        self.assertNotIn("set(changed_ordered", mesh_native_source)
        self.assertNotIn("set(changed_vertices)", mesh_native_source)
        self.assertNotIn("any(index < 0 or index >= vertex_count for index in changed_vertices)", mesh_native_source)
        self.assertLess(legacy_update_body.index("if changed_vertices:"), legacy_update_body.index('if result.action == "recalculate_normals"'))
        self.assertIn("_all_vertices_by_submesh(mesh, result.affected_submesh_indices)", legacy_update_body)
        undo_redo_start = legacy_update_body.index('if result.action in {"undo", "redo"} and result.ok and not result.topology_changed:')
        undo_redo_body = legacy_update_body[undo_redo_start: legacy_update_body.index("if result.topology_changed:", undo_redo_start)]
        self.assertIn("if changed_vertices and not result.topology_changed:", undo_redo_body)
        self.assertIn("affected = range(len(mesh.submeshes))", undo_redo_body)
        self.assertNotIn("affected = tuple(range(len(mesh.submeshes)))", undo_redo_body)
        self.assertLess(
            undo_redo_body.index("mesh_edit_vertex_update_groups("),
            undo_redo_body.index("mesh_edit_triangle_groups("),
        )
        topology_body = legacy_update_body[legacy_update_body.index("if result.topology_changed:"): legacy_update_body.index('if result.action in {"material_assign", "material_copy"}')]
        self.assertIn("mesh_edit_triangle_groups(", topology_body)
        self.assertIn("refresh_sources", topology_body)
        self.assertIn("refresh_sources = affected if not replace_all else range(len(mesh.submeshes))", topology_body)
        self.assertNotIn("refresh_sources = affected if not replace_all else tuple(range(len(mesh.submeshes)))", topology_body)
        self.assertIn("replace_all_triangles=replace_all", topology_body)
        topology_refresh_start = mesh_controller_source.index("def _topology_refresh_source_indices(")
        topology_refresh_body = mesh_controller_source[topology_refresh_start: mesh_controller_source.index("def _coerce_source_index(", topology_refresh_start)]
        self.assertNotIn("tuple(result.affected_submesh_indices or ())", topology_refresh_body)
        weighted_start = mesh_ops_source.index("def _weighted_normals")
        weighted_body = mesh_ops_source[weighted_start: mesh_ops_source.index("def _computed_weighted_normals", weighted_start)]
        self.assertLess(weighted_body.index("apply_native_mesh_weighted_normals"), weighted_body.index("for submesh_index in sorted(target_indices):"))
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "normals.weighted"', weighted_body)
        self.assertLess(
            weighted_body.index('_allow_python_mesh_edit_fallback(mesh, "normals.weighted"'),
            weighted_body.index("for submesh_index in sorted(target_indices):"),
        )
        tangents_start = mesh_ops_source.index("def _generate_tangents")
        tangents_body = mesh_ops_source[tangents_start: mesh_ops_source.index("def _computed_vertex_tangents", tangents_start)]
        self.assertLess(tangents_body.index("apply_native_mesh_generate_tangents"), tangents_body.index("for submesh_index in sorted(target_indices):"))
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "tangents.generate"', tangents_body)
        self.assertLess(
            tangents_body.index('_allow_python_mesh_edit_fallback(mesh, "tangents.generate"'),
            tangents_body.index("for submesh_index in sorted(target_indices):"),
        )
        flip_start = mesh_ops_source.index("def _flip_normals")
        flip_body = mesh_ops_source[flip_start: mesh_ops_source.index("def _sharpen_normals", flip_start)]
        self.assertLess(
            flip_body.index("if selection.source_indices and not has_explicit_selection:"),
            flip_body.index("selected_faces = _selected_faces(mesh, selection"),
        )
        self.assertLess(
            flip_body.index("native_affected = apply_native_mesh_flip_normals(mesh, target_indices)"),
            flip_body.index("selected_faces = _selected_faces(mesh, selection"),
        )
        self.assertLess(flip_body.index("apply_native_mesh_flip_normals"), flip_body.index("recompute_submesh_normals(submesh)"))
        self.assertIn('_allow_python_mesh_edit_fallback(mesh, "normals.flip"', flip_body)
        self.assertLess(
            flip_body.index('_allow_python_mesh_edit_fallback(mesh, "normals.flip"'),
            flip_body.index("recompute_submesh_normals(submesh)"),
        )
        sharpen_start = mesh_ops_source.index("def _sharpen_normals")
        sharpen_body = mesh_ops_source[sharpen_start: mesh_ops_source.index("def _copy_normals", sharpen_start)]
        self.assertIn('"normals.sharpen"', sharpen_body)
        self.assertIn("apply_native_mesh_sharpen_normals", sharpen_body)
        self.assertLess(
            sharpen_body.index("apply_native_mesh_sharpen_normals(mesh, {"),
            sharpen_body.index("_allow_python_mesh_edit_fallback(mesh, \"normals.sharpen\""),
        )
        self.assertLess(
            sharpen_body.index("native_changed = apply_native_mesh_sharpen_normals(mesh, selected_faces)"),
            sharpen_body.rindex('_allow_python_mesh_edit_fallback(mesh, "normals.sharpen"'),
        )
        self.assertLess(
            sharpen_body.index("_allow_python_mesh_edit_fallback(mesh, \"normals.sharpen\""),
            sharpen_body.index("selected_faces = _selected_faces(mesh, selection"),
        )
        self.assertLess(
            sharpen_body.rindex('_allow_python_mesh_edit_fallback(mesh, "normals.sharpen"'),
            sharpen_body.index("changed: MeshEditChangedVertices = {}"),
        )
        copy_start = mesh_ops_source.index("def _copy_normals")
        copy_body = mesh_ops_source[copy_start: mesh_ops_source.index("def _uv_transform", copy_start)]
        self.assertIn("apply_native_mesh_copy_normals", copy_body)
        self.assertNotIn("selected_for_native = _selected_vertices_with_source_ranges(mesh, selection)", copy_body)
        self.assertIn("selected_vertices = selection.vertex_map()", copy_body)
        self.assertIn("selected_edges = selection.edge_map()", copy_body)
        self.assertIn("selected_faces = selection.face_map()", copy_body)
        self.assertIn("selected_edges_by_submesh=selected_edges", copy_body)
        self.assertIn("selected_faces_by_submesh=selected_faces", copy_body)
        self.assertIn("source_indices=source_indices", copy_body)
        self.assertLess(
            copy_body.index("apply_native_mesh_copy_normals("),
            copy_body.index("selected = _selected_vertices(mesh, selection"),
        )
        self.assertLess(
            copy_body.index('_allow_python_mesh_edit_fallback(\n        mesh,\n        "normals.copy"'),
            copy_body.index("selected = _selected_vertices(mesh, selection"),
        )
        uv_start = mesh_ops_source.index("def _uv_transform")
        uv_body = mesh_ops_source[uv_start: mesh_ops_source.index("def _native_uv_transform_kwargs", uv_start)]
        self.assertNotIn("_selected_vertices_with_source_ranges(mesh, selection)", uv_body)
        self.assertIn("native_target_sources = _selection_target_sources(selection)", uv_body)
        self.assertIn("selected_edges_by_submesh=selected_edges", uv_body)
        self.assertIn("selected_faces_by_submesh=selected_faces", uv_body)
        self.assertIn("source_indices=source_indices", uv_body)
        self.assertLess(
            uv_body.index("native_changed = apply_native_mesh_uv_transform("),
            uv_body.index("selected = _selected_vertices(mesh, selection"),
        )
        self.assertLess(
            uv_body.index("if not _allow_python_mesh_edit_fallback(mesh, native_operation, submesh_indices=native_target_sources):"),
            uv_body.index("selected = _selected_vertices(mesh, selection"),
        )
        self.assertIn("selected_vertices_from_edit_domains(item, vertices.size(), faces)", native_core_source)
        self.assertIn("selected_vertices_from_edit_domains(item, result.uvs.size(), faces)", native_core_source)
        copy_native_start = mesh_native_source.index("def apply_native_mesh_copy_normals(")
        copy_native_body = mesh_native_source[copy_native_start: mesh_native_source.index("def apply_native_mesh_recalculate_normals", copy_native_start)]
        self.assertIn("selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None", copy_native_body)
        self.assertIn("selected_faces_by_submesh: Mapping[int, set[int]] | None = None", copy_native_body)
        self.assertIn("source_indices: Sequence[int] = ()", copy_native_body)
        self.assertIn("_put_selected_edit_domain_payload(", copy_native_body)
        uv_native_start = mesh_native_source.index("def apply_native_mesh_uv_transform(")
        uv_native_body = mesh_native_source[uv_native_start: mesh_native_source.index("def apply_native_mesh_uv_transform_submeshes", uv_native_start)]
        self.assertIn("selected_edges_by_submesh: Mapping[int, set[tuple[int, int]]] | None = None", uv_native_body)
        self.assertIn("selected_faces_by_submesh: Mapping[int, set[int]] | None = None", uv_native_body)
        self.assertIn("source_indices: Sequence[int] = ()", uv_native_body)
        self.assertIn("_put_selected_edit_domain_payload(", uv_native_body)
        self.assertLess(
            uv_native_body.index("_put_selected_edit_domain_payload("),
            uv_native_body.index("_run_native_mesh_core_job("),
        )
        self.assertLess(
            copy_native_body.index("_put_selected_edit_domain_payload("),
            copy_native_body.index("_run_native_mesh_core_job("),
        )
        self.assertIn("selected_edges_by_submesh=edges", mesh_ops_source)
        self.assertIn("all_faces_by_submesh=all_faces", mesh_ops_source)
        self.assertIn("def apply_native_mesh_fix_winding(", mesh_native_source)
        self.assertIn('"operation": "fix_winding"', mesh_native_source)
        self.assertIn("def apply_native_mesh_fill_holes(", mesh_native_source)
        self.assertIn('"operation": "fill_holes"', mesh_native_source)
        self.assertIn("def apply_native_mesh_fill(", mesh_native_source)
        self.assertIn('"operation": "fill"', mesh_native_source)
        self.assertIn("def apply_native_mesh_loop_cut(", mesh_native_source)
        self.assertIn('"operation": "loop_cut"', mesh_native_source)
        self.assertIn("def apply_native_mesh_edge_split(", mesh_native_source)
        self.assertIn('"operation": "edge_split"', mesh_native_source)
        self.assertIn("def apply_native_mesh_merge(", mesh_native_source)
        self.assertIn('"operation": "merge"', mesh_native_source)
        self.assertIn("def apply_native_mesh_weld(", mesh_native_source)
        self.assertIn('"operation": "weld"', mesh_native_source)
        self.assertIn("def apply_native_mesh_bridge(", mesh_native_source)
        self.assertIn('"operation": "bridge"', mesh_native_source)
        self.assertIn("def apply_native_mesh_dissolve(", mesh_native_source)
        self.assertIn('"operation": "dissolve"', mesh_native_source)
        self.assertIn("def apply_native_mesh_extrude(", mesh_native_source)
        self.assertIn('"operation": "extrude"', mesh_native_source)
        self.assertIn("def apply_native_mesh_inset(", mesh_native_source)
        self.assertIn('"operation": "inset"', mesh_native_source)
        self.assertIn("def apply_native_mesh_triangulate_display(", mesh_native_source)
        self.assertIn('"operation": "triangulate_display"', mesh_native_source)
        self.assertIn("def apply_native_mesh_duplicate(", mesh_native_source)
        self.assertIn('"operation": "duplicate"', mesh_native_source)
        self.assertIn("def apply_native_mesh_mirror(", mesh_native_source)
        self.assertIn('"operation": "mirror"', mesh_native_source)
        self.assertIn("def apply_native_mesh_separate(", mesh_native_source)
        self.assertIn('"operation": "separate"', mesh_native_source)
        dissolve_start = mesh_ops_source.index("def _dissolve(")
        dissolve_body = mesh_ops_source[dissolve_start: mesh_ops_source.index("def _delete_submeshes(", dissolve_start)]
        self.assertLess(
            dissolve_body.index("apply_native_mesh_dissolve("),
            dissolve_body.index("_dissolve_internal_edges(mesh, edges)"),
        )
        extrude_start = mesh_ops_source.index("def _extrude(")
        extrude_body = mesh_ops_source[extrude_start: mesh_ops_source.index("def _extrude_edges(", extrude_start)]
        self.assertLess(
            extrude_body.index("apply_native_mesh_extrude("),
            extrude_body.index("_selected_faces(mesh, selection"),
        )
        inset_start = mesh_ops_source.index("def _inset(")
        inset_body = mesh_ops_source[inset_start: mesh_ops_source.index("def _inset_amount(", inset_start)]
        self.assertLess(
            inset_body.index("apply_native_mesh_inset("),
            inset_body.index("_selected_faces(mesh, selection"),
        )
        fix_winding_start = mesh_ops_source.index("def _fix_winding(")
        fix_winding_body = mesh_ops_source[fix_winding_start: mesh_ops_source.index("def _fill_holes(", fix_winding_start)]
        self.assertLess(
            fix_winding_body.index("apply_native_mesh_fix_winding("),
            fix_winding_body.index("for submesh_index in target_indices:"),
        )
        fill_holes_start = mesh_ops_source.index("def _fill_holes(")
        fill_holes_body = mesh_ops_source[fill_holes_start: mesh_ops_source.index("def _triangulate_display(", fill_holes_start)]
        self.assertLess(
            fill_holes_body.index("apply_native_mesh_fill_holes("),
            fill_holes_body.index("for submesh_index in target_indices:"),
        )
        triangulate_start = mesh_ops_source.index("def _triangulate_display(")
        triangulate_body = mesh_ops_source[triangulate_start: mesh_ops_source.index("def _closed_edge_loop_order(", triangulate_start)]
        self.assertLess(
            triangulate_body.index("apply_native_mesh_triangulate_display("),
            triangulate_body.index("for submesh_index in target_indices:"),
        )
        bridge_start = mesh_ops_source.index("def _bridge(")
        bridge_body = mesh_ops_source[bridge_start: mesh_ops_source.index("def _surface_channel_target_indices(", bridge_start)]
        self.assertLess(
            bridge_body.index("apply_native_mesh_bridge("),
            bridge_body.index("for submesh_index, edges in selected_edges.items():"),
        )
        fill_start = mesh_ops_source.index("def _fill(")
        fill_body = mesh_ops_source[fill_start: mesh_ops_source.index("def _remove_doubles(", fill_start)]
        self.assertIn("_allow_python_mesh_edit_fallback(", fill_body)
        self.assertIn('"topology.fill"', fill_body)
        self.assertLess(
            fill_body.index("apply_native_mesh_fill("),
            fill_body.index("_closed_edge_loop_order(edges)"),
        )
        loop_cut_start = mesh_ops_source.index("def _loop_cut(")
        loop_cut_body = mesh_ops_source[loop_cut_start: mesh_ops_source.index("def _loop_cut_count(", loop_cut_start)]
        self.assertIn('"topology.loop_cut"', loop_cut_body)
        self.assertLess(
            loop_cut_body.index("apply_native_mesh_loop_cut("),
            loop_cut_body.index("cut_count = _loop_cut_count(params)"),
        )
        self.assertLess(
            loop_cut_body.index("apply_native_mesh_loop_cut("),
            loop_cut_body.index("for submesh_index, edges in selected_edges.items():"),
        )
        edge_split_start = mesh_ops_source.index("def _edge_split(")
        edge_split_body = mesh_ops_source[edge_split_start: mesh_ops_source.index("def _edge_key(", edge_split_start)]
        self.assertIn('"topology.edge_split"', edge_split_body)
        self.assertLess(
            edge_split_body.index("apply_native_mesh_edge_split("),
            edge_split_body.index("for submesh_index, edges in selected_edges.items():"),
        )
        merge_start = mesh_ops_source.index("def _merge(")
        merge_body = mesh_ops_source[merge_start: mesh_ops_source.index("def _weld(", merge_start)]
        self.assertIn('"topology.merge"', merge_body)
        self.assertLess(
            merge_body.index("apply_native_mesh_merge("),
            merge_body.index("_selected_vertices(mesh, selection"),
        )
        weld_start = mesh_ops_source.index("def _weld(")
        weld_body = mesh_ops_source[weld_start: mesh_ops_source.index("def _fill(", weld_start)]
        self.assertIn('"topology.weld"', weld_body)
        self.assertLess(
            weld_body.index("apply_native_mesh_weld("),
            weld_body.index("_selected_vertices(mesh, selection"),
        )
        duplicate_start = mesh_ops_source.index("def _duplicate(")
        duplicate_body = mesh_ops_source[duplicate_start: mesh_ops_source.index("def _mirror(", duplicate_start)]
        self.assertLess(
            duplicate_body.index("apply_native_mesh_duplicate("),
            duplicate_body.index("_selected_faces(mesh, selection"),
        )
        self.assertLess(
            duplicate_body.index("apply_native_mesh_duplicate("),
            duplicate_body.index("_append_face_copy("),
        )
        mirror_start = mesh_ops_source.index("def _mirror(")
        mirror_body = mesh_ops_source[mirror_start: mesh_ops_source.index("def _mirrored(", mirror_start)]
        self.assertIn('"topology.mirror"', mirror_body)
        self.assertLess(
            mirror_body.index("apply_native_mesh_transform_selection("),
            mirror_body.index("_selected_vertices(mesh, selection"),
        )
        self.assertLess(
            mirror_body.index("apply_native_mesh_mirror("),
            mirror_body.index("_selected_faces(mesh, selection"),
        )
        self.assertLess(
            mirror_body.index("apply_native_mesh_mirror("),
            mirror_body.index("_append_mirrored_face_copy("),
        )
        separate_start = mesh_ops_source.index("def _separate(")
        separate_body = mesh_ops_source[separate_start: mesh_ops_source.index("def _duplicate(", separate_start)]
        self.assertLess(
            separate_body.index("apply_native_mesh_separate("),
            separate_body.index("_selected_faces(mesh, selection"),
        )
        self.assertLess(
            separate_body.index("apply_native_mesh_separate("),
            separate_body.index("split_faces_to_submesh("),
        )
        self.assertIn("run_split_edit_for_submesh", native_core_source)
        self.assertIn("run_fix_winding_edit_for_submesh", native_core_source)
        self.assertIn("run_fill_holes_edit_for_submesh", native_core_source)
        self.assertIn("run_fill_edit_for_submesh", native_core_source)
        self.assertIn("run_loop_cut_edit_for_submesh", native_core_source)
        self.assertIn("run_edge_split_edit_for_submesh", native_core_source)
        self.assertIn("run_merge_edit_for_submesh", native_core_source)
        self.assertIn("run_weld_edit_for_submesh", native_core_source)
        self.assertIn("run_bridge_edit_for_submesh", native_core_source)
        self.assertIn("run_dissolve_edit_for_submesh", native_core_source)
        self.assertIn("run_extrude_edit_for_submesh", native_core_source)
        self.assertIn("run_inset_edit_for_submesh", native_core_source)
        self.assertIn("run_triangulate_display_edit_for_submesh", native_core_source)
        self.assertIn("run_duplicate_edit_for_submesh", native_core_source)
        self.assertIn("run_mirror_edit_for_submesh", native_core_source)
        self.assertIn("run_separate_edit_for_submesh", native_core_source)
        self.assertIn('operation == "split"', native_core_source)
        self.assertIn('operation == "fix_winding"', native_core_source)
        self.assertIn('operation == "fill_holes"', native_core_source)
        self.assertIn('operation == "fill"', native_core_source)
        self.assertIn('operation == "loop_cut"', native_core_source)
        self.assertIn('operation == "edge_split"', native_core_source)
        self.assertIn('operation == "merge"', native_core_source)
        self.assertIn('operation == "weld"', native_core_source)
        self.assertIn('operation == "bridge"', native_core_source)
        self.assertIn('operation == "dissolve"', native_core_source)
        self.assertIn('operation == "extrude"', native_core_source)
        self.assertIn('operation == "inset"', native_core_source)
        self.assertIn('operation == "triangulate_display"', native_core_source)
        self.assertIn('operation == "duplicate"', native_core_source)
        self.assertIn('operation == "mirror"', native_core_source)
        self.assertIn('operation == "separate"', native_core_source)
        self.assertIn("selected_faces_from_topology_json", native_core_source)
        self.assertIn("selected_edges_from_json", native_core_source)

    def test_static_preview_queues_block_active_mesh_edit(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py")
        blocker_body = _function_source(source, "_active_mesh_edit_preview_queue_blocked")
        refresh_body = _function_source(source, "_queue_static_preview_refresh")
        queue_body = _function_source(source, "_queue_static_preview_rebuild")
        texture_body = _function_source(source, "_queue_texture_preview_refresh")
        texture_uv_body = _function_source(source, "_queue_texture_uv_preview_refresh")
        global_transform_body = _function_source(source, "_queue_global_transform_preview_update")
        part_transform_body = _function_source(source, "_queue_part_transform_preview_update")
        stale_reload_body = _function_source(source, "_queue_latest_alignment_d3d11_rebuild_for_stale_reload")

        self.assertIn("Active Mesh Editor static preview {kind} is disabled", blocker_body)
        self.assertIn("_state.self.set_status_message(message, error=True)", blocker_body)
        self.assertIn("_state._mesh_edit_enabled_checked()", blocker_body)
        self.assertIn("_state._alignment_mesh_edit_tab_active()", blocker_body)
        self.assertIn("'mesh_edit_static_preview_refresh_blocked'", refresh_body)
        self.assertIn("'mesh_edit_static_preview_rebuild_blocked'", queue_body)
        self.assertIn("'mesh_edit_static_preview_texture_refresh_blocked'", texture_body)
        self.assertIn("'mesh_edit_static_preview_texture_uv_refresh_blocked'", texture_uv_body)
        self.assertIn("'mesh_edit_static_preview_transform_refresh_blocked'", global_transform_body)
        self.assertIn("'mesh_edit_static_preview_transform_refresh_blocked'", part_transform_body)
        self.assertIn("'mesh_edit_static_preview_stale_reload_blocked'", stale_reload_body)
        self.assertLess(refresh_body.index("_active_mesh_edit_preview_queue_blocked"), refresh_body.index("static_preview_refresh_timer.start()"))
        self.assertLess(queue_body.index("_active_mesh_edit_preview_queue_blocked"), queue_body.index("static_preview_refresh_timer.start()"))
        self.assertLess(queue_body.index("_active_mesh_edit_preview_queue_blocked"), queue_body.index("static_preview_settle_timer.start()"))
        self.assertLess(texture_body.index("_active_mesh_edit_preview_queue_blocked"), texture_body.index("static_preview_refresh_timer.start()"))
        self.assertLess(texture_uv_body.index("_active_mesh_edit_preview_queue_blocked"), texture_uv_body.index("static_preview_refresh_timer.start()"))
        self.assertLess(global_transform_body.index("_active_mesh_edit_transform_preview_queue_blocked"), global_transform_body.index("static_preview_refresh_timer.start()"))
        self.assertLess(part_transform_body.index("_active_mesh_edit_transform_preview_queue_blocked"), part_transform_body.index("static_preview_refresh_timer.start()"))
        self.assertLess(stale_reload_body.index("_active_mesh_edit_d3d11_static_preview_queue_blocked"), stale_reload_body.index("static_preview_refresh_timer.start()"))

    def test_source_part_adjustment_callbacks_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py")
        transform_guard_body = _function_source(source, "_active_mesh_edit_part_adjustment_mutation_blocked")
        translate_body = _function_source(source, "_apply_alignment_part_translation_delta")
        rotate_body = _function_source(source, "_apply_alignment_part_rotation_delta")
        d3d11_translate_body = _function_source(source, "_apply_alignment_d3d11_translation_total")
        d3d11_rotate_body = _function_source(source, "_apply_alignment_d3d11_rotation_total")
        include_guard_body = _function_source(source, "_active_mesh_edit_include_exclude_mutation_blocked")
        routing_guard_body = _function_source(source, "_active_mesh_edit_source_routing_mutation_blocked")
        check_body = _function_source(source, "_source_item_check_state_changed")
        target_body = _function_source(source, "_apply_parts_outliner_source_target")
        role_body = _function_source(source, "_apply_parts_outliner_source_role")
        set_mapping_body = _function_source(source, "_set_mapping_indices")

        self.assertIn("Active Mesh Editor source-part {kind} changes require native geometry execution", transform_guard_body)
        self.assertIn("Python adjustment mutation fallback is disabled", transform_guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", transform_guard_body)
        self.assertLess(
            translate_body.index("_active_mesh_edit_part_adjustment_mutation_blocked"),
            translate_body.index("adjustment.offset_xyz ="),
        )
        self.assertLess(
            rotate_body.index("_active_mesh_edit_part_adjustment_mutation_blocked"),
            rotate_body.index("adjustment.rotate_xyz_degrees ="),
        )
        self.assertLess(
            d3d11_translate_body.index("_active_mesh_edit_part_adjustment_mutation_blocked"),
            d3d11_translate_body.index("adjustment.offset_xyz = new_offset"),
        )
        self.assertLess(
            d3d11_rotate_body.index("_active_mesh_edit_part_adjustment_mutation_blocked"),
            d3d11_rotate_body.index("adjustment.rotate_xyz_degrees = new_rotation"),
        )
        self.assertIn("Active Mesh Editor source-part include/exclude changes require native geometry execution", include_guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", include_guard_body)
        self.assertIn("Active Mesh Editor source routing {action} requires native material execution", routing_guard_body)
        self.assertIn("Python routing mutation fallback is disabled", routing_guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", routing_guard_body)
        self.assertLess(
            check_body.index("_active_mesh_edit_include_exclude_mutation_blocked"),
            check_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            check_body.index("_active_mesh_edit_include_exclude_mutation_blocked"),
            check_body.index("adjustment.enabled = toggle_state.enabled"),
        )
        self.assertLess(
            target_body.index("_active_mesh_edit_source_routing_mutation_blocked"),
            target_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            target_body.index("_active_mesh_edit_source_routing_mutation_blocked"),
            target_body.index("preview_only_source_indices"),
        )
        self.assertLess(
            role_body.index("_active_mesh_edit_source_routing_mutation_blocked"),
            role_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            role_body.index("_active_mesh_edit_source_routing_mutation_blocked"),
            role_body.index("_set_source_role_override_value"),
        )
        self.assertLess(
            set_mapping_body.index("_active_mesh_edit_source_routing_mutation_blocked"),
            set_mapping_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            set_mapping_body.index("_active_mesh_edit_source_routing_mutation_blocked"),
            set_mapping_body.index("_state.texture_overrides_dirty['dirty'] = True"),
        )

    def test_mapping_edit_callbacks_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py")
        flush_body = _function_source(source, "_flush_mapping_edit_refresh")
        guard_body = _function_source(source, "_active_mesh_edit_mapping_mutation_blocked")
        commit_body = _function_source(source, "_commit_mapping_edit")

        self.assertIn("Active Mesh Editor mapping edits require native material execution", guard_body)
        self.assertIn("Python routing mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertLess(
            flush_body.index("_geometry_mesh_edit_active()"),
            flush_body.index("texture_overrides_dirty['dirty'] = True"),
        )
        self.assertLess(
            flush_body.index("_geometry_mesh_edit_active()"),
            flush_body.index("_queue_static_preview_rebuild()"),
        )
        self.assertLess(
            commit_body.index("_active_mesh_edit_mapping_mutation_blocked"),
            commit_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            commit_body.index("_active_mesh_edit_mapping_mutation_blocked"),
            commit_body.index("texture_overrides_dirty['dirty'] = True"),
        )
        self.assertLess(
            commit_body.index("_active_mesh_edit_mapping_mutation_blocked"),
            commit_body.index("edit.setProperty('committed_mapping_text', next_text)"),
        )

    def test_source_part_geometry_actions_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_routing_callbacks.py")
        guard_start = source.index("def _active_mesh_edit_source_part_geometry_action_blocked(")
        guard_body = source[guard_start: source.index("def _normalize_appended_part_to_work_area", guard_start)]
        normalize_start = source.index("def _normalize_appended_part_to_work_area(")
        normalize_body = source[normalize_start: source.index("def _fit_selected_part_size", normalize_start)]
        fit_start = source.index("def _fit_selected_part_size(")
        fit_body = source[fit_start: source.index("def _nudge_selected_part", fit_start)]
        nudge_start = source.index("def _nudge_selected_part(")
        nudge_body = source[nudge_start: source.index("def _nudge_selected_part_axis", nudge_start)]
        center_start = source.index("def _center_selected_part_on_target(")
        center_body = source[center_start: source.index("def _add_dialog_supplemental_file", center_start)]

        self.assertIn("Active Mesh Editor source-part {action} requires native geometry execution", guard_body)
        self.assertIn("Python geometry mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertLess(
            normalize_body.index("_active_mesh_edit_source_part_geometry_action_blocked"),
            normalize_body.index("submesh.vertices ="),
        )
        self.assertLess(
            fit_body.index("_active_mesh_edit_source_part_geometry_action_blocked"),
            fit_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            fit_body.index("_active_mesh_edit_source_part_geometry_action_blocked"),
            fit_body.index("adjustment.uniform_scale ="),
        )
        self.assertLess(
            nudge_body.index("_active_mesh_edit_source_part_geometry_action_blocked"),
            nudge_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            nudge_body.index("_active_mesh_edit_source_part_geometry_action_blocked"),
            nudge_body.index("_update_selected_part_adjustment()"),
        )
        self.assertLess(
            center_body.index("_active_mesh_edit_source_part_geometry_action_blocked"),
            center_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            center_body.index("_active_mesh_edit_source_part_geometry_action_blocked"),
            center_body.index("_update_selected_part_adjustment()"),
        )

    def test_complete_swap_routing_blocks_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_routing_callbacks.py")
        guard_body = _function_source(source, "_active_mesh_edit_complete_swap_routing_blocked")
        apply_body = _function_source(source, "_apply_complete_external_swap_routing_to_ui")

        self.assertIn("Active Mesh Editor complete-swap material routing requires native material execution", guard_body)
        self.assertIn("Python texture routing mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertLess(
            apply_body.index("_active_mesh_edit_complete_swap_routing_blocked"),
            apply_body.index("mappings = _state._complete_external_swap_mappings()"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_complete_swap_routing_blocked"),
            apply_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_complete_swap_routing_blocked"),
            apply_body.index("texture_override_assignments.clear()"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_complete_swap_routing_blocked"),
            apply_body.index("_state.texture_overrides_dirty['dirty'] = True"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_complete_swap_routing_blocked"),
            apply_body.index("_queue_static_preview_rebuild"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_complete_swap_routing_blocked"),
            apply_body.index("_queue_source_material_plan_refresh"),
        )

    def test_source_part_material_overrides_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_selection_mapping.py")
        callback_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py")
        remaining_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py")
        guard_body = _function_source(source, "_mesh_edit_material_override_blocked")
        role_body = _function_source(source, "_set_source_role_override_value")
        action_guard_body = _function_source(callback_source, "_active_mesh_edit_source_part_output_mutation_blocked")
        selected_role_body = _function_source(callback_source, "_set_selected_source_role")
        selected_glow_body = _function_source(callback_source, "_set_selected_source_glow_color")
        reset_body = _function_source(callback_source, "_reset_selected_part")
        remove_body = _function_source(callback_source, "_remove_selected_part_from_output")
        glow_guard_body = _function_source(remaining_source, "_active_mesh_edit_source_glow_mutation_blocked")
        glow_body = _function_source(remaining_source, "_apply_current_glow_color_to_role_overrides")
        flush_body = _function_source(remaining_source, "_flush_source_role_overrides_for_export")

        self.assertIn("Active Mesh Editor source material overrides require native material execution", guard_body)
        self.assertIn("Python adjustment mutation fallback is disabled", guard_body)
        self.assertIn("resident_material_parameters_available", guard_body)
        self.assertIn("Active Mesh Editor source glow overrides require native material execution", glow_guard_body)
        self.assertIn("Python adjustment mutation fallback is disabled", glow_guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", glow_guard_body)
        self.assertIn("Active Mesh Editor source-part {action} requires native material execution", action_guard_body)
        self.assertIn("Python adjustment mutation fallback is disabled", action_guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", action_guard_body)
        self.assertLess(
            role_body.index("_active_mesh_edit_material_override_mutation_blocked"),
            role_body.index("source_role_overrides[role_state.source_index]"),
        )
        self.assertLess(
            role_body.index("_active_mesh_edit_material_override_mutation_blocked"),
            role_body.index("adjustment.material_role = role_state.normalized_role"),
        )
        self.assertLess(
            role_body.index("_active_mesh_edit_material_override_mutation_blocked"),
            role_body.index('texture_overrides_dirty["dirty"] = True'),
        )
        self.assertLess(
            glow_body.index("_active_mesh_edit_source_glow_mutation_blocked"),
            glow_body.index("adjustment.emissive_color_rgb = update_state.emissive_color_rgb"),
        )
        self.assertLess(
            flush_body.index("_active_mesh_edit_source_glow_mutation_blocked"),
            flush_body.index("adjustment.material_role = flush_state.normalized_role"),
        )
        self.assertLess(
            flush_body.index("_active_mesh_edit_source_glow_mutation_blocked"),
            flush_body.index("adjustment.emissive_color_rgb = ()"),
        )
        self.assertLess(
            selected_role_body.index("_active_mesh_edit_source_part_output_mutation_blocked"),
            selected_role_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            selected_glow_body.index("_active_mesh_edit_source_part_output_mutation_blocked"),
            selected_glow_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            selected_glow_body.index("_active_mesh_edit_source_part_output_mutation_blocked"),
            selected_glow_body.index("_state.texture_overrides_dirty['dirty'] = True"),
        )
        self.assertLess(
            reset_body.index("_active_mesh_edit_source_part_output_mutation_blocked"),
            reset_body.index("source_part_adjustments.pop"),
        )
        self.assertLess(
            reset_body.index("_active_mesh_edit_source_part_output_mutation_blocked"),
            reset_body.index("source_role_overrides.pop"),
        )
        self.assertLess(
            remove_body.index("_active_mesh_edit_source_part_output_mutation_blocked"),
            remove_body.index("adjustment.enabled = False"),
        )

    def test_source_part_material_tuning_blocks_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py")
        guard_body = _function_source(source, "_active_mesh_edit_material_tuning_mutation_blocked")
        update_body = _function_source(source, "_update_selected_part_material_adjustment")

        self.assertIn("Active Mesh Editor source material tuning requires native material execution", guard_body)
        self.assertIn("Python adjustment mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertLess(
            update_body.index("_active_mesh_edit_material_tuning_mutation_blocked"),
            update_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            update_body.index("_active_mesh_edit_material_tuning_mutation_blocked"),
            update_body.index("adjustment.material_brightness ="),
        )
        self.assertLess(
            update_body.index("_active_mesh_edit_material_tuning_mutation_blocked"),
            update_body.index("_state.texture_overrides_dirty['dirty'] = True"),
        )
        self.assertLess(
            update_body.index("_active_mesh_edit_material_tuning_mutation_blocked"),
            update_body.index("_queue_material_edit_refresh("),
        )

    def test_copied_texture_actions_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_callback_factories.py")
        guard_start = source.index("def _active_mesh_edit_copied_texture_mutation_blocked(")
        guard_body = source[
            guard_start: source.index("def _update_selected_part_material_adjustment", guard_start)
        ]
        use_start = source.index("def _use_copied_original_texture_for_selected_source(")
        use_body = source[use_start: source.index("def _use_route_texture_for_selected_copied_source", use_start)]
        route_start = source.index("def _use_route_texture_for_selected_copied_source(")
        route_body = source[route_start: source.index("def _remove_copied_texture_from_selected_source", route_start)]
        remove_start = source.index("def _remove_copied_texture_from_selected_source(")
        remove_body = source[remove_start: source.index("def _load_selected_part_controls", remove_start)]

        self.assertIn("Active Mesh Editor copied-source texture routing requires native material execution", guard_body)
        self.assertIn("Python texture intent mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertLess(
            use_body.index("_active_mesh_edit_copied_texture_mutation_blocked"),
            use_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            use_body.index("_active_mesh_edit_copied_texture_mutation_blocked"),
            use_body.index("copied_original_texture_disabled_sources.discard"),
        )
        self.assertLess(
            route_body.index("_active_mesh_edit_copied_texture_mutation_blocked"),
            route_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            route_body.index("_active_mesh_edit_copied_texture_mutation_blocked"),
            route_body.index("copied_original_texture_disabled_sources.add"),
        )
        self.assertLess(
            remove_body.index("_active_mesh_edit_copied_texture_mutation_blocked"),
            remove_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            remove_body.index("_active_mesh_edit_copied_texture_mutation_blocked"),
            remove_body.index("copied_original_texture_intents_by_source.pop"),
        )
        for body in (use_body, route_body, remove_body):
            self.assertLess(
                body.index("_active_mesh_edit_copied_texture_mutation_blocked"),
                body.index("_queue_texture_preview_refresh()"),
            )

    def test_donor_material_actions_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_texture_callbacks.py")
        guard_body = _function_source(source, "_active_mesh_edit_donor_material_mutation_blocked")
        clear_body = _function_source(source, "_clear_selected_donor_material_source")
        apply_body = _function_source(source, "_apply_selected_donor_material")

        self.assertIn("Active Mesh Editor donor material routing requires native material execution", guard_body)
        self.assertIn("Python donor material plan mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertLess(
            clear_body.index("_active_mesh_edit_donor_material_mutation_blocked"),
            clear_body.index("donor_material_plans_by_target.pop"),
        )
        self.assertLess(
            clear_body.index("_active_mesh_edit_donor_material_mutation_blocked"),
            clear_body.index("_state.texture_overrides_dirty['dirty'] = True"),
        )
        self.assertLess(
            clear_body.index("_active_mesh_edit_donor_material_mutation_blocked"),
            clear_body.index("_queue_texture_preview_refresh()"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_donor_material_mutation_blocked"),
            apply_body.index("donor_material_plans_by_target[target_index] = plan_state.plan"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_donor_material_mutation_blocked"),
            apply_body.index("_state.texture_overrides_dirty['dirty'] = True"),
        )
        self.assertLess(
            apply_body.index("_active_mesh_edit_donor_material_mutation_blocked"),
            apply_body.index("_queue_texture_preview_refresh()"),
        )

    def test_added_part_texture_overrides_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_texture_callbacks.py")
        remaining_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py")
        guard_start = source.index("def _active_mesh_edit_added_part_texture_mutation_blocked(")
        guard_body = source[
            guard_start: source.index("def _assign_added_part_selected_texture", guard_start)
        ]
        assign_start = source.index("def _assign_added_part_selected_texture(")
        assign_body = source[assign_start: source.index("def _assign_detected_added_part_textures", assign_start)]
        detected_start = source.index("def _assign_detected_added_part_textures(")
        detected_body = source[detected_start: source.index("def _choose_added_part_texture", detected_start)]
        choose_start = source.index("def _choose_added_part_texture(")
        choose_body = source[choose_start: source.index("def _clear_added_part_texture_override", choose_start)]
        clear_start = source.index("def _clear_added_part_texture_override(")
        clear_body = source[clear_start: source.index("def _added_texture_tree_selection_changed", clear_start)]
        helper_guard_start = remaining_source.index("def _active_mesh_edit_added_part_texture_override_blocked(")
        helper_guard_body = remaining_source[
            helper_guard_start: remaining_source.index("def _set_added_part_texture_override", helper_guard_start)
        ]
        helper_start = remaining_source.index("def _set_added_part_texture_override(")
        helper_body = remaining_source[
            helper_start: remaining_source.index("return SimpleNamespace(_set_added_part_texture_override", helper_start)
        ]

        self.assertIn("Active Mesh Editor added-part texture overrides require native material execution", guard_body)
        self.assertIn("Python texture override mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertIn("Active Mesh Editor added-part texture overrides require native material execution", helper_guard_body)
        self.assertIn("Python texture override mutation fallback is disabled", helper_guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", helper_guard_body)
        for body in (assign_body, detected_body, choose_body, clear_body):
            self.assertLess(
                body.index("_active_mesh_edit_added_part_texture_mutation_blocked"),
                body.index("_set_added_part_texture_override"),
            )
        self.assertLess(
            helper_body.index("_active_mesh_edit_added_part_texture_override_blocked"),
            helper_body.index("source_material_texture_override_assignments[assignment_key]"),
        )
        self.assertLess(
            helper_body.index("_active_mesh_edit_added_part_texture_override_blocked"),
            helper_body.index("source_material_texture_override_assignments.pop"),
        )

    def test_texture_table_overrides_block_active_mesh_edit_mutation(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_texture_callbacks.py")
        guard_body = _function_source(source, "_active_mesh_edit_texture_table_mutation_blocked")
        set_body = _function_source(source, "_set_texture_row_assignment")

        self.assertIn("_state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')", source)
        self.assertIn("Active Mesh Editor texture table overrides require native material execution", guard_body)
        self.assertIn("Python texture override mutation fallback is disabled", guard_body)
        self.assertIn("_alignment_mesh_edit_tab_active()", guard_body)
        self.assertLess(
            set_body.index("_active_mesh_edit_texture_table_mutation_blocked"),
            set_body.index("_set_texture_row_assignment_helper"),
        )
        self.assertEqual(1, source.count("_set_texture_row_assignment_helper("))

    def test_selected_vertex_skin_weights_are_native_owned(self) -> None:
        service_source = _read("cdmw/services/mesh_service_rigging.py")
        facade_source = _read("cdmw/services/mesh_service.py")
        mesh_native_source = _read("cdmw/modding/mesh_native_core.py")
        native_core_source = _read("native/cdmw_mesh_core/src/main.cpp")

        self.assertIn("def _require_clean_python_skeleton_state(session: _MeshEditSession) -> None:", service_source)
        attach_skeleton_start = service_source.index("def attach_skeleton(")
        attach_skeleton_body = service_source[
            attach_skeleton_start: service_source.index("def set_pose_preview(", attach_skeleton_start)
        ]
        self.assertLess(
            attach_skeleton_body.index("_require_clean_python_skeleton_state(session)"),
            attach_skeleton_body.index("session.skeleton = skeleton"),
        )
        attach_animation_start = service_source.index("def attach_animation_clip(")
        attach_animation_body = service_source[
            attach_animation_start: service_source.index("def clear_animation_clip(", attach_animation_start)
        ]
        self.assertLess(
            attach_animation_body.index("_require_clean_python_skeleton_state(session)"),
            attach_animation_body.index("session.animation_clip = clip"),
        )

        adjust_start = service_source.index("def adjust_selected_vertex_bone_weight(")
        adjust_body = service_source[adjust_start: service_source.index("def normalize_selected_vertex_weights(", adjust_start)]
        self.assertIn("apply_native_mesh_skin_weights(", adjust_body)
        self.assertIn("native mesh editor skin weight edit unavailable; Python mesh state is stale", adjust_body)
        self.assertIn("self._push_history(session, prefer_native=True)", adjust_body)
        self.assertLess(
            adjust_body.index("self._push_history(session, prefer_native=True)"),
            adjust_body.index("apply_native_mesh_skin_weights("),
        )
        self.assertLess(adjust_body.index("apply_native_mesh_skin_weights("), adjust_body.index("_nudge_bone_weight("))
        self.assertIn("invalidate_native_mesh_session_submeshes(session.working_mesh, vertex_map.keys())", adjust_body)

        normalize_start = service_source.index("def normalize_selected_vertex_weights(")
        normalize_body = service_source[normalize_start: service_source.index("def transfer_selected_vertex_weights_from_source(", normalize_start)]
        self.assertIn("apply_native_mesh_skin_weights(", normalize_body)
        self.assertIn("native mesh editor skin weight edit unavailable; Python mesh state is stale", normalize_body)
        self.assertIn("self._push_history(session, prefer_native=True)", normalize_body)
        self.assertLess(
            normalize_body.index("self._push_history(session, prefer_native=True)"),
            normalize_body.index("apply_native_mesh_skin_weights("),
        )
        self.assertLess(normalize_body.index("apply_native_mesh_skin_weights("), normalize_body.index("_normalize_weight_row("))
        self.assertIn("invalidate_native_mesh_session_submeshes(session.working_mesh, vertex_map.keys())", normalize_body)

        transfer_start = service_source.index("def transfer_selected_vertex_weights_from_source(")
        transfer_body = service_source[transfer_start: service_source.index("def _require_clean_python_skeleton_state(", transfer_start)]
        self.assertIn("transfer_native_mesh_skin_weights_from_source(", transfer_body)
        self.assertIn("native mesh editor skin weight edit unavailable; Python mesh state is stale", transfer_body)
        self.assertIn("self._push_history(session, prefer_native=True)", transfer_body)
        self.assertLess(
            transfer_body.index("self._push_history(session, prefer_native=True)"),
            transfer_body.index("transfer_native_mesh_skin_weights_from_source("),
        )
        self.assertIn("invalidate_native_mesh_session_submeshes(session.working_mesh, selected_submeshes)", transfer_body)
        self.assertLess(
            transfer_body.index("invalidate_native_mesh_session_submeshes(session.working_mesh, selected_submeshes)"),
            transfer_body.index("transfer_native_mesh_skin_weights_from_source("),
        )
        self.assertLess(
            transfer_body.index("transfer_native_mesh_skin_weights_from_source("),
            transfer_body.index("_source_weight_row_for_transfer("),
        )
        self.assertIn("_allow_python_skin_weight_fallback(", transfer_body)
        self.assertLess(
            transfer_body.index("_allow_python_skin_weight_fallback("),
            transfer_body.index("_source_weight_row_for_transfer("),
        )
        self.assertIn("invalidate_native_mesh_session_submeshes(session.working_mesh, operations_by_submesh.keys())", transfer_body)
        self.assertIn("def _allow_python_skin_weight_fallback(", facade_source)
        skin_fallback_start = facade_source.index("def _allow_python_skin_weight_fallback(")
        skin_fallback_body = facade_source[
            skin_fallback_start: facade_source.index("def _delta_positions_by_vertex(", skin_fallback_start)
        ]
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_FACE_LIMIT", skin_fallback_body)
        self.assertNotIn("selected_vertex_count <= _PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT", skin_fallback_body)
        self.assertIn("Python skin weight fallback blocked; native mesh core is required for active Mesh Editor skin-weight edits", skin_fallback_body)
        self.assertIn("native_core_available=native_mesh_core_available()", skin_fallback_body)
        self.assertIn("native_core_disabled=bool(os.environ.get", skin_fallback_body)
        self.assertIn('raise RuntimeError("native mesh editor skin weight edit unavailable; Python skin weight fallback is disabled")', service_source)
        self.assertIn("return range(len(submesh.vertices or ()))", service_source)
        self.assertNotIn("return tuple(range(len(submesh.vertices or ())))", service_source)

        skin_bridge_start = mesh_native_source.index("def apply_native_mesh_skin_weights(")
        skin_bridge_body = mesh_native_source[skin_bridge_start: mesh_native_source.index("def build_native_region_volume_delta(", skin_bridge_start)]
        skin_report_apply_start = mesh_native_source.index("def _apply_native_skin_weight_report(")
        skin_report_apply_body = mesh_native_source[
            skin_report_apply_start: mesh_native_source.index("def apply_native_mesh_skin_weights(", skin_report_apply_start)
        ]
        self.assertIn("_changed_vertices_from_report_item(raw_item, vertex_count)", skin_report_apply_body)
        self.assertIn("len(changed_vertices) != changed_count", skin_report_apply_body)
        self.assertIn("changed_vertices_by_submesh: dict[int, Sequence[int] | set[int]] = {}", skin_report_apply_body)
        self.assertIn("_changed_vertices_for_report(changed_vertices)", skin_report_apply_body)
        self.assertNotIn("changed_vertices_by_submesh[submesh_index] = set(changed_vertices)", skin_report_apply_body)
        self.assertIn('"skin-weights-json"', skin_bridge_body)
        self.assertIn("def _selected_vertex_values(", mesh_native_source)
        self.assertIn("_selected_vertex_values(raw_vertices, vertex_count)", skin_bridge_body)
        self.assertIn("_selected_vertex_values(raw_values, target_vertex_count)", skin_bridge_body)
        self.assertIn("_put_selected_vertices_payload(item, prefix, selected", skin_bridge_body)
        self.assertNotIn("dict(selected_vertices_by_submesh or {}).items()", skin_bridge_body)
        self.assertIn("selected_map = selected_vertices_by_submesh if isinstance(selected_vertices_by_submesh, Mapping) else {}", skin_bridge_body)
        self.assertNotIn("selected_map = dict(selected_vertices_by_submesh or {})", skin_bridge_body)
        self.assertNotIn("tuple(selected_all_submeshes or ())", skin_bridge_body)
        region_volume_start = mesh_native_source.index("def build_native_region_volume_delta(")
        region_volume_body = mesh_native_source[
            region_volume_start:mesh_native_source.index("def _native_brush_edit_payload", region_volume_start)
        ]
        self.assertIn("_selected_vertex_values(raw_values, vertex_count)", region_volume_body)
        self.assertNotIn("values = tuple(raw_values or ())", region_volume_body)
        self.assertNotIn('vertices = tuple(getattr(submesh, "vertices", ()) or ())', region_volume_body)
        self.assertNotIn("tuple(raw_vertices or ())", skin_bridge_body)
        self.assertNotIn("tuple(raw_values or ())", skin_bridge_body)
        self.assertNotIn('target_vertices = tuple(getattr(target, "vertices", ()) or ())', skin_bridge_body)
        self.assertNotIn('source_vertices = tuple(getattr(source, "vertices", ()) or ())', skin_bridge_body)
        self.assertNotIn("sorted(selected)", skin_bridge_body)
        self.assertNotIn('item["selected_vertices_binary"] = _write_int_binary_payload', skin_bridge_body)
        self.assertIn('"bone_counts_output_path"', skin_bridge_body)
        self.assertIn("_ensure_native_mesh_session_submesh(", skin_bridge_body)
        self.assertIn("if not session_id:", skin_bridge_body)
        self.assertNotIn("\n                bone_payload = _write_bone_binary_payloads(", skin_bridge_body)
        self.assertNotIn('item["vertices_binary"] = _write_vec3_binary_payload', skin_bridge_body)
        self.assertNotIn("target_bone_payload = _write_bone_binary_payloads(", skin_bridge_body)
        self.assertNotIn("item.update(target_bone_payload)", skin_bridge_body)
        self.assertIn("_read_bone_binary_report_payloads(", mesh_native_source)
        self.assertIn("_mark_native_mesh_session_submeshes_current(mesh, affected)", mesh_native_source)
        self.assertIn("def transfer_native_mesh_skin_weights_from_source(", skin_bridge_body)
        self.assertIn('"operation": "transfer"', skin_bridge_body)
        self.assertIn('"source_vertices_binary"', skin_bridge_body)
        self.assertIn('"source_bone_counts_binary"', skin_bridge_body)
        self.assertIn('"bone_remap_enabled"', skin_bridge_body)
        self.assertIn('"selected_all_vertices"', skin_bridge_body)

        self.assertIn("std::vector<SubmeshSkinWeightsResult> run_skin_weights", native_core_source)
        skin_native_start = native_core_source.index("std::vector<SubmeshSkinWeightsResult> run_skin_weights")
        skin_native_body = native_core_source[skin_native_start: native_core_source.index("ObjRoundtripManifestSubmesh obj_manifest_submesh_from_item", skin_native_start)]
        self.assertIn("mesh_bones_from_item(item)", skin_native_body)
        self.assertIn("nudge_bone_weight_native", skin_native_body)
        self.assertIn("normalize_weight_row_native", skin_native_body)
        self.assertIn("source_bone_assignments_from_item(item)", skin_native_body)
        self.assertIn("closest_source_weight_sample_native", skin_native_body)
        self.assertIn("transfer_weight_row_native", skin_native_body)
        self.assertIn('operation != "adjust" && operation != "normalize" && operation != "transfer"', skin_native_body)
        self.assertIn("mutable_mesh_session_submesh_for_item(item)", skin_native_body)
        self.assertIn("write_double_binary_file(result.bone_weights_path", skin_native_body)
        self.assertNotIn("write_int_binary_file(result.changed_vertices_path, result.changed_vertices);", skin_native_body)
        skin_report_start = native_core_source.index("std::string skin_weights_report_json")
        skin_report_body = native_core_source[skin_report_start: native_core_source.index("std::string obj_export_report_json", skin_report_start)]
        self.assertIn("write_changed_vertices_report(out, result.changed_vertices, result.changed_vertices_path, changed_vertex_start)", skin_report_body)
        self.assertIn("changed_count", skin_report_body)
        self.assertIn('if (command == "skin-weights-json") return skin_weights_json_command(job_path, report_path);', native_core_source)

    def test_source_part_mutations_use_native_d3d11_triangle_refresh_before_python_preview_rebuild(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_source_part_mutation_callbacks.py")
        self.assertIn("_state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')", source)
        self.assertIn("_state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')", source)
        self.assertIn(
            "_state._mesh_edit_preview_source_indices = _state.context.get('_mesh_edit_preview_source_indices')",
            source,
        )
        self.assertIn(
            "_state._mesh_edit_replace_live_triangles_or_queue_rebuild = _state.context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')",
            source,
        )
        helper_body = _function_source(source, "_source_part_refresh_geometry_preview")
        self.assertIn("if callable(_state._alignment_d3d11_preview_active) and _state._alignment_d3d11_preview_active():", helper_body)
        self.assertIn("_mesh_edit_replace_live_triangles_or_queue_rebuild(", helper_body)
        self.assertIn("replace_all=replace_all", helper_body)
        self.assertIn("_source_part_current_preview_indices()", helper_body)
        self.assertIn("if _state._source_part_mesh_edit_active():", helper_body)
        self.assertIn("Active Mesh Editor source-part preview requires native D3D11 refresh; Python preview rebuild fallback is disabled.", helper_body)
        self.assertIn("_set_source_parts_preview_rebuild_pending(reason)", helper_body)
        self.assertIn("_queue_static_preview_rebuild()", helper_body)
        self.assertLess(
            helper_body.index("_mesh_edit_replace_live_triangles_or_queue_rebuild("),
            helper_body.index("parsed_mesh_to_preview_model("),
        )
        self.assertLess(
            helper_body.index("if _state._source_part_mesh_edit_active():"),
            helper_body.index("parsed_mesh_to_preview_model("),
        )
        active_block_body = _function_source(source, "_source_part_active_geometry_mutation_blocked")
        self.assertIn("if not _state._source_part_mesh_edit_active():", active_block_body)
        self.assertIn("Active Mesh Editor source-part topology changes require native geometry execution", active_block_body)
        self.assertIn("Python mesh mutation fallback is disabled", active_block_body)
        material_routing_guard_body = _function_source(source, "_source_part_material_routing_mutation_blocked")
        self.assertIn("if not _state._source_part_mesh_edit_active():", material_routing_guard_body)
        self.assertIn("Active Mesh Editor source-part material routing requires native material execution", material_routing_guard_body)
        self.assertIn("Python routing mutation fallback is disabled", material_routing_guard_body)
        rollback_capture_body = _function_source(source, "_source_part_append_capture_mesh_snapshot")
        rollback_restore_body = _function_source(source, "_source_part_append_restore_mesh_snapshot")
        rollback_restore_direct_body = _function_source(source, "_source_part_append_clone_parsed_mesh_snapshot")
        self.assertIn("snapshot_native_mesh_submeshes(mesh)", rollback_capture_body)
        self.assertIn("allow_python_full_mesh_clone_fallback(", rollback_capture_body)
        self.assertLess(
            rollback_capture_body.index("snapshot_native_mesh_submeshes(mesh)"),
            rollback_capture_body.index("clone_mesh_for_static_replacement_native_first("),
        )
        self.assertIn("fallback_allowed=_fallback_allowed", rollback_capture_body)
        self.assertNotIn("return clone_mesh_for_editing(mesh)", rollback_capture_body)
        self.assertIn("restore_native_mesh_submesh_snapshot(restored, snapshot)", rollback_restore_body)
        self.assertIn("return _state._source_part_append_clone_parsed_mesh_snapshot(snapshot)", rollback_restore_body)
        self.assertNotIn("return clone_mesh_for_editing(snapshot)", rollback_restore_direct_body)
        self.assertIn("'source_part.append_rollback_restore'", rollback_restore_direct_body)
        self.assertIn("_state.clone_mesh_for_static_replacement_native_first(", rollback_restore_direct_body)
        self.assertIn("fallback_allowed=_fallback_allowed", rollback_restore_direct_body)
        self.assertNotIn("clone_mesh_for_editing(snapshot)", rollback_restore_direct_body)

        delete_body = _function_source(source, "_delete_selected_source_parts")
        self.assertIn("if not resident_state_only and _state._source_part_active_geometry_mutation_blocked():", delete_body)
        self.assertIn("_source_part_refresh_geometry_preview(", delete_body)
        self.assertIn("replace_all=True", delete_body)
        self.assertNotIn("_set_replacement_preview_model(parsed_mesh_to_preview_model", delete_body)
        self.assertNotIn("_queue_static_preview_rebuild()", delete_body)
        self.assertLess(
            delete_body.index("if not resident_state_only and _state._source_part_active_geometry_mutation_blocked():"),
            delete_body.index("replacement_mesh_for_mapping.submeshes[:] = kept_submeshes"),
        )

        apply_body = _function_source(source, "_apply_source_part_preview_changes")
        self.assertIn("_source_part_refresh_geometry_preview(rebuild_reason, replace_all=True)", apply_body)
        self.assertNotIn("_queue_static_preview_rebuild()", apply_body)

        material_routing_body = _function_source(source, "_apply_source_material_grouped_routing")
        self.assertLess(
            material_routing_body.index("_source_part_material_routing_mutation_blocked"),
            material_routing_body.index("group_replacement_texture_sets("),
        )
        self.assertLess(
            material_routing_body.index("_source_part_material_routing_mutation_blocked"),
            material_routing_body.index("_push_geometry_undo_snapshot"),
        )
        self.assertLess(
            material_routing_body.index("_source_part_material_routing_mutation_blocked"),
            material_routing_body.index("texture_override_assignments.clear()"),
        )
        self.assertLess(
            material_routing_body.index("_source_part_material_routing_mutation_blocked"),
            material_routing_body.index("_set_mapping_indices"),
        )
        self.assertLess(
            material_routing_body.index("_source_part_material_routing_mutation_blocked"),
            material_routing_body.index("_refresh_source_material_plan"),
        )

        duplicate_body = _function_source(source, "_duplicate_selected_part")
        self.assertIn("if _state._source_part_active_geometry_mutation_blocked():", duplicate_body)
        self.assertIn("_source_part_refresh_geometry_preview(duplicate_route.status_text, (new_index,))", duplicate_body)
        self.assertNotIn("_set_replacement_preview_model(parsed_mesh_to_preview_model", duplicate_body)
        self.assertNotIn("_queue_static_preview_rebuild()", duplicate_body)
        self.assertLess(
            duplicate_body.index("if _state._source_part_active_geometry_mutation_blocked():"),
            duplicate_body.index("replacement_mesh_for_mapping.submeshes.append(working_copy)"),
        )

        append_body = _function_source(source, "_append_mesh_part_to_geometry") + "\n" + _function_source(source, "_rollback_cancelled_appended_mesh_part_import")
        self.assertIn("if _state._source_part_active_geometry_mutation_blocked():", append_body)
        self.assertIn("_state._source_part_refresh_geometry_preview('cancelled mesh part import', replace_all=True)", append_body)
        self.assertIn("_source_part_refresh_geometry_preview(", append_body)
        self.assertIn("append_result.source_indices", append_body)
        self.assertIn("_source_part_append_capture_mesh_snapshot(", append_body)
        self.assertIn("_source_part_append_restore_mesh_snapshot(", append_body)
        self.assertIn("_source_part_append_release_rollback_snapshots(append_rollback_snapshot)", append_body)
        self.assertLess(
            append_body.index("_source_part_append_capture_mesh_snapshot("),
            append_body.index("_source_part_append_rollback_snapshot_helper("),
        )
        self.assertNotIn("replacement_mesh=clone_mesh_for_editing(replacement_mesh_for_mapping)", append_body)
        self.assertNotIn("replacement_base_mesh=clone_mesh_for_editing(replacement_mesh_base_for_mapping)", append_body)
        self.assertNotIn("clone_mesh_for_editing(append_rollback_snapshot.replacement_mesh)", append_body)
        self.assertNotIn("clone_mesh_for_editing(append_rollback_snapshot.replacement_base_mesh)", append_body)
        self.assertNotIn("_set_replacement_preview_model(parsed_mesh_to_preview_model", append_body)
        self.assertNotIn("_queue_static_preview_rebuild()", append_body)
        self.assertLess(
            append_body.index("if _state._source_part_active_geometry_mutation_blocked():"),
            append_body.index("source_task_controller.start("),
        )
        self.assertIn("SceneImportRequest(source_path=source_path)", append_body)
        self.assertNotIn("import_scene_mesh_with_report(source_path)", append_body)

    def test_copied_original_append_uses_native_d3d11_triangle_refresh_before_python_preview_rebuild(self) -> None:
        remaining_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py")
        prompt_setup_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_prompt_setup.py")

        self.assertIn(
            "if callable(_mesh_edit_replace_live_triangles_or_queue_rebuild):",
            prompt_setup_source,
        )
        self.assertIn(
            'prompt_shell_context["_mesh_edit_replace_live_triangles_or_queue_rebuild"] = _mesh_edit_replace_live_triangles_or_queue_rebuild',
            prompt_setup_source,
        )
        self.assertIn("_state._alignment_d3d11_preview_active = _state.context.get('_alignment_d3d11_preview_active')", remaining_source)
        self.assertIn("_state._alignment_mesh_edit_tab_active = _state.context.get('_alignment_mesh_edit_tab_active')", remaining_source)
        self.assertIn("_state.prompt_shell_context = _state.context.get('prompt_shell_context')", remaining_source)
        self.assertIn("def _copied_original_live_triangle_replacer() -> object:", remaining_source)
        self.assertIn("_state.prompt_shell_context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')", remaining_source)

        helper_body = _function_source(remaining_source, "_refresh_copied_original_source_preview")
        self.assertIn("if callable(_state._alignment_d3d11_preview_active) and _state._alignment_d3d11_preview_active():", helper_body)
        self.assertIn("replacer((int(source_index),))", helper_body)
        self.assertIn("if _state._copied_original_mesh_edit_active():", helper_body)
        self.assertIn("Active Mesh Editor copied-source preview requires native D3D11 refresh; Python preview rebuild fallback is disabled.", helper_body)
        self.assertIn("_state._queue_static_preview_rebuild()", helper_body)
        self.assertLess(
            helper_body.index("replacer((int(source_index),))"),
            helper_body.index("parsed_mesh_to_preview_model("),
        )
        self.assertLess(
            helper_body.index("if _state._copied_original_mesh_edit_active():"),
            helper_body.index("parsed_mesh_to_preview_model("),
        )

        append_body = _function_source(remaining_source, "_append_original_part_payload_as_source")
        self.assertIn("if _state._copied_original_mesh_edit_active():", append_body)
        self.assertIn("Active Mesh Editor copied-original append requires native geometry execution", append_body)
        self.assertIn("Python mesh mutation fallback is disabled", append_body)
        self.assertIn("_state._refresh_copied_original_source_preview(new_source_index)", append_body)
        self.assertNotIn("_state.state.replacement_preview_model = _state.parsed_mesh_to_preview_model", append_body)
        self.assertNotIn("_state._queue_static_preview_rebuild()", append_body)
        self.assertLess(
            append_body.index("if _state._copied_original_mesh_edit_active():"),
            append_body.index("_state._push_geometry_undo_snapshot(undo_label)"),
        )
        self.assertLess(
            append_body.index("if _state._copied_original_mesh_edit_active():"),
            append_body.index("_state.state.replacement_mesh_for_mapping.submeshes.append(copied_part)"),
        )

    def test_selected_part_enable_uses_native_d3d11_triangle_refresh_before_static_rebuild(self) -> None:
        remaining_source = _read("cdmw/ui/archive_browser/static_replacement_dialog_remaining_callbacks.py")

        self.assertIn("def _selected_part_live_triangle_replacer() -> object:", remaining_source)
        self.assertIn("_state.prompt_shell_context.get('_mesh_edit_replace_live_triangles_or_queue_rebuild')", remaining_source)

        helper_body = _function_source(remaining_source, "_refresh_selected_part_enable_preview")
        self.assertIn("if callable(_state._alignment_d3d11_preview_active) and _state._alignment_d3d11_preview_active():", helper_body)
        self.assertIn("replacer(source_indices)", helper_body)
        self.assertIn("if _state._selected_part_mesh_edit_active():", helper_body)
        self.assertIn("Active Mesh Editor source enable preview requires native D3D11 refresh; Python preview rebuild fallback is disabled.", helper_body)
        self.assertIn("_state._set_source_parts_preview_rebuild_pending(_state._source_part_include_exclude_pending_reason_helper())", helper_body)
        self.assertIn("_state._queue_static_preview_rebuild()", helper_body)
        self.assertLess(
            helper_body.index("replacer(source_indices)"),
            helper_body.index("_state._queue_static_preview_rebuild()"),
        )
        self.assertLess(
            helper_body.index("if _state._selected_part_mesh_edit_active():"),
            helper_body.index("_state._queue_static_preview_rebuild()"),
        )

        update_body = _function_source(remaining_source, "_update_selected_part_adjustment")
        for token in (
            "mesh_edit_active = _state._selected_part_mesh_edit_active()", "if mesh_edit_active and apply_state.geometry_changed:",
            "Active Mesh Editor source-part transform changes require native geometry execution", "Python adjustment mutation fallback is disabled", "not resident_material_parameters_available(_state.dialog)",
            "Active Mesh Editor part visibility is unavailable until the resident material channel is ready.", "resident_updated = mesh_edit_active and send_resident_material_parameters(", "{'visible': bool(apply_state.enabled)}",
            "source_submesh_indices=(target_source_index,)", "elif mesh_edit_active:", "_state._set_source_parts_apply_pending(_state._source_part_include_exclude_pending_reason_helper())", "_state._refresh_selected_part_enable_preview(apply_state.target_indices)",
        ):
            self.assertIn(token, update_body)
        self.assertNotIn("_state._queue_static_preview_rebuild()", update_body)
        self.assertLess(
            update_body.index("if mesh_edit_active and apply_state.geometry_changed:"),
            update_body.index("if push_undo:"),
        )
        self.assertLess(
            update_body.index("if mesh_edit_active and apply_state.geometry_changed:"),
            update_body.index("adjustment.offset_xyz = apply_state.offset_xyz"),
        )


if __name__ == "__main__":
    unittest.main()
