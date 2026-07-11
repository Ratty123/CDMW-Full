"""Texture-status helpers for Model Library rows."""

from __future__ import annotations

from pathlib import Path


class ModelLibraryTextureStatusMixin:
    """Compute and refresh local texture status for result rows."""

    def _mirror_local_status(self, payload: dict[str, object]) -> str:
        return str(payload.get("local_status", "") or "")

    def _local_payload_status(self, payload: dict[str, object]) -> str:
        if self._payload_can_import(payload):
            path = Path(str(payload.get("path", "") or ""))
            if path.suffix.lower() == ".zip":
                return "ZIP ready"
            return "Ready"
        if Path(str(payload.get("path", "") or "")).suffix.lower() == ".zip":
            return "ZIP"
        return "Browse"

    def _texture_status_for_payload(self, payload: dict[str, object]) -> str:
        existing = str(payload.get("texture_status", "") or "").strip()
        if existing:
            return existing
        if payload.get("kind") == "mirror":
            return "Download to check" if not str(payload.get("local_status", "") or "").strip() else "Unknown"
        path = Path(str(payload.get("import_path", "") or payload.get("path", "") or ""))
        if path.suffix.lower() == ".glb":
            return "Embedded/Unknown"
        return "Unknown"

    def _refresh_result_row_status(self, payload: dict[str, object]) -> None:
        item = self._result_item_for_payload(payload)
        if item is None:
            return
        if payload.get("kind") == "mirror":
            item.setText(3, self._mirror_local_status(payload))
        else:
            item.setText(3, self._local_payload_status(payload))
        item.setText(4, self._texture_status_for_payload(payload))
        self._sync_no_texture_download_cache_for_item(item)

    def _refresh_result_row_statuses(self) -> None:
        for index in range(self.results_tree.topLevelItemCount()):
            item = self.results_tree.topLevelItem(index)
            payload = self._payload_from_item(item)
            if payload is None:
                continue
            if payload.get("kind") == "mirror":
                item.setText(3, self._mirror_local_status(payload))
                item.setText(4, self._texture_status_for_payload(payload))
            else:
                item.setText(3, self._local_payload_status(payload))
                item.setText(4, self._texture_status_for_payload(payload))
            self._sync_no_texture_download_cache_for_item(item)


__all__ = ["ModelLibraryTextureStatusMixin"]
