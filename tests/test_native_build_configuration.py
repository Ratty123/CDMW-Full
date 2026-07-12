from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mesh_core_packaging_uses_profile_native_configuration() -> None:
    spec_source = (ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")

    assert 'NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"' in spec_source
    assert (
        '_add_native_binary(f"native/cdmw_mesh_core/build/{NATIVE_CONFIGURATION}/cdmw-mesh-core.exe", '
        '"native", required_release=True)'
    ) in spec_source
