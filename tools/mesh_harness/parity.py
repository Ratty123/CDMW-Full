from __future__ import annotations

from pathlib import Path
from tools.mesh_harness.constants import (
    _DEFAULT_GAME_ROOT,
    _DOTNET_NATIVE_PARITY_SCENARIO,
)
from tools.mesh_harness.evidence import _write_json_atomic

from tools.mesh_harness.png_evidence import (
    _png_capture_summary,
)

def run_mesh_dotnet_native_parity_report(output_dir: Path, game_root: Path | str | None = None) -> dict[str, object]:
    """Report that automated renderer parity comparison is not implemented."""
    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_game_root = Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT
    debug_channels = ["base", "normal", "roughness", "metallic", "emissive", "final"]
    native_capture = output_dir / "native_d3d11_capture.png"
    dotnet_capture = output_dir / "dotnet_d3d11_capture.png"
    report = {
        "scenario": _DOTNET_NATIVE_PARITY_SCENARIO,
        "ok": False,
        "status": "blocked",
        "mode": "blocked_report_scaffold",
        "authority": "dotnet_vortice_d3d11",
        "comparison_backend": "legacy_cpp_d3d11",
        "dotnet_role": "production_authoritative_renderer",
        "game_root": str(resolved_game_root),
        "debug_channels": debug_channels,
        "native_capture_png": str(native_capture),
        "dotnet_capture_png": str(dotnet_capture),
        "native_capture_summary": _png_capture_summary(native_capture) if native_capture.is_file() else {"ok": False, "error": "native capture missing"},
        "dotnet_capture_summary": _png_capture_summary(dotnet_capture) if dotnet_capture.is_file() else {"ok": False, "error": "dotnet capture missing"},
        "diff_metrics": {},
        "blockers": [
            "Automated same-camera .NET versus legacy-renderer capture comparison is not implemented; use the canonical .NET real-game proof.",
        ],
    }
    _write_json_atomic(output_dir / "dotnet_native_parity_report.json", report)
    return report
