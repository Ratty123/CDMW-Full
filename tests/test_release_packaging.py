from __future__ import annotations

import shutil
import subprocess
import sys
from importlib import metadata
from pathlib import Path

import pytest

from scripts.verify_release_dependencies import (
    SUPPORTED_PYTHON_RELEASES,
    read_exact_constraints,
    release_dependency_mismatches,
    verify_release_environment,
)


ROOT = Path(__file__).resolve().parents[1]
CONSTRAINTS = ROOT / "constraints-release.txt"
BUILDER = ROOT / "build_pyside6_app.ps1"
SPEC = ROOT / "CrimsonDesertModWorkbench.spec"
STARTUP_VERIFIER = ROOT / "scripts" / "verify_packaged_startup.ps1"
ARCHIVE_BACKEND_RELEASE_HELPER = ROOT / "scripts" / "full_archive_backend_release.ps1"
WORKFLOW = ROOT / ".github" / "workflows" / "windows-build.yml"
POWERSHELL = shutil.which("powershell.exe")


def test_release_constraints_are_exact_complete_and_installed() -> None:
    pins = read_exact_constraints(CONSTRAINTS)

    assert SUPPORTED_PYTHON_RELEASES == ((3, 11), (3, 14))
    assert {
        "cryptography",
        "lz4",
        "numpy",
        "opencv-python-headless",
        "pillow",
        "pyinstaller",
        "pyside6",
        "pyside6-addons",
        "pyside6-essentials",
        "shiboken6",
    }.issubset(pins)
    assert verify_release_environment(CONSTRAINTS) == ()


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
    assert "--self-contained true" in source
    assert "--self-contained false" not in source
    assert "-p:PublishSingleFile=true" in source
    assert "-p:PublishTrimmed=false" in source
    assert "scripts\\verify_release_dependencies.py" in source
    assert "scripts\\generate_window_feature_provider_members.py" in source
    assert "constraints-release.txt" in source
    assert "scripts\\verify_packaged_startup.ps1" in source
    assert 'Invoke-DotNetMeshEditorGpuSmoke -ExecutablePath $exePath -Context "published"' in source
    assert 'Invoke-DotNetMeshEditorProvenanceCheck -ExecutablePath $exePath -Context "published"' in source
    assert "function Test-OnedirTextureBackend" in source
    assert "function Test-OnefileTextureBackend" in source
    assert 'Invoke-TextureBackendSelfTest -ExecutablePath $helperPath -Context "packaged onedir"' in source
    assert "CArchiveReader" in source
    assert '[str(helper_path), "self-test"]' in source
    assert 'cdmw-mesh-dotnet-editor.manifest.json' in source
    assert 'executable_sha256 = $exeHash' in source
    assert 'shader_sha256 = $shaderHash' in source
    assert 'Start-Process -FilePath $ExecutablePath' in source
    packaged_smoke = 'Invoke-DotNetMeshEditorGpuSmoke -ExecutablePath $packagedDotNetHelper -Context "packaged onedir"'
    assert packaged_smoke in source
    assert 'Invoke-DotNetMeshEditorProvenanceCheck -ExecutablePath $packagedDotNetHelper -Context "packaged onedir"' in source
    assert '$Mode -eq "onedir"' in source
    describe_only_return = 'if ($DescribeOnly) {\n    return\n}'
    metadata_refresh = 'Stage "Refreshing generated feature metadata"'
    metadata_check = 'Stage "Verifying generated feature metadata"'
    assert "& $pythonExe $providerMetadataGenerator\n" in source
    assert "& $pythonExe $providerMetadataGenerator --check" in source
    assert source.index(describe_only_return) < source.index(metadata_refresh)
    assert source.index(metadata_refresh) < source.index(metadata_check)
    assert source.index(metadata_check) < source.index("Starting PyInstaller")
    texture_backend_stage = 'Stage "Verifying packaged native texture backend"'
    assert source.index(texture_backend_stage) < source.index(packaged_smoke)
    assert source.index(texture_backend_stage) < source.index('Stage "Verifying packaged startup"')
    assert source.index(packaged_smoke) < source.index('Stage "Verifying packaged startup"')
    assert source.index("Verifying packaged startup") < source.index("Publishing build output")
    assert source.index("generate_window_feature_provider_members.py") < source.index("Starting PyInstaller")
    assert 'NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"' in spec_source
    assert 'native/cdmw_mesh_dotnet_editor/build/{NATIVE_CONFIGURATION}/D3D11MaterialShaders.hlsl' in spec_source
    assert 'native/cdmw_full_archive_backend/build/{NATIVE_CONFIGURATION}' in spec_source
    assert '"archive_backend"' in spec_source
    assert 'scripts\\full_archive_backend_release.ps1' in source
    assert "function Invoke-FullArchiveBackendBuild" in archive_backend_source
    assert "function Test-OnedirFullArchiveBackend" in archive_backend_source
    assert "function Test-OnefileFullArchiveBackend" in archive_backend_source
    archive_backend_stage = 'Stage "Verifying packaged full archive backend"'
    assert archive_backend_stage in source
    assert source.index(archive_backend_stage) < source.index('Stage "Verifying packaged startup"')


