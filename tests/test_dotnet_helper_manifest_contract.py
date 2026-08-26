"""The release build derives the .NET helper manifest from the helper's sources.

`build_pyside6_app.ps1` writes `cdmw-mesh-dotnet-editor.manifest.json`, then runs
the published helper and refuses the build when the two disagree. That gate fires
at the end of a full native and .NET compile, so a contract the build script gets
wrong costs minutes and reads as an unexplained packaging failure. These checks
run the build script's own derivation against the helper sources in seconds.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
BUILD_SCRIPT = REPO_ROOT / "build_pyside6_app.ps1"
DOTNET_ROOT = REPO_ROOT / "tools" / "dotnet_mesh_editor_experiment"
PROVENANCE_SOURCE = DOTNET_ROOT / "HelperBuildProvenance.cs"
PROJECT_FILE = DOTNET_ROOT / "Cdmw.MeshEditorExperiment.csproj"
CONTRACT_FUNCTION = "Get-DotNetMeshEditorHelperContract"


def _helper_capabilities_from_source() -> list[str]:
    source = PROVENANCE_SOURCE.read_text(encoding="utf-8")
    block = re.search(
        r"RequiredProtocolCapabilities\s*=\s*\{(?P<body>.*?)\};",
        source,
        re.DOTALL,
    )
    assert block is not None, (
        f"{PROVENANCE_SOURCE.name} no longer declares RequiredProtocolCapabilities as an "
        "array initializer. The build script parses that declaration to write the helper "
        "manifest, so update Get-DotNetMeshEditorHelperContract in build_pyside6_app.ps1 "
        "to match the new shape."
    )
    body = re.sub(r"//[^\r\n]*", "", block.group("body"))
    return re.findall(r'"([^"]+)"', body)


def _run_contract_function() -> dict[str, object]:
    powershell = shutil.which("powershell") or shutil.which("pwsh")
    if powershell is None:
        pytest.skip("PowerShell is unavailable, so the build script cannot be exercised.")

    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    function_block = re.search(
        rf"(?s)function {CONTRACT_FUNCTION} \{{.*?\n\}}\r?\n",
        script_text,
    )
    assert function_block is not None, (
        f"{BUILD_SCRIPT.name} no longer defines {CONTRACT_FUNCTION}. The helper manifest "
        "must keep deriving its contract from the .NET sources rather than restating it."
    )

    command = (
        f"$ErrorActionPreference = 'Stop'; $scriptDir = '{REPO_ROOT}'; "
        f"{function_block.group(0)}\n"
        f"{CONTRACT_FUNCTION} | ConvertTo-Json -Depth 4 -Compress"
    )
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        check=False,
        cwd=REPO_ROOT,
    )
    assert completed.returncode == 0, (
        f"{CONTRACT_FUNCTION} failed: {completed.stdout}\n{completed.stderr}"
    )
    return json.loads(completed.stdout)


def test_build_script_derives_the_helper_capabilities() -> None:
    contract = _run_contract_function()
    derived = [str(capability) for capability in contract["Capabilities"]]
    assert derived == _helper_capabilities_from_source(), (
        "The manifest capabilities the release build writes no longer match "
        f"{PROVENANCE_SOURCE.name}. The published helper reports its own list and the "
        "build refuses any mismatch, so this would fail the release build."
    )


def test_build_script_derives_the_helper_versions() -> None:
    contract = _run_contract_function()

    protocol_version = re.search(
        r'\["protocol_version"\]\s*=\s*(\d+)',
        PROVENANCE_SOURCE.read_text(encoding="utf-8"),
    )
    assert protocol_version is not None
    assert int(contract["ProtocolVersion"]) == int(protocol_version.group(1))

    semantic_version = re.search(
        r"<Version>\s*(\d+\.\d+\.\d+)[^<]*</Version>",
        PROJECT_FILE.read_text(encoding="utf-8"),
    )
    assert semantic_version is not None
    assert str(contract["SemanticVersion"]) == semantic_version.group(1)


def test_build_script_does_not_restate_the_capability_list() -> None:
    script_text = BUILD_SCRIPT.read_text(encoding="utf-8")
    restated = sorted(
        capability
        for capability in _helper_capabilities_from_source()
        if f'"{capability}"' in script_text
    )
    assert not restated, (
        "build_pyside6_app.ps1 names protocol capabilities directly: "
        f"{', '.join(restated)}. A hand-maintained copy drifts the moment the .NET side "
        "adds one, and the drift only surfaces at the end of a full release build. "
        f"Let {CONTRACT_FUNCTION} read them from {PROVENANCE_SOURCE.name} instead."
    )


def test_helper_provenance_resolves_its_dll_without_assembly_location() -> None:
    source = PROVENANCE_SOURCE.read_text(encoding="utf-8")

    assert "assembly.Location" not in source
    assert 'Path.Combine(AppContext.BaseDirectory, $"{assembly.GetName().Name}.dll")' in source
    assert "File.Exists(assemblyCandidatePath) ? assemblyCandidatePath : string.Empty" in source
