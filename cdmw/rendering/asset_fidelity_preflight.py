from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import struct
import threading
from functools import lru_cache
from typing import Dict, Mapping


ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION = 1
_VERTEX_STRUCT = struct.Struct("<23f")
_VERTEX_STRIDE_BYTES = 23 * 4


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _main_thread_probe_allowed() -> bool:
    return threading.current_thread() is threading.main_thread()


@lru_cache(maxsize=64)
def _detect_executable_cached(names: tuple[str, ...], path_text: str, pathext_text: str) -> tuple[str, str]:
    search_paths = [Path(value) for value in path_text.split(os.pathsep) if value]
    extensions = [value.lower() for value in pathext_text.split(os.pathsep) if value]
    if os.name == "nt":
        extensions = [value.lower() for value in pathext_text.split(";") if value] or [".exe", ".bat", ".cmd"]
    for name in names:
        raw_name = str(name or "").strip()
        if not raw_name:
            continue
        candidates = [Path(raw_name)]
        if os.name == "nt" and not Path(raw_name).suffix:
            candidates.extend(Path(f"{raw_name}{extension}") for extension in extensions)
        for candidate in candidates:
            if candidate.is_absolute() and candidate.is_file():
                return "external_detected", str(candidate)
        for folder in search_paths:
            for candidate in candidates:
                path = folder / candidate
                if path.is_file():
                    return "external_detected", str(path)
    return "not_detected", ""


def _detect_executable(*names: str) -> Dict[str, object]:
    if not _main_thread_probe_allowed():
        return {"status": "not_detected", "path": ""}
    status, path = _detect_executable_cached(
        tuple(str(name or "").strip() for name in names),
        os.environ.get("PATH", ""),
        os.environ.get("PATHEXT", ""),
    )
    if path:
        return {"status": status, "path": path}
    return {"status": status, "path": ""}


def _module_available(name: str) -> bool:
    if not _main_thread_probe_allowed():
        return False
    return importlib.util.find_spec(name) is not None


def _existing_repo_tool(*relative_paths: str) -> str:
    if not _main_thread_probe_allowed():
        return ""
    root = _repo_root()
    for relative_path in relative_paths:
        path = root / relative_path
        if path.is_file():
            return str(path)
    return ""


