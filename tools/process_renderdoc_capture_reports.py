from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
import shutil
import subprocess
from typing import Any, Mapping, Sequence

from cdmw.rendering.renderdoc_truth_pass import normalize_renderdoc_truth_pass, summarize_truth_reports
from tools.analyze_renderdoc_capture_xml import summarize_renderdoc_capture_xml
from tools.correlate_renderdoc_dds_paths import _blob_hashes, correlate_resources_to_dds, scan_dds_corpus
from tools.export_renderdoc_candidate_truth import candidate_to_truth_input
from tools.extract_renderdoc_shader_blobs import extract_shader_blobs
from tools.locate_renderdoc_dispatch_truth_candidates import locate_dispatch_truth_candidates
from tools.locate_renderdoc_draw_truth_candidates import locate_draw_truth_candidates
from tools.report_crimson_normal_y_policy import build_normal_y_policy_report
from tools.report_crimson_shader_long_run_status import build_status_report
from tools.summarize_renderdoc_shader_bindings import summarize_shader_bindings


DEFAULT_RENDERDOCCMD = Path(".tools/renderdoc/1.44/RenderDoc_1.44_64/renderdoccmd.exe")


def find_renderdoccmd() -> Path:
    local = Path.cwd() / DEFAULT_RENDERDOCCMD
    if local.is_file():
        return local
    found = shutil.which("renderdoccmd")
    return Path(found) if found else Path()


def convert_capture_artifacts(
    rdc_path: Path,
    *,
    renderdoccmd: Path | None = None,
    output_prefix: Path | None = None,
    runner: Any = subprocess.run,
) -> dict[str, Any]:
    rdc = Path(rdc_path)
    rd = Path(renderdoccmd) if renderdoccmd else find_renderdoccmd()
    prefix = Path(output_prefix) if output_prefix else rdc.with_suffix("")
    xml_path = prefix.with_suffix(".zip")
    blob_zip = prefix
    thumbnail_path = prefix.with_name(f"{prefix.name}_thumb.jpg")
    blockers: list[str] = []
    if not rdc.is_file():
        blockers.append("rdc_not_found")
    if not rd.is_file():
        blockers.append("renderdoccmd_not_found")
    if blockers:
        return {"status": "blocked", "blockers": blockers, "capture_path": str(rdc), "renderdoccmd": str(rd)}

    thumbnail_path.parent.mkdir(parents=True, exist_ok=True)
    thumb_command = [str(rd), "thumb", "--out", str(thumbnail_path), str(rdc)]
    convert_command = [str(rd), "convert", "--filename", str(rdc), "--output", str(xml_path), "--convert-format", "zip.xml"]
    thumb = runner(thumb_command, check=False, capture_output=True, text=True, timeout=180)
    converted = runner(convert_command, check=False, capture_output=True, text=True, timeout=1800)
    status = "converted" if int(getattr(converted, "returncode", 1) or 0) == 0 and xml_path.is_file() and blob_zip.exists() else "blocked"
    return {
        "status": status,
        "blockers": [] if status == "converted" else ["renderdoc_convert_failed"],
        "capture_path": str(rdc),
        "renderdoccmd": str(rd),
        "thumbnail_path": str(thumbnail_path),
        "capture_xml": str(xml_path),
        "blob_zip": str(blob_zip),
        "commands": {"thumbnail": thumb_command, "convert": convert_command},
        "returncodes": {"thumbnail": int(getattr(thumb, "returncode", 1) or 0), "convert": int(getattr(converted, "returncode", 1) or 0)},
    }


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def _write_draw_csv(path: Path, report: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=["rank", "chunk_index", "pipeline_state", "index_count", "instance_count"])
        writer.writeheader()
        for candidate in report.get("candidates", []):
            if isinstance(candidate, Mapping):
                writer.writerow(
                    {
                        "rank": candidate.get("rank", ""),
                        "chunk_index": candidate.get("chunk_index", ""),
                        "pipeline_state": (candidate.get("state", {}) if isinstance(candidate.get("state"), Mapping) else {}).get("pipeline_state", ""),
                        "index_count": candidate.get("index_count", ""),
                        "instance_count": candidate.get("instance_count", ""),
                    }
                )


