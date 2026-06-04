from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path
from typing import Any, Mapping

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from cdmw.rendering.asset_fidelity_preflight import asset_fidelity_preflight_manifest
from cdmw.rendering.crimson_shader_registry import registry_manifest


STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_REPORT_ONLY = "report_only"
STATUS_BLOCKED_EXTERNAL = "blocked_external"
STATUS_MISSING = "missing"


def _read_json(path: Path | None) -> Any:
    if path is None or not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError):
        return None


def _ratio(numerator: object, denominator: object) -> float:
    try:
        den = float(denominator or 0)
        if den <= 0:
            return 0.0
        return float(numerator or 0) / den
    except (TypeError, ValueError, ZeroDivisionError):
        return 0.0


def _sequence(value: object) -> list[object]:
    return list(value) if isinstance(value, (list, tuple)) else []


def _as_mapping(value: object) -> Mapping[str, object]:
    return value if isinstance(value, Mapping) else {}


def _nonempty_mapping_sequence(value: object) -> list[Mapping[str, object]]:
    if not isinstance(value, (list, tuple)):
        return []
    return [item for item in value if isinstance(item, Mapping)]


def _truth_captures(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    captures = _nonempty_mapping_sequence(report.get("captures", ()))
    return captures or [report]


def _has_text(value: object) -> bool:
    return bool(str(value or "").strip())


def _texture_path_like(value: object) -> bool:
    text = str(value or "").strip().replace("\\", "/").lower()
    if not text:
        return False
    if text.startswith("__") or text.startswith("g_"):
        return False
    return any(text.endswith(suffix) for suffix in (".dds", ".png", ".tga", ".tif", ".tiff", ".exr", ".jpg", ".jpeg", ".bmp", ".psd"))


def _capture_quality(capture_reports: list[Mapping[str, object]]) -> dict[str, object]:
    captures = [capture for report in capture_reports for capture in _truth_captures(report)]
    srv_slots = [slot for capture in captures for slot in _nonempty_mapping_sequence(capture.get("srv_slots", ()))]
    sampler_states = [sampler for capture in captures for sampler in _nonempty_mapping_sequence(capture.get("sampler_states", ()))]
    constant_buffers = [buffer for capture in captures for buffer in _nonempty_mapping_sequence(capture.get("constant_buffers", ()))]
    srgb_views = [
        view
        for capture in captures
        for view in _nonempty_mapping_sequence(capture.get("texture_srgb_views", ()))
        if view.get("srgb_view", "") != ""
    ]
    resolved_srvs = [
        slot
        for slot in srv_slots
        if _texture_path_like(slot.get("resource_path", slot.get("path", slot.get("dds_path", slot.get("source_path", "")))))
    ]
    resource_id_srvs = [
        slot
        for slot in srv_slots
        if _has_text(slot.get("resource", slot.get("resource_id", "")))
    ]
    named_resource_srvs = [
        slot
        for slot in srv_slots
        if _has_text(slot.get("resource_name", slot.get("object_name", "")))
        or (
            isinstance(slot.get("resource_desc", {}), Mapping)
            and _has_text(slot.get("resource_desc", {}).get("name", ""))
        )
    ]
    descriptor_srvs = [
        slot
        for slot in srv_slots
        if str(slot.get("source", "")).startswith("initial_contents_descriptor")
    ]
    normal_y_captures = [capture for capture in captures if _has_text(capture.get("normal_y_mode", capture.get("normal_y", "")))]
    blend_captures = [capture for capture in captures if isinstance(capture.get("blend_state", {}), Mapping) and bool(capture.get("blend_state", {}))]
    raster_captures = [capture for capture in captures if isinstance(capture.get("raster_state", {}), Mapping) and bool(capture.get("raster_state", {}))]
    pixel_disasm = [capture for capture in captures if _has_shader_disassembly(capture, "pixel_shader")]
    compute_disasm = [capture for capture in captures if _has_shader_disassembly(capture, "compute_shader")]
    findings = list(
        dict.fromkeys(
            str(finding)
            for capture in captures
            for finding in _sequence(capture.get("findings", ()))
            if str(finding)
        )
    )
    material_truth_complete = bool(
        resolved_srvs
        and sampler_states
        and constant_buffers
        and pixel_disasm
        and srgb_views
        and normal_y_captures
        and blend_captures
        and raster_captures
    )
    return {
        "report_count": len(capture_reports),
        "capture_count": len(captures),
        "srv_slot_count": len(srv_slots),
        "resolved_srv_resource_paths": len(resolved_srvs),
        "resolved_srv_resource_ids": len(resource_id_srvs),
        "named_srv_resources": len(named_resource_srvs),
        "initial_descriptor_srv_count": len(descriptor_srvs),
        "sampler_state_count": len(sampler_states),
        "constant_buffer_count": len(constant_buffers),
        "texture_srgb_view_count": len(srgb_views),
        "pixel_disassembly_count": len(pixel_disasm),
        "compute_disassembly_count": len(compute_disasm),
        "normal_y_count": len(normal_y_captures),
        "blend_state_count": len(blend_captures),
        "raster_state_count": len(raster_captures),
        "findings": findings[:32],
        "material_truth_complete": material_truth_complete,
    }


def _binding_summary_quality(shader_binding_summary: Mapping[str, object]) -> dict[str, object]:
    bindless_spaces = _nonempty_mapping_sequence(shader_binding_summary.get("bindless_spaces", ()))
    dynamic_spaces = _nonempty_mapping_sequence(shader_binding_summary.get("dynamic_handle_spaces", ()))
    top_bindless = bindless_spaces[:8]
    return {
        "blob_count": int(shader_binding_summary.get("blob_count") or 0),
        "bindless_space_count": len(bindless_spaces),
        "dynamic_handle_space_count": len(dynamic_spaces),
        "top_bindless_spaces": [
            {
                "type": row.get("type", ""),
                "space": row.get("space", ""),
                "hlsl_bind": row.get("hlsl_bind", ""),
                "shader_count": row.get("shader_count", 0),
                "names": row.get("names", [])[:4] if isinstance(row.get("names", []), list) else [],
            }
            for row in top_bindless
        ],
        "top_dynamic_handle_spaces": dynamic_spaces[:8],
        "findings": [
            str(item)
            for item in _sequence(shader_binding_summary.get("findings", ()))
            if str(item)
        ],
    }


def _has_shader_disassembly(capture: Mapping[str, object], shader_key: str) -> bool:
    shader = capture.get(shader_key, {})
    return isinstance(shader, Mapping) and (_has_text(shader.get("disassembly", "")) or _has_text(shader.get("disassembly_path", "")))


def _detect_renderdoc() -> dict[str, object]:
    path = shutil.which("renderdoccmd") or shutil.which("qrenderdoc")
    repo_root = Path(__file__).resolve().parents[1]
    candidates = [
        repo_root / ".tools" / "renderdoc" / "1.44" / "RenderDoc_1.44_64" / "renderdoccmd.exe",
        repo_root / ".tools" / "renderdoc" / "RenderDoc_1.44_64" / "renderdoccmd.exe",
        Path("C:/Program Files/RenderDoc/renderdoccmd.exe"),
        Path("C:/Program Files (x86)/RenderDoc/renderdoccmd.exe"),
    ]
    if not path:
        for candidate in candidates:
            if candidate.is_file():
                path = str(candidate)
                break
    return {
        "status": "detected" if path else "not_detected",
        "path": path or "",
        "capture_required": True,
    }


def _plan_item(name: str, status: str, evidence: Mapping[str, object] | None = None, note: str = "") -> dict[str, object]:
    return {
        "name": name,
        "status": status,
        "evidence": dict(evidence or {}),
        "note": note,
    }


def build_status_report(
    *,
    extract_manifest: Mapping[str, object] | None,
    audit_summary: Mapping[str, object] | None,
    dds_summary: Mapping[str, object] | None,
    material_profile_summary: Mapping[str, object] | None = None,
    renderdoc_capture_plan: Mapping[str, object] | None = None,
    shader_binding_summary: Mapping[str, object] | None = None,
    capture_reports: list[Mapping[str, object]] | None = None,
    capture_artifacts: list[Mapping[str, object]] | None = None,
    dds_correlation_summary: Mapping[str, object] | None = None,
    normal_y_policy: Mapping[str, object] | None = None,
) -> dict[str, object]:
    extract_manifest = dict(extract_manifest or {})
    audit_summary = dict(audit_summary or {})
    dds_summary = dict(dds_summary or {})
    material_profile_summary = dict(material_profile_summary or {})
    renderdoc_capture_plan = dict(renderdoc_capture_plan or {})
    shader_binding_summary = dict(shader_binding_summary or {})
    capture_reports = list(capture_reports or [])
    capture_artifacts = list(capture_artifacts or [])
    dds_correlation_summary = dict(dds_correlation_summary or {})
    normal_y_policy = dict(normal_y_policy or {})
    preflight = asset_fidelity_preflight_manifest({})
    registry = registry_manifest()
    renderdoc = _detect_renderdoc()

    sidecars = int(extract_manifest.get("sidecar_entries_selected") or 0)
    dds_refs = int(extract_manifest.get("dds_reference_rows") or 0)
    dds_selected = int(extract_manifest.get("dds_entries_selected") or 0)
    audit_rows = int(audit_summary.get("rows") or 0)
    unknown_rows = int(audit_summary.get("unknown_rows") or 0)
    unknown_ratio = _ratio(unknown_rows, audit_rows)
    dds_files = int(dds_summary.get("dds_files") or 0)
    dds_fatal = int(dds_summary.get("fatal_files") or 0)
    material_profile_rows = int(material_profile_summary.get("material_profile_rows") or 0)
    pso_rows = int(material_profile_summary.get("pso_rows") or 0)
    capture_quality = _capture_quality(capture_reports)
    binding_quality = _binding_summary_quality(shader_binding_summary)

    items: list[dict[str, object]] = []
    items.append(
        _plan_item(
            "read_only_shader_material_corpus_extract",
            STATUS_COMPLETE if sidecars > 0 else STATUS_MISSING,
            {
                "sidecar_entries_selected": sidecars,
                "dds_reference_rows": dds_refs,
                "dds_entries_selected": dds_selected,
                "sidecar_extract_skipped": bool(extract_manifest.get("sidecar_extract_skipped", False)),
            },
            "Archive source read-only; extracted payload stays local/ignored.",
        )
    )
    items.append(
        _plan_item(
            "shader_material_corpus_audit",
            STATUS_COMPLETE if audit_rows > 0 else STATUS_MISSING,
            {
                "rows": audit_rows,
                "dds_rows": audit_summary.get("dds_rows", 0),
                "top_families": audit_summary.get("families", [])[:8],
                "unknown_rows": unknown_rows,
                "unknown_ratio": round(unknown_ratio, 6),
            },
            "Audit emits slot authority/disposition; generic XML remains opt-in to avoid PSO noise.",
        )
    )
    items.append(
        _plan_item(
            "crimson_shader_registry",
            STATUS_COMPLETE if registry.get("families") and unknown_ratio < 0.01 else STATUS_PARTIAL,
            {
                "schema_version": registry.get("schema_version"),
                "families": [row.get("family") for row in registry.get("families", [])],
                "authority_values": registry.get("authority_values", []),
                "unknown_ratio": round(unknown_ratio, 6),
            },
            "Registry tuned from extracted corpus; unknown rows mostly scalar/placeholders.",
        )
    )
    items.append(
        _plan_item(
            "material_profiles_and_pso_declarations",
            STATUS_COMPLETE if material_profile_rows > 0 and pso_rows > 0 else STATUS_MISSING,
            {
                "material_profile_rows": material_profile_rows,
                "pso_rows": pso_rows,
                "top_material_families": material_profile_summary.get("material_families", [])[:8],
                "top_pso_families": material_profile_summary.get("pso_families", [])[:8],
                "top_pso_flags": material_profile_summary.get("pso_permutation_flags", [])[:16],
            },
            "Extracted game .material and pso_to_precompile declarations audited separately from sidecar instances.",
        )
    )
    items.append(
        _plan_item(
            "registry_first_material_resolution",
            STATUS_COMPLETE,
            {
                "policy": "authoritative/sidecar/capture_inferred before guess; unknown packed maps diagnostic",
            },
        )
    )
    items.append(
        _plan_item(
            "native_d3d11_shader_upgrade",
            STATUS_COMPLETE,
            {
                "pbr_terms": ["GGX", "Schlick Fresnel", "Smith geometry", "ACES-like tone map"],
            },
        )
    )
    items.append(
        _plan_item(
            "renderdoc_truth_pass",
            STATUS_COMPLETE
            if capture_quality.get("material_truth_complete")
            else (STATUS_PARTIAL if capture_reports or capture_artifacts or binding_quality.get("blob_count") else STATUS_BLOCKED_EXTERNAL),
            {
                "renderdoc": renderdoc,
                "capture_plan": renderdoc_capture_plan,
                "capture_artifacts": capture_artifacts,
                "capture_reports": len(capture_reports),
                "capture_quality": capture_quality,
            },
            "Complete only with resolved material SRVs, sampler states, constants, PS disasm, sRGB views, normal Y, blend/raster state.",
        )
    )
    items.append(
        _plan_item(
            "renderdoc_shader_binding_summary",
            STATUS_COMPLETE if binding_quality.get("blob_count") else STATUS_MISSING,
            binding_quality,
            "Disassembly proves bindless/dynamic indexing layout; resource-path truth still needs replay/UI mapping.",
        )
    )
    if dds_correlation_summary:
        unique_count = int(dds_correlation_summary.get("unique_high_confidence_count") or 0) + int(
            dds_correlation_summary.get("unique_medium_confidence_count") or 0
        )
        items.append(
            _plan_item(
                "renderdoc_dds_path_correlation",
                STATUS_PARTIAL if unique_count or int(dds_correlation_summary.get("matched_resource_count") or 0) else STATUS_MISSING,
                {
                    "dds_count": dds_correlation_summary.get("dds_count", 0),
                    "capture_resource_count": dds_correlation_summary.get("capture_resource_count", 0),
                    "matched_resource_count": dds_correlation_summary.get("matched_resource_count", 0),
                    "unique_high_confidence_count": dds_correlation_summary.get("unique_high_confidence_count", 0),
                    "unique_medium_confidence_count": dds_correlation_summary.get("unique_medium_confidence_count", 0),
                    "ambiguous_count": dds_correlation_summary.get("ambiguous_count", 0),
                    "unmatched_count": dds_correlation_summary.get("unmatched_count", 0),
                    "policy": dds_correlation_summary.get("policy", ""),
                },
                "Resource IDs are correlated against extracted DDS headers; this is not RenderDoc-authored path truth.",
            )
        )
    if normal_y_policy:
        items.append(
            _plan_item(
                "normal_y_policy_inference",
                STATUS_COMPLETE if normal_y_policy.get("status") == "inferred" else STATUS_PARTIAL,
                {
                    "normal_y_mode": normal_y_policy.get("normal_y_mode", ""),
                    "authority": normal_y_policy.get("authority", ""),
                    "renderdoc_authority": normal_y_policy.get("renderdoc_authority", ""),
                    "normal_rows": _as_mapping(normal_y_policy.get("audit", {})).get("normal_rows", 0),
                    "evidence": normal_y_policy.get("evidence", {}),
                },
                "Corpus/app policy evidence only; replay-authoritative normal Y still requires RenderDoc replay or visual A/B truth.",
            )
        )
    items.append(
        _plan_item(
            "dds_encoder_matrix_and_sample",
            STATUS_COMPLETE if dds_files > 0 else STATUS_PARTIAL,
            {
                "matrix": preflight.get("dds_encoder_matrix", {}),
                "dds_sample_files": dds_files,
                "fatal_files": dds_fatal,
                "format_counts": dds_summary.get("format_counts", [])[:12],
                "header_counts": dds_summary.get("header_counts", []),
            },
            "DirectXTex remains writer authority; external encoders are detect/report only unless shipped.",
        )
    )
    items.append(
        _plan_item(
            "mikk_assimp_ufbx_meshoptimizer_oiio_ocio_preflight",
            STATUS_REPORT_ONLY,
            {
                "tangent_basis": preflight.get("tangent_basis", {}),
                "import_preflight": preflight.get("import_preflight", {}),
                "mesh_health": preflight.get("mesh_health", {}),
                "image_color_preflight": preflight.get("image_color_preflight", {}),
            },
            "Dependency policy forbids user-side downloads; not bundled paths stay report-only.",
        )
    )

    blocking = [item for item in items if item.get("status") in {STATUS_BLOCKED_EXTERNAL, STATUS_MISSING}]
    partial = [item for item in items if item.get("status") == STATUS_PARTIAL]
    return {
        "schema_version": 1,
        "overall_status": STATUS_COMPLETE if not blocking and not partial else STATUS_PARTIAL,
        "blocking_items": [item["name"] for item in blocking],
        "plan_items": items,
    }


def write_markdown_report(report: Mapping[str, object], path: Path) -> None:
    lines = [
        "# Crimson Shader Long-Run Status",
        "",
        f"- Overall: `{report.get('overall_status', '')}`",
        f"- Blocking: `{', '.join(str(item) for item in report.get('blocking_items', []) or []) or 'none'}`",
        "",
        "| Item | Status | Note |",
        "| --- | --- | --- |",
    ]
    for item in report.get("plan_items", []) or []:
        if not isinstance(item, Mapping):
            continue
        lines.append(
            "| "
            + str(item.get("name", ""))
            + " | `"
            + str(item.get("status", ""))
            + "` | "
            + str(item.get("note", "")).replace("|", "\\|")
            + " |"
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Summarize Crimson shader long-run completion/blockers.")
    parser.add_argument("--extract-manifest", default="", help="JSON from extract_crimson_shader_corpus.py.")
    parser.add_argument("--audit-summary", default="", help="JSON summary from shader audit.")
    parser.add_argument("--dds-summary", default="", help="JSON summary from DDS sample inspection.")
    parser.add_argument("--material-profile-summary", default="", help="JSON from audit_crimson_material_profiles.py.")
    parser.add_argument("--renderdoc-capture-plan", default="", help="JSON from capture_crimson_renderdoc_frame.py.")
    parser.add_argument("--shader-binding-summary", default="", help="JSON from summarize_renderdoc_shader_bindings.py.")
    parser.add_argument("--dds-correlation-summary", default="", help="JSON from correlate_renderdoc_dds_paths.py.")
    parser.add_argument("--normal-y-policy", default="", help="JSON from report_crimson_normal_y_policy.py.")
    parser.add_argument("--renderdoc-capture-artifact", action="append", default=[], help="Optional JSON describing captured .rdc files.")
    parser.add_argument("--capture-report", action="append", default=[], help="Optional normalized RenderDoc truth report JSON.")
    parser.add_argument("--out-json", required=True, help="Output status JSON.")
    parser.add_argument("--out-md", default="", help="Optional Markdown report path.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    report = build_status_report(
        extract_manifest=_read_json(Path(args.extract_manifest)) if args.extract_manifest else None,
        audit_summary=_read_json(Path(args.audit_summary)) if args.audit_summary else None,
        dds_summary=_read_json(Path(args.dds_summary)) if args.dds_summary else None,
        material_profile_summary=_read_json(Path(args.material_profile_summary)) if args.material_profile_summary else None,
        renderdoc_capture_plan=_read_json(Path(args.renderdoc_capture_plan)) if args.renderdoc_capture_plan else None,
        shader_binding_summary=_read_json(Path(args.shader_binding_summary)) if args.shader_binding_summary else None,
        dds_correlation_summary=_read_json(Path(args.dds_correlation_summary)) if args.dds_correlation_summary else None,
        normal_y_policy=_read_json(Path(args.normal_y_policy)) if args.normal_y_policy else None,
        capture_reports=[
            payload
            for payload in (_read_json(Path(path)) for path in args.capture_report or [])
            if isinstance(payload, Mapping)
        ],
        capture_artifacts=[
            payload
            for payload in (_read_json(Path(path)) for path in args.renderdoc_capture_artifact or [])
            if isinstance(payload, Mapping)
        ],
    )
    out_json = Path(args.out_json)
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    if args.out_md:
        write_markdown_report(report, Path(args.out_md))
    print(f"wrote status report: {out_json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
