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


if __name__ == "__main__":
    unittest.main()
