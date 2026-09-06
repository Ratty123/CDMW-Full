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
        return "\n".join(_read(path) for path in (relative + ".facade", "cdmw/services/mesh_service_native_session.py", "cdmw/services/mesh_service_native_fallback_policy.py", "cdmw/services/mesh_service_native_clone.py", "cdmw/services/mesh_service_selection.py"))
    if relative == "cdmw/ui/preview/dotnet_host.py":
        return "\n".join(_read(path) for path in (relative + ".facade", "cdmw/ui/preview/dotnet_host_protocol.py"))
    if relative == "tools/dotnet_mesh_editor_experiment/MeshViewport.SelectionPicking.cs":
        return "\n".join(_read(path) for path in (relative + ".facade", "tools/dotnet_mesh_editor_experiment/MeshViewport.SelectionPaint.cs"))
    if relative == "tools/mesh_harness/real_dotnet.py":
        return "\n".join(_read(path) for path in (relative + ".facade", "tools/mesh_harness/real_dotnet_performance.py"))
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
            _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_session.py"),
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
        shell_source = _read("cdmw/ui/mesh_editor/workspace_shell_builder.py")

        self.assertIn("MeshFileSessionLoadWorker", tab_source)
        self.assertIn("class MeshFileSessionLoadWorker(QObject):", aux_worker_source)
        self.assertIn("mesh = service.load_mesh_file(self.path, run_roundtrip=True)", aux_worker_source)
        self.assertIn("thread.start(QThread.LowPriority)", tab_source)
        self.assertIn('"mesh_editor_tab"', close_source)
        self.assertIn("self.native_host_frame = RustMeshEditorHostFrame(", shell_source)
        self.assertFalse((ROOT / "cdmw/ui/native_d3d11_preview_host.py").exists())
        self.assertFalse((ROOT / "cdmw/ui/mesh_editor/native_preview_runtime.py").exists())

    def test_standalone_d3d11_update_failure_does_not_refresh_python_preview(self) -> None:
        tab_source = _read("cdmw/ui/mesh_editor/tab.py")

        update_start = tab_source.index("def _apply_standalone_native_update(")
        update_body = tab_source[update_start: tab_source.index("def _refresh_standalone_preview", update_start)]
        self.assertIn("if _native_update_has_payload(update) or self._standalone_native_preview_update_active():", update_body)
        self.assertIn('preview update failed; preview is stale.', update_body)
        self.assertIn("self.status_message_requested.emit(message, True)", update_body)
        self.assertLess(
            update_body.index("host = self.standalone_native_host"),
            update_body.index("if _native_update_has_payload(update) or self._standalone_native_preview_update_active():"),
        )
        self.assertNotIn("self._refresh_standalone_preview()", update_body)
        stroke_start = tab_source.index("def _apply_standalone_native_mesh_edit_stroke(")
        stroke_body = tab_source[stroke_start: tab_source.index("def _standalone_native_mesh_edit_stroke_command(", stroke_start)]
        self.assertIn("if not self._apply_standalone_native_update(native_update, result=result):", stroke_body)
        failure_branch = stroke_body[
            stroke_body.index("if not self._apply_standalone_native_update(native_update, result=result):"):
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
            ("cdmw/services/mesh_service.py", 'mesh=_service_call("clone_mesh_for_editing", session.working_mesh),  # type: ignore[arg-type]'),
            ("cdmw/services/mesh_service.py", '_service_call("clone_mesh_for_editing", mesh),  # type: ignore[return-value]'),
            ("cdmw/services/mesh_service.py", '_service_call("clone_mesh_for_editing", mesh),  # type: ignore[return-value]'),
            ("cdmw/services/mesh_service.py", 'cloned = _service_call("clone_mesh_for_editing", mesh)'),
            ("cdmw/services/model_library_preview.py", "preview_model = parsed_mesh_to_preview_model(scene_result.mesh)"),
            ("cdmw/modding/mesh_morph_sliders.py", "result = clone_mesh_for_editing(base_mesh)"),
            ("cdmw/ui/archive_browser/mesh_launch_flow.py", "preview_model = parsed_mesh_to_preview_model(scene_import_result.mesh)"),
            ("cdmw/ui/shell/model_library_bridge.py", "preview_model = parsed_mesh_to_preview_model(scene_result.mesh)"),
            (
                "cdmw/ui/archive_browser/static_replacement_prompt_preflight.py",
                "replacement_base = clone_mesh_for_editing(scene_result.mesh)",
            ),
            (
                "cdmw/ui/archive_browser/static_replacement_prompt_preflight.py",
                "replacement_mesh = clone_mesh_for_editing(replacement_base)",
            ),
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
                if (
                    '"clone_mesh_for_editing"' in stripped
                    or "clone_mesh_for_editing(" in stripped
                    or "parsed_mesh_to_preview_model(" in stripped
                ):
                    actual.append((relative, stripped))
        self.assertEqual(expected_boundary_or_fallback_sites, actual)



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
            restore_deltas_body.index('_service_call("recompute_mesh_normals", mesh)'),
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
        self.assertIn("_state.self.shell.set_status_message(str(exc))", static_capture_body)
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
        adapter_source = _read("cdmw/ui/mesh_editor/static_replacement_adapter.py")

        helper_start = state_source.index("def mesh_edit_all_vertices_by_source(")
        helper_body = state_source[helper_start: state_source.index("def mesh_edit_inverted_vertex_selection(", helper_start)]
        self.assertIn("selection: dict[int, range] = {}", helper_body)
        self.assertIn("selection[source_index] = range(vertex_count)", helper_body)
        self.assertNotIn("set(range(vertex_count))", helper_body)
        self.assertIn("if isinstance(indices, range) and indices.step == 1:", adapter_source)

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
        # Matched without its closing paren: what this pins is that the native writer is
        # asked first, not the exact keyword list, which grows as the export learns to
        # carry more of the asset.
        native_call = "_export_fbx_native(mesh, fbx_path, base, scale, skeleton=skeleton"
        self.assertIn(native_call, skeleton_body)
        self.assertLess(
            skeleton_body.index(native_call),
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
        # The bone list is built from the skeleton and reaches the job. It is bound to a
        # local first because the skin payload has to know whether there are any bones
        # to bind to, so the two are asserted separately rather than as one expression.
        self.assertIn("bone_payloads = _native_fbx_bone_payloads(skeleton)", bridge_source)
        self.assertIn('"bones": bone_payloads', bridge_source)
        self.assertIn("def _native_fbx_bone_payloads(", bridge_source)
        # Skin rows travel beside the geometry, or the rig arrives with no binding.
        self.assertIn("def _fbx_skin_rows(", bridge_source)
        self.assertIn("_write_bone_binary_payloads(prefix, skin_rows[0], skin_rows[1])", bridge_source)
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
        # The Classic side-panel Edit Mesh toolbar is removed outright: nothing
        # may construct the compact combos or the toolbar frame again. The
        # placeholders stay None so every getattr-guarded consumer is inert.
        self.assertNotIn("ClassicMeshEditSelectionModeCombo", ui_source)
        self.assertNotIn("ClassicMeshEditSelectionDepthCombo", ui_source)
        self.assertNotIn("ClassicMeshEditPreviewActionBar", ui_source)
        self.assertNotIn('setObjectName("ClassicMeshEditPreviewToolbar")', ui_source)
        self.assertIn("_state.compact_selection_mode_combo = None", ui_source)
        self.assertIn("_state.compact_selection_depth_combo = None", ui_source)
        self.assertIn("_state.classic_mesh_edit_action_bar = None", ui_source)
        self.assertIn("_state.mesh_edit_tool_combo.setCurrentIndex(_state.max(0, _state.mesh_edit_tool_combo.findData('orbit')))", ui_source)
        self.assertIn("button.setChecked(tool == current_tool)", refresh_body)
        self.assertIn("widget.setVisible(select_tool)", refresh_body)
        self.assertIn("widget.setEnabled(editing_requested and not topology_busy and select_tool)", refresh_body)
        self.assertIn("for element_only_control in (", refresh_body)
        self.assertIn("element_only_control.setVisible(False)", refresh_body)
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
        bridge_source = _read("cdmw/ui/preview/dotnet_host.py")
        controller_source = _read("cdmw/ui/mesh_editor/controller.py")

        self.assertIn('return self.controller.send_correlated(\n            "preview_vertex_update"', bridge_source)
        self.assertIn('return self.controller.send_correlated(\n            "preview_triangle_update"', bridge_source)
        self.assertIn('return self._reject_preview_mutation("preview_vertex_update")', bridge_source)
        self.assertIn('return self._reject_preview_mutation("preview_triangle_update")', bridge_source)
        self.assertIn('sender = getattr(host, "update_mesh_edit_vertices", None)', controller_source)
        self.assertIn('sender = getattr(host, "replace_mesh_edit_triangles", None)', controller_source)
        self.assertIn("_queue_mesh_edit_live_vertex_updates", main_source)

    def test_standalone_topology_preview_update_uses_affected_sources(self) -> None:
        controller_source = _read("cdmw/ui/mesh_editor/controller.py")
        bridge_source = _read("cdmw/ui/preview/dotnet_host.py")

        topology_start = controller_source.index("if result.topology_changed:")
        topology_body = controller_source[topology_start: controller_source.index('if result.action in {"material_assign", "material_copy"}', topology_start)]
        self.assertIn("_topology_refresh_source_indices(mesh, result)", topology_body)
        self.assertIn("mesh_edit_triangle_groups(", topology_body)
        self.assertIn("refresh_sources", topology_body)
        self.assertIn("replace_all_triangles=replace_all", topology_body)
        self.assertIn('"source_submesh_indices": _indices(source_submesh_indices or ())', bridge_source)

    def test_native_visible_selection_depth_and_double_click_guards_exist(self) -> None:

        self.assertFalse((ROOT / "native/cdmw_d3d11_preview/CMakeLists.txt").exists())





    def test_native_harness_stresses_brush_drag_without_global_input(self) -> None:
        source = "\n".join(
            _read(path)
            for path in (
                "tools/mesh_harness/constants.py",
                "tools/mesh_harness/win32_input.py",
                "tools/mesh_harness/real_dotnet.py",
                "tools/mesh_harness/real_dotnet_input.py",
                "tools/mesh_harness/png_evidence.py",
            )
        )

        self.assertIn("_WM_MOUSEMOVE = 0x0200", source)
        self.assertIn("_WM_LBUTTONDOWN = 0x0201", source)
        self.assertIn("_WM_LBUTTONUP = 0x0202", source)
        self.assertIn("def _send_mouse_message(", source)
        self.assertIn('interaction.name == "selection-brush-burst"', source)
        self.assertIn("phase = ordinal % 64", source)
        self.assertIn("request_resident_interaction_probe(", source)
        self.assertIn('mode="select_brush_vertex"', source)
        self.assertIn('"global_mouse_input_used": False', source)
        self.assertIn("tab._send_dotnet_protocol_message", source)
        self.assertIn("def _write_checker_png(", source)
        self.assertNotIn('interaction.name == "texture-update"', source)
        self.assertNotIn("build_texture_editor_resident_patch", source)
        self.assertIn("apply_resident_material_parameters", source)
        self.assertIn("exercise_deterministic_offscreen_capture", source)

    def test_mesh_edit_selection_ids_and_topology_replacement_are_safe_for_d3d11(self) -> None:
        main_source = _mesh_edit_source()
        payload_source = _read("cdmw/ui/archive_browser/static_replacement_mesh_edit_payload.py")
        bridge_source = _read("cdmw/ui/preview/dotnet_host.py")

        self.assertIn("source_indices_for_editor_id=_state._alignment_d3d11_source_indices_for_editor_id", main_source)
        self.assertIn("source_indices_for_editor_id(editor_submesh_index)", payload_source)
        self.assertIn("def _mesh_edit_clear_topology_selection(_state, _callbacks, ) -> None:", main_source)
        self.assertIn("def replace_mesh_edit_triangles(", bridge_source)
        self.assertIn('"replace_all": bool(replace_all)', bridge_source)
        self.assertIn('"source_submesh_indices": _indices(source_submesh_indices or ())', bridge_source)

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
        self.assertIn('_set_mesh_edit_row_visible(_state, "radius", sculpt_tool or remove_tool or brush_selection_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible(_state, "strength", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible(_state, "falloff", sculpt_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible(_state, "iterations", smooth_tool)', source)
        self.assertIn('"smooth_tool": tool == "smooth"', state_source)
        self.assertIn('_set_mesh_edit_row_visible(_state, "selection", select_tool)', source)
        self.assertIn('_set_mesh_edit_row_visible(_state, "depth", select_tool)', source)
        self.assertIn("_state.mesh_edit_mirror_checkbox.setVisible(sculpt_tool)", source)
        self.assertIn("for element_only_control in (", source)
        self.assertIn("element_only_control.setVisible(False)", source)
        self.assertNotIn("_state.mesh_edit_select_part_button.setVisible(select_tool)", source)
        self.assertNotIn("_state.mesh_edit_invert_selection_button.setVisible(select_tool)", source)
        self.assertNotIn("_state.mesh_edit_subdivide_selection_button.setVisible(select_tool)", source)
        self.assertNotIn("_state.mesh_edit_refine_smooth_selection_button.setVisible(select_tool)", source)
        self.assertNotIn("_state.mesh_edit_split_selection_button.setVisible(select_tool)", source)
        self.assertNotIn("_state.mesh_edit_delete_faces_button.setVisible(select_tool)", source)
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
        controller_source = _read("cdmw/ui/preview/dotnet_session.py")

        self.assertIn("_TRANSIENT_RETRY_DELAYS_MS = (500, 1_000, 2_000, 5_000)", controller_source)
        self.assertIn("_STEADY_RETRY_DELAY_MS = 5_000", controller_source)
        self.assertIn("_STATIC_RETRY_DELAY_MS = 30_000", controller_source)
        self.assertIn("def retry_now(self) -> None:", controller_source)
        self.assertIn("def deactivate(self) -> None:", controller_source)
        self.assertIn("def shutdown(self) -> None:", controller_source)
        self.assertIn("RustMeshEditorHostFrame(", _read("cdmw/ui/mesh_editor/workspace_shell_builder.py"))

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
        transition_start = source.index("def _mesh_edit_apply_preview_mode_transition(reason: str) -> None:")
        transition_body = source[transition_start: source.index("def _commit_spinbox_text", transition_start)]
        self.assertIn("context.get('alignment_d3d11_preview_host')", source)
        self.assertIn("sync_mesh_edit_preview_settings()", transition_body)
        self.assertNotIn("_alignment_d3d11_clear_active_package_helper(", transition_body)
        self.assertNotIn('_alignment_d3d11_invalidate_package_cache("mesh_edit_mode")', transition_body)
        self.assertNotIn("_queue_static_preview_refresh()", transition_body)
        self.assertNotIn("_queue_texture_preview_refresh()", transition_body)
        finalize_body = _function_source(source, "_mesh_editor_finalize_edit_mode_exit")
        post_exit_body = _function_source(source, "_mesh_editor_queue_post_edit_textured_preview_rebuild")
        toggle_body = _function_source(source, "_mesh_edit_enabled_toggled")
        self.assertIn("_state.mesh_edit_enabled_checkbox.setChecked(False)", finalize_body)
        self.assertIn("_callbacks._mesh_editor_sync_static_replacement_session_to_working_mesh", finalize_body)
        self.assertIn("_state._mesh_edit_apply_preview_mode_transition", post_exit_body)
        # The repaint runs from the exit's tail helper, which reports a failing
        # step instead of raising it into the caller. A raise there used to be
        # read as "finish failed" and re-armed mesh edit after the builder had
        # already left it, which is what made Finish Edit Mesh do nothing.
        tail_body = _function_source(source, "_mesh_editor_report_exit_tail")
        self.assertIn("_mesh_editor_report_exit_tail(", finalize_body)
        self.assertIn("_mesh_editor_queue_post_edit_textured_preview_rebuild", tail_body)
        self.assertIn("_record_mesh_edit_event", tail_body)
        self.assertIn("if not edit_enabled:", toggle_body)
        self.assertIn('_callbacks._mesh_editor_finalize_edit_mode_exit("mesh_edit_toggle", mesh_changed=True)', toggle_body)
        self.assertNotIn("_queue_texture_preview_refresh()", post_exit_body)
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
        self.assertIn('return clamp_model_preview_render_settings(geometry_settings), False, False, "material_refresh"', d3d11_presentation_source)
        self.assertIn('return clamp_model_preview_render_settings(geometry_settings), False, False, "mesh_edit_raw"', d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_all_support_maps = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_normal_map = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_material_map = True", d3d11_presentation_source)
        self.assertNotIn("fast_settings.disable_height_map = True", d3d11_presentation_source)
        self.assertIn("def _mesh_edit_raw_preview_active_value() -> bool:", source)
        self.assertIn("mesh_edit_raw_package = _state._mesh_edit_raw_preview_active_value()", source)
        self.assertIn("worker_use_textures = False", source)
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
        self.assertNotIn("alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", source)
        self.assertIn("_callbacks._mesh_edit_sync_d3d11_selection()", source)
        self.assertIn("_mesh_edit_replace_live_triangles_or_queue_rebuild(source_indices)", source)

    def test_action_bar_sculpt_tools_select_live_brush_and_move_stays_selection_drag(self) -> None:
        source = _mesh_edit_source()

        action_body = _function_source(source, "_mesh_editor_action_bar_action_requested")
        select_body = _function_source(source, "_select_mesh_edit_tool")
        self.assertNotIn("_callbacks._sync_mesh_edit_preview_settings()", select_body)
        self.assertEqual(select_body.count("_callbacks._refresh_mesh_edit_controls()"), 1)
        self.assertIn("currentIndexChanged owns the one control refresh", select_body)
        show_body = _function_source(source, "_show_mesh_edit_tab")
        self.assertNotIn("setCurrentWidget", show_body)
        self.assertNotIn("set_current_widget(mesh_edit_tab)", show_body)
        self.assertIn('if key == "transform_move":', action_body)
        self.assertIn('return _callbacks._select_mesh_edit_tool("move", active_action_key="transform_move")', action_body)
        self.assertIn('if command == "brush":', action_body)
        brush_block = action_body[action_body.index('if command == "brush":'): action_body.index('if command in _SERVICE_TOPOLOGY_ACTIONS:', action_body.index('if command == "brush":'))]
        self.assertIn("return _callbacks._select_mesh_edit_tool(tool, active_action_key=active_key)", brush_block)
        self.assertNotIn("_mesh_editor_apply_selected_brush_action", brush_block)
        self.assertIn('"move": ("move", "transform_move")', source)
        self.assertIn('if _state._mesh_edit_current_tool() == "move":\n        return "selection"', source)
        sync_body = _function_source(source, "_sync_mesh_editor_tab_action_state")
        self.assertIn('mode = "edit" if editing_active else "object"', sync_body)
        self.assertIn("selected_edge_count", sync_body)
        self.assertNotIn('mode = "sculpt" if editing_active and sculpt_tool', sync_body)
        refresh_body = _function_source(source, "_refresh_mesh_edit_controls")
        self.assertIn("selected_element_count = selected_count + selected_face_count + selected_edge_count", refresh_body)
        self.assertIn("selected_part_count = len(_state.mesh_edit_selected_source_indices)", refresh_body)
        self.assertIn("for element_only_control in (", refresh_body)
        self.assertIn("element_only_control.setVisible(False)", refresh_body)
        self.assertNotIn("_state.mesh_edit_subdivide_selection_button.setVisible(select_tool)", refresh_body)
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

    def test_native_mesh_edit_events_are_bound_to_direct_editor_callbacks(self) -> None:
        source = _read("cdmw/ui/archive_browser/static_replacement_dialog_ui_sections.py")

        connect_body = _function_source(source, "_setup_options_transform_step_016")
        self.assertIn("_state.preview_widget.mesh_edit_stroke_started.connect(lambda payload: _state._mesh_edit_begin_stroke(payload))", connect_body)
        self.assertIn("_state.preview_widget.mesh_edit_stroke_previewed.connect(lambda payload: _state._mesh_edit_apply_preview_payload(payload))", connect_body)
        self.assertIn("_state.preview_widget.mesh_edit_stroke_finished.connect(lambda payload: _state._mesh_edit_finish_stroke(payload))", connect_body)
        self.assertIn("_state.preview_widget.mesh_edit_selection_changed.connect(lambda payload: _state._mesh_edit_selection_changed(payload))", connect_body)
        direct_source = _read("cdmw/ui/mesh_editor/tab_shell_native_state.py")
        direct_body = _function_source(direct_source, "_wire_standalone_native_part_events")
        self.assertIn('(\"mesh_edit_stroke_started\", self._handle_standalone_native_mesh_edit_stroke_started)', direct_body)
        self.assertIn('(\"mesh_edit_stroke_previewed\", self._handle_standalone_native_mesh_edit_stroke_previewed)', direct_body)
        self.assertIn('(\"mesh_edit_stroke_finished\", self._handle_standalone_native_mesh_edit_stroke_finished)', direct_body)
        self.assertIn('(\"mesh_edit_selection_changed\", self._handle_standalone_native_mesh_edit_selection_changed)', direct_body)

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
        host_source = _read("cdmw/ui/preview/dotnet_host.py")
        dispatcher_source = _read("cdmw/ui/mesh_editor/live_stroke_dispatcher.py")

        for event in ("stroke_begin", "stroke_update", "stroke_end", "stroke_cancel"):
            self.assertIn(event, host_source)
        # end and cancel share one exit so a gesture can only close once.
        self.assertIn("_request_stream_id(previous) == _request_stream_id(newest)", dispatcher_source)

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
        self.assertIn('native_core_available=bool(_service_call("native_mesh_core_available"))', pose_fallback_body)
        self.assertIn("native_core_disabled=bool(os.environ.get", pose_fallback_body)
        pose_clone_start = service_source.index("def _clone_mesh_for_service_native_snapshot(")
        pose_clone_body = service_source[
            pose_clone_start: service_source.index("def _service_session_native_clone_supported(", pose_clone_start)
        ]
        self.assertIn('native_snapshot = _service_call("snapshot_native_mesh_submeshes", mesh)', pose_clone_body)
        self.assertIn('_service_call("restore_native_mesh_submesh_snapshot", restored_mesh, native_snapshot)', pose_clone_body)
        self.assertIn('_service_call("dispose_native_mesh_submesh_snapshot", native_snapshot)', pose_clone_body)
        self.assertIn("_allow_python_service_clone_fallback(mesh, operation, reason)", pose_clone_body)
        native_pose_clone_body = pose_clone_body[pose_clone_body.index('native_snapshot = _service_call("snapshot_native_mesh_submeshes", mesh)') :]
        self.assertLess(
            native_pose_clone_body.index('native_snapshot = _service_call("snapshot_native_mesh_submeshes", mesh)'),
            native_pose_clone_body.index('_service_call("clone_mesh_for_editing", mesh)'),
        )
        self.assertLess(
            native_pose_clone_body.index("_allow_python_service_clone_fallback(mesh, operation, reason)"),
            native_pose_clone_body.index('_service_call("clone_mesh_for_editing", mesh)'),
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
        self.assertIn("mesh = self._standalone_preview_mesh_snapshot()", sync_native_body)
        self.assertIn('build_rust_preview_package(', sync_native_body)
        self.assertLess(
            sync_native_body.index("mesh = self._standalone_preview_mesh_snapshot()"),
            sync_native_body.index("build_rust_preview_package("),
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
            "DOTNET_PREVIEW_VIEW_MODE_OPTIONS,",
            source,
        )
        self.assertIn("_populate_combo_options_helper(", source)
        self.assertIn("alignment_d3d11_view_mode_combo,", source)
        self.assertIn("(_state.alignment_d3d11_view_mode_combo, settings.d3d11_view_mode)", source)
        # The connect is wrapped across lines and prefixed with `controls.`;
        # match the call and its handler rather than one unwrapped line.
        connect_start = source.index("alignment_d3d11_view_mode_combo.currentIndexChanged.connect(")
        connect_block = source[connect_start:source.index(")", source.index("connect(", connect_start) + len("connect("))]
        self.assertIn("_apply_alignment_preview_render_settings", connect_block)
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
        native_merge_body = native_core_source[native_merge_start: native_core_source.index("std::string tangent_backend_summary", native_merge_start)]
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
        affine_body = native_core_source[affine_start: native_core_source.index("std::string tangent_backend_summary", affine_start)]
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
        host_source = _read("cdmw/ui/preview/dotnet_host.py")

        self.assertIn("def update_mesh_edit_vertices(", host_source)
        self.assertIn("def replace_mesh_edit_triangles(", host_source)
        self.assertNotIn("def _mesh_edit_apply_display_space_vertex_result(", source)


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
            "Active Mesh Editor static preview refresh requires Preview; Python preview rebuild fallback is disabled.",
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
        self.assertIn("Preview mesh edit preview produced no vertex update payload; preview is stale.", flush_body)
        self.assertLess(
            flush_body.index("if not groups:"),
            flush_body.index('sender = getattr('),
        )
        self.assertIn(
            "if changed_vertices_by_submesh and not immediate and _state._alignment_d3d11_preview_active():",
            update_body,
        )
        self.assertIn('"mesh_edit_live_preview_deferred"', update_body)
        self.assertIn("Preview mesh edit commands are unavailable; preview is stale.", update_body)
        self.assertIn("if _state._mesh_edit_tab_active():", update_body)
        self.assertIn("Active Mesh Editor live preview requires Preview", update_body)
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

    def test_mesh_edit_tool_refresh_does_not_republish_alignment_scene_or_display(self) -> None:
        source = _mesh_edit_source()

        sync_body = _function_source(source, "_sync_mesh_edit_preview_settings")
        self.assertNotIn("_state._clear_alignment_d3d11_fast_transform_state()", sync_body)
        self.assertNotIn("_state.alignment_d3d11_preview_host.set_alignment_state(", sync_body)
        self.assertNotIn(
            "_state.alignment_d3d11_preview_host.set_alignment_preview_transform()",
            sync_body,
        )
        self.assertIn("_state.alignment_d3d11_preview_host.set_mesh_edit_state(", sync_body)

        highlight_body = _function_source(source, "_sync_highlight_sets")
        self.assertIn("_state._selection_highlight_sets_state_helper(", highlight_body)
        self.assertIn("_state.mesh_edit_enabled_checkbox = _state.context.get('mesh_edit_enabled_checkbox')", source)
        self.assertIn("resident_active = bool(getattr(_state.dialog, '_mesh_editor_embedded_dotnet_active', False))", highlight_body)
        self.assertIn("preview_active = bool(d3d11_active or resident_active)", highlight_body)
        self.assertIn("mesh_edit_raw_active=bool(_state._mesh_edit_raw_preview_active()) if preview_active else False", highlight_body)
        self.assertIn("preview_gizmo_checked=bool(_state.preview_gizmo_checkbox.isChecked()) if preview_active else False", highlight_body)
        self.assertIn("mesh_edit_active=bool(_state.mesh_edit_enabled_checkbox.isChecked()) if preview_active else False", highlight_body)
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
        self.assertIn("selected_sources = _callbacks._mesh_editor_action_source_indices()", source)
        self.assertIn("source_indices=selected_sources", source)
        self.assertIn("for _state.element_only_control in (", source)
        self.assertIn("_state.element_only_control.setVisible(False)", source)
        self.assertNotIn("from cdmw.ui.mesh_editor.controller import apply_native_update_to_host", source)
        self.assertIn("from cdmw.ui.mesh_editor.static_replacement_adapter import StaticReplacementMeshEditSession", source)
        self.assertNotIn("mesh_editor_apply_static_replacement_edit = context.get", source)
        self.assertNotIn("return apply_static_replacement_edit(mesh, action, **params)", source)
        self.assertIn("active static Mesh Editor edit requires a native session revision", source)
        self.assertIn("active static Mesh Editor edit requires a native session", source)
        self.assertIn("def _mesh_editor_apply_static_replacement_edit(_state, _callbacks, mesh, action: str, **params: object):", source)
        self.assertIn("def _mesh_editor_apply_native_update(_state, _callbacks, native_update: object) -> bool:", source)
        self.assertIn('sender = getattr(_state.dialog, "_mesh_editor_embedded_send_native_update", None)', source)
        self.assertIn("and sender(native_update, commit_embedded=False)", source)
        self.assertNotIn("apply_native_update_to_host(\n        _state.alignment_d3d11_preview_host", source)
        self.assertIn("mesh_editor_static_replacement_session_state", source)
        self.assertIn("_mesh_editor_embedded_session_id", source)
        self.assertIn('session_id = f"static-replacement-{uuid4().hex}"', source)
        self.assertIn("StaticReplacementMeshEditSession(session_id=session_id)", source)
        self.assertIn("_state.mesh_editor_static_replacement_session_state[\"revision\"] = current_revision + (1 if changed else 0)", source)
        result_body = static_adapter_source[static_adapter_source.index("    def _result("):static_adapter_source.index("def apply_static_replacement_edit(", static_adapter_source.index("    def _result("))]
        self.assertNotIn("NATIVE_EDITOR_SESSION_COMMANDS", static_adapter_source)
        open_start = static_adapter_source.index("    def open(self, mesh: ParsedMesh) -> None:")
        open_body = static_adapter_source[open_start:static_adapter_source.index("\n    def close(", open_start)]
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
        self.assertIn("_callbacks._mesh_edit_clear_topology_selection()", split_commit_body)
        self.assertNotIn("alignment_d3d11_preview_host.clear_mesh_edit_vertex_selection()", split_commit_body)
        self.assertIn("_state.appended_source_indices.add(new_source_index)", split_commit_body)
        self.assertIn('_state.selected_source_part["index"] = new_source_index', split_commit_body)
        self.assertNotIn("source_part_adjustments[new_source_index]", split_commit_body)
        self.assertNotIn("deepcopy(source_adjustment)", split_commit_body)
        self.assertLess(
            split_commit_body.index("_callbacks._mesh_edit_clear_topology_selection()"),
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
        self.assertIn("Active Mesh Editor preview refresh requires Preview", refresh_preview_body)
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
        self.assertIn("Active Mesh Editor commit requires Preview refresh", commit_working_body)
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
        self.assertIn('"_mesh_editor_embedded_send_native_update"', selection_sync_body)
        self.assertIn("_state.MeshEditorNativeUpdate(", selection_sync_body)
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
        topology_refresh_body = mesh_controller_source[topology_refresh_start:]
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
        self.assertIn("_state.self.shell.set_status_message(message, error=True)", blocker_body)
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
            flush_body.index("_state._apply_current_glow_color_to_role_overrides()"),
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
        self.assertIn("self._push_history(", adjust_body)
        self.assertIn("prefer_native=True", adjust_body)
        self.assertLess(
            adjust_body.index("self._push_history("),
            adjust_body.index("apply_native_mesh_skin_weights("),
        )
        self.assertLess(adjust_body.index("apply_native_mesh_skin_weights("), adjust_body.index("_nudge_bone_weight("))
        self.assertIn("invalidate_native_mesh_session_submeshes(session.working_mesh, vertex_map.keys())", adjust_body)

        normalize_start = service_source.index("def normalize_selected_vertex_weights(")
        normalize_body = service_source[normalize_start: service_source.index("def transfer_selected_vertex_weights_from_source(", normalize_start)]
        self.assertIn("apply_native_mesh_skin_weights(", normalize_body)
        self.assertIn("native mesh editor skin weight edit unavailable; Python mesh state is stale", normalize_body)
        self.assertIn("self._push_history(", normalize_body)
        self.assertIn("prefer_native=True", normalize_body)
        self.assertLess(
            normalize_body.index("self._push_history("),
            normalize_body.index("apply_native_mesh_skin_weights("),
        )
        self.assertLess(normalize_body.index("apply_native_mesh_skin_weights("), normalize_body.index("_normalize_weight_row("))
        self.assertIn("invalidate_native_mesh_session_submeshes(session.working_mesh, vertex_map.keys())", normalize_body)

        transfer_start = service_source.index("def transfer_selected_vertex_weights_from_source(")
        transfer_body = service_source[transfer_start: service_source.index("def _require_clean_python_skeleton_state(", transfer_start)]
        self.assertIn("transfer_native_mesh_skin_weights_from_source(", transfer_body)
        self.assertIn("native mesh editor skin weight edit unavailable; Python mesh state is stale", transfer_body)
        self.assertIn("self._push_history(", transfer_body)
        self.assertIn("prefer_native=True", transfer_body)
        self.assertLess(
            transfer_body.index("self._push_history("),
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
        # Bound the function by the next top-level def rather than by a named
        # neighbour. The fallback policy and the delta helpers are separate
        # owners now, so which one follows the other in the composed source is
        # an ordering detail this guard should not depend on.
        skin_fallback_end = facade_source.find("\ndef ", skin_fallback_start + 1)
        skin_fallback_body = facade_source[
            skin_fallback_start: skin_fallback_end if skin_fallback_end != -1 else len(facade_source)
        ]
        self.assertNotIn("_PYTHON_MESH_SELECTION_FALLBACK_FACE_LIMIT", skin_fallback_body)
        self.assertNotIn("selected_vertex_count <= _PYTHON_MESH_SELECTION_FALLBACK_VERTEX_LIMIT", skin_fallback_body)
        self.assertIn("Python skin weight fallback blocked; native mesh core is required for active Mesh Editor skin-weight edits", skin_fallback_body)
        self.assertIn('native_core_available=bool(_service_call("native_mesh_core_available"))', skin_fallback_body)
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
        self.assertIn("Active Mesh Editor source-part preview requires a Preview refresh; software preview fallback is disabled.", helper_body)
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
        self.assertIn("Active Mesh Editor copied-source preview requires Preview refresh; Python preview rebuild fallback is disabled.", helper_body)
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
        self.assertIn("Active Mesh Editor source enable preview requires Preview refresh; Python preview rebuild fallback is disabled.", helper_body)
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
