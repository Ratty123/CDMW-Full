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


def test_real_mesh_editor_control_tree_is_fully_classified() -> None:
    assert HELPER.is_file(), f"Release Mesh Editor helper is missing: {HELPER}"
    with tempfile.TemporaryDirectory(prefix="cdmw-mesh-control-contract-") as temp_dir:
        report_path = Path(temp_dir) / "control-contract.json"
        completed = subprocess.run(
            (
                "dotnet",
                str(HELPER),
                "--headless-edit-mesh-entry-smoke",
                "--control-contract-only",
                "--edit-mesh-entry-report",
                str(report_path),
            ),
            cwd=ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            timeout=90,
            check=False,
        )
        assert report_path.is_file(), completed.stderr
        report = json.loads(report_path.read_text(encoding="utf-8"))

    assert completed.returncode == 0, json.dumps(report, indent=2)
    contract = report["control_contract"]
    assert report["ok"] is True
    assert contract["schema"] == "cdmw_mesh_editor_control_contract_v1"
    assert contract["ok"] is True
    assert contract["proof_class"] == "headless_real_form_construction"
    assert contract["visual_proof"] is False
    assert contract["renderer_started"] is False
    assert contract["control_count"] >= 100
    assert contract["row_count"] >= contract["control_count"]
    assert contract["unresolved_rows"] == []
    assert contract["unclassified_controls"] == []
    assert contract["classified_outside_reachable_surface"] == []
    assert contract["duplicate_control_rows"] == []
    assert contract["duplicate_keys"] == []
    assert contract["invalid_disabled_rows"] == []
    assert contract["enabled_disabled_controls"] == []
    assert contract["invalid_dispositions"] == []
    assert contract["missing_surfaces"] == []
    assert contract["disabled_controls_without_user_reason"] == []

    rows = contract["rows"]
    by_key = {row["key"]: row for row in rows}
    assert len(by_key) == len(rows)
    assert set(contract["required_surfaces"]) == {
        "session",
        "selection",
        "tools",
        "topology",
        "parts_layers",
        "morph_refit",
        "material_colour",
        "camera_display",
        "import_output_export",
        "exact_free_edit",
    }
    assert {
        "tool.select",
        "tool.move",
        "tool.grab",
        "tool.smooth",
        "tool.inflate",
        "tool.pinch",
        "selection.target",
        "selection.shape",
        "selection.operation",
        "selection.xray",
        "session.undo",
        "session.redo",
        "topology.delete_selection",
        "parts.selection",
        "layers.list",
        "colour.tint",
        "colour.recolour",
        "colour.emissive_enabled",
        "colour.reset",
        "morph.profile",
        "refit.apply",
        "display.mode",
        "camera.fit",
        "viewport.pointer_surface",
        "output.configure_free_edit",
        "output.export_free_edit",
        "import.open_package",
        "policy.exact_free_edit",
    }.issubset(by_key)
    assert "material_colour.unavailable" not in by_key
    assert all(row["owner"] and row["route"] and row["evidence_category"] for row in rows)
    assert {row["disposition"] for row in rows} <= {
        "executable",
        "deliberately_disabled",
    }
    assert all(
        row["disposition"] != "deliberately_disabled" or row["reason"].strip()
        for row in rows
    )
    disabled_keys = {
        row["key"]
        for row in rows
        if row["disposition"] == "deliberately_disabled"
    }
    assert set(contract["disabled_controls_without_user_reason"]) <= disabled_keys
    assert all(
        row["host_owned"] or row["control_type"] != "host"
        for row in rows
    )
