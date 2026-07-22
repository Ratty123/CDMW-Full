from __future__ import annotations

import json
import subprocess
import time
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from cdmw.core.atomic_file import atomic_write_text


_DOTNET_AUDIT_PRESENTATION_PROFILE: dict[str, object] = {
    "profile": "mesh_editor_default_v1",
    "high_quality": True,
    "view_mode": "lit",
    "cull_back_faces": False,
    "disable_depth_test": False,
    "disable_tint": False,
    "disable_brightness": True,
    "disable_uv_scale": True,
    "ao_strength": 0.45,
    "roughness_bias": -0.04,
    "metalness_scale": 1.45,
    "environment_strength": 0.62,
    "emissive_gain": 2.2,
    "tone_exposure": 1.0,
    "tone_contrast": 1.08,
    "tone_gamma": 1.0,
    "sampling_filter": "anisotropic",
    "max_anisotropy": 16,
    "mip_lod_bias": -2.0,
    "texture_address_mode": "wrap",
    "ambient_strength": 0.84,
    "diffuse_wrap_bias": 0.58,
    "diffuse_light_scale": 0.62,
    "specular_base": 0.055,
    "specular_max": 0.52,
    "color_pipeline": "srgb_srv_linear_shader_srgb_rtv",
}


def run_archive_browser_capture_batch(
    runtime_assets: Sequence[Mapping[str, object]],
    output_root: Path,
    runtime_root: Path,
    *,
    run_id: str,
    assembly_path: Path,
    timeout_seconds: float = 900.0,
    progress: Callable[[int, int, str], None] | None = None,
) -> dict[str, object]:
    """Capture Archive Browser proof through the canonical Vortice batch."""

    if not runtime_assets:
        raise ValueError("Archive Browser capture batch has no assets.")
    if progress is not None:
        for index, asset in enumerate(runtime_assets, 1):
            progress(index, len(runtime_assets), str(asset["virtual_path"]))
    report = run_dotnet_capture_batch(
        runtime_assets,
        output_root,
        runtime_root,
        run_id=run_id,
        assembly_path=assembly_path,
        timeout_seconds=timeout_seconds,
    )
    return {
        **report,
        "schema": "cdmw_mesh_visual_audit_archive_browser_batch_v2",
        "backend": "d3d11_vortice_shader",
        "surface": "archive_browser",
        "shared_package_artifacts": True,
    }


def _dotnet_audit_presentation_is_safe(report: Mapping[str, object]) -> bool:
    session = report.get("renderer_session")
    if not isinstance(session, Mapping):
        return False
    if (
        session.get("capture_mode") != "hidden_hwnd_no_show"
        or session.get("native_windows_remained_hidden") is not True
    ):
        return False
    presentation = session.get("presentation")
    if not isinstance(presentation, Mapping):
        return False
    for key, expected in _DOTNET_AUDIT_PRESENTATION_PROFILE.items():
        actual = presentation.get(key)
        if isinstance(expected, float):
            if not isinstance(actual, (int, float)) or isinstance(actual, bool):
                return False
            if abs(float(actual) - expected) > 1e-6:
                return False
        elif actual != expected:
            return False
    return True


def run_dotnet_capture_batch(
    runtime_assets: Sequence[Mapping[str, object]],
    output_root: Path,
    runtime_root: Path,
    *,
    run_id: str,
    assembly_path: Path,
    timeout_seconds: float = 900.0,
) -> dict[str, object]:
    output_root = Path(output_root).resolve()
    runtime_root = Path(runtime_root).resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    runtime_root.mkdir(parents=True, exist_ok=True)
    manifest_path = runtime_root / "dotnet-batch-manifest.json"
    report_path = runtime_root / "dotnet-batch-report.json"
    report_path.unlink(missing_ok=True)
    manifest = {
        "schema": "cdmw_mesh_visual_audit_dotnet_batch_v2",
        "compatible_reader_schemas": ["cdmw_mesh_visual_audit_dotnet_batch_v1"],
        "run_id": run_id,
        "output_root": str(output_root),
        "width": 768,
        "height": 768,
        "assets": [
            {
                "id": str(asset["id"]),
                "package_dir": str(asset["dotnet_package_dir"]),
                "resident_material_state_path": str(
                    asset.get("resident_material_state_path", "") or ""
                ),
                "views": [dict(view) for view in tuple(asset.get("views", ()) or ())],
                "material_regions": [
                    dict(region)
                    for region in tuple(asset.get("material_regions", ()) or ())
                    if isinstance(region, Mapping)
                ],
            }
            for asset in runtime_assets
        ],
    }
    _atomic_write_json(manifest_path, manifest)
    command = [
        "dotnet",
        str(Path(assembly_path).resolve()),
        "--visual-audit-batch",
        str(manifest_path),
        "--visual-audit-report",
        str(report_path),
    ]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=Path(__file__).resolve().parents[2],
            capture_output=True,
            text=True,
            timeout=max(30.0, float(timeout_seconds)),
            check=False,
        )
        report = _read_json(report_path)
        expected_ids = [str(asset["id"]) for asset in runtime_assets]
        actual_ids = [
            str(row.get("id", ""))
            for row in tuple(report.get("assets", ()) or ())
            if isinstance(row, Mapping)
        ]
        presentation_contract_ok = _dotnet_audit_presentation_is_safe(report)
        current_ok = (
            completed.returncode == 0
            and report.get("ok") is True
            and str(report.get("run_id", "")) == run_id
            and actual_ids == expected_ids
            and presentation_contract_ok
        )
        return {
            **report,
            "ok": current_ok,
            "presentation_contract_ok": presentation_contract_ok,
            "presentation_contract_error": "" if presentation_contract_ok else (
                "Visual-audit capture did not prove the canonical Mesh Editor "
                "presentation, sampling, depth, culling, and color-pipeline profile."
            ),
            "command": command,
            "exit_code": int(completed.returncode),
            "wall_ms": (time.perf_counter() - started) * 1000.0,
            "stdout_tail": completed.stdout[-65536:],
            "stderr_tail": completed.stderr[-65536:],
        }
    except subprocess.TimeoutExpired as exc:
        return {
            "schema": "cdmw_mesh_visual_audit_dotnet_batch_v2",
            "run_id": run_id,
            "ok": False,
            "command": command,
            "timeout_seconds": float(timeout_seconds),
            "wall_ms": (time.perf_counter() - started) * 1000.0,
            "stdout_tail": (exc.stdout or "")[-65536:] if isinstance(exc.stdout, str) else "",
            "stderr_tail": (exc.stderr or "")[-65536:] if isinstance(exc.stderr, str) else "",
            "fatal_error": "The resident .NET visual-audit batch timed out.",
        }


def _read_json(path: Path) -> dict[str, object]:
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return dict(payload) if isinstance(payload, Mapping) else {}


def _atomic_write_json(path: Path, payload: object) -> None:
    atomic_write_text(
        Path(path),
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
    )


__all__ = ["run_archive_browser_capture_batch", "run_dotnet_capture_batch"]
