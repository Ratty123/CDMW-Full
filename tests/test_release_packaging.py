from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from scripts.verify_release_dependencies import (
    SUPPORTED_PYTHON_RELEASES,
    read_exact_constraints,
    read_hashed_release_lock,
    release_dependency_mismatches,
    verify_release_environment,
)


ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "constraints-release.txt"
RELEASE_LOCK = ROOT / "requirements-build.txt"
BUILDER = ROOT / "build_pyside6_app.ps1"
SPEC = ROOT / "CrimsonDesertModWorkbench.spec"
STARTUP_VERIFIER = ROOT / "scripts" / "verify_packaged_startup.ps1"
ARCHIVE_BACKEND_RELEASE_HELPER = ROOT / "scripts" / "full_archive_backend_release.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-build.yml"
POWERSHELL = shutil.which("powershell.exe")


def test_release_constraints_are_exact_complete_and_installed() -> None:
    pins = read_exact_constraints(CONSTRAINTS)
    locked = read_hashed_release_lock(RELEASE_LOCK)
    locked_versions = {key: version for key, (_display_name, version, _hashes) in locked.items()}

    assert SUPPORTED_PYTHON_RELEASES == ((3, 11), (3, 14))
    assert {
        "brotli",
        "cryptography",
        "inflate64",
        "lz4",
        "multivolumefile",
        "numpy",
        "opencv-python-headless",
        "pillow",
        "psutil",
        "py7zr",
        "pybcj",
        "pycryptodomex",
        "pyinstaller",
        "pyppmd",
        "pyside6",
        "pyside6-addons",
        "pyside6-essentials",
        "shiboken6",
        "texttable",
    }.issubset(pins)
    assert {key: version for key, (_display_name, version) in pins.items()} == locked_versions
    lock_source = RELEASE_LOCK.read_text(encoding="utf-8")
    assert "--require-hashes" in lock_source
    assert "--only-binary :all:" in lock_source
    assert 'backports.zstd==1.7.0 ; python_version < "3.14"' in lock_source
    assert verify_release_environment(CONSTRAINTS) == ()


def test_release_verifier_rejects_an_unhashed_or_incomplete_lock(tmp_path: Path) -> None:
    source = RELEASE_LOCK.read_text(encoding="utf-8")
    texttable_line = next(line for line in source.splitlines() if line.startswith("texttable=="))
    hashless = tmp_path / "hashless-lock.txt"
    hashless.write_text(source.replace(texttable_line, "texttable==1.7.0"), encoding="utf-8")
    with pytest.raises(ValueError, match="has no SHA-256 hash"):
        read_hashed_release_lock(hashless)

    incomplete = tmp_path / "incomplete-lock.txt"
    incomplete.write_text(source.replace(texttable_line + "\n", ""), encoding="utf-8")
    errors = verify_release_environment(CONSTRAINTS, incomplete)
    assert "texttable: release constraint has no hashed lock entry" in errors
    assert "py7zr: active dependency texttable is not pinned in the release lock" in errors


def test_release_dependency_verifier_reports_missing_and_wrong_versions() -> None:
    pins = {
        "available": ("available", "1.2.3"),
        "missing": ("missing", "9.9.9"),
    }

    def version_getter(name: str) -> str:
        if name == "available":
            return "1.2.4"
        raise metadata.PackageNotFoundError(name)

    assert release_dependency_mismatches(pins, version_getter=version_getter) == (
        "available: installed 1.2.4, expected 1.2.3",
        "missing: missing (expected 9.9.9)",
    )