def dds_encoder_compatibility_matrix() -> Dict[str, object]:
    compressonator = _detect_executable("compressonatorcli", "CompressonatorCLI", "compressonator")
    nvtt = _detect_executable("nvcompress", "nvtt_export", "nvtt_encode")
    ispc = _detect_executable("ispc_texcomp", "ispc_texcomp.exe")
    bc7enc = _detect_executable("bc7enc_rdo", "bc7enc")
    texconv_path = _existing_repo_tool(
        "native/cdmw_d3d11_preview/build/bin/Release/texconv.exe",
        "native/cd_texture_dx/build/bin/Release/texconv.exe",
        "native/cdmw_d3d11_preview/build/bin/Debug/texconv.exe",
        "native/cd_texture_dx/build/bin/Debug/texconv.exe",
    ) or _detect_executable("texconv").get("path", "")
    cd_texture_dx_path = _existing_repo_tool(
        "native/cd_texture_dx/build/Release/cd-texture-dx.exe",
        "native/cd_texture_dx/build/Debug/cd-texture-dx.exe",
    )
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "policy": "DirectXTex is bundled DDS writer authority; other encoders are report-only unless shipped in app",
        "backends": {
            "DirectXTex": {
                "status": "bundled",
                "path": texconv_path,
                "native_encoder_path": cd_texture_dx_path,
                "role": "dds_writer_authority",
                "formats": ["BC1", "BC2", "BC3", "BC4", "BC5", "BC6H", "BC7", "RGBA"],
                "header_dx10": "supported",
                "mips": "preserve_or_generate_by_existing_pipeline",
                "srgb": "format/view explicit",
                "alpha": "preserve by source/format policy",
                "likely_in_game_risks": [
                    "wrong SRGB variant",
                    "missing or mismatched mip chain",
                    "alpha mode mismatch",
                    "DX10 header mismatch for expected format",
                    "normal-map signedness/channel convention mismatch",
                ],
            },
            "Compressonator": {
                **compressonator,
                "bundled_feasibility": "not_bundled",
                "role": "comparison_only",
                "formats": ["BC1-BC7", "ASTC", "analysis/diff"],
                "header_dx10": "tool_option_dependent",
                "mips": "tool_option_dependent",
                "srgb": "tool_option_dependent",
                "alpha": "tool_option_dependent",
                "likely_in_game_risks": ["different BC7 mode choices", "header/mip defaults differ from DirectXTex"],
            },
            "NVTT": {
                **nvtt,
                "bundled_feasibility": "not_bundled",
                "role": "comparison_only",
                "formats": ["BC1-BC7", "ASTC"],
                "header_dx10": "option_dependent",
                "mips": "option_dependent",
                "srgb": "format_option_dependent",
                "alpha": "premultiply/alpha mode options need explicit policy",
                "likely_in_game_risks": ["CUDA/non-CUDA result variance", "DX10 header and alpha defaults"],
            },
            "ISPC Texture Compressor": {
                **ispc,
                "bundled_feasibility": "not_bundled",
                "role": "comparison_only",
                "formats": ["BC1", "BC3", "BC4", "BC5", "BC6H", "BC7"],
                "header_dx10": "caller_must_write_dds_header",
                "mips": "caller_must_supply",
                "srgb": "caller_must_choose_format/header",
                "alpha": "format_dependent",
                "likely_in_game_risks": ["encoder emits blocks only; DDS wrapper policy still critical"],
            },
            "bc7enc_rdo": {
                **bc7enc,
                "bundled_feasibility": "not_bundled",
                "role": "comparison_only",
                "formats": ["BC1", "BC3", "BC4", "BC5", "BC6H", "BC7"],
                "header_dx10": "caller_must_write_dds_header",
                "mips": "caller_must_supply",
                "srgb": "caller_must_choose_format/header",
                "alpha": "format_dependent",
                "likely_in_game_risks": ["RDO changes block error profile; header/mips remain separate risk"],
            },
        },
    }


def tangent_basis_report() -> Dict[str, object]:
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "active": "cdmw_fallback",
        "paths": {
            "cdmw_fallback": {
                "status": "bundled",
                "role": "MikkTSpace-style fallback tangent/binormal generator",
                "notes": "available for all preview imports; orthonormalizes tangent frames and preserves mirrored-UV handedness",
            },
            "MikkTSpace": {
                "status": "not_bundled",
                "role": "future_optional_validator",
                "package_safe": False,
                "notes": "standard tangent basis for normal maps; enable only when vendored/built safely",
            },
        },
    }


def import_preflight_report() -> Dict[str, object]:
    assimp = _detect_executable("assimp")
    ufbx = {"status": "python_module_detected" if _module_available("ufbx") else "not_detected", "path": ""}
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "policy": "validators/bridges only; not Crimson binary truth",
        "adapters": {
            "Assimp": {
                **assimp,
                "bundled_feasibility": "not_bundled",
                "role": "health_report_only",
                "checks": ["triangulation", "normals", "tangents", "degenerate cleanup", "broad format import/export"],
            },
            "ufbx": {
                **ufbx,
                "bundled_feasibility": "not_bundled",
                "role": "health_report_only",
                "checks": ["FBX skinning", "blend shapes", "embedded textures", "PBR material mapping"],
            },
        },
    }


def _safe_int(value: object, fallback: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError, OverflowError):
        return fallback


