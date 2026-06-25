from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Mapping, Optional, Sequence

from cdmw.core.mod_package_retrofit import (
    RetrofitPathRepairSummary,
    RetrofittableModPackage,
    scan_retrofittable_mod_packages,
)


def collect_retrofittable_packages(source: Path) -> list[RetrofittableModPackage]:
    collected: list[RetrofittableModPackage] = []
    seen_roots: set[Path] = set()
    if not source.is_dir():
        for package in scan_retrofittable_mod_packages(source):
            if package.root not in seen_roots:
                collected.append(package)
                seen_roots.add(package.root)
        return collected

    skipped_dir_names = {
        "converted",
        "_archive",
        "retrofit_output",
        "converted_output",
    }

    def _should_skip_dir(path: Path) -> bool:
        name_lower = path.name.casefold()
        if name_lower in skipped_dir_names:
            return True
        if name_lower.startswith("retrofit_") or name_lower.startswith("converted_"):
            return True
        return False

    stack = [source]
    while stack:
        current = stack.pop()
        if not current.is_dir():
            continue
        current_packages = scan_retrofittable_mod_packages(current)
        for package in current_packages:
            if package.root not in seen_roots:
                collected.append(package)
                seen_roots.add(package.root)
        if len(current_packages) == 1 and current_packages[0].root == current:
            continue
        for child in sorted(current.iterdir(), key=lambda item: item.name.casefold()):
            if child.is_dir():
                if _should_skip_dir(child):
                    continue
                stack.append(child)
            elif child.is_file() and child.suffix.lower() == ".zip":
                package = scan_retrofittable_mod_packages(child)
                if package and package[0].root not in seen_roots:
                    collected.append(package[0])
                    seen_roots.add(package[0].root)

    return collected


def next_available_retrofit_package_name(
    package_name: str,
    profile: str,
    output_root: Path,
    suffixes: dict[str, int],
) -> str:
    base_key = f"{package_name}_{profile}"
    suffix = suffixes.get(base_key, 0)
    while True:
        candidate = package_name if suffix == 0 else f"{package_name}_{suffix}"
        target_root = output_root / f"{candidate}_{profile}"
        if not target_root.exists():
            suffixes[base_key] = suffix + 1
            return candidate
        suffix += 1


def retrofit_readiness_for_summary(
    summary: RetrofitPathRepairSummary,
    *,
    update_mode: bool,
) -> tuple[str, str, str]:
    if not summary.mappings:
        return (
            "No payloads",
            "No payload files were detected.",
            "#9ca3af",
        )
    return (
        "Ready (retrofit)",
        "Processing will preserve payload paths and rewrite metadata/package structure for the chosen manager profile.",
        "#93c5fd",
    )


def retrofit_summary_counts(summaries: Sequence[RetrofitPathRepairSummary]) -> dict[str, int]:
    counts = {
        "auto": 0,
        "partial": 0,
        "manual": 0,
        "aligned": 0,
        "binary": 0,
        "version": 0,
        "none": 0,
    }
    for summary in summaries:
        if not summary.mappings:
            counts["none"] += 1
            continue
        if summary.unresolved_path_count > 0:
            counts["manual"] += 1
        elif summary.ambiguous_path_count > 0:
            counts["partial"] += 1
        elif summary.repaired_path_count > 0:
            counts["auto"] += 1
        elif summary.binary_exact_unknown_count > 0:
            counts["partial"] += 1
        elif summary.build_match_status == "mismatch":
            counts["version"] += 1
        elif summary.build_match_status in {"unknown_current", "unknown_package", "unknown", ""}:
            counts["partial"] += 1
        elif summary.binary_exact_mismatch_count > 0:
            counts["binary"] += 1
        else:
            counts["aligned"] += 1
    return counts


def retrofit_readiness_label_for_summary(
    summary: RetrofitPathRepairSummary,
    *,
    update_mode: bool,
) -> str:
    if not summary.mappings:
        return "No payloads"
    return "Ready (retrofit)"