def test_release_builder_keeps_portable_self_contained_defaults_and_smokes_before_publish() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    spec_source = SPEC.read_text(encoding="utf-8")
    archive_backend_source = ARCHIVE_BACKEND_RELEASE_HELPER.read_text(encoding="utf-8")

    assert '[string]$Mode = "onefile"' in source
    assert '[string]$BuildProfile = "release"' in source
    assert "--self-contained true" in archive_backend_source
    assert "--self-contained false" not in archive_backend_source
    assert "-p:PublishSingleFile=false" in archive_backend_source
    assert "-p:PublishTrimmed=false" in archive_backend_source
    assert "scripts\\verify_release_dependencies.py" in source
    assert "generate_window_feature_provider_members" not in source
    assert "scripts\\generate_ui_localization_manifest.py" in source
    assert "scripts\\validate_ui_localization_catalogs.py" in source
    assert "constraints-release.txt" in source
    assert "scripts\\verify_packaged_startup.ps1" in source
    assert 'function Invoke-RustMeshEditorBuild' in source
    assert '$cargoArguments = @("build", "--locked", "-p", "cdmw_mesh_lab")' in source
    assert 'Assert-RustMeshEditorControlContract -RustContract $contract' in source
    assert "function Test-OnedirTextureBackend" in source
    assert "function Test-OnefileTextureBackend" in source
    assert 'Invoke-TextureBackendSelfTest -ExecutablePath $helperPath -Context "packaged onedir"' in source
    assert "CArchiveReader" in source
    assert '[str(helper_path), "self-test"]' in source
    assert 'cdmw_mesh_lab.manifest.json' in source
    assert 'cdmw_mesh_lab.control-contract.json' in source
    assert 'executable_sha256 = Get-Sha256Hex -LiteralPath $stagedExecutable' in source
    assert 'control_contract_sha256 = Get-Sha256Hex -LiteralPath $controlContractPath' in source
    assert 'preview_protocol = "cdmw_rust_preview_protocol_v1"' in source
    assert 'preview_package = "cdmw_rust_preview_package_v1"' in source
    assert 'preview_backend = "cdmw_rust_preview_0.1"' in source
    assert 'capabilities = @("embedded_child_window_v1", "rust_preview_runtime_v1")' in source
    assert "The Rust Preview control contract did not report success." in source
    assert "The Rust Preview control contract did not advertise any capabilities." in source
    assert "preview_capabilities = @(" in source
    assert "$contract.preview_contract.capabilities" in source
    assert 'Start-Process -FilePath $stagedExecutable' in source
    assert "dotnet_mesh_editor_experiment" not in source
    assert "cdmw-mesh-dotnet-editor" not in source
    assert "D3D11MaterialShaders.hlsl" not in source
    describe_only_return = 'if ($DescribeOnly) {\n    return\n}'
    localization_check = 'Stage "Verifying interface localization catalogs"'
    assert source.index(describe_only_return) < source.index(localization_check)
    assert source.index(localization_check) < source.index("Starting PyInstaller")
    assert "& $pythonExe $localizationManifestGenerator --check" in source
    assert "& $pythonExe $localizationCatalogValidator" in source
    texture_backend_stage = 'Stage "Verifying packaged native texture backend"'
    assert source.index(texture_backend_stage) < source.index('Stage "Verifying packaged startup"')
    assert source.index("Verifying packaged startup") < source.index("Publishing build output")
    assert 'NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"' in spec_source
    assert 'rust_mesh_editor_stage = f"native/rust_mesh_editor/build/{NATIVE_CONFIGURATION}"' in spec_source
    assert 'f"{rust_mesh_editor_stage}/cdmw_mesh_lab.exe"' in spec_source
    assert '"cdmw_mesh_lab.manifest.json"' in spec_source
    assert '"cdmw_mesh_lab.control-contract.json"' in spec_source
    assert '"cdmw-mesh-dotnet-editor.exe"' in spec_source
    assert 'leaf.startswith("vortice.") and leaf.endswith(".dll")' in spec_source
    assert 'native/cdmw_full_archive_backend/build/{NATIVE_CONFIGURATION}' in spec_source
    assert '"archive_backend"' in spec_source
    assert "archive_backend_debug_payloads" in spec_source
    for diagnostic_payload in (
        "createdump.exe",
        "Microsoft.DiaSymReader.Native.amd64.dll",
        "mscordaccore.dll",
        "mscordaccore_amd64_amd64_10.0.25.52411.dll",
        "mscordbi.dll",
    ):
        assert f'"{diagnostic_payload}"' in spec_source
    assert "excluded_names=archive_backend_debug_payloads" in spec_source
    assert '"cdmw/resources/localization"' in spec_source
    assert 'suffixes={".json"}' in spec_source
    assert 'scripts\\full_archive_backend_release.ps1' in source
    assert "function Invoke-FullArchiveBackendBuild" in archive_backend_source
    assert "function Test-OnedirFullArchiveBackend" in archive_backend_source
    assert "function Test-OnefileFullArchiveBackend" in archive_backend_source
    archive_backend_stage = 'Stage "Verifying packaged full archive backend"'
    assert archive_backend_stage in source
    assert source.index(archive_backend_stage) < source.index('Stage "Verifying packaged startup"')
    default_startup_smoke = "& $packagedStartupVerifier -ExecutablePath $startupSmokeExecutable"
    builder_startup_smoke = (
        "& $packagedStartupVerifier -ExecutablePath $startupSmokeExecutable -Target mesh_builder"
    )
    assert default_startup_smoke in source
    assert builder_startup_smoke in source
    assert source.index(default_startup_smoke) < source.index(builder_startup_smoke)
    assert source.index(builder_startup_smoke) < source.index("Publishing build output")


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="PowerShell behavior test")
def test_release_builder_isolates_host_injected_codex_poppler_path() -> None:
    source = BUILDER.read_text(encoding="utf-8")

    isolation_start = (
        '$packagingPathBeforeIsolation = [string][Environment]::GetEnvironmentVariable("PATH", "Process")'
    )
    filtered_path = (
        '[Environment]::SetEnvironmentVariable("PATH", $packagingPathIsolation.FilteredPath, "Process")'
    )
    restored_path = (
        '[Environment]::SetEnvironmentVariable("PATH", $packagingPathBeforeIsolation, "Process")'
    )
    assert "function Test-HostInjectedCodexPopplerPathEntry" in source
    assert "function Get-PackagingPathIsolation" in source
    assert source.index(isolation_start) < source.index(filtered_path)
    assert source.index(filtered_path) < source.index('Stage "Starting PyInstaller"')
    assert source.index('Stage "Verifying packaged startup"') < source.rindex(restored_path)
    assert f"}} finally {{\n    {restored_path}" in source

    command = f"""
. '{str(BUILDER).replace("'", "''")}' -DescribeOnly | Out-Null
$separator = [string][IO.Path]::PathSeparator
$codexPoppler = 'C:\\Users\\builder\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\native\\poppler\\Library\\bin'
$ordinaryPoppler = 'C:\\Tools\\poppler\\Library\\bin'
$unrelatedCodexRuntime = 'C:\\Users\\builder\\.cache\\codex-runtimes\\codex-primary-runtime\\dependencies\\native\\git\\cmd'
$inputPath = @('C:\\Windows\\System32', $codexPoppler, $ordinaryPoppler, $unrelatedCodexRuntime) -join $separator
$isolation = Get-PackagingPathIsolation -PathValue $inputPath
$expectedPath = @('C:\\Windows\\System32', $ordinaryPoppler, $unrelatedCodexRuntime) -join $separator
if ($isolation.FilteredPath -cne $expectedPath) {{ exit 20 }}
if (@($isolation.RemovedEntries).Count -ne 1) {{ exit 21 }}
if ($isolation.RemovedEntries[0] -cne $codexPoppler) {{ exit 22 }}
exit 0
"""
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"