def _vertex_records_for_batch(package_dir: Path, batch: Mapping[str, object]) -> list[tuple[float, ...]]:
    vertex_file = str(batch.get("vertex_file", "") or "").strip()
    if not vertex_file:
        return []
    try:
        path = (package_dir / vertex_file).resolve()
        root = package_dir.resolve()
        if root not in path.parents and path != root:
            return []
        offset = max(0, _safe_int(batch.get("vertex_offset"), 0))
        size = max(0, _safe_int(batch.get("vertex_size"), 0))
        data = path.read_bytes()
    except OSError:
        return []
    if size <= 0:
        size = max(0, len(data) - offset)
    end = min(len(data), offset + size)
    records: list[tuple[float, ...]] = []
    for cursor in range(offset, end - (_VERTEX_STRIDE_BYTES - 1), _VERTEX_STRIDE_BYTES):
        try:
            records.append(_VERTEX_STRUCT.unpack_from(data, cursor))
        except struct.error:
            break
    return records


def _triangle_area2(a: tuple[float, ...], b: tuple[float, ...], c: tuple[float, ...]) -> float:
    ax, ay, az = a[0], a[1], a[2]
    bx, by, bz = b[0], b[1], b[2]
    cx, cy, cz = c[0], c[1], c[2]
    ab = (bx - ax, by - ay, bz - az)
    ac = (cx - ax, cy - ay, cz - az)
    cross = (
        ab[1] * ac[2] - ab[2] * ac[1],
        ab[2] * ac[0] - ab[0] * ac[2],
        ab[0] * ac[1] - ab[1] * ac[0],
    )
    return (cross[0] * cross[0]) + (cross[1] * cross[1]) + (cross[2] * cross[2])


def _mesh_batch_health(package_dir: Path | None, batch: Mapping[str, object]) -> Dict[str, object]:
    records = _vertex_records_for_batch(package_dir, batch) if package_dir is not None else []
    vertex_count = len(records) if records else _safe_int(batch.get("vertex_count"), 0)
    triangle_count = vertex_count // 3
    degenerate_triangles = 0
    duplicate_vertices = 0
    weld_candidate_positions = 0
    if records:
        full_keys: set[tuple[float, ...]] = set()
        position_buckets: Dict[tuple[float, float, float], int] = {}
        for record in records:
            full_key = tuple(round(float(value), 5) for value in record[:17])
            if full_key in full_keys:
                duplicate_vertices += 1
            full_keys.add(full_key)
            position_key = tuple(round(float(value), 5) for value in record[:3])
            position_buckets[position_key] = position_buckets.get(position_key, 0) + 1
        weld_candidate_positions = sum(count - 1 for count in position_buckets.values() if count > 1)
        for index in range(0, len(records) - 2, 3):
            if _triangle_area2(records[index], records[index + 1], records[index + 2]) <= 1e-12:
                degenerate_triangles += 1
    return {
        "batch": batch.get("index", 0),
        "vertex_count": vertex_count,
        "triangle_count": triangle_count,
        "missing_uv": not bool(batch.get("has_texture_coordinates", False)),
        "missing_tangents": not bool(batch.get("tangents_usable", False)),
        "degenerate_triangles": degenerate_triangles,
        "duplicate_vertices": duplicate_vertices,
        "weld_candidate_vertices": weld_candidate_positions,
        "simplify_candidate": bool(triangle_count >= 50000),
        "lod_candidate": bool(triangle_count >= 15000),
    }