def retrofit_comparison_detail_for_summary(
    summary: RetrofitPathRepairSummary,
    *,
    update_mode: bool,
) -> str:
    if not summary.mappings:
        return "No payload files were detected."
    return "Payload paths will be preserved unless the selected manager profile requires a wrapper folder."


def _retrofit_plan_badge(label: str, color: str) -> str:
    return (
        f"<span style=\"background:{color}18; color:{color}; "
        "padding: 2px 7px; border-radius: 9px; border:1px solid "
        f"{color};\"><strong>{escape(label)}</strong></span>"
    )


def _summary_for_row(
    row: int,
    package_repair_summaries: Sequence[RetrofitPathRepairSummary],
    summary_by_row: Optional[Mapping[int, RetrofitPathRepairSummary]],
) -> RetrofitPathRepairSummary:
    if summary_by_row is not None and row in summary_by_row:
        return summary_by_row[row]
    return package_repair_summaries[row]


def build_retrofit_update_plan_html(
    rows: Sequence[int],
    *,
    packages: Sequence[RetrofittableModPackage],
    package_repair_summaries: Sequence[RetrofitPathRepairSummary],
    update_mode: bool,
    archive_index_size: int,
    profiles_by_row: Mapping[int, str],
    profile_labels: Mapping[str, str],
    output_root: Optional[Path] = None,
    max_rows_per_package: int = 18,
    summary_by_row: Optional[Mapping[int, RetrofitPathRepairSummary]] = None,
) -> str:
    if not rows:
        return "<p>No packages selected.</p>"
    html_lines = [
        "<h3 style=\"margin:0 0 8px 0;\">Package plan preview</h3>",
        "<p style=\"margin: 0 0 8px 0; color: #4b5563;\">"
        "Selected packages will be rewritten for their chosen manager profile."
        "</p>",
    ]

    for row in rows:
        if row < 0 or row >= len(packages):
            continue
        package = packages[row]
        summary = _summary_for_row(row, package_repair_summaries, summary_by_row)
        readiness_text, readiness_detail, readiness_color = retrofit_readiness_for_summary(
            summary,
            update_mode=update_mode,
        )
        profile = str(profiles_by_row.get(row, ""))
        profile_name = profile_labels.get(profile, profile)
        planned_name = f"{package.name}_{profile}"
        output_path_text = "output directory not selected" if output_root is None else str(output_root / planned_name)
        metadata_text = ", ".join(package.existing_metadata) or "-"

        html_lines.append("<div style='margin: 8px 0 12px 0;'>")
        html_lines.append(
            "<h4 style=\"margin: 0 0 4px 0;\">"
            f"{_retrofit_plan_badge(readiness_text, readiness_color)} "
            f"{escape(package.name)}"
            "</h4>"
        )
        html_lines.append(
            "<ul style='margin: 0 0 8px 8px; padding-left: 18px;'>"
            f"<li><strong>Profile:</strong> {escape(profile_name)} ({escape(profile)})</li>"
            f"<li><strong>Payload files:</strong> {len(package.payload_paths):,}</li>"
            f"<li><strong>Existing metadata:</strong> {escape(metadata_text)}</li>"
            f"<li><strong>Planned output:</strong> {escape(output_path_text)}</li>"
            f"<li><strong>Detail:</strong> {escape(readiness_detail)}</li>"
            "</ul>"
        )

        if summary.warnings:
            html_lines.append("<ul style='margin: 0 0 0 4px; padding-left: 18px;'>")
            for warning in summary.warnings[:5]:
                html_lines.append(
                    "<li>"
                    "<span style='color:#ef4444;'><strong>[warning]</strong></span> "
                    f"{escape(warning)}</li>"
                )
            if len(summary.warnings) > 5:
                html_lines.append(
                    f"<li><span style='color:#6b7280;'><em>... {len(summary.warnings) - 5} more warning(s)</em></span></li>"
                )
            html_lines.append("</ul>")
        html_lines.append("</div>")

    return "\n".join(html_lines)


