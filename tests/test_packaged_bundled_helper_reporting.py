"""The packaged build must prove the helpers it ships actually resolve.

Nothing outside a packaged run can answer that question: the payload directory
and ``sys._MEIPASS`` only exist there. OpenImageIO shipped for a while resolving
out of the developer's virtualenv and reporting unavailable to every user, and
no test caught it because every test ran from the virtualenv.
"""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from cdmw.app.startup_smoke import (
    GUI_STARTUP_SMOKE_RESULT_ENV,
    write_gui_startup_smoke_result,
)
from cdmw.services.bundled_helper_availability import (
    bundled_helper_resolution_snapshot,
    packaged_rust_mesh_editor_resolution_snapshot,
)


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


def _run_rust_editor_gate(payload: dict[str, object]) -> subprocess.CompletedProcess[str]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        raise unittest.SkipTest("PowerShell is not available")
    script = (
        f". '{VERIFY_SCRIPT}' -ExecutablePath 'unused-when-dot-sourced'; "
        "$payload = $env:CDMW_TEST_PAYLOAD | ConvertFrom-Json; "
        "Assert-PackagedRustMeshEditorEvidence -Payload $payload"
    )
    return subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        check=False,
        text=True,
        timeout=120,
        env={"CDMW_TEST_PAYLOAD": json.dumps(payload), "SystemRoot": r"C:\Windows", "PATH": ""},
    )


def _packaged_rust_editor_fixture(
    *,
    executable_sha256: str = "a" * 64,
    control_contract_sha256: str = "f" * 64,
) -> dict[str, object]:
    package_root = "C:/Temp/cdmw-payload"
    return {
        "schema": "cdmw_packaged_rust_mesh_editor_v1",
        "status": "available",
        "reason": "",
        "source": "frozen",
        "frozen": True,
        "path": f"{package_root}/native/rust_mesh_editor/cdmw_mesh_lab.exe",
        "relative_path": "native/rust_mesh_editor/cdmw_mesh_lab.exe",
        "inside_bundle_root": True,
        "executable_sha256": executable_sha256,
        "provenance_path": f"{package_root}/native/rust_mesh_editor/cdmw_mesh_lab.manifest.json",
        "provenance_relative_path": "native/rust_mesh_editor/cdmw_mesh_lab.manifest.json",
        "provenance_inside_bundle_root": True,
        "provenance_sha256": "b" * 64,
        "provenance": {
            "schema": "cdmw_rust_mesh_editor_build_provenance_v1",
            "renderer": "wgpu_d3d12_rust",
            "edit_backend": "cdmw_rust_mesh_0.1",
            "protocol": "cdmw_rust_mesh_editor_protocol_v1",
            "authoring_package": "cdmw_rust_mesh_authoring_package_v1",
            "build_profile": "release",
            "locked_dependencies": True,
            "executable": "cdmw_mesh_lab.exe",
            "control_contract": "cdmw_mesh_lab.control-contract.json",
            "control_contract_schema": "cdmw_rust_mesh_editor_control_contract_v2",
            "capabilities": ["embedded_child_window_v1"],
            "source_revision": "c" * 40,
            "source_tree_sha256": "d" * 64,
            "cargo_lock_sha256": "e" * 64,
            "executable_sha256": executable_sha256,
            "control_contract_sha256": control_contract_sha256,
            "cargo_version": "cargo 1.88.0",
            "rustc_version": "rustc 1.88.0",
        },
    }