def _color_space_health(manifest: Mapping[str, object] | None = None) -> Dict[str, object]:
    manifest = manifest if isinstance(manifest, Mapping) else {}
    batches = manifest.get("batches", ())
    srgb_slots = []
    unresolved = []
    if isinstance(batches, (tuple, list)):
        for batch in batches:
            if not isinstance(batch, Mapping):
                continue
            contract = batch.get("material_contract", {})
            slots = contract.get("texture_slots", {}) if isinstance(contract, Mapping) else {}
            normalized = contract.get("normalized_texture_slots", {}) if isinstance(contract, Mapping) else {}
            for slot_group in (slots, normalized):
                if not isinstance(slot_group, Mapping):
                    continue
                for slot_name, slot in slot_group.items():
                    if not isinstance(slot, Mapping) or str(slot.get("status", "") or "") == "missing":
                        continue
                    srgb_mode = str(slot.get("srgb_mode", "") or slot.get("sRGB", "") or slot.get("srgb", "") or "").strip()
                    record = {
                        "batch": batch.get("index", 0),
                        "slot": str(slot_name),
                        "srgb_mode": srgb_mode,
                        "authority": str(slot.get("authority", "") or ""),
                        "source_kind": str(slot.get("source_kind", "") or ""),
                    }
                    if srgb_mode:
                        srgb_slots.append(record)
                    elif str(slot_name) in {"base", "emissive", "normal", "material", "roughness", "metalness", "occlusion", "specular"}:
                        unresolved.append(record)
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "status": "builtin_report_only",
        "srgb_record_count": len(srgb_slots),
        "srgb_records": srgb_slots[:256],
        "unresolved_color_space_slots": unresolved[:256],
        "policy": "track sRGB/linear at slot/view boundary; DirectXTex remains DDS writer",
    }


def mesh_health_report(manifest: Mapping[str, object] | None = None, *, package_dir: Path | None = None) -> Dict[str, object]:
    manifest = manifest if isinstance(manifest, Mapping) else {}
    vertex_count = int(manifest.get("vertex_count", 0) or 0) if str(manifest.get("vertex_count", "0")).lstrip("-").isdigit() else 0
    face_count = int(manifest.get("face_count", 0) or 0) if str(manifest.get("face_count", "0")).lstrip("-").isdigit() else 0
    batches = manifest.get("batches", ())
    batch_count = len(tuple(batches)) if isinstance(batches, (tuple, list)) else 0
    missing_uv_batches = 0
    missing_tangent_batches = 0
    huge_texture_slots = []
    batch_health = []
    if isinstance(batches, (tuple, list)):
        for batch in batches:
            if not isinstance(batch, Mapping):
                continue
            if not bool(batch.get("has_texture_coordinates", False)):
                missing_uv_batches += 1
            if not bool(batch.get("tangents_usable", False)):
                missing_tangent_batches += 1
            texture_quality = batch.get("texture_quality")
            slots = texture_quality.get("slots", {}) if isinstance(texture_quality, Mapping) else {}
            if isinstance(slots, Mapping):
                for slot_name, slot in slots.items():
                    if isinstance(slot, Mapping) and bool(slot.get("source_exceeds_preview_cap", False)):
                        huge_texture_slots.append({"batch": batch.get("index", 0), "slot": str(slot_name)})
            batch_health.append(_mesh_batch_health(package_dir, batch))
    degenerate_triangles = sum(_safe_int(item.get("degenerate_triangles"), 0) for item in batch_health)
    duplicate_vertices = sum(_safe_int(item.get("duplicate_vertices"), 0) for item in batch_health)
    weld_candidate_vertices = sum(_safe_int(item.get("weld_candidate_vertices"), 0) for item in batch_health)
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "style": "meshoptimizer_gltf_transform_health_report",
        "status": "builtin_report_only",
        "vertex_count": vertex_count,
        "face_count": face_count,
        "batch_count": batch_count,
        "missing_uv_batches": missing_uv_batches,
        "missing_tangent_batches": missing_tangent_batches,
        "degenerate_triangles": degenerate_triangles,
        "duplicate_vertices": duplicate_vertices,
        "weld_candidate_vertices": weld_candidate_vertices,
        "huge_texture_slots": huge_texture_slots,
        "batches": batch_health[:512],
        "checks": [
            "stats",
            "missing UVs",
            "missing normals/tangents",
            "degenerate faces candidate",
            "duplicate/weld candidate",
            "huge textures",
            "LOD/simplify candidate",
        ],
        "external_backends": {
            "meshoptimizer": {"status": "not_bundled", "role": "future_optional"},
            "glTF-Transform": {"status": "not_bundled", "role": "future_optional"},
        },
    }


