from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUST_ROOT = ROOT / "tools" / "rust_mesh_lab"
COMPARISON_FIELDS = (
    "key",
    "surface",
    "disposition",
    "availability",
    "host_owned",
    "reason",
)


def test_rust_v2_contract_is_generated_only_from_compiled_rust_controls() -> None:
    with tempfile.TemporaryDirectory(prefix="cdmw-rust-control-contract-") as temporary:
        temporary_root = Path(temporary)
        rust_report = temporary_root / "rust.json"
        rust = subprocess.run(
            (
                "cargo",
                "run",
                "--locked",
                "--quiet",
                "-p",
                "cdmw_mesh_lab",
                "--",
                "--control-contract-json",
                str(rust_report),
            ),
            cwd=RUST_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            env=dict(os.environ),
            text=True,
            timeout=180,
            check=False,
        )
        assert rust.returncode == 0, rust.stderr
        integrated = json.loads(rust_report.read_text(encoding="utf-8"))

    assert integrated["ok"] is True
    assert integrated["schema"] == "cdmw_rust_mesh_editor_control_contract_v2"
    assert integrated["renderer"] == "wgpu_d3d12_rust"
    assert integrated["edit_backend"] == "cdmw_rust_mesh_0.1"
    assert integrated["row_count"] == len(integrated["rows"])
    assert integrated["row_count"] >= 130
    assert integrated["runtime_route_registry"] == "compiled_rust_integrated_ui_v2"
    assert integrated["missing_runtime_routes"] == []
    assert integrated["unverified_runtime_routes"] == []
    assert integrated["duplicate_runtime_control_ids"] == []
    runtime_control_ids: set[str] = set()
    route_kinds: set[str] = set()
    for integrated_row in integrated["rows"]:
        assert all(field in integrated_row for field in COMPARISON_FIELDS)
        control_id = integrated_row["rust_control_id"]
        assert control_id.startswith("rust.integrated.")
        assert control_id not in runtime_control_ids
        runtime_control_ids.add(control_id)

        route_kind = integrated_row["rust_route_kind"]
        route_target = integrated_row["rust_route_target"]
        route_kinds.add(route_kind)
        assert route_kind not in {"unregistered", ""}
        assert route_target
        assert integrated_row["rust_route"] == f"{route_kind}:{route_target}"
        assert integrated_row["rust_route"] != (
            "Rust UiAction or typed CDMW shadow command"
        )
        assert integrated_row["rust_source_binding_verified"] is True
        assert integrated_row["rust_implemented"] is True
        assert (
            integrated_row["rust_implementation_basis"]
            == "compiled_runtime_binding_registry_v2"
        )
        if integrated_row["disposition"] == "executable" or integrated_row["currently_enabled"]:
            assert route_kind != "deliberately_unavailable"

    assert len(runtime_control_ids) == integrated["row_count"]
    assert {
        "local_tool",
        "local_page",
        "local_state",
        "ui_action",
        "typed_shadow_command",
        "typed_shadow_topology",
        "host_action",
        "pointer_gesture",
        "read_only_state",
        "deliberately_unavailable",
        "compiled_anchor",
    } <= route_kinds
    unavailable = {
        row["key"]
        for row in integrated["rows"]
        if row["rust_route_kind"] == "deliberately_unavailable"
    }
    assert unavailable == {"material_colour.unavailable", "parts.visibility"}
    assert all(
        row["rust_runtime_dispatch"] is True
        for row in integrated["rows"]
        if row["rust_route_kind"]
        not in {"deliberately_unavailable", "read_only_state"}
    )
    assert all(
        set(row["rust_state_feedback"])
        == {"enabled", "disabled", "selected", "hover", "pressed", "failure_reason"}
        for row in integrated["rows"]
    )


