"""A release must not carry a path from the machine that built it.

Rust panic locations named the cargo registry under the user profile, every .NET assembly
named its obj folder, and an MSVC assert named the build folder: every release built on the
owner's PC published the Windows user name and folder layout. The build now maps those roots
away (`Set-PathNeutralBuildEnvironment`) and `scripts/check_package_privacy.py` refuses a
package that still has one.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.check_package_privacy import (
    machine_needles,
    main,
    scan_bytes,
    scan_package,
)

ROOT = Path(__file__).resolve().parents[1]
BUILDER = ROOT / "build_pyside6_app.ps1"
ARCHIVE_BACKEND_RELEASE_HELPER = ROOT / "scripts" / "full_archive_backend_release.ps1"
POWERSHELL = shutil.which("powershell.exe")


@pytest.fixture
def machine(monkeypatch, tmp_path):
    profile = tmp_path / "Users" / "Builder"
    monkeypatch.setenv("USERPROFILE", str(profile))
    monkeypatch.setenv("USERNAME", "Builder")
    for name in ("CARGO_HOME", "RUSTUP_HOME", "TEMP", "TMP", "LOCALAPPDATA", "APPDATA", "VCPKG_ROOT"):
        monkeypatch.delenv(name, raising=False)
    return profile


def test_every_spelling_of_a_local_path_is_found(machine) -> None:
    needles = machine_needles([r"E:\Work\CDMW Full"])
    samples = {
        "utf-8": rb"panic at E:\Work\CDMW Full\native\lib.rs:10",
        "forward slashes": b"source E:/Work/CDMW Full/tools/x.cpp",
        "JSON": rb'{"path": "E:\\Work\\CDMW Full\\build"}',
        "UTF-16": "pdb E:\\Work\\CDMW Full\\obj\\x.pdb".encode("utf-16-le"),
        "other case": rb"e:\work\cdmw full\x",
        "profile": f"{machine}\\.cargo\\registry\\src\\serde".encode(),
        "user segment on another drive": rb"D:\Users\Builder\AppData\x",
    }
    for label, data in samples.items():
        assert scan_bytes(label, data, needles), label


def test_a_bare_publisher_name_is_not_a_local_path(machine) -> None:
    needles = machine_needles()
    assert not scan_bytes("constants", b'APP_ORGANIZATION = "Builder"', needles)
    assert not scan_bytes("about", "Builder".encode("utf-16-le"), needles)


def test_a_onedir_package_is_scanned_file_by_file(machine, tmp_path, capsys) -> None:
    package = tmp_path / "CDMW"
    (package / "native").mkdir(parents=True)
    (package / "CDMW.exe").write_bytes(b"MZ clean")
    assert main([str(package), "--root", r"E:\Work\CDMW Full"]) == 0
    (package / "native" / "helper.dll").write_bytes(rb"RSDS E:\Work\CDMW Full\obj\Release\helper.pdb")
    hits = scan_package(package, machine_needles([r"E:\Work\CDMW Full"]))
    assert [hit.member for hit in hits] == ["native/helper.dll"]
    assert main([str(package), "--root", r"E:\Work\CDMW Full"]) == 1
    assert "native/helper.dll" in capsys.readouterr().out


def test_the_release_build_refuses_a_package_with_local_paths_before_publishing() -> None:
    source = BUILDER.read_text(encoding="utf-8")
    environment = source.index("\nSet-PathNeutralBuildEnvironment\n")
    natives = source.index("Invoke-NativeHelperPreparation `")
    gate = source.index("& $pythonExe @privacyArguments")
    publish = source.index('Write-BuildProgress -Percent 97 -Stage "Publishing build output"')
    release_block = source.rindex('if ($BuildProfile -eq "release") {', 0, gate)
    assert environment < natives < gate < publish
    assert release_block > source.index("Invoke-PyInstallerBuild -PythonExe")
    assert "throw \"The package contains paths from this machine" in source[gate:publish]
    publish_args = ARCHIVE_BACKEND_RELEASE_HELPER.read_text(encoding="utf-8")
    assert "-p:ContinuousIntegrationBuild=true" in publish_args


def _function(source: str, name: str) -> str:
    start = source.index(f"function {name} {{")
    depth, at = 0, source.index("{", start)
    for index in range(at, len(source)):
        depth += {"{": 1, "}": -1}.get(source[index], 0)
        if depth == 0:
            return source[start:index + 1]
    raise AssertionError(name)


@pytest.mark.skipif(POWERSHELL is None, reason="PowerShell is required")
def test_the_build_maps_every_local_root_for_rust_and_msvc(tmp_path) -> None:
    checkout = tmp_path / "CDMW Full"  # a space, as in the real checkout
    checkout.mkdir()
    source = BUILDER.read_text(encoding="utf-8")
    script = tmp_path / "probe.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n"
        f"$scriptDir = '{checkout}'\n"
        + _function(source, "Get-SourceCheckoutRoots") + "\n"
        + _function(source, "Set-PathNeutralBuildEnvironment") + "\n"
        "Set-PathNeutralBuildEnvironment | Out-Null\n"
        "Write-Output ('RUST=' + ($env:CARGO_ENCODED_RUSTFLAGS -replace [char]0x1f, '|'))\n"
        "Write-Output ('CL=' + $env:CL)\nWrite-Output ('LINK=' + $env:_LINK_)\n",
        encoding="utf-8-sig",
    )
    environment = {key: value for key, value in os.environ.items()
                   if key not in ("CARGO_ENCODED_RUSTFLAGS", "RUSTFLAGS", "CL", "_LINK_")}
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, env=environment, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    lines = dict(line.split("=", 1) for line in result.stdout.splitlines() if "=" in line)
    rust = lines["RUST"].split("|")
    profile = os.environ["USERPROFILE"].rstrip("\\")
    assert f"--remap-path-prefix={checkout}=/cdmw" in rust
    assert f"--remap-path-prefix={profile}=/user" in rust
    cargo = [flag for flag in rust if flag.endswith("=/cargo")]
    assert cargo and rust.index(cargo[0]) > rust.index(f"--remap-path-prefix={profile}=/user")
    # One quoted option per root; the doubled backslash is a literal one to cl.exe.
    assert f'"/d1trimfile:{checkout}\\\\"' in lines["CL"]
    assert re.search(r"/PDBALTPATH:%_PDB%", lines["LINK"])


@pytest.mark.skipif(POWERSHELL is None or shutil.which("git") is None,
                    reason="PowerShell and git are required")
def test_a_worktree_build_also_covers_its_main_checkout(tmp_path) -> None:
    main_checkout, worktree = tmp_path / "main repo", tmp_path / "wt"
    main_checkout.mkdir()
    git = ["git", "-c", "user.name=t", "-c", "user.email=t@example.invalid"]
    subprocess.run([*git, "init", "-q", str(main_checkout)], check=True)
    (main_checkout / "f.txt").write_text("x", encoding="utf-8")
    subprocess.run([*git, "-C", str(main_checkout), "add", "f.txt"], check=True)
    subprocess.run([*git, "-C", str(main_checkout), "commit", "-q", "-m", "x"], check=True)
    subprocess.run([*git, "-C", str(main_checkout), "worktree", "add", "-q", "--detach",
                    str(worktree)], check=True)
    source = BUILDER.read_text(encoding="utf-8")
    script = tmp_path / "roots.ps1"
    script.write_text(
        "$ErrorActionPreference = 'Stop'\nSet-StrictMode -Version Latest\n"
        f"$scriptDir = '{worktree}'\n" + _function(source, "Get-SourceCheckoutRoots") + "\n"
        "(Get-SourceCheckoutRoots) -join '|'\n",
        encoding="utf-8-sig",
    )
    result = subprocess.run(
        [POWERSHELL, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    roots = {Path(root).resolve() for root in result.stdout.strip().split("|")}
    assert roots == {worktree.resolve(), main_checkout.resolve()}
