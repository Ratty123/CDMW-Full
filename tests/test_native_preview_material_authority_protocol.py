from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOTNET_ROOT = ROOT / "tools" / "dotnet_mesh_editor_experiment"


def test_dotnet_preview_material_authority_protocol_source_contract() -> None:
    host_text = (ROOT / "cdmw" / "ui" / "preview" / "dotnet_host.py").read_text(
        encoding="utf-8"
    )

    assert '"material_parameter_update"' in host_text
    assert '"schema": "cdmw_mesh_material_parameters_v1"' in host_text


def test_retired_native_material_protocol_is_not_present() -> None:
    assert not (ROOT / "cdmw" / "ui" / "native_d3d11_preview_host.py").exists()
    assert not (ROOT / "native" / "cdmw_d3d11_preview").exists()