def test_release_packaging_requires_locked_rust_helper_and_provenance() -> None:
    build_source = (ROOT / "build_pyside6_app.ps1").read_text(encoding="utf-8")
    spec_source = (ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
    notices = (ROOT / "tools" / "rust_mesh_lab" / "THIRD_PARTY_NOTICES.md").read_text(
        encoding="utf-8"
    )

    assert '"build", "--locked", "-p", "cdmw_mesh_lab"' in build_source
    assert 'cargoArguments += "--release"' in build_source
    assert "cdmw_rust_mesh_editor_build_provenance_v1" in build_source
    assert "Get-RustMeshEditorSourceFingerprint" in build_source
    assert "[IO.Path]::GetRelativePath" not in build_source
    assert "$sourceFullName.Substring($rustRootPrefix.Length)" in build_source
    assert "--control-contract-json" in build_source
    assert "CDMW_VORTICE_CONTROL_CONTRACT_JSON" not in build_source
    assert "Assert-RustMeshEditorControlContract" in build_source
    assert (
        "Get-Content -LiteralPath $controlContractPath -Encoding UTF8 -Raw"
        in build_source
    )
    assert "vorticeControlContractPath" not in build_source
    assert "vortice_control_contract_sha256" not in build_source
    rust_build_source = build_source.split("function Invoke-RustMeshEditorBuild", 1)[1].split(
        ". (Join-Path $scriptDir", 1
    )[0]
    assert "row_count -ne 104" not in rust_build_source
    assert 'rust_mesh_editor_stage = f"native/rust_mesh_editor/build/{NATIVE_CONFIGURATION}"' in spec_source
    assert "_validate_rust_mesh_editor_payload" in spec_source
    assert '"cdmw_mesh_lab.manifest.json"' in spec_source
    assert '"cdmw_mesh_lab.control-contract.json"' in spec_source
    assert '"cdmw_mesh_lab.vortice-control-contract.json"' not in spec_source
    assert '"vortice_control_contract_sha256"' not in spec_source
    assert '"native/rust_mesh_editor"' in spec_source
    assert "wgpu" in notices
    assert "Cargo.lock" in notices

    compile(spec_source, str(ROOT / "CrimsonDesertModWorkbench.spec"), "exec")


def _load_spec_rust_payload_validator():
    spec_path = ROOT / "CrimsonDesertModWorkbench.spec"
    parsed = ast.parse(spec_path.read_text(encoding="utf-8"), filename=str(spec_path))
    selected = [
        node
        for node in parsed.body
        if isinstance(node, ast.FunctionDef)
        and node.name in {"_sha256", "_validate_rust_mesh_editor_payload"}
    ]
    namespace = {
        "hashlib": hashlib,
        "json": json,
        "NATIVE_CONFIGURATION": "Release",
    }
    exec(compile(ast.Module(body=selected, type_ignores=[]), str(spec_path), "exec"), namespace)
    return namespace["_validate_rust_mesh_editor_payload"]


def test_packaging_validator_rejects_hash_and_rust_contract_mismatches(tmp_path: Path) -> None:
    validate = _load_spec_rust_payload_validator()
    executable = tmp_path / "cdmw_mesh_lab.exe"
    rust_contract_path = tmp_path / "cdmw_mesh_lab.control-contract.json"
    manifest_path = tmp_path / "cdmw_mesh_lab.manifest.json"
    executable.write_bytes(b"rust-helper")
    baseline_row = {
        "key": "top.finish",
        "surface": "top_session_bar",
        "disposition": "executable",
        "availability": "enabled",
        "host_owned": False,
        "reason": "",
    }
    rust_contract = {
        "ok": True,
        "schema": "cdmw_rust_mesh_editor_control_contract_v2",
        "row_count": 1,
        "preview_contract": {
            "ok": True,
            "schema": "cdmw_rust_preview_control_contract_v1",
            "protocol": "cdmw_rust_preview_protocol_v1",
            "package": "cdmw_rust_preview_package_v1",
            "viewport_only": True,
            "commands": [
                {
                    "command": "package_load_request",
                    "compiled_dispatch": True,
                }
            ],
        },
        "rows": [
            {
                **baseline_row,
                "rust_implemented": True,
                "rust_state_feedback": [
                    "enabled",
                    "disabled",
                    "selected",
                    "hover",
                    "pressed",
                    "failure_reason",
                ],
            }
        ],
    }
    rust_contract_path.write_text(json.dumps(rust_contract), encoding="utf-8")

    def write_manifest() -> None:
        manifest_path.write_text(
            json.dumps(
                {
                    "schema": "cdmw_rust_mesh_editor_build_provenance_v1",
                    "renderer": "wgpu_d3d12_rust",
                    "edit_backend": "cdmw_rust_mesh_0.1",
                    "protocol": "cdmw_rust_mesh_editor_protocol_v1",
                    "authoring_package": "cdmw_rust_mesh_authoring_package_v1",
                    "preview_protocol": "cdmw_rust_preview_protocol_v1",
                    "preview_package": "cdmw_rust_preview_package_v1",
                    "preview_backend": "cdmw_rust_preview_0.1",
                    "build_profile": "release",
                    "locked_dependencies": True,
                    "executable": executable.name,
                    "control_contract": rust_contract_path.name,
                    "control_contract_schema": "cdmw_rust_mesh_editor_control_contract_v2",
                    "capabilities": [
                        "embedded_child_window_v1",
                        "rust_preview_runtime_v1",
                    ],
                    "preview_capabilities": [
                        "preview_profile_read_only_v1",
                        "preview_session_v1",
                        "resident_package_load_v1",
                        "resident_preview_package_replace_v2",
                        "absolute_camera_state_v1",
                        "view_state_changed_v1",
                        "viewport_display_modes_v1",
                        "read_only_part_pick_v1",
                        "overlay_state_update_v1",
                        "skeleton_overlay_v1",
                        "pbd_cloth_overlay_v1",
                        "deterministic_offscreen_capture_v1",
                        "comparison_scene_v1",
                        "alignment_preview_v1",
                        "static_replacement_mesh_input_v1",
                        "effect_particle_preview_v1",
                        "ui_theme_state_v1",
                        "ui_localization_v1",
                    ],
                    "source_revision": "synthetic-test",
                    "source_tree_sha256": "1" * 64,
                    "cargo_lock_sha256": "2" * 64,
                    "cargo_version": "cargo synthetic",
                    "rustc_version": "rustc synthetic",
                    "executable_sha256": hashlib.sha256(executable.read_bytes()).hexdigest(),
                    "control_contract_sha256": hashlib.sha256(
                        rust_contract_path.read_bytes()
                    ).hexdigest(),
                }
            ),
            encoding="utf-8",
        )

    write_manifest()
    validate(tmp_path, required_release=True)

    executable.write_bytes(b"tampered")
    with pytest.raises(SystemExit, match="executable_sha256"):
        validate(tmp_path, required_release=True)

    executable.write_bytes(b"rust-helper")
    rust_contract["schema"] = "cdmw_rust_mesh_editor_control_contract_v1"
    rust_contract_path.write_text(json.dumps(rust_contract), encoding="utf-8")
    write_manifest()
    with pytest.raises(SystemExit, match="control contract is invalid"):
        validate(tmp_path, required_release=True)