def test_onedir_publish_removes_runtime_artifacts_created_by_startup_smoke() -> None:
    source = BUILDER.read_text(encoding="utf-8")

    assert 'foreach ($artifactName in @("workspace", "CrimsonDesertModWorkbench.cfg"))' in source
    cleanup_call = "Remove-PackagedOnedirRuntimeArtifacts -OnedirPath $builtDir"
    publish_call = "Move-PathWithRetries -SourcePath $builtDir -DestinationPath $finalOutputPath"
    assert cleanup_call in source
    assert source.index(cleanup_call) < source.index(publish_call)


def test_release_spec_collects_all_app_submodules_for_lazy_facades() -> None:
    from PyInstaller.utils.hooks import collect_submodules
    from cdmw.ui.archive_browser.workspace import ArchiveBrowserWorkspace
    from cdmw.ui.shell.workbench import WorkbenchWindow
    from cdmw.ui.texture_workflow.workspace import TexturesWorkspace

    owners = (WorkbenchWindow, ArchiveBrowserWorkspace, TexturesWorkspace)
    collected = set(collect_submodules("cdmw"))
    assert "cdmw.core.ncnn_model_catalog" in collected
    assert {base.__module__ for owner in owners for base in owner.__mro__
            if base.__module__.startswith("cdmw.")} <= collected
    source = SPEC.read_text(encoding="utf-8")
    assert "from PyInstaller.utils.hooks import collect_all, collect_submodules" in source
    assert 'hiddenimports += collect_submodules("cdmw", filter=_should_collect_cdmw_submodule)' in source
    assert '"cdmw.services.mesh_dotnet_experiment"' in source
    assert '"cdmw.services.mesh_dotnet_runtime_status"' in source
    assert "Retired Vortice preview payload was collected" in source


