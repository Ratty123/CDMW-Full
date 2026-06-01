from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
import sys
import time
import traceback
from typing import Any, Dict, Iterable, Mapping, Sequence

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.core.archive import (
    archive_entry_load_priority,
    build_archive_entry_basename_index,
    build_archive_entry_path_index,
    build_archive_preview_result,
)
from cdmw.core.archive_accelerator import scan_archive_entries_cached_accelerated
from cdmw.models import ArchiveEntry, ModelPreviewData, ModelPreviewMesh


DEFAULT_CTF_ROOT = Path(r"C:\Users\Ratrider\Desktop\CTF")
DEFAULT_GAME_ROOT = Path(r"C:\games\Steam\steamapps\common\Crimson Desert")
DEFAULT_TARGET = "cd_phm_02_sword_0015.pac"
DEFAULT_BODY_BASENAMES = (
    "cd_phm_00_nude_10_0001.pac",
    "cd_phm_00_nude_00_0001.pac",
    "cd_phm_00_nude_00_4001.pac",
)


def _entry_row(entry: ArchiveEntry) -> Dict[str, object]:
    return {
        "path": entry.path,
        "package": entry.pamt_path.parent.name,
        "comp_size": int(entry.comp_size),
        "orig_size": int(entry.orig_size),
        "compression": entry.compression_label,
        "encrypted": bool(entry.encrypted),
    }


def _model_bounds_sample(model: ModelPreviewData, *, max_positions: int = 16384) -> Dict[str, object]:
    positions = []
    for mesh in tuple(getattr(model, "meshes", ()) or ()):
        if not isinstance(mesh, ModelPreviewMesh):
            continue
        positions.extend(tuple(mesh.positions or ())[:4096])
        if len(positions) >= max_positions:
            break
    if not positions:
        return {"sample_spans": (0.0, 0.0, 0.0), "ballish_bounds": True}
    xs = [float(position[0]) for position in positions]
    ys = [float(position[1]) for position in positions]
    zs = [float(position[2]) for position in positions]
    spans = (max(xs) - min(xs), max(ys) - min(ys), max(zs) - min(zs))
    finite = all(math.isfinite(value) for value in spans)
    max_span = max(spans) if spans else 0.0
    min_span = min(spans) if spans else 0.0
    return {
        "sample_spans": tuple(round(value, 4) for value in spans),
        "ballish_bounds": bool((not finite) or max_span <= 0.0 or min_span / max_span > 0.72),
    }


def _model_stats(model: object) -> Dict[str, object]:
    if not isinstance(model, ModelPreviewData):
        return {"available": False, "ballish_bounds": True}
    bounds = _model_bounds_sample(model)
    return {
        "available": True,
        "format": str(getattr(model, "format", "") or ""),
        "mesh_count": int(getattr(model, "mesh_count", 0) or 0),
        "vertex_count": int(getattr(model, "vertex_count", 0) or 0),
        "face_count": int(getattr(model, "face_count", 0) or 0),
        "summary": str(getattr(model, "summary", "") or "").strip(),
        **bounds,
    }


def _preview_entry(
    entry: ArchiveEntry,
    *,
    entries_by_path: Mapping[str, Sequence[ArchiveEntry]],
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    label: str,
) -> Dict[str, object]:
    started = time.perf_counter()
    result = build_archive_preview_result(
        None,
        entry,
        texture_entries_by_normalized_path=dict(entries_by_path),
        texture_entries_by_basename=dict(entries_by_basename),
        support_texture_slots=(),
        quality_tier="fast",
    )
    elapsed = max(0.0, time.perf_counter() - started)
    return {
        "label": label,
        "entry": _entry_row(entry),
        "elapsed_s": round(elapsed, 3),
        "status": str(getattr(result, "status", "") or ""),
        "metadata": str(getattr(result, "metadata_summary", "") or ""),
        "warning_badge": str(getattr(result, "warning_badge", "") or ""),
        "warning_text": str(getattr(result, "warning_text", "") or ""),
        "timings": {
            str(key): round(float(value), 3)
            for key, value in dict(getattr(result, "timings", {}) or {}).items()
        },
        "model": _model_stats(getattr(result, "preview_model", None)),
    }


def _first_by_basename(
    entries_by_basename: Mapping[str, Sequence[ArchiveEntry]],
    basenames: Iterable[str],
) -> Sequence[ArchiveEntry]:
    result = []
    for basename in basenames:
        candidates = list(entries_by_basename.get(str(basename).lower(), ()))
        candidates.sort(key=archive_entry_load_priority, reverse=True)
        if candidates:
            result.append(candidates[0])
    return tuple(result)


def _markdown_report(payload: Mapping[str, Any]) -> str:
    failures = tuple(str(value) for value in payload.get("failures", ()) or ())
    target_preview = payload.get("target_preview") if isinstance(payload.get("target_preview"), Mapping) else {}
    body_previews = tuple(value for value in payload.get("body_previews", ()) or () if isinstance(value, Mapping))
    lines = [
        "# Weapon Placement Studio CTF Smoke",
        "",
        f"- Target: `{payload.get('target')}`",
        f"- Game root: `{payload.get('game_root')}`",
        f"- Cache root: `{payload.get('cache_root')}`",
        f"- Archive source: `{payload.get('scan_source')}`",
        f"- Archive scan wall: `{payload.get('scan_wall_s')}s`",
        f"- Index wall: `{payload.get('index_wall_s')}s`",
        f"- Result: `{'PASS' if not failures else 'FAIL'}`",
        "",
        "## Target PAC",
        "",
        f"- Decode: `{target_preview.get('elapsed_s')}s`",
        f"- Metadata: `{target_preview.get('metadata')}`",
        f"- Model: `{json.dumps(target_preview.get('model', {}), sort_keys=True)}`",
        "",
        "## Body PAC Candidates",
        "",
    ]
    for preview in body_previews:
        model = preview.get("model", {})
        entry = preview.get("entry", {})
        lines.append(
            f"- `{entry.get('path')}`: decode `{preview.get('elapsed_s')}s`, "
            f"model `{json.dumps(model, sort_keys=True)}`"
        )
    if failures:
        lines.extend(("", "## Failures", ""))
        lines.extend(f"- {failure}" for failure in failures)
    lines.extend(("", "## Raw JSON", "", "```json", json.dumps(payload, indent=2, sort_keys=True), "```", ""))
    return "\n".join(lines)


