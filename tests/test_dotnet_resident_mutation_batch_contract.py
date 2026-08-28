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


def test_resident_mutation_batch_contract_executes_csharp_behavior() -> None:
    assert HELPER.is_file(), f"Release Mesh Editor helper is missing: {HELPER}"
    with tempfile.TemporaryDirectory(prefix="cdmw-resident-mutation-") as temp_dir:
        report = Path(temp_dir) / "resident-mutation.json"
        completed = subprocess.run(
            (
                "dotnet",
                str(HELPER),
                "--headless-resident-mutation-batch-contract",
                "--resident-mutation-report",
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

    assert payload["schema"] == "cdmw_resident_mutation_batch_contract_v1"
    assert payload["capability"] == "resident_mutation_batch_v3"
    assert payload["ok"] is True
    assert all(payload["gates"].values())
    assert {
        "vertex_material_selection_prepared",
        "topology_append_staged",
        "topology_shrink_staged",
        "topology_material_selection_prepared",
        "invalid_vertex_rejected_without_mutation",
        "invalid_topology_rejected_without_mutation",
        "invalid_material_rejected_without_mutation",
        "invalid_selection_rejected_without_mutation",
        "failure_before_final_commit_leaves_previous_state",
        "duplicate_accepted_request_is_idempotent",
        "duplicate_rejected_request_stays_rejected",
        "wrong_session_rejected",
        "wrong_process_generation_rejected",
        "invalid_base_revision_rejected",
    }.issubset(payload["gates"])
