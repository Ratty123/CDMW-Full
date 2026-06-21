"""Catalogue and mirror helper methods for Model Library."""

from __future__ import annotations

import time
from pathlib import Path

from cdmw.core.model_catalogue import (
    DEFAULT_MODEL_MIRROR_URL,
    MirrorDownloadCandidate,
    catalogue_stats,
    mirror_download_candidates,
    normalize_mirror_base_url,
)
from cdmw.services.workspace_layout import workspace_paths


class ModelLibraryCatalogueMixin:
    """Mirror catalogue URLs, candidates, status text, and display formatting."""

    def _mirror_candidates_for_payload(self, payload: dict[str, object]) -> tuple[MirrorDownloadCandidate, ...]:
        payload_mirror_url = str(payload.get("mirror_url", "") or "").strip()
        if not payload_mirror_url:
            try:
                payload_mirror_url = self.mirror_url()
            except ValueError:
                payload_mirror_url = DEFAULT_MODEL_MIRROR_URL
        return mirror_download_candidates(
            payload,
            payload_mirror_url,
            preferred_format=self._primary_preferred_format(),
        )

    def _download_candidates_for_selected_formats(
        self,
        payload: dict[str, object],
        selected_formats: list[str],
        *,
        require_importable: bool,
        mirror_url: str,
    ) -> list[MirrorDownloadCandidate]:
        payload_mirror_url = str(payload.get("mirror_url", "") or "").strip() or mirror_url
        candidates = mirror_download_candidates(
            payload,
            payload_mirror_url,
            preferred_format=selected_formats[0] if selected_formats else "gltf",
        )
        selected = set(selected_formats)
        filtered = [
            candidate
            for candidate in candidates
            if candidate.format in selected
        ]
        if require_importable and not any(candidate.import_supported for candidate in filtered):
            return []
        return sorted(filtered, key=lambda candidate: selected_formats.index(candidate.format))

    def _selected_file_url_text(self, payloads: list[dict[str, object]]) -> str:
        sections: list[str] = []
        for payload in payloads:
            name = str(payload.get("name", "") or "Untitled model")
            uid = str(payload.get("uid", "") or "")
            license_label = str(payload.get("license_label", "") or "")
            creator = str(payload.get("creator_name", "") or payload.get("creator_username", "") or "")
            sections.append(name)
            if uid:
                sections.append(f"UID: {uid}")
            if creator:
                sections.append(f"Creator: {creator}")
            if license_label:
                sections.append(f"License: {license_label}")
            for candidate in self._mirror_candidates_for_payload(payload):
                sections.append(f"{getattr(candidate, 'label', 'File')}: {getattr(candidate, 'url', '')}")
            viewer_url = str(payload.get("viewer_url", "") or "")
            if viewer_url:
                sections.append(f"Page: {viewer_url}")
            sections.append("")
        return "\n".join(sections).strip()

    def mirror_url(self) -> str:
        return normalize_mirror_base_url(self.mirror_url_edit.text().strip())

    def catalogue_dir(self) -> Path:
        return Path(
            self.catalogue_dir_edit.text().strip()
            or str(workspace_paths(self.base_dir)["model_catalogue_root"])
        ).expanduser()

    def catalogue_db_path(self) -> Path:
        return self.catalogue_dir() / "mirror_catalogue.sqlite"

    def _update_catalogue_status(self) -> None:
        stats = catalogue_stats(self.catalogue_db_path())
        self.catalogue_status_label.setText(
            f"Indexed metadata: {stats['models']:,} model(s), {stats['shards']:,} catalogue page(s). Downloads are stored under {self.catalogue_dir() / 'downloads'} after you enter the mirror URL."
        )

    def _mirror_size_summary(self, payload: dict[str, object]) -> str:
        size = self._mirror_size_bytes(payload)
        return self._format_size(size) if size > 0 else "-"

    def _mirror_size_bytes(self, payload: dict[str, object]) -> int:
        archives = payload.get("archives") if isinstance(payload.get("archives"), dict) else {}
        sizes: list[int] = []
        for value in archives.values():
            if isinstance(value, dict):
                size = value.get("size")
                try:
                    sizes.append(int(size))
                except (TypeError, ValueError):
                    pass
        if not sizes:
            return 0
        return max(sizes)

    def _format_size(self, size: int) -> str:
        value = max(0, int(size))
        if value < 1024:
            return f"{value} B"
        if value < 1024 * 1024:
            return f"{value / 1024:.1f} KB"
        if value < 1024 * 1024 * 1024:
            return f"{value / (1024 * 1024):.1f} MB"
        return f"{value / (1024 * 1024 * 1024):.1f} GB"

    def _format_count(self, value: object) -> str:
        try:
            if value is None or value == "":
                return "-"
            return f"{int(value):,}"
        except (TypeError, ValueError):
            return "-"

    def _format_time(self, timestamp: float) -> str:
        if timestamp <= 0:
            return "-"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(timestamp))


__all__ = ["ModelLibraryCatalogueMixin"]
