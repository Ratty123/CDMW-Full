"""Read-only real-archive proof for the production Rust Archive Preview.

This gate deliberately avoids Qt, desktop input and the historical Vortice
comparison harness.  It resolves the same PAC/PAC_XML/DDS material context as
Archive Browser, publishes Rust preview packages, and asks the Rust helper for
deterministic offscreen D3D12 captures.
"""

from __future__ import annotations

import json
import subprocess
import time
from hashlib import sha256
from pathlib import Path
from typing import Any

from cdmw.core.archive_format import parse_archive_pamt
from cdmw.models import ArchiveEntry
from cdmw.services.mesh_rust_contract import (
    RUST_MESH_RENDERER,
    RUST_PREVIEW_BACKEND,
    resolve_rust_mesh_editor,
    validate_rust_mesh_editor_package,
)
from cdmw.services.mesh_rust_preview_package import build_rust_preview_package
from cdmw.services.mesh_service import MeshService
from tools.mesh_harness.archive_provenance import (
    _archive_content_fingerprints,
    _archive_entry_provenance,
    _archive_source_file_snapshot,
    _hydrate_real_archive_mesh_materials,
)
from tools.mesh_harness.real_common import (
    _archive_entry_indexes,
    _archive_key,
    _read_archive_payload,
)


REAL_RUST_PREVIEW_SAMPLES = (
    (
        "sword-gold-depth",
        "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0014.pac",
    ),
    (
        "sword-blue-handle",
        "character/model/1_pc/1_phm/weapon/2_twohandweapon/cd_phm_02_sword_0009.pac",
    ),
    (
        "helmet",
        "character/model/1_pc/14_ptm/armor/13_hel/cd_ptm_00_hel_0001.pac",
    ),
    (
        "armour",
        "character/model/1_pc/14_ptm/armor/9_upperbody/cd_ptm_00_ub_00_0318.pac",
    ),
    (
        "skin",
        "character/model/1_pc/1_phm/nude/cd_phm_00_nude_00_0001.pac",
    ),
)


def _sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return payload


def _capture_gates(report: dict[str, Any], output_paths: tuple[Path, ...]) -> dict[str, bool]:
    frames = report.get("frames")
    textured = frames.get("textured") if isinstance(frames, dict) else None
    owner_rows = report.get("owner_coverage")
    owner_rows = owner_rows if isinstance(owner_rows, list) else []
    return {
        "capture_schema": report.get("schema") == "cdmw_rust_preview_material_capture_v1",
        "rust_renderer": report.get("renderer") == RUST_MESH_RENDERER,
        "d3d12_backend": str((report.get("adapter") or {}).get("backend", "")).casefold()
        == "dx12",
        "full_resolution": report.get("dimensions") == [1024, 1024],
        "msaa_enabled": int((report.get("quality") or {}).get("sample_count", 0) or 0) >= 4,
        "anisotropic_filtering": int(
            (report.get("quality") or {}).get("anisotropy_clamp", 0) or 0
        )
        >= 8,
        "dds_textures_uploaded": int(report.get("dds_textures_uploaded", 0) or 0) > 0,
        "textures_bound_to_materials": int(report.get("texture_bound_materials", 0) or 0) > 0,
        "active_material_bindings": int(report.get("active_material_bindings", 0) or 0) > 0,
        "material_ranges_rendered": int(report.get("material_ranges_rendered", 0) or 0) > 0,
        "visible_geometry": isinstance(textured, dict)
        and int(textured.get("non_background_pixels", 0) or 0) > 0,
        "owner_coverage": bool(owner_rows)
        and all(int(row.get("pixel_count", 0) or 0) > 0 for row in owner_rows),
        "capture_outputs_published": all(path.is_file() and path.stat().st_size > 0 for path in output_paths),
    }


