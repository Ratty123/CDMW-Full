"""Export actions for Text Search results."""

from __future__ import annotations

from pathlib import Path
from typing import Optional, Sequence

from PySide6.QtWidgets import QMessageBox

from cdmw.core.text_search import TextSearchResult, export_text_search_results


class TextSearchExportMixin:
    def _resolve_export_root(self) -> Optional[Path]:
        text = self.export_root_edit.text().strip()
        if not text:
            self.status_message_requested.emit("Select an export root first.", True)
            return None
        return Path(text).expanduser()

    def _confirm_export(self, results: Sequence[TextSearchResult]) -> bool:
        answer = QMessageBox.question(
            self,
            "Export Files",
            f"Export {len(results):,} matched file(s) while preserving folder structure?",
        )
        return answer == QMessageBox.Yes

    def export_selected_results(self) -> None:
        selected = self.selected_results()
        if not selected:
            self.status_message_requested.emit("Select one or more results to export.", True)
            return
        self._export_results(selected, label="selected")

    def export_all_results(self) -> None:
        if not self.search_results:
            self.status_message_requested.emit("There are no search results to export.", True)
            return
        self._export_results(self.search_results, label="all results")

    def _export_results(self, results: Sequence[TextSearchResult], *, label: str) -> None:
        export_root = self._resolve_export_root()
        if export_root is None:
            return
        if not self._confirm_export(results):
            return
        try:
            stats = export_text_search_results(results, export_root, on_log=self.append_log)
            message = (
                f"Exported {stats['exported']:,} file(s) from {label}. "
                f"Renamed {stats['renamed']:,}, failed {stats['failed']:,}."
            )
            self.status_message_requested.emit(message, False)
            self.append_log(message)
        except Exception as exc:
            self.status_message_requested.emit(str(exc), True)
            self.append_log(f"ERROR: {exc}")


__all__ = ["TextSearchExportMixin"]
