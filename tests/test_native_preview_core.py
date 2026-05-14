from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from cdmw.models import ArchiveEntry, ModelPreviewRenderSettings
from cdmw.rendering import native_preview_core
from cdmw.rendering.native_preview_core import (
    NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES,
    NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS,
    NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES,
    NativePreviewCoreServiceClient,
    build_native_preview_core_job,
    run_native_preview_core_preview_job,
)


def _entry() -> ArchiveEntry:
    return ArchiveEntry(
        path="character/model/example/cd_example.pac",
        pamt_path=Path("C:/game/0009/0.pamt"),
        paz_file=Path("C:/game/0009/1.paz"),
        offset=128,
        comp_size=64,
        orig_size=64,
        flags=0,
        paz_index=1,
    )


class _FakeServiceStdin:
    def __init__(self) -> None:
        self.writes: list[str] = []

    def write(self, value: str) -> int:
        self.writes.append(value)
        return len(value)

    def flush(self) -> None:
        return


class _FakeServiceProcess:
    def __init__(self) -> None:
        self.stdin = _FakeServiceStdin()
        self.stdout = object()
        self.alive = True
        self.killed = False

    def poll(self) -> object:
        return None if self.alive else 0

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self.alive = False
        return 0

    def kill(self) -> None:
        self.killed = True
        self.alive = False


