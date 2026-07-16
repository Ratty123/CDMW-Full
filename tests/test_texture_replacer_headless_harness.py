from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HARNESS = ROOT / "tools" / "texture_replacer_headless_harness.py"


def test_missing_native_helper_returns_prerequisite_exit_and_result_json(tmp_path: Path) -> None:
    output = tmp_path / "harness-output"
    completed = subprocess.run(
        [
            sys.executable,
            str(HARNESS),
            "--scenario",
            "policy-matrix",
            "--output",
            str(output),
            "--native-binary",
            str(tmp_path / "missing" / "cd-texture-dx.exe"),
        ],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 2
    result = json.loads((output / "result.json").read_text(encoding="utf-8"))
    assert result["schema_version"] == 1
    assert result["selected_scenario"] == "policy-matrix"
    assert result["passed"] is False
    assert result["exit_code"] == 2
    assert result["failures"][0]["type"] == "HarnessPrerequisiteError"
    assert "Native texture helper is missing" in result["failures"][0]["message"]


def test_cli_declares_all_required_scenarios_and_inputs() -> None:
    completed = subprocess.run(
        [sys.executable, str(HARNESS), "--help"],
        cwd=ROOT,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=60,
        check=False,
    )
    assert completed.returncode == 0
    help_text = completed.stdout
    for scenario in (
        "reported-bc7-rebuild",
        "policy-matrix",
        "consumer-matrix",
        "failure-lifecycle",
        "full-suite",
    ):
        assert scenario in help_text
    for option in (
        "--output",
        "--native-binary",
        "--edited-dds",
        "--original-dds",
        "--virtual-path",
    ):
        assert option in help_text
