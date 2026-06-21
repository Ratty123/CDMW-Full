"""Mesh import setup summary and placement helper UI."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path, PurePosixPath
from typing import Dict, List, Optional, Tuple

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QSizePolicy,
    QVBoxLayout,
)

from cdmw.core.archive import read_archive_entry_data
from cdmw.core.mesh_baseline import read_archive_entry_baseline_data
from cdmw.models import ArchiveEntry
from cdmw.modding.asset_replacement import ReplacementAssetProfile, analyze_replacement_asset
from cdmw.modding.mesh_parser import ParsedMesh, parse_mesh
from cdmw.modding.scene_importer import import_scene_mesh
from cdmw.modding.static_mesh_replacer import describe_static_placement_context
from cdmw.ui.archive_browser.mesh_import_setup_state import (
    mesh_import_compatibility_control_text as _mesh_import_compatibility_control_text,
)
from cdmw.ui.themes import get_theme
from cdmw.ui.widgets import CollapsibleSection


class ArchiveMeshSetupHelperMixin:
    """Mesh setup dialogs, placement summaries, and compatibility chips."""
    def _show_modify_original_workspace_ready_dialog(
        self,
        entry: ArchiveEntry,
        result: Mapping[str, object],
        ) -> None:
        workspace = result.get("workspace_dir")
        obj_path = result.get("obj_path")
        if not isinstance(workspace, Path) or not isinstance(obj_path, Path):
            return
        supplemental_files = tuple(
            path for path in result.get("supplemental_files", ()) if isinstance(path, Path)
        )
        output_paths = tuple(path for path in result.get("output_paths", ()) if isinstance(path, Path))
        dialog = QMessageBox(self)
        dialog.setIcon(QMessageBox.Information)
        dialog.setWindowTitle("Modify Original Workspace Ready")
        dialog.setText("Editable clone workspace created.")
        dialog.setInformativeText(
            f"OBJ clone:\n{obj_path}\n\n"
            f"Workspace:\n{workspace}\n\n"
            "Edit the OBJ or copied texture/material files, then import the edited clone to build a loose mod package."
        )
        detail_lines = [
            *(str(line) for line in result.get("summary_lines", ()) if str(line).strip()),
            "",
            f"Copied related file(s): {int(result.get('related_count') or 0):,}",
            f"Import supplemental file(s) detected: {len(supplemental_files):,}",
            "",
            "Exported files:",
            *(str(path) for path in output_paths[:40]),
        ]
        if len(output_paths) > 40:
            detail_lines.append(f"... {len(output_paths) - 40:,} more file(s)")
        dialog.setDetailedText("\n".join(detail_lines))
        import_button = dialog.addButton("Import Edited Clone...", QMessageBox.AcceptRole)
        open_button = dialog.addButton("Open Workspace", QMessageBox.ActionRole)
        dialog.addButton(QMessageBox.Close)
        dialog.setDefaultButton(import_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is open_button:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(workspace.resolve())))
            return
        if clicked is import_button:
            QTimer.singleShot(
                0,
                lambda current_entry=entry, payload=result: self._open_modify_original_mesh_setup(
                    current_entry,
                    payload,
                ),
            )

    def _prompt_archive_mesh_import_mode(self, entry: Optional[ArchiveEntry] = None) -> Optional[str]:
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Choose Mesh Import Mode")
        dialog.setIcon(QMessageBox.Question)
        dialog.setText("Choose how to import this mesh file.")
        compatibility_note = ""
        profile: Optional[ReplacementAssetProfile] = None
        if entry is not None:
            try:
                original_data = read_archive_entry_baseline_data(entry, read_entry_data=read_archive_entry_data).data
                profile = analyze_replacement_asset(
                    entry,
                    archive_entries_by_basename=self.archive_entries_by_basename,
                    parsed_mesh=parse_mesh(original_data, entry.path),
                )
                compatibility_note = f"\n\nMesh replacement compatibility: {profile.support_level} ({profile.category_hint})."
                if profile.errors:
                    compatibility_note += "\n" + "\n".join(profile.errors[:2])
            except Exception as exc:
                compatibility_note = f"\n\nMesh replacement compatibility could not be inspected: {exc}"
        dialog.setInformativeText(
            "Round-trip edit expects an OBJ to keep the original exported mesh structure. "
            "Mesh replacement maps a different OBJ/DAE model onto the original material/draw slots when the target asset is compatible."
            + compatibility_note
        )
        roundtrip_button = dialog.addButton("Round-trip Edit", QMessageBox.AcceptRole)
        static_button = dialog.addButton("Mesh Replacement", QMessageBox.ActionRole)
        if profile is not None and not profile.export_supported:
            static_button.setEnabled(False)
            static_button.setToolTip("\n".join(profile.errors) or "Mesh replacement is not enabled for this asset.")
        dialog.addButton(QMessageBox.Cancel)
        dialog.setDefaultButton(roundtrip_button)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked == static_button:
            return "static_replacement"
        if clicked == roundtrip_button:
            return "roundtrip"
        return None

    @staticmethod
    def _format_static_alignment_number(value: object) -> str:
        try:
            number = float(value)
        except (TypeError, ValueError):
            return str(value)
        if abs(number) < 0.000005:
            number = 0.0
        return f"{number:.5f}"

    @classmethod
    def _format_static_alignment_vec(cls, value: object) -> str:
        if not isinstance(value, (list, tuple)) or len(value) != 3:
            return str(value)
        return "(" + ", ".join(cls._format_static_alignment_number(part) for part in value) + ")"

    @classmethod
    def _build_archive_static_placement_context_html(
        cls,
        entry: ArchiveEntry,
        obj_path: Path,
        *,
        original_mesh: Optional[ParsedMesh] = None,
        replacement_mesh: Optional[ParsedMesh] = None,
        ) -> Tuple[str, Dict[str, object]]:
        try:
            if original_mesh is None:
                original_data = read_archive_entry_baseline_data(entry, read_entry_data=read_archive_entry_data).data
                original_mesh = parse_mesh(original_data, entry.path)
            if replacement_mesh is None:
                replacement_mesh = import_scene_mesh(obj_path)
            context_lines = describe_static_placement_context(original_mesh, replacement_mesh)
            parsed: Dict[str, object] = {}
            for line in context_lines:
                if ": " in line:
                    key, value = line.split(": ", 1)
                    parsed[key.strip().lower()] = value.strip()

            def _parse_axis_length(key: str) -> Tuple[str, float]:
                value = str(parsed.get(key, "unknown / 0") or "")
                axis, _sep, raw_length = value.partition("/")
                try:
                    length = float(raw_length.strip())
                except ValueError:
                    length = 0.0
                return axis.strip().upper() or "?", length

            def _parse_vec_from_text(key: str) -> str:
                value = str(parsed.get(key, "") or "")
                match = re.search(r"\(([^)]*)\)", value)
                if not match:
                    return value
                parts = []
                for raw_part in match.group(1).split(","):
                    try:
                        parts.append(float(raw_part.strip()))
                    except ValueError:
                        parts.append(raw_part.strip())
                return cls._format_static_alignment_vec(tuple(parts))

            original_axis, original_length = _parse_axis_length("original axis/length")
            replacement_axis, replacement_length = _parse_axis_length("replacement axis/length")
            try:
                auto_scale = float(str(parsed.get("auto length scale", "1") or "1"))
            except ValueError:
                auto_scale = 1.0
            guidance: List[str] = []
            if original_axis != replacement_axis and original_axis != "?" and replacement_axis != "?":
                guidance.append(
                    f"Axis: replacement is along <b>{replacement_axis}</b>, original is along <b>{original_axis}</b>; auto alignment will rotate between these axes."
                )
            if auto_scale < 0.95:
                guidance.append(
                    f"Scale: auto length scale is <b>{cls._format_static_alignment_number(auto_scale)}</b>, so enabled auto-scale will shrink the replacement."
                )
            elif auto_scale > 1.05:
                guidance.append(
                    f"Scale: auto length scale is <b>{cls._format_static_alignment_number(auto_scale)}</b>, so enabled auto-scale will enlarge the replacement."
                )
            else:
                guidance.append("Scale: replacement and original are already close in length.")
            guidance.append(
                "Offset: after import, move X/Y/Z in small steps if the anchor point is close but not exactly aligned."
            )
            guidance.append(
                "Rotation: use this after Auto/Flip if the asset is tilted or rolled around the anchor."
            )
            html = f"""
            <style>
              .muted {{ color: #9aa0a6; }}
              .value {{ color: #8ab4f8; font-weight: 600; }}
              .warn {{ color: #fdd663; font-weight: 600; }}
              .ok {{ color: #81c995; font-weight: 600; }}
              table {{ border-collapse: collapse; }}
              td {{ padding: 2px 10px 2px 0; vertical-align: top; }}
            </style>
            <div>
              <div class="muted">Tiny values like 3.2471e-07 mean almost zero; this dialog rounds them to 0.00000.</div>
              <table>
                <tr><td>Original length axis</td><td class="value">{original_axis}</td><td class="value">{cls._format_static_alignment_number(original_length)}</td></tr>
                <tr><td>Replacement length axis</td><td class="value">{replacement_axis}</td><td class="value">{cls._format_static_alignment_number(replacement_length)}</td></tr>
                <tr><td>Auto length scale</td><td colspan="2" class="{'warn' if auto_scale < 0.95 or auto_scale > 1.05 else 'ok'}">{cls._format_static_alignment_number(auto_scale)}</td></tr>
                <tr><td>Original inferred anchor</td><td colspan="2" class="value">{_parse_vec_from_text("original inferred anchor")}</td></tr>
                <tr><td>Replacement inferred anchor</td><td colspan="2" class="value">{_parse_vec_from_text("replacement inferred anchor")}</td></tr>
                <tr><td>Original far end</td><td colspan="2" class="value">{_parse_vec_from_text("original inferred far end")}</td></tr>
                <tr><td>Replacement far end</td><td colspan="2" class="value">{_parse_vec_from_text("replacement inferred far end")}</td></tr>
              </table>
              <div style="margin-top:8px;"><b>Suggested starting point</b></div>
              <ul>
                {''.join(f'<li>{item}</li>' for item in guidance)}
              </ul>
            </div>
            """
            return html, {
                "auto_scale": auto_scale,
                "original_axis": original_axis,
                "replacement_axis": replacement_axis,
            }
        except Exception as exc:
            return f"<span style='color:#fdd663;'>Placement values could not be read automatically: {escape(str(exc))}</span>", {}

    def _add_replacement_asset_profile_summary(
        self,
        parent_layout: QVBoxLayout,
        profile: ReplacementAssetProfile,
        ) -> None:
        theme = get_theme(self.current_theme_key)
        support_colors = {
            "Supported": "#86efac",
            "Experimental": "#facc15",
            "Preview only": "#93c5fd",
            "Blocked": "#fca5a5",
        }
        group = QGroupBox("Asset Compatibility")
        group_layout = QVBoxLayout(group)
        group_layout.setContentsMargins(5, 3, 5, 3)
        group_layout.setSpacing(3)
        facts = {str(label): str(value) for label, value in profile.facts}

        def _section_label(title: str, body_html: str, *, accent: str = "#8b949e") -> QLabel:
            label = QLabel(
                "<div style='font-size:8px; line-height:1.08; padding:2px 5px; border-left:3px solid "
                f"{accent}; background:#24292f;'>"
                "<div style='margin-bottom:1px;'>"
                f"<span style='color:{accent}; font-weight:700;'>{escape(title)}</span>"
                "</div>"
                "<div>"
                f"{body_html}"
                "</div>"
                "</div>"
            )
            label.setWordWrap(True)
            label.setTextFormat(Qt.RichText)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setMinimumWidth(0)
            label.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            return label

        chip_row = QHBoxLayout()
        chip_row.setSpacing(4)

        def _chip(label_text: str, value_text: str, color: str = "") -> QLabel:
            chip = QLabel(f"{label_text}: {value_text}")
            chip.setTextInteractionFlags(Qt.TextSelectableByMouse)
            chip.setStyleSheet(
                "QLabel {"
                f"background: {theme['surface_alt']};"
                f"border: 1px solid {theme['border']};"
                "border-radius: 3px;"
                "padding: 1px 4px;"
                f"color: {color or theme['text']};"
                "font-size: 8px;"
                "font-weight: 600;"
                "}"
            )
            return chip

        for label_text in ("Support", "Format", "Category", "Family"):
            value_text = facts.get(label_text)
            if value_text:
                chip_row.addWidget(
                    _chip(
                        label_text,
                        value_text,
                        support_colors.get(value_text, "") if label_text == "Support" else "",
                    )
                )
        chip_row.addStretch(1)
        group_layout.addLayout(chip_row)

        metric_labels = {"Submeshes", "Faces", "Vertices", "UVs", "Skinning", "LOD", "Sidecar", "Texture slots"}
        metrics_frame = QFrame()
        metrics_frame.setStyleSheet(
            "QFrame {"
            f"background: {theme['surface']};"
            f"border: 1px solid {theme['border']};"
            "border-radius: 6px;"
            "}"
        )
        metrics_grid = QGridLayout(metrics_frame)
        metrics_grid.setContentsMargins(5, 3, 5, 3)
        metrics_grid.setHorizontalSpacing(8)
        metrics_grid.setVerticalSpacing(1)
        metric_index = 0
        for label_text, value_text in profile.facts:
            if label_text not in metric_labels:
                continue
            label = QLabel(label_text)
            label.setObjectName("HintLabel")
            value = QLabel(value_text)
            value.setWordWrap(True)
            value.setMinimumWidth(0)
            value.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            value.setTextInteractionFlags(Qt.TextSelectableByMouse)
            value.setStyleSheet(f"color: {theme['text_strong']};")
            row = metric_index // 2
            column = (metric_index % 2) * 2
            metrics_grid.addWidget(label, row, column)
            metrics_grid.addWidget(value, row, column + 1)
            metric_index += 1
        if metric_index:
            group_layout.addWidget(metrics_frame)

        related_by_role: Dict[str, List[str]] = {}
        for related in profile.related_files:
            related_by_role.setdefault(related.role, []).append(PurePosixPath(related.path).name)
        related_summary = "<span style='color:#8b949e;'>None found</span>"
        if related_by_role:
            related_summary = (
                "<table cellspacing='0' cellpadding='0' style='width:100%;'>"
                + "".join(
                    "<tr>"
                    f"<td style='color:#79c0ff; font-weight:700; padding:1px 10px 1px 0; white-space:nowrap;'>{escape(role)}</td>"
                    f"<td style='color:#f0f6fc; padding:1px 0; word-break:break-all;'>{escape(', '.join(names[:4]))}"
                    f"<span style='color:#8b949e;'>{' ...' if len(names) > 4 else ''}</span></td>"
                    "</tr>"
                    for role, names in related_by_role.items()
                )
                + "</table>"
            )
        group_layout.addWidget(_section_label("Related files", related_summary, accent="#79c0ff"))

        if getattr(profile, "required_companions", ()):
            companion_names = [PurePosixPath(path).name for path in profile.required_companions[:8]]
            companions_body = (
                f"<span style='color:#f0f6fc;'>{escape(', '.join(companion_names))}</span>"
                f"<span style='color:#8b949e;'>{' ...' if len(profile.required_companions) > len(companion_names) else ''}</span>"
            )
            companions_label = _section_label("Required companions", companions_body, accent="#f2cc60")
            companions_label.setToolTip("\n".join(profile.required_companions[:80]))
            group_layout.addWidget(companions_label)

        if profile.texture_summary:
            texture_pairs = list(profile.texture_summary[:8])
            texture_rows = []
            for index in range(0, len(texture_pairs), 2):
                first_label, first_value = texture_pairs[index]
                second_html = "<td></td><td></td>"
                if index + 1 < len(texture_pairs):
                    second_label, second_value = texture_pairs[index + 1]
                    second_html = (
                        f"<td style='color:#8b949e; padding:1px 10px 1px 18px; white-space:nowrap;'>{escape(str(second_label))}</td>"
                        f"<td style='color:#f0f6fc; font-weight:600; padding:1px 0; white-space:nowrap;'>{escape(str(second_value))}</td>"
                    )
                texture_rows.append(
                    "<tr>"
                    f"<td style='color:#8b949e; padding:1px 10px 1px 0; white-space:nowrap;'>{escape(str(first_label))}</td>"
                    f"<td style='color:#f0f6fc; font-weight:600; padding:1px 0; white-space:nowrap;'>{escape(str(first_value))}</td>"
                    f"{second_html}"
                    "</tr>"
                )
            texture_summary = (
                "<table cellspacing='0' cellpadding='0' style='width:100%;'>"
                + "".join(texture_rows)
                + "</table>"
            )
            group_layout.addWidget(_section_label("Texture slots", texture_summary, accent="#d2a8ff"))

        messages = list(profile.errors) + list(profile.warnings)
        if messages:
            message_body = "".join(
                f"<div style='margin:1px 0;'>- {escape(message)}</div>"
                for message in messages[:6]
            )
            group_layout.addWidget(
                _section_label(
                    "Warnings" if not profile.errors else "Blocking issues",
                    message_body,
                    accent="#fca5a5" if profile.errors else "#facc15",
                )
            )
        compact_bits = []
        for label_text in ("Support", "Format", "Category", "Family"):
            value_text = facts.get(label_text)
            if value_text:
                compact_bits.append(f"{label_text}: {value_text}")
        if facts.get("Vertices"):
            compact_bits.append(f"Vertices: {facts['Vertices']}")
        if facts.get("Texture slots"):
            compact_bits.append(f"Texture slots: {facts['Texture slots']}")
        if messages:
            compact_bits.append(f"Warnings: {len(messages)}")
        helmet_visibility_body = ""
        if str(getattr(profile, "category_hint", "") or "").strip().lower() == "helmet":
            helmet_visibility_body = (
                "<span style='color:#f0f6fc;'>Mesh/material only; head or hair visibility follows the original helmet rules.</span>"
            )
        compact_label = QLabel(
            "<div style='font-size:8px; line-height:1.08; padding:2px 5px; border-left:3px solid #d29922; background:#2b2416;'>"
            "<span style='color:#f2cc60; font-weight:700;'>Compatibility</span>"
            f"<span style='color:#c9d1d9;'> {' | '.join(escape(bit) for bit in compact_bits)}</span>"
            "</div>"
        )
        compact_label.setWordWrap(True)
        compact_label.setTextFormat(Qt.RichText)
        compact_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        parent_layout.addWidget(compact_label)
        if helmet_visibility_body:
            helmet_label = _section_label("Helmet visibility", helmet_visibility_body, accent="#f2cc60")
            helmet_label.setToolTip(
                "It does not change whether the game hides the character head or hair. "
                "If a head or hair disappears, choose an original helmet with matching visibility rules, "
                "or edit the appearance/bonemask data separately."
            )
            parent_layout.addWidget(helmet_label)
        compatibility_control_text = _mesh_import_compatibility_control_text()
        details_section = CollapsibleSection(compatibility_control_text["details_section"], expanded=False)
        group.setTitle(compatibility_control_text["details_group"])
        details_section.body_layout.addWidget(group)
        parent_layout.addWidget(details_section)

__all__ = ["ArchiveMeshSetupHelperMixin"]