def _capture_real_rust_preview_samples(deadline, entries_by_basename, entries_by_path, helper, output_dir, samples, selected_samples):
    for label, model_path, entry in selected_samples:
        sample_root = output_dir / label
        sample_root.mkdir(parents=True, exist_ok=True)
        started = time.perf_counter()
        try:
            payload = _read_archive_payload(entry)
            mesh = MeshService().load_mesh_bytes(payload, entry.path)
            resolved_textures, diagnostics = _hydrate_real_archive_mesh_materials(
                mesh,
                entry,
                entries_by_path,
                entries_by_basename,
            )
            package = build_rust_preview_package(
                mesh,
                output_package_dir=sample_root / "rust-preview-package",
                include_material_resources=True,
            )
            capture_path = sample_root / "textured.bmp"
            report_path = sample_root / "capture-report.json"
            remaining = max(1.0, deadline - time.monotonic())
            creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            completed = subprocess.run(
                [
                    str(helper),
                    "--capture-cdmw-preview-session",
                    str(package.manifest_path),
                    "--capture-output",
                    str(capture_path),
                    "--capture-report-json",
                    str(report_path),
                ],
                cwd=output_dir,
                capture_output=True,
                text=True,
                timeout=remaining,
                creationflags=creation_flags,
            )
            if completed.returncode != 0:
                raise RuntimeError(
                    f"Rust capture exited {completed.returncode}: "
                    f"{(completed.stderr or completed.stdout)[-2000:]}"
                )
            report = _load_json(report_path)
            package_manifest = _load_json(package.manifest_path)
            published_outputs = (
                capture_path,
                sample_root / "textured-base-color.bmp",
                sample_root / "textured-part-id.bmp",
                report_path,
            )
            gates = _capture_gates(report, published_outputs)
            vertex_count = sum(
                len(tuple(getattr(submesh, "vertices", ()) or ()))
                for submesh in tuple(getattr(mesh, "submeshes", ()) or ())
            )
            face_count = sum(
                len(tuple(getattr(submesh, "faces", ()) or ()))
                for submesh in tuple(getattr(mesh, "submeshes", ()) or ())
            )
            gates.update(
                {
                    "real_pac_geometry": vertex_count > 0 and face_count > 0,
                    "read_only_package": package_manifest.get("interaction_profile") == "read_only"
                    and (package_manifest.get("output_policy") or {}).get("archive_writes") is False,
                    "real_archive_textures": bool(resolved_textures),
                    "no_synthetic_fallback": bool(resolved_textures)
                    and all(
                        "checker" not in str(row.get("source_path", "")).casefold()
                        for row in resolved_textures
                    ),
                    "pac_xml_dds_provenance": bool(resolved_textures)
                    and all(
                        str((row.get("archive_provenance") or {}).get("pamt_path", ""))
                        and str(row.get("source_sha256", ""))
                        for row in resolved_textures
                    ),
                }
            )
            samples.append(
                {
                    "label": label,
                    "model_path": model_path,
                    "ok": all(gates.values()),
                    "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "archive_provenance": _archive_entry_provenance(entry),
                    "source_payload_sha256": sha256(payload).hexdigest(),
                    "resolved_texture_count": len(resolved_textures),
                    "resolved_texture_roles": sorted(
                        {str(row.get("semantic", "") or "") for row in resolved_textures}
                    ),
                    "material_diagnostics": list(diagnostics),
                    "package_manifest": str(package.manifest_path),
                    "capture_report": str(report_path),
                    "capture": str(capture_path),
                    "renderer": report.get("renderer"),
                    "preview_backend": RUST_PREVIEW_BACKEND,
                    "adapter": report.get("adapter"),
                    "quality": report.get("quality"),
                    "dimensions": report.get("dimensions"),
                    "gates": gates,
                }
            )
        except Exception as exc:
            samples.append(
                {
                    "label": label,
                    "model_path": model_path,
                    "ok": False,
                    "elapsed_ms": round((time.perf_counter() - started) * 1000.0, 3),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )


def run_real_archive_rust_preview_smoke(
    game_root: Path,
    output_dir: Path,
    *,
    timeout_seconds: float = 360.0,
) -> dict[str, object]:
    output_dir = Path(output_dir).resolve()
    game_root = Path(game_root).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        output_dir.relative_to(game_root)
    except ValueError:
        pass
    else:
        return {
            "ok": False,
            "read_only": False,
            "error": "Rust preview proof output must be outside the game root.",
        }

    pamt_path = game_root / "0009" / "0.pamt"
    if not pamt_path.is_file():
        return {"ok": False, "read_only": True, "error": f"missing PAMT: {pamt_path}"}
    resolution = resolve_rust_mesh_editor()
    helper_error = validate_rust_mesh_editor_package(resolution)
    if helper_error:
        return {
            "ok": False,
            "read_only": True,
            "error": helper_error,
            "rust_helper": {
                "path": resolution.resolved_path,
                "source": resolution.source,
                "exists": resolution.exists,
                "is_file": resolution.is_file,
            },
        }

    entries = tuple(parse_archive_pamt(pamt_path))
    entries_by_path, entries_by_basename = _archive_entry_indexes(entries)
    source_snapshot_before = _archive_source_file_snapshot(entries)
    selected_samples: list[tuple[str, str, ArchiveEntry]] = []
    missing_samples: list[str] = []
    for _label, model_path in REAL_RUST_PREVIEW_SAMPLES:
        entry = next(iter(entries_by_path.get(_archive_key(model_path), ())), None)
        if isinstance(entry, ArchiveEntry):
            selected_samples.append((_label, model_path, entry))
        else:
            missing_samples.append(model_path)
    fingerprint_paths = tuple(
        sorted(
            {
                Path(path).resolve()
                for _label, _model_path, entry in selected_samples
                for path in (entry.pamt_path, entry.paz_file)
                if path and Path(path).is_file()
            },
            key=lambda path: str(path).casefold(),
        )
    )
    fingerprints_before = _archive_content_fingerprints(fingerprint_paths)

    helper = Path(resolution.resolved_path)
    helper_sha256 = _sha256(helper)
    samples: list[dict[str, object]] = []
    deadline = time.monotonic() + max(30.0, float(timeout_seconds))
    _capture_real_rust_preview_samples(deadline, entries_by_basename, entries_by_path, helper, output_dir, samples, selected_samples)

    fingerprints_after = _archive_content_fingerprints(fingerprint_paths)
    source_snapshot_after = _archive_source_file_snapshot(entries)
    archives_unchanged = bool(
        fingerprints_before
        and fingerprints_before == fingerprints_after
        and source_snapshot_before == source_snapshot_after
    )
    return {
        "ok": bool(
            not missing_samples
            and len(samples) == len(REAL_RUST_PREVIEW_SAMPLES)
            and all(bool(sample.get("ok")) for sample in samples)
            and archives_unchanged
        ),
        "read_only": archives_unchanged,
        "renderer_backend": RUST_MESH_RENDERER,
        "preview_backend": RUST_PREVIEW_BACKEND,
        "rust_helper": str(helper),
        "rust_helper_sha256": helper_sha256,
        "game_root": str(game_root),
        "pamt_path": str(pamt_path),
        "sample_count": len(samples),
        "missing_samples": missing_samples,
        "samples": samples,
        "archive_content_fingerprints_before": fingerprints_before,
        "archive_content_fingerprints_after": fingerprints_after,
        "archive_sources_unchanged": archives_unchanged,
        "desktop_automation_used": False,
        "vortice_used": False,
    }


__all__ = ["REAL_RUST_PREVIEW_SAMPLES", "run_real_archive_rust_preview_smoke"]
