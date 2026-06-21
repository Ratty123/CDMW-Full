from __future__ import annotations

import re
from html import escape
from pathlib import Path
from typing import Mapping, Optional, Sequence

from cdmw.core.mod_package_retrofit import (
    RetrofitPathRepairSummary,
    RetrofittableModPackage,
    scan_retrofittable_mod_packages,
)


def read_retrofit_printable_file_text(raw_file: Path) -> str:
    try:
        payload = raw_file.read_bytes()[:2048]
    except OSError:
        return ""
    if raw_file.suffix.casefold() == ".paver" and len(payload) >= 4:
        major = int.from_bytes(payload[:2], "little")
        minor = int.from_bytes(payload[2:4], "little")
        if 0 < major <= 999 and 0 <= minor <= 999:
            return f"{major}.{minor}"
    decoded = payload.decode("utf-8", errors="ignore")
    ascii_match = re.search(r"\d+(?:\.\d+)?", decoded)
    if ascii_match:
        return ascii_match.group(0)

    if len(payload) >= 4:
        major = int.from_bytes(payload[:2], "little")
        minor = int.from_bytes(payload[2:4], "little")
        if 0 < major <= 999 and 0 <= minor <= 999:
            return f"{major}.{minor}"
        major = int.from_bytes(payload[:2], "big")
        minor = int.from_bytes(payload[2:4], "big")
        if 0 < major <= 999 and 0 <= minor <= 999:
            return f"{major}.{minor}"

    decoded_utf16 = payload.decode("utf-16", errors="ignore")
    utf16_match = re.search(r"\d+(?:\.\d+)?", decoded_utf16)
    if utf16_match:
        return utf16_match.group(0)

    return " ".join(" ".join(ch for ch in decoded if ch.isprintable()).split())