def run_smoke(args: argparse.Namespace) -> Dict[str, Any]:
    game_root = Path(args.game_root)
    ctf_root = Path(args.ctf_root)
    cache_root = Path(args.cache_root) if args.cache_root else ctf_root / "archive_cache"
    report_dir = Path(args.report_dir) if args.report_dir else ctf_root / "benchmark_reports"
    target = str(args.target or DEFAULT_TARGET)
    payload: Dict[str, Any] = {
        "target": target,
        "game_root": str(game_root),
        "cache_root": str(cache_root),
        "report_dir": str(report_dir),
        "failures": [],
    }
    failures = payload["failures"]
    if not game_root.exists():
        failures.append(f"Game root missing: {game_root}")
        return payload
    scan_started = time.perf_counter()
    entries, source, _cache_path, scan_timings, _metadata = scan_archive_entries_cached_accelerated(
        game_root,
        cache_root,
        force_refresh=False,
    )
    payload.update(
        scan_source=source,
        entry_count=len(entries),
        scan_wall_s=round(max(0.0, time.perf_counter() - scan_started), 3),
        scan_timings={str(key): round(float(value), 3) for key, value in dict(scan_timings).items()},
    )
    index_started = time.perf_counter()
    entries_by_basename = build_archive_entry_basename_index(entries)
    entries_by_path = build_archive_entry_path_index(entries)
    payload.update(
        index_wall_s=round(max(0.0, time.perf_counter() - index_started), 3),
        basename_keys=len(entries_by_basename),
        path_keys=len(entries_by_path),
    )
    target_candidates = _first_by_basename(entries_by_basename, (target,))
    payload["target_candidates"] = [_entry_row(entry) for entry in target_candidates]
    if not target_candidates:
        failures.append(f"Target PAC not found: {target}")
        return payload
    body_candidates = _first_by_basename(entries_by_basename, DEFAULT_BODY_BASENAMES)
    payload["body_candidates"] = [_entry_row(entry) for entry in body_candidates]
    if not body_candidates:
        failures.append("No PHM body PAC candidate found")
        return payload
    target_preview = _preview_entry(
        target_candidates[0],
        entries_by_path=entries_by_path,
        entries_by_basename=entries_by_basename,
        label="target",
    )
    body_previews = [
        _preview_entry(
            body_entry,
            entries_by_path=entries_by_path,
            entries_by_basename=entries_by_basename,
            label=body_entry.basename,
        )
        for body_entry in body_candidates[:3]
    ]
    payload["target_preview"] = target_preview
    payload["body_previews"] = body_previews
    max_target_s = float(args.max_target_preview_s)
    max_body_s = float(args.max_body_preview_s)
    if float(target_preview.get("elapsed_s", 999.0)) > max_target_s:
        failures.append(f"Target decode timing threshold exceeded: {target_preview.get('elapsed_s')}s > {max_target_s}s")
    if bool((target_preview.get("model") or {}).get("ballish_bounds")):
        failures.append("Target model has ballish_bounds")
    if not bool((target_preview.get("model") or {}).get("available")):
        failures.append("Target model missing")
    for preview in body_previews:
        if float(preview.get("elapsed_s", 999.0)) > max_body_s:
            failures.append(f"Body decode timing threshold exceeded: {preview.get('label')} {preview.get('elapsed_s')}s > {max_body_s}s")
        if bool((preview.get("model") or {}).get("ballish_bounds")):
            failures.append(f"Body model has ballish_bounds: {preview.get('label')}")
        if not bool((preview.get("model") or {}).get("available")):
            failures.append(f"Body model missing: {preview.get('label')}")
    report_dir.mkdir(parents=True, exist_ok=True)
    timestamp = time.strftime("%Y%m%d_%H%M%S")
    report_path = report_dir / f"weapon_placement_studio_{timestamp}.md"
    report_path.write_text(_markdown_report(payload), encoding="utf-8")
    payload["report_path"] = str(report_path)
    return payload


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="CTF smoke test for Weapon Placement Studio PAC preview inputs.")
    parser.add_argument("--ctf-root", default=str(DEFAULT_CTF_ROOT))
    parser.add_argument("--game-root", default=str(DEFAULT_GAME_ROOT))
    parser.add_argument("--cache-root", default="")
    parser.add_argument("--report-dir", default="")
    parser.add_argument("--target", default=DEFAULT_TARGET)
    parser.add_argument("--max-target-preview-s", type=float, default=2.0)
    parser.add_argument("--max-body-preview-s", type=float, default=2.5)
    args = parser.parse_args(argv)
    try:
        payload = run_smoke(args)
    except Exception as exc:
        payload = {
            "target": args.target,
            "game_root": args.game_root,
            "cache_root": args.cache_root or str(Path(args.ctf_root) / "archive_cache"),
            "failures": [f"{type(exc).__name__}: {exc}"],
            "traceback": traceback.format_exc(),
        }
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0 if not payload.get("failures") else 1


if __name__ == "__main__":
    raise SystemExit(main())