def image_color_preflight_report() -> Dict[str, object]:
    oiio = _detect_executable("oiiotool")
    ocio_available = _module_available("PyOpenColorIO") or _module_available("opencolorio")
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "policy": "DirectXTex remains DDS writer authority; OIIO/OCIO do not replace DDS output",
        "backends": {
            "OpenImageIO": {
                **oiio,
                "bundled_feasibility": "not_bundled",
                "role": "future_source_image_io",
                "dds_write": "not_used",
                "notes": "useful for high-bit/PSD/TIFF/TGA/EXR-ish source handling and batch image ops",
            },
            "OpenColorIO": {
                "status": "python_module_detected" if ocio_available else "not_detected",
                "path": "",
                "bundled_feasibility": "not_bundled",
                "role": "future_color_management",
                "notes": "helps prevent sRGB/linear/gamma drift in texture workflows",
            },
        },
    }


def normal_y_policy_report(d3d11_normal_y_mode: object = "asset") -> Dict[str, object]:
    requested_mode = str(d3d11_normal_y_mode or "asset").strip().lower() or "asset"
    if requested_mode == "force_flip":
        effective_preview_policy = "force_invert_normal_y"
    elif requested_mode == "force_no_flip":
        effective_preview_policy = "force_preserve_normal_y"
    else:
        effective_preview_policy = "asset_policy_inverts_green_up_for_directx_preview"
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "status": "app_policy_inferred",
        "normal_y_mode": "green_up_asset_inverted_for_directx_preview",
        "archive_source_normal_space": "green_up",
        "d3d11_normal_y_mode": requested_mode,
        "effective_preview_policy": effective_preview_policy,
        "authority": "corpus_and_app_policy_inferred",
        "renderdoc_authority": "unavailable_ags_replay_blocked",
        "evidence": {
            "archive_marks_normal_slots_green_up": True,
            "directxtex_preview_inverts_green_up_normals": True,
            "d3d11_asset_mode_inverts_normal_y_by_default": True,
        },
        "findings": [
            "renderdoc_normal_y_truth_unavailable_due_ags_replay_blocker",
            "force_flip_or_force_no_flip_can_A_B_visual_policy_until_replay_truth_available",
        ],
    }


def shader_truth_capture_backend_report() -> Dict[str, object]:
    renderdoc_path = _existing_repo_tool(
        ".tools/renderdoc/1.44/RenderDoc_1.44_64/renderdoccmd.exe",
        ".tools/renderdoc/RenderDoc_1.44_64/renderdoccmd.exe",
    ) or str(_detect_executable("renderdoccmd").get("path", ""))
    dxcompiler_path = _existing_repo_tool(
        ".tools/renderdoc/1.44/RenderDoc_1.44_64/plugins/d3d12/dxcompiler.dll",
        ".tools/renderdoc/RenderDoc_1.44_64/plugins/d3d12/dxcompiler.dll",
    )
    pix = _detect_executable("pixtool", "pixtool.exe", "PIX", "PIX.exe")
    rgp = _detect_executable("RadeonGPUProfiler", "RadeonGPUProfiler.exe", "RadeonDeveloperPanel", "RadeonDeveloperPanel.exe")
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "policy": "capture tools are truth sources only; no game bytecode execution in preview",
        "backends": {
            "RenderDoc": {
                "status": "bundled" if renderdoc_path else "not_detected",
                "path": renderdoc_path,
                "role": "primary_frame_capture_when_compatible",
                "shader_disassembly": {
                    "status": "bundled" if dxcompiler_path else "not_detected",
                    "path": dxcompiler_path,
                    "backend": "dxcompiler.dll",
                    "notes": "tools/extract_renderdoc_shader_blobs.py can call RenderDoc-bundled dxcompiler.dll headlessly on Windows",
                },
                "crimson_desert_notes": [
                    "AMD path needs AMD.ags.AllowUnknownExtensions=true for pre-launch D3D12 capture to pass E/load",
                    "Use --allow-amd-unknown-extensions and restore renderdoc.conf after launch",
                    "Avoid --opt-ref-all-resources on heavy scenes; observed E_OUTOFMEMORY during readback",
                    "Late injection does not attach to already-created D3D12 device reliably",
                ],
            },
            "PIX": {
                **pix,
                "role": "best_external_d3d12_shader_pipeline_fallback",
                "bundled_feasibility": "not_bundled",
                "notes": "GPU captures can inspect D3D12 events, state, shaders, resources, and hardware counters when installed",
            },
            "Radeon GPU Profiler": {
                **rgp,
                "role": "amd_timing_wavefront_profiler_not_material_slot_truth",
                "bundled_feasibility": "not_bundled",
                "notes": "useful after RenderDoc/PIX to validate AMD occupancy/timing; capture normally goes through Radeon Developer Panel",
            },
        },
    }