def retrofit_scan_readiness_summary(
    *,
    package_count: int,
    summaries: Sequence[RetrofitPathRepairSummary],
    update_mode: bool,
) -> tuple[str, str]:
    if not summaries:
        if not package_count:
            return ("No packages", "Run Scan first to analyze mod folders.")
        return ("Ready", f"{package_count} package(s) found.")
    without_payloads = sum(1 for summary in summaries if not summary.mappings)
    payload_packages = len(summaries) - without_payloads
    return (
        "Repackage summary",
        f"Packages: {len(summaries)}; payload packages: {payload_packages}; without payloads: {without_payloads}.",
    )


def retrofit_selection_readiness_summary(
    rows: Sequence[int],
    *,
    summaries: Sequence[RetrofitPathRepairSummary],
    update_mode: bool,
) -> str:
    if not rows:
        return "No packages selected."
    selected_summaries = [summaries[row] for row in rows if 0 <= row < len(summaries)]
    if not selected_summaries:
        return "No packages selected."
    without_payloads = sum(1 for summary in selected_summaries if not summary.mappings)
    payload_packages = len(selected_summaries) - without_payloads
    return f"Selected {len(selected_summaries)} package(s): {payload_packages} ready, {without_payloads} without payloads."


def build_retrofit_processing_results_html(
    processed: Sequence[tuple[str, Path, RetrofitPathRepairSummary]],
    failed: Sequence[tuple[str, str]],
    *,
    update_mode: bool,
) -> str:
    processed_count = len(processed)
    failed_count = len(failed)
    summary_html = f"""
        <h3 style=\"margin:0 0 8px 0;\">Process summary</h3>
        <p style=\"margin: 0 0 10px 0;\">
          <span style=\"color:#16a34a;\"><strong>Processed:</strong> {processed_count}</span> &nbsp;|&nbsp;
          <span style=\"color:#ef4444;\"><strong>Failed:</strong> {failed_count}</span> &nbsp;|&nbsp;
          <span style=\"color:#6b7280;\"><strong>Selected:</strong> {processed_count + failed_count}</span>
        </p>
    """
    if processed:
        summary_html += "<h4 style=\"margin: 10px 0 4px 0;\">Successful</h4><ul style=\"margin: 0 0 2px 0; padding-left: 18px;\">"
        for package_name, output_root, summary in processed:
            status_label, status_detail, status_color = retrofit_readiness_for_summary(
                summary,
                update_mode=update_mode,
            )
            warnings = "".join(
                f"<br/><span style=\"color:#ef4444;\">warning:</span> {escape(warning)}"
                for warning in summary.warnings[:5]
            )
            summary_html += (
                "<li>"
                f"<span style=\"color:{status_color};\"><strong>[{escape(status_label)}]</strong></span> "
                f"<strong>{escape(package_name)}</strong><br/>"
                f"<span style=\"color:#6b7280;\">Output:</span> {escape(str(output_root))}<br/>"
                f"{escape(status_detail)}"
                f"{warnings}"
                "</li>"
            )
        summary_html += "</ul>"
    if failed:
        summary_html += "<h4 style=\"margin: 10px 0 4px 0; color: #dc2626;\">Failed</h4><ul style=\"margin: 0; padding-left: 18px;\">"
        for package_name, reason in failed:
            summary_html += (
                "<li>"
                f"<span style=\"color:#ef4444;\"><strong>[failed]</strong></span> "
                f"<strong>{escape(package_name)}</strong><br/>"
                f"{escape(reason)}"
                "</li>"
            )
        summary_html += "</ul>"
    if not processed and not failed:
        summary_html += "<p>No packages were processed.</p>"
    return summary_html


__all__ = [
    "build_retrofit_processing_results_html",
    "build_retrofit_update_plan_html",
    "collect_retrofittable_packages",
    "next_available_retrofit_package_name",
    "retrofit_comparison_detail_for_summary",
    "retrofit_readiness_for_summary",
    "retrofit_readiness_label_for_summary",
    "retrofit_scan_readiness_summary",
    "retrofit_selection_readiness_summary",
    "retrofit_summary_counts",
]
