from __future__ import annotations

import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
QA_RUNNER = ROOT / "run_full_qa.ps1"
CODEX_CHECK = ROOT / "scripts" / "codex_check.ps1"
PACKAGE_BUILDER = ROOT / "build_pyside6_app.ps1"
POWERSHELL = shutil.which("powershell.exe")


def test_full_qa_uses_canonical_bounded_temp_owned_gates() -> None:
    source = QA_RUNNER.read_text(encoding="utf-8")
    codex_source = CODEX_CHECK.read_text(encoding="utf-8")
    package_source = PACKAGE_BUILDER.read_text(encoding="utf-8")

    assert "unittest discover" not in source
    assert '"-Area", "full", "-PytestBaseTemp", $qaPytest' in source
    assert "[System.IO.Path]::GetTempPath()" in source
    assert '"PYTHONPYCACHEPREFIX" = (Join-Path $qaRoot "pycache")' in source
    assert '"CARGO_TARGET_DIR" = (Join-Path $qaRoot "cargo-target")' in source
    assert '"CDMW_PYINSTALLER_MODE" = "onedir"' in source
    assert '"CDMW_PYINSTALLER_PROFILE" = "release"' in source
    assert "WaitForExit($TimeoutSeconds * 1000)" in source
    assert "timed out after $TimeoutSeconds second(s)" in source
    assert "Remove-QAOwnedPath $qaRoot $qaRoot" in source
    assert 'Remove-QAPath "crash_reports"' not in source
    assert "CDMW_GUI_STARTUP_SMOKE_RESULT" in source
    assert '"post_construction"' in source
    assert '"-BuildProfile", "release", "-NativeHelpersOnly"' in source
    assert '"_internal\\native\\cdmw-mesh-dotnet-editor.exe"' in source
    assert '"-DotNetGpuSmokeExecutable", $packagedDotNetHelper' in source
    assert ') $scriptDir $BuildTimeoutSeconds' in source
    assert "function Invoke-NativeHelperPreparation" in package_source
    assert "Invoke-DotNetMeshEditorBuild -Configuration $Configuration -Required:$RequireDotNet" in package_source
    assert 'backend -ne "d3d11_vortice_shader"' in package_source
    assert '$smoke.gates.native_windows_remained_hidden -ne $true' in package_source
    assert "[string]$PytestBaseTemp" in codex_source
    assert '"--basetemp=$PytestBaseTemp"' in codex_source
    assert '"cdmw", "tests", "tools"' in source
    assert "Skipping missing test" not in codex_source
    assert "Configured tests are missing for area" in codex_source


