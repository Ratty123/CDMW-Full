"""The retired renderer cannot reenter the release helper contract."""
from pathlib import Path


def test_rust_owns_preview_packaging() -> None:
    root = Path(__file__).resolve().parents[1]
    packaging = (root / "build_pyside6_app.ps1").read_text(encoding="utf-8")
    assert "function Assert-RustMeshEditorControlContract" in packaging
    assert "Assert-RustMeshEditorControlContract -RustContract $contract" in packaging
    assert "Get-DotNetMeshEditorHelperContract" not in packaging
    assert not (root / "tools/dotnet_mesh_editor_experiment/Cdmw.MeshEditorExperiment.csproj").exists()
