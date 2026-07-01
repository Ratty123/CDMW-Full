"""Texture-row diagnostics HTML for static replacement planning."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from html import escape

from cdmw.core.final_package_preview import (
    TEXTURE_PLAN_STATUS_IGNORED_ADVANCED,
    TEXTURE_PLAN_STATUS_LIKELY_GREY,
    build_dds_override_table_row,
    simplified_part_label,
)
from cdmw.modding.material_replacer import is_shared_material_layer_texture
from cdmw.ui.archive_browser.static_replacement_dialog_helpers import (
    texture_context_chip_cell,
    texture_context_kv_row,
    texture_context_path_html,
    texture_plan_status_color,
    texture_slot_role_color,
    texture_status_text,
)


def texture_target_diagnostics_html(
    target_name: str,
    rows: Sequence[Mapping[str, object]],
    selected_row: Mapping[str, object] | None = None,
    *,
    texture_row_source_summary: Callable[[Mapping[str, object] | None], str],
    texture_row_is_assigned: Callable[[Mapping[str, object]], bool],
) -> str:
    if not rows:
        return (
            "<html><body style='color:#8b949e; background:#1f1f1f; font-size:0.9em;'>"
            "<p style='margin:5px;'>No sidecar texture rows were found for this target.</p>"
            "</body></html>"
        )

    selected_table_row = build_dds_override_table_row(selected_row) if selected_row is not None else None
    full_target = str(target_name or "Original DDS target")
    short_target = simplified_part_label(full_target)
    selected_source_summary = texture_row_source_summary(selected_row) if selected_row is not None else ""
    assigned_count = int(selected_row.get("_assigned_count", 0)) if selected_row is not None else sum(
        1
        for row_state in rows
        if bool(row_state.get("checked")) and str(row_state.get("source_path", "") or "").strip()
    )
    target_row_count = int(selected_row.get("_target_row_count", len(rows))) if selected_row is not None else len(rows)
    warnings: list[str] = []
    for row_state in rows:
        table_row = build_dds_override_table_row(row_state)
        role = table_row.role
        classification = row_state.get("classification")
        semantic_type = str(getattr(classification, "semantic_type", "") or "").lower()
        semantic_subtype = str(getattr(classification, "semantic_subtype", "") or "").lower()
        target_path = str(row_state.get("target_path", "") or "")
        if str(row_state.get("slot_kind", "") or "").strip().lower() == "base" and not bool(row_state.get("checked")):
            warnings.append(f"{role}: no replacement base/color is assigned. This will likely be grey if this slot is the visible color authority.")
        if semantic_type in {"mask", "roughness", "vector"} or "mask" in semantic_subtype:
            warnings.append(f"{role}: material/mask data can affect shine, metal, roughness, AO, blend, or surface response.")
        if not bool(getattr(classification, "visualized", False)):
            warnings.append(f"{role}: advanced shader slot; keep original unless you are intentionally repairing this binding.")
        if is_shared_material_layer_texture(target_path):
            warnings.append(f"{role}: shared/detail layer is intentionally not auto-enabled.")

    html_parts: list[str] = [
        "<html><body style='color:#e6edf3; background:#1f1f1f; font-size:0.8em; margin:0;'>",
        "<div style='padding:4px 5px; line-height:1.08;'>",
        "<table width='100%' cellspacing='0' cellpadding='0' style='background:#161b22; border:1px solid #30363d;'>",
        "<tr><td style='padding:4px 5px;'>",
        f"<div style='font-size:1em; font-weight:700; color:#f0f6fc;'>{escape(short_target)} "
        f"<span style='color:#8b949e;'>- {assigned_count}/{target_row_count} slot(s) assigned</span></div>",
        f"<div title='{escape(full_target)}' style='color:#8b949e; margin-top:1px; word-break:break-all;'>Original: {escape(short_target)}</div>",
        (
            f"<div style='color:#79c0ff; margin-top:1px; word-break:break-all;'>Affects: {escape(selected_source_summary)}</div>"
            if selected_source_summary
            else ""
        ),
        "</td></tr></table>",
    ]
    if selected_row is not None and selected_table_row is not None:
        status_label = selected_table_row.status.label
        status_color = texture_plan_status_color(status_label)
        status_foreground = "#ffffff" if status_label in {TEXTURE_PLAN_STATUS_LIKELY_GREY, TEXTURE_PLAN_STATUS_IGNORED_ADVANCED} else "#0d1117"
        source_path = str(selected_row.get("_contract_selected_source", "") or selected_row.get("source_path", "") or "").strip()
        contract_action = str(selected_row.get("_contract_action", "") or "").strip()
        contract_reason = str(selected_row.get("_contract_reason", "") or "").strip()
        source_color = "#238636" if source_path else "#30363d"
        source_foreground = "#ffffff" if source_path else "#f0f6fc"
        classification = selected_row.get("classification")
        guidance = selected_row.get("guidance")
        html_parts.extend(
            [
                "<div style='height:5px;'></div>",
                "<table width='100%' cellspacing='0' cellpadding='0' style='background:#10233a; border:1px solid #388bfd;'>",
                "<tr><td style='padding:4px 5px;'>",
                "<table cellspacing='0' cellpadding='0'><tr>",
                texture_context_chip_cell(selected_table_row.role, texture_slot_role_color(selected_row)),
                "<td width='4'></td>",
                texture_context_chip_cell(status_label, status_color, foreground=status_foreground),
                "<td width='4'></td>",
                texture_context_chip_cell("Assigned source" if source_path else "Keep original", source_color, foreground=source_foreground),
                "</tr></table>",
                "<table width='100%' cellspacing='0' cellpadding='0' style='margin-top:4px;'>",
                texture_context_kv_row("Parameter", escape(str(selected_row.get("parameter_name") or "(unnamed parameter)"))),
                texture_context_kv_row("Original DDS", texture_context_path_html(selected_row.get("target_path"))),
                texture_context_kv_row("Affects", escape(texture_row_source_summary(selected_row))),
                texture_context_kv_row("Override source", texture_context_path_html(source_path) if source_path else "<span style='color:#c9d1d9;'>Keep original</span>"),
                texture_context_kv_row(
                    "Final behavior",
                    escape(
                        f"{contract_action or texture_status_text(selected_row, assigned=texture_row_is_assigned(selected_row))}"
                        f"{': ' + contract_reason if contract_reason else ''}"
                    ),
                ),
                texture_context_kv_row("Virtual sidecar", texture_context_path_html(selected_row.get("_contract_final_output_dds") or selected_row.get("target_path"))),
                texture_context_kv_row("Controls", escape(selected_table_row.controls)),
                texture_context_kv_row("Shader", escape(str(selected_row.get("shader_family") or "unknown"))),
                texture_context_kv_row(
                    "Classification",
                    f"{escape(str(getattr(classification, 'semantic_type', '') or 'unknown'))} / "
                    f"{escape(str(getattr(classification, 'semantic_subtype', '') or 'generic'))}",
                ),
                texture_context_kv_row("Confidence", escape(str(selected_row.get("confidence") or "manual"))),
                texture_context_kv_row("Reason", escape(str(getattr(guidance, "reason", "") or getattr(classification, "reason", "") or ""))),
                "</table></td></tr></table>",
            ]
        )
    html_parts.extend(
        [
            "<div style='height:6px;'></div>",
            "<div style='font-weight:700; color:#f0f6fc; margin-bottom:3px;'>Original sidecar bindings</div>",
            "<table width='100%' cellspacing='0' cellpadding='2' style='border:1px solid #30363d; background:#161b22;'>",
            "<tr style='color:#8b949e; background:#24292f;'>"
            "<th align='left'>Role</th><th align='left'>Parameter</th><th align='left'>DDS</th><th align='left'>State</th></tr>",
        ]
    )
    for row_index, row_state in enumerate(rows):
        table_row = build_dds_override_table_row(row_state)
        status_label = table_row.status.label
        row_bg = "#161b22" if row_index % 2 == 0 else "#1c2128"
        state_text = str(row_state.get("_contract_action", "") or "").replace("_", " ").title()
        if not state_text:
            state_text = "Assigned" if bool(row_state.get("checked")) and str(row_state.get("source_path", "") or "").strip() else "Keep original"
        html_parts.append(
            f"<tr style='background:{row_bg};'>"
            f"<td style='color:{texture_slot_role_color(row_state)}; font-weight:700; white-space:nowrap;'>{escape(table_row.role)}</td>"
            f"<td style='color:#f2cc60;'>{escape(str(row_state.get('parameter_name') or '(unnamed parameter)'))}</td>"
            f"<td>{texture_context_path_html(row_state.get('target_path'))}</td>"
            f"<td style='color:{texture_plan_status_color(status_label)}; white-space:nowrap;'>{escape(state_text)}</td>"
            "</tr>"
        )
    html_parts.append("</table>")
    if warnings:
        html_parts.extend(
            [
                "<div style='height:6px;'></div>",
                "<div style='font-weight:700; color:#f0f6fc; margin-bottom:3px;'>Warnings</div>",
                "<table width='100%' cellspacing='0' cellpadding='3' style='border:1px solid #3d2f12; background:#2b2416;'>",
            ]
        )
        for warning in sorted(set(warnings)):
            html_parts.append(
                "<tr><td width='8' style='background:#d29922;'></td>"
                f"<td style='color:#f2cc60;'>{escape(warning)}</td></tr>"
            )
        html_parts.append("</table>")
    html_parts.append("</div></body></html>")
    return "".join(html_parts)


__all__ = ["texture_target_diagnostics_html"]
