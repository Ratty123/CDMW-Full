from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Dict, Optional, Sequence

from PySide6.QtCore import QThread, Qt
from PySide6.QtWidgets import (
    QDialog,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QSplitter,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from cdmw.models import ReplaceAssistantReviewItem
from cdmw.ui.replace_assistant.workers import ReplaceAssistantReviewCompareWorker
from cdmw.ui.widgets import PreviewLabel, PreviewScrollArea, build_responsive_splitter_sizes


class ReplaceAssistantReviewDialog(QDialog):
    def __init__(self, texconv_path: Optional[Path], review_items: Sequence[ReplaceAssistantReviewItem], parent: Optional[QWidget] = None) -> None:
        super().__init__(parent)
        self.texconv_path = texconv_path
        self.review_items = list(review_items)
        self.request_id = 0
        self.worker: Optional[ReplaceAssistantReviewCompareWorker] = None
        self.thread: Optional[QThread] = None
        self.pending_item: Optional[ReplaceAssistantReviewItem] = None

        self.setWindowTitle("Texture Replacer Review")
        self.resize(1320, 820)

        root_layout = QHBoxLayout(self)
        root_layout.setContentsMargins(10, 10, 10, 10)
        root_layout.setSpacing(10)

        queue_group = QGroupBox("Built Items")
        queue_layout = QVBoxLayout(queue_group)
        queue_layout.setContentsMargins(10, 12, 10, 10)
        queue_layout.setSpacing(8)
        queue_hint = QLabel("Review each rebuilt DDS against the edited source before shipping the package. Select a built item to load its previews.")
        queue_hint.setWordWrap(True)
        queue_hint.setObjectName("HintLabel")
        queue_layout.addWidget(queue_hint)
        self.item_list = QListWidget()
        self.item_list.setMinimumWidth(280)
        self.item_list.setAlternatingRowColors(True)
        self.item_list.setTextElideMode(Qt.ElideMiddle)
        for item in self.review_items:
            list_item = QListWidgetItem(item.relative_path.as_posix(), self.item_list)
            list_item.setToolTip(item.relative_path.as_posix())
        queue_layout.addWidget(self.item_list, stretch=1)
        root_layout.addWidget(queue_group, stretch=0)

        compare_splitter = QSplitter(Qt.Horizontal)
        compare_splitter.setChildrenCollapsible(False)
        root_layout.addWidget(compare_splitter, stretch=1)

        source_panel = QGroupBox("Edited Input")
        source_layout = QVBoxLayout(source_panel)
        source_layout.setContentsMargins(10, 12, 10, 10)
        source_layout.setSpacing(8)
        self.source_title = QLabel("Edited input")
        self.source_title.setWordWrap(True)
        self.source_meta = QLabel("")
        self.source_meta.setWordWrap(True)
        self.source_meta.setObjectName("HintLabel")
        self.source_label = PreviewLabel("Select a built item to review.")
        self.source_label.setMinimumSize(360, 360)
        self.source_scroll = PreviewScrollArea()
        self.source_scroll.setWidgetResizable(False)
        self.source_scroll.setAlignment(Qt.AlignCenter)
        self.source_scroll.setWidget(self.source_label)
        self.source_label.attach_scroll_area(self.source_scroll)
        source_layout.addWidget(self.source_title)
        source_layout.addWidget(self.source_meta)
        source_layout.addWidget(self.source_scroll, stretch=1)
        compare_splitter.addWidget(source_panel)

        output_panel = QGroupBox("Rebuilt DDS Review")
        output_layout = QVBoxLayout(output_panel)
        output_layout.setContentsMargins(10, 12, 10, 10)
        output_layout.setSpacing(8)
        self.output_title = QLabel("Rebuilt DDS")
        self.output_title.setWordWrap(True)
        self.output_meta = QLabel("")
        self.output_meta.setWordWrap(True)
        self.output_meta.setObjectName("HintLabel")
        self.output_label = PreviewLabel("Select a built item to review.")
        self.output_label.setMinimumSize(360, 360)
        self.output_scroll = PreviewScrollArea()
        self.output_scroll.setWidgetResizable(False)
        self.output_scroll.setAlignment(Qt.AlignCenter)
        self.output_scroll.setWidget(self.output_label)
        self.output_label.attach_scroll_area(self.output_scroll)
        self.metadata_browser = QTextBrowser()
        self.metadata_browser.setOpenExternalLinks(False)
        self.metadata_browser.setMaximumHeight(220)
        self.metadata_browser.setPlaceholderText("Reference and rebuild metadata appear here.")
        self.details_browser = QTextBrowser()
        self.details_browser.setOpenExternalLinks(False)
        self.details_browser.setPlaceholderText("Detailed paths and notes appear here.")
        output_layout.addWidget(self.output_title)
        output_layout.addWidget(self.output_meta)
        output_layout.addWidget(self.output_scroll, stretch=1)
        output_layout.addWidget(self.metadata_browser, stretch=0)
        output_layout.addWidget(self.details_browser, stretch=1)
        compare_splitter.addWidget(output_panel)
        compare_splitter.setSizes(build_responsive_splitter_sizes(1480, [47, 53], [320, 360]))

        self.item_list.currentRowChanged.connect(self._handle_row_changed)

    def closeEvent(self, event) -> None:  # type: ignore[override]
        self._stop_worker()
        super().closeEvent(event)

    def _stop_worker(self) -> None:
        if self.worker is not None:
            self.worker.stop()
        if self.thread is not None:
            try:
                self.thread.requestInterruption()
            except Exception:
                pass
            self.thread.quit()
        self.worker = None
        self.thread = None

    def _handle_row_changed(self, row: int) -> None:
        if row < 0 or row >= len(self.review_items):
            return
        item = self.review_items[row]
        self.request_id += 1
        request_id = self.request_id
        self.source_title.setText(item.source_path.name)
        self.source_meta.setText("Preparing edited input preview...")
        self.output_title.setText(item.output_dds_path.name)
        self.output_meta.setText("Preparing rebuilt DDS preview...")
        self.metadata_browser.setHtml("<p>Preparing metadata...</p>")
        self.details_browser.setHtml(f"<p>{escape(item.relative_path.as_posix())}</p>")
        if self.thread is not None:
            self.pending_item = item
            if self.worker is not None:
                self.worker.stop()
            return
        worker = ReplaceAssistantReviewCompareWorker(request_id, self.texconv_path, item)
        thread = QThread(self)
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.completed.connect(self._handle_payload_ready)
        worker.error.connect(self._handle_payload_error)
        worker.finished.connect(thread.quit)
        worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(self._cleanup_worker_refs)
        self.worker = worker
        self.thread = thread
        thread.start()

    def _cleanup_worker_refs(self) -> None:
        self.thread = None
        self.worker = None
        if self.pending_item is not None:
            pending = self.pending_item
            self.pending_item = None
            try:
                row = self.review_items.index(pending)
            except ValueError:
                return
            self.item_list.setCurrentRow(row)

    def _format_metadata_block(self, title: str, metadata: Optional[Dict[str, str]]) -> str:
        if not metadata:
            return f"<h3>{escape(title)}</h3><p>Unavailable.</p>"
        rows = []
        for label in ("format", "size", "mips", "kind"):
            value = metadata.get(label)
            if value:
                pretty_label = {
                    "format": "Format",
                    "size": "Size",
                    "mips": "Mips",
                    "kind": "Kind",
                }[label]
                rows.append(f"<tr><td><b>{pretty_label}</b></td><td>{escape(value)}</td></tr>")
        return (
            f"<h3>{escape(title)}</h3>"
            "<table cellspacing='6' cellpadding='0'>"
            + "".join(rows)
            + "</table>"
        )

    def _format_comparison_html(
        self,
        source_metadata: Dict[str, str],
        original_metadata: Optional[Dict[str, str]],
        output_metadata: Optional[Dict[str, str]],
        comparison_rows: Sequence[tuple[str, str]],
    ) -> str:
        parts = [
            "<html><body>",
            self._format_metadata_block("Edited Source", source_metadata),
            self._format_metadata_block("Original Reference DDS", original_metadata),
            self._format_metadata_block("Rebuilt DDS", output_metadata),
            "<h3>Comparison</h3>",
            "<table cellspacing='6' cellpadding='0'>",
        ]
        for label, value in comparison_rows:
            parts.append(f"<tr><td><b>{escape(label)}</b></td><td>{escape(value)}</td></tr>")
        parts.append("</table></body></html>")
        return "".join(parts)

    def _format_details_html(self, item: ReplaceAssistantReviewItem, source_detail: str) -> str:
        rows = [
            ("Package relative path", item.relative_path.as_posix()),
            ("Edited source", str(item.source_path)),
            ("Original reference DDS", str(item.original_dds_path) if item.original_dds_path is not None else "Unavailable"),
            ("Built DDS", str(item.output_dds_path)),
        ]
        html_rows = "".join(
            f"<tr><td><b>{escape(label)}</b></td><td>{escape(value)}</td></tr>"
            for label, value in rows
        )
        notes = escape(source_detail or "")
        notes = notes.replace("\n", "<br>")
        return (
            "<html><body>"
            "<h3>Paths</h3>"
            "<table cellspacing='6' cellpadding='0'>"
            f"{html_rows}"
            "</table>"
            "<h3>Notes</h3>"
            f"<p>{notes}</p>"
            "</body></html>"
        )

    def _handle_payload_ready(self, request_id: int, payload: object) -> None:
        if request_id != self.request_id or not isinstance(payload, dict):
            return
        item = payload.get("item")
        if not isinstance(item, ReplaceAssistantReviewItem):
            return
        self.source_title.setText(item.source_path.name)
        source_metadata = payload.get("source_metadata") if isinstance(payload.get("source_metadata"), dict) else {}
        source_meta_text = str(payload.get("source_meta", "") or "")
        if source_metadata:
            summary_parts = []
            if source_metadata.get("kind"):
                summary_parts.append(source_metadata["kind"])
            if source_metadata.get("size"):
                summary_parts.append(source_metadata["size"])
            if source_metadata.get("format"):
                summary_parts.append(source_metadata["format"])
            if source_meta_text:
                summary_parts.append(source_meta_text)
            self.source_meta.setText(" | ".join(summary_parts))
        else:
            self.source_meta.setText(source_meta_text)
        source_image = payload.get("source_image")
        source_preview_path = str(payload.get("source_preview_path", "") or "")
        if source_image is not None:
            self.source_label.set_preview_image(source_image, item.source_path.name)
        elif source_preview_path:
            self.source_label.set_preview_image_path(source_preview_path, item.source_path.name)
        else:
            self.source_label.clear_preview("No input preview available.")
        output_result = payload.get("output_result")
        output_image = payload.get("output_image")
        if isinstance(output_result, object) and hasattr(output_result, "title"):
            self.output_title.setText(getattr(output_result, "title", item.output_dds_path.name) or item.output_dds_path.name)
            self.output_meta.setText(getattr(output_result, "metadata_summary", "") or getattr(output_result, "message", ""))
            if output_image is not None:
                self.output_label.set_preview_image(output_image, self.output_title.text())
            elif getattr(output_result, "preview_png_path", ""):
                self.output_label.set_preview_image_path(getattr(output_result, "preview_png_path"), self.output_title.text())
            else:
                self.output_label.clear_preview(getattr(output_result, "message", "No rebuilt DDS preview available."))
        original_metadata = payload.get("original_metadata") if isinstance(payload.get("original_metadata"), dict) else None
        output_metadata = payload.get("output_metadata") if isinstance(payload.get("output_metadata"), dict) else None
        comparison_rows = payload.get("comparison_rows") if isinstance(payload.get("comparison_rows"), list) else []
        self.metadata_browser.setHtml(
            self._format_comparison_html(
                source_metadata=source_metadata,
                original_metadata=original_metadata,
                output_metadata=output_metadata,
                comparison_rows=comparison_rows,
            )
        )
        self.details_browser.setHtml(self._format_details_html(item, str(payload.get("source_detail", ""))))

    def _handle_payload_error(self, request_id: int, message: str) -> None:
        if request_id != self.request_id:
            return
        self.source_meta.setText(message)
        self.output_meta.setText(message)
        self.source_label.clear_preview("Preview failed.")
        self.output_label.clear_preview("Preview failed.")
        self.metadata_browser.setHtml(f"<p>{escape(message)}</p>")
        self.details_browser.setHtml(f"<p>{escape(message)}</p>")
