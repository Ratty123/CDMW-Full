from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path

from cdmw.services.asset_authoring_service import AssetAuthoringService
from tools.mesh_harness.constants import (
    _DEFAULT_GAME_ROOT,
    _DOTNET_NATIVE_PARITY_SCENARIO,
)
from tools.mesh_harness.evidence import _write_json_atomic
from tools.mesh_harness.png_evidence import _png_capture_summary


MESH_IMAGE_PARITY_SCHEMA = "cdmw_mesh_image_parity_v1"
DEFAULT_PARITY_FAIL_THRESHOLD = 0.004
DEFAULT_PARITY_FAIL_PERCENT = 1.0
DEFAULT_PARITY_HARD_FAIL_THRESHOLD = 0.008
DEFAULT_PARITY_DIFFERENCE_SCALE = 8.0


def run_mesh_dotnet_native_parity_report(
    output_dir: Path,
    game_root: Path | str | None = None,
    *,
    reference_capture_path: Path | str | None = None,
    candidate_capture_path: Path | str | None = None,
    configured_paths: Mapping[str, object] | None = None,
    fail_threshold: float = DEFAULT_PARITY_FAIL_THRESHOLD,
    fail_percent: float = DEFAULT_PARITY_FAIL_PERCENT,
    hard_fail_threshold: float = DEFAULT_PARITY_HARD_FAIL_THRESHOLD,
    difference_scale: float = DEFAULT_PARITY_DIFFERENCE_SCALE,
    timeout_s: float = 60.0,
) -> dict[str, object]:
    """Compare explicit same-camera renderer captures with OpenImageIO.

    This is an offline pixel comparison. It does not create captures or prove
    that the two inputs share camera, lighting, exposure, or asset provenance.
    """

    output_dir.mkdir(parents=True, exist_ok=True)
    resolved_game_root = Path(game_root) if game_root is not None else _DEFAULT_GAME_ROOT
    reference_capture = (
        Path(reference_capture_path).expanduser()
        if reference_capture_path is not None
        else output_dir / "native_d3d11_capture.png"
    )
    candidate_capture = (
        Path(candidate_capture_path).expanduser()
        if candidate_capture_path is not None
        else output_dir / "dotnet_d3d11_capture.png"
    )
    difference_capture = output_dir / "dotnet_native_absdiff.png"
    reference_summary = _capture_summary(reference_capture)
    candidate_summary = _capture_summary(candidate_capture)
    blockers = _capture_pair_blockers(
        reference_capture,
        candidate_capture,
        reference_summary,
        candidate_summary,
    )

    comparison: dict[str, object] = {}
    if not blockers:
        comparison = AssetAuthoringService().run_openimageio_diff(
            reference_capture,
            candidate_capture,
            configured_paths,
            timeout_s=timeout_s,
            fail_threshold=fail_threshold,
            fail_percent=fail_percent,
            hard_fail_threshold=hard_fail_threshold,
            difference_output_path=difference_capture,
            difference_scale=difference_scale,
        )
        comparison_status = str(comparison.get("status", "") or "")
        if comparison_status in {"helper_unavailable", "configured_missing"}:
            blockers.append(
                "OpenImageIO oiiotool is unavailable; configure --oiio-path or CDMW_OIIO_BIN."
            )
        elif comparison_status not in {"ok", "different"}:
            detail = str(comparison.get("stderr") or comparison.get("message") or comparison_status or "unknown error")
            blockers.append(f"OpenImageIO comparison failed: {detail}")

    comparison_status = str(comparison.get("status", "") or "")
    comparison_executed = comparison_status in {"ok", "different"}
    threshold_passed = comparison_status == "ok"
    comparison_warning = str((comparison.get("metrics", {}) or {}).get("result", "") or "") == "warning"
    if blockers:
        status = "blocked"
    elif comparison_warning:
        status = "passed_with_warning"
    elif threshold_passed:
        status = "passed"
    else:
        status = "threshold_mismatch"

    report = {
        "schema": MESH_IMAGE_PARITY_SCHEMA,
        "scenario": _DOTNET_NATIVE_PARITY_SCENARIO,
        "ok": threshold_passed,
        "status": status,
        "mode": "offline_openimageio_capture_comparison",
        "proof_class": "offline_pixel_comparison",
        "user_facing_visual_proof": False,
        "authority": "dotnet_vortice_d3d11",
        "comparison_backend": "legacy_cpp_d3d11",
        "image_diff_backend": "openimageio_oiiotool" if comparison_executed else "unavailable",
        "dotnet_role": "production_authoritative_renderer",
        "game_root": str(resolved_game_root),
        "debug_channels": ["base", "normal", "roughness", "metallic", "emissive", "final"],
        "compared_channel": "final",
        "reference_capture_png": str(reference_capture),
        "candidate_capture_png": str(candidate_capture),
        "native_capture_png": str(reference_capture),
        "dotnet_capture_png": str(candidate_capture),
        "reference_capture_summary": reference_summary,
        "candidate_capture_summary": candidate_summary,
        "native_capture_summary": reference_summary,
        "dotnet_capture_summary": candidate_summary,
        "capture_pair_valid": not bool(_capture_pair_blockers(
            reference_capture,
            candidate_capture,
            reference_summary,
            candidate_summary,
        )),
        "capture_inputs_explicit": reference_capture_path is not None and candidate_capture_path is not None,
        "same_camera_proven": False,
        "thresholds": {
            "fail_threshold": float(fail_threshold),
            "fail_percent": float(fail_percent),
            "hard_fail_threshold": float(hard_fail_threshold),
        },
        "comparison_executed": comparison_executed,
        "threshold_passed": threshold_passed,
        "diff_metrics": dict(comparison.get("metrics", {}) or {}),
        "comparison_result": comparison,
        "difference_image_png": str(difference_capture),
        "difference_image_written": bool(comparison.get("difference_output_written")),
        "difference_image_scale": float(difference_scale),
        "difference_image_summary": (
            _png_capture_summary(difference_capture) if difference_capture.is_file() else {"ok": False, "error": "difference image missing"}
        ),
        "blockers": blockers,
        "limitations": [
            "The harness compares supplied pixels but does not yet automate same-camera capture production.",
            "A passing offline diff is regression evidence, not a substitute for the canonical real-PAC visual gate.",
            "Per-channel parity requires separate base, normal, roughness, metallic, emissive, and final captures.",
        ],
    }
    _write_json_atomic(output_dir / "dotnet_native_parity_report.json", report)
    return report


