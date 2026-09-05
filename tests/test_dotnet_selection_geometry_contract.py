from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[1]
HELPER = (
    ROOT
    / "tools"
    / "dotnet_mesh_editor_experiment"
    / "bin"
    / "Release"
    / "net10.0-windows"
    / "cdmw-mesh-dotnet-editor.dll"
)






def test_csharp_tolerance_policy_matches_authoritative_native_screen_selection() -> None:
    native = (
        ROOT / "native" / "cdmw_mesh_core" / "src" / "owners" / "session_state_02.cpp"
    ).read_text(encoding="utf-8")

    assert "constexpr double epsilon = 1.0e-9" in native
    assert "const double t = length_squared <= 1.0e-12" in native
    assert "if (std::abs(area) <= 1.0e-12)" in native
