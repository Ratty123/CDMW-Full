"""Thin Model Library local-row compatibility helpers."""

from __future__ import annotations

import os
from pathlib import Path

from cdmw.workers.model_library_rows import normalize_local_model_rows


class ModelLibraryLocalRowsMixin:
    """Expose paths while workers own row normalization and filesystem I/O."""

    def _download_output_root(self) -> Path:
        return self.catalogue_dir() / "downloads"

    def _normalize_local_model_rows(self, rows: list[dict[str, object]]) -> list[dict[str, object]]:
        """Compatibility helper; production callers dispatch this through the task lane."""

        return normalize_local_model_rows(rows, self._download_output_root())

    def _ensure_download_root_registered(self, output_root: Path) -> None:
        normalized = os.path.abspath(str(output_root))
        if normalized not in self.local_roots:
            self.local_roots.append(normalized)
            self._save_roots()
            self._refresh_roots_tree()
        if not self.local_path_edit.text().strip():
            self.local_path_edit.setText(normalized)


__all__ = ["ModelLibraryLocalRowsMixin"]