def test_windows_workflow_gates_packaging_on_both_headless_python_releases() -> None:
    """A package must never ship on QA that skipped an interpreter.

    A push to main runs only the interpreter the package is built with, because
    the second leg is a compatibility check rather than a different suite. That
    stays safe only while packaging cannot happen on a push: the package job is
    restricted to tags and manual dispatch, and on those events the matrix is
    the full list again. Assert that pair rather than a literal matrix line, or
    the trim reads as a hole in release gating.
    """

    source = WORKFLOW.read_text(encoding="utf-8")

    assert "fromJSON('[\"3.11\", \"3.14\"]')" in source
    assert (
        "if: github.event_name == 'workflow_dispatch' "
        "|| startsWith(github.ref, 'refs/tags/')"
    ) in source
    assert "(github.event_name == 'push' && !startsWith(github.ref, 'refs/tags/'))" in source
    assert "needs: qa" in source
    assert "constraints-release.txt" in source
    assert "scripts\\verify_release_dependencies.py" in source
    assert "codex_check.ps1 -Area full" in source
    assert "matrix.shard" not in source
    assert "-Shard" not in source
    assert 'PYTEST_ADDOPTS: \'-m "not visual and not real_game and not timing"\'' in source
    assert "Build and startup-smoke onedir package" in source
    assert "Build and startup-smoke onefile package" in source
    assert "-Area mesh " not in source
    assert "CDMW_GAME_ROOT" not in source


def test_windows_workflow_runs_only_for_code_events_or_manual_dispatch() -> None:
    """Unchanged main must not rerun the full suite and notify every night."""

    source = WORKFLOW.read_text(encoding="utf-8")
    triggers = source.split("\non:\n", 1)[1].split("\npermissions:", 1)[0]

    assert set(re.findall(r"^  ([a-z_]+):", triggers, flags=re.MULTILINE)) == {
        "push", "pull_request", "workflow_dispatch",
    }
    assert "    branches:\n      - main" in triggers
    assert '    tags:\n      - "v*"' in triggers


def test_windows_workflow_keeps_ordinary_main_pushes_fast() -> None:
    """A normal push must not spend an hour rerunning release-grade QA."""

    source = WORKFLOW.read_text(encoding="utf-8")
    fast_start = source.index("- name: Run fast main-push validation")
    canonical_start = source.index("- name: Run canonical nonvisual QA")
    package_start = source.index("  package:", canonical_start)
    fast_step = source[fast_start:canonical_start]
    canonical_step = source[canonical_start:package_start]

    assert "if: github.event_name == 'push' && !startsWith(github.ref, 'refs/tags/')" in fast_step
    assert "codex_check.ps1 -Area smoke" in fast_step
    assert "codex_check.ps1 -Area mesh-contract" in fast_step
    assert "codex_check.ps1 -Area mesh-unit" not in fast_step
    assert "codex_check.ps1 -Area full" not in fast_step
    assert (
        "if: github.event_name != 'push' || startsWith(github.ref, 'refs/tags/')"
        in canonical_step
    )
    assert "codex_check.ps1 -Area full" in canonical_step
    assert "codex_check.ps1 -Area smoke" not in canonical_step
    assert "codex_check.ps1 -Area mesh-contract" not in canonical_step
    assert "$nativeAccessViolation" not in canonical_step
    assert "for ($attempt = 1; $attempt -le 3; $attempt++)" not in canonical_step
    assert "retrying the same full one-process suite" not in canonical_step
    assert "dotnet_mesh_editor_experiment" not in source
    assert "cdmw-mesh-dotnet-editor" not in source
    assert "D3D11MaterialShaders.hlsl" not in source


def test_codex_check_keeps_smoke_build_free_and_splits_mesh_contracts() -> None:
    source = (ROOT / "scripts" / "codex_check.ps1").read_text(encoding="utf-8")
    smoke_start = source.index("    smoke = @(")
    smoke_end = source.index("    )", smoke_start)
    contract_start = source.index('    "mesh-contract" = @(')
    contract_end = source.index("    )", contract_start)
    native_start = source.index('    "mesh-native" = @(')
    native_end = source.index("    )", native_start)

    smoke = source[smoke_start:smoke_end]
    contract = source[contract_start:contract_end]
    native = source[native_start:native_end]
    assert "test_rust_preview_production_cutover.py" not in smoke
    assert "test_mesh_rust_archive_texture_launch.py" in contract
    assert "test_mesh_rust_embedding.py" in contract
    assert "test_rust_mesh_editor_control_contract.py" in contract
    assert "test_rust_preview_production_cutover.py" in contract
    assert "test_native_mesh_interaction_abi.py" in native
    assert "test_mesh_native_operation_coverage.py" in native
    assert "test_dotnet_resident_mutation_batch_contract.py" not in source
    assert "test_dotnet_mesh_editor_control_contract.py" not in source
    assert "test_dotnet_native_mesh_interaction_abi.py" not in source
    assert "$NeedsDotNetHelper" not in source
    assert '$Area -in @("smoke", "mesh-unit")' not in source