def renderdoc_truth_pass_report() -> Dict[str, object]:
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "status": "checklist_only",
        "replay_status": "ags_replay_blocked_for_current_crimson_capture",
        "policy": "capture game frame, inspect SRVs/samplers/CBs/PS disasm/SRGB views/normal Y/blend/raster, then tune registry",
        "capture_backends": shader_truth_capture_backend_report(),
        "offline_truth_supported": [
            "RenderDoc XML descriptor scan",
            "SRV/sampler/constant-buffer inventory",
            "shader disassembly extraction when blobs are present",
            "manual truth import from exported capture notes",
        ],
        "current_truth_gaps": [
            "capture DDS/path mapping unresolved because XML has no .dds names",
            "normal-Y truth unresolved because replay UI/pipeline inspection is blocked",
            "AGS replay blocked on current replay device; use PIX or compatible AMD replay environment for next truth pass",
        ],
    }


def _iter_mapping_items(value: object):
    if not isinstance(value, (list, tuple)):
        return
    for item in value:
        if isinstance(item, Mapping):
            yield item


def _bump_count(counts: Dict[str, int], value: object, fallback: str = "<none>") -> str:
    key = str(value or fallback).strip() or fallback
    counts[key] = int(counts.get(key, 0)) + 1
    return key


def _shader_record_sample(record: Mapping[str, object], *, batch_index: object, source: str) -> Dict[str, object]:
    return {
        "batch": batch_index,
        "source": source,
        "slot": str(record.get("slot", "") or ""),
        "status": str(record.get("status", "") or ""),
        "authority": str(record.get("authority", "") or ""),
        "source_kind": str(record.get("source_kind", "") or ""),
        "registry_source_kind": str(record.get("registry_source_kind", "") or ""),
        "disposition": str(record.get("disposition", "") or ""),
        "parameter_name": str(record.get("parameter_name", "") or ""),
        "source_dds_path": str(record.get("source_dds_path", "") or ""),
        "note": str(record.get("note", "") or record.get("reason", "") or ""),
    }


