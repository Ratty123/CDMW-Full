from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def test_dotnet_preview_material_authority_protocol_source_contract() -> None:
    host_text = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(
        encoding="utf-8"
    )
    protocol_text = (DOTNET_ROOT / "ExperimentForm.Protocol.cs").read_text(encoding="utf-8")
    parameters_text = (DOTNET_ROOT / "NetMaterialSet.Parameters.cs").read_text(
        encoding="utf-8"
    )
    presentation_text = (
        DOTNET_ROOT / "D3D11MaterialViewport.PresentationSettings.cs"
    ).read_text(encoding="utf-8")
    shader_text = (DOTNET_ROOT / "D3D11MaterialShaders.hlsl").read_text(
        encoding="utf-8"
    )

    assert '"material_parameter_update"' in host_text
    assert '"schema": "cdmw_mesh_material_parameters_v1"' in host_text
    assert 'case "material_parameter_update":' in protocol_text
    assert '"resident_material_parameter_updates_v1"' in protocol_text
    assert 'OptionalBoolean(group, "emissive_color_authoritative")' in parameters_text
    assert 'OptionalBoolean(group, "emissive_scalar_mask")' in parameters_text
    assert 'RoughnessHint = OptionalFloat(group, "roughness_hint"' in parameters_text
    assert "MaterialHintPresenceMask" in presentation_text
    assert "parameters.RoughnessHint.HasValue" in presentation_text
    assert "emissive = max(emissiveColor, emissiveSample.rgb)" in shader_text


def test_retired_native_material_protocol_is_not_present() -> None:
    assert not (ROOT / "cdmw" / "ui" / "native_d3d11_preview_host.py").exists()
    assert not (ROOT / "native" / "cdmw_d3d11_preview").exists()