def test_codex_check_configured_test_paths_exist() -> None:
    source = CODEX_CHECK.read_text(encoding="utf-8")
    configured = sorted(set(re.findall(r'"(tests/test_[^"]+\.py)"', source)))
    missing = [path for path in configured if not (ROOT / path).is_file()]

    assert configured
    assert not missing, f"Missing codex_check test paths: {missing}"


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="PowerShell behavior test")
def test_native_helper_only_describe_keeps_packaging_out_of_the_gate() -> None:
    result = subprocess.run(
        [
            POWERSHELL,
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(PACKAGE_BUILDER),
            "-BuildProfile",
            "release",
            "-NativeHelpersOnly",
            "-DescribeOnly",
        ],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=20,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert "rebuild Release helpers" in result.stdout
    assert "hidden d3d11_vortice_shader smoke" in result.stdout
    assert "Starting PyInstaller" not in result.stdout


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="PowerShell behavior test")
def test_qa_step_reads_real_child_exit_codes(tmp_path: Path) -> None:
    command = f"""
. '{str(QA_RUNNER).replace("'", "''")}'
Invoke-QAStep -Name 'success probe' -FilePath '{str(POWERSHELL).replace("'", "''")}' `
    -ArgumentList @('-NoProfile', '-Command', 'exit 0') `
    -WorkingDirectory '{str(tmp_path).replace("'", "''")}' -TimeoutSeconds 10
try {{
    Invoke-QAStep -Name 'failure probe' -FilePath '{str(POWERSHELL).replace("'", "''")}' `
        -ArgumentList @('-NoProfile', '-Command', 'exit 7') `
        -WorkingDirectory '{str(tmp_path).replace("'", "''")}' -TimeoutSeconds 10
    exit 20
}} catch {{
    if (-not $_.Exception.Message.Contains('failed with exit code 7')) {{ exit 21 }}
}}
exit 0
"""

    stdout_path = tmp_path / "qa-step-stdout.log"
    stderr_path = tmp_path / "qa-step-stderr.log"
    with stdout_path.open("w", encoding="utf-8") as stdout, stderr_path.open("w", encoding="utf-8") as stderr:
        result = subprocess.run(
            [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
            cwd=ROOT,
            text=True,
            stdout=stdout,
            stderr=stderr,
            timeout=60,
        )

    assert result.returncode == 0, (
        f"STDOUT:\n{stdout_path.read_text(encoding='utf-8')}\n"
        f"STDERR:\n{stderr_path.read_text(encoding='utf-8')}"
    )


@pytest.mark.skipif(sys.platform != "win32" or POWERSHELL is None, reason="PowerShell behavior test")
def test_qa_timeout_and_cleanup_are_enforced() -> None:
    # Not `tmp_path`. `Remove-QAOwnedPath` refuses twice, and the first refusal is
    # that the owned root is not under the *system* temp directory. CI runs pytest
    # with `--basetemp=$RUNNER_TEMP/...`, which on a GitHub runner is `D:\a\_temp`
    # and not under `%TEMP%`, so a `tmp_path` root tripped the outer guard and the
    # test read the wrong refusal -- exit 11 rather than the QA-ownership message
    # it means to exercise. Building the roots under the real system temp puts the
    # outer guard's precondition back where the test assumes it.
    with tempfile.TemporaryDirectory(prefix="cdmw-qa-runner-") as system_temp_dir:
        _assert_qa_timeout_and_cleanup_are_enforced(Path(system_temp_dir))


def _assert_qa_timeout_and_cleanup_are_enforced(tmp_path: Path) -> None:
    qa_root = tmp_path / "cdmw-full-qa-owned"
    qa_root.mkdir()
    outside = tmp_path / "crash_reports"
    outside.mkdir()
    sentinel = outside / "user-report.log"
    sentinel.write_text("keep", encoding="utf-8")
    command = f"""
. '{str(QA_RUNNER).replace("'", "''")}'
$qaRoot = '{str(qa_root).replace("'", "''")}'
$outside = '{str(outside).replace("'", "''")}'
try {{
    Remove-QAOwnedPath -Path $outside -OwnedRoot $qaRoot
    exit 10
}} catch {{
    if (-not $_.Exception.Message.Contains('outside the QA-owned temp directory')) {{ exit 11 }}
}}
if (-not (Test-Path -LiteralPath (Join-Path $outside 'user-report.log'))) {{ exit 12 }}
try {{
    Invoke-QAStep -Name 'timeout probe' -FilePath '{str(POWERSHELL).replace("'", "''")}' `
        -ArgumentList @('-NoProfile', '-Command', 'Start-Sleep -Seconds 5') `
        -WorkingDirectory $qaRoot -TimeoutSeconds 1
    exit 13
}} catch {{
    if (-not $_.Exception.Message.Contains('timed out after 1 second(s)')) {{ exit 14 }}
}}
Remove-QAOwnedPath -Path $qaRoot -OwnedRoot $qaRoot
if (Test-Path -LiteralPath $qaRoot) {{ exit 15 }}
exit 0
"""

    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
    )

    assert result.returncode == 0, f"STDOUT:\n{result.stdout}\nSTDERR:\n{result.stderr}"
    assert sentinel.read_text(encoding="utf-8") == "keep"