def test_onedir_publish_removes_runtime_artifacts_created_by_startup_smoke() -> None:
    source = BUILDER.read_text(encoding="utf-8")

    assert 'foreach ($artifactName in @("workspace", "CrimsonDesertModWorkbench.cfg"))' in source
    cleanup_call = "Remove-PackagedOnedirRuntimeArtifacts -OnedirPath $builtDir"
    publish_call = "Move-PathWithRetries -SourcePath $builtDir -DestinationPath $finalOutputPath"
    assert cleanup_call in source
    assert source.index(cleanup_call) < source.index(publish_call)


def test_release_spec_collects_all_app_submodules_for_lazy_facades() -> None:
    from PyInstaller.utils.hooks import collect_submodules
    from cdmw.ui.shell.window_feature_providers import (
        ARCHIVE_FEATURE_PROVIDERS,
        MESH_FEATURE_PROVIDERS,
        SHELL_FEATURE_PROVIDERS,
        TEXTURE_FEATURE_PROVIDERS,
    )

    providers = (
        *SHELL_FEATURE_PROVIDERS,
        *ARCHIVE_FEATURE_PROVIDERS,
        *TEXTURE_FEATURE_PROVIDERS,
        *MESH_FEATURE_PROVIDERS,
    )
    collected = set(collect_submodules("cdmw"))
    assert "cdmw.core.ncnn_model_catalog" in collected
    assert {provider.module_name for provider in providers} <= collected
    source = SPEC.read_text(encoding="utf-8")
    assert "from PyInstaller.utils.hooks import collect_all, collect_submodules" in source
    assert 'hiddenimports += collect_submodules("cdmw")' in source


def test_windows_workflow_gates_packaging_on_both_headless_python_releases() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert 'python-version: ["3.11", "3.14"]' in source
    assert "needs: qa" in source
    assert "constraints-release.txt" in source
    assert "scripts\\verify_release_dependencies.py" in source
    assert "codex_check.ps1 -Area full" in source
    assert 'PYTEST_ADDOPTS: \'-m "not visual and not real_game"\'' in source
    assert "Build and startup-smoke onedir package" in source
    assert "Build and startup-smoke onefile package" in source
    assert "-Area mesh " not in source
    assert "CDMW_GAME_ROOT" not in source


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="PowerShell behavior test")
def test_packaged_startup_result_readback_requires_post_construction(tmp_path: Path) -> None:
    valid = tmp_path / "valid.json"
    invalid = tmp_path / "invalid.json"
    valid.write_text('{"ok":true,"pid":42,"stage":"post_construction","target":"default"}\n', encoding="utf-8")
    invalid.write_text('{"ok":true,"pid":42,"stage":"pre_window","target":"default"}\n', encoding="utf-8")
    command = f"""
. '{str(STARTUP_VERIFIER).replace("'", "''")}' -ExecutablePath ignored
$payload = Assert-PackagedStartupResult -ResultPath '{str(valid).replace("'", "''")}'
if ($payload.stage -ne 'post_construction') {{ exit 10 }}
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
