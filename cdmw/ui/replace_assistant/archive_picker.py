"""Bounded standalone-catalogue picker for one archive original DDS."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from cdmw.domain.archives.catalogue import (
    ArchiveEntryDto,
    ArchivePage,
    ArchiveQuery,
    ArchiveQueryHandle,
    ArchiveSessionHandle,
    ArchiveSortField,
    ArchiveViewMode,
)
from cdmw.domain.archives.catalogue_operations import FetchPageRequest
from cdmw.services.archive_catalogue_service import ArchiveCatalogueService


class RemoteArchiveOriginalDialog(QDialog):
    """Query and show at most one page rather than copying the archive catalogue."""

    PAGE_SIZE = 500

    def __init__(
        self,
        service: ArchiveCatalogueService,
        session: ArchiveSessionHandle,
        *,
        initial_filter: str,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self._service = service
        self._session = session
        self._generation = 0
        self._requests: dict[str, tuple[str, int]] = {}
        self._closed = False
        self.selected_entry: ArchiveEntryDto | None = None

        self.setWindowTitle("Choose archive original DDS")
        self.resize(900, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        hint = QLabel(
            "Filter the standalone archive catalogue, then choose the original that matches the edited texture."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.filter_edit = QLineEdit(initial_filter)
        self.filter_edit.setPlaceholderText("Filter by basename or relative path...")
        layout.addWidget(self.filter_edit)

        self.results_list = QListWidget()
        self.results_list.setSelectionMode(QAbstractItemView.SingleSelection)
        layout.addWidget(self.results_list, stretch=1)

        self.status_label = QLabel("Querying archive catalogue...")
        self.status_label.setObjectName("HintLabel")
        layout.addWidget(self.status_label)

        button_row = QHBoxLayout()
        self.choose_button = QPushButton("Choose")
        cancel_button = QPushButton("Cancel")
        self.choose_button.setEnabled(False)
        button_row.addStretch(1)
        button_row.addWidget(self.choose_button)
        button_row.addWidget(cancel_button)
        layout.addLayout(button_row)

        self._query_timer = QTimer(self)
        self._query_timer.setSingleShot(True)
        self._query_timer.setInterval(120)
        self._query_timer.timeout.connect(self._start_query)
        self.filter_edit.textChanged.connect(lambda _text: self._query_timer.start())
        self.results_list.itemSelectionChanged.connect(self._update_choose_button)
        self.results_list.itemDoubleClicked.connect(lambda _item: self._accept_current())
        self.choose_button.clicked.connect(self._accept_current)
        cancel_button.clicked.connect(self.reject)

        service.result_ready.connect(self._handle_result)
        service.request_failed.connect(self._handle_failure)
        service.request_cancelled.connect(self._handle_cancelled)
        self._query_timer.start(0)
        self.filter_edit.selectAll()
        self.filter_edit.setFocus()

    def _cancel_requests(self) -> None:
        for request_id in tuple(self._requests):
            self._service.cancel(request_id)
        self._requests.clear()

    def _start_query(self) -> None:
        if self._closed:
            return
        self._generation += 1
        generation = self._generation
        self._cancel_requests()
        self.results_list.clear()
        self.choose_button.setEnabled(False)
        self.status_label.setText("Querying archive catalogue...")
        query = ArchiveQuery(
            session_id=self._session.session_id,
            include_text=self.filter_edit.text().strip() or None,
            extensions=(".dds",),
            view_mode=ArchiveViewMode.FLAT,
            sort_field=ArchiveSortField.PATH,
            sort_active=True,
        )
        try:
            request_id = self._service.create_query(query, ui_generation=generation)
        except Exception as exc:
            self.status_label.setText(str(exc))
            return
        self._requests[request_id] = ("query", generation)

    def _handle_result(self, request_id: str, operation: str, payload: object) -> None:
        tracked = self._requests.pop(request_id, None)
        if tracked is None or tracked[1] != self._generation:
            return
        kind, generation = tracked
        if kind == "query" and operation == "create_query" and isinstance(payload, ArchiveQueryHandle):
            try:
                page_request_id = self._service.fetch_page(
                    FetchPageRequest(payload.query_id, 0, self.PAGE_SIZE),
                    ui_generation=generation,
                )
            except Exception as exc:
                self.status_label.setText(str(exc))
                return
            self._requests[page_request_id] = ("page", generation)
            return
        if kind != "page" or operation != "fetch_page" or not isinstance(payload, ArchivePage):
            return
        for entry in payload.rows:
            item = QListWidgetItem(f"{entry.package} | {entry.path}")
            item.setData(Qt.UserRole, entry)
            self.results_list.addItem(item)
        if self.results_list.count():
            self.results_list.setCurrentRow(0)
        visible = len(payload.rows)
        suffix = " Narrow the filter to see omitted matches." if payload.total_matches > visible else ""
        self.status_label.setText(
            f"Showing {visible:,} of {payload.total_matches:,} matching DDS entr{'y' if payload.total_matches == 1 else 'ies'}.{suffix}"
        )
        self._update_choose_button()

    def _handle_failure(self, request_id: str, error: object) -> None:
        if self._requests.pop(request_id, None) is None:
            return
        self.status_label.setText(str(getattr(error, "message", "") or error or "Archive query failed."))

    def _handle_cancelled(self, request_id: str) -> None:
        self._requests.pop(request_id, None)

    def _update_choose_button(self) -> None:
        self.choose_button.setEnabled(self.results_list.currentItem() is not None)

    def _accept_current(self) -> None:
        current = self.results_list.currentItem()
        selected = current.data(Qt.UserRole) if current is not None else None
        if not isinstance(selected, ArchiveEntryDto):
            return
        self.selected_entry = selected
        self.accept()

    def done(self, result: int) -> None:
        if not self._closed:
            self._closed = True
            self._query_timer.stop()
            self._cancel_requests()
            for signal, slot in (
                (self._service.result_ready, self._handle_result),
                (self._service.request_failed, self._handle_failure),
                (self._service.request_cancelled, self._handle_cancelled),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
        super().done(result)


__all__ = ["RemoteArchiveOriginalDialog"]
