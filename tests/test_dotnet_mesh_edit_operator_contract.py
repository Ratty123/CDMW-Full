from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile

import pytest


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


def test_authoritative_resync_rearms_real_viewport_grab() -> None:
    assert HELPER.is_file(), f"Release Mesh Editor helper is missing: {HELPER}"
    with tempfile.TemporaryDirectory(prefix="cdmw-mesh-edit-resync-") as temp_dir:
        report = Path(temp_dir) / "resync.json"
        completed = subprocess.run(
            (
                "dotnet",
                str(HELPER),
                "--headless-gpu-interaction-soak",
                "--interaction-soak-mode",
                "grab",
                "--frame-pacing-smoke",
                "--frame-pacing-report",
                str(report),
            ),
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if completed.returncode != 0 and report.is_file():
            failure = json.loads(report.read_text(encoding="utf-8"))
            message = str(failure.get("error", {}).get("message", ""))
            if "0x887A002D" in message and "SDK_COMPONENT_MISSING" in message:
                pytest.skip(
                    "The D3D11 debug layer requires the 64-bit Windows Graphics Tools capability."
                )
        assert completed.returncode == 0, completed.stderr or completed.stdout
        payload = json.loads(report.read_text(encoding="utf-8"))

    proof = payload["authoritative_resync_rearm_proof"]
    assert payload["ok"] is True
    assert payload["lifecycle"]["backend"] == "d3d11_vortice_shader"
    assert payload["gates"]["authoritative_resync_rearms_modal_tool"] is True
    assert payload["gates"]["hardware_d3d11_debug_layer_clean"] is True
    assert payload["gates"]["warp_d3d11_debug_layer_clean"] is True
    assert payload["gates"]["d3d11_adapter_provenance_recorded"] is True
    for driver_type in ("hardware", "warp"):
        debug = payload["d3d11_debug_layer"][driver_type]
        assert debug["ok"] is True
        assert debug["driver_type"] == driver_type
        assert debug["debug_layer_requested"] is True
        assert debug["debug_layer_active"] is True
        assert debug["capture_started"] is True
        assert debug["stored_message_count"] == 0
        assert debug["discarded_message_count"] == 0
        assert debug["adapter_description"]
        assert debug["feature_level"]
    assert proof == {
        "ok": True,
        "awaited_authority_before_reset": True,
        "provisional_cleared": True,
        "state_after_reset": "idle",
        "returned_idle": True,
        "next_grab_rearmed": True,
    }