def shader_asset_fidelity_status(
    manifest: Mapping[str, object] | None = None,
    preflight: Mapping[str, object] | None = None,
) -> Dict[str, object]:
    manifest = manifest if isinstance(manifest, Mapping) else {}
    preflight = preflight if isinstance(preflight, Mapping) else {}
    batches = manifest.get("batches", ())
    authority_counts: Dict[str, int] = {}
    promotion_authority_counts: Dict[str, int] = {}
    disposition_counts: Dict[str, int] = {}
    unknown_samples: list[Dict[str, object]] = []
    unresolved_samples: list[Dict[str, object]] = []
    diagnostic_only_count = 0
    guess_promotions = 0
    material_count = 0

    if isinstance(batches, (list, tuple)):
        for batch_index, batch in enumerate(batches):
            if not isinstance(batch, Mapping):
                continue
            contract = batch.get("material_contract", {})
            if isinstance(contract, Mapping):
                material_count += 1
                for source_name in ("slot_diagnostics", "normalized_slot_diagnostics", "registry_decodes"):
                    for record in _iter_mapping_items(contract.get(source_name)) or ():
                        status = str(record.get("status", "") or "").strip().lower()
                        disposition = str(record.get("disposition", "") or "").strip().lower()
                        source_kind = str(record.get("source_kind", "") or record.get("registry_source_kind", "") or "").strip().lower()
                        authority = str(record.get("authority", "") or "").strip().lower()
                        parameter_name = str(record.get("parameter_name", "") or "").strip()
                        source_path = str(record.get("source_dds_path", "") or record.get("source_path", "") or "").strip()
                        if source_name == "registry_decodes" or status not in {"", "missing"}:
                            authority = _bump_count(authority_counts, authority, "guess")
                        if disposition:
                            _bump_count(disposition_counts, disposition)
                        if disposition in {"promoted", "recorded"}:
                            promoted_authority = _bump_count(promotion_authority_counts, authority or "guess", "guess")
                            if promoted_authority == "guess":
                                guess_promotions += 1
                        unknown = bool(
                            source_kind == "unknown_crimson_texture"
                            or (disposition == "diagnostic_only" and authority == "guess" and (parameter_name or source_path))
                        )
                        if disposition == "diagnostic_only":
                            diagnostic_only_count += 1
                        if unknown and len(unknown_samples) < 64:
                            unknown_samples.append(
                                _shader_record_sample(record, batch_index=batch.get("index", batch_index), source=source_name)
                            )

            channel_contract = batch.get("material_channel_contract", {})
            if isinstance(channel_contract, Mapping):
                for record in _iter_mapping_items(channel_contract.get("unresolved")) or ():
                    authority = _bump_count(authority_counts, record.get("authority", "guess"), "guess")
                    disposition = str(record.get("disposition", "") or "diagnostic_only").strip().lower()
                    _bump_count(disposition_counts, disposition)
                    if disposition == "diagnostic_only":
                        diagnostic_only_count += 1
                    if len(unresolved_samples) < 64:
                        unresolved_samples.append(
                            _shader_record_sample(record, batch_index=batch.get("index", batch_index), source="material_channel_contract.unresolved")
                        )
                    source_kind = str(record.get("source_kind", "") or "").strip().lower()
                    if (
                        source_kind == "unknown_crimson_texture"
                        or disposition == "diagnostic_only"
                        or str(record.get("authority", "") or "").strip().lower() == "guess"
                    ) and len(unknown_samples) < 64:
                        unknown_samples.append(
                            _shader_record_sample(record, batch_index=batch.get("index", batch_index), source="material_channel_contract.unresolved")
                        )

    dds_matrix = preflight.get("dds_encoder_matrix", {})
    dds_backends = dds_matrix.get("backends", {}) if isinstance(dds_matrix, Mapping) else {}
    directxtex = dds_backends.get("DirectXTex", {}) if isinstance(dds_backends, Mapping) else {}
    external_detected = []
    report_only = []
    if isinstance(dds_backends, Mapping):
        for name, backend in dds_backends.items():
            if name == "DirectXTex" or not isinstance(backend, Mapping):
                continue
            report_only.append(str(name))
            if str(backend.get("status", "") or "") in {"external_detected", "python_module_detected"}:
                external_detected.append(str(name))

    normal_y = preflight.get("normal_y_policy", {})
    renderdoc = preflight.get("renderdoc_truth_pass", {})
    unknown_count = len(unknown_samples)
    unresolved_count = len(unresolved_samples)
    status = "needs_capture_truth" if unknown_count or guess_promotions else "registry_covered"
    ui_summary = [
        "Shader authority: "
        + ", ".join(
            f"{name}={int(authority_counts.get(name, 0))}"
            for name in ("authoritative", "sidecar", "capture_inferred", "guess")
        ),
        f"Unknown Crimson packed maps: {unknown_count} diagnostic-only; policy=unresolved_diagnostic",
        (
            "DDS preflight: DirectXTex="
            + str(directxtex.get("status", "unknown") if isinstance(directxtex, Mapping) else "unknown")
            + f"; report-only backends={len(report_only)}"
            + (f"; detected={','.join(external_detected)}" if external_detected else "")
        ),
        (
            "Normal Y: "
            + str(normal_y.get("normal_y_mode", "") if isinstance(normal_y, Mapping) else "")
            + "; mode="
            + str(normal_y.get("d3d11_normal_y_mode", "") if isinstance(normal_y, Mapping) else "")
        ),
        (
            "RenderDoc truth: "
            + str(renderdoc.get("replay_status", renderdoc.get("status", "")) if isinstance(renderdoc, Mapping) else "")
            + "; DDS paths/normal-Y capture truth unresolved"
        ),
    ]
    return {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "status": status,
        "material_count": material_count,
        "authority_counts": authority_counts,
        "promotion_authority_counts": promotion_authority_counts,
        "disposition_counts": disposition_counts,
        "guess_promotion_count": guess_promotions,
        "diagnostic_only_count": diagnostic_only_count,
        "unknown_crimson_map_count": unknown_count,
        "unknown_crimson_map_policy": "unresolved_diagnostic",
        "unknown_crimson_map_samples": unknown_samples,
        "unresolved_material_channel_count": unresolved_count,
        "unresolved_material_channel_samples": unresolved_samples,
        "dds_preflight_summary": {
            "directxtex_status": str(directxtex.get("status", "") if isinstance(directxtex, Mapping) else ""),
            "directxtex_role": str(directxtex.get("role", "") if isinstance(directxtex, Mapping) else ""),
            "report_only_backends": report_only,
            "external_detected_backends": external_detected,
        },
        "normal_y_policy": dict(normal_y) if isinstance(normal_y, Mapping) else {},
        "renderdoc_truth_status": {
            "status": str(renderdoc.get("status", "") if isinstance(renderdoc, Mapping) else ""),
            "replay_status": str(renderdoc.get("replay_status", "") if isinstance(renderdoc, Mapping) else ""),
            "current_truth_gaps": list(renderdoc.get("current_truth_gaps", ()) if isinstance(renderdoc, Mapping) else ()),
        },
        "ui_summary": ui_summary,
    }


