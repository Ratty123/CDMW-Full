from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path
from uuid import uuid4

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tools.mesh_harness.modify_original_audit import run_modify_original_material_subset
from tools.mesh_harness.visual_audit_corpus import default_visual_audit_v2_specs


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the hidden 12-asset Modify Original PAC-material production-orchestration audit."
        )
    )
    parser.add_argument("--game-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--dotnet-assembly", type=Path)
    parser.add_argument("--dotnet-timeout", type=float, default=1800.0)
    return parser


def main() -> int:
    parser = _parser()
    args = parser.parse_args()
    game_root = args.game_root.resolve()
    output = args.output.resolve()
    assembly = (
        args.dotnet_assembly.resolve()
        if args.dotnet_assembly is not None
        else (
            Path(__file__).resolve().parent
            / "dotnet_mesh_editor_experiment"
            / "bin"
            / "Release"
            / "net8.0-windows"
            / "cdmw-mesh-dotnet-editor.dll"
        )
    )
    if not assembly.is_file():
        parser.error(
            "The Release .NET renderer is missing. Run dotnet build on "
            "tools\\dotnet_mesh_editor_experiment\\Cdmw.MeshEditorExperiment.csproj first."
        )
    run_id = uuid4().hex
    temporary_root = (
        Path(tempfile.gettempdir())
        / "cdmw-mesh-modify-original-audit"
        / run_id
    ).resolve()
    specs = default_visual_audit_v2_specs(game_root)
    report = run_modify_original_material_subset(
        game_root=game_root,
        output_root=output,
        temporary_root=temporary_root,
        specs=specs,
        assembly_path=assembly,
        run_id=run_id,
        timeout_seconds=max(30.0, float(args.dotnet_timeout)),
        progress=lambda current, total, role, path: print(
            f"[{current:02d}/{total:02d}] {role}: {path}",
            flush=True,
        ),
    )
    print(
        f"Modify Original subset: {'PASS' if report.get('ok') else 'FAIL'} | "
        f"assets={report.get('asset_count')} | evidence={output}",
        flush=True,
    )
    return 0 if report.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
