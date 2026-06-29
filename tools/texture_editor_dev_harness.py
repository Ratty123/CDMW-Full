from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Sequence

import numpy as np

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from cdmw.domain.textures.editor_presets import resolve_texture_editor_dds_preset, texture_editor_dds_presets
from cdmw.models import TextureEditorDocument, TextureEditorLayer
from cdmw.services.texture_editor_service import TextureEditorNativeDdsOptions, TextureEditorNativeDdsService


def build_synthetic_document() -> tuple[TextureEditorDocument, dict[str, np.ndarray]]:
    base = np.zeros((8, 8, 4), dtype=np.uint8)
    base[..., 0] = 32
    base[..., 1] = 96
    base[..., 2] = 180
    base[..., 3] = 255
    overlay = np.zeros((8, 8, 4), dtype=np.uint8)
    overlay[2:6, 2:6, 0] = 220
    overlay[2:6, 2:6, 1] = 64
    overlay[2:6, 2:6, 3] = 192
    document = TextureEditorDocument(
        "harness_texture",
        8,
        8,
        active_layer_id="paint",
        layers=(
            TextureEditorLayer("base", "Base", ""),
            TextureEditorLayer("paint", "Paint", "", opacity=90),
        ),
    )
    return document, {"base": base, "paint": overlay}


def _json_safe_report(report: dict[str, object]) -> dict[str, object]:
    safe: dict[str, object] = {}
    for key, value in report.items():
        if isinstance(value, Path):
            safe[key] = str(value)
        elif isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value
        elif isinstance(value, list):
            safe[key] = value
        elif isinstance(value, dict):
            safe[key] = value
        else:
            safe[key] = str(value)
    return safe


def run_native_dds_export(output_dir: Path) -> dict[str, object]:
    document, layer_pixels = build_synthetic_document()
    scenario_dir = output_dir / "native-dds-export"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    result = TextureEditorNativeDdsService().export_dds(
        document,
        layer_pixels,
        TextureEditorNativeDdsOptions(
            output_path=scenario_dir / "harness_texture.dds",
            preset_key="base_color",
            temp_root=scenario_dir / "temp",
        ),
    )
    return {
        "ok": result.dds_path.is_file() and result.report.get("native_backend") == "directxtex",
        "dds_path": str(result.dds_path),
        "report": _json_safe_report(result.report),
    }


def run_compression_preview(output_dir: Path) -> dict[str, object]:
    document, layer_pixels = build_synthetic_document()
    scenario_dir = output_dir / "compression-preview"
    scenario_dir.mkdir(parents=True, exist_ok=True)
    result = TextureEditorNativeDdsService().preview_compressed(
        document,
        layer_pixels,
        TextureEditorNativeDdsOptions(
            output_path=scenario_dir / "harness_texture_preview.dds",
            preview_output_path=scenario_dir / "harness_texture_preview.png",
            preset_key="base_color",
            temp_root=scenario_dir / "temp",
        ),
    )
    return {
        "ok": bool(result.dds_path.is_file() and result.preview_path and result.preview_path.is_file()),
        "dds_path": str(result.dds_path),
        "preview_png": str(result.preview_path or ""),
        "report": _json_safe_report(result.report),
        "preview_report": _json_safe_report(result.preview_report),
    }


def run_preset_matrix(output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = []
    ok = True
    for preset in texture_editor_dds_presets():
        resolved = resolve_texture_editor_dds_preset(preset.key, width=8, height=8)
        row = {
            "key": preset.key,
            "format": resolved.dds_format,
            "mip_mode": resolved.mip_mode,
            "mip_count": resolved.mip_count,
            "srgb": resolved.srgb,
            "warning": resolved.warning,
        }
        rows.append(row)
        ok = ok and bool(resolved.dds_format) and resolved.mip_count >= 1
    return {"ok": bool(ok), "presets": rows}


def run_scenario(scenario: str, output_dir: Path) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    runners = {
        "native-dds-export": run_native_dds_export,
        "compression-preview": run_compression_preview,
        "preset-matrix": run_preset_matrix,
    }
    try:
        if scenario == "full-suite-smoke":
            scenarios = {name: runner(output_dir) for name, runner in runners.items()}
            result = {
                "scenario": scenario,
                "ok": all(bool(item.get("ok")) for item in scenarios.values()),
                "scenarios": scenarios,
            }
        else:
            item = runners[scenario](output_dir)
            result = {"scenario": scenario, "ok": bool(item.get("ok")), **item}
    except Exception as exc:
        result = {"scenario": scenario, "ok": False, "error": str(exc)}
    (output_dir / "result.json").write_text(json.dumps(result, indent=2, sort_keys=True), encoding="utf-8")
    return result


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Texture Editor native DDS harness without starting the app.")
    parser.add_argument(
        "--scenario",
        default="full-suite-smoke",
        choices=("native-dds-export", "compression-preview", "preset-matrix", "full-suite-smoke"),
    )
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    result = run_scenario(args.scenario, args.output)
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0 if result.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