def test_windows_workflow_uses_only_approved_action_commit_shas() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    approved = {
        "actions/cache": "0057852bfaa89a56745cba8c7296529d2fc39830",
        "actions/checkout": "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09",
        "actions/download-artifact": "37930b1c2abaa49bbe596cd826c3c89aef350131",
        "actions/setup-dotnet": "26b0ec14cb23fa6904739307f278c14f94c95bf1",
        "actions/setup-python": "ece7cb06caefa5fff74198d8649806c4678c61a1",
        "actions/upload-artifact": "b7c566a772e6b6bfb58ed0dc250532a479d7789f",
        "signpath/github-action-submit-signing-request": "c92b958760219087e01f8d67a1669ed57afe2627",
    }
    references = re.findall(r"^\s*uses:\s+([^@\s]+)@([^#\s]+)", source, flags=re.MULTILINE)

    assert references
    for action, revision in references:
        assert action in approved
        assert revision == approved[action]


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="PowerShell behavior test")
def test_packaged_startup_result_readback_requires_post_construction(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    builder = tmp_path / "builder.json"
    invalid = tmp_path / "invalid.json"
    # A packaged run also reports how each helper shipping inside the package
    # resolved, and the verifier rejects a result without it. These fixtures
    # carry the same shape a real run writes so this test keeps proving the
    # stage/target/pid readback rather than tripping over that newer section.
    resolved_helpers = [
        {"key": "openimageio", "status": "available", "source": "bundled_lookup", "path": "oiio"},
        {"key": "cdmw_mesh_core", "status": "available", "source": "bundled_lookup", "path": "mesh"},
    ]
    rust_editor = {
        "schema": "cdmw_packaged_rust_mesh_editor_v1",
        "status": "available",
        "reason": "",
        "source": "frozen",
        "frozen": True,
        "path": "C:/Temp/payload/native/rust_mesh_editor/cdmw_mesh_lab.exe",
        "relative_path": "native/rust_mesh_editor/cdmw_mesh_lab.exe",
        "inside_bundle_root": True,
        "executable_sha256": "a" * 64,
        "provenance_path": "C:/Temp/payload/native/rust_mesh_editor/cdmw_mesh_lab.manifest.json",
        "provenance_relative_path": "native/rust_mesh_editor/cdmw_mesh_lab.manifest.json",
        "provenance_inside_bundle_root": True,
        "provenance_sha256": "b" * 64,
        "provenance": {
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
            "executable": "cdmw_mesh_lab.exe",
            "control_contract": "cdmw_mesh_lab.control-contract.json",
            "control_contract_schema": "cdmw_rust_mesh_editor_control_contract_v2",
            "capabilities": ["embedded_child_window_v1", "rust_preview_runtime_v1"],
            "preview_capabilities": [
                "resident_preview_package_replace_v2",
                "static_replacement_mesh_input_v1",
            ],
            "source_revision": "c" * 40,
            "source_tree_sha256": "d" * 64,
            "cargo_lock_sha256": "e" * 64,
            "executable_sha256": "a" * 64,
            "control_contract_sha256": "f" * 64,
            "cargo_version": "cargo 1.88.0",
            "rustc_version": "rustc 1.88.0",
        },
    }
    valid.write_text(
        json.dumps(
            {
                "ok": True,
                "pid": 42,
                "stage": "post_construction",
                "target": "default",
                "bundled_helpers": resolved_helpers,
                "rust_mesh_editor": rust_editor,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    builder.write_text(
        json.dumps(
            {
                "ok": True,
                "pid": 43,
                "stage": "post_construction",
                "target": "mesh_builder",
                "bundled_helpers": resolved_helpers,
                "rust_mesh_editor": rust_editor,
            }
        )
        + "\n",
        encoding="utf-8",
    )
    # Left without the section on purpose: the stage check runs first, so this
    # still has to fail for being pre-construction rather than for its helpers.
    invalid.write_text('{"ok":true,"pid":42,"stage":"pre_window","target":"default"}\n', encoding="utf-8")
    command = f"""
. '{str(STARTUP_VERIFIER).replace("'", "''")}' -ExecutablePath ignored
$payload = Assert-PackagedStartupResult -ResultPath '{str(valid).replace("'", "''")}'
if ($payload.stage -ne 'post_construction') {{ exit 10 }}
$builderPayload = Assert-PackagedStartupResult `
    -ResultPath '{str(builder).replace("'", "''")}' `
    -ExpectedTarget mesh_builder
if ($builderPayload.target -ne 'mesh_builder') {{ exit 13 }}
try {{
    Assert-PackagedStartupResult -ResultPath '{str(invalid).replace("'", "''")}' | Out-Null
    exit 11
}} catch {{
    if (-not $_.Exception.Message.Contains('post-construction')) {{ exit 12 }}
}}
exit 0
"""

    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