def asset_fidelity_preflight_manifest(manifest: Mapping[str, object] | None = None, *, package_dir: Path | None = None) -> Dict[str, object]:
    manifest = manifest if isinstance(manifest, Mapping) else {}
    mesh_package_dir = package_dir if _main_thread_probe_allowed() else None
    preflight = {
        "schema_version": ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION,
        "dds_encoder_matrix": dds_encoder_compatibility_matrix(),
        "tangent_basis": tangent_basis_report(),
        "import_validators": import_preflight_report(),
        "mesh_health": mesh_health_report(manifest, package_dir=mesh_package_dir),
        "image_color": {
            **image_color_preflight_report(),
            "color_space_health": _color_space_health(manifest),
        },
        "normal_y_policy": normal_y_policy_report(manifest.get("d3d11_normal_y_mode", "asset")),
        "renderdoc_truth_pass": renderdoc_truth_pass_report(),
    }
    preflight["shader_asset_fidelity_status"] = shader_asset_fidelity_status(manifest, preflight)
    return preflight


__all__ = [
    "ASSET_FIDELITY_PREFLIGHT_SCHEMA_VERSION",
    "asset_fidelity_preflight_manifest",
    "dds_encoder_compatibility_matrix",
    "image_color_preflight_report",
    "import_preflight_report",
    "mesh_health_report",
    "normal_y_policy_report",
    "renderdoc_truth_pass_report",
    "shader_asset_fidelity_status",
    "shader_truth_capture_backend_report",
    "tangent_basis_report",
]
