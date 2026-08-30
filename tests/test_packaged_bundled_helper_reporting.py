"""The packaged build must prove the helpers it ships actually resolve.

Nothing outside a packaged run can answer that question: the payload directory
and ``sys._MEIPASS`` only exist there. OpenImageIO shipped for a while resolving
out of the developer's virtualenv and reporting unavailable to every user, and
no test caught it because every test ran from the virtualenv.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cdmw.app.startup_smoke import GUI_STARTUP_SMOKE_RESULT_ENV, write_gui_startup_smoke_result
from cdmw.services import bundled_helper_availability
from cdmw.services.bundled_helper_availability import bundled_helper_resolution_snapshot


REPO_ROOT = Path(__file__).resolve().parents[1]
VERIFY_SCRIPT = REPO_ROOT / "scripts" / "verify_packaged_startup.ps1"


def _run_gate(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    """Exercise the real PowerShell assertion the build gate runs."""

    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise unittest.SkipTest("PowerShell is not available")
    # ExecutablePath is mandatory, and dot-sourcing runs the param block. The
    # script's own `InvocationName -ne "."` guard keeps the main flow from
    # running, so the placeholder is never opened.
    script = (
        f". '{VERIFY_SCRIPT}' -ExecutablePath 'unused-when-dot-sourced'; "
        "$payload = $env:CDMW_TEST_PAYLOAD | ConvertFrom-Json; "
        "Assert-PackagedBundledHelpers -Payload $payload"
    )
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={"CDMW_TEST_PAYLOAD": json.dumps(payload), "SystemRoot": r"C:\Windows", "PATH": ""},
    )


def _run_texture_gate(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise unittest.SkipTest("PowerShell is not available")
    script = (
        f". '{VERIFY_SCRIPT}' -ExecutablePath 'unused-when-dot-sourced'; "
        "$payload = $env:CDMW_TEST_PAYLOAD | ConvertFrom-Json; "
        "Assert-PackagedMeshTextureEvidence -Payload $payload"
    )
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=120,
        env={"CDMW_TEST_PAYLOAD": json.dumps(payload), "SystemRoot": r"C:\Windows", "PATH": ""},
    )


class PackagedBundledHelperReportingTests(unittest.TestCase):
    def test_smoke_result_carries_the_bundled_helper_snapshot(self) -> None:
        helpers = [{"key": "openimageio", "status": "available", "source": "bundled_lookup", "path": "x"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "result.json"
            with mock.patch.dict("os.environ", {GUI_STARTUP_SMOKE_RESULT_ENV: str(result_path)}):
                write_gui_startup_smoke_result(
                    ok=True,
                    stage="post_construction",
                    target="",
                    bundled_helpers=helpers,
                )
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(helpers, payload["bundled_helpers"])

    def test_smoke_result_omits_the_section_when_it_was_not_collected(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "result.json"
            with mock.patch.dict("os.environ", {GUI_STARTUP_SMOKE_RESULT_ENV: str(result_path)}):
                write_gui_startup_smoke_result(ok=True, stage="post_construction", target="")
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertNotIn("bundled_helpers", payload)

    def test_smoke_result_carries_packaged_texture_evidence(self) -> None:
        evidence = {
            "schema": "cdmw_packaged_mesh_editor_controls_smoke_v3",
            "read_only": True,
        }
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "result.json"
            with mock.patch.dict("os.environ", {GUI_STARTUP_SMOKE_RESULT_ENV: str(result_path)}):
                write_gui_startup_smoke_result(
                    ok=True,
                    stage="post_construction",
                    target="mesh_archive_textures",
                    evidence=evidence,
                )
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(evidence, payload["evidence"])

    def test_snapshot_reports_bundled_helpers_only_and_runs_nothing(self) -> None:
        with mock.patch("subprocess.run", side_effect=AssertionError("startup must not execute helpers")):
            snapshot = bundled_helper_resolution_snapshot()

        self.assertTrue(snapshot, "expected at least one bundled helper")
        keys = {entry["key"] for entry in snapshot}
        self.assertIn("openimageio", keys)
        self.assertIn("cdmw_mesh_core", keys)
        for removed in ("material_maker", "ufbx", "meshoptimizer"):
            self.assertNotIn(removed, keys)
        for entry in snapshot:
            self.assertEqual({"key", "status", "source", "path"}, set(entry))

    def test_gate_accepts_a_run_where_every_bundled_helper_resolved(self) -> None:
        completed = _run_gate(
            {
                "bundled_helpers": [
                    {"key": "openimageio", "status": "available", "source": "bundled_lookup", "path": "x"},
                    {"key": "cdmw_mesh_core", "status": "available", "source": "bundled_lookup", "path": "y"},
                ]
            }
        )

        self.assertEqual(0, completed.returncode, completed.stderr)
        self.assertIn("openimageio", completed.stdout)

    def test_gate_fails_when_a_bundled_helper_did_not_resolve(self) -> None:
        completed = _run_gate(
            {
                "bundled_helpers": [
                    {"key": "openimageio", "status": "unavailable", "source": "not_detected", "path": ""},
                ]
            }
        )

        self.assertNotEqual(0, completed.returncode)
        self.assertIn("did not resolve inside the package", completed.stderr)

    def test_gate_fails_when_the_build_reports_no_bundled_helpers_at_all(self) -> None:
        missing = _run_gate({"ok": True})
        empty = _run_gate({"bundled_helpers": []})

        self.assertNotEqual(0, missing.returncode)
        self.assertIn("no bundled_helpers section", missing.stderr)
        self.assertNotEqual(0, empty.returncode)
        self.assertIn("empty bundled_helpers", empty.stderr)

    def test_packaged_texture_gate_requires_current_real_controls_and_selection(self) -> None:
        evidence = {
            "schema": "cdmw_packaged_mesh_editor_controls_smoke_v3",
            "read_only": True,
            "archive_sources_unchanged": True,
            "production_route": "MainWindow._launch_archive_mesh_editor_for_entry",
            "actual_csharp_controls": True,
            "global_mouse_input_used": False,
            "model_path": "character/model/body.pac",
            "helper": {
                "path": "C:/app/Cdmw.MeshEditorExperiment.exe",
                "sha256": "abc123",
                "process_id": 777,
            },
            "application": {
                "frozen": True,
                "executable_sha256": "def456",
                "helper_inside_bundle_root": True,
            },
            "viewport_availability": {
                "before_session": {"standalone_workspace_current": True, "host_visible": True},
                "before_controls": {"owned": True, "visible": True, "nonzero": True},
                "after_textured": {"visible": True, "nonzero": True},
                "after_select": {"visible": True, "nonzero": True},
                "after_grab_history": {"visible": True, "nonzero": True},
                "after_close": {"standalone_workspace_current": True, "host_visible": True},
            },
            "control_continuity": {
                "ok": True,
                "actual_controls": True,
                "case_count": 9,
                "settlement_p95_ms": 12.0,
                "cases": [{"stable": True} for _ in range(9)],
            },
            "solid_textured": {
                "actual_controls": True,
                "selected_mode": "textured",
                "renderer_resources": {
                    "display_mode": "textured",
                    "textures_enabled": True,
                    "live_texture_srvs": 3,
                    "textured_draw_calls": 2,
                    "draw_counter_source": "renderer.live_metrics.geometry_resources",
                },
            },
            "select": {
                "ok": True,
                "actual_control": True,
                "input_backend": "scoped_hwnd_messages_no_global_cursor",
                "input_target_pid": 777,
                "overlay": {
                    "counter_source": "renderer.live_metrics.geometry_resources",
                    "committed_primitives_before": 0,
                    "committed_primitives_after": 6,
                },
                "capture": {"ok": True},
            },
            "grab_undo_redo": {
                "ok": True,
                "actual_controls": True,
                "gates": {
                    "first_grab_changed_geometry": True,
                    "first_grab_one_history_entry": True,
                    "first_undo_restored_exact_baseline": True,
                    "first_undo_restored_history_cursor": True,
                    "grab_rearmed_after_undo": True,
                    "second_grab_one_history_entry": True,
                    "second_undo_restored_exact_baseline": True,
                    "redo_restored_exact_second_commit": True,
                    "redo_restored_history_cursor": True,
                },
            },
            "grab_redo_capture": {"ok": True},
            "desktop_input": {
                "ok": True,
                "harness_foreground_count": 0,
                "cursor_on_harness_screen_count": 0,
            },
            "capture": {"ok": True},
            "material_update": {"resource_count": 3, "resource_file_count": 3},
            "material_failures": [],
        }

        accepted = _run_texture_gate({"evidence": evidence})
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        evidence["select"]["overlay"]["committed_primitives_after"] = 0
        no_highlight = _run_texture_gate({"evidence": evidence})
        self.assertNotEqual(0, no_highlight.returncode)
        self.assertIn("newly drawn committed selection highlight", no_highlight.stderr)
        evidence["select"]["overlay"]["committed_primitives_after"] = 6

        evidence["application"]["helper_inside_bundle_root"] = False
        development_helper = _run_texture_gate({"evidence": evidence})
        self.assertNotEqual(0, development_helper.returncode)
        self.assertIn("helper outside that app's unpacked bundle", development_helper.stderr)
        evidence["application"]["helper_inside_bundle_root"] = True

        evidence["solid_textured"]["selected_mode"] = "untextured_faces"
        rejected = _run_texture_gate({"evidence": evidence})
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("did not retain Solid (Textured)", rejected.stderr)

        evidence["solid_textured"]["selected_mode"] = "textured"
        evidence["grab_undo_redo"]["gates"]["grab_rearmed_after_undo"] = False
        stuck_grab = _run_texture_gate({"evidence": evidence})
        self.assertNotEqual(0, stuck_grab.returncode)
        self.assertIn("Grab, Undo, Grab", stuck_grab.stderr)

    def test_current_texture_smoke_routes_real_controls_without_builder_embedding(self) -> None:
        source = (REPO_ROOT / "tools" / "mesh_harness" / "packaged_mesh_texture_smoke.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("window._launch_archive_mesh_editor_for_entry(entry)", source)
        self.assertIn('_click_button_by_text(form_hwnd, "Select"', source)
        self.assertIn('_click_button_by_text(form_hwnd, "Grab"', source)
        select_attempt = source.split("def _perform_actual_select_attempt(", 1)[1].split(
            "def _exercise_actual_select_control(", 1
        )[0]
        grab_attempt = source.split("def _perform_actual_grab(", 1)[1].split(
            "def _perform_actual_history_command(", 1
        )[0]
        self.assertIn('"resident_interaction_transaction"', select_attempt)
        self.assertIn('event_name="resident_interaction_transaction"', grab_attempt)
        self.assertNotIn('"select_request"', select_attempt)
        self.assertNotIn('"stroke_begin"', grab_attempt)
        self.assertNotIn('event_name="stroke_end"', grab_attempt)
        self.assertIn('command_text="Undo"', source)
        self.assertIn('command_text="Redo"', source)
        self.assertIn("_exercise_actual_control_continuity(", source)
        self.assertIn('control.get("message_dispatch_ms"', source)
        self.assertIn('_select_combo_item_by_text(\n        form_hwnd,\n        "Solid (Textured)"', source)
        self.assertIn('"global_mouse_input_used": False', source)
        self.assertIn("runtime_event_requested.connect(capture_runtime_event)", source)
        self.assertNotIn("prompt_archive_static_replacement_options", source)
        self.assertNotIn("builder_host()", source)

    def test_texture_smoke_reads_live_draws_not_the_cached_diagnostic_snapshot(self) -> None:
        from tools.mesh_harness.packaged_mesh_texture_smoke import _renderer_texture_state

        renderer = {
            "display_mode": "textured",
            "textures_enabled": True,
            "geometry_resources": {
                "live_texture_srvs": 15,
                "textured_solid_batch_draws": 0,
                "committed_selection_overlay_primitives": 0,
            },
            "live_metrics": {
                "geometry_resources": {
                    "textured_solid_batch_draws": 3,
                    "committed_selection_overlay_primitives": 6,
                    "driver_type": "hardware",
                    "adapter_description": "Test GPU",
                    "feature_level": "Level_11_1",
                    "debug_layer_requested": False,
                    "debug_layer_state": "disabled",
                },
            },
        }
        tab = SimpleNamespace(standalone_dotnet_status_payload={"renderer": renderer})

        state = _renderer_texture_state(tab)
        self.assertEqual(3, state["textured_draw_calls"])
        self.assertEqual(15, state["live_texture_srvs"])
        self.assertEqual(6, state["committed_selection_overlay_primitives"])
        self.assertEqual("hardware", state["driver_type"])
        self.assertEqual("Test GPU", state["adapter_description"])
        self.assertEqual("Level_11_1", state["feature_level"])
        self.assertIs(state["debug_layer_requested"], False)
        self.assertEqual("disabled", state["debug_layer_state"])

        renderer["geometry_resources"]["textured_solid_batch_draws"] = 99
        renderer["live_metrics"]["geometry_resources"]["textured_solid_batch_draws"] = 0
        self.assertEqual(0, _renderer_texture_state(tab)["textured_draw_calls"])

if __name__ == "__main__":
    unittest.main()
