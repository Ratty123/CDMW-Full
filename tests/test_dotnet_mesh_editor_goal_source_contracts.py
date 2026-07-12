from pathlib import Path


def test_dotnet_material_channels_and_embedded_panel_source_contracts() -> None:
    dotnet_root = Path(__file__).resolve().parents[1] / "tools" / "dotnet_mesh_editor_experiment"
    source = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(dotnet_root.glob("*.cs"))
        if path.name != "Cdmw.MeshEditorExperiment.GlobalUsings.g.cs"
    )
    hlsl_source = (dotnet_root / "D3D11MaterialShaders.hlsl").read_text(encoding="utf-8")

    assert "MaterialChannelSelectors" in hlsl_source
    assert "MaterialTint.w > 0.5f ? float4(1.0f, 1.0f, 1.0f, 1.0f)" in hlsl_source
    assert "roughnessSample[(int)MaterialChannelSelectors.x]" in hlsl_source
    assert "metallicSample[(int)MaterialChannelSelectors.y]" in hlsl_source
    assert "ChannelComponentIndexForSubmesh" in source
    assert all(key in source for key in ('"BC4" or "BC4U" or "ATI1"', '"BC5" or "BC5U" or "ATI2"'))
    assert "if (!options.Embedded)" not in source
    assert "DotNetMeshEditorToolScroll" in source
    assert 'SetWindowTheme(control.Handle, "DarkMode_Explorer", null)' in source
    assert source.index("_ = _textureSet.LoadAsync(_materials);") < source.index("_viewport = new MeshViewport")
    assert 'AddSection(stack, "Clipboard"' not in source
