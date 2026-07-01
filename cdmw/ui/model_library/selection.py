"""Selection state and detail rendering for Model Library."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from cdmw.ui.model_library.state import external_audit_texture_slot_text as _external_audit_texture_slot_text


class ModelLibrarySelectionMixin:
    """Update result actions and details for selected Model Library rows."""

    def _update_selection_state(self) -> None:
        payload = self._selected_payload()
        checked_payloads = self._checked_payloads()
        batch_mirror_count = sum(1 for selected in checked_payloads if selected.get("kind") == "mirror")
        delete_payloads = [
            selected
            for selected in checked_payloads
            if self._local_delete_target_for_payload(selected) is not None
        ]
        if not delete_payloads and payload is not None and self._local_delete_target_for_payload(payload) is not None:
            delete_payloads = [payload]
        no_texture_download_count = self._visible_no_texture_download_count()
        checked_count = len(checked_payloads)
        result_count = self.results_tree.topLevelItemCount()
        mirror_url_ready = bool(self.mirror_url_edit.text().strip())
        has_selection = bool(payload)
        is_mirror = bool(payload and payload.get("kind") == "mirror")
        is_local = bool(payload and payload.get("kind") == "local")
        local_importable = bool(is_local and self._payload_can_import(payload))
        mirror_importable = bool(is_mirror)
        can_preview_here = self._payload_can_preview_here(payload)
        self.import_mesh_button.setEnabled(has_selection and (local_importable or mirror_importable))
        self.preview_button.setEnabled(can_preview_here)
        self.generate_icon_button.setEnabled(can_preview_here)
        self.download_button.setEnabled(batch_mirror_count > 0 and mirror_url_ready)
        self.download_button.setText("Download Checked" if batch_mirror_count <= 1 else f"Download Checked ({batch_mirror_count})")
        self.download_import_button.setEnabled(is_mirror and mirror_url_ready)
        self.open_file_url_button.setEnabled(is_mirror)
        self.open_location_button.setEnabled(has_selection)
        self.open_page_button.setEnabled(has_selection)
        self.delete_local_button.setEnabled(bool(delete_payloads))
        self.delete_local_button.setText("Delete Local" if len(delete_payloads) <= 1 else f"Delete Local ({len(delete_payloads)})")
        self.delete_no_texture_downloads_button.setEnabled(self._active_results_view == "local" and no_texture_download_count > 0)
        self.delete_no_texture_downloads_button.setText(
            "Delete No-Texture Downloads"
            if no_texture_download_count <= 1
            else f"Delete No-Texture Downloads ({no_texture_download_count})"
        )
        self.more_actions_button.setEnabled(
            bool(
                (is_mirror and mirror_url_ready)
                or is_mirror
                or has_selection
                or delete_payloads
                or no_texture_download_count
            )
        )
        self.select_all_button.setEnabled(result_count > 0)
        self.select_none_button.setEnabled(checked_count > 0)
        self.remove_local_root_button.setEnabled(self.roots_tree.currentItem() is not None)
        if result_count:
            view_name = "Local Library" if self._active_results_view == "local" else "Mirror Catalogue"
            self.results_status_label.setText(f"{view_name}: {result_count:,} result(s) | {checked_count:,} checked")
        else:
            view_name = "Local Library" if self._active_results_view == "local" else "Mirror Catalogue"
            hidden = int(getattr(self, "_last_hidden_downloaded_count", 0) or 0)
            if self._active_results_view == "mirror" and hidden and self.hide_downloaded_checkbox.isChecked():
                self.results_status_label.setText(f"{view_name}: 0 visible result(s) | {hidden:,} downloaded hidden")
            else:
                self.results_status_label.setText(f"{view_name}: 0 result(s)")
        self._show_details(payload)

    def _show_details(self, payload: Optional[dict[str, object]]) -> None:
        if not payload:
            self.details_edit.clear()
            self.details_text.setPlainText("Select a local file or mirror result.")
            return
        name = str(payload.get("name", "") or "Untitled model")
        self.details_edit.setText(name)
        if payload.get("kind") == "mirror":
            candidates = self._mirror_candidates_for_payload(payload)
            lines = [
                f"UID: {payload.get('uid', '')}",
                f"Creator: {payload.get('creator_name', '') or payload.get('creator_username', '') or '-'}",
                f"License: {payload.get('license_label', '') or '-'}",
                f"Formats: {', '.join(candidate.label for candidate in candidates) or '-'}",
                f"Faces: {self._format_count(payload.get('face_count'))}",
                f"Vertices: {self._format_count(payload.get('vertex_count'))}",
                f"Views: {self._format_count(payload.get('view_count'))}",
                f"Likes: {self._format_count(payload.get('like_count'))}",
                f"Local status: {self._mirror_local_status(payload) or 'Not downloaded'}",
                f"Textures: {self._texture_status_for_payload(payload)}",
            ]
            if candidates:
                lines.append("")
                lines.append("File URLs:")
                lines.extend(f"- {candidate.label}: {candidate.url}" for candidate in candidates)
            lines.append("")
            lines.append("Downloads are enabled after you enter the mirror URL. Downloaded files are stored under the catalogue downloads folder.")
            if payload.get("asset_dir"):
                lines.append(f"Local: {payload.get('asset_dir')}")
            if payload.get("archive_path"):
                lines.append(f"Archive: {payload.get('archive_path')}")
            if payload.get("import_path"):
                lines.append(f"Resolved import file: {payload.get('import_path')}")
            if payload.get("viewer_url"):
                lines.append(f"Page: {payload.get('viewer_url')}")
            description = str(payload.get("description", "") or "").strip()
            if description:
                lines.append("")
                lines.append(description[:1600])
            self.details_text.setPlainText("\n".join(lines))
            return
        path = Path(str(payload.get("path", "") or ""))
        lines = [
            f"Path: {path}",
            f"Root: {payload.get('root', '')}",
            f"Format: {payload.get('extension', '')}",
            f"Size: {self._format_size(int(payload.get('size', 0) or 0))}",
            f"Modified: {self._format_time(float(payload.get('modified_at', 0.0) or 0.0))}",
            f"Local status: {self._local_payload_status(payload)}",
            f"Textures: {self._texture_status_for_payload(payload)}",
            "Import: supported" if self._payload_can_import(payload) else "Import: browse only",
        ]
        if payload.get("creator_name") or payload.get("creator_username"):
            lines.append(f"Creator: {payload.get('creator_name', '') or payload.get('creator_username', '')}")
        if payload.get("license_label"):
            lines.append(f"License: {payload.get('license_label')}")
        if payload.get("viewer_url"):
            lines.append(f"Page: {payload.get('viewer_url')}")
        if payload.get("asset_dir"):
            lines.append(f"Asset folder: {payload.get('asset_dir')}")
        import_path = str(payload.get("import_path", "") or "")
        if import_path:
            lines.append(f"Resolved import file: {import_path}")
        audit_category = str(payload.get("audit_category", "") or "")
        if audit_category:
            confidence = float(payload.get("audit_confidence", 0.0) or 0.0)
            texture_slots = ", ".join(str(slot) for slot in tuple(payload.get("audit_texture_slots", ()) or ())) or "-"
            workflows = ", ".join(str(workflow) for workflow in tuple(payload.get("audit_workflows", ()) or ())) or "-"
            flags = []
            if payload.get("audit_false_positive"):
                flags.append("false-positive")
            if payload.get("audit_mixed_model"):
                flags.append("mixed")
            suffix = f" ({', '.join(flags)})" if flags else ""
            lines.append(f"Audit: {audit_category} {confidence:.0%}{suffix}; textures: {texture_slots}; PBR: {workflows}")
            class_rows = tuple(row for row in tuple(payload.get("audit_material_classes", ()) or ()) if isinstance(row, dict))
            if class_rows:
                class_text = ", ".join(
                    f"{str(row.get('class', '') or '')} {float(row.get('confidence', 0.0) or 0.0):.0%}"
                    for row in class_rows[:8]
                    if str(row.get("class", "") or "").strip()
                )
                if class_text:
                    lines.append(f"Material classes: {class_text}")
            inventory_rows = tuple(row for row in tuple(payload.get("audit_material_inventory", ()) or ()) if isinstance(row, dict))
            for row in inventory_rows[:5]:
                material_name = str(row.get("material_name", "") or "-")
                material_slots = ", ".join(str(slot) for slot in tuple(row.get("texture_slots", ()) or ())[:8]) or "-"
                material_workflow = str(row.get("pbr_workflow", "") or "-")
                alpha_mode = str(row.get("alpha_mode", "") or "-")
                row_classes = tuple(item for item in tuple(row.get("material_classes", ()) or ()) if isinstance(item, dict))
                material_class_text = ", ".join(
                    f"{str(item.get('class', '') or '')} {float(item.get('confidence', 0.0) or 0.0):.0%}"
                    for item in row_classes[:4]
                    if str(item.get("class", "") or "").strip()
                ) or "-"
                lines.append(
                    f"Material: {material_name}; class: {material_class_text}; slots: {material_slots}; PBR: {material_workflow}; alpha: {alpha_mode}"
                )
                texture_slot_rows = tuple(item for item in tuple(row.get("texture_slot_rows", ()) or ()) if isinstance(item, dict))
                texture_file_text = ", ".join(
                    text
                    for text in (_external_audit_texture_slot_text(item) for item in texture_slot_rows[:4])
                    if text
                )
                if texture_file_text:
                    lines.append(f"Texture files: {texture_file_text}")
                texture_stats = ", ".join(str(item) for item in tuple(row.get("texture_stats", ()) or ())[:3])
                if texture_stats:
                    lines.append(f"Texture stats: {texture_stats}")
                vertex_color = tuple(row.get("vertex_color_factor", ()) or ())
                vertex_alpha = tuple(row.get("vertex_alpha", ()) or ())
                if len(vertex_color) >= 3:
                    vertex_text = f"Vertex color: rgb={float(vertex_color[0]):.2f}/{float(vertex_color[1]):.2f}/{float(vertex_color[2]):.2f}"
                    if len(vertex_alpha) >= 2:
                        vertex_text += f"; alpha={float(vertex_alpha[0]):.2f} min={float(vertex_alpha[1]):.2f}"
                    lines.append(vertex_text)
                for warning in tuple(row.get("warnings", ()) or ())[:1]:
                    lines.append(f"Material warning: {warning}")
            for warning in tuple(payload.get("audit_warnings", ()) or ())[:3]:
                lines.append(f"Audit warning: {warning}")
        archive_path = str(payload.get("archive_path", "") or "")
        if archive_path:
            lines.append(f"Archive: {archive_path}")
        self.details_text.setPlainText("\n".join(lines))


__all__ = ["ModelLibrarySelectionMixin"]