class NativePreviewCoreTests(unittest.TestCase):
    def test_build_job_carries_archive_entry_and_schema_v8(self) -> None:
        job = build_native_preview_core_job(
            _entry(),
            cache_root=Path("C:/cache/native"),
            output_root=Path("C:/cache/package"),
            render_settings=ModelPreviewRenderSettings(),
            package_root=Path("C:/game"),
        )

        self.assertEqual(8, job["schema_version"])
        self.assertEqual("d3d11", job["renderer_backend"])
        self.assertEqual("character/model/example/cd_example.pac", job["entry"]["path"])
        self.assertEqual("C:\\game\\0009\\1.paz", job["entry"]["paz_file"])
        self.assertEqual("mesh_base_first", job["render_settings"]["visible_texture_mode"])
        self.assertEqual("lit", job["render_settings"]["render_diagnostic_mode"])
        self.assertTrue(job["capabilities"]["direct_dds"])
        self.assertTrue(job["capabilities"]["material_graph"])
        self.assertEqual(3, job["capabilities"]["material_graph_version"])
        self.assertFalse(job["capabilities"]["python_fallback_allowed"])
        self.assertTrue(job["capabilities"]["native_material_runtime"])

    def test_missing_binary_returns_fallback_attempt(self) -> None:
        with patch.object(native_preview_core, "find_native_preview_core_binary", return_value=None):
            attempt = run_native_preview_core_preview_job(
                _entry(),
                cache_root=Path("C:/cache/native"),
                timeout_seconds=0.5,
            )

        self.assertEqual("missing", attempt.status)
        self.assertFalse(attempt.succeeded)
        self.assertIn("unavailable", attempt.diagnostic_line())

    def test_report_success_returns_package_path(self) -> None:
        def fake_run_process(cmd, **_kwargs):
            report_path = Path(cmd[3])
            report_path.write_text(
                json.dumps(
                    {
                        "status": "ok",
                        "package_path": "C:/cache/native/package_001",
                        "backend": "cdmw_preview_core_0.1",
                        "decoded_cache_job_hits": 2,
                        "decoded_cache_job_misses": 1,
                    }
                ),
                encoding="utf-8",
            )
            return 0, "", ""

        with tempfile.TemporaryDirectory() as temp_dir:
            fake_binary = Path(temp_dir) / "cdmw-preview-core.exe"
            fake_binary.write_text("stub", encoding="utf-8")
            with (
                patch.object(native_preview_core, "find_native_preview_core_binary", return_value=fake_binary),
                patch.object(native_preview_core, "run_process_with_cancellation", side_effect=fake_run_process),
            ):
                attempt = run_native_preview_core_preview_job(
                    _entry(),
                    cache_root=Path(temp_dir) / "cache",
                    timeout_seconds=0.5,
                    use_service=False,
                )

        self.assertTrue(attempt.succeeded)
        self.assertEqual("C:/cache/native/package_001", attempt.package_path)
        self.assertIn("cache=2/1", attempt.diagnostic_line())

    def test_native_preview_core_is_bundled_and_archive_worker_attempts_it(self) -> None:
        spec_text = Path("CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
        build_text = Path("build_native_windows.ps1").read_text(encoding="utf-8")
        main_window_text = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        source_text = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        d3d11_text = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("cdmw-preview-core.exe", spec_text)
        self.assertIn("native\\cdmw_preview_core", build_text)
        self.assertIn("run_native_preview_core_preview_job", main_window_text)
        self.assertIn("native_preview_core_enabled", main_window_text)
        self.assertIn("_validate_d3d11_preview_package_paths", main_window_text)
        self.assertIn("renderer:", main_window_text)
        self.assertIn("d3d11_renderer_start_blocked_invalid_package", main_window_text)
        self.assertIn("preview-job", source_text)
        self.assertIn("name-index-job", source_text)
        self.assertIn("--service", source_text)
        self.assertIn("native_diagnostics.h", source_text)
        self.assertIn("--diagnostic-log", source_text)
        self.assertIn("--crash-dir", source_text)
        self.assertIn("preview_job_start", source_text)
        self.assertIn("service_start", source_text)
        self.assertIn("_native_diagnostic_args", Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8"))
        self.assertIn("parse_pac_submeshes", source_text)
        self.assertIn("crypt_chacha20_filename", source_text)
        self.assertIn("lz4_decompress_block", source_text)
        self.assertIn("dds_textures", source_text)
        self.assertIn("parse_pam_submeshes", source_text)
        self.assertIn("parse_pamlod_submeshes", source_text)
        self.assertIn("material_sidecars", source_text)
        self.assertIn("native_sidecar_index", source_text)
        self.assertIn("shader_rule_for_family", source_text)
        self.assertIn("role_from_parameter_shader_and_name", source_text)
        self.assertIn("packed_channels_for_role", source_text)
        self.assertIn("texture_flip_vertical", source_text)
        self.assertIn("legacy_no_flip", source_text)
        self.assertIn("support_role_requires_material_scope", source_text)
        self.assertIn("rejected_texture_examples", source_text)
        self.assertIn("skin/hair visible layer albedo held", source_text)
        self.assertIn("shader_rule_holds_layer_albedo", source_text)
        self.assertIn("material_output_quality", source_text)
        self.assertIn("decoded_cache_job_hits", source_text)
        self.assertIn("prune_decoded_entry_cache", source_text)
        self.assertIn("kDecodedEntryCacheMaxEntries = 512", source_text)
        self.assertIn("kDecodedEntryCacheMaxBytes = 256ull * 1024ull * 1024ull", source_text)
        self.assertIn("kDecodedEntryCacheMaxSingleBytes = 64ull * 1024ull * 1024ull", source_text)
        self.assertIn("kDecodedEntryCacheRecycleBytes = 192ull * 1024ull * 1024ull", source_text)
        self.assertIn("kServiceMaxJobs = 32", source_text)
        self.assertIn("kServicePrivateRecycleBytes = 768ull * 1024ull * 1024ull", source_text)
        self.assertIn("process_private_bytes", source_text)
        self.assertIn("service_recycle_reason", source_text)
        self.assertIn("_get_native_preview_core_service", Path("cdmw/rendering/native_preview_core.py").read_text(encoding="utf-8"))
        self.assertIn("sampler_max_anisotropy", d3d11_text)
        self.assertIn("sampler_recreate_count", d3d11_text)

    def test_preview_core_service_recycles_after_job_count_limit(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = NativePreviewCoreServiceClient(temp_path / "cdmw-preview-core.exe")
            fake_process = _FakeServiceProcess()
            active_report = [temp_path / "report.json"]

            def fake_start(*_args, **_kwargs) -> None:
                client._process = fake_process

            def fake_read(*_args, **_kwargs) -> str:
                active_report[0].write_text(
                    json.dumps({"status": "ok", "decoded_cache_bytes": 0, "process_private_bytes": 0}),
                    encoding="utf-8",
                )
                return '{"status":"ok"}'

            with (
                patch.object(client, "_start_locked", side_effect=fake_start),
                patch.object(client, "_read_stdout_line_locked", side_effect=fake_read),
            ):
                for index in range(NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS):
                    active_report[0] = temp_path / f"report_{index}.json"
                    client.preview_job(temp_path / "job.json", active_report[0], timeout_seconds=0.5)

            report = json.loads(active_report[0].read_text(encoding="utf-8"))
            self.assertIsNone(client._process)
            self.assertEqual("job_count", report["service_recycle_reason"])
            self.assertEqual(NATIVE_PREVIEW_CORE_SERVICE_MAX_JOBS, report["service_job_count"])
            self.assertTrue(any('"shutdown"' in write for write in fake_process.stdin.writes))

    def test_preview_core_service_recycles_after_decoded_cache_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = NativePreviewCoreServiceClient(temp_path / "cdmw-preview-core.exe")
            fake_process = _FakeServiceProcess()
            report_path = temp_path / "report.json"

            def fake_start(*_args, **_kwargs) -> None:
                client._process = fake_process

            def fake_read(*_args, **_kwargs) -> str:
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "decoded_cache_bytes": NATIVE_PREVIEW_CORE_SERVICE_CACHE_RECYCLE_BYTES + 1,
                            "process_private_bytes": 0,
                        }
                    ),
                    encoding="utf-8",
                )
                return '{"status":"ok"}'

            with (
                patch.object(client, "_start_locked", side_effect=fake_start),
                patch.object(client, "_read_stdout_line_locked", side_effect=fake_read),
            ):
                client.preview_job(temp_path / "job.json", report_path, timeout_seconds=0.5)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIsNone(client._process)
            self.assertEqual("decoded_cache_bytes", report["service_recycle_reason"])

    def test_preview_core_service_recycles_after_private_memory_threshold(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_path = Path(temp_dir)
            client = NativePreviewCoreServiceClient(temp_path / "cdmw-preview-core.exe")
            fake_process = _FakeServiceProcess()
            report_path = temp_path / "report.json"

            def fake_start(*_args, **_kwargs) -> None:
                client._process = fake_process

            def fake_read(*_args, **_kwargs) -> str:
                report_path.write_text(
                    json.dumps(
                        {
                            "status": "ok",
                            "decoded_cache_bytes": 0,
                            "process_private_bytes": NATIVE_PREVIEW_CORE_SERVICE_PRIVATE_RECYCLE_BYTES + 1,
                        }
                    ),
                    encoding="utf-8",
                )
                return '{"status":"ok"}'

            with (
                patch.object(client, "_start_locked", side_effect=fake_start),
                patch.object(client, "_read_stdout_line_locked", side_effect=fake_read),
            ):
                client.preview_job(temp_path / "job.json", report_path, timeout_seconds=0.5)

            report = json.loads(report_path.read_text(encoding="utf-8"))
            self.assertIsNone(client._process)
            self.assertEqual("process_private_bytes", report["service_recycle_reason"])

    def test_archive_preview_worker_owns_native_preview_core_helpers(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")
        archive_worker_start = source.index("class ArchivePreviewWorker(QObject):")
        d3d11_worker_start = source.index("class ArchiveD3D11PackageWorker(QObject):")
        archive_worker_source = source[archive_worker_start:d3d11_worker_start]
        d3d11_worker_source = source[d3d11_worker_start:source.index("class AlignmentD3D11PackageWorker(QObject):")]

        self.assertIn("def _try_native_preview_core", archive_worker_source)
        self.assertIn("def _native_preview_core_result", archive_worker_source)
        self.assertIn("def _attach_native_preview_core_note", archive_worker_source)
        self.assertNotIn("def _try_native_preview_core", d3d11_worker_source)
        self.assertNotIn("self._try_native_preview_core()", d3d11_worker_source)

    def test_archive_browser_has_native_preview_prefetch_worker(self) -> None:
        source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("class ArchiveNativePreviewPrefetchWorker(QObject):", source)
        self.assertIn("archive_native_prefetch_timer", source)
        self.assertIn("def _archive_native_prefetch_candidate_entries", source)
        self.assertIn("def _start_archive_native_preview_prefetch", source)
        self.assertIn("def _stop_archive_native_preview_prefetch", source)
        self.assertIn("archive_native_prefetch_thread", source)
        self.assertIn("timeout_seconds=5.0", source)
        self.assertIn("run_native_preview_core_preview_job", source)

    def test_static_native_material_index_prefers_exact_sidecars(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('job.extension == ".pam" || job.extension == ".pamlod"', source)
        self.assertIn("!candidates.empty()", source)
        self.assertIn("return candidates;", source)

    def test_native_material_index_preserves_pami_roles_and_scopes_inputs(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn('xml_attr_value_from_map(attrs, {"_name", "StringItemID", "Name"})', source)
        self.assertIn('xml_attr_value_from_map(attrs, {"Value", "_path"})', source)
        self.assertIn("collect_xml_tag_blocks(scope_text, \"MaterialParameterTexture\")", source)
        self.assertIn('"PrimitiveName"', source)
        self.assertIn("relevant_bindings_for_mesh", source)
        self.assertIn("material_identity_requires_exact_path_match", source)
        self.assertIn("scoped_materials.size() <= 1", source)
        self.assertIn("native material inputs scoped to this batch", source)
        self.assertIn('p.find("colorblendingmask")', source)
        self.assertIn('material_output_quality = "exact"', source)

    def test_native_material_index_reads_technique_parameter_declarations(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("struct TechniqueParameterInfo", source)
        self.assertIn("cached_technique_index", source)
        self.assertIn("cached_package_technique_index", source)
        self.assertIn("package_root_pamt_paths", source)
        self.assertIn("technique_parameter_for_name", source)
        self.assertIn("srgb_mode_for_role", source)
        self.assertIn("srgb_mode", source)
        self.assertIn("parameter_declared_by", source)
        self.assertIn("native technique index: files=", source)

    def test_native_preview_core_reports_material_quality_gate(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        python_source = Path("cdmw/ui/main_window.py").read_text(encoding="utf-8")

        self.assertIn("material_quality_safe", source)
        self.assertIn("base_low_res_count", source)
        self.assertIn("base_low_confidence_count", source)
        self.assertIn("base_technical_count", source)
        self.assertIn("native_base_quality", source)
        self.assertIn("selected_texture_examples", source)
        self.assertIn("job_allows_texture_role", source)
        self.assertIn("visible_texture_mode", source)
        self.assertIn("best_base_binding_for_mode", source)
        self.assertIn("visible_class_for_binding", source)
        self.assertIn("technical_for_visible_base", source)
        self.assertIn("native_asset_family_json", source)
        self.assertIn("asset_family_reference_count", source)
        self.assertIn("kNativePackageSchemaVersion", source)
        self.assertIn("kNativeMaterialGraphVersion", source)
        self.assertIn("NativeMaterialGraph", source)
        self.assertIn("native material graph: version=", source)
        self.assertIn("material_semantics_version", source)
        self.assertIn("material_graph_version", source)
        self.assertIn("material_slots_json", source)
        self.assertIn("selection_decisions_json", source)
        self.assertIn('\\"dds_upload_policy\\"', source)
        self.assertIn("collect_xml_tag_blocks", source)
        self.assertIn("add_layer_family_sibling_refs", source)
        self.assertIn("cached_parsed_material_sidecar", source)
        self.assertIn("sidecar_parse_cache_job_hits", source)
        self.assertIn("extract_material_parameters", source)
        self.assertIn("compile_material_layers", source)
        self.assertIn("material_layers", source)
        self.assertIn("primary_material_layer", source)
        self.assertIn("layer_role", source)
        self.assertIn("evidence_grade", source)
        self.assertIn("_native_preview_core_manifest_metadata", python_source)
        self.assertIn("Native Asset Family: schema=v", python_source)
        self.assertIn("D3D11 runtime is native-only", python_source)
        self.assertIn("_native_preview_core_failure_result", python_source)
        self.assertNotIn("_native_preview_core_reference_metadata", python_source)
        self.assertNotIn("compatibility fallback used", python_source)
        self.assertNotIn("requires Python material resolver", python_source)
        self.assertNotIn("_native_preview_core_quality_fallback_reason", python_source)
        self.assertNotIn("Native Preview Core: material quality fallback", python_source)
        self.assertIn("D3D11 package source: native-core", python_source)

    def test_native_base_selection_promotes_layer_diffuse_over_overlay(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")
        selector_start = source.index("static const TextureBinding* best_base_binding_for_mode")
        selector_end = source.index("static std::string shader_rule_for_family", selector_start)
        selector = source[selector_start:selector_end]
        visible_start = source.index("static std::string visible_class_for_binding")
        visible_end = source.index("static bool visible_class_allowed_for_mode", visible_start)
        visible = source[visible_start:visible_end]

        self.assertIn('hint.find("overlaycolor")', visible)
        self.assertIn("low_authority_base_path(raw_path)", visible)
        self.assertIn('return "visible_generic";', visible)
        self.assertIn('visible_class == "layer_visible"', source)
        self.assertIn("has_non_low_authority_visible_base", selector)
        self.assertIn("if (low_authority && has_non_low_authority_visible_base)", selector)
        self.assertIn('parameter_key.find("detaildiffuse")', selector)
        self.assertIn("score -= 220", selector)
        self.assertIn("!base_low_authority", source)
        self.assertIn("lookup_relevant", source)
        self.assertIn("if (!result.empty() || job.package_root.empty()) return result;", source)
        self.assertNotIn("by_path", source)

    def test_d3d11_host_does_not_use_rich_material_inputs_as_base_override(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")
        parse_start = source.index("static std::vector<PreviewBatch> parse_manifest_batches")
        parse_end = source.index("static ViewSettings parse_view_settings", parse_start)
        parse_source = source[parse_start:parse_end]

        self.assertIn('batch.base_dds = dds_slot_source(object, "base");', parse_source)
        self.assertNotIn('best_material_dds_for_role(object, "base")', parse_source)

    def test_d3d11_host_consumes_schema_v8_material_layer_stack(self) -> None:
        source = Path("native/cdmw_d3d11_preview/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("kMaxMaterialLayers = 4", source)
        self.assertIn("parse_material_layers", source)
        self.assertIn("json_object_array_field", source)
        self.assertIn("parse_primary_material_layer", source)
        self.assertIn("Texture2D layer0_diffuse_tex : register(t9)", source)
        self.assertIn("Texture2D layer3_diffuse_tex : register(t12)", source)
        self.assertIn("Texture2D layer0_mask_tex : register(t13)", source)
        self.assertIn("Texture2D layer0_material_tex : register(t17)", source)
        self.assertIn("Texture2D layer0_normal_tex : register(t21)", source)
        self.assertIn("Texture2D layer0_height_tex : register(t25)", source)
        self.assertIn("constants.flags4 = DirectX::XMFLOAT4", source)
        self.assertIn("normal_y_policy", source)
        self.assertIn("invert_normal_y", source)
        self.assertIn("flags3.y", source)
        self.assertIn("constants.layer_params[layer_index] = DirectX::XMFLOAT4", source)
        self.assertIn("ID3D11ShaderResourceView* srvs[kTotalSrvCount]", source)
        self.assertIn("context_->PSSetShaderResources(0, kTotalSrvCount, srvs)", source)
        self.assertIn("CREATETEX_FORCE_SRGB", source)
        self.assertIn('compile_shader(kShaderSource, "ps_main", "ps_4_0"', source)

    def test_native_core_scopes_sidecar_wrappers_before_dds_extraction(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("score_material_wrapper_block_for_preview", source)
        self.assertIn('collect_xml_tag_blocks(text, "SkinnedMeshMaterialWrapper")', source)
        self.assertIn("material_keys_overlap", source)
        self.assertIn("normalized_texture_family_key", source)
        self.assertIn("build_material_bindings(job, index, parsed.meshes, package)", source)
        self.assertIn("refs_considered", source)
        self.assertIn("sidecar skipped unrelated material wrapper", source)
        self.assertIn("SkinnedMesh(?:Skin(?:Wrinkle)?|Standard(?:_Ver[0-9]+)?|Cloth(?:_Ver[0-9]+)?|Hair|Fur", source)
        self.assertNotIn("best_wrapper_by_material", source)

    def test_native_core_scores_pac_layouts_and_rejects_unsafe_geometry(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        self.assertIn("struct PacVertexLayout", source)
        self.assertIn("evaluate_native_submesh_quality", source)
        self.assertIn("pac40_uv8_n16", source)
        self.assertIn("pac40_uv32_n16", source)
        self.assertIn("degenerate_triangle_ratio", source)
        self.assertIn("edge_outlier_ratio", source)
        self.assertIn("uv_finite_ratio", source)
        self.assertIn("normal_valid_ratio", source)
        self.assertIn("native geometry unsafe", source)
        self.assertIn('\\"geometry_quality\\":{', source)
        self.assertIn('\\"layout\\":\\"', source)

    def test_native_core_hair_flow_and_layer_modes_are_conservative(self) -> None:
        source = Path("native/cdmw_preview_core/src/main.cpp").read_text(encoding="utf-8")

        role_start = source.index("static std::string role_from_parameter_shader_and_name")
        role_end = source.index("static std::string semantic_type_for_role", role_start)
        role_source = source[role_start:role_end]
        layer_start = source.index("static std::vector<MaterialLayer> compile_material_layers")
        layer_end = source.index("static std::string material_layer_json", layer_start)
        layer_source = source[layer_start:layer_end]

        self.assertLess(role_source.index('p.find("flow")'), role_source.index('t.find("_n.dds")'))
        self.assertIn('return "flow";', role_source)
        self.assertIn('if (mode == "mesh_base_first")', layer_source)
        self.assertIn('shader_rule.find("hair")', layer_source)
        self.assertIn('shader_rule.find("skin")', layer_source)
        self.assertIn('\\"alpha_mode', source)
        self.assertIn('\\"two_sided', source)
        self.assertIn('\\"uv_flip_policy\\":\\"legacy_no_flip', source)
        self.assertIn('\\"normal_y_policy\\":\\"shader_invert_legacy_compat', source)


if __name__ == "__main__":
    unittest.main()
