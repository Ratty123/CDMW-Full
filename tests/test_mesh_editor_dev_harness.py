from __future__ import annotations

from tests.mesh_harness_support import (
    unittest,
    Bone,
    MeshAnimationClip,
    MeshAnimationKeyframe,
    MeshAnimationSequenceSegment,
    MeshAnimationTrack,
    Path,
    Skeleton,
    _png_capture_summary,
    _real_game_mesh_evidence,
    _sample_real_archive_paa_playback,
    _sequence_event_marker_overlap,
    _sequence_lane_pair_summary,
    _sequence_path_record_context,
    _sequence_reference_overlap,
    _sequence_timeline_field_overlap,
    _sequence_timeline_field_semantic_aliases,
    _write_rgb_png,
    build_synthetic_mesh,
    json,
    mesh_editor_native_preview_command,
    mesh_editor_write_native_preview_package,
    patch,
    run_scenario,
    scenario_metadata,
    scenario_names,
    struct,
    tempfile,
)
from tools.mesh_harness.scenario_runner import _apply_backend_gate

class MeshHarnessRealArchiveTests(unittest.TestCase):
    def test_legacy_facade_keeps_constant_identity(self) -> None:
        from tools import mesh_editor_dev_harness as facade
        from tools.mesh_harness import constants

        self.assertIs(facade._DEFAULT_GAME_ROOT, constants._DEFAULT_GAME_ROOT)
        self.assertIs(facade._REAL_MESH_EDITOR_DOTNET_SCENARIO, constants._REAL_MESH_EDITOR_DOTNET_SCENARIO)
        self.assertIs(facade._SYNTHETIC_D3D11_SCENARIOS, constants._SYNTHETIC_D3D11_SCENARIOS)

    def test_scenario_registry_declares_visual_real_game_process_ownership(self) -> None:
        metadata = scenario_metadata("real-archive-mesh-editor-dotnet-edit-smoke")

        self.assertIn(metadata.name, scenario_names())
        self.assertFalse(metadata.headless)
        self.assertTrue(metadata.visual)
        self.assertTrue(metadata.real_game)
        self.assertEqual("harness", metadata.process_ownership)
        self.assertEqual("production_visual_proof", metadata.scenario_role)
        self.assertEqual("dotnet+d3d11", metadata.expected_backend)
        self.assertEqual("d3d11_vortice_shader", metadata.expected_renderer_backend)
        self.assertEqual("cdmw_mesh_core_0.1", metadata.expected_edit_backend)

        parity = scenario_metadata("mesh-dotnet-native-parity-report")
        self.assertTrue(parity.headless)
        self.assertFalse(parity.visual)
        self.assertFalse(parity.real_game)
        self.assertEqual("none", parity.process_ownership)
        self.assertEqual("offline_image_comparison", parity.scenario_role)
        self.assertEqual("python+optional-openimageio", parity.expected_backend)

    def test_real_game_evidence_keeps_v1_schema_and_truth_gates(self) -> None:
        gate_names = (
            "texture_gate_ok",
            "real_texture_provenance_ok",
            "no_synthetic_fallback",
            "archive_sources_unchanged",
            "archive_source_content_unchanged",
            "source_payload_unchanged",
            "changed_only_selected_geometry",
            "selected_face_moved",
            "selected_projection_ok",
            "selected_projected_drag_tracks_cursor",
            "native_window_stationary_ok",
            "live_stroke_frame_budget_ok",
            "heartbeat_ok",
            "native_fallback_ok",
        )
        proof = {
            "ok": True,
            "backend": "d3d11",
            "model_path": "character/model/1_pc/14_ptm/nude/cd_ptm_00_nude_00_0001.pac",
            "source_payload_sha256": "asset-hash",
            "bound_texture_count": 1,
            "resolved_production_textures": [{"archive_path": "character/texture/body.dds"}],
            **dict.fromkeys(gate_names, True),
        }

        evidence = _real_game_mesh_evidence(proof)

        self.assertEqual("cdmw_real_game_mesh_proof_v1", evidence["schema"])
        self.assertTrue(evidence["ok"])
        self.assertEqual(1, evidence["bound_texture_count"])
        self.assertEqual(set(gate_names), set(evidence["gates"]))

    def test_dotnet_real_game_backend_gate_requires_renderer_and_edit_core(self) -> None:
        passed = _apply_backend_gate(
            {
                "ok": True,
                "renderer_backend": "d3d11_vortice_shader",
                "edit_backend": "cdmw_mesh_core_0.1",
            },
            expected_renderer_backend="d3d11_vortice_shader",
            expected_edit_backend="cdmw_mesh_core_0.1",
        )
        wrong_renderer = _apply_backend_gate(
            {
                "ok": True,
                "renderer_backend": "winforms_gdi_fallback",
                "edit_backend": "cdmw_mesh_core_0.1",
            },
            expected_renderer_backend="d3d11_vortice_shader",
            expected_edit_backend="cdmw_mesh_core_0.1",
        )

        self.assertTrue(passed["ok"])
        self.assertTrue(passed["backend_gate_ok"])
        self.assertFalse(wrong_renderer["ok"])
        self.assertFalse(wrong_renderer["renderer_backend_ok"])

    def test_dotnet_real_game_evidence_includes_backend_gates(self) -> None:
        root_gate_names = (
            "real_textures_bound_and_decoded",
            "real_texture_provenance",
            "no_synthetic_fallback",
            "source_archives_unchanged",
            "selected_geometry_only",
            "selected_projection_tracks_cursor",
            "native_window_stationary",
            "live_stroke_frame_budget_ok",
            "heartbeat_ok",
            "edit_backend_ok",
        )
        canonical_gate_names = {
            "texture_gate_ok",
            "real_texture_provenance_ok",
            "no_synthetic_fallback",
            "archive_sources_unchanged",
            "archive_source_content_unchanged",
            "source_payload_unchanged",
            "changed_only_selected_geometry",
            "selected_face_moved",
            "selected_projection_ok",
            "selected_projected_drag_tracks_cursor",
            "native_window_stationary_ok",
            "live_stroke_frame_budget_ok",
            "heartbeat_ok",
            "native_fallback_ok",
            "renderer_backend_ok",
            "edit_backend_ok",
            "backend_gate_ok",
            *root_gate_names,
        }
        proof = {
            "ok": True,
            "renderer_backend": "d3d11_vortice_shader",
            "edit_backend": "cdmw_mesh_core_0.1",
            "archive_source_content_unchanged": True,
            "source_payload_unchanged": True,
            "changed_vertex_count": 3,
            "renderer_backend_ok": True,
            "edit_backend_ok": True,
            "backend_gate_ok": True,
            "gates": dict.fromkeys(root_gate_names, True),
        }

        evidence = _real_game_mesh_evidence(proof)

        self.assertTrue(evidence["ok"])
        self.assertEqual("d3d11_vortice_shader", evidence["renderer_backend"])
        self.assertEqual("cdmw_mesh_core_0.1", evidence["edit_backend"])
        self.assertEqual(canonical_gate_names, set(evidence["gates"]))
        self.assertTrue(all(evidence["gates"].values()))

    def test_sequence_reference_overlap_summarizes_source_compiled_clip_refs(self) -> None:
        overlap = _sequence_reference_overlap(
            (
                "character/motion/a_idle.paa",
                "character/motion/b_idle.paa",
                "effect/hit.paem",
            ),
            (
                "CHARACTER/MOTION/A_IDLE.PAA",
                "character/motion/c_idle.paa",
            ),
            active_path="character/motion/a_idle.paa",
        )

        self.assertEqual("source_compiled_clip_reference_overlap", overlap["status"])
        self.assertEqual("proven_reference_string_overlap", overlap["confidence"])
        self.assertEqual(3, overlap["source_reference_count"])
        self.assertEqual(2, overlap["compiled_reference_count"])
        self.assertEqual(1, overlap["overlap_reference_count"])
        self.assertEqual(2, overlap["source_only_reference_count"])
        self.assertEqual(1, overlap["compiled_only_reference_count"])
        self.assertEqual(1, overlap["overlap_paa_reference_count"])
        self.assertTrue(overlap["active_clip_in_overlap"])
        self.assertEqual(("character/motion/a_idle.paa",), overlap["overlap_paths"])

    def test_sequence_lane_pair_summary_maps_source_and_compiled_lane_offsets(self) -> None:
        source_timeline = {
            "lanes": (
                {"index": 0, "path": "character/motion/a_idle.paa", "source_offset": 120, "confidence": "string_path"},
                {"index": 1, "path": "character/motion/b_idle.paa", "source_offset": 240, "confidence": "string_path"},
            )
        }
        compiled_timeline = {
            "lanes": (
                {"index": 0, "path": "CHARACTER/MOTION/A_IDLE.PAA", "source_offset": 48, "confidence": "string_path"},
            )
        }

        summary = _sequence_lane_pair_summary(
            source_timeline,
            compiled_timeline,
            active_path="character/motion/a_idle.paa",
        )

        self.assertEqual("source_compiled_lane_pair_overlap", summary["status"])
        self.assertEqual(2, summary["source_lane_count"])
        self.assertEqual(1, summary["compiled_lane_count"])
        self.assertEqual(1, summary["lane_pair_count"])
        self.assertEqual(1, summary["active_lane_pair_count"])
        pair = summary["lane_pairs"][0]
        self.assertEqual("character/motion/a_idle.paa", pair["path"])
        self.assertEqual(0, pair["source_lane_index"])
        self.assertEqual(0, pair["compiled_lane_index"])
        self.assertEqual(120, pair["source_offset"])
        self.assertEqual(48, pair["compiled_offset"])
        self.assertTrue(pair["active_clip"])
        self.assertEqual("source_compiled_lane_pair_read_only", pair["status"])

    def test_sequence_event_marker_overlap_maps_source_and_compiled_offsets(self) -> None:
        summary = _sequence_event_marker_overlap(
            {
                "event_markers": (
                    {"text": "Trigger_00", "offset": 120, "role": "event"},
                    {"text": "_startTimePiece", "offset": 240, "role": "timing"},
                    {"text": "source_only", "offset": 360, "role": "event"},
                )
            },
            {
                "event_markers": (
                    {"text": "trigger_00", "offset": 48, "role": "event"},
                    {"text": "compiled_only", "offset": 96, "role": "event"},
                )
            },
        )

        self.assertEqual("source_compiled_event_marker_overlap", summary["status"])
        self.assertEqual("proven_readable_string_overlap", summary["confidence"])
        self.assertEqual(3, summary["source_marker_count"])
        self.assertEqual(2, summary["compiled_marker_count"])
        self.assertEqual(1, summary["overlap_marker_count"])
        self.assertEqual(2, summary["source_only_marker_count"])
        self.assertEqual(1, summary["compiled_only_marker_count"])
        row = summary["overlap_markers"][0]
        self.assertEqual("Trigger_00", row["text"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertEqual("source_compiled_event_marker_overlap_read_only", row["status"])

    def test_sequence_timeline_field_overlap_deduplicates_field_names(self) -> None:
        summary = _sequence_timeline_field_overlap(
            {
                "timeline_fields": (
                    {"name": "_startTimePiece", "offset": 120, "role": "timing", "declared_type": "int32"},
                    {"name": "_startTimePiece", "offset": 240, "role": "timing", "declared_type": "int32"},
                    {"name": "_framesPerSecond", "offset": 360, "role": "timing", "declared_type": "int32"},
                )
            },
            {
                "timeline_fields": (
                    {"name": "_STARTTIMEPIECE", "offset": 48, "role": "timing", "declared_type": "int32"},
                    {"name": "_startBlendTime", "offset": 96, "role": "timing", "declared_type": "float"},
                )
            },
        )

        self.assertEqual("source_compiled_timeline_field_overlap", summary["status"])
        self.assertEqual("proven_field_name_overlap", summary["confidence"])
        self.assertEqual(2, summary["source_unique_field_count"])
        self.assertEqual(2, summary["compiled_unique_field_count"])
        self.assertEqual(1, summary["overlap_field_count"])
        self.assertEqual(1, summary["source_only_field_count"])
        self.assertEqual(1, summary["compiled_only_field_count"])
        row = summary["overlap_fields"][0]
        self.assertEqual("_startTimePiece", row["name"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertEqual(("_framesPerSecond",), summary["source_only_fields"])
        self.assertEqual(("_startBlendTime",), summary["compiled_only_fields"])

    def test_sequence_timeline_field_semantic_aliases_match_source_only_fields(self) -> None:
        summary = _sequence_timeline_field_semantic_aliases(
            {
                "timeline_fields": (
                    {"name": "_startBlendingTime", "offset": 120, "role": "timing", "declared_type": "float"},
                    {"name": "_endBlendingTime", "offset": 180, "role": "timing", "declared_type": "float"},
                    {"name": "_hasTransformBlend", "offset": 240, "role": "timing", "declared_type": "bool"},
                )
            },
            {
                "timeline_fields": (
                    {"name": "_startBlendTime", "offset": 48, "role": "timing", "declared_type": "float"},
                    {"name": "_hasTransformBlend", "offset": 96, "role": "timing", "declared_type": "bool"},
                )
            },
        )

        self.assertEqual("source_compiled_timeline_field_semantic_aliases", summary["status"])
        self.assertEqual("inferred_name_alias_value_unbound", summary["confidence"])
        self.assertEqual(1, summary["alias_count"])
        row = summary["alias_rows"][0]
        self.assertEqual("_startBlendingTime", row["source_name"])
        self.assertEqual("_startBlendTime", row["compiled_name"])
        self.assertEqual("startblendtime", row["alias_key"])
        self.assertEqual(120, row["source_offset"])
        self.assertEqual(48, row["compiled_offset"])
        self.assertIn("_endBlendingTime", summary["unmatched_source_fields"])
        self.assertNotIn("_hasTransformBlend", summary["unmatched_source_fields"])

    def test_sequence_path_record_context_reports_read_only_byte_window(self) -> None:
        path = "character/motion/a_idle.paa"
        actor = b"actor"
        path_bytes = path.encode("ascii")
        data = (
            b"\x00" * 8
            + struct.pack("<I", len(actor))
            + actor
            + struct.pack("<I", len(path_bytes))
            + path_bytes
            + struct.pack("<I", 30)
            + struct.pack("<f", 2.0)
        )

        context = _sequence_path_record_context(data, path, window_before=24, window_after=len(path_bytes) + 12)

        text_offset = data.index(path_bytes)
        self.assertEqual("path_record_window_recovered", context["status"])
        self.assertEqual("active_lane_record_layout_unbound", context["binding_status"])
        self.assertEqual(text_offset, context["path_text_offset"])
        self.assertEqual(text_offset - 4, context["path_length_offset"])
        self.assertEqual(2, context["length_prefixed_string_count"])
        self.assertEqual(1, context["fps_like_u32_count"])
        self.assertEqual(1, context["float32_candidate_count"])
        self.assertEqual("actor", context["length_prefixed_strings"][0]["text"])
        self.assertEqual(path, context["length_prefixed_strings"][1]["text"])
        self.assertIn((text_offset + len(path_bytes), 30), tuple((row["offset"], row["u32"]) for row in context["scalar_rows"]))

    def test_mesh_editor_native_runtime_writes_preview_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "preview_package"

            package_dir = mesh_editor_write_native_preview_package(
                build_synthetic_mesh("pam"),
                output_root=output_dir,
                use_textures=False,
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual(output_dir, package_dir)
            self.assertEqual("pam", manifest["format"])
            self.assertEqual(1, len(manifest["batches"]))
            self.assertTrue((package_dir / "geometry" / "geometry.bin").is_file())

    def test_mesh_editor_native_runtime_writes_overlay_compare_package(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir) / "compare_package"
            source_mesh = build_synthetic_mesh("pam")
            edited_mesh = build_synthetic_mesh("pam")
            edited_mesh.submeshes[0].vertices[0] = (0.0, 0.0, 0.5)

            package_dir = mesh_editor_write_native_preview_package(
                edited_mesh,
                reference_mesh=source_mesh,
                output_root=output_dir,
                use_textures=False,
                display_mode="overlay",
            )
            manifest = json.loads((package_dir / "manifest.json").read_text(encoding="utf-8"))

            self.assertEqual("overlay", manifest["display_mode"])
            self.assertEqual(2, len(manifest["batches"]))
            self.assertEqual("original_reference", manifest["batches"][0]["editor_identity"]["role"])
            self.assertFalse(manifest["batches"][0]["editor_identity"]["editable"])
            self.assertEqual("replacement_preview", manifest["batches"][1]["editor_identity"]["role"])
            self.assertTrue(manifest["batches"][1]["editor_identity"]["editable"])

    def test_mesh_editor_native_runtime_builds_host_command(self) -> None:
        package_dir = Path("C:/tmp/mesh-editor-package")
        status_file = Path("C:/tmp/mesh-editor-status.json")
        host = Path("C:/native/cdmw-d3d11-preview.exe")
        held: list[Path] = []

        class HostWidget:
            def setAttribute(self, *_args: object) -> None:
                return

            def winId(self) -> int:
                return 123

            def hold_native_preview_package_cache_lease(self, path: Path) -> None:
                held.append(path)

        with patch("cdmw.ui.mesh_editor.native_preview_runtime.find_native_d3d11_host", return_value=host):
            program, args = mesh_editor_native_preview_command(
                package_dir,
                status_file,
                host_widget=HostWidget(),
                crash_dir=Path("C:/tmp/crash"),
                diagnostic_log=Path("C:/tmp/native.jsonl"),
            )

        self.assertEqual(str(host), program)
        self.assertIn("--preview-package", args)
        self.assertIn(str(package_dir), args)
        self.assertIn("--status-file", args)
        self.assertIn(str(status_file), args)
        self.assertIn("--crash-dir", args)
        self.assertIn(str(Path("C:/tmp/crash")), args)
        self.assertEqual([package_dir], held)
        self.assertIn("--parent-hwnd", args)

    def test_real_archive_playback_sampler_reports_preview_only_geometry(self) -> None:
        mesh = build_synthetic_mesh("pac")
        mesh.has_bones = True
        mesh.submeshes[0].bone_indices = [(0,), (0,), (0,), (0,)]
        mesh.submeshes[0].bone_weights = [(1.0,), (1.0,), (1.0,), (1.0,)]
        skeleton = Skeleton(bones=[Bone(index=0, name="Root", parent_index=-1)], bone_count=1)
        clip = MeshAnimationClip(
            source="sequence_clip.paa",
            duration_seconds=1.0,
            tracks=(
                MeshAnimationTrack(
                    bone_name="Root",
                    rotation_keyframes=(
                        MeshAnimationKeyframe(0.0, (0.0, 0.0, 0.0)),
                        MeshAnimationKeyframe(1.0, (0.0, 0.0, 90.0)),
                    ),
                ),
            ),
            sequence_segments=(
                MeshAnimationSequenceSegment(
                    sequence_path="sequencer/binary__/sequence_sample.paseqc",
                    clip_path="sequence_clip.paa",
                    lane_index=5,
                    start_seconds=0.0,
                    end_seconds=1.0,
                    status="paseqc_lane_bound_to_paa_clip_preview_only_sequence_semantics_unknown",
                ),
            ),
            frame_rate=30.0,
            timing_confidence="inferred",
            timing_status="default_30fps_unproven",
        )

        sample = _sample_real_archive_paa_playback(mesh, skeleton, clip)

        self.assertTrue(sample["ready"])
        self.assertTrue(sample["enabled"])
        self.assertGreater(sample["sampled_bone_count"], 0)
        self.assertEqual(sample["sampled_bone_count"], sample["repeat_sampled_bone_count"])
        self.assertEqual(5, sample["active_sequence_lane_index"])
        self.assertEqual("sequencer/binary__/sequence_sample.paseqc", sample["active_sequence_path"])
        self.assertEqual("sequence_clip.paa", sample["active_sequence_clip_path"])
        self.assertIn("paseqc_lane_bound", sample["active_sequence_status"])
        self.assertTrue(sample["pose_changed"])
        self.assertTrue(sample["deterministic_repeat_seek"])
        self.assertEqual(sample["time_seconds"], sample["repeat_time_seconds"])
        self.assertTrue(sample["export_geometry_unchanged"])
        self.assertEqual("default_30fps_unproven", sample["timing_status"])

    def test_real_archive_rigging_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-rigging-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_animation_binding_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-animation-binding-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_animation"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_sequence_binding_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-sequence-binding-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_sequence"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_app_workflow_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-app-workflow-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_app"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_mesh_editor_d3d11_edit_smoke_reports_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario("real-archive-mesh-editor-d3d11-edit-smoke", output_dir, game_root=temp_root / "missing")

            self.assertFalse(result["ok"])
            self.assertTrue((output_dir / "result.json").is_file())
            real_archive = result["real_archive_mesh_editor_d3d11_edit"]
            self.assertTrue(real_archive["read_only"])
            self.assertIn("missing PAMT", real_archive["skipped"])

    def test_real_archive_mesh_editor_dotnet_smoke_routes_missing_game_root_without_archive_writes(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            temp_root = Path(temp_dir)
            output_dir = temp_root / "out"

            result = run_scenario(
                "real-archive-mesh-editor-dotnet-edit-smoke",
                output_dir,
                game_root=temp_root / "missing",
            )

            proof = result["real_archive_mesh_editor_dotnet_edit"]
            self.assertFalse(result["ok"])
            self.assertTrue(proof["read_only"])
            self.assertFalse(proof["backend_gate_ok"])
            self.assertEqual("d3d11_vortice_shader", proof["expected_renderer_backend"])
            self.assertEqual("cdmw_mesh_core_0.1", proof["expected_edit_backend"])
            self.assertTrue((output_dir / "result.json").is_file())
            self.assertTrue((output_dir / "evidence_report.json").is_file())

    def test_real_archive_mesh_editor_dotnet_smoke_gates_backends_and_emits_real_game_evidence(self) -> None:
        proof = {
            "ok": True,
            "renderer_backend": "d3d11_vortice_shader",
            "edit_backend": "cdmw_mesh_core_0.1",
            "archive_source_content_unchanged": True,
            "source_payload_unchanged": True,
            "changed_vertex_count": 1,
            "gates": dict.fromkeys(
                (
                    "real_textures_bound_and_decoded",
                    "real_texture_provenance",
                    "no_synthetic_fallback",
                    "source_archives_unchanged",
                    "selected_geometry_only",
                    "selected_projection_tracks_cursor",
                    "native_window_stationary",
                    "live_stroke_frame_budget_ok",
                    "heartbeat_ok",
                    "edit_backend_ok",
                ),
                True,
            ),
        }
        with tempfile.TemporaryDirectory() as temp_dir, patch(
            "tools.mesh_harness.real_dotnet.run_real_archive_mesh_editor_dotnet_edit_smoke",
            return_value=proof,
        ) as run_dotnet:
            output_dir = Path(temp_dir) / "out"
            game_root = Path(temp_dir) / "game"
            result = run_scenario(
                "real-archive-mesh-editor-dotnet-edit-smoke",
                output_dir,
                game_root=game_root,
            )
            evidence = json.loads((output_dir / "evidence_report.json").read_text(encoding="utf-8"))

        run_dotnet.assert_called_once_with(game_root, output_dir, timeout_seconds=180.0)
        self.assertTrue(result["ok"])
        self.assertTrue(result["real_archive_mesh_editor_dotnet_edit"]["backend_gate_ok"])
        self.assertTrue(evidence["real_game_proof"]["ok"])

    def test_real_archive_mesh_editor_drag_smoke_uses_multistep_mouse_moves(self) -> None:
        source = Path("tools/mesh_harness/real_d3d.py").read_text(encoding="utf-8")
        self.assertIn("mouse_drag_points", source)
        self.assertIn("for offset in range(1, 41)", source)
        for token in (
            "mouse_drag_end",
            "edit_update_events",
            "selected_before_capture_path",
            "visual_proof_path",
            "_write_real_archive_visual_edit_proof",
            "visual_edit_proof_png",
            "live_stroke_timings",
            "live_stroke_timing_summary",
            "live_stroke_frame_budget_ok",
            "handler_ms",
            "d3d11_send_ms",
        ):
            self.assertIn(token, source)

    def test_real_archive_mesh_editor_side_by_side_drag_smoke_uses_replacement_viewport(self) -> None:
        source = "\n".join(
            Path(path).read_text(encoding="utf-8")
            for path in (
                "tools/mesh_harness/constants.py",
                "tools/mesh_harness/scenario_registry.py",
                "tools/mesh_harness/real_d3d.py",
            )
        )
        for token in (
            "real-archive-mesh-editor-d3d11-side-by-side-edit-smoke",
            "reference_mesh",
            "side_by_side",
            "display_mode",
            "projection_probe_start",
            "replacement_viewport_offset_ok",
            "drag_points_in_replacement_viewport",
        ):
            self.assertIn(token, source)

        compatibility = scenario_metadata("real-archive-mesh-editor-d3d11-side-by-side-edit-smoke")
        self.assertEqual("native_renderer_compatibility", compatibility.scenario_role)
        self.assertEqual("legacy-cpp-d3d11", compatibility.expected_backend)

    def test_png_capture_summary_rejects_blank_capture(self) -> None:
        width = 64
        height = 64
        blank_row = bytes((0, 0, 0)) * width
        visible_rows: list[bytes] = []
        for y in range(height):
            row = bytearray()
            for x in range(width):
                row.extend((220, 220, 220) if x == y or x == width - y - 1 else (18, 24, 30))
            visible_rows.append(bytes(row))

        with tempfile.TemporaryDirectory() as temp_dir:
            output_dir = Path(temp_dir)
            blank_path = output_dir / "blank.png"
            visible_path = output_dir / "visible.png"
            _write_rgb_png(blank_path, width, height, [blank_row] * height)
            _write_rgb_png(visible_path, width, height, visible_rows)

            blank_summary = _png_capture_summary(blank_path)
            visible_summary = _png_capture_summary(visible_path)

            self.assertFalse(blank_summary["ok"])
            self.assertEqual(1, blank_summary["unique_rgb_count"])
            self.assertTrue(visible_summary["ok"])
            self.assertGreater(visible_summary["unique_rgb_count"], 1)
            self.assertGreater(visible_summary["bright_sample_count"], 0)
