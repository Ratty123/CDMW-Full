"""Archive asset preview panel boundary."""

from __future__ import annotations

from typing import List, Optional, Sequence

from PySide6.QtWidgets import QCheckBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSizePolicy, QWidget

from cdmw.models import ArchiveEntry, ArchiveModelTextureReference, ArchivePreviewResult


class ArchivePreviewTextToolsMixin:
    """Text preview language detection and find/wrap toolbars for archive previews."""

    def _archive_preview_health_text(
        self,
        result: Optional[ArchivePreviewResult],
        entry: Optional[ArchiveEntry],
        references: Sequence[ArchiveModelTextureReference] = (),
    ) -> str:
        if not isinstance(entry, ArchiveEntry):
            return ""
        parts: List[str] = []
        if isinstance(result, ArchivePreviewResult):
            status = str(getattr(result, "status", "") or "").strip().lower()
            preferred_view = str(getattr(result, "preferred_view", "") or "").strip().lower()
            if status == "ok":
                parts.append("Preview OK" if preferred_view and preferred_view != "info" else "Readable")
            elif status:
                parts.append(status.replace("_", " ").title())
            preview_model = getattr(result, "preview_model", None)
            if preview_model is not None:
                parts.append("3D Preview")
        role = self._archive_entry_role_label(entry)
        if role:
            parts.append(role)
        reference_roles = {
            self._archive_reference_role_label(reference)
            for reference in references
            if isinstance(reference, ArchiveModelTextureReference)
        }
        if "Texture" in reference_roles:
            has_partial_texture = any(
                "partial" in self._archive_texture_reference_status_text(reference).casefold()
                for reference in references
                if isinstance(reference, ArchiveModelTextureReference)
                and self._archive_reference_role_label(reference) == "Texture"
            )
            parts.append("Textures Partial" if has_partial_texture else "Textures Linked")
        if "Material" in reference_roles:
            parts.append("Material Linked")
        if "Physics" in reference_roles or "HKX" in reference_roles:
            parts.append("Physics Metadata")
        if self._archive_known_used_by_references(entry):
            parts.append("Used By Known Index")
        exact_name, name_hint, _name_reason = self._archive_entry_item_name_match(entry)
        if exact_name:
            parts.append("Name Exact")
        elif name_hint:
            parts.append("Name Inferred")
        if entry.extension in {".hkx", ".hkt"}:
            parts.append("Editable HKX/HKT" if role in {"Physics", "HKX"} else "HKX/HKT")
        seen: set[str] = set()
        ordered: List[str] = []
        for part in parts:
            normalized = part.casefold()
            if part and normalized not in seen:
                ordered.append(part)
                seen.add(normalized)
        return self._ui_compact_status_line(ordered)

    def _set_archive_preview_health_message(
        self,
        message: str,
        *,
        visible: Optional[bool] = None,
        attention: bool = False,
    ) -> None:
        try:
            label = self.archive_preview_health_label
            label.setText(message)
            label.setVisible(bool(message) if visible is None else bool(visible))
            label.setProperty("attention", bool(attention))
            label.style().unpolish(label)
            label.style().polish(label)
        except RuntimeError:
            pass

    def _archive_preview_text_language_extension_for_entry(
        self,
        entry: object | None,
        preview_text: str,
    ) -> str:
        extension = entry.extension.lower() if entry is not None else ""
        stripped = preview_text.lstrip("\ufeff\r\n\t ")
        if extension == ".pami":
            return ".xml"
        if stripped.startswith(("<?xml", "<")):
            return ".xml"
        if stripped.startswith(("{", "[")):
            return ".json"

        non_empty_lines = [line.strip() for line in preview_text.splitlines() if line.strip()]
        sample_lines = non_empty_lines[:8]
        if any(line.startswith("[") and line.endswith("]") for line in sample_lines):
            return ".ini"
        if any("=" in line and not line.startswith("<") for line in sample_lines):
            return ".ini"
        if any(line.startswith("--") for line in sample_lines) or "function " in preview_text[:4096]:
            return ".lua"
        return extension

    def _archive_preview_text_language_extension(self, preview_text: str) -> str:
        return self._archive_preview_text_language_extension_for_entry(self._current_archive_entry(), preview_text)

    def _build_archive_text_tools(self, editor: object) -> QWidget:
        tools = QWidget()
        tools_layout = QHBoxLayout(tools)
        tools_layout.setContentsMargins(0, 0, 0, 0)
        tools_layout.setSpacing(6)

        find_label = QLabel("Find")
        find_label.setObjectName("HintLabel")
        search_edit = QLineEdit()
        search_edit.setPlaceholderText("Search preview")
        search_edit.setClearButtonEnabled(True)
        search_edit.setMaximumWidth(220)
        result_label = QLabel("")
        result_label.setObjectName("HintLabel")
        previous_button = QPushButton("Prev")
        next_button = QPushButton("Next")
        wrap_checkbox = QCheckBox("Wrap lines")
        wrap_checkbox.setChecked(True)
        editor.set_wrap_enabled(True)

        for button in (previous_button, next_button):
            button.setMinimumWidth(58)
            button.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)

        def _update_result_label(current: int, total: int) -> None:
            query = search_edit.text().strip()
            if not query:
                result_label.setText("")
                return
            result_label.setText(f"{current}/{total}" if total else "0")

        def _run_search(*, jump: bool) -> None:
            current, total = editor.search_text(search_edit.text(), jump=jump)
            _update_result_label(current, total)

        def _find_next() -> None:
            if not search_edit.text().strip():
                return
            current, total = editor.find_next_match()
            _update_result_label(current, total)

        def _find_previous() -> None:
            if not search_edit.text().strip():
                return
            current, total = editor.find_previous_match()
            _update_result_label(current, total)

        search_edit.textChanged.connect(lambda _text: _run_search(jump=True))
        search_edit.returnPressed.connect(_find_next)
        previous_button.clicked.connect(_find_previous)
        next_button.clicked.connect(_find_next)
        wrap_checkbox.toggled.connect(editor.set_wrap_enabled)
        editor.textChanged.connect(lambda: _run_search(jump=False) if search_edit.text().strip() else None)

        tools_layout.addWidget(find_label)
        tools_layout.addWidget(search_edit)
        tools_layout.addWidget(previous_button)
        tools_layout.addWidget(next_button)
        tools_layout.addWidget(result_label)
        tools_layout.addStretch(1)
        tools_layout.addWidget(wrap_checkbox)
        return tools

    def _update_archive_preview_text_tools_visibility(self, *_args) -> None:
        if not hasattr(self, "archive_preview_text_tools"):
            return
        current_widget = self.archive_preview_stack.currentWidget()
        self.archive_preview_text_tools.setVisible(current_widget is self.archive_preview_text_edit)
        if hasattr(self, "archive_preview_info_tools"):
            self.archive_preview_info_tools.setVisible(current_widget is self.archive_preview_info_edit)
        if hasattr(self, "archive_preview_controls_hint_label"):
            self.archive_preview_controls_hint_label.setVisible(
                current_widget is self.archive_model_preview
                or current_widget is self.archive_d3d11_preview_host
            )


__all__ = ["ArchivePreviewTextToolsMixin"]
