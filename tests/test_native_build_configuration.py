from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_mesh_core_packaging_uses_profile_native_configuration() -> None:
    spec_source = (ROOT / "CrimsonDesertModWorkbench.spec").read_text(encoding="utf-8")
    native_builder_source = (ROOT / "build_native_windows.ps1").read_text(encoding="utf-8")
    package_builder_source = (ROOT / "build_pyside6_app.ps1").read_text(encoding="utf-8")

    assert 'NATIVE_CONFIGURATION = "Debug" if PROFILE == "debug" else "Release"' in spec_source
    assert (
        '_add_native_binary(f"native/cdmw_mesh_core/build/{NATIVE_CONFIGURATION}/cdmw-mesh-core.exe", '
        '"native", required_release=True)'
    ) in spec_source
    assert (
        '_add_native_binary(f"native/cdmw_mesh_core/build/{NATIVE_CONFIGURATION}/cdmw-mesh-core.dll", '
        '"native", required_release=True)'
    ) in spec_source
    # The retired renderer's payload tree is gone; only the native ABI copy
    # remains, selected from the active native build configuration above.
    assert 'native/cdmw_mesh_dotnet_editor/build/' not in spec_source
    assert '"native\\cdmw_mesh_core\\build\\$Configuration\\cdmw-mesh-core.dll"' in native_builder_source
    assert '"native\\cdmw_mesh_core\\build\\$Configuration\\cdmw-mesh-core.dll"' in package_builder_source
