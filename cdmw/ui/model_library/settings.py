"""Settings and filter persistence for Model Library."""

from __future__ import annotations

import json
import os

from cdmw.services.workspace_layout import workspace_paths

MODEL_LIBRARY_FILTER_COLUMNS: tuple[tuple[int, str], ...] = (
    (1, "Name"),
    (2, "Source"),
    (3, "Local"),
    (4, "Textures"),
    (5, "Format"),
    (6, "Size"),
    (7, "License"),
    (8, "Creator"),
    (9, "Location"),
)


class ModelLibrarySettingsMixin:
    """Persist roots, mirror settings, filters, and preferred download formats."""

    def _load_settings(self) -> None:
        self.local_roots = self._settings_path_list("model_library/local_roots_json")
        default_catalogue_dir = workspace_paths(self.base_dir)["model_catalogue_root"]
        mirror_url = str(self.settings.value("model_library/mirror_url", "") or "")
        catalogue_dir = str(self.settings.value("model_library/catalogue_dir", str(default_catalogue_dir)) or str(default_catalogue_dir))
        self.mirror_url_edit.setText(mirror_url)
        self.catalogue_dir_edit.setText(catalogue_dir)
        self._set_active_results_view(str(self.settings.value("model_library/results_view", "mirror") or "mirror"), persist=False)

    def _settings_path_list(self, key: str) -> list[str]:
        return self._settings_string_list(key)

    def _settings_string_list(self, key: str, *, default: tuple[str, ...] = ()) -> list[str]:
        raw = self.settings.value(key, json.dumps(list(default)) if default else "")
        if isinstance(raw, list):
            return [str(item) for item in raw if str(item).strip()]
        text = str(raw or "").strip()
        if not text:
            return list(default)
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            return [part for part in text.split(os.pathsep) if part.strip()]
        if isinstance(payload, list):
            return [str(item) for item in payload if str(item).strip()]
        return list(default)

    def _column_filter_settings_key(self) -> str:
        return (
            "model_library/local_column_filters_json"
            if self._active_results_view == "local"
            else "model_library/mirror_column_filters_json"
        )

    def _column_filters_from_settings(self, key: str) -> dict[int, str]:
        raw = self.settings.value(key, "{}")
        try:
            payload = json.loads(str(raw or "{}"))
        except json.JSONDecodeError:
            return {}
        if not isinstance(payload, dict):
            return {}
        filters: dict[int, str] = {}
        for column, _label in MODEL_LIBRARY_FILTER_COLUMNS:
            value = str(payload.get(str(column), "") or "").strip()
            if value:
                filters[column] = value
        return filters

    def _load_column_filters_for_active_view(self) -> None:
        if not hasattr(self, "results_column_filter_edits"):
            return
        filters = self._column_filters_from_settings(self._column_filter_settings_key())
        self._updating_column_filters = True
        try:
            for column, edit in self.results_column_filter_edits.items():
                edit.setText(filters.get(column, ""))
        finally:
            self._updating_column_filters = False

    def _active_column_filters(self) -> dict[int, str]:
        if not hasattr(self, "results_column_filter_edits"):
            return {}
        filters: dict[int, str] = {}
        for column, edit in self.results_column_filter_edits.items():
            value = edit.text().strip()
            if value:
                filters[column] = value
        return filters

    def _save_column_filters_for_active_view(self) -> None:
        self.settings.setValue(
            self._column_filter_settings_key(),
            json.dumps({str(column): value for column, value in self._active_column_filters().items()}),
        )

    def _save_roots(self) -> None:
        self.settings.setValue("model_library/local_roots_json", json.dumps(self.local_roots))

    def _save_mirror_settings(self) -> None:
        try:
            mirror_url = self.mirror_url()
        except ValueError:
            mirror_url = self.mirror_url_edit.text().strip()
        self.settings.setValue("model_library/mirror_url", mirror_url)
        self.settings.setValue("model_library/catalogue_dir", str(self.catalogue_dir()))

    def _checked_preferred_formats(self) -> list[str]:
        selected: list[str] = []
        for format_key in ("gltf", "glb", "source", "extra"):
            checkbox = getattr(self, "preferred_format_checks", {}).get(format_key)
            if checkbox is not None and checkbox.isChecked():
                selected.append(format_key)
        return selected

    def _selected_preferred_formats(self, *, require_importable: bool = False, allow_empty: bool = False) -> list[str]:
        selected = self._checked_preferred_formats()
        if require_importable:
            selected = [format_key for format_key in selected if format_key in {"gltf", "glb", "source"}]
        if not selected and not allow_empty:
            selected = ["gltf"]
        return selected

    def _primary_preferred_format(self, *, require_importable: bool = False) -> str:
        return self._selected_preferred_formats(require_importable=require_importable)[0]

    def _save_preferred_format_settings(self) -> None:
        if not hasattr(self, "preferred_format_checks"):
            return
        self.settings.setValue("model_library/preferred_formats_json", json.dumps(self._checked_preferred_formats()))


__all__ = ["MODEL_LIBRARY_FILTER_COLUMNS", "ModelLibrarySettingsMixin"]