def _write_status_markdown(path: Path, report: Mapping[str, Any]) -> None:
    lines = ["# Crimson Shader Long-Run Status", "", f"Overall: {report.get('overall_status', '')}", ""]
    for item in report.get("plan_items", []):
        if isinstance(item, Mapping):
            lines.append(f"- {item.get('name')}: {item.get('status')}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _resource_ids(report: Mapping[str, Any]) -> set[str]:
    ids: set[str] = set()
    captures = report.get("captures", []) if isinstance(report.get("captures"), list) else [report]
    for capture in captures:
        if not isinstance(capture, Mapping):
            continue
        for srv in capture.get("srv_slots", []) or []:
            if isinstance(srv, Mapping) and str(srv.get("resource", "") or ""):
                ids.add(str(srv.get("resource", "")))
    return ids


def process_capture_reports(
    run_dir: Path,
    *,
    capture_xml: Path,
    blob_zip: Path,
    capture_path: Path | None = None,
    rank: int = 1,
    dds_root: Path | None = None,
    dxc: Path | None = None,
    scene_note: str = "",
) -> dict[str, Any]:
    run = Path(run_dir)
    reports = run / "reports"
    reports.mkdir(parents=True, exist_ok=True)

    xml_summary = summarize_renderdoc_capture_xml(capture_xml, scene_note=scene_note)
    _write_json(reports / "xml_summary.json", xml_summary)

    draw_candidates = locate_draw_truth_candidates(capture_xml)
    _write_json(reports / "draw_candidates.json", draw_candidates)
    _write_draw_csv(reports / "draw_candidates.csv", draw_candidates)

    dispatch_candidates = locate_dispatch_truth_candidates(capture_xml)
    _write_json(reports / "dispatch_candidates.json", dispatch_candidates)

    shader_blobs = extract_shader_blobs(
        draw_candidates,
        renderdoc_zip=blob_zip,
        out_dir=reports / "shader_blobs",
        ranks=(int(rank),),
        dxc=dxc,
    )
    _write_json(reports / "shader_blobs.json", shader_blobs)

    shader_bindings = summarize_shader_bindings([shader_blobs])
    _write_json(reports / "shader_binding_summary.json", shader_bindings)

    truth_input = candidate_to_truth_input(
        draw_candidates,
        rank=int(rank),
        capture_path=str(capture_path or capture_xml),
        shader_blob_manifest=shader_blobs,
    )
    truth_input_path = reports / f"truth_input_rank{int(rank)}.json"
    _write_json(truth_input_path, truth_input)

    normalized = normalize_renderdoc_truth_pass(truth_input)
    truth_report = {"schema_version": 1, "summary": summarize_truth_reports([normalized]), "captures": [normalized]}
    truth_report_path = reports / f"truth_report_rank{int(rank)}.json"
    _write_json(truth_report_path, truth_report)

    dds_correlation: dict[str, Any]
    if dds_root and Path(dds_root).exists():
        resource_hashes = _blob_hashes(capture_xml, blob_zip, _resource_ids(truth_report))
        dds_correlation = correlate_resources_to_dds([truth_report], scan_dds_corpus(Path(dds_root)), resource_blob_hashes=resource_hashes)
    else:
        dds_correlation = {"status": "blocked", "blocker": "dds_root_not_found", "dds_root": str(dds_root or "")}
    _write_json(reports / "dds_correlation.json", dds_correlation)

    normal_y_policy = build_normal_y_policy_report()
    _write_json(reports / "normal_y_policy.json", normal_y_policy)

    status = build_status_report(
        shader_binding_summary=shader_bindings,
        capture_reports=[truth_report],
        dds_correlation_summary=dds_correlation,
        normal_y_policy=normal_y_policy,
    )
    _write_json(reports / "status.json", status)
    _write_status_markdown(reports / "status.md", status)

    target_item = next((item for item in status.get("plan_items", []) if isinstance(item, Mapping) and item.get("name") == "renderdoc_target_material_selection"), {})
    return {
        "status": "capture_reports_processed",
        "run_dir": str(run),
        "rank": int(rank),
        "reports_dir": str(reports),
        "truth_report": str(truth_report_path),
        "target_material_selection": dict(target_item),
    }


def process_rdc_capture_reports(
    run_dir: Path,
    *,
    rdc_path: Path,
    renderdoccmd: Path | None = None,
    rank: int = 1,
    dds_root: Path | None = None,
    dxc: Path | None = None,
    scene_note: str = "",
) -> dict[str, Any]:
    conversion = convert_capture_artifacts(Path(rdc_path), renderdoccmd=renderdoccmd, output_prefix=Path(run_dir) / "capture" / Path(rdc_path).with_suffix("").name)
    if conversion.get("status") != "converted":
        return {"status": "blocked", "blocker": "renderdoc_conversion_failed", "conversion": conversion}
    report = process_capture_reports(
        Path(run_dir),
        capture_xml=Path(str(conversion["capture_xml"])),
        blob_zip=Path(str(conversion["blob_zip"])),
        capture_path=Path(rdc_path),
        rank=rank,
        dds_root=dds_root,
        dxc=dxc,
        scene_note=scene_note,
    )
    report["conversion"] = conversion
    return report


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--capture-xml", type=Path)
    parser.add_argument("--blob-zip", type=Path)
    parser.add_argument("--rdc", type=Path)
    parser.add_argument("--renderdoccmd", type=Path)
    parser.add_argument("--capture-path", type=Path)
    parser.add_argument("--rank", type=int, default=1)
    parser.add_argument("--dds-root", type=Path)
    parser.add_argument("--dxc", type=Path)
    parser.add_argument("--scene-note", default="")
    args = parser.parse_args(argv)
    capture_xml = args.capture_xml
    blob_zip = args.blob_zip
    capture_path = args.capture_path
    conversion: dict[str, Any] = {}
    if args.rdc:
        report = process_rdc_capture_reports(
            args.run_dir,
            rdc_path=args.rdc,
            renderdoccmd=args.renderdoccmd,
            rank=args.rank,
            dds_root=args.dds_root,
            dxc=args.dxc,
            scene_note=args.scene_note,
        )
        print(json.dumps(report, indent=2))
        if report.get("status") != "capture_reports_processed":
            return 2
        return 0
    if capture_xml is None or blob_zip is None:
        raise SystemExit("--capture-xml and --blob-zip required unless --rdc is supplied")
    report = process_capture_reports(
        args.run_dir,
        capture_xml=capture_xml,
        blob_zip=blob_zip,
        capture_path=capture_path,
        rank=args.rank,
        dds_root=args.dds_root,
        dxc=args.dxc,
        scene_note=args.scene_note,
    )
    if conversion:
        report["conversion"] = conversion
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
