"""Native build configuration and source-derived ABI provenance."""

import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = ROOT / "build_pyside6_app.ps1"
NATIVE_ABI_CONTRACT_FUNCTION = "Get-NativeMeshInteractionAbiContract"
NATIVE_ABI_HEADER = ROOT / "native/cdmw_mesh_core/src/mesh_interaction_abi.h"
NATIVE_ABI_IMPLEMENTATION = ROOT / "native/cdmw_mesh_core/src/mesh_interaction_abi.cpp"


def test_mesh_core_packaging_uses_profile_native_configuration() -> None:
    spec_source = (ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
    native_builder_source = (ROOT / "build_native_windows.ps1").read_text(encoding="utf-8")
    package_builder_source = (ROOT / "build_pyside6_app.ps1").read_text(encoding="utf-8")

    assert 'NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"' in spec_source
    assert (
        '_add_native_binary(f"native/cdmw_mesh_core/build/{NATIVE_CONFIGURATION}/cdmw-mesh-core.exe", '
        '"native", required_release=True)'
    ) in spec_source
    assert (
        '_add_native_binary(f"native/cdmw_mesh_core/build/{NATIVE_CONFIGURATION}/cdmw-mesh-core.dll", '
        '"native", required_release=True)'
    ) in spec_source
    # The retired renderer's payload tree is gone; only the native ABI copy
    # remains, selected from the active native build configuration above.
    assert 'native/cdmw_mesh_dotnet_editor/build/' not in spec_source
    assert '"native\\cdmw_mesh_core\\build\\$Configuration\\cdmw-mesh-core.dll"' in native_builder_source
    assert '"native\\cdmw_mesh_core\\build\\$Configuration\\cdmw-mesh-core.dll"' in package_builder_source


def _run_native_abi_contract_function() -> dict[str, object]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable, so the build script cannot be exercised.")

    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    hash_function = re.search(r"(?s)function Get-Sha256Hex \{.*?\n\}\r?\n", script_text)
    contract_function = re.search(
        rf"(?s)function {NATIVE_ABI_CONTRACT_FUNCTION} \{{.*?\n\}}\r?\n",
        script_text,
    )
    assert hash_function is not None
    assert contract_function is not None, (
        f"{BUILD_SCRIPT.name} no longer defines {NATIVE_ABI_CONTRACT_FUNCTION}. "
        "The release manifest must derive native ABI identity from the C ABI sources."
    )

    command = (
        f"$ErrorActionPreference = 'Stop'; $scriptDir = '{ROOT}'; "
        f"{hash_function.group(0)}\n{contract_function.group(0)}\n"
        f"{NATIVE_ABI_CONTRACT_FUNCTION} | ConvertTo-Json -Depth 4 -Compress"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 0, (
        f"{NATIVE_ABI_CONTRACT_FUNCTION} failed: {completed.stdout}\n{completed.stderr}"
    )
    return json.loads(completed.stdout)


def _run_fully_qualified_path_check(path: str) -> str:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable, so the build script cannot be exercised.")

    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    function = re.search(r"(?s)function Test-FullyQualifiedPath \{.*?\n\}\r?\n", script_text)
    assert function is not None
    command = (
        f"$ErrorActionPreference = 'Stop'; {function.group(0)}\n"
        f"if (Test-FullyQualifiedPath -LiteralPath '{path}') {{ 'true' }} else {{ 'false' }}"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        cwd=ROOT,
    )
    assert completed.returncode == 0, completed.stderr
    return completed.stdout.strip()


def test_build_script_derives_native_abi_manifest_identity() -> None:
    contract = _run_native_abi_contract_function()
    header_hash = hashlib.sha256(NATIVE_ABI_HEADER.read_bytes()).hexdigest()
    implementation = NATIVE_ABI_IMPLEMENTATION.read_text(encoding="utf-8")

    version = re.search(
        r"CDMW_MESH_INTERACTION_ABI_VERSION\s+(\d+)u?",
        NATIVE_ABI_HEADER.read_text(encoding="utf-8"),
    )
    native_contract = re.search(
        r'cdmw_mesh_interaction_abi_contract\s*\(.*?return\s+"([^"]+)";',
        implementation,
        re.DOTALL,
    )
    backend = re.search(
        r'cdmw_mesh_interaction_backend\s*\(.*?return\s+"([^"]+)";',
        implementation,
        re.DOTALL,
    )
    assert version is not None
    assert native_contract is not None
    assert backend is not None
    assert int(contract["AbiVersion"]) == int(version.group(1))
    assert contract["Contract"] == native_contract.group(1)
    assert contract["Backend"] == backend.group(1)
    assert contract["HeaderSha256"] == header_hash


def test_build_script_accepts_only_fully_qualified_windows_paths() -> None:
    assert _run_fully_qualified_path_check(r"C:\packaged\cdmw-mesh-core.dll") == "true"
    assert _run_fully_qualified_path_check(r"\relative\cdmw-mesh-core.dll") == "false"
