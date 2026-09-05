"""The production C++ ABI remains part of the native validation route."""
from pathlib import Path


def test_mesh_unit_builds_the_production_native_abi() -> None:
    source = (Path(__file__).resolve().parents[1] / "scripts" / "codex_check.ps1").read_text(encoding="utf-8")
    assert 'cmake --build $MeshCoreBuild --config Release --target cdmw-mesh-core-abi' in source
    assert '$DotNetHelper' not in source
