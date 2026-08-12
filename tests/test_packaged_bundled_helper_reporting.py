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
            "schema": "cdmw_packaged_mesh_texture_smoke_v1",
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
        self.assertNotIn("material_maker", keys)
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

    def test_packaged_texture_gate_requires_both_real_textured_modes(self) -> None:
        evidence = {
            "schema": "cdmw_packaged_mesh_texture_smoke_v1",
            "read_only": True,
            "archive_sources_unchanged": True,
            "model_path": "character/model/body.pac",
            "normal_mode": {
                "selected_mode": "textured",
                "renderer_resources": {
                    "display_mode": "textured",
                    "textures_enabled": True,
                    "live_texture_srvs": 3,
                    "textured_draw_calls": 2,
                },
            },
            "edit_mode": {
                "selected_mode": "textured",
                "renderer_resources": {
                    "display_mode": "textured",
                    "textures_enabled": True,
                    "live_texture_srvs": 3,
                    "textured_draw_calls": 2,
                },
            },
            "material_update": {"resource_count": 3, "resource_file_count": 3},
            "material_failures": [],
        }

        accepted = _run_texture_gate({"evidence": evidence})
        self.assertEqual(0, accepted.returncode, accepted.stderr)

        evidence["edit_mode"]["selected_mode"] = "untextured_faces"
        rejected = _run_texture_gate({"evidence": evidence})
        self.assertNotEqual(0, rejected.returncode)
        self.assertIn("did not retain Solid (Textured)", rejected.stderr)

    def test_texture_smoke_waits_for_protocol_settle_before_renderer_probe(self) -> None:
        from tools.mesh_harness import packaged_mesh_texture_smoke as smoke

        class FakeCombo:
            def __init__(self) -> None:
                self.index = 0
                self.values = ("untextured_faces", "textured")

            def findData(self, value: object) -> int:
                try:
                    return self.values.index(value)
                except ValueError:
                    return -1

            def setCurrentIndex(self, index: int) -> None:
                self.index = index

            def currentData(self) -> str:
                return self.values[self.index]

        class FakeTab:
            standalone_dotnet_pending_textured_view = False
            standalone_dotnet_scene_pending: object = {"request_id": 1}
            standalone_dotnet_presentation_pending: object = {"request_id": 2}
            standalone_dotnet_presentation_queued = True
            standalone_dotnet_process_generation = 7
            standalone_dotnet_texture_resources_ready_by_role = {
                "editable_imported": True,
                "original_reference": True,
            }
            standalone_dotnet_applied_material_generation_by_role = {
                "editable_imported": 3,
                "original_reference": 3,
            }
            standalone_dotnet_status_payload: dict[str, object] = {}

            def __init__(self) -> None:
                self.package_active = True
                self.compile_active = True
                self.status_requests: list[dict[str, object]] = []

            def _standalone_dotnet_package_worker_active(self) -> bool:
                return self.package_active

            def _dotnet_material_compile_active(self) -> bool:
                return self.compile_active

            def _dotnet_target_controller(self) -> object:
                return SimpleNamespace(
                    session_view=lambda: SimpleNamespace(session_id="texture-smoke-session")
                )

            def _send_dotnet_protocol_message(self, payload: dict[str, object]) -> bool:
                self.status_requests.append(dict(payload))
                self.standalone_dotnet_status_payload = {
                    "renderer_status_response": {"request_id": payload["request_id"]},
                    "renderer": {
                        "display_mode": "textured",
                        "textures_enabled": True,
                        "geometry_resources": {
                            "live_texture_srvs": 3,
                            "texture_srv_creates": 3,
                            "textured_solid_batch_draws": 2,
                        },
                    },
                }
                return True

        tab = FakeTab()
        combo = FakeCombo()

        def settle(_app: object, predicate: object, *, label: str, **_kwargs: object) -> float:
            if label == "Edit Mesh Solid (Textured)":
                self.assertFalse(predicate())
                tab.standalone_dotnet_scene_pending = None
                tab.standalone_dotnet_presentation_pending = None
                tab.standalone_dotnet_presentation_queued = False
                tab.package_active = False
                tab.compile_active = False
                self.assertTrue(predicate())
                return 12.0
            self.assertEqual("Edit Mesh Solid (Textured) renderer textured draw", label)
            self.assertTrue(predicate())
            return 1.0

        with mock.patch.object(smoke, "_pump_until", side_effect=settle):
            result = smoke._select_textured_mode(
                SimpleNamespace(processEvents=lambda: None),
                tab,
                combo,
                label="Edit Mesh Solid (Textured)",
            )

        self.assertEqual("textured", result["selected_mode"])
        self.assertEqual(1, len(tab.status_requests))


if __name__ == "__main__":
    unittest.main()
