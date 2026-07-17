from __future__ import annotations

from pathlib import Path

from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT
from tests.native_source_text import d3d11_preview_source
from tests.test_architecture_size_ratchets import _brace_function_spans


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "native" / "cdmw_d3d11_preview" / "src"
OWNER_ROOT = SOURCE_ROOT / "owners"


def test_d3d11_preview_has_thin_entry_point_and_real_owner_sources() -> None:
    main = SOURCE_ROOT / "main.cpp"
    owners = tuple(sorted(OWNER_ROOT.glob("*.cpp")))
    cmake = (SOURCE_ROOT.parent / "CMakeLists.txt").read_text(encoding="utf-8")

    assert len(main.read_text(encoding="utf-8").splitlines()) <= 20
    assert owners
    assert "HEADER_FILE_ONLY" not in cmake
    assert "UNITY_BUILD ON" in cmake
    assert "UNITY_BUILD_MODE GROUP" in cmake
    assert "d3d_preview_unity.cpp" not in cmake
    for owner in owners:
        source = owner.read_text(encoding="utf-8")
        assert f"src/owners/{owner.name}" in cmake
        assert len(source.splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT
        assert '#include "owners/' not in source


def test_d3d11_preview_owner_files_and_functions_are_bounded() -> None:
    oversized_files: dict[str, int] = {}
    oversized_functions: dict[str, int] = {}
    paths = [*sorted(SOURCE_ROOT.glob("*.hpp")), *sorted(OWNER_ROOT.glob("*.cpp"))]
    for path in paths:
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        if line_count > DEFAULT_OWNER_FILE_LINE_LIMIT:
            oversized_files[path.relative_to(ROOT).as_posix()] = line_count
        for key, span in _brace_function_spans(path).items():
            if span > 150:
                oversized_functions[key] = span
    assert not oversized_files
    assert not oversized_functions


def test_d3d11_preview_source_aggregation_preserves_owner_protocol_text() -> None:
    source = d3d11_preview_source()
    assert 'if (command == "update_mesh_edit_vertices")' in source
    assert 'if (command == "set_source_part_picking")' in source
    assert "mesh_edit_revision_ack_v1" in source
    assert "D3D11CreateDeviceAndSwapChain" in source
