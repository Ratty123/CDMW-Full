from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
HELPER = (
    ROOT
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "bin"
    / "Release"
    / "net10.0-windows"
    / "cdmw-mesh-dotnet-editor.dll"
)


def test_modal_operator_contract_reaches_terminal_states() -> None:
    assert HELPER.is_file(), f"Release Mesh Editor helper is missing: {HELPER}"
    with tempfile.TemporaryDirectory(prefix="cdmw-mesh-edit-operator-") as temp_dir:
        report = Path(temp_dir) / "operator.json"
        completed = subprocess.run(
            (
                "dotnet",
                str(HELPER),
                "--headless-mesh-edit-operator-contract",
                "--mesh-edit-operator-report",
                str(report),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        payload = json.loads(report.read_text(encoding="utf-8"))

    assert payload["schema"] == "cdmw_mesh_edit_operator_contract_v1"
    assert payload["ok"] is True
    assert all(payload["gates"].values())
    assert payload["gates"]["mixed_1000_cycle_rearm"] is True
    assert set(payload["required_states"]) == {
        "idle",
        "armed",
        "preparing",
        "running",
        "confirming",
        "awaitingcommit",
        "awaitingrenderer",
        "recovering",
        "failed",
    }
