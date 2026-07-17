from __future__ import annotations

from pathlib import Path

from tests.architecture_limits import DEFAULT_OWNER_FILE_LINE_LIMIT
from tests.test_architecture_size_ratchets import _brace_function_spans


ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOT = ROOT / "native" / "cdmw_mesh_core" / "src"
OWNER_ROOT = SOURCE_ROOT / "owners"


def test_native_mesh_core_has_thin_entry_point_and_real_owner_sources() -> None:
    main = SOURCE_ROOT / "main.cpp"
    owners = tuple(sorted(OWNER_ROOT.glob("*.cpp")))
    cmake = (SOURCE_ROOT.parent / "CMakeLists.txt").read_text(encoding="utf-8")

    assert len(main.read_text(encoding="utf-8").splitlines()) <= 50
    assert owners
    assert "HEADER_FILE_ONLY" not in cmake
    assert "UNITY_BUILD ON" in cmake
    assert "UNITY_BUILD_MODE GROUP" in cmake
    assert "mesh_core_unity.cpp" not in cmake
    for owner in owners:
        assert f"src/owners/{owner.name}" in cmake
        assert len(owner.read_text(encoding="utf-8").splitlines()) <= DEFAULT_OWNER_FILE_LINE_LIMIT
        assert '#include "owners/' not in owner.read_text(encoding="utf-8")


def test_native_mesh_core_owner_functions_are_bounded() -> None:
    oversized: dict[str, int] = {}
    false_positives: set[str] = set()
    for owner in sorted(OWNER_ROOT.glob("*.cpp")):
        for key, span in _brace_function_spans(owner).items():
            name = key.rsplit("::", 1)[-1].split("#", 1)[0]
            if span > 150:
                oversized[key] = span
            if name in {"i", "string", "bone_attr_ids"}:
                false_positives.add(key)
    assert not false_positives
    assert not oversized