def _resident_interaction_fixture(tool: str, mode: str, tool_id: int) -> dict[str, object]:
    transaction = {
        "session_id": "fixture-resident-session",
        "sha256": "a" * 64,
        "process_generation": 2,
        "helper_process_id": 777,
        "request_id": 1000 + tool_id,
        "gesture_id": 2000 + tool_id,
        "transaction_sequence": 3000 + tool_id,
        "base_revision": 10,
        "target_revision": 11,
        "base_selection_revision": 4,
        "target_selection_revision": 4,
        "topology_generation": 8,
        "tool": tool_id,
    }
    acknowledgement = {**transaction, "status": "applied"}
    return {
        "ok": True,
        "tool": tool,
        "mode": mode,
        "gesture": {
            "ok": True,
            "input_backend": "helper_ui_thread_resident_probe",
            "global_mouse_input_used": False,
            "resident_interaction_transaction_count": 1,
            "helper_originated_mutation_echo_count": 0,
            "terminal_event": "resident_interaction_transaction",
            "operator": {"state": "idle"},
            "timing": {
                "begin_ms": 0.1,
                "input_sample_p95_ms": 0.2,
                "input_sample_max_ms": 0.3,
                "finish_ms": 0.1,
                "total_ms": 0.5,
            },
            "probe_acknowledgement": {
                "ok": True,
                "status": "applied",
                "request_id": transaction["request_id"],
            },
            "resident_interaction_transaction": transaction,
            "commit_v2_acknowledgement": acknowledgement,
        },
        "gates": {
            "transaction_count_one": True,
            "commit_v2_ack_applied": True,
            "geometry_changed": True,
            "one_history_transaction": True,
            "undo_restored_exact_baseline": True,
            "undo_restored_history_cursor": True,
            "operator_idle": True,
            "native_backend": True,
            "no_mutation_echo": True,
        },
    }


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

    def test_smoke_result_carries_independent_packaged_rust_editor_proof(self) -> None:
        rust_proof = _packaged_rust_editor_fixture()
        helpers = [{"key": "openimageio", "status": "available", "source": "bundled_lookup", "path": "x"}]
        with tempfile.TemporaryDirectory() as temp_dir:
            result_path = Path(temp_dir) / "result.json"
            with (
                mock.patch.dict("os.environ", {GUI_STARTUP_SMOKE_RESULT_ENV: str(result_path)}),
                mock.patch(
                    "cdmw.services.bundled_helper_availability."
                    "packaged_rust_mesh_editor_resolution_snapshot",
                    return_value=rust_proof,
                ),
            ):
                write_gui_startup_smoke_result(
                    ok=True,
                    stage="post_construction",
                    target="",
                    bundled_helpers=helpers,
                    evidence={"helper": {"provenance": {"renderer_backend": "d3d11_vortice_shader"}}},
                )
            payload = json.loads(result_path.read_text(encoding="utf-8"))

        self.assertEqual(rust_proof, payload["rust_mesh_editor"])
        self.assertEqual(
            "d3d11_vortice_shader",
            payload["evidence"]["helper"]["provenance"]["renderer_backend"],
        )
        self.assertNotEqual(
            payload["rust_mesh_editor"]["provenance"]["renderer"],
            payload["evidence"]["helper"]["provenance"]["renderer_backend"],
        )

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

    def test_packaged_rust_snapshot_validates_live_frozen_files_without_running_them(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            payload_root = Path(temp_dir)
            rust_root = payload_root / "native" / "rust_mesh_editor"
            rust_root.mkdir(parents=True)
            executable = rust_root / "cdmw_mesh_lab.exe"
            executable.write_bytes(b"synthetic packaged rust editor")
            executable_sha256 = hashlib.sha256(executable.read_bytes()).hexdigest()
            control_contract = rust_root / "cdmw_mesh_lab.control-contract.json"
            control_contract.write_text(
                json.dumps(
                    {
                        "schema": "cdmw_rust_mesh_editor_control_contract_v2",
                        "ok": True,
                    }
                ),
                encoding="utf-8",
            )
            control_contract_sha256 = hashlib.sha256(control_contract.read_bytes()).hexdigest()
            provenance = dict(
                _packaged_rust_editor_fixture(
                    executable_sha256=executable_sha256,
                    control_contract_sha256=control_contract_sha256,
                )["provenance"]
            )
            manifest = rust_root / "cdmw_mesh_lab.manifest.json"
            manifest.write_text(json.dumps(provenance), encoding="utf-8")

            with (
                mock.patch.object(sys, "_MEIPASS", str(payload_root), create=True),
                mock.patch.object(sys, "frozen", True, create=True),
                mock.patch("subprocess.run", side_effect=AssertionError("startup proof must not run helpers")),
            ):
                proof = packaged_rust_mesh_editor_resolution_snapshot()

            self.assertEqual("available", proof["status"])
            self.assertEqual("frozen", proof["source"])
            self.assertEqual("native/rust_mesh_editor/cdmw_mesh_lab.exe", proof["relative_path"])
            self.assertEqual(executable_sha256, proof["executable_sha256"])
            self.assertEqual(hashlib.sha256(manifest.read_bytes()).hexdigest(), proof["provenance_sha256"])
            self.assertEqual("wgpu_d3d12_rust", proof["provenance"]["renderer"])

            executable.write_bytes(b"changed after provenance was written")
            with (
                mock.patch.object(sys, "_MEIPASS", str(payload_root), create=True),
                mock.patch.object(sys, "frozen", True, create=True),
            ):
                rejected = packaged_rust_mesh_editor_resolution_snapshot()

            self.assertEqual("unavailable", rejected["status"])
            self.assertIn("hash does not match", rejected["reason"])

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

    def test_packaged_rust_gate_requires_exact_independent_release_provenance(self) -> None:
        accepted = _run_rust_editor_gate({"rust_mesh_editor": _packaged_rust_editor_fixture()})
        self.assertEqual(0, accepted.returncode, accepted.stderr)
        self.assertIn("Packaged Rust Edit Mesh verified", accepted.stdout)

        vortice_only = _run_rust_editor_gate(
            {
                "evidence": {
                    "helper": {
                        "provenance": {
                            "renderer_backend": "d3d11_vortice_shader",
                            "edit_backend": "cdmw_mesh_core_0.1",
                        }
                    }
                }
            }
        )
        self.assertNotEqual(0, vortice_only.returncode)
        self.assertIn("no independent rust_mesh_editor section", vortice_only.stderr)

        wrong_path_proof = _packaged_rust_editor_fixture()
        wrong_path_proof["relative_path"] = "native/cdmw_mesh_lab.exe"
        wrong_path = _run_rust_editor_gate({"rust_mesh_editor": wrong_path_proof})
        self.assertNotEqual(0, wrong_path.returncode)
        self.assertIn("native/rust_mesh_editor/cdmw_mesh_lab.exe", wrong_path.stderr)

        wrong_hash_proof = _packaged_rust_editor_fixture()
        wrong_hash_proof["provenance"]["executable_sha256"] = "f" * 64
        wrong_hash = _run_rust_editor_gate({"rust_mesh_editor": wrong_hash_proof})
        self.assertNotEqual(0, wrong_hash.returncode)
        self.assertIn("executable hash does not match", wrong_hash.stderr)

        wrong_contract_proof = _packaged_rust_editor_fixture()
        wrong_contract_proof["provenance"]["renderer"] = "d3d11_vortice_shader"
        wrong_contract = _run_rust_editor_gate({"rust_mesh_editor": wrong_contract_proof})
        self.assertNotEqual(0, wrong_contract.returncode)
        self.assertIn("locked Release wgpu/D3D12 Rust editor contract", wrong_contract.stderr)

        unlocked_proof = _packaged_rust_editor_fixture()
        unlocked_proof["provenance"]["locked_dependencies"] = False
        unlocked = _run_rust_editor_gate({"rust_mesh_editor": unlocked_proof})
        self.assertNotEqual(0, unlocked.returncode)
        self.assertIn("locked Release wgpu/D3D12 Rust editor contract", unlocked.stderr)

    def test_packaged_texture_gate_requires_current_real_controls_and_selection(self) -> None:
        evidence = {
            "schema": "cdmw_packaged_mesh_editor_controls_smoke_v3",
            "read_only": True,
            "archive_sources_unchanged": True,
            "production_route": "MainWindow._launch_archive_mesh_editor_for_entry",
            "actual_csharp_controls": True,
            "global_mouse_input_used": False,
            "physical_mouse_input": {
                "gesture_count": 0,
                "restore_failure_count": 0,
                "active": False,
            },
            "model_path": "character/model/body.pac",
            "helper": {
                "path": "C:/app/Cdmw.MeshEditorExperiment.exe",
                "sha256": "c" * 64,
                "process_id": 777,
                "capabilities": ["resident_interaction_abi_v1"],
                "provenance": {
                    "protocol_version": 3,
                    "manifest_mode": "release_manifest",
                    "manifest_id": "d" * 64,
                    "source_revision": "e" * 40,
                    "process_sha256": "c" * 64,
                    "shader_sha256": "f" * 64,
                    "renderer_backend": "d3d11_vortice_shader",
                    "edit_backend": "cdmw_mesh_core_0.1",
                    "native_abi": {
                        "library_path": "C:/app/cdmw-mesh-core.dll",
                        "library_sha256": "a" * 64,
                        "abi_version": 1,
                        "contract": "cdmw_mesh_interaction_abi_v1",
                        "backend": "cdmw_mesh_core_0.1",
                        "header_sha256": "b" * 64,
                    },
                },
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
                "case_count": 8,
                "settlement_p95_ms": 12.0,
                "cases": [{"stable": True} for _ in range(8)],
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
                "input_backend": "helper_ui_thread_resident_probe",
                "global_mouse_input_used": False,
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
            "resident_interactions": {
                mode: _resident_interaction_fixture(tool, mode, tool_id)
                for mode, tool, tool_id in (
                    ("select", "Select", 1),
                    ("move", "Move", 2),
                    ("grab", "Grab", 3),
                    ("smooth", "Smooth", 4),
                    ("inflate", "Inflate", 5),
                    ("pinch", "Pinch", 6),
                )
            },
            "desktop_input": {
                "ok": True,
                "method": "helper_ui_thread_no_global_input",
                "gesture_count": 0,
                "restore_failure_count": 0,
                "active": False,
            },
            "capture": {"ok": True},
            "material_update": {"resource_count": 3, "resource_file_count": 3},
            "material_failures": [],
        }

        accepted = _run_texture_gate({"evidence": evidence})
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        evidence["helper"]["provenance"]["native_abi"]["library_sha256"] = ""
        missing_native_hash = _run_texture_gate({"evidence": evidence})
        self.assertNotEqual(0, missing_native_hash.returncode)
        self.assertIn("native interaction ABI", missing_native_hash.stderr)
        evidence["helper"]["provenance"]["native_abi"]["library_sha256"] = "a" * 64

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

        evidence["grab_undo_redo"]["gates"]["grab_rearmed_after_undo"] = True
        evidence["resident_interactions"]["pinch"]["gesture"][
            "commit_v2_acknowledgement"
        ]["target_revision"] = 99
        mismatched_commit = _run_texture_gate({"evidence": evidence})
        self.assertNotEqual(0, mismatched_commit.returncode)
        self.assertIn("commit-v2 correlation field 'target_revision'", mismatched_commit.stderr)

    def test_packaged_resident_probe_requires_exact_commit_v2_correlation(self) -> None:
        from tools.mesh_harness.packaged_mesh_texture_smoke import (
            _validate_packaged_resident_probe,
        )

        gesture = _resident_interaction_fixture("Inflate", "inflate", 5)["gesture"]
        probe = {
            "ok": True,
            "request": {
                "request_id": gesture["probe_acknowledgement"]["request_id"],
            },
            "probe_acknowledgement": gesture["probe_acknowledgement"],
            "resident_interaction_transactions": [
                gesture["resident_interaction_transaction"]
            ],
            "authority_acknowledgement": gesture["commit_v2_acknowledgement"],
            "helper_originated_mutation_echo_count": 0,
            "terminal_event": "resident_interaction_transaction",
            "final_operator_state": "idle",
            "native_gesture_active_after": False,
            "begin_ms": 0.1,
            "input_sample_p95_ms": 0.2,
            "input_sample_max_ms": 0.3,
            "finish_ms": 0.1,
            "total_ms": 0.5,
        }
        transaction, acknowledgement = _validate_packaged_resident_probe(
            probe,
            mode="inflate",
        )
        self.assertEqual(1005, transaction["request_id"])
        self.assertEqual("applied", acknowledgement["status"])

        probe["authority_acknowledgement"] = {
            **gesture["commit_v2_acknowledgement"],
            "target_revision": 99,
        }
        with self.assertRaisesRegex(RuntimeError, "target_revision"):
            _validate_packaged_resident_probe(probe, mode="inflate")

    def test_current_texture_smoke_routes_real_controls_without_builder_embedding(self) -> None:
        source = (REPO_ROOT / "tools" / "mesh_harness" / "packaged_mesh_texture_smoke.py").read_text(
            encoding="utf-8"
        )

        self.assertIn("window._launch_archive_mesh_editor_for_entry(entry)", source)
        self.assertIn(
            'select_control = _click_button_by_text(\n        form_hwnd,\n        "Select",',
            source,
        )
        self.assertIn(
            'tool_control = _click_button_by_text(\n        form_hwnd,\n        tool_text,',
            source,
        )
        self.assertIn("scroll_clipped=True", source)
        select_attempt = source.split("def _perform_actual_select_attempt(", 1)[1].split(
            "def _exercise_actual_select_control(", 1
        )[0]
        grab_attempt = source.split("def _perform_actual_grab(", 1)[1].split(
            "def _perform_actual_history_command(", 1
        )[0]
        resident_tool_attempt = source.split("def _perform_actual_resident_tool(", 1)[1].split(
            "def _perform_actual_grab(", 1
        )[0]
        helper_identity = source.split("def _helper_identity(", 1)[1].split(
            "def _application_identity(", 1
        )[0]
        self.assertIn("_request_packaged_interaction_probe(", select_attempt)
        self.assertIn('mode="select_brush_vertex"', select_attempt)
        self.assertNotIn('_latest_event(\n                mesh_editor_tab,\n                "resident_mutation_batch_ack"', select_attempt)
        self.assertEqual(1, select_attempt.count('"resident_mutation_batch_ack"'))
        self.assertIn("helper_originated_mutation_echo_count", select_attempt)
        self.assertIn('mode="grab"', grab_attempt)
        self.assertIn("_perform_actual_resident_tool(", grab_attempt)
        self.assertIn("_request_packaged_interaction_probe(", resident_tool_attempt)
        self.assertIn("mode=mode", resident_tool_attempt)
        self.assertIn('{"event": "tool_state", "tool": "orbit"}', resident_tool_attempt)
        self.assertLess(
            resident_tool_attempt.index('{"event": "tool_state", "tool": "orbit"}'),
            resident_tool_attempt.index("tool_control = _click_button_by_text("),
        )
        self.assertIn('_latest_event(mesh_editor_tab, "protocol_ready")', helper_identity)
        self.assertIn('"provenance"', helper_identity)
        self.assertNotIn('"select_request"', select_attempt)
        self.assertNotIn('"stroke_begin"', resident_tool_attempt)
        self.assertNotIn('event_name="stroke_end"', resident_tool_attempt)
        for mode in ("select_brush_vertex", "move", "grab", "smooth", "inflate", "pinch"):
            self.assertIn(f'"{mode}"', source)
        self.assertIn("_validate_packaged_resident_probe(", source)
        self.assertIn('"resident_interactions"', source)
        self.assertIn('command_text="Undo"', source)
        self.assertIn('command_text="Redo"', source)
        self.assertIn("_exercise_actual_control_continuity(", source)
        self.assertIn('control.get("message_dispatch_ms"', source)
        self.assertIn('_select_combo_item_by_text(\n        form_hwnd,\n        "Solid (Textured)"', source)
        textured_activation = source.split("def _activate_solid_textured_control(", 1)[1].split(
            "def _perform_actual_select_attempt(", 1
        )[0]
        self.assertNotIn('_click_button_by_text(form_hwnd, "Viewport"', textured_activation)
        self.assertNotIn('"page_control"', textured_activation)
        self.assertIn('"viewport_controls_pinned": True', textured_activation)
        self.assertLess(
            source.index("textured = _activate_solid_textured_control("),
            source.index("control_continuity = _exercise_actual_control_continuity("),
        )
        self.assertIn('"global_mouse_input_used": False', source)
        self.assertIn('"method": "helper_ui_thread_no_global_input"', source)
        self.assertIn("_physical_mouse_input_evidence()", source)
        self.assertNotIn("_send_physical_mouse_message", source)
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
