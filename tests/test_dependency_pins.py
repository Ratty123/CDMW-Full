from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from scripts.verify_release_dependencies import read_exact_constraints, read_hashed_release_lock


DIRECTXTEX_COMMIT = "bf256afaed1c789ddd444fb45105ffbcab283efe"
VGMSTREAM_BUILD_COMMIT = "21bfb6f0a513271f2e18a51322128756bb59f365"
VGMSTREAM_SHA256 = "110f9087e60057c4af6cff84e26c214159c224792421affdddd3aaa2091f2641"


@pytest.mark.parametrize(
    ("package", "minimum"),
    (("pillow", "13.0.0"), ("brotli", "1.2.1"), ("setuptools", "84.1.0")),
)
def test_release_dependencies_exclude_october_2026_vulnerable_versions(package: str, minimum: str) -> None:
    # Pillow's October advisory batch, GHSA-9v8h-qqgm-4m35 (Brotli),
    # and GHSA-xmj3-9gf7-h52w (setuptools) require these security floors.
    constraints = read_exact_constraints(Path("constraints-release.txt"))
    locked = read_hashed_release_lock(Path("requirements-build.txt"))
    assert Version(constraints[package][1]) >= Version(minimum)
    assert Version(locked[package][1]) >= Version(minimum)


def test_runtime_pillow_requirement_excludes_the_last_vulnerable_release() -> None:
    requirements = (
        Requirement(line)
        for line in Path("requirements.txt").read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    )
    pillow = next(requirement for requirement in requirements if requirement.name.lower() == "pillow")
    assert "12.3.0" not in pillow.specifier
    assert "13.0.0" in pillow.specifier


def test_directxtex_fetches_are_pinned_to_the_same_commit() -> None:
    for path in (Path("native/cd_texture_dx/CMakeLists.txt"),):
        source = path.read_text(encoding="utf-8")
        assert f'set(CDMW_DIRECTXTEX_COMMIT "{DIRECTXTEX_COMMIT}"' in source
        assert "GIT_TAG ${CDMW_DIRECTXTEX_COMMIT}" in source
        assert "GIT_TAG main" not in source


def test_vgmstream_packaging_uses_immutable_version_commit_and_sha256() -> None:
    source = Path("build_pyside6_app.ps1").read_text(encoding="utf-8")

    assert '$vgmstreamVersion = "r1980"' in source
    assert f'$vgmstreamBuildCommit = "{VGMSTREAM_BUILD_COMMIT}"' in source
    assert f'$vgmstreamArchiveSha256 = "{VGMSTREAM_SHA256}"' in source
    assert "raw/master" not in source
    assert "vgmstream-latest" not in source
    assert "function Get-Sha256Hex" in source
    assert "Get-Sha256Hex -LiteralPath $zipPath" in source
    assert re.search(r"if \(\$downloadHash -ne \$vgmstreamArchiveSha256\)", source)
    assert "function Test-VgmstreamRuntimePin" in source
    assert 'Join-Path $RuntimeDir ".cdmw-dependency.json"' in source
    assert "Get-Sha256Hex -LiteralPath $runtimeFile" in source
