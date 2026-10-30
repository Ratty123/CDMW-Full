"""One bounded, cancellable reference-search batch."""

from __future__ import annotations

import threading

from PySide6.QtCore import QObject, Signal, Slot

from cdmw.core.archive_reverse_references import scan_reference_batch
from cdmw.models import RunCancelled


class ArchiveReferenceScanWorker(QObject):
    completed = Signal(int, object)
    failed = Signal(int, str)
    finished = Signal()

    def __init__(self, generation, target, entries):
        super().__init__()
        self.generation = generation
        self.target = target
        self.entries = tuple(entries)
        self.stop_event = threading.Event()

    def stop(self):
        self.stop_event.set()

    @Slot()
    def run(self):
        try:
            result = scan_reference_batch(self.target, self.entries, self.stop_event)
            if not self.stop_event.is_set():
                self.completed.emit(self.generation, result)
        except RunCancelled:
            pass
        except Exception as exc:
            if not self.stop_event.is_set():
                self.failed.emit(self.generation, str(exc))
        finally:
            self.finished.emit()