def _capture_summary(path: Path) -> dict[str, object]:
    if not path.is_file():
        return {"ok": False, "error": "capture missing", "path": str(path)}
    if path.suffix.casefold() != ".png":
        return {"ok": False, "error": "parity capture must be PNG", "path": str(path)}
    return {**_png_capture_summary(path), "path": str(path)}


def _capture_pair_blockers(
    reference_capture: Path,
    candidate_capture: Path,
    reference_summary: Mapping[str, object],
    candidate_summary: Mapping[str, object],
) -> list[str]:
    blockers: list[str] = []
    if reference_capture.resolve(strict=False) == candidate_capture.resolve(strict=False):
        blockers.append("Reference and candidate captures must be different files.")
    if not bool(reference_summary.get("ok")):
        blockers.append(f"Reference capture is invalid: {reference_summary.get('error', 'unknown error')}")
    if not bool(candidate_summary.get("ok")):
        blockers.append(f"Candidate capture is invalid: {candidate_summary.get('error', 'unknown error')}")
    reference_size = (reference_summary.get("width"), reference_summary.get("height"))
    candidate_size = (candidate_summary.get("width"), candidate_summary.get("height"))
    if bool(reference_summary.get("ok")) and bool(candidate_summary.get("ok")) and reference_size != candidate_size:
        blockers.append(
            f"Capture dimensions differ: reference={reference_size[0]}x{reference_size[1]} "
            f"candidate={candidate_size[0]}x{candidate_size[1]}."
        )
    return blockers


__all__ = [
    "DEFAULT_PARITY_DIFFERENCE_SCALE",
    "DEFAULT_PARITY_FAIL_PERCENT",
    "DEFAULT_PARITY_FAIL_THRESHOLD",
    "DEFAULT_PARITY_HARD_FAIL_THRESHOLD",
    "MESH_IMAGE_PARITY_SCHEMA",
    "run_mesh_dotnet_native_parity_report",
]
