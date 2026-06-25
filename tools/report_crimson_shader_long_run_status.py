from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Mapping, Sequence


STATUS_COMPLETE = "complete"
STATUS_PARTIAL = "partial"
STATUS_BLOCKED_EXTERNAL = "blocked_external"
TARGET_MATERIAL_TERMS = ("sword", "weapon", "blade", "gear", "armor", "character", "player", "cloth", "hair")


def _captures(reports: Sequence[Mapping[str, Any]] | None) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    for report in reports or []:
        if isinstance(report.get("captures"), list):
            output.extend(item for item in report["captures"] if isinstance(item, Mapping))
        else:
            output.append(report)
    return output


def _resolved_texture_path(value: object) -> bool:
    text = str(value or "")
    return bool(text and ".dds" in text.lower() and not text.startswith("__"))


def _capture_quality(captures: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    srvs = [srv for capture in captures for srv in capture.get("srv_slots", []) if isinstance(srv, Mapping)]
    return {
        "resolved_srv_resource_paths": sum(1 for srv in srvs if _resolved_texture_path(srv.get("resource_path", srv.get("path", "")))),
        "resolved_srv_resource_ids": sum(1 for srv in srvs if str(srv.get("resource", ""))),
        "named_srv_resources": sum(1 for srv in srvs if str(srv.get("resource_name", ""))),
        "initial_descriptor_srv_count": sum(1 for srv in srvs if srv.get("source") == "initial_contents_descriptor"),
    }


def _truth_complete(capture: Mapping[str, Any]) -> bool:
    return bool(
        capture.get("srv_slots")
        and capture.get("sampler_states")
        and capture.get("constant_buffers")
        and (capture.get("pixel_shader", {}).get("disassembly_path") or capture.get("pixel_shader", {}).get("disassembly") or capture.get("compute_shader", {}).get("disassembly_path"))
        and capture.get("texture_srgb_views")
        and capture.get("normal_y_mode")
        and (capture.get("blend_state") or capture.get("dispatch_groups"))
        and (capture.get("raster_state") or capture.get("dispatch_groups"))
    )


def _target_material_evidence(captures: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    observed: list[dict[str, Any]] = []
    matched: list[dict[str, Any]] = []
    family_counts: dict[str, int] = {}
    for capture in captures:
        material = str(capture.get("material_name", "") or "")
        family = str(capture.get("shader_family", "") or "")
        drawcall = str(capture.get("drawcall", "") or "")
        fragments = [material, family, drawcall]
        for srv in capture.get("srv_slots", []) or []:
            if isinstance(srv, Mapping):
                fragments.extend(str(srv.get(key, "") or "") for key in ("name", "resource_name", "resource_path", "parameter_name"))
        haystack = " ".join(fragments).lower()
        terms = sorted({term for term in TARGET_MATERIAL_TERMS if term in haystack})
        row = {"material_name": material, "shader_family": family, "drawcall": drawcall}
        observed.append(row)
        if family:
            family_counts[family] = family_counts.get(family, 0) + 1
        if terms:
            matched.append({**row, "matched_terms": terms})
    return {
        "target_terms": list(TARGET_MATERIAL_TERMS),
        "capture_count": len(captures),
        "matched_capture_count": len(matched),
        "matched_captures": matched,
        "observed_captures": observed,
        "observed_shader_families": [{"shader_family": key, "count": value} for key, value in sorted(family_counts.items())],
    }


def build_status_report(
    *,
    extract_manifest: Mapping[str, Any] | None = None,
    audit_summary: Mapping[str, Any] | None = None,
    dds_summary: Mapping[str, Any] | None = None,
    material_profile_summary: Mapping[str, Any] | None = None,
    shader_binding_summary: Mapping[str, Any] | None = None,
    capture_artifacts: Sequence[Mapping[str, Any]] | None = None,
    capture_reports: Sequence[Mapping[str, Any]] | None = None,
    dds_correlation_summary: Mapping[str, Any] | None = None,
    normal_y_policy: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    captures = _captures(capture_reports)
    blocking: list[str] = []
    plan_items: list[dict[str, Any]] = [
        {"name": "sidecar_material_extract", "status": STATUS_COMPLETE if (extract_manifest or {}).get("sidecar_entries_selected", 0) else STATUS_PARTIAL, "evidence": dict(extract_manifest or {})},
        {"name": "material_profile_summary", "status": STATUS_COMPLETE if (material_profile_summary or {}).get("material_profile_rows", 0) else STATUS_PARTIAL, "evidence": dict(material_profile_summary or {})},
    ]
    quality = _capture_quality(captures)
    if any(_truth_complete(capture) for capture in captures):
        capture_status = STATUS_COMPLETE
    elif captures or capture_artifacts:
        capture_status = STATUS_PARTIAL
    else:
        capture_status = STATUS_BLOCKED_EXTERNAL
        blocking.append("renderdoc_truth_pass")
    plan_items.append(
        {
            "name": "renderdoc_truth_pass",
            "status": capture_status,
            "evidence": {"capture_quality": quality, "artifact_count": len(capture_artifacts or ()), "capture_report_count": len(captures)},
        }
    )
    target_evidence = _target_material_evidence(captures)
    if target_evidence["matched_capture_count"]:
        target_status = STATUS_COMPLETE
    elif captures or capture_artifacts:
        target_status = STATUS_PARTIAL
    else:
        target_status = STATUS_BLOCKED_EXTERNAL
    plan_items.append(
        {
            "name": "renderdoc_target_material_selection",
            "status": target_status,
            "evidence": target_evidence,
        }
    )
    if shader_binding_summary:
        plan_items.append(
            {
                "name": "renderdoc_shader_binding_summary",
                "status": STATUS_COMPLETE if int(shader_binding_summary.get("blob_count", 0) or 0) else STATUS_PARTIAL,
                "evidence": {
                    "blob_count": shader_binding_summary.get("blob_count", 0),
                    "top_bindless_spaces": list(shader_binding_summary.get("bindless_spaces", []))[:8],
                    "dynamic_handle_spaces": list(shader_binding_summary.get("dynamic_handle_spaces", []))[:8],
                    "findings": list(shader_binding_summary.get("findings", [])),
                },
            }
        )
    if dds_correlation_summary:
        plan_items.append(
            {
                "name": "renderdoc_dds_path_correlation",
                "status": STATUS_PARTIAL if dds_correlation_summary.get("unique_high_confidence_count", 0) else STATUS_BLOCKED_EXTERNAL,
                "evidence": dict(dds_correlation_summary),
            }
        )
    if normal_y_policy:
        plan_items.append(
            {
                "name": "normal_y_policy_inference",
                "status": STATUS_COMPLETE if normal_y_policy.get("normal_y_mode") else STATUS_PARTIAL,
                "evidence": dict(normal_y_policy),
            }
        )
    return {
        "schema_version": 1,
        "overall_status": STATUS_COMPLETE if all(item["status"] == STATUS_COMPLETE for item in plan_items) else STATUS_PARTIAL,
        "blocking_items": blocking,
        "plan_items": plan_items,
        "inputs": {
            "audit_summary": dict(audit_summary or {}),
            "dds_summary": dict(dds_summary or {}),
        },
    }


def _read(path: Path | None) -> Mapping[str, Any]:
    return json.loads(path.read_text(encoding="utf-8")) if path else {}


def _write_markdown(path: Path, report: Mapping[str, Any]) -> None:
    lines = ["# Crimson Shader Long-Run Status", "", f"Overall: {report.get('overall_status', '')}", ""]
    for item in report.get("plan_items", []):
        lines.append(f"- {item.get('name')}: {item.get('status')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract-manifest", type=Path)
    parser.add_argument("--audit-summary", type=Path)
    parser.add_argument("--dds-summary", type=Path)
    parser.add_argument("--material-profile-summary", type=Path)
    parser.add_argument("--shader-binding-summary", type=Path)
    parser.add_argument("--capture-report", type=Path, action="append")
    parser.add_argument("--dds-correlation-summary", type=Path)
    parser.add_argument("--normal-y-policy", type=Path)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--out-md", type=Path)
    args = parser.parse_args(argv)
    report = build_status_report(
        extract_manifest=_read(args.extract_manifest),
        audit_summary=_read(args.audit_summary),
        dds_summary=_read(args.dds_summary),
        material_profile_summary=_read(args.material_profile_summary),
        shader_binding_summary=_read(args.shader_binding_summary),
        capture_reports=[_read(path) for path in args.capture_report or []],
        dds_correlation_summary=_read(args.dds_correlation_summary),
        normal_y_policy=_read(args.normal_y_policy),
    )
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, indent=2), encoding="utf-8")
    if args.out_md:
        _write_markdown(args.out_md, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