def retrofit_game_build_from_root(package_root: Path) -> str:
    candidate = package_root / "meta" / "0.paver"
    if candidate.is_file():
        return read_retrofit_printable_file_text(candidate)
    candidate = package_root / "0.paver"
    if candidate.is_file():
        return read_retrofit_printable_file_text(candidate)
    fallback = package_root / "meta" / "version.txt"
    if fallback.is_file():
        return read_retrofit_printable_file_text(fallback)
    return ""


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
    if not update_mode:
        if not summary.mappings:
            return (
                "No payloads",
                "No payload files were detected.",
                "#9ca3af",
            )
        return (
            "Repackage only",
            (
                "No current-game update is selected. Processing will preserve payload paths and rewrite "
                "metadata/package structure for the chosen mod manager profile."
            ),
            "#93c5fd",
        )
    if not summary.mappings:
        return (
            "No payloads",
            "No payload files were detected.",
            "#9ca3af",
        )
    if summary.unresolved_path_count > 0:
        label = (
            "No (manual fixes) "
            f"({summary.unresolved_path_count} unresolved, {summary.ambiguous_path_count} ambiguous)"
        )
        detail = (
            f"{summary.unresolved_path_count} payload path(s) still need manual repair and "
            f"{summary.repaired_path_count} path(s) can be auto-fixed."
        )
        return label, detail, "#fca5a5"
    if summary.ambiguous_path_count > 0:
        label = f"No (manual review) ({summary.ambiguous_path_count} ambiguous)"
        detail = (
            f"{summary.ambiguous_path_count} payload path(s) matched multiple archive paths; "
            f"{summary.repaired_path_count} path(s) can be auto-fixed."
        )
        return label, detail, "#fbbf24"
    if summary.repaired_path_count > 0:
        detail = "Package path repair can be done automatically; unchanged payload paths are reused where possible."
        if summary.binary_exact_mismatch_count > 0:
            detail = (
                "Package path repair can be done automatically. The scan also found "
                f"{summary.binary_exact_mismatch_count} payload(s) that differ byte-for-byte from current game entries."
                " That is normal for replacement mods, but file-internal edits are not merged."
            )
        return (
            f"Yes ({summary.repaired_path_count} path fix)",
            detail,
            "#86efac",
        )
    if summary.binary_exact_unknown_count > 0:
        label = (
            "No (manual review) "
            f"({summary.binary_exact_unknown_count} payload"
            f"{'s' if summary.binary_exact_unknown_count != 1 else ''} not comparable)"
        )
        detail = (
            "Some payload files could not be byte-compared against the loaded game archives. "
            f"{summary.binary_size_match_count} size matches, "
            f"{summary.binary_size_mismatch_count} size mismatches, "
            f"{summary.binary_exact_match_count} exact matches."
        )
        return label, detail, "#f59e0b"
    if summary.build_match_status in {"unknown_current", "unknown_package", "unknown"}:
        return (
            "No (manual review)",
            (
                "Build/version metadata could not be matched to the loaded game version. "
                "Payload comparison evidence is shown below, but this package still needs manual confirmation."
            ),
            "#fbbf24",
        )
    if summary.build_match_status == "mismatch":
        return (
            "No (build update needed)",
            (
                f"Package build ({summary.package_game_build or 'unknown'}) does not match "
                f"current game build ({summary.current_game_build or 'unknown'})."
            ),
            "#f59e0b",
        )
    if summary.build_match_status == "aligned":
        detail = "No path repair is needed; payloads are already using current game-relative paths."
        if summary.binary_exact_mismatch_count > 0:
            detail += (
                f" {summary.binary_exact_mismatch_count} payload(s) differ from vanilla current-game files, "
                "which is expected for replacement mods."
            )
    else:
        detail = (
            "No compact-path repairs are available from this scan; check build compatibility manually "
            "before testing in-game."
        )
    return (
        "No (already aligned)",
        detail,
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
    if not update_mode:
        if not summary.mappings:
            return "No payloads"
        return "Ready (retrofit)"
    return retrofit_readiness_for_summary(summary, update_mode=update_mode)[0]


def retrofit_comparison_detail_for_summary(
    summary: RetrofitPathRepairSummary,
    *,
    update_mode: bool,
) -> str:
    if not update_mode:
        return "Game-file compare disabled because Repackage only mode is selected."
    if not summary.mappings:
        return "No payload files were available to compare."
    if summary.binary_exact_mismatch_count > 0:
        return (
            f"{summary.binary_exact_mismatch_count} payload(s) differ from current game entries. "
            "This proves a payload difference, but it does not apply file-internal mod edits to a new 1.10 base file."
        )
    if summary.binary_exact_unknown_count > 0:
        if any(mapping.binary_status == "size_match" for mapping in summary.mappings):
            return (
                f"{summary.binary_size_match_count} payload(s) matched current game entry sizes. "
                "Exact byte compare is deferred to Preview Update Plan for selected packages."
            )
        return (
            f"{summary.binary_exact_unknown_count} payload(s) could not be compared against current game entries. "
            "Load or refresh the game archive index before trusting update status."
        )
    if summary.binary_exact_match_count > 0:
        return f"{summary.binary_exact_match_count} payload(s) match the current game entries byte-for-byte."
    return "No current-game payload comparison was available."


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
    if not update_mode:
        index_state = (
            "Repackage only mode is selected. The tool will not compare against current game files "
            "or try to repair for the latest game version."
        )
    elif archive_index_size:
        index_state = f"Using game archive index ({archive_index_size:,} basenames)."
    else:
        index_state = (
            "No game archive index is loaded. "
            "Without an index, compact-path changes cannot be safely proposed."
        )
    selected_summaries = [
        _summary_for_row(row, package_repair_summaries, summary_by_row)
        for row in rows
        if 0 <= row < len(package_repair_summaries)
    ]
    selection_counts = retrofit_summary_counts(selected_summaries)
    html_lines = [
        (
            "<h3 style=\"margin:0 0 8px 0;\">Update plan preview</h3>"
            if update_mode
            else "<h3 style=\"margin:0 0 8px 0;\">Repackage plan preview</h3>"
        ),
        "<p style=\"margin: 0 0 8px 0; color: #4b5563;\">"
        f"{escape(index_state)}"
        "</p>",
    ]
    if update_mode:
        html_lines.append(
            "<p style=\"margin: 0 0 8px 0;\">"
            f"<span style=\"color:#16a34a;\"><strong>Auto-fix:</strong> {selection_counts['auto']}</span> "
            f"| <span style=\"color:#f59e0b;\"><strong>Manual review:</strong> {selection_counts['partial']}</span> "
            f"| <span style=\"color:#f59e0b;\"><strong>Build update:</strong> {selection_counts['version']}</span> "
            f"| <span style=\"color:#ef4444;\"><strong>Payload differs:</strong> {selection_counts['binary']}</span> "
            f"| <span style=\"color:#fca5a5;\"><strong>Manual fixes:</strong> {selection_counts['manual']}</span> "
            f"| <span style=\"color:#93c5fd;\"><strong>Already aligned:</strong> {selection_counts['aligned']}</span>"
            "</p>"
        )

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
        unchanged_count = (
            len(summary.mappings)
            - summary.repaired_path_count
            - summary.unresolved_path_count
            - summary.ambiguous_path_count
        )
        planned_name = f"{package.name}_{profile}"
        output_path_text = "output directory not selected" if output_root is None else str(output_root / planned_name)

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
            f"<li><strong>Build:</strong> "
            f"{escape(summary.package_game_build or 'unknown')} -> "
            f"{escape(summary.current_game_build or 'unknown')}</li>"
            f"<li><strong>Archive size check:</strong> "
            f"match={summary.binary_size_match_count}, "
            f"mismatch={summary.binary_size_mismatch_count}, "
            f"unknown={summary.binary_size_unknown_count}</li>"
            f"<li><strong>Archive byte check:</strong> "
            f"match={summary.binary_exact_match_count}, "
            f"mismatch={summary.binary_exact_mismatch_count}, "
            f"unknown={summary.binary_exact_unknown_count}</li>"
            f"<li><strong>Game-file compare:</strong> "
            f"{escape(retrofit_comparison_detail_for_summary(summary, update_mode=update_mode))}</li>"
            f"<li><strong>Planned output:</strong> {escape(output_path_text)}</li>"
            f"<li><strong>Auto-fix:</strong> {summary.repaired_path_count}, "
            f"<span style='color:#f59e0b;'>manual review={summary.ambiguous_path_count}</span>, "
            f"<span style='color:#ef4444;'>unresolved={summary.unresolved_path_count}</span>, "
            f"<span style='color:#6b7280;'>unchanged={unchanged_count}</span></li>"
            f"<li><strong>Detail:</strong> {escape(readiness_detail)}</li>"
            "</ul>"
        )
        if not update_mode:
            html_lines.append(
                "<p style='margin: 0 0 2px 0; color:#6b7280;'>"
                "<strong>No update diff requested.</strong> Current-game path repair and payload compare are disabled for this operation."
                "</p>"
            )
            html_lines.append("</div>")
            continue

        mapping_rows: list[str] = []
        shown = 0
        for mapping in summary.mappings:
            if shown >= max_rows_per_package:
                break
            if mapping.status == "repaired":
                status_text = "auto-fix"
                color = "#16a34a"
                line = (
                    f"<li><span style='color:{color};'><strong>[{status_text}]</strong></span> "
                    f"{escape(mapping.source_path)} -> {escape(mapping.target_path or mapping.source_path)}"
                )
            elif mapping.status == "ambiguous":
                status_text = "manual review"
                color = "#f59e0b"
                line = (
                    f"<li><span style='color:{color};'><strong>[{status_text}]</strong></span> "
                    f"{escape(mapping.source_path)}"
                )
            elif mapping.status == "unresolved":
                status_text = "manual fix"
                color = "#ef4444"
                line = (
                    f"<li><span style='color:{color};'><strong>[{status_text}]</strong></span> "
                    f"{escape(mapping.source_path)}"
                )
            elif mapping.binary_status in {"size_mismatch", "mismatch"}:
                status_text = "payload differs"
                color = "#ef4444"
                line = (
                    f"<li><span style='color:{color};'><strong>[{status_text}]</strong></span> "
                    f"{escape(mapping.source_path)}"
                )
                if mapping.target_path and mapping.target_path.casefold() != mapping.source_path.casefold():
                    line += f" -> {escape(mapping.target_path)}"
            elif mapping.binary_status == "unknown":
                if not mapping.binary_note:
                    continue
                status_text = "binary not checked"
                color = "#6b7280"
                line = (
                    f"<li><span style='color:{color};'><strong>[{status_text}]</strong></span> "
                    f"{escape(mapping.source_path)} -> {escape(mapping.target_path or mapping.source_path)}"
                )
            else:
                continue

            if mapping.message:
                line += (
                    f"<br/><span style='color:#6b7280; margin-left: 18px;'>"
                    f"{escape(mapping.message)}</span>"
                )
            if mapping.binary_note:
                line += (
                    f"<br/><span style='color:#6b7280; margin-left: 18px;'>"
                    f"{escape(mapping.binary_note)}</span>"
                )
            line += "</li>"
            mapping_rows.append(line)
            shown += 1

        if mapping_rows:
            html_lines.append("<ul style='margin: 0 0 0 4px; padding-left: 18px;'>")
            if (
                unchanged_count
                and summary.repaired_path_count == 0
                and summary.ambiguous_path_count == 0
                and summary.unresolved_path_count == 0
            ):
                html_lines.append(
                    "<li><strong>No path conversions are needed.</strong> "
                    f"{unchanged_count} payload(s) already match target paths.</li>"
                )
            html_lines.extend(mapping_rows)
            if len(mapping_rows) == max_rows_per_package and len(summary.mappings) > len(mapping_rows):
                html_lines.append(
                    "<li><span style='color:#6b7280;'><em>... more mappings not shown.</em></span></li>"
                )
            html_lines.append("</ul>")
        elif summary.warnings:
            html_lines.append(
                "<p style='margin: 0 0 2px 0; color:#6b7280;'>"
                "<strong>No payload path conversions identified.</strong>"
                "</p>"
            )
        else:
            html_lines.append(
                "<p style='margin: 0 0 2px 0; color:#6b7280;'><strong>No payload path conversion is needed.</strong></p>"
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
    if not update_mode:
        return (
            "Repackage summary",
            f"Packages: {len(summaries)}; current-game update checks are disabled.",
        )
    counts = retrofit_summary_counts(summaries)
    parts = [
        f"{counts['auto']} Yes (auto-fix)",
        f"{counts['partial']} No (manual review)",
        f"{counts['version']} No (build update needed)",
        f"{counts['binary']} No (payload differs)",
        f"{counts['manual']} No (manual fixes)",
        f"{counts['aligned']} No (already aligned)",
    ]
    if counts["none"]:
        parts.append(f"{counts['none']} without payloads")
    return (
        "Scan summary",
        f"Packages: {len(summaries)}; " + ", ".join(parts),
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
    if not update_mode:
        return (
            f"Selected {len(selected_summaries)} package(s): repackage only. "
            "No current-game update check or latest-version repair will run."
        )
    counts = retrofit_summary_counts(selected_summaries)
    return (
        f"Selected {len(selected_summaries)} package(s): "
        f"{counts['auto']} Yes, {counts['partial']} No (review), {counts['version']} No (build updates), "
        f"{counts['binary']} No (payload differs), "
        f"{counts['manual']} No (manual fixes), {counts['aligned']} No (already aligned), "
        f"{counts['none']} no payloads"
    )


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
            summary_html += (
                "<li>"
                f"<span style=\"color:{status_color};\"><strong>[{escape(status_label)}]</strong></span> "
                f"<strong>{escape(package_name)}</strong><br/>"
                f"<span style=\"color:#6b7280;\">Output:</span> {escape(str(output_root))}<br/>"
                f"<span style=\"color:#16a34a;\">repaired={summary.repaired_path_count}</span>, "
                f"<span style=\"color:#f59e0b;\">ambiguous={summary.ambiguous_path_count}</span>, "
                f"<span style=\"color:#ef4444;\">unresolved={summary.unresolved_path_count}</span><br/>"
                f"<span style=\"color:#6b7280;\">size-check: match={summary.binary_size_match_count}, "
                f"mismatch={summary.binary_size_mismatch_count}, unknown={summary.binary_size_unknown_count}</span><br/>"
                f"<span style=\"color:#6b7280;\">byte-check: exact-match={summary.binary_exact_match_count}, "
                f"mismatch={summary.binary_exact_mismatch_count}, unknown={summary.binary_exact_unknown_count}</span><br/>"
                f"<span style=\"color:#6b7280;\">build:</span> "
                f"{escape(summary.package_game_build or 'unknown')} -> "
                f"{escape(summary.current_game_build or 'unknown')}<br/>"
                f"<span style=\"color:#6b7280;\">game-file compare:</span> "
                f"{escape(retrofit_comparison_detail_for_summary(summary, update_mode=update_mode))}<br/>"
                f"{escape(status_detail)}"
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
    "read_retrofit_printable_file_text",
    "retrofit_comparison_detail_for_summary",
    "retrofit_game_build_from_root",
    "retrofit_readiness_for_summary",
    "retrofit_readiness_label_for_summary",
    "retrofit_scan_readiness_summary",
    "retrofit_selection_readiness_summary",
    "retrofit_summary_counts",
]
