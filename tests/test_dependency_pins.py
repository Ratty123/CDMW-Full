from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.version import Version

from scripts.verify_release_dependencies import (
    read_exact_constraints,
    read_hashed_release_lock,
    release_dependency_pin_gaps,
)


DIRECTXTEX_COMMIT = "bf256afaed1c789ddd444fb45105ffbcab283efe"
VGMSTREAM_BUILD_COMMIT = "21bfb6f0a513271f2e18a51322128756bb59f365"
VGMSTREAM_SHA256 = "110f9087e60057c4af6cff84e26c214159c224792421affdddd3aaa2091f2641"


QT_SDK_LOCK = Path("requirements-qt-sdk.txt")
# py7zr and everything it pulls in on Windows CPython. Only scripts/vendor_qt_sdk.py uses them.
QT_SDK_ONLY = frozenset(
    {
        "backports-zstd",
        "brotli",
        "inflate64",
        "multivolumefile",
        "psutil",
        "py7zr",
        "pybcj",
        "pycryptodomex",
        "pyppmd",
        "texttable",
    }
)
QT_SDK_ONLY_MODULES = frozenset(
    {"py7zr", "Cryptodome", "brotli", "psutil", "pyppmd", "bcj", "multivolumefile", "inflate64", "texttable", "backports"}
)
SHIPPED_SOURCE = (Path("cdmw_app.py"), Path("cdmw"), Path("tools/placement_studio"), Path("tools/translation_studio"))


@pytest.mark.parametrize(
    ("package", "minimum"),
    (("pillow", "13.0.0"), ("setuptools", "84.1.0")),
)
def test_release_dependencies_exclude_october_2026_vulnerable_versions(package: str, minimum: str) -> None:
    # Pillow's October advisory batch and GHSA-xmj3-9gf7-h52w (setuptools)
    # require these security floors.
    constraints = read_exact_constraints(Path("constraints-release.txt"))
    locked = read_hashed_release_lock(Path("requirements-build.txt"))
    assert Version(constraints[package][1]) >= Version(minimum)
    assert Version(locked[package][1]) >= Version(minimum)


def test_qt_sdk_lock_keeps_the_brotli_security_floor() -> None:
    # GHSA-9v8h-qqgm-4m35 (Brotli); brotli now comes only with py7zr.
    locked = read_hashed_release_lock(QT_SDK_LOCK)
    assert Version(locked["brotli"][1]) >= Version("1.2.1")


def test_py7zr_chain_is_build_only_and_hash_locked() -> None:
    constraints = read_exact_constraints(Path("constraints-release.txt"))
    release_lock = read_hashed_release_lock(Path("requirements-build.txt"))
    assert not QT_SDK_ONLY & set(constraints)
    assert not QT_SDK_ONLY & set(release_lock)

    source = QT_SDK_LOCK.read_text(encoding="utf-8")
    assert "--require-hashes" in source
    assert "--only-binary :all:" in source
    assert 'backports.zstd==1.7.0 ; python_version < "3.14"' in source
    names = set()
    for line in source.splitlines():
        line = line.split("#", 1)[0].strip()
        if line and not line.startswith("--"):
            names.add(re.sub(r"[-_.]+", "-", re.split(r"[=; ]", line, maxsplit=1)[0]).lower())
    assert names == QT_SDK_ONLY
    # Every active dependency of py7zr on this interpreter is pinned beside it.
    qt_sdk = read_hashed_release_lock(QT_SDK_LOCK)
    pins = {key: (name, version) for key, (name, version, _hashes) in qt_sdk.items()}
    assert release_dependency_pin_gaps(pins) == ()
    assert "requirements-qt-sdk.txt" in Path("scripts/vendor_qt_sdk.py").read_text(encoding="utf-8")


def test_shipped_source_never_imports_the_py7zr_chain() -> None:
    import ast

    offenders = []
    for root in SHIPPED_SOURCE:
        files = [root] if root.suffix == ".py" else sorted(root.rglob("*.py"))
        for path in files:
            tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    modules = [alias.name for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                    modules = [node.module]
                else:
                    continue
                for module in modules:
                    if module.split(".", 1)[0] in QT_SDK_ONLY_MODULES:
                        offenders.append(f"{path}:{node.lineno}: {module}")
    assert offenders == []


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
