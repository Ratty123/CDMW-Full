from pathlib import Path
import re

import pytest


ROOT = Path(__file__).resolve().parents[1]

# Every native component whose sources are declared twice: once for CMake, which
# is what the desktop build and CI use, and once for Bazel. Nothing derives one
# list from the other, so they can only be kept together by checking them.
DUAL_DECLARED_NATIVE_COMPONENTS = (
    "cd_texture_dx",
    "cdmw_archive_accelerator",
    "cdmw_full_archive_core",
    "cdmw_mesh_core",
    "cdmw_preview_core",
)

# Components compiled as a single unity translation unit. There the declaration
# order is part of the contract and not just presentation: the owner sources are
# concatenated in list order and rely on file-static helpers defined by an
# earlier source in the same unit, so a reordering that keeps the same set can
# still fail to compile.
UNITY_NATIVE_COMPONENTS = frozenset({"cdmw_mesh_core", "cdmw_preview_core"})

_SOURCE_PATTERN = re.compile(r"(?:src|source)/[A-Za-z0-9_/.]+\.(?:cpp|cc|c)")


def _declared_sources(path: Path) -> list[str]:
    return _SOURCE_PATTERN.findall(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("component", DUAL_DECLARED_NATIVE_COMPONENTS)
def test_native_component_source_lists_agree_across_cmake_and_bazel(component: str) -> None:
    root = ROOT / "native" / component
    cmake_path = root / "CMakeLists.txt"
    bazel_path = root / "BUILD.bazel"
    assert cmake_path.is_file(), f"{component} lost its CMakeLists.txt"
    assert bazel_path.is_file(), f"{component} lost its BUILD.bazel"

    cmake_sources = _declared_sources(cmake_path)
    bazel_sources = _declared_sources(bazel_path)
    assert cmake_sources, f"{component} declares no sources to CMake"

    missing_from_bazel = sorted(set(cmake_sources) - set(bazel_sources))
    missing_from_cmake = sorted(set(bazel_sources) - set(cmake_sources))
    assert not missing_from_bazel, (
        f"{component}: sources built by CMake but not by Bazel: {missing_from_bazel}. "
        f"Add them to native/{component}/BUILD.bazel."
    )
    assert not missing_from_cmake, (
        f"{component}: sources built by Bazel but not by CMake: {missing_from_cmake}. "
        f"Add them to native/{component}/CMakeLists.txt."
    )

    if component in UNITY_NATIVE_COMPONENTS:
        assert cmake_sources == bazel_sources, (
            f"{component} is a unity build, so the two lists must also agree on order. "
            f"CMake: {cmake_sources}. Bazel: {bazel_sources}."
        )


def test_mesh_core_packaging_uses_profile_native_configuration() -> None:
    spec_source = (ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")

    assert 'NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"' in spec_source
    assert (
        '_add_native_binary(f"native/cdmw_mesh_core/build/{NATIVE_CONFIGURATION}/cdmw-mesh-core.exe", '
        '"native", required_release=True)'
    ) in spec_source
