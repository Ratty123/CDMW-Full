from __future__ import annotations

from pathlib import Path
import re

from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT
from tests.native_source_text import preview_core_source
from tests.test_architecture_size_ratchets import _brace_function_spans


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "native" / "cdmw_preview_core" / "src"
OWNER_ROOT = SOURCE_ROOT / "owners"


def test_native_preview_core_has_thin_entry_point_and_real_owner_sources() -> None:
    main = SOURCE_ROOT / "main.cpp"
    owners = tuple(sorted(OWNER_ROOT.glob("*.cpp")))
    cmake = (SOURCE_ROOT.parent / "CMakeLists.txt").read_text(encoding="utf-8")

    assert main.read_text(encoding="utf-8").splitlines() == [
        '#include "preview_core.hpp"',
        "",
        "int main(int argc, char** argv) {",
        "    return cdmw_preview_core::run_cli(argc, argv);",
        "}",
    ]
    assert owners
    assert "set(PREVIEW_CORE_OWNER_SOURCES" in cmake
    assert "UNITY_BUILD ON" in cmake
    assert "UNITY_BUILD_MODE GROUP" in cmake
    assert "preview_core_owners" in cmake
    assert "HEADER_FILE_ONLY" not in cmake
    for owner in owners:
        text = owner.read_text(encoding="utf-8-sig")
        assert f"src/owners/{owner.name}" in cmake
        assert len(text.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT
        assert re.search(r'#include\s+["<][^">]+\.cpp[">]', text) is None


def test_native_preview_core_owner_functions_are_bounded() -> None:
    oversized = {
        key: span
        for owner in sorted(OWNER_ROOT.glob("*.cpp"))
        for key, span in _brace_function_spans(owner).items()
        if span > 150
    }
    assert not oversized


def test_native_preview_core_preserves_public_command_surface_in_owners() -> None:
    source = preview_core_source()

    for command in (
        "self-test",
        "--service",
        "preview-job",
        "mesh-audit-job",
        "mesh-parse-job",
        "mesh-rebuild-job",
        "name-index-job",
    ):
        assert f'std::string(argv[1]) == "{command}"' in source
    assert "int run_cli(int argc, char** argv)" in source
    assert '\\"python_fallback_allowed\\":false' in source
    assert '\\"package_builder\\":\\"cdmw_preview_core_cpp' in source
